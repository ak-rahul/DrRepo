"""Process metrics in the Prometheus text format (served by `drrepo serve` at /metrics).

A small thread-safe registry of labelled counters, so no client library is
needed. `AnalysisService` records every analysis:

    drrepo_analyses_total{outcome}            finished analyses ("ok" or "error")
    drrepo_analysis_seconds_{sum,count}       wall time of finished analyses
    drrepo_collector_results_total{collector,status}
    drrepo_llm_tokens_total{label}            tokens by budget line (planner, investigation:security, ...)

The API adds gauges at scrape time (jobs by status, the LLM circuit breaker).
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any

_HELP = {
    "drrepo_analyses_total": ("counter", "Finished analyses by outcome."),
    "drrepo_analysis_seconds_sum": ("counter", "Total wall time of finished analyses."),
    "drrepo_analysis_seconds_count": ("counter", "Number of timed analyses."),
    "drrepo_collector_results_total": ("counter", "Collector results by collector and status."),
    "drrepo_llm_tokens_total": ("counter", "LLM tokens recorded by budget line."),
}

Labels = tuple[tuple[str, str], ...]


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _sample(name: str, labels: Labels, value: float) -> str:
    rendered = ",".join(f'{k}="{_escape(v)}"' for k, v in labels)
    number = int(value) if float(value).is_integer() else value
    return f"{name}{{{rendered}}} {number}" if rendered else f"{name} {number}"


class Metrics:
    def __init__(self) -> None:
        self._values: dict[str, dict[Labels, float]] = defaultdict(lambda: defaultdict(float))
        self._lock = threading.Lock()

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        with self._lock:
            self._values[name][key] += value

    def value(self, name: str, **labels: str) -> float:
        with self._lock:
            return self._values.get(name, {}).get(tuple(sorted(labels.items())), 0.0)

    def record_analysis(self, report: dict[str, Any], seconds: float) -> None:
        """Count one finished analysis: outcome, duration, collector statuses, tokens."""
        self.inc("drrepo_analyses_total", outcome="ok")
        self.inc("drrepo_analysis_seconds_sum", seconds)
        self.inc("drrepo_analysis_seconds_count")
        for collector, result in (report.get("collector_status") or {}).items():
            self.inc(
                "drrepo_collector_results_total",
                collector=collector,
                status=str((result or {}).get("status", "unknown")),
            )
        usage = report.get("llm_usage") or {}
        for label, tokens in (usage.get("by_label") or {}).items():
            if isinstance(tokens, (int, float)):
                self.inc("drrepo_llm_tokens_total", float(tokens), label=label)

    def render(self, gauges: dict[str, tuple[str, dict[Labels, float]]] | None = None) -> str:
        """The exposition text: every counter, plus `gauges` ({name: (help, {labels: value})})."""
        lines: list[str] = []
        with self._lock:
            snapshot = {name: dict(series) for name, series in self._values.items()}
        for name in sorted(snapshot):
            kind, help_text = _HELP.get(name, ("counter", name))
            lines += [f"# HELP {name} {help_text}", f"# TYPE {name} {kind}"]
            lines += [_sample(name, labels, v) for labels, v in sorted(snapshot[name].items())]
        for name, (help_text, series) in sorted((gauges or {}).items()):
            lines += [f"# HELP {name} {help_text}", f"# TYPE {name} gauge"]
            lines += [_sample(name, labels, v) for labels, v in sorted(series.items())]
        return "\n".join(lines) + "\n"

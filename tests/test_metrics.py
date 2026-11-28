"""Prometheus metrics and JSON logs."""

import json
import logging

from drrepo.log import JsonFormatter
from drrepo.metrics import Metrics


def test_record_analysis_and_render():
    metrics = Metrics()
    report = {
        "collector_status": {"security": {"status": "ok"}, "scorecard": {"status": "skipped"}},
        "llm_usage": {"by_label": {"planner": 900, "investigation:security": 4100}},
    }
    metrics.record_analysis(report, 12.5)
    metrics.record_analysis(report, 7.5)
    metrics.inc("drrepo_analyses_total", outcome="error")
    text = metrics.render({"drrepo_jobs": ("Jobs.", {(("status", "queued"),): 3.0})})
    assert 'drrepo_analyses_total{outcome="ok"} 2' in text
    assert 'drrepo_analyses_total{outcome="error"} 1' in text
    assert "drrepo_analysis_seconds_sum 20" in text and "drrepo_analysis_seconds_count 2" in text
    assert 'drrepo_collector_results_total{collector="scorecard",status="skipped"} 2' in text
    assert 'drrepo_llm_tokens_total{label="investigation:security"} 8200' in text
    assert "# TYPE drrepo_jobs gauge" in text and 'drrepo_jobs{status="queued"} 3' in text


def test_label_values_are_escaped():
    metrics = Metrics()
    metrics.inc("drrepo_llm_tokens_total", 1, label=r'a"b\c')
    assert 'label="a\\"b\\\\c"' in metrics.render()  # quote and backslash escaped


def test_json_log_lines():
    record = logging.LogRecord(
        "drrepo", logging.WARNING, __file__, 1, "clone %s failed", ("x",), None
    )
    entry = json.loads(JsonFormatter().format(record))
    assert entry["level"] == "WARNING" and entry["message"] == "clone x failed"
    assert entry["logger"] == "drrepo" and entry["timestamp"].endswith("+00:00")

"""Logging for DrRepo.

Importing this module has no side effects beyond creating the named logger:
no directories are created and no handlers are attached. Entrypoints (CLI,
Streamlit app, REST API) call `configure_logging()` once with the configured
level and format. Library code just does `from drrepo.log import logger`.

`LOG_FORMAT=json` writes one JSON object per line (`timestamp`, `level`,
`logger`, `message`, plus `exception` when there is one), for log shippers.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

LOGGER_NAME = "drrepo"
_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

logger = logging.getLogger(LOGGER_NAME)
# Without a handler, records below WARNING would be dropped by Python's
# last-resort handler until an entrypoint configures logging. That's the right
# behavior for library use, so just stop records reaching the root logger twice.
logger.propagate = False
logger.addHandler(logging.NullHandler())


class JsonFormatter(logging.Formatter):
    """One JSON object per record, so log pipelines can parse fields instead of text."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "thread": record.threadName,
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def _level(name: str | None, default: int = logging.INFO) -> int:
    value = logging.getLevelName((name or "").upper())
    return value if isinstance(value, int) else default


def configure_logging(
    level: str = "INFO",
    log_file: str | Path | None = "logs/app.log",
    console_level: str | None = None,
    fmt: str = "text",
) -> None:
    """Attach a stderr console handler (and optionally a file handler) to the DrRepo logger.

    `level` applies to the file; `console_level` (default: same as `level`) lets
    the CLI keep the terminal quiet while still logging everything to disk.
    Safe to call repeatedly (e.g. on every Streamlit rerun): handlers are
    replaced, never duplicated. Console output goes to stderr, which keeps
    stdout clean for `--json` output.
    """
    numeric_level = _level(level)
    numeric_console = _level(console_level, numeric_level) if console_level else numeric_level

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter: logging.Formatter = (
        JsonFormatter() if fmt == "json" else logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)
    )

    console = logging.StreamHandler()  # stderr
    console.setLevel(numeric_console)
    console.setFormatter(formatter)
    logger.addHandler(console)

    if log_file:
        path = Path(log_file)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(path, encoding="utf-8")
        except OSError as e:
            logger.warning(f"Could not open log file {path}: {e}; logging to console only")
        else:
            file_handler.setFormatter(formatter)
            file_handler.setLevel(numeric_level)
            logger.addHandler(file_handler)

    logger.setLevel(min(numeric_level, numeric_console))

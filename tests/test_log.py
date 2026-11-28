import json
import logging

from drrepo.log import configure_logging, logger


class TestLogging:
    def test_configure_is_idempotent_and_honors_levels(self, tmp_path):
        log_file = tmp_path / "logs" / "app.log"
        configure_logging("DEBUG", log_file=log_file, console_level="WARNING")
        configure_logging("DEBUG", log_file=log_file, console_level="WARNING")
        try:
            assert len(logger.handlers) == 2
            console, file_handler = logger.handlers
            assert console.level == logging.WARNING
            assert file_handler.level == logging.DEBUG
            logger.debug("hello file")
            file_handler.flush()
            assert "hello file" in log_file.read_text(encoding="utf-8")
        finally:
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()

    def test_unknown_level_defaults_to_info(self):
        configure_logging("NOPE", log_file=None)
        try:
            assert logger.level == logging.INFO
        finally:
            for handler in list(logger.handlers):
                logger.removeHandler(handler)


def test_json_log_lines():
    from drrepo.log import JsonFormatter

    record = logging.LogRecord(
        "drrepo", logging.WARNING, __file__, 1, "clone %s failed", ("x",), None
    )
    entry = json.loads(JsonFormatter().format(record))
    assert entry["level"] == "WARNING" and entry["message"] == "clone x failed"
    assert entry["logger"] == "drrepo" and entry["timestamp"].endswith("+00:00")

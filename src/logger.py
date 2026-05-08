import os
import sys
import logging
import logging.handlers
import queue
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_LOG_DIR = Path.home() / ".yt2tiktok" / "logs"
_APP_LOG = _LOG_DIR / "app.log"
_ERR_LOG = _LOG_DIR / "errors.log"

# ---------------------------------------------------------------------------
# Queue that GUI components can poll for log messages
# ---------------------------------------------------------------------------
gui_log_queue: queue.Queue = queue.Queue()


# ---------------------------------------------------------------------------
# Custom handler that writes formatted records into gui_log_queue
# ---------------------------------------------------------------------------
class QueueHandler(logging.Handler):
    """Puts formatted log messages (INFO and above) into gui_log_queue."""

    def __init__(self, log_queue: queue.Queue, level: int = logging.INFO) -> None:
        super().__init__(level)
        self._queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._queue.put_nowait(msg)
        except Exception:
            self.handleError(record)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup_logging() -> logging.Logger:
    """Configure the root logger with rotating file, error-only, and queue
    handlers.  Returns the root logger.  Safe to call multiple times — extra
    calls are no-ops once handlers are attached."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()

    # Only configure once.
    if root.handlers:
        return root

    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    # -- Rotating app log (all levels DEBUG+) --------------------------------
    file_handler = logging.handlers.RotatingFileHandler(
        _APP_LOG,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # -- Rotating error log (ERROR+ only) ------------------------------------
    error_handler = logging.handlers.RotatingFileHandler(
        _ERR_LOG,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(fmt)
    root.addHandler(error_handler)

    # -- GUI queue handler (INFO+) -------------------------------------------
    queue_handler = QueueHandler(gui_log_queue, level=logging.INFO)
    queue_handler.setFormatter(fmt)
    root.addHandler(queue_handler)

    return root


def get_logger(name: str) -> logging.Logger:
    """Return a named logger.  Ensures the root logger is configured first."""
    setup_logging()
    return logging.getLogger(name)


def install_crash_handler() -> None:
    """Override sys.excepthook to log unhandled exceptions to the error log."""
    setup_logging()
    _error_logger = logging.getLogger("crash")

    def _excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            # Let KeyboardInterrupt through without logging.
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        _error_logger.critical(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_tb),
        )

    sys.excepthook = _excepthook

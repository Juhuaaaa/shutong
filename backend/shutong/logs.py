"""The ``shutong`` log: a rotating file under the data dir plus the newest records in memory for the web page."""
from collections import deque
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import threading
from typing import Dict, List, Optional, Tuple

LOGGER = "shutong"
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
FILE_NAME = "shutong.log"
_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"


class LogBuffer(logging.Handler):
    """The newest records, numbered so a page can ask for what came after the last one it showed."""

    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self._entries: deque = deque(maxlen=capacity)
        self._seq = 0
        self._guard = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if record.exc_info:
            message += "\n" + logging.Formatter().formatException(record.exc_info)
        with self._guard:
            self._seq += 1
            self._entries.append({
                "seq": self._seq, "at": datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="seconds"),
                "level": record.levelname, "logger": record.name, "message": message,
            })

    def since(self, after: int, *, level: Optional[str] = None, query: Optional[str] = None,
              limit: int = 500) -> Tuple[List[Dict], int]:
        floor = logging.getLevelName(level) if level in LEVELS else logging.NOTSET
        needle = (query or "").casefold()
        with self._guard:
            found = [entry for entry in self._entries if entry["seq"] > after
                     and logging.getLevelName(entry["level"]) >= floor
                     and (not needle or needle in entry["message"].casefold())]
            return found[-limit:], self._seq


_handlers: Dict[Path, LogBuffer] = {}


def setup_logging(data_dir: Path, level: str = "INFO", *, console: bool = False) -> LogBuffer:
    """Attach the file and memory handlers once per data dir; later calls only return the buffer.

    ``console`` also prints to stderr (``shutong serve``: shows up in ``docker logs``).
    """
    data_dir = Path(data_dir).resolve()
    logger = logging.getLogger(LOGGER)
    if data_dir in _handlers:
        return _handlers[data_dir]
    logs = data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(logs / FILE_NAME, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    buffer = LogBuffer()
    handlers: List[logging.Handler] = [file_handler, buffer]
    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter(_FORMAT))
        handlers.append(stream)
    for handler in handlers:
        logger.addHandler(handler)
    _handlers[data_dir] = buffer
    set_level(level)
    return buffer


def set_level(level: str) -> None:
    logging.getLogger(LOGGER).setLevel(level if level in LEVELS else "INFO")


def log_file(data_dir: Path) -> Path:
    return Path(data_dir) / "logs" / FILE_NAME


def shutdown_logging(data_dir: Path) -> None:
    """Detach the handlers set up for ``data_dir`` (tests make many short-lived apps)."""
    data_dir = Path(data_dir).resolve()
    buffer = _handlers.pop(data_dir, None)
    if buffer is None:
        return
    logger = logging.getLogger(LOGGER)
    target = str(log_file(data_dir))
    for handler in list(logger.handlers):
        if handler is buffer or getattr(handler, "baseFilename", None) == target:
            logger.removeHandler(handler)
            handler.close()

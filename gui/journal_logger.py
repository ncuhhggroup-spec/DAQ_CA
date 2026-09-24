import logging
import sys
from pathlib import Path
from PySide6.QtWidgets import QTextEdit
from PySide6.QtCore import Qt

# Ensure the log directory exists
log_path = Path(__file__).resolve().parent.parent / "experiment_journal.log"
log_path.parent.mkdir(parents=True, exist_ok=True)

class QTextEditHandler(logging.Handler):
    """A logging handler that appends log records to a QTextEdit widget.

    The handler expects a reference to a QTextEdit instance via ``set_widget``.
    It formats the record using the logger's formatter and appends it to the
    widget in a thread‑safe manner using ``Qt.CallLater``.
    """

    def __init__(self, level=logging.NOTSET):
        super().__init__(level)
        self._widget: QTextEdit | None = None

    def set_widget(self, widget: QTextEdit) -> None:
        self._widget = widget
        # Ensure the widget is read‑only and uses a monospaced font.
        widget.setReadOnly(True)
        widget.setLineWrapMode(QTextEdit.NoWrap)

    def emit(self, record: logging.LogRecord) -> None:
        if self._widget is None:
            # If no widget is attached, just ignore – fall back to file logging.
            return
        msg = self.format(record)
        # Use Qt's thread‑safe signal to append text.
        def append():
            self._widget.moveCursor(Qt.TextCursor.End)
            self._widget.insertPlainText(msg + "\n")
            self._widget.ensureCursorVisible()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, append)

def get_logger(name: str = "gui_logger") -> logging.Logger:
    """Create (or retrieve) a logger configured with both a file handler and
    a ``QTextEditHandler``. The file handler writes to ``experiment_journal.log``
    in the repository root, while the widget handler can be attached by the
    GUI at runtime.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    # File handler – persistent on disk.
    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    file_formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # QTextEdit handler – will be attached later by the GUI.
    qt_handler = QTextEditHandler()
    qt_formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    qt_handler.setFormatter(qt_formatter)
    logger.addHandler(qt_handler)

    logger.propagate = False
    return logger

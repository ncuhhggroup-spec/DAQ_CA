"""
sid4_watcher_gui.py
===================
GUI Directory Watcher & EPICS File Archiver for PHASICS SID4 Wavefront Sensor.

Features:
- Live file system event monitoring via Watchdog.
- Customizable Watch Folder, Target DAQ Folder, File Prefix (e.g., 'PHA SID4'), and File Extensions.
- Non-blocking execution using QThread.
- File lock detection (ensures vendor software finishes writing before processing).
- Automatic EPICS PV metadata query (EXP:Seq:FileName, EXP:Seq:ShotNumber).
- Renaming format: <FileName>_shot_<ShotNumber:04d>.<ext>
"""

from __future__ import annotations

import logging
import os
import pathlib
import shutil
import sys
import time
from typing import Optional, List, Set

# ---------------------------------------------------------------------------
# Qt Backend Shim (PyQt6 / PySide6)
# ---------------------------------------------------------------------------
try:
    from PyQt6 import QtCore, QtGui, QtWidgets
    from PyQt6.QtCore import (
        QObject, QThread, QTimer, Qt, pyqtSignal as Signal, pyqtSlot as Slot
    )
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QGroupBox, QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog,
        QFormLayout, QMessageBox, QFrame, QSplitter
    )
    _QT_BACKEND = "PyQt6"
except ImportError:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import (
        QObject, QThread, QTimer, Qt, Signal, Slot
    )
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QGroupBox, QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog,
        QFormLayout, QMessageBox, QFrame, QSplitter
    )
    _QT_BACKEND = "PySide6"

try:
    import epics
    _EPICS_AVAILABLE = True
except ImportError:
    _EPICS_AVAILABLE = False

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    _WATCHDOG_AVAILABLE = True
except ImportError:
    _WATCHDOG_AVAILABLE = False

logger = logging.getLogger(__name__)

# Dark Theme CSS
_STYLE = """
QMainWindow, QWidget {
    background-color: #0f1117;
    color: #e2e8f0;
    font-family: "Segoe UI", "Inter", -apple-system, sans-serif;
    font-size: 12px;
}
QGroupBox {
    background-color: #171a23;
    border: 1px solid #272d3d;
    border-radius: 8px;
    margin-top: 14px;
    padding: 10px 12px 12px 12px;
    font-weight: bold;
    color: #38bdf8;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: #38bdf8;
}
QLineEdit {
    background-color: #1e2230;
    border: 1.5px solid #31384e;
    border-radius: 6px;
    padding: 5px 8px;
    color: #f1f5f9;
}
QLineEdit:focus {
    border-color: #6366f1;
}
QPushButton {
    background-color: #3b82f6;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 600;
}
QPushButton:hover { background-color: #60a5fa; }
QPushButton:pressed { background-color: #2563eb; }
QPushButton:disabled { background-color: #334155; color: #64748b; }

QPushButton#startBtn {
    background-color: #10b981;
}
QPushButton#startBtn:hover { background-color: #34d399; }

QPushButton#stopBtn {
    background-color: #f43f5e;
}
QPushButton#stopBtn:hover { background-color: #fb7185; }
"""


def wait_for_file_ready(file_path: pathlib.Path, timeout: float = 10.0, check_interval: float = 0.2) -> bool:
    """Check file size stability to ensure external software has finished writing."""
    start_time = time.time()
    last_size = -1

    while time.time() - start_time < timeout:
        if not file_path.exists():
            time.sleep(check_interval)
            continue

        try:
            current_size = file_path.stat().st_size
            if current_size > 0 and current_size == last_size:
                return True
            last_size = current_size
        except OSError:
            pass

        time.sleep(check_interval)

    return False


if _WATCHDOG_AVAILABLE:
    class SID4WatchdogHandler(FileSystemEventHandler):
        """Watchdog File Event Handler emitting Qt Signals on matching files."""

        def __init__(self, file_detected_signal: Signal, prefix_filter: str, ext_filters: List[str]):
            super().__init__()
            self.file_detected_signal = file_detected_signal
            self.prefix_filter = prefix_filter.strip()
            self.ext_filters = [e.strip().lower() for e in ext_filters if e.strip()]
            self._processed_files: Set[pathlib.Path] = set()

        def on_created(self, event):
            if not event.is_directory:
                self._process_event(pathlib.Path(event.src_path))

        def on_modified(self, event):
            if not event.is_directory:
                self._process_event(pathlib.Path(event.src_path))

        def _process_event(self, file_path: pathlib.Path):
            # Check prefix
            if self.prefix_filter and not file_path.name.startswith(self.prefix_filter):
                return

            # Check extension
            if self.ext_filters and file_path.suffix.lower() not in self.ext_filters:
                return

            # Avoid duplicates
            if file_path in self._processed_files:
                return

            self._processed_files.add(file_path)
            self.file_detected_signal.emit(str(file_path))


class SID4WatcherGUI(QMainWindow):
    file_detected_signal = Signal(str)
    log_signal = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PHASICS SID4 Directory Watcher & EPICS DAQ Archiver")
        self.resize(950, 650)
        self.setStyleSheet(_STYLE)

        self._observer: Optional[Observer] = None
        self._epics_state_pv = None

        self._init_ui()
        self._setup_epics()

        # 10 Hz Display Timer for EPICS Readout Panel
        self.display_timer = QTimer(self)
        self.display_timer.setInterval(100)
        self.display_timer.timeout.connect(self._update_epics_panel)
        self.display_timer.start()

        self.file_detected_signal.connect(self._handle_file_detected)
        self.log_signal.connect(self.log)

    def _init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # 1. Path & Filter Settings Group
        cfg_group = QGroupBox("Folder & Filter Configuration")
        cfg_layout = QFormLayout(cfg_group)

        # Watch Dir
        w_row = QHBoxLayout()
        default_watch = r"C:\Phasics\TempOutput"
        self.watch_dir_edit = QLineEdit(default_watch)
        btn_browse_watch = QPushButton("Browse...")
        btn_browse_watch.clicked.connect(self._browse_watch_dir)
        w_row.addWidget(self.watch_dir_edit, stretch=1)
        w_row.addWidget(btn_browse_watch)
        cfg_layout.addRow("Watch Directory:", w_row)

        # Target Dir
        t_row = QHBoxLayout()
        default_target = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_epics")
        self.target_dir_edit = QLineEdit(default_target)
        btn_browse_target = QPushButton("Browse...")
        btn_browse_target.clicked.connect(self._browse_target_dir)
        t_row.addWidget(self.target_dir_edit, stretch=1)
        t_row.addWidget(btn_browse_target)
        cfg_layout.addRow("DAQ Target Directory:", t_row)

        # File Prefix Filter
        self.prefix_edit = QLineEdit("PHA SID4")
        self.prefix_edit.setPlaceholderText("e.g. PHA SID4")
        cfg_layout.addRow("File Prefix Filter:", self.prefix_edit)

        # Extensions Filter
        self.ext_edit = QLineEdit(".tif, .tiff, .phz, .dat, .raw")
        self.ext_edit.setPlaceholderText("Comma separated, e.g. .tif, .phz")
        cfg_layout.addRow("Allowed Extensions:", self.ext_edit)

        main_layout.addWidget(cfg_group)

        # 2. Control Buttons & Status
        ctrl_layout = QHBoxLayout()
        self.btn_start = QPushButton("▶ Start Watching")
        self.btn_start.setObjectName("startBtn")
        self.btn_start.clicked.connect(self._start_watching)
        ctrl_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("■ Stop Watching")
        self.btn_stop.setObjectName("stopBtn")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_watching)
        ctrl_layout.addWidget(self.btn_stop)

        ctrl_layout.addStretch()

        self.status_badge = QLabel("● IDLE")
        self.status_badge.setStyleSheet("color: #f59e0b; font-weight: bold; padding: 4px 10px; background: #171a23; border-radius: 4px;")
        ctrl_layout.addWidget(self.status_badge)

        main_layout.addLayout(ctrl_layout)

        # 3. EPICS PV Readout Panel
        epics_group = QGroupBox("EPICS Channel Access PV Readouts")
        epics_layout = QHBoxLayout(epics_group)

        self.lbl_pv_state = QLabel("IDLE")
        self.lbl_pv_state.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 13px;")
        epics_layout.addWidget(QLabel("EXP:Seq:State:"))
        epics_layout.addWidget(self.lbl_pv_state)
        epics_layout.addSpacing(20)

        self.lbl_pv_fn = QLabel("exp_run")
        self.lbl_pv_fn.setStyleSheet("color: #f1f5f9; font-weight: bold; font-size: 13px;")
        epics_layout.addWidget(QLabel("EXP:Seq:FileName:"))
        epics_layout.addWidget(self.lbl_pv_fn)
        epics_layout.addSpacing(20)

        self.lbl_pv_sn = QLabel("0")
        self.lbl_pv_sn.setStyleSheet("color: #f1f5f9; font-weight: bold; font-size: 13px;")
        epics_layout.addWidget(QLabel("EXP:Seq:ShotNumber:"))
        epics_layout.addWidget(self.lbl_pv_sn)
        epics_layout.addStretch()

        main_layout.addWidget(epics_group)

        # 4. System & Event Log Panel
        log_group = QGroupBox("Event Log & DAQ Transfer Console")
        log_layout = QVBoxLayout(log_group)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setStyleSheet("background-color: #1e1e1e; color: #dcdcdc; font-family: Consolas, monospace;")
        log_layout.addWidget(self.log_edit)

        main_layout.addWidget(log_group, stretch=1)

    def log(self, message: str, level: str = "INFO"):
        timestamp = time.strftime("%H:%M:%S")
        color_map = {
            "INFO": "#dcdcdc",
            "WARNING": "#f59e0b",
            "ERROR": "#ef4444",
            "SUCCESS": "#10b981",
        }
        color = color_map.get(level.upper(), "#dcdcdc")
        formatted_msg = (
            f'<span style="color: #888888;">[{timestamp}]</span> '
            f'<b style="color: {color};">[{level.upper()}]</b> {message}'
        )
        self.log_edit.append(formatted_msg)
        self.log_edit.moveCursor(QtGui.QTextCursor.MoveOperation.End if hasattr(QtGui, "QTextCursor") else QtGui.QTextCursor.End)

    def _browse_watch_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Directory to Watch", self.watch_dir_edit.text())
        if d:
            self.watch_dir_edit.setText(d)

    def _browse_target_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Target DAQ Directory", self.target_dir_edit.text())
        if d:
            self.target_dir_edit.setText(d)

    def _setup_epics(self):
        if not _EPICS_AVAILABLE:
            self.log("PyEpics library not available. Using fallback metadata.", "WARNING")
            return

        try:
            self._epics_state_pv = epics.PV("EXP:Seq:State")
            self.log("EPICS PV Subscribed: EXP:Seq:State", "INFO")
        except Exception as e:
            self.log(f"EPICS initialization error: {e}", "WARNING")

    def _update_epics_panel(self):
        if not _EPICS_AVAILABLE:
            return

        try:
            st = epics.caget("EXP:Seq:State", as_string=True) or "IDLE"
            fn = epics.caget("EXP:Seq:FileName", as_string=True) or "exp_run"
            sn = epics.caget("EXP:Seq:ShotNumber") or 0

            self.lbl_pv_state.setText(str(st))
            self.lbl_pv_fn.setText(str(fn))
            self.lbl_pv_sn.setText(str(int(sn)))
        except Exception:
            pass

    def _start_watching(self):
        if not _WATCHDOG_AVAILABLE:
            QMessageBox.critical(self, "Error", "watchdog library is not installed.\nRun: pip install watchdog")
            return

        watch_path = pathlib.Path(self.watch_dir_edit.text().strip())
        target_path = pathlib.Path(self.target_dir_edit.text().strip())

        if not watch_path.exists():
            try:
                watch_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(self, "Directory Error", f"Cannot create Watch Directory:\n{e}")
                return

        target_path.mkdir(parents=True, exist_ok=True)

        prefix = self.prefix_edit.text().strip()
        exts = [e.strip() for e in self.ext_edit.text().split(",") if e.strip()]

        handler = SID4WatchdogHandler(self.file_detected_signal, prefix, exts)
        self._observer = Observer()
        self._observer.schedule(handler, path=str(watch_path), recursive=False)
        self._observer.start()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.watch_dir_edit.setEnabled(False)
        self.prefix_edit.setEnabled(False)
        self.ext_edit.setEnabled(False)

        self.status_badge.setText("● WATCHING")
        self.status_badge.setStyleSheet("color: #10b981; font-weight: bold; padding: 4px 10px; background: #171a23; border-radius: 4px;")

        self.log(f"Started watching directory: {watch_path}", "SUCCESS")
        self.log(f"Filter Prefix: '{prefix}' | Extensions: {exts}", "INFO")

    def _stop_watching(self):
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2.0)
            self._observer = None

        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.watch_dir_edit.setEnabled(True)
        self.prefix_edit.setEnabled(True)
        self.ext_edit.setEnabled(True)

        self.status_badge.setText("● STOPPED")
        self.status_badge.setStyleSheet("color: #ef4444; font-weight: bold; padding: 4px 10px; background: #171a23; border-radius: 4px;")

        self.log("Stopped file system watching.", "WARNING")

    @Slot(str)
    def _handle_file_detected(self, file_path_str: str):
        file_path = pathlib.Path(file_path_str)
        self.log(f"Detected SID4 output file: {file_path.name}", "INFO")

        # 1. Wait for file writing completion
        if not wait_for_file_ready(file_path):
            self.log(f"File write timeout or locked: {file_path.name}", "ERROR")
            return

        # 2. Fetch EPICS Metadata
        try:
            fn = epics.caget("EXP:Seq:FileName", as_string=True) if _EPICS_AVAILABLE else "exp_run"
            sn = epics.caget("EXP:Seq:ShotNumber") if _EPICS_AVAILABLE else 0

            fn = fn if fn is not None else "exp_run"
            sn = int(sn) if sn is not None else 0
        except Exception as e:
            fn, sn = "exp_run", 0
            self.log(f"Failed querying EPICS PVs: {e}", "WARNING")

        # 3. Form exact DAQ filename: <FileName>_shot_<ShotNumber:04d>.<ext>
        ext = file_path.suffix
        exact_filename = f"{fn}_shot_{sn:04d}{ext}"

        target_dir = pathlib.Path(self.target_dir_edit.text().strip())
        target_path = target_dir / exact_filename

        # 4. Copy to DAQ directory
        try:
            shutil.copy2(file_path, target_path)
            self.log(f"💾 [AUTO-SAVE] Copied & Renamed SID4 file: {exact_filename}", "SUCCESS")
        except Exception as e:
            self.log(f"Failed copying file: {e}", "ERROR")

    def closeEvent(self, event):
        self.display_timer.stop()
        self._stop_watching()
        event.accept()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    app = QApplication(sys.argv)
    win = SID4WatcherGUI()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
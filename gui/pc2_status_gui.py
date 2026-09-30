#!/usr/bin/env python3
"""
gui/pc2_status_gui.py
======================
Local status‑monitor GUI for the PC_2 IOC.

- Shows live CameraStatus (colored), ShotNumber and FileName.
- All EPICS network I/O runs in a background QThread to keep the UI responsive.
- Uses PyEpics to monitor the four PVs.

Usage:
    python gui/pc2_status_gui.py
"""

import sys
import asyncio
from typing import Any

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QVBoxLayout,
    QFormLayout,
    QTextEdit,
)
from PySide6.QtCore import Qt, Signal, QThread

# ---------------------------------------------------------------------
class StatusWorker(QThread):
    """Background worker that monitors PVs using PyEpics camonitor.

    Emits Qt signals for UI updates and logs events.
    """
    # Qt signals
    cameraStatusChanged = Signal(str)
    shotNumberChanged = Signal(int)
    fileNameChanged = Signal(str)
    logMessage = Signal(str)  # simple text log
    connectionLost = Signal(str)

    def __init__(self, prefix: str = "EXP:Seq:"):
        super().__init__()
        self.prefix = prefix.rstrip(":") + ":"
        self._running = True
        self.monitors = []

    def run(self) -> None:
        import epics
        try:
            # Define PV names
            pv_status = f"{self.prefix}CameraStatus"
            pv_shot = f"{self.prefix}ShotNumber"
            pv_file = f"{self.prefix}FileName"

            def _decode(val):
                if isinstance(val, (bytes, bytearray)):
                    return val.decode('utf-8', errors='ignore').rstrip('\x00')
                return str(val).rstrip('\x00')

            def _on_camera_status(pvname=None, value=None, char_value=None, **kw):
                decoded = _decode(char_value if char_value is not None else value)
                self.cameraStatusChanged.emit(decoded)
                self.logMessage.emit(f"CameraStatus updated: {decoded}")

            def _on_shot_number(pvname=None, value=None, **kw):
                if value is not None:
                    try:
                        num = int(value)
                        self.shotNumberChanged.emit(num)
                        self.logMessage.emit(f"ShotNumber updated: {num}")
                    except Exception:
                        pass

            def _on_file_name(pvname=None, value=None, char_value=None, **kw):
                decoded = _decode(char_value if char_value is not None else value)
                self.fileNameChanged.emit(decoded)
                self.logMessage.emit(f"FileName updated: {decoded}")

            # Set up camonitors
            epics.camonitor(pv_status, callback=_on_camera_status)
            epics.camonitor(pv_shot, callback=_on_shot_number)
            epics.camonitor(pv_file, callback=_on_file_name)

            self.monitors = [pv_status, pv_shot, pv_file]

            # Emit initial values using caget
            try:
                init_status = epics.caget(pv_status, as_string=True, timeout=2.0)
                self.cameraStatusChanged.emit(_decode(init_status))
                init_shot = epics.caget(pv_shot, timeout=2.0)
                if init_shot is not None:
                    self.shotNumberChanged.emit(int(init_shot))
                init_file = epics.caget(pv_file, as_string=True, timeout=2.0)
                self.fileNameChanged.emit(_decode(init_file))
                self.logMessage.emit("Initial PV values fetched.")
            except Exception:
                pass

            while self._running:
                self.msleep(200)

        except Exception as exc:
            self.connectionLost.emit(str(exc))
            self.logMessage.emit(f"Error in StatusWorker: {exc}")
        finally:
            for pv in self.monitors:
                try:
                    epics.camonitor_clear(pv)
                except Exception:
                    pass
            self.monitors.clear()
    def stop(self):
        self._running = False
        self.quit()
        self.wait()

# ---------------------------------------------------------------------
# Main GUI window
# ---------------------------------------------------------------------
class StatusWindow(QWidget):
    def __init__(self, prefix: str = "EXP:Seq:"):
        super().__init__()
        self.setWindowTitle("PC2 – DAQ Status Monitor")
        self.resize(300, 150)

        # UI Elements
        self.lbl_status = QLabel("---")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setStyleSheet("background-color: gray; color: white; font-weight: bold;")
        self.lbl_shot = QLabel("0")
        self.lbl_file = QLabel("---")

        form = QFormLayout()
        form.addRow("Camera Status:", self.lbl_status)
        form.addRow("Shot Number:", self.lbl_shot)
        form.addRow("File Name:", self.lbl_file)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.log_box)
        self.setLayout(layout)

        # Worker setup
        self.worker = StatusWorker(prefix)
        self.worker.cameraStatusChanged.connect(self.update_status)
        self.worker.shotNumberChanged.connect(self.update_shot)
        self.worker.fileNameChanged.connect(self.update_file)
        self.worker.logMessage.connect(self.append_log)
        self.worker.connectionLost.connect(self.handle_error)
        self.worker.start()

    # -----------------------------------------------------------------
    # Slot implementations
    # -----------------------------------------------------------------
    def update_status(self, text: str):
        self.lbl_status.setText(text)
        # colour coding
        colour = {
            "IDLE": "#4caf50",          # green
            "ACTIVATING": "#ff9800",   # orange
            "ERROR": "#f44336",        # red
        }.get(text.upper(), "gray")
        self.lbl_status.setStyleSheet(f"background-color: {colour}; color: white; font-weight: bold;")

    def update_shot(self, number: int):
        self.lbl_shot.setText(str(number))

    def update_file(self, name: str):
        self.lbl_file.setText(name)

    def handle_error(self, msg: str):
        self.lbl_status.setText("DISCONNECTED")
        self.lbl_status.setStyleSheet("background-color: #9e9e9e; color: white; font-weight: bold;")
        self.append_log(f"[ERROR] Connection error: {msg}")

    def append_log(self, text: str):
        self.log_box.append(text)

    def closeEvent(self, event):  # pragma: no‑cover – UI cleanup
        self.worker.stop()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    win = StatusWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

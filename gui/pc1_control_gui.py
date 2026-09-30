#!/usr/bin/env python3
"""
gui/pc1_control_gui.py
======================
Remote control GUI for the PC_1 client using PyEpics.

Features:
- Server IP configuration (sets EPICS_CA_ADDR_LIST and re-initializes libca).
- Target filename entry.
- Live read-out of CameraStatus, ShotNumber, and FileName via epics.camonitor.
- ARM and FIRE (Single Shot) buttons respecting interlock (disabled when CameraStatus != "IDLE").
- Log box for user feedback.

Usage:
    python gui/pc1_control_gui.py
"""

import sys
import os
from typing import Any

import epics

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QFormLayout,
    QVBoxLayout,
    QHBoxLayout,
)
from PySide6.QtCore import Qt, Signal, QThread, Slot


# ---------------------------------------------------------------------
# Worker thread handling EPICS communication using PyEpics.
# ---------------------------------------------------------------------
class ControlWorker(QThread):
    """Background worker for the PC_1 control client using PyEpics.

    It provides:
    * Continuous monitoring of CameraStatus, ShotNumber, and FileName.
    * Methods to write FileName, trigger Arm, and single-shot fire using epics.caput / epics.caget.
    * Qt signals to push updates to the UI thread safely.
    """

    # Signals emitted to the GUI thread
    cameraStatusChanged = Signal(str)
    shotNumberChanged = Signal(int)
    fileNameChanged = Signal(str)
    operationFinished = Signal(bool, str)  # success, message
    connectionLost = Signal(str)

    def __init__(self, prefix: str = "EXP:Seq:", server_ip: str | None = None):
        super().__init__()
        self.prefix = prefix.rstrip(":") + ":"
        self.server_ip = server_ip
        self._running = True
        self.monitors = []
        self._setup_env()

    def _setup_env(self) -> None:
        """Configure EPICS CA environment variables and re-initialize libca."""
        if self.server_ip:
            os.environ["EPICS_CA_ADDR_LIST"] = self.server_ip
            os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"
        else:
            os.environ.pop("EPICS_CA_ADDR_LIST", None)
            os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "YES"

        try:
            epics.ca.initialize_libca()
        except Exception as exc:
            self.connectionLost.emit(f"Failed to initialize EPICS CA lib: {exc}")

    @staticmethod
    def _decode_val(val: Any) -> str:
        """Helper to decode bytes or string responses."""
        if val is None:
            return ""
        if isinstance(val, (bytes, bytearray)):
            return val.decode("utf-8", errors="ignore").rstrip("\x00")
        if isinstance(val, (list, tuple)):
            if len(val) > 0 and isinstance(val[0], int):
                return bytes(val).decode("utf-8", errors="ignore").rstrip("\x00")
            return "".join(str(x) for x in val).rstrip("\x00")
        return str(val).rstrip("\x00")

    # -----------------------------------------------------------------
    # Callback functions for epics.camonitor
    # -----------------------------------------------------------------
    def _on_camera_status(self, pvname=None, value=None, char_value=None, **kwargs):
        val = char_value if char_value is not None else value
        decoded = self._decode_val(val)
        self.cameraStatusChanged.emit(decoded)

    def _on_shot_number(self, pvname=None, value=None, **kwargs):
        if value is not None:
            try:
                self.shotNumberChanged.emit(int(value))
            except (ValueError, TypeError):
                pass

    def _on_file_name(self, pvname=None, value=None, char_value=None, **kwargs):
        val = char_value if char_value is not None else value
        decoded = self._decode_val(val)
        self.fileNameChanged.emit(decoded)

    # -----------------------------------------------------------------
    # Public Slots called from the GUI
    # -----------------------------------------------------------------
    @Slot(str)
    def set_target_file(self, name: str) -> None:
        """Write the FileName PV."""
        try:
            pv_name = f"{self.prefix}FileName"
            res = epics.caput(pv_name, name, wait=True, timeout=2.0)
            if res == 1:
                self.operationFinished.emit(True, f"FileName set to '{name}'")
            else:
                self.operationFinished.emit(False, f"Failed to set FileName to '{name}' (caput timeout/error)")
        except Exception as exc:
            self.operationFinished.emit(False, f"Failed to set FileName: {exc}")


    @Slot(str)
    def single_shot_fire(self, file_name: str) -> None:
        """Perform a complete single-shot fire: check status, write target filename, then set Arm=1."""
        try:
            cam_status_pv = f"{self.prefix}CameraStatus"
            cam_status_raw = epics.caget(cam_status_pv, as_string=True, timeout=2.0)
            cam_status = self._decode_val(cam_status_raw)

            if cam_status.upper() != "IDLE":
                self.operationFinished.emit(
                    False, f"Interlock: CameraStatus is '{cam_status}'. Abort single-shot fire."
                )
                return

            # 1. Set target file name
            file_pv = f"{self.prefix}FileName"
            res_file = epics.caput(file_pv, file_name, wait=True, timeout=2.0)
            if res_file != 1:
                self.operationFinished.emit(False, f"Single-shot Fire failed: Unable to set FileName '{file_name}'")
                return

            # 2. Trigger Arm
            arm_pv = f"{self.prefix}Arm"
            res_arm = epics.caput(arm_pv, 1, wait=True, timeout=2.0)
            if res_arm == 1:
                self.operationFinished.emit(True, f"Single-shot Fire issued! (FileName: '{file_name}')")
            else:
                self.operationFinished.emit(False, "Single-shot Fire failed: Arm command failed.")
        except Exception as exc:
            self.operationFinished.emit(False, f"Single-shot Fire failed: {exc}")

    def run(self) -> None:
        """Thread execution logic setting up PyEpics camonitors."""
        try:
            pv_status = f"{self.prefix}CameraStatus"
            pv_shot = f"{self.prefix}ShotNumber"
            pv_file = f"{self.prefix}FileName"

            epics.camonitor(pv_status, callback=self._on_camera_status)
            epics.camonitor(pv_shot, callback=self._on_shot_number)
            epics.camonitor(pv_file, callback=self._on_file_name)

            self.monitors = [pv_status, pv_shot, pv_file]

            # Fetch initial values via caget so UI is updated immediately on startup
            try:
                init_status = epics.caget(pv_status, as_string=True, timeout=2.0)
                if init_status is not None:
                    self.cameraStatusChanged.emit(self._decode_val(init_status))
                init_shot = epics.caget(pv_shot, timeout=2.0)
                if init_shot is not None:
                    self.shotNumberChanged.emit(int(init_shot))
                init_file = epics.caget(pv_file, as_string=True, timeout=2.0)
                if init_file is not None:
                    self.fileNameChanged.emit(self._decode_val(init_file))
            except Exception:
                pass

            while self._running:
                self.msleep(200)

        except Exception as exc:
            self.connectionLost.emit(str(exc))
        finally:
            self._cleanup_monitors()

    def _cleanup_monitors(self) -> None:
        for pv in self.monitors:
            try:
                epics.camonitor_clear(pv)
            except Exception:
                pass
        self.monitors.clear()

    def stop(self) -> None:
        self._running = False
        self._cleanup_monitors()
        self.quit()
        self.wait()

    def update_server_ip(self, new_ip: str | None) -> None:
        """Restart the worker when server IP changes."""
        self.stop()
        self.server_ip = new_ip
        self._setup_env()
        self._running = True
        self.start()


# ---------------------------------------------------------------------
# Main GUI window
# ---------------------------------------------------------------------
class ControlWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PC1 – DAQ Control Panel (PyEpics)")
        self.resize(420, 320)

        # UI Elements ---------------------------------------------------
        self.le_server_ip = QLineEdit()
        self.le_server_ip.setPlaceholderText("e.g. 192.168.1.32 (optional)")
        self.btn_apply_ip = QPushButton("Apply IP")

        self.le_file = QLineEdit("exp_run_pc1")
        self.lbl_status = QLabel("---")
        self.lbl_shot = QLabel("0")
        self.btn_fire = QPushButton("🔥 FIRE (Single Shot)")
        self.btn_fire.setStyleSheet("background-color: #e53935; color: white; font-weight: bold; padding: 6px;")
        self.btn_fire.setEnabled(False)  # enabled once status == IDLE

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)

        # Layout --------------------------------------------------------
        form = QFormLayout()
        form.addRow("Server IP:", self.le_server_ip)
        form.addRow("", self.btn_apply_ip)
        form.addRow("Target File:", self.le_file)
        form.addRow("Camera Status:", self.lbl_status)
        form.addRow("Shot Number:", self.lbl_shot)
        form.addRow("", self.btn_fire)

        main_layout = QVBoxLayout()
        main_layout.addLayout(form)
        main_layout.addWidget(self.log_box)
        self.setLayout(main_layout)

        # Worker --------------------------------------------------------
        self.worker = ControlWorker()
        self.worker.cameraStatusChanged.connect(self.update_status)
        self.worker.shotNumberChanged.connect(self.update_shot)
        self.worker.fileNameChanged.connect(self.update_file)
        self.worker.operationFinished.connect(self.log_message)
        self.worker.connectionLost.connect(self.handle_error)
        self.worker.start()

        # UI signal connections ------------------------------------------
        self.btn_apply_ip.clicked.connect(self.apply_ip)
        self.le_file.editingFinished.connect(self.file_changed)
        self.btn_fire.clicked.connect(self.on_fire_clicked)

    # -----------------------------------------------------------------
    # UI slots
    # -----------------------------------------------------------------
    @Slot()
    def on_fire_clicked(self):
        file_name = self.le_file.text().strip() or "exp_run_pc1"
        self.worker.single_shot_fire(file_name)

    @Slot()
    def apply_ip(self):
        ip = self.le_server_ip.text().strip() or None
        self.log_message(True, f"Applying server IP: {ip or 'default broadcast'}")
        self.worker.update_server_ip(ip)

    @Slot()
    def file_changed(self):
        name = self.le_file.text().strip()
        if name:
            self.worker.set_target_file(name)

    @Slot(str)
    def update_status(self, text: str):
        self.lbl_status.setText(text)
        colour = {
            "IDLE": "#4caf50",
            "ACTIVATING": "#ff9800",
            "ERROR": "#f44336",
        }.get(text.upper(), "gray")
        self.lbl_status.setStyleSheet(f"background-color: {colour}; color: white; font-weight: bold;")
        
        # Enable / disable FIRE button based on interlock logic
        is_idle = (text.upper() == "IDLE")
        self.btn_fire.setEnabled(is_idle)

    @Slot(int)
    def update_shot(self, number: int):
        self.lbl_shot.setText(str(number))

    @Slot(str)
    def update_file(self, name: str):
        if self.le_file.text() != name:
            self.le_file.setText(name)

    @Slot(bool, str)
    def log_message(self, success: bool, msg: str):
        prefix = "[OK]" if success else "[ERROR]"
        entry = f"{prefix} {msg}"
        if not self.log_box.toPlainText().endswith(entry):
            self.log_box.append(entry)

    @Slot(str)
    def handle_error(self, msg: str):
        self.lbl_status.setText("DISCONNECTED")
        self.lbl_status.setStyleSheet("background-color: #9e9e9e; color: white; font-weight: bold;")
        self.log_message(False, f"Connection error: {msg}")

    def closeEvent(self, event):
        self.worker.stop()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    win = ControlWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

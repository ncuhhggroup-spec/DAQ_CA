import sys
import logging
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QGroupBox, QTextEdit
)
from PySide6.QtCore import QThread, Signal, Slot, Qt
from PySide6.QtGui import QFont

import epics

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# 8-PV Specifications
PVS = {
    "ShotTarget": "EXP:Seq:ShotTarget",
    "Arm": "EXP:Seq:Arm",
    "State": "EXP:Seq:State",
    "FileName": "EXP:Seq:FileName",
    "ShotNumber": "EXP:Seq:ShotNumber",
    "ErrorMessage": "EXP:Seq:ErrorMessage",
    "DG645Status": "EXP:Seq:DG645Status",
    "CameraStatus": "EXP:Seq:CameraStatus",
}


class StatusWorker(QThread):
    """
    Thread-isolated PyEpics worker for PC2 Status GUI.
    Monitors all 8 PVs and emits Qt signals when changes occur.
    """
    pv_changed = Signal(str, object)
    log_emitted = Signal(str)

    def __init__(self):
        super().__init__()
        self._pv_objs = {}

    def run(self):
        self.log_emitted.emit("StatusWorker thread started. Subscribing to EPICS PVs...")

        for key, pv_name in PVS.items():
            pv = epics.PV(pv_name, callback=self._on_pv_change)
            self._pv_objs[key] = pv
            val = pv.get()
            if val is not None:
                self.pv_changed.emit(key, val)

        # PySide6: standard 'exec()' instead of deprecated 'exec_()'
        self.exec()

    def _on_pv_change(self, pvname=None, value=None, **kwargs):
        for key, name in PVS.items():
            if name == pvname:
                self.pv_changed.emit(key, value)
                break


class PC2StatusGUIHardware(QMainWindow):
    """
    PC2 Status GUI for monitoring sequence state, hardware connection status, and event logs.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PC2 Status Monitor - Hardware Integration (8-PV Spec)")
        self.resize(700, 550)

        self._setup_ui()
        self._start_worker()

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Title
        title_label = QLabel("PC2 DAQ System Status Panel")
        title_label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # Top Section: Badges & System State
        status_group = QGroupBox("Hardware & System State")
        status_layout = QHBoxLayout(status_group)

        self.state_label = QLabel("STATE: UNKNOWN")
        self.state_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setStyleSheet("background-color: #424242; color: white; padding: 8px; border-radius: 4px;")
        status_layout.addWidget(self.state_label)

        self.dg645_badge = QLabel("DG645: UNKNOWN")
        self.dg645_badge.setAlignment(Qt.AlignCenter)
        self.dg645_badge.setStyleSheet("background-color: #424242; color: white; padding: 8px; border-radius: 4px;")
        status_layout.addWidget(self.dg645_badge)

        self.camera_badge = QLabel("Camera: UNKNOWN")
        self.camera_badge.setAlignment(Qt.AlignCenter)
        self.camera_badge.setStyleSheet("background-color: #424242; color: white; padding: 8px; border-radius: 4px;")
        status_layout.addWidget(self.camera_badge)

        main_layout.addWidget(status_group)

        # Middle Section: Sequence Parameters Readout
        param_group = QGroupBox("Sequence Readouts")
        grid_layout = QGridLayout(param_group)

        grid_layout.addWidget(QLabel("Shot Target:"), 0, 0)
        self.target_val = QLabel("-")
        self.target_val.setFont(QFont("Segoe UI", 10, QFont.Bold))
        grid_layout.addWidget(self.target_val, 0, 1)

        grid_layout.addWidget(QLabel("Current Shot:"), 0, 2)
        self.shot_val = QLabel("-")
        self.shot_val.setFont(QFont("Segoe UI", 10, QFont.Bold))
        grid_layout.addWidget(self.shot_val, 0, 3)

        grid_layout.addWidget(QLabel("File Name Prefix:"), 1, 0)
        self.filename_val = QLabel("-")
        self.filename_val.setFont(QFont("Segoe UI", 10, QFont.Bold))
        grid_layout.addWidget(self.filename_val, 1, 1)

        grid_layout.addWidget(QLabel("Error Message:"), 1, 2)
        self.error_val = QLabel("None")
        self.error_val.setStyleSheet("color: #4caf50;")
        grid_layout.addWidget(self.error_val, 1, 3)

        main_layout.addWidget(param_group)

        # Bottom Section: Event Logging Window
        log_group = QGroupBox("System Event Log")
        log_layout = QVBoxLayout(log_group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)

        main_layout.addWidget(log_group)

    def _start_worker(self):
        self.worker = StatusWorker()
        self.worker.pv_changed.connect(self._on_pv_changed)
        self.worker.log_emitted.connect(self._add_log_entry)
        self.worker.start()

    @Slot(str, object)
    def _on_pv_changed(self, key, value):
        val_str = str(value) if value is not None else ""

        if key == "State":
            self.state_label.setText(f"STATE: {val_str}")
            color_map = {
                "IDLE": "#2196f3",
                "ARMED": "#ff9800",
                "ACQUIRING": "#00bcd4",
                "SAVING": "#9c27b0",
                "ERROR": "#f44336"
            }
            bg_color = color_map.get(val_str, "#424242")
            self.state_label.setStyleSheet(f"background-color: {bg_color}; color: white; padding: 8px; border-radius: 4px;")
            self._add_log_entry(f"State changed -> {val_str}")

        elif key == "DG645Status":
            self.dg645_badge.setText(f"DG645: {val_str}")
            bg_color = "#4caf50" if val_str == "CONNECTED" else "#f44336"
            self.dg645_badge.setStyleSheet(f"background-color: {bg_color}; color: white; padding: 8px; border-radius: 4px;")

        elif key == "CameraStatus":
            self.camera_badge.setText(f"Camera: {val_str}")
            bg_color = "#4caf50" if val_str == "CONNECTED" else "#f44336"
            self.camera_badge.setStyleSheet(f"background-color: {bg_color}; color: white; padding: 8px; border-radius: 4px;")

        elif key == "ShotTarget":
            self.target_val.setText(val_str)

        elif key == "ShotNumber":
            self.shot_val.setText(val_str)

        elif key == "FileName":
            self.filename_val.setText(val_str)

        elif key == "ErrorMessage":
            if val_str:
                self.error_val.setText(val_str)
                self.error_val.setStyleSheet("color: #f44336; font-weight: bold;")
            else:
                self.error_val.setText("None")
                self.error_val.setStyleSheet("color: #4caf50;")

    def _add_log_entry(self, message: str):
        # Microseconds formatting fix (%f with [:-3] slicing)
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_text.append(f"[{timestamp}] {message}")

    def closeEvent(self, event):
        self.worker.quit()
        self.worker.wait()
        super().closeEvent(event)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = PC2StatusGUIHardware()
    gui.show()
    sys.exit(app.exec())
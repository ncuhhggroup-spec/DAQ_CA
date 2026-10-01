import sys
import logging
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QGroupBox, QListWidget, QListWidgetItem
)
from PySide6.QtCore import QThread, Signal, Slot, Qt
from PySide6.QtGui import QFont

import epics

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

PVS = {
    "ShotTarget": "EXP:Seq:ShotTarget",
    "Arm": "EXP:Seq:Arm",
    "State": "EXP:Seq:State",
    "FileName": "EXP:Seq:FileName",
    "ShotNumber": "EXP:Seq:ShotNumber",
    "ErrorMessage": "EXP:Seq:ErrorMessage",
    "DG645Status": "EXP:Seq:DG645Status",
    "DG645Mode": "EXP:Seq:DG645Mode",
    "CameraStatus": "EXP:Seq:CameraStatus",
    "CameraMode": "EXP:Seq:CameraMode",
}

class StatusWorker(QThread):
    """
    Thread-isolated PyEpics monitoring worker for PC2 Status GUI.
    Subscribes to all EPICS PVs and emits Qt signals on value changes.
    """
    pv_changed = Signal(str, object)
    log_emitted = Signal(str)

    def __init__(self):
        super().__init__()
        self._pv_objs = {}

    def run(self):
        self.log_emitted.emit("StatusWorker thread started. Monitoring EPICS hardware PVs...")

        for key, pv_name in PVS.items():
            pv = epics.PV(pv_name, callback=self._on_pv_change)
            self._pv_objs[key] = pv
            val = pv.get()
            if val is not None:
                self.pv_changed.emit(key, val)

        self.exec_()

    def _on_pv_change(self, pvname=None, value=None, **kwargs):
        for key, name in PVS.items():
            if name == pvname:
                self.pv_changed.emit(key, value)
                break

class PC2StatusGUIHardware(QMainWindow):
    """
    PC2 Monitoring Status GUI with Hardware Mode Indicators (REAL vs SIMULATED).
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PC2 Status Monitoring GUI - Hardware Integration")
        self.resize(800, 600)

        self._setup_ui()
        self._start_worker()

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Title
        title_label = QLabel("PC2 Hardware & DAQ Status Monitor")
        title_label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # Badges & Indicators Row
        badge_layout = QHBoxLayout()

        # State Badge Box
        state_box = QGroupBox("Sequence State")
        state_box_layout = QVBoxLayout(state_box)
        self.state_label = QLabel("UNKNOWN")
        self.state_label.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setStyleSheet("background-color: #616161; color: white; border-radius: 8px; padding: 10px;")
        state_box_layout.addWidget(self.state_label)
        badge_layout.addWidget(state_box)

        # DG645 Badge Box
        dg_box = QGroupBox("DG645 Hardware")
        dg_layout = QVBoxLayout(dg_box)
        self.dg_mode_label = QLabel("MODE: UNKNOWN")
        self.dg_mode_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.dg_mode_label.setAlignment(Qt.AlignCenter)
        self.dg_mode_label.setStyleSheet("background-color: #424242; color: #ffca28; border-radius: 4px; padding: 4px;")
        dg_layout.addWidget(self.dg_mode_label)

        self.dg_status_label = QLabel("STATUS: UNKNOWN")
        self.dg_status_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.dg_status_label.setAlignment(Qt.AlignCenter)
        self.dg_status_label.setStyleSheet("background-color: #616161; color: white; border-radius: 6px; padding: 6px;")
        dg_layout.addWidget(self.dg_status_label)
        badge_layout.addWidget(dg_box)

        # Camera Badge Box
        cam_box = QGroupBox("Camera Hardware")
        cam_layout = QVBoxLayout(cam_box)
        self.cam_mode_label = QLabel("MODE: UNKNOWN")
        self.cam_mode_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.cam_mode_label.setAlignment(Qt.AlignCenter)
        self.cam_mode_label.setStyleSheet("background-color: #424242; color: #ffca28; border-radius: 4px; padding: 4px;")
        cam_layout.addWidget(self.cam_mode_label)

        self.cam_status_label = QLabel("STATUS: UNKNOWN")
        self.cam_status_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.cam_status_label.setAlignment(Qt.AlignCenter)
        self.cam_status_label.setStyleSheet("background-color: #616161; color: white; border-radius: 6px; padding: 6px;")
        cam_layout.addWidget(self.cam_status_label)
        badge_layout.addWidget(cam_box)

        main_layout.addLayout(badge_layout)

        # Details Grid
        details_group = QGroupBox("Live Sequence Data")
        grid_layout = QGridLayout(details_group)

        grid_layout.addWidget(QLabel("Shot Target:"), 0, 0)
        self.target_val = QLabel("-")
        self.target_val.setFont(QFont("Segoe UI", 10, QFont.Bold))
        grid_layout.addWidget(self.target_val, 0, 1)

        grid_layout.addWidget(QLabel("Current Shot #:"), 0, 2)
        self.shot_val = QLabel("-")
        self.shot_val.setFont(QFont("Segoe UI", 10, QFont.Bold))
        grid_layout.addWidget(self.shot_val, 0, 3)

        grid_layout.addWidget(QLabel("File Name:"), 1, 0)
        self.filename_val = QLabel("-")
        self.filename_val.setFont(QFont("Segoe UI", 10, QFont.Bold))
        grid_layout.addWidget(self.filename_val, 1, 1)

        grid_layout.addWidget(QLabel("ARM PV:"), 1, 2)
        self.arm_val = QLabel("-")
        self.arm_val.setFont(QFont("Segoe UI", 10, QFont.Bold))
        grid_layout.addWidget(self.arm_val, 1, 3)

        grid_layout.addWidget(QLabel("Error Message:"), 2, 0)
        self.error_val = QLabel("None")
        self.error_val.setStyleSheet("color: #f44336;")
        grid_layout.addWidget(self.error_val, 2, 1, 1, 3)

        main_layout.addWidget(details_group)

        # Event Log Window
        log_group = QGroupBox("Real-Time Event Log")
        log_layout = QVBoxLayout(log_group)
        self.log_list = QListWidget()
        log_layout.addWidget(self.log_list)

        main_layout.addWidget(log_group)

    def _start_worker(self):
        self.worker = StatusWorker()
        self.worker.pv_changed.connect(self._on_pv_changed)
        self.worker.log_emitted.connect(self._add_log_entry)
        self.worker.start()

    @Slot(str, object)
    def _on_pv_changed(self, key, value):
        val_str = str(value)

        if key == "State":
            self.state_label.setText(val_str)
            colors = {
                "IDLE": "#2196f3",
                "ARMED": "#ff9800",
                "ACQUIRING": "#00bcd4",
                "SAVING": "#9c27b0",
                "ERROR": "#f44336",
            }
            bg = colors.get(val_str, "#616161")
            self.state_label.setStyleSheet(f"background-color: {bg}; color: white; border-radius: 8px; padding: 10px;")
            self._add_log_entry(f"State changed -> {val_str}")

        elif key == "DG645Mode":
            self.dg_mode_label.setText(f"MODE: {val_str}")
            bg = "#2e7d32" if val_str == "REAL" else "#e65100"
            self.dg_mode_label.setStyleSheet(f"background-color: {bg}; color: white; border-radius: 4px; padding: 4px;")

        elif key == "DG645Status":
            self.dg_status_label.setText(f"STATUS: {val_str}")
            bg = "#4caf50" if val_str == "CONNECTED" else "#f44336"
            self.dg_status_label.setStyleSheet(f"background-color: {bg}; color: white; border-radius: 6px; padding: 6px;")

        elif key == "CameraMode":
            self.cam_mode_label.setText(f"MODE: {val_str}")
            bg = "#2e7d32" if val_str == "REAL" else "#e65100"
            self.cam_mode_label.setStyleSheet(f"background-color: {bg}; color: white; border-radius: 4px; padding: 4px;")

        elif key == "CameraStatus":
            self.cam_status_label.setText(f"STATUS: {val_str}")
            bg = "#4caf50" if val_str == "CONNECTED" else "#f44336"
            self.cam_status_label.setStyleSheet(f"background-color: {bg}; color: white; border-radius: 6px; padding: 6px;")

        elif key == "ShotTarget":
            self.target_val.setText(val_str)
        elif key == "ShotNumber":
            self.shot_val.setText(val_str)
        elif key == "FileName":
            self.filename_val.setText(val_str)
        elif key == "Arm":
            self.arm_val.setText(val_str)
        elif key == "ErrorMessage":
            self.error_val.setText(val_str if val_str else "None")
            if val_str:
                self._add_log_entry(f"ERROR: {val_str}")

    def _add_log_entry(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S.%3f")[:-3]
        item = QListWidgetItem(f"[{timestamp}] {msg}")
        self.log_list.addItem(item)
        self.log_list.scrollToBottom()

    def closeEvent(self, event):
        self.worker.quit()
        self.worker.wait()
        super().closeEvent(event)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = PC2StatusGUIHardware()
    gui.show()
    sys.exit(app.exec_())
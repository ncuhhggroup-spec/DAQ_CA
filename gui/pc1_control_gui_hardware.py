import sys
import logging
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLabel, QLineEdit, QSpinBox, QPushButton, QGroupBox,
    QTextEdit
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
    "CameraStatus": "EXP:Seq:CameraStatus",
}

class ControlWorker(QThread):
    """
    Thread-isolated PyEpics worker for PC1 Control GUI.
    All EPICS CA interactions are strictly isolated within this thread.
    """
    pv_updated = Signal(str, object)
    interlock_updated = Signal(bool, str)  # (is_allowed, reason)
    log_emitted = Signal(str)

    def __init__(self):
        super().__init__()
        self._pv_objs = {}
        self._cache = {
            "State": "UNKNOWN",
            "DG645Status": "UNKNOWN",
            "CameraStatus": "UNKNOWN",
        }
        self._running = True

    def run(self):
        self.log_emitted.emit("ControlWorker thread started. Subscribing to EPICS PVs...")

        # Setup PV monitors
        for key, pv_name in PVS.items():
            pv = epics.PV(pv_name, callback=self._on_pv_change)
            self._pv_objs[key] = pv
            # Initial read
            val = pv.get()
            if val is not None:
                self._update_cache_and_notify(key, val)

        self.exec_()

    def _on_pv_change(self, pvname=None, value=None, **kwargs):
        for key, name in PVS.items():
            if name == pvname:
                self._update_cache_and_notify(key, value)
                break

    def _update_cache_and_notify(self, key, value):
        if key in self._cache:
            self._cache[key] = str(value)

        self.pv_updated.emit(key, value)
        self._evaluate_interlock()

    def _evaluate_interlock(self):
        state = self._cache.get("State", "")
        dg_stat = self._cache.get("DG645Status", "")
        cam_stat = self._cache.get("CameraStatus", "")

        reasons = []
        if state != "IDLE":
            reasons.append(f"State is '{state}' (must be IDLE)")
        if dg_stat != "CONNECTED":
            reasons.append(f"DG645 is '{dg_stat}'")
        if cam_stat != "CONNECTED":
            reasons.append(f"Camera is '{cam_stat}'")

        if not reasons:
            self.interlock_updated.emit(True, "Ready to Arm sequence.")
        else:
            reason_str = "Interlock Active: " + ", ".join(reasons)
            self.interlock_updated.emit(False, reason_str)

    @Slot(int)
    def set_shot_target(self, val):
        epics.caput(PVS["ShotTarget"], val)
        self.log_emitted.emit(f"Set ShotTarget -> {val}")

    @Slot(str)
    def set_file_name(self, name):
        epics.caput(PVS["FileName"], name)
        self.log_emitted.emit(f"Set FileName -> '{name}'")

    @Slot()
    def trigger_arm(self):
        epics.caput(PVS["Arm"], 1)
        self.log_emitted.emit("Issued Arm sequence trigger (EXP:Seq:Arm = 1)")

class PC1ControlGUIHardware(QMainWindow):
    """
    PC1 Control GUI with QThread-isolated ControlWorker and Client Interlock Safeguards.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PC1 Control GUI - Hardware Integration (8-PV Spec)")
        self.resize(650, 500)

        self._setup_ui()
        self._start_worker()

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Title
        title_label = QLabel("PC1 DAQ Sequence Control Panel")
        title_label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # Control Box
        ctrl_group = QGroupBox("Sequence Control Settings")
        form_layout = QFormLayout(ctrl_group)

        self.target_spin = QSpinBox()
        self.target_spin.setRange(1, 10000)
        self.target_spin.setValue(1)
        self.target_spin.valueChanged.connect(self._on_target_changed)
        form_layout.addRow("Shot Target:", self.target_spin)

        self.filename_input = QLineEdit("exp_run")
        self.filename_input.editingFinished.connect(self._on_filename_changed)
        form_layout.addRow("File Name Prefix:", self.filename_input)

        main_layout.addWidget(ctrl_group)

        # Interlock & Arm Section
        arm_group = QGroupBox("Execution & Safeguard Interlock")
        arm_layout = QVBoxLayout(arm_group)

        self.interlock_label = QLabel("Evaluating Interlocks...")
        self.interlock_label.setStyleSheet("color: orange; font-weight: bold;")
        arm_layout.addWidget(self.interlock_label)

        self.arm_btn = QPushButton("ARM DAQ SEQUENCE")
        self.arm_btn.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.arm_btn.setMinimumHeight(45)
        self.arm_btn.setEnabled(False)
        self.arm_btn.setStyleSheet("""
            QPushButton:enabled { background-color: #2e7d32; color: white; border-radius: 5px; }
            QPushButton:disabled { background-color: #424242; color: #888888; border-radius: 5px; }
        """)
        self.arm_btn.clicked.connect(self._on_arm_clicked)
        arm_layout.addWidget(self.arm_btn)

        main_layout.addWidget(arm_group)

        # Log Window
        log_group = QGroupBox("Client Activity Log")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)

        main_layout.addWidget(log_group)

    def _start_worker(self):
        self.worker = ControlWorker()
        self.worker.pv_updated.connect(self._on_pv_updated)
        self.worker.interlock_updated.connect(self._on_interlock_updated)
        self.worker.log_emitted.connect(self.log_message)
        self.worker.start()

    @Slot(str, object)
    def _on_pv_updated(self, key, value):
        if key == "ShotTarget" and value is not None:
            self.target_spin.blockSignals(True)
            self.target_spin.setValue(int(value))
            self.target_spin.blockSignals(False)
        elif key == "FileName" and value is not None:
            self.filename_input.blockSignals(True)
            self.filename_input.setText(str(value))
            self.filename_input.blockSignals(False)

    @Slot(bool, str)
    def _on_interlock_updated(self, is_allowed, reason):
        self.arm_btn.setEnabled(is_allowed)
        if is_allowed:
            self.interlock_label.setText("✔ SAFE: All Interlocks Passed. Ready to ARM.")
            self.interlock_label.setStyleSheet("color: #4caf50; font-weight: bold;")
        else:
            self.interlock_label.setText(f"❌ INTERLOCK LOCKED: {reason}")
            self.interlock_label.setStyleSheet("color: #f44336; font-weight: bold;")

    def _on_target_changed(self, val):
        self.worker.set_shot_target(val)

    def _on_filename_changed(self):
        name = self.filename_input.text().strip()
        if name:
            self.worker.set_file_name(name)

    def _on_arm_clicked(self):
        self.worker.trigger_arm()

    def log_message(self, msg):
        self.log_text.append(msg)

    def closeEvent(self, event):
        self.worker.quit()
        self.worker.wait()
        super().closeEvent(event)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = PC1ControlGUIHardware()
    gui.show()
    sys.exit(app.exec_())

import sys
import threading
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QLineEdit,
    QPushButton,
    QTextEdit,
)
from PySide6.QtCore import Qt, QTimer
import pyqtgraph as pg

# Core components
from core.sequence_controller import SequenceController, SystemState
from core.data_manager import DataManager
from drivers.mock_stage_driver import MockStageDriver
from drivers.mock_camera_gui import MockCameraGUI
from drivers.mock_dg645_driver import MockDG645Driver

# Logger utility
from gui.journal_logger import get_logger

class MainWindow(QMainWindow):
    """DAQ Control Panel GUI.

    Provides controls for shot target, file name, note, and arms the acquisition
    while displaying live camera frames and status indicators.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DAQ_CA Control Panel")
        self.resize(1000, 700)
        self.logger = get_logger()
        self._setup_ui()
        self._setup_core()
        self._connect_signals()
        self._update_ui_state(SystemState.IDLE)

    # ---------------------------------------------------------------------
    # UI construction
    # ---------------------------------------------------------------------
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Top controls
        ctrl_layout = QHBoxLayout()
        main_layout.addLayout(ctrl_layout)

        # Shot target
        ctrl_layout.addWidget(QLabel("Shot Target:"))
        self.spin_shot = QSpinBox()
        self.spin_shot.setRange(1, 9999)
        self.spin_shot.setValue(1)
        ctrl_layout.addWidget(self.spin_shot)

        # File name
        ctrl_layout.addWidget(QLabel("File Name:"))
        self.edit_file = QLineEdit("experiment")
        ctrl_layout.addWidget(self.edit_file)

        # Note
        ctrl_layout.addWidget(QLabel("Note:"))
        self.edit_note = QLineEdit()
        ctrl_layout.addWidget(self.edit_note)

        # ARM / DISARM buttons
        self.btn_arm = QPushButton("ARM & START")
        self.btn_disarm = QPushButton("DISARM & CANCEL")
        ctrl_layout.addWidget(self.btn_arm)
        ctrl_layout.addWidget(self.btn_disarm)

        # Status label
        self.lbl_status = QLabel("IDLE")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setStyleSheet(self._status_style(SystemState.IDLE))
        main_layout.addWidget(self.lbl_status)

        # Image view for live frames
        self.image_view = pg.ImageView()
        main_layout.addWidget(self.image_view, stretch=1)

        # Log console (read‑only QTextEdit)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        main_layout.addWidget(self.txt_log, stretch=0)

        # Attach QTextEdit to logger handler
        for h in self.logger.handlers:
            if hasattr(h, "set_widget"):
                h.set_widget(self.txt_log)
                break

    # ---------------------------------------------------------------------
    # Core objects
    # ---------------------------------------------------------------------
    def _setup_core(self):
        # Instantiate mock hardware – replace with real drivers in production
        self.stage = MockStageDriver()
        self.camera = MockCameraGUI(width=512, height=512)
        self.dg645 = MockDG645Driver()
        self.data_mgr = DataManager()
        self.ctrl = SequenceController(
            stage=self.stage,
            cam=self.camera,
            data_mgr=self.data_mgr,
            dg645=self.dg645,
        )
        # Timer to refresh live frame view
        self.refresh_timer = QTimer()
        self.refresh_timer.setInterval(50)  # ~20 fps
        self.refresh_timer.timeout.connect(self._update_frame)

    # ---------------------------------------------------------------------
    # Signal connections
    # ---------------------------------------------------------------------
    def _connect_signals(self):
        self.btn_arm.clicked.connect(self._on_arm)
        self.btn_disarm.clicked.connect(self._on_disarm)
        self.ctrl.state_changed.connect(self._on_state_changed)

    # ---------------------------------------------------------------------
    # UI callbacks
    # ---------------------------------------------------------------------
    def _on_arm(self):
        """Collect parameters, log stage position, and start acquisition in a
        background thread to keep the UI responsive.
        """
        shot_target = self.spin_shot.value()
        file_name = self.edit_file.text().strip()
        note = self.edit_note.text().strip()
        # Pre‑log stage coordinates
        pos = {axis: self.stage.get_position(axis) for axis in (1, 2, 3)}
        self.logger.info(
            f"ARM request – ShotTarget={shot_target}, FileName='{file_name}', Note='{note}', StagePos={pos}"
        )
        # Run arm_and_start in a separate thread
        threading.Thread(
            target=self._run_acquisition,
            args=(shot_target, file_name, note, pos),
            daemon=True,
        ).start()

    def _run_acquisition(self, shot_target, file_name, note, stage_pos):
        try:
            self.ctrl.arm_and_start(frames=shot_target)
            self.ctrl.acquire()
            log_entry = {
                "timestamp": "placeholder",
                "shot_target": shot_target,
                "note": note,
                "stage_x": stage_pos.get(1, 0),
                "stage_y": stage_pos.get(2, 0),
                "stage_z": stage_pos.get(3, 0),
            }
            out_dir = Path.cwd() / "output"
            out_dir.mkdir(exist_ok=True)
            hdf5_path = out_dir / f"{file_name}.h5"
            tiff_path = out_dir / f"{file_name}.tif"
            self.ctrl.save(hdf5_path=str(hdf5_path), tiff_path=str(tiff_path), log_entry=log_entry)
            self.logger.info(f"Acquisition saved – HDF5: {hdf5_path}, TIFF: {tiff_path}")
            if self.data_mgr.buffer is not None and self.data_mgr.buffer.shape[0] > 0:
                metrics = self.data_mgr.fit_gaussian_2d(self.data_mgr.buffer[0])
                self.logger.info(f"Gaussian fit metrics: {metrics}")
        except Exception as e:
            self.logger.exception(f"Acquisition error: {e}")
            self.ctrl._set_state(SystemState.ERROR)

    def _on_disarm(self):
        self.ctrl.reset()
        self.logger.info("DISARM requested – system reset to IDLE")

    def _on_state_changed(self, new_state: SystemState):
        self._update_ui_state(new_state)
        self.lbl_status.setText(new_state.name)
        self.lbl_status.setStyleSheet(self._status_style(new_state))
        if new_state == SystemState.ACQUIRING:
            self.refresh_timer.start()
        else:
            self.refresh_timer.stop()

    def _update_ui_state(self, state: SystemState):
        is_idle = state == SystemState.IDLE
        for w in (self.spin_shot, self.edit_file, self.edit_note, self.btn_arm):
            w.setEnabled(is_idle)
        self.btn_disarm.setEnabled(not is_idle)

    def _update_frame(self):
        if self.camera.last_frame is not None:
            self.image_view.setImage(self.camera.last_frame, autoLevels=True)

    # ---------------------------------------------------------------------
    # Helper for dynamic QSS styling
    # ---------------------------------------------------------------------
    @staticmethod
    def _status_style(state: SystemState) -> str:
        colors = {
            SystemState.IDLE: "#6c757d",
            SystemState.ARMED: "#ffc107",
            SystemState.ACQUIRING: "#0d6efd",
            SystemState.SAVING: "#6f42c1",
            SystemState.ERROR: "#dc3545",
        }
        color = colors.get(state, "#6c757d")
        return f"QLabel {{ background-color: {color}; color: white; padding: 4px; font-weight: bold; }}"

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

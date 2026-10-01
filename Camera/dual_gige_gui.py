"""
dual_gige_gui.py
================
PyQt6 / PySide6 GUI front-end for Single GigE Point Grey Grasshopper2 Camera (Cam 0).
Refactored for strict local vs. EPICS DAQ workflow separation.

Key Features:
- Tab 1: Live View & Local Operations
  - CW (Continuous Wave) 10 Hz streaming toggle.
  - Dedicated "📸 Single Shot" button that automatically pauses CW acquisition.
  - Manual Trigger Mode switch (Internal Free-Run vs. External Hardware TTL).
  - Independent Local Free Saving (directory & file prefix, isolated from EPICS).
  - Real-time 2D Gaussian beam analysis, ROI, target crosshair, and background subtraction.
- Tab 2: EPICS DAQ Mode
  - Automatic forced switch to External Hardware Trigger mode upon entering DAQ mode.
  - EPICS IOC Network & Hardware Mode Status Banner strictly bound to Cam 0 (REAL vs SIMULATED).
  - Live readouts for Sequence State, Shot Counter, and Active DAQ Filename.
  - Automated background frame saving on SAVING state using EPICS PV metadata.
  - Rich-text System & DAQ Event Log console with Qt Thread-safe Signal communication.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Optional

import numpy as np
import tifffile

# Qt backend detection (PyQt6 / PySide6)
try:
    from PyQt6 import QtCore, QtGui, QtWidgets
    from PyQt6.QtCore import (
        QMutex, QMutexLocker, QThread, QTimer, Qt, pyqtSignal as Signal, pyqtSlot as Slot
    )
    from PyQt6.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
        QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
        QPushButton, QTextEdit, QTabWidget, QVBoxLayout, QWidget,
    )
    _QT_BACKEND = "PyQt6"
except ImportError:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import (
        QMutex, QMutexLocker, QThread, QTimer, Qt, Signal, Slot
    )
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
        QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
        QPushButton, QTextEdit, QTabWidget, QVBoxLayout, QWidget,
    )
    _QT_BACKEND = "PySide6"

import pyqtgraph as pg

from camera_analysis import fit_2d_gaussian, GaussianFitResult
from dual_gige_driver import DualGigECameraController

logger = logging.getLogger(__name__)

# PyQtGraph global settings
pg.setConfigOptions(
    imageAxisOrder="row-major",
    antialias=True,
    useOpenGL=True,
)

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "camera_settings.json")

# Modern Dark CSS Theme
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
    border-radius: 6px;
    margin-top: 14px;
    padding: 10px 8px 6px 8px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
    color: #818cf8;
    font-size: 11px;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {
    background-color: #1e2230;
    border: 1px solid #31384e;
    border-radius: 4px;
    padding: 4px 6px;
    color: #f1f5f9;
    font-size: 12px;
}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #6366f1;
}
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4f46e5, stop:1 #4338ca);
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 6px 12px;
    font-weight: 600;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #6366f1, stop:1 #4f46e5);
}
QPushButton:pressed {
    background: #3730a3;
}
QPushButton#singleShotBtn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0891b2, stop:1 #0e7490);
}
QPushButton#singleShotBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #06b6d4, stop:1 #0891b2);
}
QPushButton#recordBgBtn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #059669, stop:1 #047857);
}
QPushButton#recordBgBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #10b981, stop:1 #059669);
}
QPushButton#analyzeBtn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #d97706, stop:1 #b45309);
}
QPushButton#analyzeBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f59e0b, stop:1 #d97706);
}
QPushButton#saveBtn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2563eb, stop:1 #1d4ed8);
}
QPushButton#saveBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3b82f6, stop:1 #2563eb);
}
QPushButton#browseBtn {
    background: #334155;
    color: #f8fafc;
    border: 1px solid #475569;
}
QPushButton#cwBtnRunning {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #059669, stop:1 #047857);
    color: #ffffff;
    font-weight: bold;
}
QPushButton#cwBtnStopped {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #dc2626, stop:1 #b91c1c);
    color: #ffffff;
    font-weight: bold;
}
QTabWidget::pane {
    border: 1px solid #272d3d;
    background-color: #0f1117;
    border-radius: 6px;
}
QTabBar::tab {
    background: #171a23;
    color: #94a3b8;
    border: 1px solid #272d3d;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 22px;
    margin-right: 4px;
    font-weight: 600;
}
QTabBar::tab:selected {
    background: #1e2230;
    color: #38bdf8;
    border-color: #38bdf8;
}
"""


class CameraGrabberThread(QThread):
    """Background thread grabbing frames exclusively for Camera 0."""
    
    frame_ready = Signal(object)

    def __init__(self, controller: DualGigECameraController):
        super().__init__()
        self.controller = controller
        self._running = False
        self._mutex = QMutex()

    def run(self):
        self._running = True
        while True:
            with QMutexLocker(self._mutex):
                if not self._running:
                    break
            
            try:
                # 簡化：直接抓取 Cam 0 影格
                f0 = self.controller.grab_frame(0)
                if f0 is not None:
                    self.frame_ready.emit(f0)
            except Exception as e:
                logger.debug("Cam 0 frame grabber thread error: %s", e)
            
            time.sleep(0.01)

    def stop(self):
        with QMutexLocker(self._mutex):
            self._running = False
        self.wait(2000)


class SingleGigECameraGUI(QMainWindow):
    # Thread-safe Qt Signal for EPICS state changes
    epics_state_changed = Signal(str)

    def __init__(self, force_mock: bool = False):
        super().__init__()
        self.setWindowTitle("Point Grey GigE Camera Controller (Cam 0) - Diagnostic & DAQ System")
        self.resize(1150, 850)
        self.setStyleSheet(_STYLE)

        # State Variables
        self.is_cw_running = True
        self.latest_frame: Optional[np.ndarray] = None
        self.latest_fit: Optional[GaussianFitResult] = None

        # EPICS State tracking
        self._epics_state_pv = None
        self._last_epics_state = None

        # Controller Initialization (Cam 0 Only)
        self.controller = DualGigECameraController(
            serial_0=0,
            name_0="Cam_0",
            force_mock=force_mock,
        )

        self._init_ui()
        self._load_settings()

        # Connect & start Cam 0
        self._connect_camera()

        # Setup EPICS Listeners
        self._setup_epics_listeners()

        # 10 Hz Timer for UI rendering
        self.display_timer = QTimer(self)
        self.display_timer.setInterval(100)
        self.display_timer.timeout.connect(self._on_display_tick)

        # Start Grabber Thread
        self.grabber_thread = CameraGrabberThread(self.controller)
        self.grabber_thread.frame_ready.connect(self._on_frame_received)
        self.grabber_thread.start()
        self.display_timer.start()

    def _init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Tab Widget
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # --- TAB 1: Live View & Local Operations ---
        self.tab_local = QWidget()
        self._build_tab_local(self.tab_local)
        self.tabs.addTab(self.tab_local, "🎥 Live View & Local Operations")

        # --- TAB 2: EPICS DAQ Mode ---
        self.tab_epics = QWidget()
        self._build_tab_epics(self.tab_epics)
        self.tabs.addTab(self.tab_epics, "⚡ EPICS DAQ Mode")

        # --- TAB 3: System & Event Log ---
        self.tab_log = QWidget()
        self._build_tab_log(self.tab_log)
        self.tabs.addTab(self.tab_log, "📜 System & Event Log")

        main_layout.addWidget(self.tabs)
        self.statusBar().showMessage("System Ready | Camera 0 Active")

    # -------------------------------------------------------------------------
    # Tab 1: Live View & Local Operations
    # -------------------------------------------------------------------------

    def _build_tab_epics(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Top EPICS Network Banner
        self.epics_banner_label = QLabel("EPICS IOC: DISCONNECTED | Mode: UNKNOWN")
        self.epics_banner_label.setStyleSheet("background-color: #f44336; color: white; font-weight: bold; font-size: 14px; padding: 10px; border-radius: 6px;")
        self.epics_banner_label.setAlignment(Qt.AlignmentFlag.AlignCenter if hasattr(Qt, "AlignmentFlag") else Qt.AlignCenter)
        layout.addWidget(self.epics_banner_label)

        # EPICS Sequence & PV Status Board
        pv_group = QGroupBox("EPICS Channel Access PV Status Readouts")
        f_layout = QFormLayout(pv_group)

        self.pv_state_label = QLabel("IDLE")
        self.pv_state_label.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 14px;")
        f_layout.addRow("Sequence State (EXP:Seq:State):", self.pv_state_label)

        self.pv_cam_mode_label = QLabel("SIMULATED")
        self.pv_cam_mode_label.setStyleSheet("color: #f59e0b; font-weight: bold;")
        f_layout.addRow("Camera Mode (EXP:Seq:CameraMode):", self.pv_cam_mode_label)

        self.pv_cam_status_label = QLabel("CONNECTED")
        self.pv_cam_status_label.setStyleSheet("color: #10b981; font-weight: bold;")
        f_layout.addRow("Camera Status (EXP:Seq:CameraStatus):", self.pv_cam_status_label)

        self.pv_filename_label = QLabel("exp_run")
        self.pv_filename_label.setStyleSheet("color: #f1f5f9; font-weight: bold;")
        f_layout.addRow("Active Filename (EXP:Seq:FileName):", self.pv_filename_label)

        self.pv_shot_label = QLabel("0")
        self.pv_shot_label.setStyleSheet("color: #f1f5f9; font-weight: bold;")
        f_layout.addRow("Current Shot # (EXP:Seq:ShotNumber):", self.pv_shot_label)

        layout.addWidget(pv_group)

        # EPICS DAQ Auto-Save Configuration
        daq_group = QGroupBox("EPICS Automated Sequence Save Configuration")
        daq_layout = QVBoxLayout(daq_group)

        d_row = QHBoxLayout()
        d_row.addWidget(QLabel("DAQ Auto-Save Dir:"))
        default_daq_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_epics")
        self.daq_dir_edit = QLineEdit(default_daq_dir)
        d_row.addWidget(self.daq_dir_edit, stretch=1)

        btn_daq_browse = QPushButton("Browse...")
        btn_daq_browse.setObjectName("browseBtn")
        btn_daq_browse.clicked.connect(self._on_browse_daq_dir)
        d_row.addWidget(btn_daq_browse)

        daq_layout.addLayout(d_row)

        info_lbl = QLabel("Note: In EPICS DAQ Mode, the camera is automatically locked to EXTERNAL_TTL trigger mode.\nFrames are captured upon DG645 pulse and saved automatically during SAVING state using EPICS PV metadata.")
        info_lbl.setStyleSheet("color: #94a3b8; font-style: italic;")
        daq_layout.addWidget(info_lbl)

        layout.addWidget(daq_group)

        # EPICS Acquired Image Display Viewport
        daq_img_group = QGroupBox("EPICS DAQ Acquired Frame Viewport")
        daq_img_layout = QVBoxLayout(daq_img_group)

        self.daq_gl_layout = pg.GraphicsLayoutWidget()
        self.daq_gl_layout.setBackground("#000000")
        self.daq_view = self.daq_gl_layout.addViewBox(row=0, col=0, lockAspect=True, enableMouse=True)
        self.daq_view.invertY(True)

        self.daq_img_item = pg.ImageItem()
        self.daq_view.addItem(self.daq_img_item)

        self.daq_hist_lut = pg.HistogramLUTItem(self.daq_img_item)
        self.daq_hist_lut.gradient.loadPreset("inferno")
        self.daq_gl_layout.addItem(self.daq_hist_lut, row=0, col=1)
        self.daq_hist_lut.setMaximumWidth(110)

        daq_img_layout.addWidget(self.daq_gl_layout)
        layout.addWidget(daq_img_group, stretch=1)

    def _init_graphics_overlays(self):
        # Target Circle Overlay
        self.target_circle = pg.CircleROI([762, 562], [100, 100], pen=pg.mkPen("#38bdf8", width=1.5, style=Qt.PenStyle.DashLine))
        self.target_circle.setZValue(10)
        self.view.addItem(self.target_circle)

        self.crosshair_v = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#38bdf8", width=1.0))
        self.crosshair_h = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen("#38bdf8", width=1.0))
        self.view.addItem(self.crosshair_v)
        self.view.addItem(self.crosshair_h)
        self.target_circle.sigRegionChanged.connect(self._update_crosshair_pos)

        # ROI Box for Fitting
        self.roi_box = pg.RectROI([612, 412], [400, 400], pen=pg.mkPen("#f59e0b", width=1.5))
        self.roi_box.addScaleHandle([1, 1], [0, 0])
        self.roi_box.addScaleHandle([0, 0], [1, 1])
        self.roi_box.setZValue(9)
        self.view.addItem(self.roi_box)

        # Fitted Centroid Marker
        self.fit_marker = pg.ScatterPlotItem(size=12, pen=pg.mkPen("#ef4444", width=2), brush=pg.mkBrush("#ef4444"))
        self.fit_marker.setZValue(12)
        self.view.addItem(self.fit_marker)

        self.proxy = pg.SignalProxy(self.gl_layout.scene().sigMouseMoved, rateLimit=30, slot=self._on_mouse_moved)

    # -------------------------------------------------------------------------
    # Tab 2: EPICS DAQ Mode
    # -------------------------------------------------------------------------

    def _build_tab_epics(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Top EPICS Network Banner
        self.epics_banner_label = QLabel("EPICS IOC: DISCONNECTED | Mode: UNKNOWN")
        self.epics_banner_label.setStyleSheet("background-color: #f44336; color: white; font-weight: bold; font-size: 14px; padding: 10px; border-radius: 6px;")
        self.epics_banner_label.setAlignment(Qt.AlignmentFlag.AlignCenter if hasattr(Qt, "AlignmentFlag") else Qt.AlignCenter)
        layout.addWidget(self.epics_banner_label)

        # EPICS Sequence & PV Status Board
        pv_group = QGroupBox("EPICS Channel Access PV Status Readouts")
        f_layout = QFormLayout(pv_group)

        self.pv_state_label = QLabel("IDLE")
        self.pv_state_label.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 14px;")
        f_layout.addRow("Sequence State (EXP:Seq:State):", self.pv_state_label)

        self.pv_cam_mode_label = QLabel("SIMULATED")
        self.pv_cam_mode_label.setStyleSheet("color: #f59e0b; font-weight: bold;")
        f_layout.addRow("Camera Mode (EXP:Seq:CameraMode):", self.pv_cam_mode_label)

        self.pv_cam_status_label = QLabel("CONNECTED")
        self.pv_cam_status_label.setStyleSheet("color: #10b981; font-weight: bold;")
        f_layout.addRow("Camera Status (EXP:Seq:CameraStatus):", self.pv_cam_status_label)

        self.pv_filename_label = QLabel("exp_run")
        self.pv_filename_label.setStyleSheet("color: #f1f5f9; font-weight: bold;")
        f_layout.addRow("Active Filename (EXP:Seq:FileName):", self.pv_filename_label)

        self.pv_shot_label = QLabel("0")
        self.pv_shot_label.setStyleSheet("color: #f1f5f9; font-weight: bold;")
        f_layout.addRow("Current Shot # (EXP:Seq:ShotNumber):", self.pv_shot_label)

        layout.addWidget(pv_group)

        # EPICS DAQ Auto-Save Configuration
        daq_group = QGroupBox("EPICS Automated Sequence Save Configuration")
        daq_layout = QVBoxLayout(daq_group)

        d_row = QHBoxLayout()
        d_row.addWidget(QLabel("DAQ Auto-Save Dir:"))
        default_daq_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_epics")
        self.daq_dir_edit = QLineEdit(default_daq_dir)
        d_row.addWidget(self.daq_dir_edit, stretch=1)

        btn_daq_browse = QPushButton("Browse...")
        btn_daq_browse.setObjectName("browseBtn")
        btn_daq_browse.clicked.connect(self._on_browse_daq_dir)
        d_row.addWidget(btn_daq_browse)

        daq_layout.addLayout(d_row)

        info_lbl = QLabel("Note: In EPICS DAQ Mode, the camera is automatically locked to EXTERNAL_TTL trigger mode.\nFrames are captured upon DG645 pulse and saved automatically during SAVING state using EPICS PV metadata.")
        info_lbl.setStyleSheet("color: #94a3b8; font-style: italic;")
        daq_layout.addWidget(info_lbl)

        layout.addWidget(daq_group)

        # System & DAQ Log Window
        log_group = QGroupBox("System & DAQ Event Log (全系統日誌)")
        log_layout = QVBoxLayout(log_group)

        self.daq_log_edit = QTextEdit()
        self.daq_log_edit.setReadOnly(True)
        self.daq_log_edit.setStyleSheet("background-color: #1e1e1e; color: #dcdcdc; font-family: Consolas, monospace;")
        log_layout.addWidget(self.daq_log_edit)

        btn_clear_log = QPushButton("Clear Log")
        btn_clear_log.setObjectName("browseBtn")
        btn_clear_log.clicked.connect(self._clear_log)
        log_layout.addWidget(btn_clear_log, alignment=Qt.AlignmentFlag.AlignRight if hasattr(Qt, "AlignmentFlag") else Qt.AlignRight)

        layout.addWidget(log_group, stretch=1)

# -------------------------------------------------------------------------
    # Tab 3: System & Event Log
    # -------------------------------------------------------------------------

    def _build_tab_log(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        log_group = QGroupBox("System & DAQ Event Log (全系統日誌)")
        log_layout = QVBoxLayout(log_group)

        self.daq_log_edit = QTextEdit()
        self.daq_log_edit.setReadOnly(True)
        self.daq_log_edit.setStyleSheet("background-color: #1e1e1e; color: #dcdcdc; font-family: Consolas, monospace;")
        log_layout.addWidget(self.daq_log_edit)

        btn_clear_log = QPushButton("Clear Log")
        btn_clear_log.setObjectName("browseBtn")
        btn_clear_log.clicked.connect(self._clear_log)
        log_layout.addWidget(
            btn_clear_log,
            alignment=Qt.AlignmentFlag.AlignRight if hasattr(Qt, "AlignmentFlag") else Qt.AlignRight
        )

        layout.addWidget(log_group, stretch=1)

    # -------------------------------------------------------------------------
    # System Event Logger & Helper Methods
    # -------------------------------------------------------------------------

    def log(self, message: str, level: str = "INFO"):
        """System-wide colored event logger supporting HTML rich-text formatting."""
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
        self.daq_log_edit.append(formatted_msg)
        self.daq_log_edit.moveCursor(QtGui.QTextCursor.MoveOperation.End if hasattr(QtGui, "QTextCursor") else QtGui.QTextCursor.End)

    def _clear_log(self):
        """Clear event log console."""
        self.daq_log_edit.clear()
        self.log("Event log cleared.")

    def log_daq(self, message: str):
        """Backward compatibility alias for log()."""
        self.log(message, "INFO")

    def _update_crosshair_pos(self):
        pos = self.target_circle.pos()
        size = self.target_circle.size()
        cx = pos.x() + size.x() / 2.0
        cy = pos.y() + size.y() / 2.0
        self.crosshair_v.setPos(cx)
        self.crosshair_h.setPos(cy)

    def _on_mouse_moved(self, evt):
        pos = evt[0]
        if self.view.sceneBoundingRect().contains(pos):
            mouse_pt = self.view.mapSceneToView(pos)
            x, y = int(round(mouse_pt.x())), int(round(mouse_pt.y()))
            if self.latest_frame is not None:
                h, w = self.latest_frame.shape
                if 0 <= x < w and 0 <= y < h:
                    val = self.latest_frame[y, x]
                    self.coord_label.setText(f"Cursor: (X: {x:4d}, Y: {y:4d}) | Intensity: {val:5d} ADU (Raw)")
                    return
        self.coord_label.setText("Cursor: (X: ----, Y: ----) | Intensity: ---- ADU")

    def _on_tab_changed(self, index: int):
        """When switching to Tab 2 (EPICS DAQ Mode), force EXTERNAL_TTL trigger mode."""
        if index == 1:  # EPICS DAQ Tab
            self.trigger_combo.setCurrentIndex(1)  # Force EXTERNAL_TTL
            self.controller.set_trigger_mode("EXTERNAL_TTL")
            self.statusBar().showMessage("Switched to EPICS DAQ Mode -> Locked to EXTERNAL_TTL Trigger")
            self.log("Entered EPICS DAQ Mode: Enforced EXTERNAL_TTL trigger mode.", "INFO")

    def _on_toggle_cw(self):
        if self.is_cw_running:
            self.controller.stop_capture_all()
            self.is_cw_running = False
            self.btn_cw_toggle.setText("Start CW Acquisition")
            self.btn_cw_toggle.setObjectName("cwBtnStopped")
            self.btn_cw_toggle.style().unpolish(self.btn_cw_toggle)
            self.btn_cw_toggle.style().polish(self.btn_cw_toggle)
            self.status_badge.setText("● PAUSED")
            self.status_badge.setStyleSheet("color: #ef4444; font-weight: bold; padding: 2px 8px; background: #171a23; border-radius: 4px;")
            self.log("CW Acquisition PAUSED.", "WARNING")
        else:
            self.controller.start_capture_all()
            self.is_cw_running = True
            self.btn_cw_toggle.setText("Stop CW Acquisition")
            self.btn_cw_toggle.setObjectName("cwBtnRunning")
            self.btn_cw_toggle.style().unpolish(self.btn_cw_toggle)
            self.btn_cw_toggle.style().polish(self.btn_cw_toggle)
            self.status_badge.setText("● LIVE (CW)")
            self.status_badge.setStyleSheet("color: #10b981; font-weight: bold; padding: 2px 8px; background: #171a23; border-radius: 4px;")
            self.log("CW Acquisition STARTED.", "SUCCESS")

    def _on_single_shot_click(self):
        """Grab a single frame directly from Cam 0; automatically stops CW stream if running."""
        if self.is_cw_running:
            self._on_toggle_cw()
            self.log("Single shot triggered: Automatically paused CW acquisition.", "INFO")

        try:
            driver_0 = self.controller.drivers[0] if getattr(self.controller, 'drivers', None) else None
            was_capturing = getattr(driver_0, 'is_capturing', False) if driver_0 else False

            if not was_capturing:
                self.controller.start_capture_all()

            frame = self.controller.grab_frame(0)

            if not was_capturing:
                self.controller.stop_capture_all()

            if frame is not None:
                self.latest_frame = frame
                self.img_item.setImage(frame, autoLevels=False)
                self.status_badge.setText("● SINGLE SHOT")
                self.status_badge.setStyleSheet("color: #38bdf8; font-weight: bold; padding: 2px 8px; background: #171a23; border-radius: 4px;")
                self.statusBar().showMessage("📸 Single shot grabbed successfully (CW Paused).")
                self.log("📸 Single shot frame captured and rendered.", "SUCCESS")
            else:
                self.log("Single shot failed: Cam 0 Driver returned empty frame.", "ERROR")
                QMessageBox.warning(self, "Single Shot", "Failed to grab single frame from Camera 0.")
        except Exception as e:
            self.log(f"Single shot exception: {e}", "ERROR")
            QMessageBox.critical(self, "Single Shot Error", str(e))

    def _on_local_trigger_changed(self, idx: int):
        mode = "EXTERNAL_TTL" if idx == 1 else "INTERNAL/OFF"
        self.controller.set_trigger_mode(mode)
        self.statusBar().showMessage(f"Local Trigger mode set to: {mode}")
        self.log(f"Local Trigger mode changed to: {mode}", "INFO")

    def _on_exposure_changed(self, val_ms: float):
        self.controller.set_exposure_time(0, val_ms / 1000.0)

    def _on_gain_changed(self, val_db: float):
        self.controller.set_gain(0, val_db)

    def _on_target_toggle(self, state: int):
        visible = bool(state)
        self.target_circle.setVisible(visible)
        self.crosshair_v.setVisible(visible)
        self.crosshair_h.setVisible(visible)

    def _on_roi_toggle(self, state: int):
        self.roi_box.setVisible(bool(state))

    def _on_record_bg(self):
        try:
            bg = self.controller.record_background(0, num_averages=3)
            mean_bg = float(np.mean(bg))
            self.bg_status_label.setText(f"BG: [Mean {mean_bg:.1f}]")
            self.bg_status_label.setStyleSheet("color: #10b981; font-weight: bold;")
            self.log(f"Background recorded (3 averages). Mean intensity: {mean_bg:.1f} ADU", "SUCCESS")
            QMessageBox.information(self, "Background", f"Cam 0 Background recorded.\nMean: {mean_bg:.1f} ADU")
        except Exception as e:
            self.log(f"Background recording failed: {e}", "ERROR")
            QMessageBox.critical(self, "Background Error", str(e))

    def _on_analyze(self):
        if self.latest_frame is None:
            self.log("Gaussian Analysis aborted: No image frame available.", "WARNING")
            QMessageBox.warning(self, "Analyze", "No image frame available.")
            return

        pos = self.roi_box.pos()
        size = self.roi_box.size()
        x_min, y_min = int(pos.x()), int(pos.y())
        x_max, y_max = int(pos.x() + size.x()), int(pos.y() + size.y())

        fit = fit_2d_gaussian(self.latest_frame, roi_coords=(x_min, y_min, x_max, y_max))
        self.latest_fit = fit

        if fit.success:
            res_str = (
                f"Beam Center: ({fit.global_x0:.1f}, {fit.global_y0:.1f}) px | "
                f"FWHM (X/Y): ({fit.fwhm_x:.1f}, {fit.fwhm_y:.1f}) px | "
                f"RMSE: {fit.residual_rmse:.1f} ADU"
            )
            self.fit_result_label.setText(res_str)
            self.fit_marker.setData([{"pos": (fit.global_x0, fit.global_y0)}])
            self.log(f"Gaussian Fit Success -> {res_str}", "SUCCESS")
        else:
            self.fit_result_label.setText(f"Fit failed: {fit.message}")
            self.fit_marker.clear()
            self.log(f"Gaussian Fit Failed: {fit.message}", "WARNING")

    def _on_browse_local_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Local Save Directory", self.local_dir_edit.text())
        if d:
            self.local_dir_edit.setText(d)

    def _on_browse_daq_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select DAQ Save Directory", self.daq_dir_edit.text())
        if d:
            self.daq_dir_edit.setText(d)

    def _on_save_local_shot(self):
        """Save shot locally without affecting or reading EPICS PVs."""
        if self.latest_frame is None:
            self.log("Local Save aborted: No frame in memory.", "WARNING")
            QMessageBox.warning(self, "Save Local", "No frame available.")
            return

        target_dir = self.local_dir_edit.text().strip()
        os.makedirs(target_dir, exist_ok=True)

        prefix = self.local_prefix_edit.text().strip() or "cam0_local"
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{timestamp}.tif"
        filepath = os.path.join(target_dir, filename)

        try:
            extra = {}
            if self.latest_fit and self.latest_fit.success:
                extra["analysis"] = {
                    "center_x": self.latest_fit.global_x0,
                    "center_y": self.latest_fit.global_y0,
                    "fwhm_x": self.latest_fit.fwhm_x,
                    "fwhm_y": self.latest_fit.fwhm_y,
                }
            self.controller.save_tiff_with_metadata(
                filepath=filepath,
                index=0,
                image_data=self.latest_frame,
                extra_metadata=extra,
            )
            self.log(f"💾 Local image saved successfully: {filepath}", "SUCCESS")
            QMessageBox.information(self, "Saved Locally", f"Saved image to:\n{filepath}")
        except Exception as e:
            self.log(f"Local save failed: {e}", "ERROR")
            QMessageBox.critical(self, "Save Error", str(e))

    # -------------------------------------------------------------------------
    # EPICS Integration & Background Auto-Saving (Strictly Cam 0)
    # -------------------------------------------------------------------------

    def _connect_camera(self):
        """Connect to Camera 0 exclusively and publish its true hardware mode."""
        c0, _ = self.controller.connect_all()
        self.controller.start_capture_all()

        try:
            import epics
            # 直接讀取控制器對應 Cam 0 的 is_mock 屬性
            is_real = c0 and (not self.controller.is_mock)
            mode_str = "REAL" if is_real else "SIMULATED"
            stat_str = "CONNECTED" if c0 else "DISCONNECTED"

            epics.caput("EXP:Seq:CameraMode", mode_str)
            epics.caput("EXP:Seq:CameraStatus", stat_str)

            self.pv_cam_mode_label.setText(mode_str)
            self.pv_cam_status_label.setText(stat_str)

            bg_col = "#2e7d32" if is_real else "#e65100"
            self.epics_banner_label.setText(f"✔ EPICS IOC: ONLINE | Status: {stat_str} | Mode: {mode_str} HARDWARE")
            self.epics_banner_label.setStyleSheet(f"background-color: {bg_col}; color: white; font-weight: bold; font-size: 14px; padding: 10px; border-radius: 6px;")

            self.log(
                f"Cam 0 Hardware Status -> Connected: {c0}, Driver Mock: {self.controller.is_mock}",
                "SUCCESS" if is_real else "WARNING"
            )
            self.log(f"Published EPICS PVs -> EXP:Seq:CameraMode='{mode_str}', EXP:Seq:CameraStatus='{stat_str}'", "INFO")
        except Exception as e:
            self.log(f"Could not publish camera status to EPICS: {e}", "ERROR")

    def _setup_epics_listeners(self):
        try:
            import epics
            # Bind Qt Signal for thread-safe cross-thread UI updates
            self.epics_state_changed.connect(self._handle_epics_auto_sequence)
            
            # Subscribe to EPICS State PV
            self._epics_state_pv = epics.PV("EXP:Seq:State", callback=self._on_epics_state_change)
            self.log("Subscribed to EPICS PV: EXP:Seq:State", "INFO")
        except Exception as e:
            self.log(f"Failed to subscribe to EPICS state PV: {e}", "WARNING")

    def _on_epics_state_change(self, pvname=None, value=None, **kwargs):
        """Executed inside PyEpics C-CA thread -> safely emits Qt Signal to main UI thread."""
        if value is not None:
            state_str = str(value)
            self.epics_state_changed.emit(state_str)

    def _handle_epics_auto_sequence(self, new_state: str):
        self.pv_state_label.setText(new_state)

        # 1. Read latest PV metadata from EPICS
        try:
            import epics
            fn_val = epics.caget("EXP:Seq:FileName", as_string=True)
            sn_val = epics.caget("EXP:Seq:ShotNumber")

            fn = fn_val if fn_val is not None else "exp_run"
            sn = sn_val if sn_val is not None else 0

            self.pv_filename_label.setText(str(fn))
            self.pv_shot_label.setText(str(sn))
        except Exception as e:
            fn, sn = "exp_run", 0
            self.log(f"Failed reading EPICS PVs: {e}", "WARNING")

        # Edge detection safeguard
        if new_state == self._last_epics_state:
            return

        self.log(f"EPICS State Transition: {self._last_epics_state} -> {new_state}", "INFO")

        # 2. Sequence state machine for Cam 0
        if new_state == "ARMED":
            self.controller.set_trigger_mode("EXTERNAL_TTL")
            self.controller.start_capture_all()
            self.log("⚡ [ARMED] Locked to EXTERNAL_TTL & armed Cam 0 capture buffer.", "SUCCESS")

        elif new_state == "ACQUIRING":
            self.controller.start_capture_all()
            self.log("⚡ [ACQUIRING] Cam 0 buffer active, waiting for DG645 TTL trigger pulse...", "INFO")

        elif new_state == "SAVING":
            try:
                target_dir = self.daq_dir_edit.text().strip()
                os.makedirs(target_dir, exist_ok=True)

                filename = f"{fn}_shot_{int(sn):04d}.tif"
                filepath = os.path.join(target_dir, filename)

                if self.latest_frame is not None:
                    tifffile.imwrite(filepath, self.latest_frame)
                    # Automatically render acquired image on Tab 2 viewport
                    self.daq_img_item.setImage(self.latest_frame, autoLevels=False)
                    self.log(f"💾 [SAVING AUTO-SAVE] Saved DAQ frame: {filepath}", "SUCCESS")
                else:
                    self.log("❌ [SAVING ERROR] No image frame in buffer to save!", "ERROR")
            except Exception as e:
                self.log(f"❌ [SAVING ERROR] Failed auto-saving camera image: {e}", "ERROR")

        self._last_epics_state = new_state

    @Slot(object)
    def _on_frame_received(self, frame):
        if frame is not None:
            self.latest_frame = frame

    def _on_display_tick(self):
        if not self.is_cw_running:
            return

        if self.latest_frame is not None:
            self.img_item.setImage(self.latest_frame, autoLevels=False)

    def _load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if "exposure_ms" in cfg:
                    self.exp_spin.setValue(float(cfg["exposure_ms"]))
                if "gain_db" in cfg:
                    self.gain_spin.setValue(float(cfg["gain_db"]))
                if "local_save_dir" in cfg:
                    self.local_dir_edit.setText(cfg["local_save_dir"])
                if "daq_save_dir" in cfg:
                    self.daq_dir_edit.setText(cfg["daq_save_dir"])
            except Exception as e:
                logger.warning("Could not load settings: %s", e)

    def _save_settings(self):
        try:
            cfg = {
                "exposure_ms": self.exp_spin.value(),
                "gain_db": self.gain_spin.value(),
                "local_save_dir": self.local_dir_edit.text().strip(),
                "daq_save_dir": self.daq_dir_edit.text().strip(),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            logger.error("Could not save settings: %s", e)

    def closeEvent(self, event):
        self.display_timer.stop()
        self.grabber_thread.stop()
        self._save_settings()
        self.controller.stop_capture_all()
        self.controller.disconnect_all()
        event.accept()


# Maintain class alias for backward compatibility
DualGigECameraGUI = SingleGigECameraGUI


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    app = QApplication(sys.argv)
    window = SingleGigECameraGUI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
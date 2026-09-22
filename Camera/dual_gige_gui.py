"""
dual_gige_gui.py
================
PyQt6 / PySide6 GUI front-end for Dual GigE Point Grey Grasshopper2 Cameras.

Key Features:
- Tabbed Navigation to switch between Camera 1 and Camera 2 full image viewports.
- One-click CW (Continuous Wave) acquisition toggle button with live state indicators.
- Configurable Data Save Directory textbox with interactive folder browser and auto-persistence.
- 10 Hz refresh cap for ultra-smooth, lightweight rendering.
- Raw live image display without background subtraction.
- Live mouse cursor tracker: (X, Y) pixel coordinates and raw intensity.
- Interactive Target Overlay: Draggable Circle & Crosshair for laser beam centering.
- Integrated ROI selection box for localized analysis.
- Background Management: "Record Background" button and indicator.
- 2D Gaussian Fitting Analysis over ROI: outputs Beam Center (X0, Y0), FWHM_x, FWHM_y, and Fit Residuals.
- Single Shot & Series TIFF saving with embedded JSON metadata & background.
- Auto-save/load settings to camera_settings.json upon close & launch.

Author : Antigravity DAQ Module
Date   : 2026-09-22
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Callable, Optional

import numpy as np

# Qt backend detection (PyQt6 / PySide6)
try:
    from PyQt6 import QtCore, QtGui, QtWidgets
    from PyQt6.QtCore import (
        QMutex, QMutexLocker, QObject, QThread, QTimer, Qt, pyqtSignal as Signal, pyqtSlot as Slot
    )
    from PyQt6.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
        QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
        QPushButton, QSizePolicy, QSpinBox, QSplitter, QStatusBar, QTabWidget,
        QVBoxLayout, QWidget,
    )
    _QT_BACKEND = "PyQt6"
except ImportError:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import (
        QMutex, QMutexLocker, QObject, QThread, QTimer, Qt, Signal, Slot
    )
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
        QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
        QPushButton, QSizePolicy, QSpinBox, QSplitter, QStatusBar, QTabWidget,
        QVBoxLayout, QWidget,
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

# Dark Modern CSS Style
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
QPushButton:disabled {
    background: #232734;
    color: #555e75;
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
QPushButton#browseBtn:hover {
    background: #475569;
}
QPushButton#cwBtnRunning {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #059669, stop:1 #047857);
    color: #ffffff;
    font-weight: bold;
    padding: 6px 14px;
    font-size: 12px;
}
QPushButton#cwBtnRunning:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #10b981, stop:1 #059669);
}
QPushButton#cwBtnStopped {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #dc2626, stop:1 #b91c1c);
    color: #ffffff;
    font-weight: bold;
    padding: 6px 14px;
    font-size: 12px;
}
QPushButton#cwBtnStopped:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ef4444, stop:1 #dc2626);
}
QTabWidget::pane {
    border: 1px solid #272d3d;
    background-color: #0f1117;
    border-radius: 6px;
    top: -1px;
}
QTabBar::tab {
    background: #171a23;
    color: #94a3b8;
    border: 1px solid #272d3d;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 22px;
    margin-right: 4px;
    font-weight: 600;
    font-size: 13px;
}
QTabBar::tab:selected {
    background: #1e2230;
    color: #38bdf8;
    border-color: #38bdf8;
    border-bottom: 2px solid #38bdf8;
}
QTabBar::tab:hover:!selected {
    background: #222736;
    color: #f1f5f9;
}
QLabel {
    color: #94a3b8;
}
QStatusBar {
    background-color: #0b0d12;
    color: #94a3b8;
    border-top: 1px solid #1e2230;
}
"""

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "camera_settings.json")


class CameraDisplayPanel(QWidget):
    """Viewport and control panel for a single GigE Camera channel."""
    
    name_changed = Signal(int, str)
    
    def __init__(
        self,
        cam_idx: int,
        default_name: str,
        controller: DualGigECameraController,
        save_dir_provider: Optional[Callable[[], str]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.cam_idx = cam_idx
        self.channel_name = default_name
        self.controller = controller
        self.save_dir_provider = save_dir_provider
        
        self.latest_frame: Optional[np.ndarray] = None
        self.latest_fit: Optional[GaussianFitResult] = None
        
        self._init_ui()
        self._init_graphics()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # Header: Channel Name & Quick Info
        header_box = QHBoxLayout()
        header_box.addWidget(QLabel("<b>Channel Name:</b>"))
        self.name_edit = QLineEdit(self.channel_name)
        self.name_edit.setPlaceholderText("Channel identifier (e.g. Cam_NearField)")
        self.name_edit.textChanged.connect(self._on_name_changed)
        header_box.addWidget(self.name_edit)
        
        self.status_badge = QLabel("● IDLE")
        self.status_badge.setStyleSheet("color: #94a3b8; font-weight: bold; font-size: 12px; padding: 2px 8px; background: #171a23; border-radius: 4px;")
        header_box.addWidget(self.status_badge)
        main_layout.addLayout(header_box)

        # Plot Widget / Image View
        self.gl_layout = pg.GraphicsLayoutWidget()
        self.gl_layout.setBackground("#000000")
        self.view = self.gl_layout.addViewBox(row=0, col=0, lockAspect=True, enableMouse=True)
        self.view.invertY(True)
        
        self.img_item = pg.ImageItem()
        self.view.addItem(self.img_item)
        
        # Color LUT / Hist
        self.hist_lut = pg.HistogramLUTItem(self.img_item)
        self.hist_lut.gradient.loadPreset("inferno")
        self.gl_layout.addItem(self.hist_lut, row=0, col=1)
        self.hist_lut.setMaximumWidth(110)
        
        main_layout.addWidget(self.gl_layout, stretch=1)

        # Live Hover Tracker Bar
        self.coord_label = QLabel("Cursor: (X: ----, Y: ----) | Intensity: ---- ADU")
        self.coord_label.setStyleSheet("color: #38bdf8; font-family: monospace; font-size: 11px;")
        main_layout.addWidget(self.coord_label)

        # Controls & Analysis Group
        ctrl_group = QGroupBox("Camera Controls & Diagnostics")
        ctrl_layout = QVBoxLayout(ctrl_group)
        ctrl_layout.setSpacing(6)

        # Row 1: Exposure & Gain
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Exposure (ms):"))
        self.exp_spin = QDoubleSpinBox()
        self.exp_spin.setRange(0.1, 5000.0)
        self.exp_spin.setValue(100.0)
        self.exp_spin.setSingleStep(5.0)
        self.exp_spin.valueChanged.connect(self._on_exposure_changed)
        row1.addWidget(self.exp_spin)

        row1.addWidget(QLabel("Gain (dB):"))
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(0.0, 24.0)
        self.gain_spin.setValue(0.0)
        self.gain_spin.setSingleStep(0.5)
        self.gain_spin.valueChanged.connect(self._on_gain_changed)
        row1.addWidget(self.gain_spin)
        ctrl_layout.addLayout(row1)

        # Row 2: Target Overlay & ROI settings
        row2 = QHBoxLayout()
        self.target_check = QCheckBox("Show Target Circle")
        self.target_check.setChecked(True)
        self.target_check.stateChanged.connect(self._on_target_toggle)
        row2.addWidget(self.target_check)

        self.roi_check = QCheckBox("Show ROI Box")
        self.roi_check.setChecked(True)
        self.roi_check.stateChanged.connect(self._on_roi_toggle)
        row2.addWidget(self.roi_check)
        
        self.bg_status_label = QLabel("BG: [None]")
        self.bg_status_label.setStyleSheet("color: #f59e0b; font-weight: bold;")
        row2.addWidget(self.bg_status_label)
        ctrl_layout.addLayout(row2)

        # Row 3: Action Buttons
        btn_row = QHBoxLayout()
        self.btn_record_bg = QPushButton("Record Background")
        self.btn_record_bg.setObjectName("recordBgBtn")
        self.btn_record_bg.clicked.connect(self._on_record_bg)
        btn_row.addWidget(self.btn_record_bg)

        self.btn_analyze = QPushButton("Analyze (2D Gaussian)")
        self.btn_analyze.setObjectName("analyzeBtn")
        self.btn_analyze.clicked.connect(self._on_analyze)
        btn_row.addWidget(self.btn_analyze)

        self.btn_save_shot = QPushButton("💾 Save Shot (TIFF)")
        self.btn_save_shot.setObjectName("saveBtn")
        self.btn_save_shot.clicked.connect(self._on_save_shot)
        btn_row.addWidget(self.btn_save_shot)
        ctrl_layout.addLayout(btn_row)

        # Results Display
        self.results_label = QLabel("Fit: [Not Analyzed]")
        self.results_label.setStyleSheet("color: #a7f3d0; font-family: monospace; font-size: 11px;")
        self.results_label.setWordWrap(True)
        ctrl_layout.addWidget(self.results_label)

        main_layout.addWidget(ctrl_group)

    def _init_graphics(self):
        # 1. Interactive Target Overlay (Draggable / Scalable Circle & Crosshair)
        self.target_circle = pg.CircleROI([762, 562], [100, 100], pen=pg.mkPen("#38bdf8", width=1.5, style=Qt.PenStyle.DashLine))
        self.target_circle.setZValue(10)
        self.view.addItem(self.target_circle)

        # Center crosshair for the target circle
        self.crosshair_v = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#38bdf8", width=1.0))
        self.crosshair_h = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen("#38bdf8", width=1.0))
        self.view.addItem(self.crosshair_v)
        self.view.addItem(self.crosshair_h)
        self.target_circle.sigRegionChanged.connect(self._update_crosshair_pos)

        # 2. ROI Box for Fitting
        self.roi_box = pg.RectROI([612, 412], [400, 400], pen=pg.mkPen("#f59e0b", width=1.5))
        self.roi_box.addScaleHandle([1, 1], [0, 0])
        self.roi_box.addScaleHandle([0, 0], [1, 1])
        self.roi_box.setZValue(9)
        self.view.addItem(self.roi_box)

        # 3. Fitted Centroid Marker & Fit Contour Ellipse
        self.fit_marker = pg.ScatterPlotItem(size=12, pen=pg.mkPen("#ef4444", width=2), brush=pg.mkBrush("#ef4444"))
        self.fit_marker.setZValue(12)
        self.view.addItem(self.fit_marker)

        # Mouse hover signal proxy
        self.proxy = pg.SignalProxy(self.gl_layout.scene().sigMouseMoved, rateLimit=30, slot=self._on_mouse_moved)

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

    def _on_name_changed(self, text: str):
        self.channel_name = text.strip() or f"Cam_{self.cam_idx}"
        self.controller.set_channel_name(self.cam_idx, self.channel_name)
        self.name_changed.emit(self.cam_idx, self.channel_name)

    def _on_exposure_changed(self, val_ms: float):
        self.controller.set_exposure_time(self.cam_idx, val_ms / 1000.0)

    def _on_gain_changed(self, val_db: float):
        self.controller.set_gain(self.cam_idx, val_db)

    def _on_target_toggle(self, state: int):
        visible = (state == 2 or state == Qt.CheckState.Checked.value if hasattr(Qt, "CheckState") else bool(state))
        self.target_circle.setVisible(visible)
        self.crosshair_v.setVisible(visible)
        self.crosshair_h.setVisible(visible)

    def _on_roi_toggle(self, state: int):
        visible = (state == 2 or state == Qt.CheckState.Checked.value if hasattr(Qt, "CheckState") else bool(state))
        self.roi_box.setVisible(visible)

    def _on_record_bg(self):
        try:
            bg = self.controller.record_background(self.cam_idx, num_averages=3)
            mean_bg = np.mean(bg)
            self.bg_status_label.setText(f"BG: [Mean {mean_bg:.1f}]")
            self.bg_status_label.setStyleSheet("color: #10b981; font-weight: bold;")
            QMessageBox.information(self, "Background Recorded",
                                    f"Channel '{self.channel_name}' background recorded.\nMean: {mean_bg:.1f} ADU")
        except Exception as e:
            QMessageBox.critical(self, "Background Error", str(e))

    def _on_analyze(self):
        if self.latest_frame is None:
            QMessageBox.warning(self, "Analyze", "No image frame available to analyze.")
            return

        # Extract ROI bounds
        pos = self.roi_box.pos()
        size = self.roi_box.size()
        x_min, y_min = int(pos.x()), int(pos.y())
        x_max, y_max = int(pos.x() + size.x()), int(pos.y() + size.y())

        fit = fit_2d_gaussian(self.latest_frame, roi_coords=(x_min, y_min, x_max, y_max))
        self.latest_fit = fit
        
        if fit.success:
            self.results_label.setText(
                f"Beam Center: ({fit.global_x0:.1f}, {fit.global_y0:.1f}) px | "
                f"FWHM (X/Y): ({fit.fwhm_x:.1f}, {fit.fwhm_y:.1f}) px | "
                f"RMSE: {fit.residual_rmse:.1f} ADU"
            )
            # Update fit marker position
            self.fit_marker.setData([{"pos": (fit.global_x0, fit.global_y0)}])
        else:
            self.results_label.setText(f"Fit failed: {fit.message}")
            self.fit_marker.clear()

    def _on_save_shot(self):
        if self.latest_frame is None:
            QMessageBox.warning(self, "Save Shot", "No image frame available.")
            return

        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
        target_dir = self.save_dir_provider() if self.save_dir_provider else os.getcwd()
        os.makedirs(target_dir, exist_ok=True)
        
        default_file = os.path.join(target_dir, f"{self.channel_name}_{timestamp_str}.tif")
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Shot (TIFF)", default_file, "TIFF Files (*.tif *.tiff)"
        )
        if file_path:
            extra = {}
            if self.latest_fit and self.latest_fit.success:
                extra["analysis"] = {
                    "center_x": self.latest_fit.global_x0,
                    "center_y": self.latest_fit.global_y0,
                    "fwhm_x": self.latest_fit.fwhm_x,
                    "fwhm_y": self.latest_fit.fwhm_y,
                    "rmse": self.latest_fit.residual_rmse,
                }
            
            saved_file = self.controller.save_tiff_with_metadata(
                filepath=file_path,
                index=self.cam_idx,
                image_data=self.latest_frame,
                extra_metadata=extra,
                embed_background=True,
            )
            QMessageBox.information(self, "File Saved", f"Successfully saved TIFF to:\n{saved_file}")

    def update_frame(self, frame: np.ndarray):
        """Update live view with raw frame (called at 10 Hz)."""
        self.latest_frame = frame
        self.img_item.setImage(frame, autoLevels=False)
        self.status_badge.setText("● LIVE")
        self.status_badge.setStyleSheet("color: #10b981; font-weight: bold; font-size: 12px; padding: 2px 8px; background: #171a23; border-radius: 4px;")

    def set_status_text(self, text: str, color_hex: str = "#94a3b8"):
        self.status_badge.setText(text)
        self.status_badge.setStyleSheet(f"color: {color_hex}; font-weight: bold; font-size: 12px; padding: 2px 8px; background: #171a23; border-radius: 4px;")

    def get_settings(self) -> dict:
        """Export settings for persistence."""
        target_pos = self.target_circle.pos()
        target_size = self.target_circle.size()
        roi_pos = self.roi_box.pos()
        roi_size = self.roi_box.size()
        
        return {
            "channel_name": self.channel_name,
            "exposure_ms": self.exp_spin.value(),
            "gain_db": self.gain_spin.value(),
            "target_circle": {
                "visible": self.target_check.isChecked(),
                "x": target_pos.x(),
                "y": target_pos.y(),
                "w": target_size.x(),
                "h": target_size.y(),
            },
            "roi_box": {
                "visible": self.roi_check.isChecked(),
                "x": roi_pos.x(),
                "y": roi_pos.y(),
                "w": roi_size.x(),
                "h": roi_size.y(),
            },
        }

    def apply_settings(self, cfg: dict):
        """Apply saved settings from dictionary."""
        if "channel_name" in cfg:
            self.name_edit.setText(cfg["channel_name"])
        if "exposure_ms" in cfg:
            self.exp_spin.setValue(float(cfg["exposure_ms"]))
        if "gain_db" in cfg:
            self.gain_spin.setValue(float(cfg["gain_db"]))
        
        if "target_circle" in cfg:
            tc = cfg["target_circle"]
            self.target_check.setChecked(tc.get("visible", True))
            if "x" in tc and "y" in tc and "w" in tc and "h" in tc:
                self.target_circle.setPos([tc["x"], tc["y"]])
                self.target_circle.setSize([tc["w"], tc["h"]])
                self._update_crosshair_pos()
                
        if "roi_box" in cfg:
            rb = cfg["roi_box"]
            self.roi_check.setChecked(rb.get("visible", True))
            if "x" in rb and "y" in rb and "w" in rb and "h" in rb:
                self.roi_box.setPos([rb["x"], rb["y"]])
                self.roi_box.setSize([rb["w"], rb["h"]])


class CameraGrabberThread(QThread):
    """Background acquisition thread grabbing frames at full camera rate."""
    
    frames_ready = Signal(object, object)  # (frame0, frame1)

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
                f0 = self.controller.grab_frame(0) if self.controller.drivers[0].is_capturing else None
                f1 = self.controller.grab_frame(1) if self.controller.drivers[1].is_capturing else None
                if f0 is not None or f1 is not None:
                    self.frames_ready.emit(f0, f1)
            except Exception as e:
                logger.debug("Grab error in thread: %s", e)
            
            time.sleep(0.01)

    def stop(self):
        with QMutexLocker(self._mutex):
            self._running = False
        self.wait(2000)


class DualGigECameraGUI(QMainWindow):
    """Main Application Window for Dual GigE Cameras."""

    def __init__(self, force_mock: bool = False):
        super().__init__()
        self.setWindowTitle("Dual GigE Camera Subsystem - DAQ & Diagnostics")
        self.resize(1200, 880)
        self.setStyleSheet(_STYLE)

        # State flags
        self.is_cw_running = True
        self.latest_f0: Optional[np.ndarray] = None
        self.latest_f1: Optional[np.ndarray] = None

        # Initialize Dual Controller
        self.controller = DualGigECameraController(
            serial_0=0, serial_1=1,
            name_0="Cam_NearField", name_1="Cam_FarField",
            force_mock=force_mock,
        )

        self._init_ui()
        self._load_settings()

        # Connect and Start Capture
        self._connect_cameras()

        # 10 Hz Display Timer for throttled UI updates
        self.display_timer = QTimer(self)
        self.display_timer.setInterval(100)  # 100 ms = 10 Hz (10 FPS)
        self.display_timer.timeout.connect(self._on_display_tick)

        # Start background grabber thread
        self.grabber_thread = CameraGrabberThread(self.controller)
        self.grabber_thread.frames_ready.connect(self._on_frames_received)
        self.grabber_thread.start()
        self.display_timer.start()

    def get_save_dir(self) -> str:
        """Return configured save directory path."""
        path = self.save_path_edit.text().strip()
        if not path:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        return os.path.abspath(path)

    def _init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Global Top Bar - Row 1: Title, CW Button, Trigger Mode, User Notes
        top_bar = QHBoxLayout()
        title_label = QLabel("<b>DUAL GIGE CAMERA SUBSYSTEM</b> (Grasshopper2)")
        title_label.setStyleSheet("font-size: 15px; color: #818cf8; font-weight: bold;")
        top_bar.addWidget(title_label)

        top_bar.addSpacing(16)

        # Button for switching CW Acquisition
        self.btn_cw_toggle = QPushButton("Stop CW Acquisition")
        self.btn_cw_toggle.setObjectName("cwBtnRunning")
        self.btn_cw_toggle.setToolTip("Toggle Continuous Wave (CW) live acquisition for both cameras")
        self.btn_cw_toggle.clicked.connect(self._on_toggle_cw)
        top_bar.addWidget(self.btn_cw_toggle)

        top_bar.addStretch()

        # Trigger mode selector
        top_bar.addWidget(QLabel("Trigger Mode:"))
        self.trigger_combo = QComboBox()
        self.trigger_combo.addItems(["INTERNAL/OFF (Free-Run)", "EXTERNAL_TTL (Hardware Burst)"])
        self.trigger_combo.currentIndexChanged.connect(self._on_trigger_mode_changed)
        top_bar.addWidget(self.trigger_combo)

        # User Notes Input
        top_bar.addWidget(QLabel("User Notes:"))
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("e.g. Near/Far field alignment run 001")
        self.notes_edit.setMinimumWidth(220)
        self.notes_edit.textChanged.connect(self._on_notes_changed)
        top_bar.addWidget(self.notes_edit)

        main_layout.addLayout(top_bar)

        # Global Top Bar - Row 2: File Path Textbox & Folder Browser for saving data
        path_bar = QHBoxLayout()
        path_bar.addWidget(QLabel("<b>Data Save Path:</b>"))
        default_data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        self.save_path_edit = QLineEdit(default_data_dir)
        self.save_path_edit.setPlaceholderText("Specify directory path where captured images & data will be saved...")
        path_bar.addWidget(self.save_path_edit, stretch=1)

        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.setObjectName("browseBtn")
        self.btn_browse.setToolTip("Select data destination folder")
        self.btn_browse.clicked.connect(self._on_browse_save_path)
        path_bar.addWidget(self.btn_browse)

        self.btn_open_dir = QPushButton("Open Folder")
        self.btn_open_dir.setObjectName("browseBtn")
        self.btn_open_dir.setToolTip("Open save folder in Windows Explorer")
        self.btn_open_dir.clicked.connect(self._on_open_save_folder)
        path_bar.addWidget(self.btn_open_dir)

        main_layout.addLayout(path_bar)

        # Tab Widget separating the 2 camera images
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        self.cam_panel_0 = CameraDisplayPanel(0, "Cam_NearField", self.controller, save_dir_provider=self.get_save_dir)
        self.cam_panel_1 = CameraDisplayPanel(1, "Cam_FarField", self.controller, save_dir_provider=self.get_save_dir)

        self.cam_panel_0.name_changed.connect(self._on_channel_name_changed)
        self.cam_panel_1.name_changed.connect(self._on_channel_name_changed)

        self.tabs.addTab(self.cam_panel_0, f"Cam 0: {self.cam_panel_0.channel_name}")
        self.tabs.addTab(self.cam_panel_1, f"Cam 1: {self.cam_panel_1.channel_name}")

        main_layout.addWidget(self.tabs, stretch=1)

        # Status Bar
        self.statusBar().showMessage("Ready | 10 Hz Live Display Engine Active | CW Acquisition ON")

    def _on_channel_name_changed(self, cam_idx: int, name: str):
        """Update tab label when camera channel name is changed."""
        self.tabs.setTabText(cam_idx, f"Cam {cam_idx}: {name}")

    def _on_toggle_cw(self):
        """Switch CW acquisition ON / OFF."""
        if self.is_cw_running:
            # Stop CW acquisition
            self.controller.stop_capture_all()
            self.is_cw_running = False
            self.btn_cw_toggle.setText("Start CW Acquisition")
            self.btn_cw_toggle.setObjectName("cwBtnStopped")
            self.btn_cw_toggle.style().unpolish(self.btn_cw_toggle)
            self.btn_cw_toggle.style().polish(self.btn_cw_toggle)
            
            self.cam_panel_0.set_status_text("● PAUSED", "#ef4444")
            self.cam_panel_1.set_status_text("● PAUSED", "#ef4444")
            self.statusBar().showMessage("CW Acquisition Paused / Stopped.")
        else:
            # Start CW acquisition
            self.controller.start_capture_all()
            self.is_cw_running = True
            self.btn_cw_toggle.setText("Stop CW Acquisition")
            self.btn_cw_toggle.setObjectName("cwBtnRunning")
            self.btn_cw_toggle.style().unpolish(self.btn_cw_toggle)
            self.btn_cw_toggle.style().polish(self.btn_cw_toggle)
            
            self.cam_panel_0.set_status_text("● LIVE", "#10b981")
            self.cam_panel_1.set_status_text("● LIVE", "#10b981")
            self.statusBar().showMessage("CW Acquisition Running...")

    def _on_browse_save_path(self):
        """Interactive folder selection for data saving."""
        curr_dir = self.get_save_dir()
        selected_dir = QFileDialog.getExistingDirectory(self, "Select Save Directory", curr_dir)
        if selected_dir:
            self.save_path_edit.setText(selected_dir)
            self.statusBar().showMessage(f"Save directory set to: {selected_dir}")

    def _on_open_save_folder(self):
        """Open target save directory in file explorer."""
        target = self.get_save_dir()
        os.makedirs(target, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(target)
        else:
            import subprocess
            subprocess.Popen(["xdg-open", target])

    def _connect_cameras(self):
        c0, c1 = self.controller.connect_all()
        self.controller.start_capture_all()
        msg = f"Cameras: Cam0={'OK' if c0 else 'FAIL'}, Cam1={'OK' if c1 else 'FAIL'} | CW Acquisition Active"
        self.statusBar().showMessage(msg)

    def _on_trigger_mode_changed(self, idx: int):
        mode = "EXTERNAL_TTL" if idx == 1 else "INTERNAL/OFF"
        self.controller.set_trigger_mode(mode)
        self.statusBar().showMessage(f"Trigger mode switched to: {mode}")

    def _on_notes_changed(self, text: str):
        self.controller.user_notes = text.strip()

    @Slot(object, object)
    def _on_frames_received(self, f0, f1):
        if f0 is not None:
            self.latest_f0 = f0
        if f1 is not None:
            self.latest_f1 = f1

    def _on_display_tick(self):
        """Timer callback at strictly 10 Hz."""
        if not self.is_cw_running:
            return
            
        if self.latest_f0 is not None:
            self.cam_panel_0.update_frame(self.latest_f0)
            self.latest_f0 = None
        if self.latest_f1 is not None:
            self.cam_panel_1.update_frame(self.latest_f1)
            self.latest_f1 = None

    def _load_settings(self):
        """Load settings from camera_settings.json."""
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if "user_notes" in cfg:
                    self.notes_edit.setText(cfg["user_notes"])
                if "save_directory" in cfg:
                    self.save_path_edit.setText(cfg["save_directory"])
                if "cam_0" in cfg:
                    self.cam_panel_0.apply_settings(cfg["cam_0"])
                    self._on_channel_name_changed(0, self.cam_panel_0.channel_name)
                if "cam_1" in cfg:
                    self.cam_panel_1.apply_settings(cfg["cam_1"])
                    self._on_channel_name_changed(1, self.cam_panel_1.channel_name)
                logger.info("Settings loaded from %s", SETTINGS_FILE)
            except Exception as e:
                logger.warning("Failed to load settings: %s", e)

    def _save_settings(self):
        """Save settings to camera_settings.json."""
        try:
            cfg = {
                "user_notes": self.notes_edit.text(),
                "save_directory": self.save_path_edit.text().strip(),
                "cam_0": self.cam_panel_0.get_settings(),
                "cam_1": self.cam_panel_1.get_settings(),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            logger.info("Settings saved to %s", SETTINGS_FILE)
        except Exception as e:
            logger.error("Failed to save settings: %s", e)

    def closeEvent(self, event):
        """Clean teardown on window close."""
        self.display_timer.stop()
        self.grabber_thread.stop()
        self._save_settings()
        self.controller.stop_capture_all()
        self.controller.disconnect_all()
        event.accept()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    app = QApplication(sys.argv)
    window = DualGigECameraGUI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

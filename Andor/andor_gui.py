"""
andor_gui.py
------------
PyQt6 / PySide6 GUI for the Andor CCD camera driver.

Features
--------
* Live 2-D image display via pyqtgraph ImageView with selectable colormaps
* Exposure time, trigger mode, and frame count controls
* Background QThread acquisition worker (non-blocking UI)
* Simulation / real hardware toggle
* Status bar with camera mode indicator
* Frame statistics overlay (min, max, mean)

Dependencies
------------
    pip install PyQt6 pyqtgraph numpy
    -- OR --
    pip install PySide6 pyqtgraph numpy

Usage
-----
    python andor_gui.py
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Qt shim – try PyQt6 first, then PySide6
# ---------------------------------------------------------------------------
try:
    from PyQt6 import QtCore, QtGui, QtWidgets
    from PyQt6.QtCore import (
        QObject, QThread, QTimer, Qt, pyqtSignal as Signal, pyqtSlot as Slot
    )
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QGroupBox, QLabel, QDoubleSpinBox, QSpinBox, QComboBox, QPushButton,
        QStatusBar, QSizePolicy, QFrame, QSplitter, QMessageBox,
    )
    from PyQt6.QtGui import QFont, QColor, QPalette, QIcon
    _QT_BACKEND = "PyQt6"
except ImportError:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import (
        QObject, QThread, QTimer, Qt, Signal, Slot
    )
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QGroupBox, QLabel, QDoubleSpinBox, QSpinBox, QComboBox, QPushButton,
        QStatusBar, QSizePolicy, QFrame, QSplitter, QMessageBox,
    )
    from PySide6.QtGui import QFont, QColor, QPalette, QIcon
    _QT_BACKEND = "PySide6"

import pyqtgraph as pg

from andor_driver import AndorCameraDriver, DRV_IDLE, DRV_ACQUIRING

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colour palette constants
# ---------------------------------------------------------------------------
BG_DARK        = "#0d0f14"
BG_PANEL       = "#13161f"
BG_CARD        = "#1a1d28"
ACCENT_BLUE    = "#3b82f6"
ACCENT_CYAN    = "#22d3ee"
ACCENT_EMERALD = "#10b981"
ACCENT_ROSE    = "#f43f5e"
ACCENT_AMBER   = "#f59e0b"
TEXT_PRIMARY   = "#e2e8f0"
TEXT_MUTED     = "#64748b"
BORDER         = "#2d3149"

BUTTON_STYLE_PRIMARY = f"""
QPushButton {{
    background-color: {ACCENT_BLUE};
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.3px;
}}
QPushButton:hover {{
    background-color: #60a5fa;
}}
QPushButton:pressed {{
    background-color: #2563eb;
}}
QPushButton:disabled {{
    background-color: #334155;
    color: {TEXT_MUTED};
}}
"""

BUTTON_STYLE_SUCCESS = f"""
QPushButton {{
    background-color: {ACCENT_EMERALD};
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: #34d399;
}}
QPushButton:pressed {{
    background-color: #059669;
}}
QPushButton:disabled {{
    background-color: #334155;
    color: {TEXT_MUTED};
}}
"""

BUTTON_STYLE_DANGER = f"""
QPushButton {{
    background-color: {ACCENT_ROSE};
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: #fb7185;
}}
QPushButton:pressed {{
    background-color: #be123c;
}}
QPushButton:disabled {{
    background-color: #334155;
    color: {TEXT_MUTED};
}}
"""

SPINBOX_STYLE = f"""
QDoubleSpinBox, QSpinBox {{
    background-color: {BG_DARK};
    color: {TEXT_PRIMARY};
    border: 1.5px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    font-size: 13px;
    selection-background-color: {ACCENT_BLUE};
}}
QDoubleSpinBox:focus, QSpinBox:focus {{
    border-color: {ACCENT_BLUE};
}}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QSpinBox::up-button, QSpinBox::down-button {{
    width: 20px;
    background-color: {BG_CARD};
    border-left: 1px solid {BORDER};
}}
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover,
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background-color: {ACCENT_BLUE};
}}
"""

COMBO_STYLE = f"""
QComboBox {{
    background-color: {BG_DARK};
    color: {TEXT_PRIMARY};
    border: 1.5px solid {BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 13px;
    min-width: 160px;
}}
QComboBox:focus {{
    border-color: {ACCENT_BLUE};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT_BLUE};
    border: 1px solid {BORDER};
}}
"""

LABEL_STYLE = f"color: {TEXT_MUTED}; font-size: 11px; font-weight: 500;"
VALUE_LABEL_STYLE = f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: 600;"

GROUP_STYLE = f"""
QGroupBox {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 14px;
    padding: 10px 12px 12px 12px;
    color: {TEXT_PRIMARY};
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.8px;
    text-transform: uppercase;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: {ACCENT_CYAN};
}}
"""


# ---------------------------------------------------------------------------
# Acquisition worker (QThread)
# ---------------------------------------------------------------------------

class AcquisitionWorker(QObject):
    """
    Runs in a separate QThread.
    Acquires a single frame and emits it as a signal.
    """

    frame_ready  = Signal(np.ndarray)   # emits uint16 (H x W) array
    error        = Signal(str)
    finished     = Signal()

    def __init__(
        self,
        driver: AndorCameraDriver,
        exposure_s: float,
        trigger_mode: int,
    ) -> None:
        super().__init__()
        self._driver       = driver
        self._exposure_s   = exposure_s
        self._trigger_mode = trigger_mode
        self._running      = False

    @Slot()
    def run(self) -> None:
        self._running = True
        try:
            self._driver.set_exposure_time(self._exposure_s)
            self._driver.set_trigger_mode(self._trigger_mode)
            # acq_mode=1 is Single Scan (single shot)
            self._driver.set_acquisition_params(num_frames=1, acq_mode=1)
            self._driver.start_acquisition()

            self._driver.wait_for_acquisition()
            if self._running:
                frame = self._driver.get_acquired_data16()
                self.frame_ready.emit(frame)

        except Exception as exc:
            logger.exception("Acquisition error: %s", exc)
            self.error.emit(str(exc))
        finally:
            try:
                self._driver.abort_acquisition()
            except Exception:
                pass
            self._running = False
            self.finished.emit()

    def stop(self) -> None:
        self._running = False
        try:
            self._driver.abort_acquisition()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Stat Badge widget
# ---------------------------------------------------------------------------

class StatBadge(QFrame):
    """Small labelled numeric badge for statistics overlay."""

    def __init__(self, label: str, unit: str = "", parent=None) -> None:
        super().__init__(parent)
        self._unit = unit
        self.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(30, 35, 50, 180);
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 4px 10px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setSpacing(2)
        layout.setContentsMargins(6, 4, 6, 4)

        self._lbl = QLabel(label)
        self._lbl.setStyleSheet(LABEL_STYLE)
        self._val = QLabel("—")
        self._val.setStyleSheet(VALUE_LABEL_STYLE)

        layout.addWidget(self._lbl)
        layout.addWidget(self._val)

    def set_value(self, v: float) -> None:
        self._val.setText(f"{v:.0f}{self._unit}")


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class AndorMainWindow(QMainWindow):
    """
    Main application window.

    Layout
    ------
    ┌─────────────────────────────────────────────────────────┐
    │  Header bar  (title + mode badge)                       │
    ├──────────────────┬──────────────────────────────────────┤
    │  Control Panel   │          Image View (pyqtgraph)       │
    │  ─ Camera        │                                      │
    │  ─ Acquisition   │   [min] [max] [mean] stat badges     │
    │  ─ Display       │                                      │
    │  ─ Action Btns   │                                      │
    └──────────────────┴──────────────────────────────────────┘
    │  Status bar                                             │
    └─────────────────────────────────────────────────────────┘
    """

    def __init__(self) -> None:
        super().__init__()
        self._driver: Optional[AndorCameraDriver] = None
        self._worker: Optional[AcquisitionWorker] = None
        self._thread: Optional[QThread]           = None
        self._frame_count: int = 0

        self._setup_ui()
        self._apply_global_style()
        self._update_button_states()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle("Andor CCD Camera Control")
        self.resize(1280, 780)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # --- Header ---
        root_layout.addWidget(self._make_header())

        # --- Main content (splitter) ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(3)
        splitter.setStyleSheet(f"QSplitter::handle {{ background: {BORDER}; }}")

        splitter.addWidget(self._make_control_panel())
        splitter.addWidget(self._make_image_panel())
        splitter.setSizes([310, 970])

        root_layout.addWidget(splitter)

        # --- Status bar ---
        self.statusBar().setStyleSheet(f"""
            QStatusBar {{
                background: {BG_PANEL};
                color: {TEXT_MUTED};
                font-size: 11px;
                border-top: 1px solid {BORDER};
                padding: 2px 12px;
            }}
        """)
        self._status_label = QLabel("Ready")
        self._mode_badge   = QLabel("● SIMULATION")
        self._mode_badge.setStyleSheet(f"color: {ACCENT_AMBER}; font-weight: 700; font-size: 11px;")
        self.statusBar().addWidget(self._status_label)
        self.statusBar().addPermanentWidget(self._mode_badge)

    def _make_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(58)
        header.setStyleSheet(f"""
            QWidget {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {BG_PANEL},
                    stop:1 #111827
                );
                border-bottom: 1px solid {BORDER};
            }}
        """)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(20, 0, 20, 0)

        # Icon + title
        title = QLabel("⬡  Andor CCD Camera Control")
        title.setStyleSheet(f"""
            color: {TEXT_PRIMARY};
            font-size: 17px;
            font-weight: 700;
            letter-spacing: 0.5px;
        """)
        lay.addWidget(title)
        lay.addStretch()

        # Frame counter
        self._frame_counter_lbl = QLabel("Frames: 0")
        self._frame_counter_lbl.setStyleSheet(
            f"color: {ACCENT_CYAN}; font-size: 12px; font-weight: 600;"
        )
        lay.addWidget(self._frame_counter_lbl)

        return header

    def _make_control_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(310)
        panel.setStyleSheet(f"background-color: {BG_PANEL};")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)

        layout.addWidget(self._make_camera_group())
        layout.addWidget(self._make_acquisition_group())
        layout.addWidget(self._make_display_group())
        layout.addWidget(self._make_action_group())
        layout.addStretch()

        return panel

    def _make_camera_group(self) -> QGroupBox:
        grp = QGroupBox("Camera")
        grp.setStyleSheet(GROUP_STYLE)
        lay = QVBoxLayout(grp)
        lay.setSpacing(8)

        # SDK path label
        sdk_lbl = QLabel("SDK Path")
        sdk_lbl.setStyleSheet(LABEL_STYLE)
        self._sdk_path_lbl = QLabel(r"C:\Program Files\Andor SDK")
        self._sdk_path_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 10px; word-wrap: break-word;"
        )
        self._sdk_path_lbl.setWordWrap(True)

        # Simulation toggle
        sim_row = QHBoxLayout()
        sim_lbl = QLabel("Mode")
        sim_lbl.setStyleSheet(LABEL_STYLE)
        self._sim_combo = QComboBox()
        self._sim_combo.addItems(["Auto-detect", "Simulation", "Real Hardware"])
        self._sim_combo.setStyleSheet(COMBO_STYLE)

        sim_row.addWidget(sim_lbl)
        sim_row.addWidget(self._sim_combo)

        self._init_btn = QPushButton("Initialize Camera")
        self._init_btn.setStyleSheet(BUTTON_STYLE_PRIMARY)
        self._init_btn.clicked.connect(self._on_initialize)

        self._detector_lbl = QLabel("Detector: —")
        self._detector_lbl.setStyleSheet(
            f"color: {ACCENT_CYAN}; font-size: 11px; font-weight: 600;"
        )

        lay.addWidget(sdk_lbl)
        lay.addWidget(self._sdk_path_lbl)
        lay.addLayout(sim_row)
        lay.addWidget(self._init_btn)
        lay.addWidget(self._detector_lbl)
        return grp

    def _make_acquisition_group(self) -> QGroupBox:
        grp = QGroupBox("Acquisition")
        grp.setStyleSheet(GROUP_STYLE)
        lay = QVBoxLayout(grp)
        lay.setSpacing(8)

        # Exposure
        exp_lbl = QLabel("Exposure Time (s)")
        exp_lbl.setStyleSheet(LABEL_STYLE)
        self._exp_spin = QDoubleSpinBox()
        self._exp_spin.setRange(0.001, 60.0)
        self._exp_spin.setSingleStep(0.01)
        self._exp_spin.setDecimals(4)
        self._exp_spin.setValue(0.1)
        self._exp_spin.setStyleSheet(SPINBOX_STYLE)

        # Trigger mode
        trig_lbl = QLabel("Trigger Mode")
        trig_lbl.setStyleSheet(LABEL_STYLE)
        self._trig_combo = QComboBox()
        self._trig_combo.addItems([
            "Internal Trigger (Mode 0)",
            "External Trigger (Mode 1)",
        ])
        self._trig_combo.setStyleSheet(COMBO_STYLE)

        lay.addWidget(exp_lbl)
        lay.addWidget(self._exp_spin)
        lay.addWidget(trig_lbl)
        lay.addWidget(self._trig_combo)
        return grp

    def _make_display_group(self) -> QGroupBox:
        grp = QGroupBox("Display")
        grp.setStyleSheet(GROUP_STYLE)
        lay = QVBoxLayout(grp)
        lay.setSpacing(8)

        cmap_lbl = QLabel("Colormap")
        cmap_lbl.setStyleSheet(LABEL_STYLE)
        self._cmap_combo = QComboBox()
        self._cmap_combo.addItems([
            "viridis", "inferno", "plasma", "magma",
            "grey", "hot", "thermal",
        ])
        self._cmap_combo.setStyleSheet(COMBO_STYLE)
        self._cmap_combo.currentTextChanged.connect(self._on_cmap_change)

        lay.addWidget(cmap_lbl)
        lay.addWidget(self._cmap_combo)
        return grp

    def _make_action_group(self) -> QGroupBox:
        grp = QGroupBox("Actions")
        grp.setStyleSheet(GROUP_STYLE)
        lay = QVBoxLayout(grp)
        lay.setSpacing(8)

        self._start_btn = QPushButton("▶  Capture Single Shot")
        self._start_btn.setStyleSheet(BUTTON_STYLE_SUCCESS)
        self._start_btn.clicked.connect(self._on_start)

        self._stop_btn = QPushButton("■  Abort Acquisition")
        self._stop_btn.setStyleSheet(BUTTON_STYLE_DANGER)
        self._stop_btn.clicked.connect(self._on_stop)

        lay.addWidget(self._start_btn)
        lay.addWidget(self._stop_btn)
        return grp

    def _make_image_panel(self) -> QWidget:
        container = QWidget()
        container.setStyleSheet(f"background-color: {BG_DARK};")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # pyqtgraph ImageView
        pg.setConfigOptions(antialias=True, background=BG_DARK)
        self._image_view = pg.ImageView()
        self._image_view.ui.histogram.gradient.loadPreset("viridis")
        self._image_view.ui.roiBtn.hide()
        self._image_view.ui.menuBtn.hide()
        self._image_view.setStyleSheet(f"background: {BG_DARK}; border: none;")

        layout.addWidget(self._image_view)

        # Stat badges row
        stats_row = QHBoxLayout()
        stats_row.setSpacing(8)
        self._stat_min  = StatBadge("MIN", " ADU")
        self._stat_max  = StatBadge("MAX", " ADU")
        self._stat_mean = StatBadge("MEAN", " ADU")
        stats_row.addWidget(self._stat_min)
        stats_row.addWidget(self._stat_max)
        stats_row.addWidget(self._stat_mean)
        stats_row.addStretch()

        layout.addLayout(stats_row)
        self._last_frame_time: Optional[float] = None

        return container

    # ------------------------------------------------------------------
    # Global stylesheet
    # ------------------------------------------------------------------

    def _apply_global_style(self) -> None:
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background-color: {BG_DARK};
                color: {TEXT_PRIMARY};
                font-family: 'Segoe UI', 'Inter', sans-serif;
            }}
            QScrollBar:vertical {{
                background: {BG_DARK};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {BORDER};
                border-radius: 4px;
            }}
        """)

    # ------------------------------------------------------------------
    # Slots / event handlers
    # ------------------------------------------------------------------

    @Slot()
    def _on_initialize(self) -> None:
        """Initialize (or re-initialize) the camera driver."""
        if self._driver and self._driver.is_initialized:
            try:
                self._driver.shutdown()
            except Exception:
                pass

        sim_idx = self._sim_combo.currentIndex()
        simulation: Optional[bool] = {0: None, 1: True, 2: False}.get(sim_idx)

        try:
            self._driver = AndorCameraDriver(simulation=simulation)
            self._driver.initialize()
        except Exception as exc:
            QMessageBox.critical(self, "Initialization Error", str(exc))
            self._set_status(f"Error: {exc}")
            return

        w, h = self._driver.detector_size
        self._detector_lbl.setText(f"Detector: {w} × {h} px")

        is_sim = self._driver.is_simulated
        self._mode_badge.setText("● SIMULATION" if is_sim else "● HARDWARE")
        self._mode_badge.setStyleSheet(
            f"color: {ACCENT_AMBER if is_sim else ACCENT_EMERALD}; "
            f"font-weight: 700; font-size: 11px;"
        )
        self._set_status(
            f"Camera initialized ({'simulation' if is_sim else 'hardware'} – "
            f"{w}×{h} px)"
        )
        self._update_button_states()

    @Slot()
    def _on_start(self) -> None:
        """Start background acquisition thread."""
        if self._driver is None or not self._driver.is_initialized:
            QMessageBox.warning(self, "Camera Not Ready",
                                "Please initialize the camera first.")
            return
        if self._thread is not None:
            try:
                if self._thread.isRunning():
                    return
            except RuntimeError:
                self._thread = None
                self._worker = None

        exposure_s   = self._exp_spin.value()
        trigger_mode = self._trig_combo.currentIndex()

        self._worker = AcquisitionWorker(
            self._driver, exposure_s, trigger_mode
        )
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.frame_ready.connect(self._on_frame_ready)
        self._worker.error.connect(self._on_acq_error)
        self._worker.finished.connect(self._on_acq_finished)
        self._worker.finished.connect(self._thread.quit)

        # Clean references when thread finishes
        self._thread.finished.connect(self._on_thread_finished)

        self._thread.start()
        self._set_status("Acquiring single shot…")
        self._update_button_states(acquiring=True)

    @Slot()
    def _on_stop(self) -> None:
        """Request the worker to stop / abort acquisition."""
        if self._worker:
            self._worker.stop()
        if self._driver:
            try:
                self._driver.abort_acquisition()
            except Exception:
                pass
        self._set_status("Aborting acquisition…")

    @Slot(np.ndarray)
    def _on_frame_ready(self, frame: np.ndarray) -> None:
        """Receive a single frame and update the display."""
        self._frame_count += 1
        self._frame_counter_lbl.setText(f"Frames: {self._frame_count}")

        # Statistics
        self._stat_min.set_value(float(frame.min()))
        self._stat_max.set_value(float(frame.max()))
        self._stat_mean.set_value(float(frame.mean()))

        # Display (pyqtgraph expects row-major; transpose if needed)
        self._image_view.setImage(
            frame.T,
            autoRange=False,
            autoLevels=True,
            autoHistogramRange=True,
        )

    @Slot(str)
    def _on_acq_error(self, msg: str) -> None:
        QMessageBox.critical(self, "Acquisition Error", msg)
        self._set_status(f"Error: {msg}")

    @Slot()
    def _on_acq_finished(self) -> None:
        self._set_status(
            f"Single shot complete – total frames: {self._frame_count}"
        )
        self._update_button_states(acquiring=False)

    @Slot()
    def _on_thread_finished(self) -> None:
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        if self._thread:
            self._thread.deleteLater()
            self._thread = None

    @Slot(str)
    def _on_cmap_change(self, name: str) -> None:
        """Apply a new colormap to the ImageView histogram."""
        try:
            self._image_view.ui.histogram.gradient.loadPreset(name)
        except KeyError:
            # Custom colormaps not in pyqtgraph presets – fall back to grey
            self._image_view.ui.histogram.gradient.loadPreset("grey")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, msg: str) -> None:
        self._status_label.setText(msg)
        logger.info("Status: %s", msg)

    def _update_button_states(self, acquiring: bool = False) -> None:
        initialized = bool(self._driver and self._driver.is_initialized)
        self._init_btn.setEnabled(not acquiring)
        self._start_btn.setEnabled(initialized and not acquiring)
        self._stop_btn.setEnabled(acquiring)
        self._exp_spin.setEnabled(not acquiring)
        self._trig_combo.setEnabled(not acquiring)
        self._sim_combo.setEnabled(not acquiring)

    # ------------------------------------------------------------------
    # Clean-up on close
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self._worker:
            self._worker.stop()
        if self._thread is not None:
            try:
                if self._thread.isRunning():
                    self._thread.quit()
                    self._thread.wait(3000)
            except RuntimeError:
                pass
            self._thread = None
            self._worker = None
        if self._driver:
            try:
                self._driver.shutdown()
            except Exception:
                pass
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Andor CCD Control")
    app.setOrganizationName("DAQ_CA")

    # Global font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    win = AndorMainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

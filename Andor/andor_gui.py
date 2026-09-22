"""
andor_gui.py
------------
PyQt6 / PySide6 GUI for the Andor CCD camera driver.

Features
--------
* Live 2-D image display via pyqtgraph ImageView with selectable colormaps
* Tabbed display:
    - Tab 1: "Raw Image" (pixel coordinates)
    - Tab 2: "Wavelength Calibrated" (CDS calibrated x-axis in nm, background-subtracted)
* CDS wavelength calibration from grating diffraction parameters:
    - d_gt = 278 nm, m_diff = 1, gamma_toroi = 3.75 deg, R = 1926 mm,
      px = 13.5e-3 mm, x0 = 963 px, theta_0 adjustable
* Stateful rolling background subtraction acquisition loop:
    - a. Acquire initial background B_0
    - b. Await hardware/software trigger for new shot
    - c. Acquire raw data D_k, compute S_k = D_k - B_{k-1}, display S_k
    - d. Immediately acquire new background B_k for next shot (k+1)
* Single-shot acquisition mode
* TIFF data & metadata persistence (D_k, B_k, S_k) with JSON-formatted ImageDescription
* Output directory destination UI with "Browse..." button
* "My Note" custom note text entry field attached to metadata
* Local JSON state persistence (andor_settings.json) on shutdown and restore on startup
* Thread-isolated background workers (QThread) to ensure non-blocking UI
* Simulation / real hardware toggle
* Status bar with camera mode indicator & frame/shot statistics

Dependencies
------------
    pip install PyQt6 pyqtgraph numpy tifffile
    -- OR --
    pip install PySide6 pyqtgraph numpy tifffile

Usage
-----
    python andor_gui.py
"""

from __future__ import annotations

import datetime
import json
import logging
import pathlib
import sys
import time
from typing import Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Qt shim – try PyQt6 first, then PySide6
# ---------------------------------------------------------------------------
try:
    from PyQt6 import QtCore, QtGui, QtWidgets
    from PyQt6.QtCore import (
        QObject, QThread, QTimer, Qt, pyqtSignal as Signal, pyqtSlot as Slot,
    )
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QGroupBox, QLabel, QDoubleSpinBox, QSpinBox, QComboBox, QPushButton,
        QStatusBar, QSizePolicy, QFrame, QSplitter, QMessageBox,
        QLineEdit, QTabWidget, QFileDialog, QScrollArea,
    )
    from PyQt6.QtGui import QFont, QColor, QPalette, QIcon, QTransform
    _QT_BACKEND = "PyQt6"
except ImportError:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import (
        QObject, QThread, QTimer, Qt, Signal, Slot,
    )
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QGroupBox, QLabel, QDoubleSpinBox, QSpinBox, QComboBox, QPushButton,
        QStatusBar, QSizePolicy, QFrame, QSplitter, QMessageBox,
        QLineEdit, QTabWidget, QFileDialog, QScrollArea,
    )
    from PySide6.QtGui import QFont, QColor, QPalette, QIcon, QTransform
    _QT_BACKEND = "PySide6"

import pyqtgraph as pg

try:
    import tifffile as _tifffile
    _TIFFFILE_AVAILABLE = True
except ImportError:
    _TIFFFILE_AVAILABLE = False

from andor_driver import AndorCameraDriver, DRV_IDLE, DRV_ACQUIRING

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CDS Grating / Spectrometer Constants
# Mirrors CalculateEnergy_260415.m line 6:
# d_gt = 278; m_diff = 1; gamma_toroi = 3.75; R = 1926; px = 13.5e-3; x0 = 963;
# ---------------------------------------------------------------------------
D_GT_NM         = 278.0        # grating period in nm
M_DIFF          = 1            # diffraction order
GAMMA_TOROI_DEG = 3.75         # toroidal angle in degrees
R_MM            = 1926.0       # spectrometer radius in mm
PX_MM           = 13.5e-3      # pixel size in mm
X0_PX           = 963.0        # center pixel (1-indexed)

# Path to local state file
_SETTINGS_PATH = pathlib.Path(__file__).parent / "andor_settings.json"

# ---------------------------------------------------------------------------
# Color palette constants
# ---------------------------------------------------------------------------
BG_DARK        = "#0d0f14"
BG_PANEL       = "#13161f"
BG_CARD        = "#1a1d28"
ACCENT_BLUE    = "#3b82f6"
ACCENT_CYAN    = "#22d3ee"
ACCENT_EMERALD = "#10b981"
ACCENT_ROSE    = "#f43f5e"
ACCENT_AMBER   = "#f59e0b"
ACCENT_VIOLET  = "#8b5cf6"
TEXT_PRIMARY   = "#e2e8f0"
TEXT_MUTED     = "#64748b"
BORDER         = "#2d3149"

BUTTON_STYLE_PRIMARY = f"""
QPushButton {{
    background-color: {ACCENT_BLUE};
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.3px;
}}
QPushButton:hover {{ background-color: #60a5fa; }}
QPushButton:pressed {{ background-color: #2563eb; }}
QPushButton:disabled {{ background-color: #334155; color: {TEXT_MUTED}; }}
"""

BUTTON_STYLE_SUCCESS = f"""
QPushButton {{
    background-color: {ACCENT_EMERALD};
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton:hover {{ background-color: #34d399; }}
QPushButton:pressed {{ background-color: #059669; }}
QPushButton:disabled {{ background-color: #334155; color: {TEXT_MUTED}; }}
"""

BUTTON_STYLE_DANGER = f"""
QPushButton {{
    background-color: {ACCENT_ROSE};
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton:hover {{ background-color: #fb7185; }}
QPushButton:pressed {{ background-color: #be123c; }}
QPushButton:disabled {{ background-color: #334155; color: {TEXT_MUTED}; }}
"""

BUTTON_STYLE_VIOLET = f"""
QPushButton {{
    background-color: {ACCENT_VIOLET};
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton:hover {{ background-color: #a78bfa; }}
QPushButton:pressed {{ background-color: #6d28d9; }}
QPushButton:disabled {{ background-color: #334155; color: {TEXT_MUTED}; }}
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
QDoubleSpinBox:focus, QSpinBox:focus {{ border-color: {ACCENT_BLUE}; }}
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
    min-width: 150px;
}}
QComboBox:focus {{ border-color: {ACCENT_BLUE}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT_BLUE};
    border: 1px solid {BORDER};
}}
"""

LINEEDIT_STYLE = f"""
QLineEdit {{
    background-color: {BG_DARK};
    color: {TEXT_PRIMARY};
    border: 1.5px solid {BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
}}
QLineEdit:focus {{ border-color: {ACCENT_BLUE}; }}
"""

LABEL_STYLE       = f"color: {TEXT_MUTED}; font-size: 11px; font-weight: 500;"
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

TAB_STYLE = f"""
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    background: {BG_DARK};
}}
QTabBar::tab {{
    background: {BG_CARD};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 7px 18px;
    font-size: 12px;
    font-weight: 600;
    min-width: 150px;
}}
QTabBar::tab:selected {{
    background: {BG_DARK};
    color: {ACCENT_CYAN};
    border-bottom: 2px solid {ACCENT_CYAN};
}}
QTabBar::tab:hover:!selected {{
    background: #1e2336;
    color: {TEXT_PRIMARY};
}}
"""


# ---------------------------------------------------------------------------
# CDS Wavelength Calibration Function
# ---------------------------------------------------------------------------

def calculate_lambda_vec(n_cols: int, theta0_deg: float) -> np.ndarray:
    """
    Calculate the CDS wavelength vector lambda(x) for column indices 1 ... N_cols.

    Formula from calculateenergy.m:
        delta_theta(x) = atan2d((x - x0) * px, R * sind(gamma_toroi))
        lambda(x) = (d_gt / m_diff) * sind(gamma_toroi) * (sind(theta_0) + sind(theta_0 + delta_theta(x)))

    Parameters
    ----------
    n_cols : int
        Number of detector columns (e.g. 1024 or 2048).
    theta0_deg : float
        Adjustable center grating angle theta_0 in degrees.

    Returns
    -------
    np.ndarray
        1-D float64 array of shape (n_cols,), containing wavelength in nm.
    """
    x = np.arange(1, n_cols + 1, dtype=np.float64)  # 1-indexed to match MATLAB
    gamma_rad = np.radians(GAMMA_TOROI_DEG)
    theta0_rad = np.radians(theta0_deg)

    delta_theta_deg = np.degrees(
        np.arctan2((x - X0_PX) * PX_MM, R_MM * np.sin(gamma_rad))
    )
    delta_theta_rad = np.radians(delta_theta_deg)

    lambda_vec = (
        (D_GT_NM / M_DIFF)
        * np.sin(gamma_rad)
        * (np.sin(theta0_rad) + np.sin(theta0_rad + delta_theta_rad))
    )
    return lambda_vec


# ---------------------------------------------------------------------------
# Settings & State Persistence
# ---------------------------------------------------------------------------

_DEFAULT_SETTINGS = {
    "exposure_s": 0.1,
    "trigger_mode_idx": 0,
    "theta0_deg": 12.0,
    "gain": 1.0,
    "colormap": "viridis",
    "output_dir": "",
    "user_note": "",
    "save_enabled_idx": 0,
    "sim_mode_idx": 0,
    "window_geometry": None,
}


class AndorSettings:
    """JSON file persistence for application state and parameters."""

    @staticmethod
    def load(path: pathlib.Path = _SETTINGS_PATH) -> dict:
        settings = dict(_DEFAULT_SETTINGS)
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                settings.update({k: v for k, v in data.items() if k in settings})
        except Exception as exc:
            logger.warning("Failed to load settings from %s: %s", path, exc)
        return settings

    @staticmethod
    def save(data: dict, path: pathlib.Path = _SETTINGS_PATH) -> None:
        try:
            tmp_path = path.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            tmp_path.replace(path)
            logger.info("Settings saved to %s", path)
        except Exception as exc:
            logger.warning("Failed to save settings to %s: %s", path, exc)


# ---------------------------------------------------------------------------
# TIFF & Tag Metadata Saving
# ---------------------------------------------------------------------------

def save_shot_tiff(
    out_dir: str | pathlib.Path,
    shot_index: int,
    raw_d: np.ndarray,
    bg_b: np.ndarray,
    sub_s: np.ndarray,
    metadata: dict,
) -> pathlib.Path:
    """
    Save Raw Signal (D_k), Background (B_k), and Subtracted Signal (S_k)
    as a 3-page TIFF file with embedded JSON metadata in ImageDescription.

    Parameters
    ----------
    out_dir : str or Path
        Target directory to save into.
    shot_index : int
        Shot number counter.
    raw_d : np.ndarray
        Raw signal data (H x W).
    bg_b : np.ndarray
        Background frame (H x W).
    sub_s : np.ndarray
        Subtracted signal (H x W, float32).
    metadata : dict
        Metadata dictionary to embed.

    Returns
    -------
    pathlib.Path
        Saved TIFF file path.
    """
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ts_str = metadata.get("timestamp", datetime.datetime.now().isoformat())
    ts_clean = ts_str.replace(":", "-").replace(".", "-")
    filename = f"shot_{shot_index:04d}_{ts_clean[:19]}.tiff"
    file_path = out_dir / filename

    meta_json = json.dumps(metadata, indent=2)

    # 3-page stack: page 0 = Raw (D_k), page 1 = Background (B_k), page 2 = Subtracted (S_k)
    stack = np.stack(
        [raw_d.astype(np.float32), bg_b.astype(np.float32), sub_s.astype(np.float32)],
        axis=0,
    )

    if _TIFFFILE_AVAILABLE:
        _tifffile.imwrite(
            str(file_path),
            stack,
            description=meta_json,
        )
    else:
        # Fallback to PIL.Image if tifffile is missing
        from PIL import Image
        pages = [
            Image.fromarray(raw_d),
            Image.fromarray(bg_b),
            Image.fromarray(sub_s.astype(np.float32)),
        ]
        pages[0].save(
            str(file_path),
            save_all=True,
            append_images=pages[1:],
            tiffinfo={270: meta_json},  # 270 = ImageDescription
        )

    logger.info("Saved shot TIFF to %s", file_path)
    return file_path


# ---------------------------------------------------------------------------
# Background Acquisition Workers (QThread isolated)
# ---------------------------------------------------------------------------

class SingleShotWorker(QObject):
    """Acquires a single frame without background subtraction."""

    frame_ready = Signal(np.ndarray)
    error       = Signal(str)
    finished    = Signal()

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
            self._driver.set_acquisition_params(num_frames=1, acq_mode=1)
            self._driver.start_acquisition()
            self._driver.wait_for_acquisition()
            if self._running:
                frame = self._driver.get_acquired_data16()
                self.frame_ready.emit(frame)
        except Exception as exc:
            logger.exception("SingleShotWorker error: %s", exc)
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


class RollingAcquisitionWorker(QObject):
    """
    Implements the 4-step rolling background subtraction state machine:
      a. Acquire initial Background Frame (B_0) using internal trigger (mode 0)
      b. Await hardware/software trigger for new shot data
      c. Acquire Raw Data (D_k), compute Cleaned Signal (S_k = D_k - B_{k-1}), and display S_k
      d. Immediately acquire a new Background Frame (B_k) for the next shot (k+1)
    """

    bg_ready      = Signal(np.ndarray)
    shot_ready    = Signal(np.ndarray, np.ndarray, np.ndarray, int)  # D_k, B_k, S_k, shot_index
    status_update = Signal(str)
    error         = Signal(str)
    finished      = Signal()

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

    def _acquire_frame(self, trigger_mode: int) -> np.ndarray:
        self._driver.set_exposure_time(self._exposure_s)
        self._driver.set_trigger_mode(trigger_mode)
        self._driver.set_acquisition_params(num_frames=1, acq_mode=1)
        self._driver.start_acquisition()
        self._driver.wait_for_acquisition()
        return self._driver.get_acquired_data16()

    @Slot()
    def run(self) -> None:
        self._running = True
        shot_k = 0

        try:
            # ── Step a: Acquire initial Background Frame B_0 (Internal trigger) ──
            self.status_update.emit("Step a: Acquiring initial background frame B₀…")
            b_prev = self._acquire_frame(trigger_mode=0)
            self.bg_ready.emit(b_prev)

            # ── Rolling loop ──
            while self._running:
                shot_k += 1

                # ── Step b & c: Await trigger & acquire Raw Data D_k ──
                self.status_update.emit(
                    f"Shot {shot_k}: Awaiting trigger & acquiring Raw Data D_{shot_k}…"
                )
                d_k = self._acquire_frame(trigger_mode=self._trigger_mode)

                if not self._running:
                    break

                # Compute Cleaned Signal S_k = D_k - B_{k-1}
                s_k = d_k.astype(np.float32) - b_prev.astype(np.float32)

                # ── Step d: Immediately acquire new Background Frame B_k ──
                self.status_update.emit(
                    f"Shot {shot_k}: Acquiring next background frame B_{shot_k}…"
                )
                b_k = self._acquire_frame(trigger_mode=0)

                # Emit shot data
                self.shot_ready.emit(d_k, b_k, s_k, shot_k)

                # Roll background: B_k becomes B_{k-1} for shot k+1
                b_prev = b_k

        except Exception as exc:
            logger.exception("RollingAcquisitionWorker error: %s", exc)
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
    """Labelled badge displaying numerical statistics."""

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
        self._val.setText(f"{v:.1f}{self._unit}")

    def clear(self) -> None:
        self._val.setText("—")


# ---------------------------------------------------------------------------
# Helper: Build pyqtgraph ImageView container
# ---------------------------------------------------------------------------

def _create_image_view_container(
    colormap: str = "viridis",
    x_label: str = "X Pixel",
    x_units: str = "",
    y_label: str = "Y Pixel",
    aspect_locked: bool = True,
) -> Tuple[QWidget, pg.ImageView, Tuple[StatBadge, StatBadge, StatBadge]]:
    """Creates an ImageView with axis labels and statistics badge row inside a dark QWidget."""
    container = QWidget()
    container.setStyleSheet(f"background-color: {BG_DARK};")
    layout = QVBoxLayout(container)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(6)

    pg.setConfigOptions(antialias=True, background=BG_DARK)
    plot_item = pg.PlotItem()
    plot_item.setLabel("bottom", x_label, units=x_units)
    plot_item.setLabel("left", y_label)
    plot_item.getViewBox().setAspectLocked(aspect_locked)

    iv = pg.ImageView(view=plot_item)
    try:
        iv.ui.histogram.gradient.loadPreset(colormap)
    except Exception:
        iv.ui.histogram.gradient.loadPreset("viridis")
    iv.ui.roiBtn.hide()
    iv.ui.menuBtn.hide()
    iv.setStyleSheet(f"background: {BG_DARK}; border: none;")
    layout.addWidget(iv)

    stats_row = QHBoxLayout()
    stats_row.setSpacing(8)
    stat_min  = StatBadge("MIN", " ADU")
    stat_max  = StatBadge("MAX", " ADU")
    stat_mean = StatBadge("MEAN", " ADU")
    stats_row.addWidget(stat_min)
    stats_row.addWidget(stat_max)
    stats_row.addWidget(stat_mean)
    stats_row.addStretch()
    layout.addLayout(stats_row)

    return container, iv, (stat_min, stat_max, stat_mean)


def _refresh_stats(badges: Tuple[StatBadge, StatBadge, StatBadge], data: np.ndarray) -> None:
    badges[0].set_value(float(data.min()))
    badges[1].set_value(float(data.max()))
    badges[2].set_value(float(data.mean()))


# ---------------------------------------------------------------------------
# Main Application Window
# ---------------------------------------------------------------------------

class AndorMainWindow(QMainWindow):
    """
    Refactored Andor DAQ & Visualizer Main Window.
    """

    def __init__(self) -> None:
        super().__init__()
        self._driver:          Optional[AndorCameraDriver]        = None
        self._single_worker:   Optional[SingleShotWorker]         = None
        self._rolling_worker:  Optional[RollingAcquisitionWorker] = None
        self._single_thread:   Optional[QThread]                  = None
        self._rolling_thread:  Optional[QThread]                  = None

        self._frame_count: int = 0
        self._shot_count:  int = 0
        self._lambda_vec:  Optional[np.ndarray] = None
        self._last_raw:    Optional[np.ndarray] = None
        self._last_sub:    Optional[np.ndarray] = None

        # Load persisted settings
        self._settings = AndorSettings.load()

        self._setup_ui()
        self._apply_global_style()
        self._restore_settings()
        self._update_button_states()

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle("Andor CCD DAQ & Wavelength Spectrometer")
        self.resize(1420, 860)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Header bar
        root_layout.addWidget(self._make_header())

        # Main splitter (Controls on left, Tabbed visualizer on right)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(3)
        splitter.setStyleSheet(f"QSplitter::handle {{ background: {BORDER}; }}")

        splitter.addWidget(self._make_control_panel())
        splitter.addWidget(self._make_tabbed_visualizer())
        splitter.setSizes([350, 1070])

        root_layout.addWidget(splitter)

        # Status bar
        self.statusBar().setStyleSheet(f"""
            QStatusBar {{
                background: {BG_PANEL};
                color: {TEXT_MUTED};
                font-size: 11px;
                border-top: 1px solid {BORDER};
                padding: 3px 12px;
            }}
        """)
        self._status_label = QLabel("Ready")
        self._mode_badge   = QLabel("● SIMULATION")
        self._mode_badge.setStyleSheet(
            f"color: {ACCENT_AMBER}; font-weight: 700; font-size: 11px;"
        )
        self.statusBar().addWidget(self._status_label)
        self.statusBar().addPermanentWidget(self._mode_badge)

    def _make_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(56)
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

        title = QLabel("⬡  Andor CCD Spectrometer DAQ")
        title.setStyleSheet(f"""
            color: {TEXT_PRIMARY};
            font-size: 17px;
            font-weight: 700;
            letter-spacing: 0.5px;
        """)
        lay.addWidget(title)
        lay.addStretch()

        self._frame_counter_lbl = QLabel("Frames: 0  |  Shots: 0")
        self._frame_counter_lbl.setStyleSheet(
            f"color: {ACCENT_CYAN}; font-size: 12px; font-weight: 600;"
        )
        lay.addWidget(self._frame_counter_lbl)

        return header

    def _make_control_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {BG_PANEL}; border: none; }}"
        )

        inner = QWidget()
        inner.setStyleSheet(f"background-color: {BG_PANEL};")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        layout.addWidget(self._make_camera_group())
        layout.addWidget(self._make_acquisition_group())
        layout.addWidget(self._make_calibration_group())
        layout.addWidget(self._make_output_group())
        layout.addWidget(self._make_note_group())
        layout.addWidget(self._make_display_group())
        layout.addWidget(self._make_actions_group())
        layout.addStretch()

        scroll.setWidget(inner)
        scroll.setFixedWidth(350)
        return scroll

    def _make_camera_group(self) -> QGroupBox:
        grp = QGroupBox("Camera")
        grp.setStyleSheet(GROUP_STYLE)
        lay = QVBoxLayout(grp)
        lay.setSpacing(8)

        sdk_lbl = QLabel("SDK Path")
        sdk_lbl.setStyleSheet(LABEL_STYLE)
        self._sdk_path_lbl = QLabel(r"C:\Program Files\Andor SDK")
        self._sdk_path_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 10px; word-wrap: break-word;"
        )
        self._sdk_path_lbl.setWordWrap(True)

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

        exp_lbl = QLabel("Exposure Time (s)")
        exp_lbl.setStyleSheet(LABEL_STYLE)
        self._exp_spin = QDoubleSpinBox()
        self._exp_spin.setRange(0.001, 60.0)
        self._exp_spin.setSingleStep(0.01)
        self._exp_spin.setDecimals(4)
        self._exp_spin.setValue(0.1)
        self._exp_spin.setStyleSheet(SPINBOX_STYLE)

        gain_lbl = QLabel("Gain")
        gain_lbl.setStyleSheet(LABEL_STYLE)
        self._gain_spin = QDoubleSpinBox()
        self._gain_spin.setRange(1.0, 1000.0)
        self._gain_spin.setSingleStep(1.0)
        self._gain_spin.setDecimals(1)
        self._gain_spin.setValue(1.0)
        self._gain_spin.setStyleSheet(SPINBOX_STYLE)

        trig_lbl = QLabel("Signal Trigger Mode")
        trig_lbl.setStyleSheet(LABEL_STYLE)
        self._trig_combo = QComboBox()
        self._trig_combo.addItems([
            "Internal Trigger (Mode 0)",
            "External Trigger (Mode 1)",
        ])
        self._trig_combo.setStyleSheet(COMBO_STYLE)

        lay.addWidget(exp_lbl)
        lay.addWidget(self._exp_spin)
        lay.addWidget(gain_lbl)
        lay.addWidget(self._gain_spin)
        lay.addWidget(trig_lbl)
        lay.addWidget(self._trig_combo)
        return grp

    def _make_calibration_group(self) -> QGroupBox:
        grp = QGroupBox("Wavelength Calibration")
        grp.setStyleSheet(GROUP_STYLE)
        lay = QVBoxLayout(grp)
        lay.setSpacing(8)

        theta_lbl = QLabel("Center Grating Angle θ₀ (°)")
        theta_lbl.setStyleSheet(LABEL_STYLE)
        self._theta0_spin = QDoubleSpinBox()
        self._theta0_spin.setRange(0.0, 45.0)
        self._theta0_spin.setSingleStep(0.1)
        self._theta0_spin.setDecimals(2)
        self._theta0_spin.setValue(12.0)
        self._theta0_spin.setStyleSheet(SPINBOX_STYLE)
        self._theta0_spin.valueChanged.connect(self._on_theta0_changed)

        self._wl_range_lbl = QLabel("λ Range: — nm")
        self._wl_range_lbl.setStyleSheet(
            f"color: {ACCENT_VIOLET}; font-size: 11px; font-weight: 600;"
        )

        lay.addWidget(theta_lbl)
        lay.addWidget(self._theta0_spin)
        lay.addWidget(self._wl_range_lbl)
        return grp

    def _make_output_group(self) -> QGroupBox:
        grp = QGroupBox("Output Destination")
        grp.setStyleSheet(GROUP_STYLE)
        lay = QVBoxLayout(grp)
        lay.setSpacing(8)

        dir_lbl = QLabel("Target Save Folder")
        dir_lbl.setStyleSheet(LABEL_STYLE)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(6)
        self._out_dir_edit = QLineEdit()
        self._out_dir_edit.setPlaceholderText("Select output directory…")
        self._out_dir_edit.setStyleSheet(LINEEDIT_STYLE)

        browse_btn = QPushButton("Browse…")
        browse_btn.setStyleSheet(BUTTON_STYLE_PRIMARY)
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._on_browse_output_dir)

        dir_row.addWidget(self._out_dir_edit)
        dir_row.addWidget(browse_btn)

        self._save_enabled_combo = QComboBox()
        self._save_enabled_combo.addItems([
            "Save TIFF Per Shot (D_k, B_k, S_k)",
            "Do Not Save",
        ])
        self._save_enabled_combo.setStyleSheet(COMBO_STYLE)

        lay.addWidget(dir_lbl)
        lay.addLayout(dir_row)
        lay.addWidget(self._save_enabled_combo)
        return grp

    def _make_note_group(self) -> QGroupBox:
        grp = QGroupBox("User Note")
        grp.setStyleSheet(GROUP_STYLE)
        lay = QVBoxLayout(grp)
        lay.setSpacing(8)

        note_lbl = QLabel("My Note (Metadata Tag)")
        note_lbl.setStyleSheet(LABEL_STYLE)
        self._note_edit = QLineEdit()
        self._note_edit.setPlaceholderText("Enter custom note or run ID…")
        self._note_edit.setStyleSheet(LINEEDIT_STYLE)

        lay.addWidget(note_lbl)
        lay.addWidget(self._note_edit)
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

    def _make_actions_group(self) -> QGroupBox:
        grp = QGroupBox("Actions")
        grp.setStyleSheet(GROUP_STYLE)
        lay = QVBoxLayout(grp)
        lay.setSpacing(8)

        self._start_btn = QPushButton("▶  Capture Single Shot")
        self._start_btn.setStyleSheet(BUTTON_STYLE_SUCCESS)
        self._start_btn.clicked.connect(self._on_start_single)

        self._rolling_start_btn = QPushButton("⟳  Start Rolling Acquisition")
        self._rolling_start_btn.setStyleSheet(BUTTON_STYLE_VIOLET)
        self._rolling_start_btn.clicked.connect(self._on_start_rolling)

        self._stop_btn = QPushButton("■  Abort Acquisition")
        self._stop_btn.setStyleSheet(BUTTON_STYLE_DANGER)
        self._stop_btn.clicked.connect(self._on_stop)

        lay.addWidget(self._start_btn)
        lay.addWidget(self._rolling_start_btn)
        lay.addWidget(self._stop_btn)
        return grp

    def _make_tabbed_visualizer(self) -> QWidget:
        container = QWidget()
        container.setStyleSheet(f"background-color: {BG_DARK};")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(0)

        self._tab_widget = QTabWidget()
        self._tab_widget.setStyleSheet(TAB_STYLE)

        # Tab 1: Raw Image (pixel coordinates)
        raw_widget, self._raw_iv, self._raw_stats = _create_image_view_container(
            x_label="X Pixel", y_label="Y Pixel", aspect_locked=True
        )
        self._tab_widget.addTab(raw_widget, "📷  Raw Image")

        # Tab 2: Wavelength Calibrated (nm coordinates)
        cal_widget, self._cal_iv, self._cal_stats = _create_image_view_container(
            x_label="Wavelength", x_units="nm", y_label="Y Pixel", aspect_locked=False
        )
        self._tab_widget.addTab(cal_widget, "〜  Wavelength Calibrated")

        layout.addWidget(self._tab_widget)
        return container

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
            QScrollBar:horizontal {{
                background: {BG_DARK};
                height: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:horizontal {{
                background: {BORDER};
                border-radius: 4px;
            }}
        """)

    # ------------------------------------------------------------------
    # State Persistence
    # ------------------------------------------------------------------

    def _restore_settings(self) -> None:
        s = self._settings
        self._exp_spin.setValue(float(s.get("exposure_s", 0.1)))
        self._gain_spin.setValue(float(s.get("gain", 1.0)))
        self._trig_combo.setCurrentIndex(int(s.get("trigger_mode_idx", 0)))
        self._theta0_spin.setValue(float(s.get("theta0_deg", 12.0)))
        idx = self._cmap_combo.findText(s.get("colormap", "viridis"))
        if idx >= 0:
            self._cmap_combo.setCurrentIndex(idx)
        self._out_dir_edit.setText(s.get("output_dir", ""))
        self._note_edit.setText(s.get("user_note", ""))
        self._save_enabled_combo.setCurrentIndex(int(s.get("save_enabled_idx", 0)))
        self._sim_combo.setCurrentIndex(int(s.get("sim_mode_idx", 0)))

        geo = s.get("window_geometry")
        if geo:
            try:
                self.restoreGeometry(bytes.fromhex(geo))
            except Exception:
                pass

        self._update_wavelength_vector()

    def _collect_settings(self) -> dict:
        return {
            "exposure_s":       self._exp_spin.value(),
            "gain":             self._gain_spin.value(),
            "trigger_mode_idx": self._trig_combo.currentIndex(),
            "theta0_deg":       self._theta0_spin.value(),
            "colormap":         self._cmap_combo.currentText(),
            "output_dir":       self._out_dir_edit.text().strip(),
            "user_note":        self._note_edit.text().strip(),
            "save_enabled_idx": self._save_enabled_combo.currentIndex(),
            "sim_mode_idx":     self._sim_combo.currentIndex(),
            "window_geometry":  bytes(self.saveGeometry()).hex(),
        }

    # ------------------------------------------------------------------
    # Calibration Helpers
    # ------------------------------------------------------------------

    def _update_wavelength_vector(self) -> None:
        n_cols = self._driver.width if (self._driver and self._driver.is_initialized) else 1024
        theta0 = self._theta0_spin.value()
        self._lambda_vec = calculate_lambda_vec(n_cols, theta0)

        wl_min = self._lambda_vec.min()
        wl_max = self._lambda_vec.max()
        self._wl_range_lbl.setText(f"λ Range: {wl_min:.2f} – {wl_max:.2f} nm")

    def _apply_calibrated_image(self, data_s: np.ndarray) -> None:
        """
        Display 2D data (H x W) in the calibrated tab with X-axis scaled in nm.
        """
        h, w = data_s.shape
        if self._lambda_vec is None or len(self._lambda_vec) != w:
            self._update_wavelength_vector()

        lv = self._lambda_vec
        wl_min = float(lv[0])
        wl_max = float(lv[-1])
        wl_span = wl_max - wl_min
        dx = wl_span / float(w)

        # pyqtgraph ImageView displays (W, H)
        self._cal_iv.setImage(
            data_s.T,
            autoRange=False,
            autoLevels=True,
            autoHistogramRange=True,
        )

        # Apply QTransform to map pixel column [0 ... W] to [wl_min ... wl_max]
        item = self._cal_iv.getImageItem()
        tr = QTransform()
        tr.translate(wl_min, 0.0)
        tr.scale(dx, 1.0)
        item.setTransform(tr)

        vb = self._cal_iv.getView()
        vb.setRange(xRange=[wl_min, wl_max], yRange=[0, h], padding=0.02)
        _refresh_stats(self._cal_stats, data_s)

    def _build_metadata(self) -> dict:
        cam_serial = "SIM-MOCK-01"
        if self._driver and not self._driver.is_simulated:
            cam_serial = "ANDOR-CCD-HW"

        lv = self._lambda_vec
        wl_range = [float(lv.min()), float(lv.max())] if lv is not None else []

        return {
            "camera_serial": cam_serial,
            "timestamp": datetime.datetime.now().isoformat(),
            "exposure_time_s": self._exp_spin.value(),
            "gain": self._gain_spin.value(),
            "trigger_mode": self._trig_combo.currentIndex(),
            "theta0_deg": self._theta0_spin.value(),
            "wavelength_range_nm": wl_range,
            "user_note": self._note_edit.text().strip(),
        }

    # ------------------------------------------------------------------
    # Slots & Action Handlers
    # ------------------------------------------------------------------

    @Slot()
    def _on_initialize(self) -> None:
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
            f"Camera initialized ({'simulation' if is_sim else 'hardware'} – {w}×{h} px)"
        )
        self._update_wavelength_vector()
        self._update_button_states()

    @Slot()
    def _on_start_single(self) -> None:
        if not self._check_camera_ready() or self._is_worker_running():
            return

        exp_s = self._exp_spin.value()
        trig_mode = self._trig_combo.currentIndex()

        self._single_worker = SingleShotWorker(self._driver, exp_s, trig_mode)
        self._single_thread = QThread()
        self._single_worker.moveToThread(self._single_thread)

        self._single_thread.started.connect(self._single_worker.run)
        self._single_worker.frame_ready.connect(self._on_single_frame_ready)
        self._single_worker.error.connect(self._on_acq_error)
        self._single_worker.finished.connect(self._on_single_finished)
        self._single_worker.finished.connect(self._single_thread.quit)
        self._single_thread.finished.connect(self._on_single_thread_done)

        self._single_thread.start()
        self._set_status("Acquiring single shot…")
        self._update_button_states(acquiring=True)

    @Slot()
    def _on_start_rolling(self) -> None:
        if not self._check_camera_ready() or self._is_worker_running():
            return

        self._update_wavelength_vector()
        exp_s = self._exp_spin.value()
        trig_mode = self._trig_combo.currentIndex()

        self._rolling_worker = RollingAcquisitionWorker(self._driver, exp_s, trig_mode)
        self._rolling_thread = QThread()
        self._rolling_worker.moveToThread(self._rolling_thread)

        self._rolling_thread.started.connect(self._rolling_worker.run)
        self._rolling_worker.bg_ready.connect(self._on_bg_ready)
        self._rolling_worker.shot_ready.connect(self._on_rolling_shot_ready)
        self._rolling_worker.status_update.connect(self._set_status)
        self._rolling_worker.error.connect(self._on_acq_error)
        self._rolling_worker.finished.connect(self._on_rolling_finished)
        self._rolling_worker.finished.connect(self._rolling_thread.quit)
        self._rolling_thread.finished.connect(self._on_rolling_thread_done)

        self._rolling_thread.start()
        self._set_status("Rolling acquisition loop started…")
        self._update_button_states(acquiring=True)

    @Slot()
    def _on_stop(self) -> None:
        if self._single_worker:
            self._single_worker.stop()
        if self._rolling_worker:
            self._rolling_worker.stop()
        if self._driver:
            try:
                self._driver.abort_acquisition()
            except Exception:
                pass
        self._set_status("Aborting acquisition…")

    @Slot(np.ndarray)
    def _on_single_frame_ready(self, frame: np.ndarray) -> None:
        self._frame_count += 1
        self._last_raw = frame
        self._update_counter_label()

        # Update Tab 1 (Raw Image)
        self._raw_iv.setImage(
            frame.T, autoRange=False, autoLevels=True, autoHistogramRange=True
        )
        _refresh_stats(self._raw_stats, frame)

        # Update Tab 2 (Wavelength Calibrated - single shot shown without subtraction)
        self._apply_calibrated_image(frame.astype(np.float32))

        # Check if saving requested
        if self._should_save():
            meta = self._build_metadata()
            bg_zero = np.zeros_like(frame)
            try:
                saved = save_shot_tiff(
                    self._out_dir_edit.text().strip(),
                    self._shot_count + 1,
                    frame, bg_zero, frame.astype(np.float32),
                    meta,
                )
                self._set_status(f"Saved: {saved.name}")
            except Exception as exc:
                logger.error("Error saving TIFF: %s", exc)

    @Slot(np.ndarray)
    def _on_bg_ready(self, bg_0: np.ndarray) -> None:
        self._frame_count += 1
        self._update_counter_label()
        self._raw_iv.setImage(
            bg_0.T, autoRange=False, autoLevels=True, autoHistogramRange=True
        )
        _refresh_stats(self._raw_stats, bg_0)
        self._set_status("Initial background B₀ acquired. Awaiting shot trigger…")

    @Slot(np.ndarray, np.ndarray, np.ndarray, int)
    def _on_rolling_shot_ready(
        self, d_k: np.ndarray, b_k: np.ndarray, s_k: np.ndarray, shot_k: int
    ) -> None:
        self._shot_count = shot_k
        self._frame_count += 2  # D_k and B_k
        self._last_raw = d_k
        self._last_sub = s_k
        self._update_counter_label()

        # Update Tab 1: Raw Image D_k
        self._raw_iv.setImage(
            d_k.T, autoRange=False, autoLevels=True, autoHistogramRange=True
        )
        _refresh_stats(self._raw_stats, d_k)

        # Update Tab 2: Wavelength Calibrated Cleaned Signal S_k
        self._apply_calibrated_image(s_k)

        # Save TIFF if configured
        if self._should_save():
            meta = self._build_metadata()
            out_dir = self._out_dir_edit.text().strip()
            try:
                saved = save_shot_tiff(out_dir, shot_k, d_k, b_k, s_k, meta)
                self._set_status(f"Shot {shot_k} saved: {saved.name}")
            except Exception as exc:
                logger.error("Failed to save TIFF for shot %d: %s", shot_k, exc)

    @Slot(str)
    def _on_acq_error(self, err_msg: str) -> None:
        QMessageBox.critical(self, "Acquisition Error", err_msg)
        self._set_status(f"Error: {err_msg}")

    @Slot()
    def _on_single_finished(self) -> None:
        self._set_status(f"Single shot complete – Frames: {self._frame_count}")
        self._update_button_states(acquiring=False)

    @Slot()
    def _on_rolling_finished(self) -> None:
        self._set_status(
            f"Rolling loop stopped – Shots: {self._shot_count}, Frames: {self._frame_count}"
        )
        self._update_button_states(acquiring=False)

    @Slot()
    def _on_single_thread_done(self) -> None:
        if self._single_worker:
            self._single_worker.deleteLater()
            self._single_worker = None
        if self._single_thread:
            self._single_thread.deleteLater()
            self._single_thread = None

    @Slot()
    def _on_rolling_thread_done(self) -> None:
        if self._rolling_worker:
            self._rolling_worker.deleteLater()
            self._rolling_worker = None
        if self._rolling_thread:
            self._rolling_thread.deleteLater()
            self._rolling_thread = None

    @Slot(str)
    def _on_cmap_change(self, cmap_name: str) -> None:
        for iv in (self._raw_iv, self._cal_iv):
            try:
                iv.ui.histogram.gradient.loadPreset(cmap_name)
            except KeyError:
                iv.ui.histogram.gradient.loadPreset("grey")

    @Slot(float)
    def _on_theta0_changed(self, _: float) -> None:
        self._update_wavelength_vector()
        if self._last_sub is not None:
            self._apply_calibrated_image(self._last_sub)
        elif self._last_raw is not None:
            self._apply_calibrated_image(self._last_raw.astype(np.float32))

    @Slot()
    def _on_browse_output_dir(self) -> None:
        current = self._out_dir_edit.text().strip() or str(pathlib.Path.home())
        selected = QFileDialog.getExistingDirectory(
            self, "Select Destination Output Folder", current
        )
        if selected:
            self._out_dir_edit.setText(selected)

    # ------------------------------------------------------------------
    # Helper Queries
    # ------------------------------------------------------------------

    def _should_save(self) -> bool:
        return (
            self._save_enabled_combo.currentIndex() == 0
            and bool(self._out_dir_edit.text().strip())
        )

    def _check_camera_ready(self) -> bool:
        if self._driver is None or not self._driver.is_initialized:
            QMessageBox.warning(
                self, "Camera Not Ready",
                "Please initialize the camera first."
            )
            return False
        return True

    def _is_worker_running(self) -> bool:
        for th in (self._single_thread, self._rolling_thread):
            if th is not None:
                try:
                    if th.isRunning():
                        return True
                except RuntimeError:
                    pass
        return False

    def _update_counter_label(self) -> None:
        self._frame_counter_lbl.setText(
            f"Frames: {self._frame_count}  |  Shots: {self._shot_count}"
        )

    def _set_status(self, msg: str) -> None:
        self._status_label.setText(msg)
        logger.info("Status: %s", msg)

    def _update_button_states(self, acquiring: bool = False) -> None:
        init_ok = bool(self._driver and self._driver.is_initialized)
        self._init_btn.setEnabled(not acquiring)
        self._start_btn.setEnabled(init_ok and not acquiring)
        self._rolling_start_btn.setEnabled(init_ok and not acquiring)
        self._stop_btn.setEnabled(acquiring)
        self._exp_spin.setEnabled(not acquiring)
        self._gain_spin.setEnabled(not acquiring)
        self._trig_combo.setEnabled(not acquiring)
        self._sim_combo.setEnabled(not acquiring)

    # ------------------------------------------------------------------
    # Application Shutdown
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        # Stop background workers
        if self._single_worker:
            self._single_worker.stop()
        if self._rolling_worker:
            self._rolling_worker.stop()

        for th in (self._single_thread, self._rolling_thread):
            if th is not None:
                try:
                    if th.isRunning():
                        th.quit()
                        th.wait(2500)
                except RuntimeError:
                    pass

        self._single_worker  = None
        self._single_thread  = None
        self._rolling_worker = None
        self._rolling_thread = None

        if self._driver:
            try:
                self._driver.shutdown()
            except Exception:
                pass

        # Persist settings to JSON
        AndorSettings.save(self._collect_settings())

        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Andor CCD Spectrometer DAQ")
    app.setOrganizationName("DAQ_CA")

    font = QFont("Segoe UI", 10)
    app.setFont(font)

    win = AndorMainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

"""
pg_camera_gui.py
================
PyQt6 / PySide6 GUI front-end for the Grasshopper2 GS2-GE-20S4M camera.

Requires
--------
  pip install PyQt6 pyqtgraph numpy
  # or PySide6 instead of PyQt6

Usage
-----
  python pg_camera_gui.py

The script auto-selects between PyQt6 and PySide6; whichever is installed
first on sys.path wins.

Author : <your-name>
Date   : 2026-09-21
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Qt backend – try PyQt6 first, fall back to PySide6
# ---------------------------------------------------------------------------
try:
    from PyQt6 import QtCore, QtGui, QtWidgets
    from PyQt6.QtCore import (
        QMutex, QMutexLocker, QObject, QThread, Qt, pyqtSignal as Signal
    )
    from PyQt6.QtWidgets import (
        QApplication, QComboBox, QDoubleSpinBox, QFormLayout, QFrame,
        QGroupBox, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
        QPushButton, QSizePolicy, QStatusBar, QVBoxLayout, QWidget,
    )
    _QT_BACKEND = "PyQt6"
except ImportError:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import (
        QMutex, QMutexLocker, QObject, QThread, Qt, Signal
    )
    from PySide6.QtWidgets import (
        QApplication, QComboBox, QDoubleSpinBox, QFormLayout, QFrame,
        QGroupBox, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
        QPushButton, QSizePolicy, QStatusBar, QVBoxLayout, QWidget,
    )
    _QT_BACKEND = "PySide6"

import pyqtgraph as pg

from pg_camera_driver import Grasshopper2Driver

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global pyqtgraph settings
# ---------------------------------------------------------------------------
pg.setConfigOptions(
    imageAxisOrder="row-major",
    antialias=True,
    useOpenGL=True,
)

# ---------------------------------------------------------------------------
# Stylesheet – dark, polished
# ---------------------------------------------------------------------------
_STYLE = """
/* ─── Global ─────────────────────────────────────────────────────────── */
QMainWindow, QWidget {
    background-color: #12141a;
    color: #e2e8f0;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}

/* ─── Group boxes ────────────────────────────────────────────────────── */
QGroupBox {
    background-color: #1a1d27;
    border: 1px solid #2d3148;
    border-radius: 8px;
    margin-top: 18px;
    padding: 12px 10px 8px 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 6px;
    color: #7c8bff;
    font-weight: 600;
    font-size: 12px;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}

/* ─── Spin boxes & combo boxes ───────────────────────────────────────── */
QDoubleSpinBox, QComboBox {
    background-color: #1e2130;
    border: 1px solid #2d3148;
    border-radius: 5px;
    padding: 5px 8px;
    color: #e2e8f0;
    selection-background-color: #4c5aff;
    min-width: 110px;
}
QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #5c6bff;
}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background-color: #2d3148;
    border: none;
    border-radius: 3px;
    width: 16px;
}
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: #3d4268;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #1a1d27;
    border: 1px solid #2d3148;
    selection-background-color: #4c5aff;
    color: #e2e8f0;
}

/* ─── Labels ─────────────────────────────────────────────────────────── */
QLabel {
    color: #94a3b8;
    font-size: 12px;
}
QLabel#statusLabel {
    color: #4ade80;
    font-weight: 600;
}

/* ─── Buttons ────────────────────────────────────────────────────────── */
QPushButton {
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #3d4bff, stop:1 #2d38e0
    );
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.3px;
    min-height: 34px;
}
QPushButton:hover {
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #5560ff, stop:1 #404ce8
    );
}
QPushButton:pressed {
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #2d38e0, stop:1 #222ca8
    );
}
QPushButton:disabled {
    background-color: #252836;
    color: #4a5568;
}
QPushButton#liveBtn[live="true"] {
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #e05353, stop:1 #b83333
    );
}
QPushButton#liveBtn[live="true"]:hover {
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #f06060, stop:1 #cc4444
    );
}
QPushButton#connectBtn[connected="true"] {
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #22c55e, stop:1 #16a34a
    );
}

/* ─── Status bar ─────────────────────────────────────────────────────── */
QStatusBar {
    background-color: #0e1018;
    color: #64748b;
    border-top: 1px solid #1e2130;
    font-size: 11px;
}

/* ─── Scrollbars ─────────────────────────────────────────────────────── */
QScrollBar:vertical { background: #1a1d27; width: 8px; }
QScrollBar::handle:vertical { background: #2d3148; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

/* ─── Separator ──────────────────────────────────────────────────────── */
QFrame[frameShape="4"], QFrame[frameShape="5"] {
    color: #2d3148;
}
"""

# ---------------------------------------------------------------------------
# Frame-grab worker (runs in a background QThread)
# ---------------------------------------------------------------------------


class FrameWorker(QObject):
    """
    Background worker that continuously grabs frames from the camera driver
    and emits them via a Qt signal.

    Signals
    -------
    frame_ready(np.ndarray)
        Emitted with each new uint16 2-D array.
    error(str)
        Emitted when an exception is raised during grabbing.
    """

    frame_ready: Signal = Signal(object)   # np.ndarray
    error: Signal       = Signal(str)

    def __init__(self, driver: Grasshopper2Driver) -> None:
        super().__init__()
        self._driver  = driver
        self._running = False
        self._mutex   = QMutex()

    # ------------------------------------------------------------------
    def start_streaming(self) -> None:
        """Called from the worker thread – grab loop."""
        self._running = True
        while True:
            with QMutexLocker(self._mutex):
                if not self._running:
                    break
            try:
                frame = self._driver.grab_frame_numpy()
                self.frame_ready.emit(frame)
            except Exception as exc:
                self.error.emit(str(exc))
                break

    def stop_streaming(self) -> None:
        """Signal the grab loop to stop (thread-safe)."""
        with QMutexLocker(self._mutex):
            self._running = False


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class CameraWindow(QMainWindow):
    """
    Main application window for the Grasshopper2 camera GUI.

    Layout
    ------
    ┌────────────────────────────────────────────────────────────────────┐
    │  [Image View – pyqtgraph, fills centre]                           │
    ├──────────────────────────┬─────────────────────────────────────── ┤
    │  Camera Settings panel   │  (future expansion space)             │
    └──────────────────────────┴─────────────────────────────────────── ┘
    │  Status bar                                                        │
    └────────────────────────────────────────────────────────────────────┘
    """

    def __init__(self) -> None:
        super().__init__()
        self._driver: Optional[Grasshopper2Driver] = None
        self._thread: Optional[QThread]     = None
        self._worker: Optional[FrameWorker] = None
        self._live    = False
        self._frame_count = 0
        self._last_fps_ts = 0.0

        self._build_ui()
        self._apply_style()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle("Point Grey Grasshopper2  –  GS2-GE-20S4M")
        self.setMinimumSize(1100, 760)

        # ── Central widget & root layout ──────────────────────────────
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(12)
        self.setCentralWidget(root)

        # ── Left: image viewer ─────────────────────────────────────────
        self._image_view = pg.ImageView()
        self._image_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._image_view.ui.roiBtn.hide()
        self._image_view.ui.menuBtn.hide()
        # Dark background – set on the underlying ViewBox/GraphicsView
        self._image_view.getView().setBackgroundColor("#0e1018")
        # Apply colormap – try several sources, fall back to hand-built greyscale
        self._apply_colormap()

        root_layout.addWidget(self._image_view, stretch=4)

        # ── Right: control panel ───────────────────────────────────────
        ctrl_panel = QWidget()
        ctrl_panel.setFixedWidth(260)
        ctrl_layout = QVBoxLayout(ctrl_panel)
        ctrl_layout.setContentsMargins(0, 0, 0, 0)
        ctrl_layout.setSpacing(12)
        root_layout.addWidget(ctrl_panel, stretch=0)

        # ── Camera info block ──────────────────────────────────────────
        info_group = QGroupBox("Camera")
        info_form  = QFormLayout(info_group)
        info_form.setSpacing(6)

        self._lbl_model = QLabel("—")
        self._lbl_serial = QLabel("—")
        self._lbl_firmware = QLabel("—")
        self._lbl_fps_live  = QLabel("—")

        info_form.addRow("Model:",    self._lbl_model)
        info_form.addRow("Serial:",   self._lbl_serial)
        info_form.addRow("Firmware:", self._lbl_firmware)
        info_form.addRow("Live FPS:", self._lbl_fps_live)

        ctrl_layout.addWidget(info_group)

        # ── Imaging settings ───────────────────────────────────────────
        settings_group = QGroupBox("Imaging Settings")
        settings_form  = QFormLayout(settings_group)
        settings_form.setSpacing(8)
        settings_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Exposure
        self._spin_exposure = QDoubleSpinBox()
        self._spin_exposure.setRange(0.001, 10.0)
        self._spin_exposure.setDecimals(3)
        self._spin_exposure.setSingleStep(0.01)
        self._spin_exposure.setValue(0.1)
        self._spin_exposure.setSuffix("  s")
        self._spin_exposure.setToolTip(
            "Shutter/exposure time (0.001 – 10.0 s)"
        )

        # Frame rate
        self._spin_fps = QDoubleSpinBox()
        self._spin_fps.setRange(1.0, 30.0)
        self._spin_fps.setDecimals(1)
        self._spin_fps.setSingleStep(1.0)
        self._spin_fps.setValue(10.0)
        self._spin_fps.setSuffix("  FPS")
        self._spin_fps.setToolTip("Frame rate (1 – 30 FPS)")

        # Gain
        self._spin_gain = QDoubleSpinBox()
        self._spin_gain.setRange(0.0, 24.0)
        self._spin_gain.setDecimals(2)
        self._spin_gain.setSingleStep(0.5)
        self._spin_gain.setValue(0.0)
        self._spin_gain.setSuffix("  dB")
        self._spin_gain.setToolTip("Analogue gain (0 – 24 dB)")

        # Trigger mode
        self._combo_trigger = QComboBox()
        self._combo_trigger.addItem("Internal (Continuous / Software)", userData=False)
        self._combo_trigger.addItem("External TTL Trigger",             userData=True)
        self._combo_trigger.setToolTip(
            "Internal: free-run continuous\n"
            "External: waits for TTL signal on GPIO0"
        )

        settings_form.addRow("Exposure:", self._spin_exposure)
        settings_form.addRow("Frame Rate:", self._spin_fps)
        settings_form.addRow("Gain:", self._spin_gain)
        settings_form.addRow("Trigger:", self._combo_trigger)

        ctrl_layout.addWidget(settings_group)

        # ── Apply settings button ──────────────────────────────────────
        self._btn_apply = QPushButton("Apply Settings")
        self._btn_apply.setObjectName("applyBtn")
        self._btn_apply.setEnabled(False)
        self._btn_apply.setToolTip(
            "Push exposure / FPS / gain / trigger changes to camera"
        )
        self._btn_apply.clicked.connect(self._on_apply_settings)
        ctrl_layout.addWidget(self._btn_apply)

        # ── Separator ──────────────────────────────────────────────────
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        ctrl_layout.addWidget(sep1)

        # ── Acquisition buttons ────────────────────────────────────────
        acq_group = QGroupBox("Acquisition")
        acq_layout = QVBoxLayout(acq_group)
        acq_layout.setSpacing(8)

        self._btn_connect = QPushButton("Connect Camera")
        self._btn_connect.setObjectName("connectBtn")
        self._btn_connect.setProperty("connected", "false")
        self._btn_connect.clicked.connect(self._on_toggle_connect)

        self._btn_single = QPushButton("Single Shot")
        self._btn_single.setObjectName("singleBtn")
        self._btn_single.setEnabled(False)
        self._btn_single.setToolTip("Capture one frame and update display")
        self._btn_single.clicked.connect(self._on_single_shot)

        self._btn_live = QPushButton("▶  Start Live Stream")
        self._btn_live.setObjectName("liveBtn")
        self._btn_live.setProperty("live", "false")
        self._btn_live.setEnabled(False)
        self._btn_live.setToolTip("Toggle continuous frame acquisition")
        self._btn_live.clicked.connect(self._on_toggle_live)

        acq_layout.addWidget(self._btn_connect)
        acq_layout.addWidget(self._btn_single)
        acq_layout.addWidget(self._btn_live)
        ctrl_layout.addWidget(acq_group)

        # ── Histogram info ─────────────────────────────────────────────
        hist_group = QGroupBox("Frame Statistics")
        hist_form  = QFormLayout(hist_group)
        hist_form.setSpacing(6)

        self._lbl_min   = QLabel("—")
        self._lbl_max   = QLabel("—")
        self._lbl_mean  = QLabel("—")
        self._lbl_shape = QLabel("—")

        hist_form.addRow("Min:",   self._lbl_min)
        hist_form.addRow("Max:",   self._lbl_max)
        hist_form.addRow("Mean:",  self._lbl_mean)
        hist_form.addRow("Shape:", self._lbl_shape)

        ctrl_layout.addWidget(hist_group)
        ctrl_layout.addStretch(1)

        # ── Status bar ─────────────────────────────────────────────────
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage(
            f"Ready  |  Qt backend: {_QT_BACKEND}  |  "
            "Connect a camera to begin."
        )

    def _apply_style(self) -> None:
        self.setStyleSheet(_STYLE)
        # Refresh dynamic properties for buttons
        for btn in [self._btn_live, self._btn_connect]:
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _apply_colormap(self) -> None:
        """
        Apply a perceptually-uniform colormap to the ImageView histogram.

        Strategy (in priority order):
          1. 'inferno' from matplotlib (if installed)
          2. 'inferno' from colorcet (if installed)
          3. A named built-in pyqtgraph colormap ('thermal', 'greyclip', 'grey')
          4. Hand-built black→white linear ColorMap as guaranteed fallback
        """
        cmap = None

        # ── 1. matplotlib source ───────────────────────────────────────
        if cmap is None:
            try:
                cmap = pg.colormap.get("inferno", source="matplotlib")
            except Exception:
                pass

        # ── 2. colorcet source ─────────────────────────────────────────
        if cmap is None:
            try:
                cmap = pg.colormap.get("CET-L4", source="colorcet")
            except Exception:
                pass

        # ── 3. pyqtgraph built-in names ────────────────────────────────
        if cmap is None:
            for name in ("thermal", "flame", "yellowy", "greyclip", "grey"):
                try:
                    candidate = pg.colormap.get(name)
                    if candidate is not None:
                        cmap = candidate
                        break
                except Exception:
                    continue

        # ── 4. Guaranteed hand-built fallback: black → white ──────────
        if cmap is None:
            import numpy as np
            pos    = np.array([0.0, 1.0])
            color  = np.array([[0, 0, 0, 255], [255, 255, 255, 255]], dtype=np.ubyte)
            cmap   = pg.ColorMap(pos, color)

        try:
            self._image_view.setColorMap(cmap)
        except Exception as exc:
            logger.warning("Could not apply colormap: %s", exc)

    # ------------------------------------------------------------------
    # Camera connection
    # ------------------------------------------------------------------

    def _on_toggle_connect(self) -> None:
        if self._driver is None:
            self._do_connect()
        else:
            self._do_disconnect()

    def _do_connect(self) -> None:
        self._status_bar.showMessage("Connecting to camera…")
        QApplication.processEvents()
        try:
            self._driver = Grasshopper2Driver()
            self._driver.connect()
        except Exception as exc:
            self._driver = None
            QMessageBox.critical(
                self,
                "Connection Error",
                f"Failed to connect to the camera:\n\n{exc}",
            )
            self._status_bar.showMessage("Connection failed.")
            return

        info = self._driver.get_camera_info()
        self._lbl_model.setText(info.get("model", "—"))
        self._lbl_serial.setText(str(info.get("serial", "—")))
        self._lbl_firmware.setText(info.get("firmware", "—"))

        # Enable controls
        self._btn_apply.setEnabled(True)
        self._btn_single.setEnabled(True)
        self._btn_live.setEnabled(True)

        # Update connect button appearance
        self._btn_connect.setText("Disconnect")
        self._btn_connect.setProperty("connected", "true")
        self._refresh_btn_style(self._btn_connect)

        self._status_bar.showMessage(
            f"Connected: {info.get('model', 'Unknown')}  "
            f"| S/N {info.get('serial', '—')}"
        )

    def _do_disconnect(self) -> None:
        if self._live:
            self._stop_live()

        try:
            self._driver.disconnect()
        except Exception as exc:
            logger.warning("Error during disconnect: %s", exc)
        finally:
            self._driver = None

        self._lbl_model.setText("—")
        self._lbl_serial.setText("—")
        self._lbl_firmware.setText("—")
        self._lbl_fps_live.setText("—")

        self._btn_apply.setEnabled(False)
        self._btn_single.setEnabled(False)
        self._btn_live.setEnabled(False)

        self._btn_connect.setText("Connect Camera")
        self._btn_connect.setProperty("connected", "false")
        self._refresh_btn_style(self._btn_connect)

        self._status_bar.showMessage("Disconnected.")

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _on_apply_settings(self) -> None:
        if self._driver is None:
            return
        try:
            self._driver.set_exposure_time(self._spin_exposure.value())
            self._driver.set_frame_rate(self._spin_fps.value())
            self._driver.set_gain(self._spin_gain.value())
            ext_trig = bool(self._combo_trigger.currentData())
            self._driver.set_trigger_mode(enabled=ext_trig)
            self._status_bar.showMessage(
                f"Settings applied  "
                f"(exp={self._spin_exposure.value():.3f}s  "
                f"fps={self._spin_fps.value():.1f}  "
                f"gain={self._spin_gain.value():.2f}dB  "
                f"trig={'ext' if ext_trig else 'int'})"
            )
        except Exception as exc:
            QMessageBox.warning(self, "Settings Error", str(exc))

    # ------------------------------------------------------------------
    # Single-shot acquisition
    # ------------------------------------------------------------------

    def _on_single_shot(self) -> None:
        if self._driver is None:
            return
        if self._live:
            return   # live stream already running

        was_capturing = self._driver.is_capturing
        try:
            if not was_capturing:
                self._driver.start_capture()
            frame = self._driver.grab_frame_numpy()
            self._display_frame(frame)
        except Exception as exc:
            QMessageBox.warning(self, "Single Shot Error", str(exc))
        finally:
            if not was_capturing:
                self._driver.stop_capture()

    # ------------------------------------------------------------------
    # Live streaming
    # ------------------------------------------------------------------

    def _on_toggle_live(self) -> None:
        if self._live:
            self._stop_live()
        else:
            self._start_live()

    def _start_live(self) -> None:
        if self._driver is None:
            return
        try:
            if not self._driver.is_capturing:
                self._driver.start_capture()
        except Exception as exc:
            QMessageBox.critical(self, "Capture Error", str(exc))
            return

        self._worker = FrameWorker(self._driver)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.start_streaming)
        self._worker.frame_ready.connect(self._display_frame)
        self._worker.error.connect(self._on_stream_error)

        self._thread.start()
        self._live = True
        self._frame_count = 0
        self._last_fps_ts = time.perf_counter()

        self._btn_live.setText("⏹  Stop Live Stream")
        self._btn_live.setProperty("live", "true")
        self._refresh_btn_style(self._btn_live)

        self._btn_single.setEnabled(False)
        self._btn_apply.setEnabled(False)

        self._status_bar.showMessage("Live streaming…")

    def _stop_live(self) -> None:
        if self._worker:
            self._worker.stop_streaming()
        if self._thread:
            self._thread.quit()
            self._thread.wait(3000)   # max 3 s grace period
        self._worker = None
        self._thread = None

        if self._driver and self._driver.is_capturing:
            self._driver.stop_capture()

        self._live = False
        self._btn_live.setText("▶  Start Live Stream")
        self._btn_live.setProperty("live", "false")
        self._refresh_btn_style(self._btn_live)

        self._btn_single.setEnabled(True)
        self._btn_apply.setEnabled(True)

        self._status_bar.showMessage("Live stream stopped.")

    def _on_stream_error(self, msg: str) -> None:
        self._stop_live()
        QMessageBox.critical(
            self, "Stream Error", f"Frame acquisition error:\n\n{msg}"
        )

    # ------------------------------------------------------------------
    # Frame display
    # ------------------------------------------------------------------

    def _display_frame(self, frame: np.ndarray) -> None:
        """
        Update the ImageView with a new uint16 frame and refresh stats.

        Parameters
        ----------
        frame : 2-D numpy array of dtype uint16 (SENSOR_HEIGHT, SENSOR_WIDTH).
        """
        # pyqtgraph ImageView expects (height, width) for row-major images
        self._image_view.setImage(
            frame,
            autoLevels=True,
            autoHistogramRange=False,
        )

        # Frame statistics
        self._lbl_min.setText(str(int(frame.min())))
        self._lbl_max.setText(str(int(frame.max())))
        self._lbl_mean.setText(f"{frame.mean():.1f}")
        self._lbl_shape.setText(f"{frame.shape[1]} × {frame.shape[0]}")

        # Live FPS counter (update every 10 frames)
        self._frame_count += 1
        if self._frame_count % 10 == 0:
            now = time.perf_counter()
            elapsed = now - self._last_fps_ts
            fps = 10.0 / elapsed if elapsed > 0 else 0.0
            self._last_fps_ts = now
            self._lbl_fps_live.setText(f"{fps:.1f} FPS")

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _refresh_btn_style(btn: QPushButton) -> None:
        """Force Qt to re-evaluate dynamic property–based stylesheets."""
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        btn.update()

    # ------------------------------------------------------------------
    # Cleanup on close
    # ------------------------------------------------------------------

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # type: ignore[override]
        if self._live:
            self._stop_live()
        if self._driver:
            try:
                self._driver.disconnect()
            except Exception:
                pass
        event.accept()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Grasshopper2 CCD Viewer")
    app.setOrganizationName("DAQ_CA")

    # High-DPI support
    try:
        app.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)
    except AttributeError:
        pass

    win = CameraWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

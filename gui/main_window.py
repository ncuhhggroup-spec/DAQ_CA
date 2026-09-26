# gui/main_window.py
"""
Graphical User Interface for DAQ_CA control panel.

This module provides a Qt based application that connects to the EPICS
Channel Access IOC server using `caproto` and allows the user to configure
acquisition parameters, arm/start the sequence, and observe real‑time
status, console logs and camera frames.

The design deliberately isolates all network I/O into a worker thread so
that the Qt main thread remains responsive.  The worker uses the
`caproto.asyncio.client` API; a small asyncio event loop runs inside the
thread and communicates with the UI via Qt signals.
"""

import asyncio
import json
import logging
from pathlib import Path

import os

# If the user provides a specific IOC server IP via the `IOC_IP` environment variable,
# configure EPICS Channel Access to target that address. This does not override any
# existing EPICS_CA_ADDR_LIST value if the user has set it manually.
if "IOC_IP" in os.environ:
    os.environ.setdefault("EPICS_CA_ADDR_LIST", os.environ["IOC_IP"])
    os.environ.setdefault("EPICS_CA_AUTO_ADDR_LIST", "NO")

from PySide6.QtCore import Qt, Signal, Slot, QThread
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QLineEdit,
    QSpinBox,
    QDoubleSpinBox,
    QPushButton,
    QTextEdit,
    QHBoxLayout,
    QVBoxLayout,
    QMessageBox,
)

import pyqtgraph as pg

# caproto imports – the client side of EPICS Channel Access
from caproto.asyncio.client import Context

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Worker thread handling EPICS interactions
# ---------------------------------------------------------------------------
class EPICSWorker(QThread):
    """Background thread that runs an asyncio event loop and talks to the
    IOC server.

    Signals are emitted for PV value changes and for generic console
    messages.  All writes to PVs are performed via ``write_pv`` which
    schedules a coroutine onto the loop.
    """

    # Signals emitted to the UI thread
    state_changed = Signal(str)               # New state string
    console_message = Signal(str)             # Arbitrary log line
    frame_received = Signal(object)           # NumPy array representing a camera frame
    ioc_status_changed = Signal(bool)         # True=connected, False=disconnected

    def __init__(self, prefix: str = "EXP:Seq:"):
        super().__init__()
        self.prefix = prefix
        self.loop = None
        self._running = True
        # Store PV objects for quick access
        self.pvs = {}

    # ---------------------------------------------------------------------
    # Qt/QThread overrides
    # ---------------------------------------------------------------------
    def run(self) -> None:
        """Entry point for the thread – creates and runs the asyncio loop.
        """
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._setup())
        # Run the loop forever until the thread is asked to stop
        while self._running:
            try:
                self.loop.run_until_complete(asyncio.sleep(0.1))
            except Exception as exc:  # pragma: no cover – defensive
                log.exception("Exception in EPICSWorker loop: %s", exc)
        self.loop.close()

    def stop(self) -> None:
        """Request the thread to finish.
        """
        self._running = False
        # Wake the loop if it is sleeping and still open
        if self.loop and not self.loop.is_closed():
            # Trigger the loop to exit its sleep
            self.loop.call_soon_threadsafe(lambda: None)

    # ---------------------------------------------------------------------
    # EPICS client helpers – all async
    # ---------------------------------------------------------------------
    async def _setup(self) -> None:
        """Connect to required PVs and start monitoring.
        """
        pv_names = {
            "ShotTarget": "ShotTarget",
            "FileName": "FileName",
            "Note": "Note",
            "Arm": "Arm",
            "State": "State",
            "ShotInterval": "ShotInterval",
            "StageStatus": "StageStatus",
            "DG645Status": "DG645Status",
            "CameraStatus": "CameraStatus",
        }
        for attr, name in pv_names.items():
            full_name = f"{self.prefix}{name}"
            # Use the asyncio Context to obtain a PV object.
            # ``get_pvs`` returns a list; we expect exactly one PV per name.
            pvs = await Context().get_pvs(full_name)
            if not pvs:
                raise RuntimeError(f"PV {full_name} not found")
            chan = pvs[0]
            self.pvs[attr] = chan
            # Subscribe to changes for the State PV – others could be added
            if attr == "State":
                chan.subscribe(self._state_callback)
            elif attr == "StageStatus":
                chan.subscribe(lambda pv, response: self._safe_update_status(self.stage_status, response.data[0] if hasattr(response, 'data') else response))
            elif attr == "DG645Status":
                chan.subscribe(lambda pv, response: self._safe_update_status(self.dg645_status, response.data[0] if hasattr(response, 'data') else response))
            elif attr == "CameraStatus":
                chan.subscribe(lambda pv, response: self._safe_update_status(self.camera_status, response.data[0] if hasattr(response, 'data') else response))
        self.console_message.emit("Connected to EPICS IOC server.")
        self.ioc_status_changed.emit(True)

    def _state_callback(self, pv, value, **kwargs):
        """Callback invoked by caproto when the State PV changes.
        """
        state = value.decode() if isinstance(value, (bytes, bytearray)) else str(value)
        self.state_changed.emit(state)
        self.console_message.emit(f"State changed → {state}")

    def _update_status_label(self, label: QLabel, value) -> None:
        """Update a status QLabel based on PV value.
        If the value contains 'CONNECTED', set green; otherwise red.
        """
        text = value.decode() if isinstance(value, (bytes, bytearray)) else str(value)
        if "CONNECTED" in text.upper():
            color = "#28a745"
        else:
            color = "#dc3545"
        label.setStyleSheet(f"background-color: {color}; color: white; padding: 2px;")
        label.setText(text)

    def _safe_update_status(self, label: QLabel, value) -> None:
        """Wrapper to call _update_status_label with exception handling."""
        try:
            self._update_status_label(label, value)
        except Exception as exc:  # pragma: no cover – defensive
            log.exception("Exception in status label update: %s", exc)
            # Emit to console for visibility
            self.console_message.emit(f"[EPICS Error] Status update failed: {exc}")

    # ---------------------------------------------------------------------
    # Public API used by the GUI
    # ---------------------------------------------------------------------
    def write_pv(self, name: str, value) -> None:
        """Schedule a write operation onto the asyncio loop.
        """
        if name not in self.pvs:
            self.console_message.emit(f"Attempted to write unknown PV: {name}")
            return
        async def _write():
            chan = self.pvs[name]
            await chan.write(value)
            self.console_message.emit(f"Wrote {name} = {value}")
        self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(_write()))

    def request_frame(self) -> None:
        """Placeholder for a camera frame request.  In a real system this
        would trigger a read from a camera driver or a dedicated PV that
        streams image data.  For demonstration we emit a dummy NumPy array.
        """
        import numpy as np
        # Create a synthetic Gaussian blob image
        x = np.linspace(-3, 3, 256)
        y = np.linspace(-3, 3, 256)
        xv, yv = np.meshgrid(x, y)
        sigma = 0.8
        img = np.exp(-(xv**2 + yv**2) / (2 * sigma**2)) * 255
        img = img.astype(np.uint8)
        self.frame_received.emit(img)

    # ---------------------------------------------------------------------
    # Clean‑up handling
    # ---------------------------------------------------------------------
    def __del__(self):  # pragma: no cover – defensive
        self.stop()

# ---------------------------------------------------------------------------
# Main Window – UI construction and signal wiring
# ---------------------------------------------------------------------------
class MainWindow(QWidget):
    """Top‑level window for the DAQ control panel.
    """

    def __init__(self, prefix: str = "EXP:Seq:"):
        super().__init__()
        self.setWindowTitle("DAQ_CA Control Panel")
        self.resize(900, 600)
        self.worker = EPICSWorker(prefix)
        self._setup_ui()
        self._connect_signals()
        self.worker.start()

    # ---------------------------------------------------------------------
    # UI layout
    # ---------------------------------------------------------------------
    def _setup_ui(self) -> None:
        # --- Parameter input area ------------------------------------------------
        self.shot_spin = QSpinBox()
        self.shot_spin.setRange(1, 100)
        self.shot_spin.setValue(1)
        self.shot_spin.setSuffix(" shots")
        self.shot_spin.setObjectName("shot_spin")

        self.filename_edit = QLineEdit("exp_run")
        self.filename_edit.setObjectName("filename_edit")

        self.note_edit = QLineEdit()
        self.note_edit.setObjectName("note_edit")

        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.1, 3600.0)
        self.interval_spin.setValue(10.0)
        self.interval_spin.setSuffix(" s")
        self.interval_spin.setObjectName("interval_spin")
        self.interval_spin.setDecimals(2)

        # Instrument status indicators (colored labels)
        self.stage_status = QLabel("Stage: UNKNOWN")
        self.stage_status.setObjectName("stage_status")
        self.dg645_status = QLabel("DG645: UNKNOWN")
        self.dg645_status.setObjectName("dg645_status")
        self.camera_status = QLabel("Camera: UNKNOWN")
        self.ioc_status = QLabel("IOC: DISCONNECTED")
        self.ioc_status.setStyleSheet("background-color: #dc3545; color: white; padding: 2px;")
        self.camera_status.setObjectName("camera_status")

        param_layout = QVBoxLayout()
        param_layout.addWidget(QLabel("Shot Target:"))
        param_layout.addWidget(self.shot_spin)
        param_layout.addWidget(QLabel("File Name:"))
        param_layout.addWidget(self.filename_edit)
        param_layout.addWidget(QLabel("Note:"))
        param_layout.addWidget(self.note_edit)
        param_layout.addWidget(QLabel("Shot Interval (s):"))
        param_layout.addWidget(self.interval_spin)
        param_layout.addSpacing(10)
        param_layout.addWidget(QLabel("Instrument Status:"))
        param_layout.addWidget(self.stage_status)
        param_layout.addWidget(self.dg645_status)
        param_layout.addWidget(self.camera_status)
        param_layout.addWidget(self.ioc_status)

        # --- Control buttons ----------------------------------------------------
        self.arm_btn = QPushButton("ARM / START")
        self.disarm_btn = QPushButton("DISARM / CANCEL")
        self.arm_btn.setObjectName("arm_btn")
        self.disarm_btn.setObjectName("disarm_btn")
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.arm_btn)
        btn_layout.addWidget(self.disarm_btn)

        # --- State indicator ----------------------------------------------------
        self.state_label = QLabel("IDLE")
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setObjectName("state_label")
        self._apply_state_style("IDLE")

        # --- Console log --------------------------------------------------------
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setObjectName("console")

        # --- Image view ---------------------------------------------------------
        self.image_view = pg.ImageView()
        self.image_view.ui.histogram.hide()
        self.image_view.ui.roiBtn.hide()
        self.image_view.ui.menuBtn.hide()
        self.image_view.setObjectName("image_view")

        # Layout assembly --------------------------------------------------------
        left_panel = QVBoxLayout()
        left_panel.addLayout(param_layout)
        left_panel.addLayout(btn_layout)
        left_panel.addWidget(self.state_label)
        left_panel.addWidget(self.console)
        left_panel.addStretch()

        main_layout = QHBoxLayout(self)
        main_layout.addLayout(left_panel, stretch=1)
        main_layout.addWidget(self.image_view, stretch=2)

    # ---------------------------------------------------------------------
    # Styling helpers
    # ---------------------------------------------------------------------
    def _apply_state_style(self, state: str) -> None:
        """Apply background colour based on the DAQ state.
        """
        colors = {
            "IDLE": "#6c757d",
            "ARMED": "#ffc107",
            "ACQUIRING": "#0d6efd",
            "SAVING": "#6f42c1",
            "ERROR": "#dc3545",
        }
        color = colors.get(state.upper(), "#6c757d")
        style = f"background-color: {color}; color: white; font-weight: bold; padding: 6px;"
        self.state_label.setStyleSheet(style)

    # ---------------------------------------------------------------------
    # Signal wiring
    # ---------------------------------------------------------------------
    def _connect_signals(self) -> None:
        # UI -> EPICS writes
        self.shot_spin.valueChanged.connect(lambda v: self.worker.write_pv("ShotTarget", v))
        self.filename_edit.editingFinished.connect(lambda: self.worker.write_pv("FileName", self.filename_edit.text()))
        self.note_edit.editingFinished.connect(lambda: self.worker.write_pv("Note", self.note_edit.text()))
        self.interval_spin.valueChanged.connect(lambda v: self.worker.write_pv("ShotInterval", v))
        self.arm_btn.clicked.connect(self._on_arm)
        self.disarm_btn.clicked.connect(self._on_disarm)

        # Worker -> UI updates
        self.worker.state_changed.connect(self._on_state_change)
        self.worker.console_message.connect(self._append_console)
        self.worker.frame_received.connect(self._update_image)
        self.worker.ioc_status_changed.connect(self._update_ioc_status)

    # ---------------------------------------------------------------------
    def _update_ioc_status(self, connected: bool) -> None:
        """Update IOC connection status label based on boolean flag."""
        text = "IOC: CONNECTED" if connected else "IOC: DISCONNECTED"
        self.ioc_status.setText(text)
        color = "#28a745" if connected else "#dc3545"
        self.ioc_status.setStyleSheet(f"background-color: {color}; color: white; padding: 2px;")

    # UI event handlers
    # ---------------------------------------------------------------------
    @Slot()
    def _on_arm(self) -> None:
        # Write 1 to the Arm PV – the server will reset it to 0 when done
        self.worker.write_pv("Arm", 1)
        self.console.append("[User] ARM command sent.")

    @Slot()
    def _on_disarm(self) -> None:
        # Disarming is performed by writing 0 to the Arm PV (or a dedicated
        # Cancel PV if present).  Here we simply reset the state locally.
        self.worker.write_pv("Arm", 0)
        self.console.append("[User] DISARM command sent.")

    @Slot(str)
    def _on_state_change(self, new_state: str) -> None:
        self.state_label.setText(new_state.upper())
        self._apply_state_style(new_state)
        # Disable parameter widgets while active
        active = new_state.upper() in {"ARMED", "ACQUIRING", "SAVING"}
        for w in (self.shot_spin, self.filename_edit, self.note_edit, self.interval_spin):
            w.setEnabled(not active)
        self.arm_btn.setEnabled(not active)
        self.disarm_btn.setEnabled(active)

    @Slot(str)
    def _append_console(self, line: str) -> None:
        self.console.append(line)
        # Auto‑scroll to bottom
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    @Slot(object)
    def _update_image(self, img) -> None:
        # Expect a NumPy array – feed directly to pyqtgraph
        self.image_view.setImage(img, autoLevels=True)

    # ---------------------------------------------------------------------
    # Graceful shutdown
    # ---------------------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:
        # Ask the worker to stop and wait for it to finish
        self.worker.stop()
        self.worker.wait(2000)  # 2 s timeout
        super().closeEvent(event)

# ---------------------------------------------------------------------------
# Launcher helper – useful when the module is executed directly
# ---------------------------------------------------------------------------
def main() -> None:
    import sys
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

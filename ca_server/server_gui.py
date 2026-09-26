# ca_server/server_gui.py
"""Lightweight server‑side diagnostics GUI.

This window runs alongside the EPICS IOC (started in a background thread) and
shows real‑time device connection statuses, the latest error message, and a log
console.  It also provides two control buttons:

* **Rescan** – writes ``1`` to the ``EXP:Seq:Rescan`` PV to force a fresh
  connection check.
* **Clear Error** – writes ``1`` to the ``EXP:Seq:ResetError`` PV to clear the
  ``ErrorMessage`` PV.
"""

import sys
import threading
import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QHBoxLayout,
)
from PySide6.QtCore import Qt, Signal, Slot, QThread

from caproto.asyncio.client import Context

# ---------------------------------------------------------------------------
# Worker thread handling EPICS interactions for the diagnostics GUI
# ---------------------------------------------------------------------------
class DiagnosticWorker(QThread):
    """Background thread that connects to the IOC and streams PV updates.

    Signals are emitted for each PV change and for generic log messages.
    """

    # Signals
    stage_status_changed = Signal(str)
    dg_status_changed = Signal(str)
    cam_status_changed = Signal(str)
    error_message_changed = Signal(str)
    console_message = Signal(str)

    def __init__(self, prefix: str = "EXP:Seq:"):
        super().__init__()
        self.prefix = prefix
        self._running = True
        self.loop = None
        self.pvs = {}

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._setup())
        # Keep the event loop alive until stopped
        while self._running:
            try:
                self.loop.run_until_complete(asyncio.sleep(0.2))
            except Exception as exc:  # pragma: no cover – defensive
                logging.exception("Exception in DiagnosticWorker loop: %s", exc)
        self.loop.close()

    def stop(self) -> None:
        self._running = False
        if self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(lambda: None)

    async def _setup(self) -> None:
        ctx = Context()
        pv_names = {
            "StageStatus": "StageStatus",
            "DG645Status": "DG645Status",
            "CameraStatus": "CameraStatus",
            "ErrorMessage": "ErrorMessage",
        }
        for attr, name in pv_names.items():
            full_name = f"{self.prefix}{name}"
            pvs = await ctx.get_pvs(full_name)
            if not pvs:
                raise RuntimeError(f"PV {full_name} not found")
            chan = pvs[0]
            self.pvs[attr] = chan
            # Subscribe to changes
            chan.subscribe(self._make_callback(attr))
        self.console_message.emit("Connected to IOC diagnostic PVs.")

    def _make_callback(self, attr: str):
        def _callback(pv, response, **kwargs):
            try:
                value = response.data[0] if hasattr(response, "data") else response
                text = value.decode() if isinstance(value, (bytes, bytearray)) else str(value)
            except Exception:
                text = str(response)
            if attr == "StageStatus":
                self.stage_status_changed.emit(text)
            elif attr == "DG645Status":
                self.dg_status_changed.emit(text)
            elif attr == "CameraStatus":
                self.cam_status_changed.emit(text)
            elif attr == "ErrorMessage":
                self.error_message_changed.emit(text)
        return _callback

    def write_pv(self, name: str, value) -> None:
        """Schedule a write operation onto the asyncio loop."""
        if name not in self.pvs:
            self.console_message.emit(f"Attempted to write unknown PV: {name}")
            return
        async def _write():
            await self.pvs[name].write(value)
            self.console_message.emit(f"Wrote {name} = {value}")
        self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(_write()))

# ---------------------------------------------------------------------------
# Main window – UI construction and signal wiring
# ---------------------------------------------------------------------------
class ServerMonitorWindow(QWidget):
    """Top‑level window for IOC diagnostics."""

    def __init__(self, prefix: str = "EXP:Seq:"):
        super().__init__()
        self.setWindowTitle("DAQ IOC Server Monitor")
        self.resize(600, 400)
        self.worker = DiagnosticWorker(prefix)
        self._setup_ui()
        self._connect_signals()
        self.worker.start()

    # UI layout
    def _setup_ui(self) -> None:
        self.stage_label = QLabel("Stage: UNKNOWN")
        self.dg_label = QLabel("DG645: UNKNOWN")
        self.cam_label = QLabel("Camera: UNKNOWN")
        self.error_label = QLabel("Error: None")
        for lbl in (self.stage_label, self.dg_label, self.cam_label, self.error_label):
            lbl.setStyleSheet("background-color: #dc3545; color: white; padding: 2px;")

        self.rescan_btn = QPushButton("Rescan Devices")
        self.clear_error_btn = QPushButton("Clear Error")

        self.console = QTextEdit()
        self.console.setReadOnly(True)

        status_layout = QVBoxLayout()
        status_layout.addWidget(self.stage_label)
        status_layout.addWidget(self.dg_label)
        status_layout.addWidget(self.cam_label)
        status_layout.addWidget(self.error_label)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.rescan_btn)
        btn_layout.addWidget(self.clear_error_btn)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(status_layout)
        main_layout.addLayout(btn_layout)
        main_layout.addWidget(self.console)

    def _connect_signals(self) -> None:
        self.worker.stage_status_changed.connect(self._update_stage)
        self.worker.dg_status_changed.connect(self._update_dg)
        self.worker.cam_status_changed.connect(self._update_cam)
        self.worker.error_message_changed.connect(self._update_error)
        self.worker.console_message.connect(self._append_console)
        self.rescan_btn.clicked.connect(self._on_rescan)
        self.clear_error_btn.clicked.connect(self._on_clear_error)

    @Slot(str)
    def _update_stage(self, text: str) -> None:
        self._apply_status(self.stage_label, text)

    @Slot(str)
    def _update_dg(self, text: str) -> None:
        self._apply_status(self.dg_label, text)

    @Slot(str)
    def _update_cam(self, text: str) -> None:
        self._apply_status(self.cam_label, text)

    @Slot(str)
    def _update_error(self, text: str) -> None:
        if text:
            self.error_label.setStyleSheet("background-color: #dc3545; color: white; padding: 2px;")
        else:
            self.error_label.setStyleSheet("background-color: #28a745; color: white; padding: 2px;")
        self.error_label.setText(f"Error: {text or 'None'}")

    def _apply_status(self, label: QLabel, text: str) -> None:
        color = "#28a745" if "CONNECTED" in text.upper() else "#dc3545"
        label.setStyleSheet(f"background-color: {color}; color: white; padding: 2px;")
        label.setText(text)

    @Slot(str)
    def _append_console(self, line: str) -> None:
        self.console.append(line)
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    @Slot()
    def _on_rescan(self) -> None:
        self.worker.write_pv("Rescan", 1)
        self.console.append("[User] Rescan triggered.")

    @Slot()
    def _on_clear_error(self) -> None:
        self.worker.write_pv("ResetError", 1)
        self.console.append("[User] Clear Error triggered.")

    def closeEvent(self, event):
        self.worker.stop()
        self.worker.wait(2000)
        super().closeEvent(event)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    app = QApplication(sys.argv)
    win = ServerMonitorWindow()
    win.show()
    sys.exit(app.exec())

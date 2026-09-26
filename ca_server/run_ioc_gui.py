# ca_server/run_ioc_gui.py
"""Launch the DAQ IOC server and a lightweight diagnostic GUI.

The GUI displays device connection statuses, logs, and provides controls to
re‑scan device connectivity and reset error messages.
"""

import sys
import threading
import logging
from PySide6.QtWidgets import QApplication

from .ioc_server import create_ioc
from .server_gui import ServerMonitorWindow


def start_ioc():
    """Start the IOC server in a background thread."""
    # Create both the DAQ IOC and the diagnostic DeviceStatus group
    daq_ioc, diag_ioc = create_ioc(prefix="EXP:Seq:")
    # Run both PVGroups together
    from caproto.server import run
    run([daq_ioc.pvdb, diag_ioc.pvdb], startup_hook=None)


def main():
    # Configure root logger to capture messages for the GUI console
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # Start the IOC in a separate daemon thread so the Qt event loop can run
    ioc_thread = threading.Thread(target=start_ioc, daemon=True)
    ioc_thread.start()

    # Start the Qt application for the server GUI
    app = QApplication(sys.argv)
    window = ServerMonitorWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

"""
main_window.py - Main GUI Dashboard for FAULHABER MCDC 3002 S RS 3-Axis Controller.

Integrates connection panel, master global controls, 3-axis node control cards,
serial monitor terminal, and background communication worker.
"""

from datetime import datetime
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QSplitter, QStatusBar,
    QMessageBox, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer
import serial.tools.list_ports

from serial_worker import SerialWorker
from widgets.node_card import NodeCardWidget, LedIndicator
from widgets.master_panel import MasterPanelWidget
from widgets.log_panel import LogPanelWidget


class MainWindow(QMainWindow):
    """
    Main application window for 3-node FAULHABER stage controller.
    """

    DARK_STYLESHEET = """
        QMainWindow {
            background-color: #0B1120;
            color: #F1F5F9;
        }
        QWidget {
            color: #F1F5F9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            font-size: 13px;
        }
        QGroupBox {
            font-weight: 700;
            font-size: 13px;
            border: 1px solid #1E293B;
            border-radius: 8px;
            margin-top: 10px;
            padding-top: 14px;
            background-color: #131E32;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 2px 8px;
            color: #38BDF8;
        }
        QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
            background-color: #0F172A;
            border: 1px solid #334155;
            border-radius: 6px;
            padding: 4px 8px;
            color: #F8FAFC;
            font-size: 12px;
        }
        QComboBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {
            border: 1px solid #38BDF8;
        }
        QComboBox::drop-down {
            border: none;
            width: 20px;
        }
        QComboBox QAbstractItemView {
            background-color: #0F172A;
            border: 1px solid #334155;
            selection-background-color: #2563EB;
            color: #F8FAFC;
        }
        QPushButton {
            background-color: #1E293B;
            border: 1px solid #475569;
            border-radius: 6px;
            padding: 5px 12px;
            color: #F8FAFC;
            font-weight: 600;
        }
        QPushButton:hover {
            background-color: #334155;
            border-color: #64748B;
        }
        QPushButton:pressed {
            background-color: #0F172A;
        }
        QPushButton:disabled {
            background-color: #1E293B;
            border-color: #334155;
            color: #64748B;
        }
        QPushButton#enableBtn, QPushButton#masterEnableBtn {
            background-color: #065F46;
            border: 1px solid #059669;
            color: #ECFDF5;
        }
        QPushButton#enableBtn:hover, QPushButton#masterEnableBtn:hover {
            background-color: #047857;
        }
        QPushButton#disableBtn {
            background-color: #7F1D1D;
            border: 1px solid #DC2626;
            color: #FEF2F2;
        }
        QPushButton#disableBtn:hover {
            background-color: #991B1B;
        }
        QPushButton#masterEStopBtn {
            background-color: #991B1B;
            border: 2px solid #EF4444;
            color: #FFFFFF;
            font-weight: 800;
            font-size: 13px;
        }
        QPushButton#masterEStopBtn:hover {
            background-color: #B91C1C;
        }
        QPushButton#masterHomeBtn, QPushButton#homeBtn {
            background-color: #1E3A8A;
            border: 1px solid #3B82F6;
            color: #EFF6FF;
        }
        QPushButton#masterHomeBtn:hover, QPushButton#homeBtn:hover {
            background-color: #2563EB;
        }
        QPushButton#moveAbsBtn, QPushButton#sendCmdBtn {
            background-color: #0284C7;
            border: 1px solid #38BDF8;
            color: #FFFFFF;
        }
        QPushButton#moveAbsBtn:hover, QPushButton#sendCmdBtn:hover {
            background-color: #0369A1;
        }
        QPushButton#jogPosBtn, QPushButton#jogNegBtn {
            background-color: #334155;
            border: 1px solid #64748B;
            color: #38BDF8;
            font-weight: 700;
        }
        QPushButton#jogPosBtn:hover, QPushButton#jogNegBtn:hover {
            background-color: #475569;
        }
        QStatusBar {
            background-color: #090D16;
            color: #94A3B8;
            border-top: 1px solid #1E293B;
        }
        QSplitter::handle {
            background-color: #1E293B;
            height: 3px;
        }
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FAULHABER MCDC 3002 S RS — 3-Axis Multi-Node Controller")
        self.resize(1180, 850)
        self.setStyleSheet(self.DARK_STYLESHEET)

        self.worker: SerialWorker = None

        self._init_ui()
        self._refresh_com_ports()

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(14, 12, 14, 10)
        main_layout.setSpacing(10)

        # -------------------------------------------------------------
        # Top Connection Bar
        # -------------------------------------------------------------
        conn_frame = QFrame()
        conn_frame.setObjectName("connFrame")
        conn_frame.setStyleSheet("""
            QFrame#connFrame {
                background-color: #131E32;
                border: 1px solid #1E293B;
                border-radius: 8px;
                padding: 6px 12px;
            }
        """)
        conn_layout = QHBoxLayout(conn_frame)
        conn_layout.setContentsMargins(10, 8, 10, 8)
        conn_layout.setSpacing(12)

        title_lbl = QLabel("FAULHABER MCDC 3002 S")
        title_lbl.setStyleSheet("font-size: 15px; font-weight: 800; color: #38BDF8; letter-spacing: 0.5px;")
        conn_layout.addWidget(title_lbl)

        conn_layout.addSpacing(15)

        # Port selection
        conn_layout.addWidget(QLabel("COM Port:"))
        self.combo_port = QComboBox()
        self.combo_port.setMinimumWidth(150)
        conn_layout.addWidget(self.combo_port)

        self.btn_refresh_ports = QPushButton("↻ Refresh")
        self.btn_refresh_ports.setFixedHeight(30)
        self.btn_refresh_ports.setToolTip("Scan available system COM ports")
        self.btn_refresh_ports.clicked.connect(self._refresh_com_ports)
        conn_layout.addWidget(self.btn_refresh_ports)

        # Baud rate selection
        conn_layout.addWidget(QLabel("Baud:"))
        self.combo_baud = QComboBox()
        for baud in (9600, 19200, 38400, 57600, 115200):
            self.combo_baud.addItem(str(baud), baud)
        self.combo_baud.setCurrentText("9600")
        conn_layout.addWidget(self.combo_baud)

        # Connect / Disconnect button & indicator
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setFixedHeight(32)
        self.btn_connect.setStyleSheet("background-color: #2563EB; color: white; font-weight: bold; padding: 0 16px;")
        self.btn_connect.clicked.connect(self._toggle_connection)
        conn_layout.addWidget(self.btn_connect)

        self.led_conn_status = LedIndicator()
        self.lbl_conn_status = QLabel("Disconnected")
        self.lbl_conn_status.setStyleSheet("color: #EF4444; font-weight: bold; font-size: 12px;")
        conn_layout.addWidget(self.led_conn_status)
        conn_layout.addWidget(self.lbl_conn_status)

        conn_layout.addStretch()
        main_layout.addWidget(conn_frame)

        # -------------------------------------------------------------
        # Vertical Splitter dividing Control Panels and Serial Console
        # -------------------------------------------------------------
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        top_container = QWidget()
        top_layout = QVBoxLayout(top_container)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)

        # -------------------------------------------------------------
        # Master Control Panel (Global Actions)
        # -------------------------------------------------------------
        self.master_panel = MasterPanelWidget()
        self.master_panel.sig_send_command.connect(self._send_command)
        top_layout.addWidget(self.master_panel)

        # -------------------------------------------------------------
        # 3-Node Control Cards Grid
        # -------------------------------------------------------------
        nodes_layout = QHBoxLayout()
        nodes_layout.setSpacing(12)

        self.node_cards = {}
        for nid in (1, 2, 3):
            card = NodeCardWidget(node_id=nid, title=f"Axis {nid}")
            card.sig_send_command.connect(self._send_command)
            self.node_cards[nid] = card
            nodes_layout.addWidget(card, 1)

        top_layout.addLayout(nodes_layout)
        splitter.addWidget(top_container)

        # -------------------------------------------------------------
        # Serial Monitor & Command Terminal Panel
        # -------------------------------------------------------------
        self.log_panel = LogPanelWidget()
        self.log_panel.sig_send_raw.connect(self._send_raw)
        splitter.addWidget(self.log_panel)

        # Splitter sizing: 65% controls, 35% logs
        splitter.setSizes([550, 250])
        main_layout.addWidget(splitter, 1)

        # -------------------------------------------------------------
        # Status Bar
        # -------------------------------------------------------------
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready. Select COM port and click Connect.")

    def _refresh_com_ports(self):
        """Scan available COM ports using pyserial list_ports."""
        current = self.combo_port.currentText()
        self.combo_port.clear()
        ports = list(serial.tools.list_ports.comports())
        for port in ports:
            display_text = f"{port.device} ({port.description})" if port.description else port.device
            self.combo_port.addItem(display_text, port.device)

        if self.combo_port.count() == 0:
            self.combo_port.addItem("No COM Ports Found", "")

    def _toggle_connection(self):
        """Connect or disconnect serial port."""
        if self.worker and self.worker.isRunning():
            self._disconnect_serial()
        else:
            self._connect_serial()

    def _connect_serial(self):
        port_device = self.combo_port.currentData()
        if not port_device:
            QMessageBox.warning(self, "Connection Error", "Please select a valid COM port.")
            return

        baudrate = self.combo_baud.currentData()

        # Instantiate serial worker thread
        self.worker = SerialWorker()
        self.worker.configure(port=port_device, baudrate=baudrate)

        # Connect signals
        self.worker.sig_connected.connect(self._on_worker_connected)
        self.worker.sig_disconnected.connect(self._on_worker_disconnected)
        self.worker.sig_error.connect(self._on_worker_error)
        self.worker.sig_log_tx.connect(self.log_panel.append_tx)
        self.worker.sig_log_rx.connect(self.log_panel.append_rx)
        self.worker.sig_position_update.connect(self._on_position_update)
        self.worker.sig_power_state.connect(self._on_power_state_update)

        self.btn_connect.setEnabled(False)
        self.statusBar.showMessage(f"Connecting to {port_device} at {baudrate} baud...")
        self.worker.start()

    def _disconnect_serial(self):
        if self.worker:
            self.statusBar.showMessage("Disconnecting...")
            self.worker.stop()
            self.worker = None

    def _on_worker_connected(self, port: str, baud: int):
        self.led_conn_status.set_state(True)
        self.lbl_conn_status.setText(f"Connected: {port}")
        self.lbl_conn_status.setStyleSheet("color: #10B981; font-weight: bold; font-size: 12px;")
        self.btn_connect.setText("Disconnect")
        self.btn_connect.setStyleSheet("background-color: #DC2626; color: white; font-weight: bold; padding: 0 16px;")
        self.btn_connect.setEnabled(True)
        self.combo_port.setEnabled(False)
        self.combo_baud.setEnabled(False)
        self.btn_refresh_ports.setEnabled(False)

        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_panel.append_system(ts, f"Serial port {port} opened at {baud} 8-N-1. Routine polling active.")
        self.statusBar.showMessage(f"Connected to {port} @ {baud} baud.")

    def _on_worker_disconnected(self):
        self.led_conn_status.set_state(False)
        self.lbl_conn_status.setText("Disconnected")
        self.lbl_conn_status.setStyleSheet("color: #EF4444; font-weight: bold; font-size: 12px;")
        self.btn_connect.setText("Connect")
        self.btn_connect.setStyleSheet("background-color: #2563EB; color: white; font-weight: bold; padding: 0 16px;")
        self.btn_connect.setEnabled(True)
        self.combo_port.setEnabled(True)
        self.combo_baud.setEnabled(True)
        self.btn_refresh_ports.setEnabled(True)

        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_panel.append_system(ts, "Serial port disconnected.")
        self.statusBar.showMessage("Disconnected.")

    def _on_worker_error(self, err_msg: str):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_panel.append_error(ts, err_msg)
        self.statusBar.showMessage(f"Error: {err_msg}")

    def _on_position_update(self, node_id: int, counts: int):
        if node_id in self.node_cards:
            self.node_cards[node_id].update_position(counts)

    def _on_power_state_update(self, node_id: int, is_enabled: bool):
        if node_id in self.node_cards:
            self.node_cards[node_id].update_power_state(is_enabled)

    def _send_command(self, node_id: int, cmd: str):
        """Dispatch command to worker if connected."""
        if self.worker and self.worker.isRunning():
            self.worker.send_command(node_id, cmd)
        else:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self.log_panel.append_error(ts, f"Cannot send '{node_id}{cmd}': Serial port not connected.")
            self.statusBar.showMessage("Error: Connect to serial port first.")

    def _send_raw(self, raw_cmd: str):
        """Dispatch user typed command from console."""
        if self.worker and self.worker.isRunning():
            self.worker.send_raw(raw_cmd)
        else:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self.log_panel.append_error(ts, f"Cannot send '{raw_cmd}': Serial port not connected.")
            self.statusBar.showMessage("Error: Connect to serial port first.")

    def closeEvent(self, event):
        """Cleanly shutdown serial worker on window close."""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
        event.accept()

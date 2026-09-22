"""
widgets/log_panel.py - Real-time ASCII Serial Monitor and Manual Command Console.

Displays color-coded TX/RX transactions with timestamps, auto-scroll toggle,
clear button, and interactive command prompt with history recall.
"""

from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QTextEdit,
    QLineEdit, QPushButton, QCheckBox, QLabel, QFrame
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QTextCursor, QFont, QColor


class CustomCommandLine(QLineEdit):
    """QLineEdit with Up/Down arrow command history navigation."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._history = []
        self._history_idx = 0

    def add_history(self, cmd: str):
        if cmd and (not self._history or self._history[-1] != cmd):
            self._history.append(cmd)
        self._history_idx = len(self._history)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Up:
            if self._history and self._history_idx > 0:
                self._history_idx -= 1
                self.setText(self._history[self._history_idx])
            return
        elif event.key() == Qt.Key.Key_Down:
            if self._history and self._history_idx < len(self._history) - 1:
                self._history_idx += 1
                self.setText(self._history[self._history_idx])
            elif self._history_idx >= len(self._history) - 1:
                self._history_idx = len(self._history)
                self.clear()
            return
        super().keyPressEvent(event)


class LogPanelWidget(QGroupBox):
    """
    Serial monitor & ASCII console for FAULHABER communication diagnostics.
    """
    sig_send_raw = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(" Serial Terminal & Command Prompt ", parent)
        self._init_ui()

    def _init_ui(self):
        self.setObjectName("logPanel")
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # -------------------------------------------------------------
        # 1. Top Controls (Auto-scroll, Clear, Quick Info)
        # -------------------------------------------------------------
        top_ctrl_row = QHBoxLayout()
        info_label = QLabel("ASCII Traffic Monitor:")
        info_label.setStyleSheet("color: #94A3B8; font-weight: 600; font-size: 12px;")
        top_ctrl_row.addWidget(info_label)

        top_ctrl_row.addStretch()

        self.chk_autoscroll = QCheckBox("Auto-Scroll")
        self.chk_autoscroll.setChecked(True)
        top_ctrl_row.addWidget(self.chk_autoscroll)

        self.btn_clear = QPushButton("Clear Console")
        self.btn_clear.setFixedHeight(24)
        self.btn_clear.clicked.connect(self.clear_log)
        top_ctrl_row.addWidget(self.btn_clear)

        layout.addLayout(top_ctrl_row)

        # -------------------------------------------------------------
        # 2. Terminal Text Window
        # -------------------------------------------------------------
        self.terminal = QTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal.setStyleSheet("""
            QTextEdit {
                background-color: #090D16;
                color: #E2E8F0;
                border: 1px solid #1E293B;
                border-radius: 6px;
                font-family: 'Consolas', 'DejaVu Sans Mono', monospace;
                font-size: 12px;
                padding: 6px;
            }
        """)
        layout.addWidget(self.terminal, 1)

        # -------------------------------------------------------------
        # 3. Manual Command Input Row
        # -------------------------------------------------------------
        cmd_row = QHBoxLayout()
        cmd_lbl = QLabel("Command:")
        cmd_lbl.setStyleSheet("color: #38BDF8; font-weight: bold;")
        
        self.input_cmd = CustomCommandLine()
        self.input_cmd.setPlaceholderText("Enter ASCII command (e.g., 1POS, 2EN, 1LA50000, 1M, 3HO)...")
        self.input_cmd.setFixedHeight(32)
        self.input_cmd.returnPressed.connect(self._on_send_clicked)

        self.btn_send = QPushButton("Send (↵)")
        self.btn_send.setObjectName("sendCmdBtn")
        self.btn_send.setFixedHeight(32)
        self.btn_send.clicked.connect(self._on_send_clicked)

        cmd_row.addWidget(cmd_lbl)
        cmd_row.addWidget(self.input_cmd, 1)
        cmd_row.addWidget(self.btn_send)
        layout.addLayout(cmd_row)

    def _on_send_clicked(self):
        cmd = self.input_cmd.text().strip()
        if cmd:
            self.input_cmd.add_history(cmd)
            self.sig_send_raw.emit(cmd)
            self.input_cmd.clear()

    def append_tx(self, timestamp: str, text: str):
        """Append transmitted command log in neon green."""
        html = f"<span style='color: #64748B;'>[{timestamp}]</span> <b style='color: #10B981;'>TX ➜</b> <span style='color: #34D399; font-weight: 600;'>{text}</span>"
        self._append_html(html)

    def append_rx(self, timestamp: str, text: str):
        """Append received response log in cyan."""
        html = f"<span style='color: #64748B;'>[{timestamp}]</span> <b style='color: #38BDF8;'>RX ⬅</b> <span style='color: #7DD3FC;'>{text}</span>"
        self._append_html(html)

    def append_system(self, timestamp: str, text: str):
        """Append system / status information log in gold/yellow."""
        html = f"<span style='color: #64748B;'>[{timestamp}]</span> <b style='color: #FBBF24;'>SYS ℹ</b> <span style='color: #FDE68A;'>{text}</span>"
        self._append_html(html)

    def append_error(self, timestamp: str, text: str):
        """Append error log in red."""
        html = f"<span style='color: #64748B;'>[{timestamp}]</span> <b style='color: #EF4444;'>ERR ✖</b> <span style='color: #FCA5A5;'>{text}</span>"
        self._append_html(html)

    def _append_html(self, html: str):
        self.terminal.append(html)
        if self.chk_autoscroll.isChecked():
            cursor = self.terminal.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.terminal.setTextCursor(cursor)

    def clear_log(self):
        self.terminal.clear()

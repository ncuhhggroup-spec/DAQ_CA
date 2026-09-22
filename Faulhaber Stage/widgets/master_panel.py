"""
widgets/master_panel.py - Master Global Action Panel for FAULHABER multi-node network.

Provides global batch controls: Enable All, Emergency Stop/Disable All, and Home All.
"""

from PyQt6.QtWidgets import (
    QGroupBox, QHBoxLayout, QPushButton, QLabel, QFrame
)
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QIcon


class MasterPanelWidget(QGroupBox):
    """
    Master control panel triggering coordinated actions across all nodes (1, 2, 3).
    """
    # Signal emitted when a command needs to be sent: (node_id, cmd_string)
    sig_send_command = pyqtSignal(int, str)

    def __init__(self, parent=None):
        super().__init__(" Master Control (Global Actions) ", parent)
        self._init_ui()

    def _init_ui(self):
        self.setObjectName("masterPanel")
        layout = QHBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(16, 12, 16, 12)

        info_lbl = QLabel("Synchronized Node Operations:")
        info_lbl.setStyleSheet("color: #94A3B8; font-weight: 600; font-size: 13px;")
        layout.addWidget(info_lbl)

        layout.addStretch()

        # 1. Enable All Button
        self.btn_enable_all = QPushButton("⚡ Enable All Nodes")
        self.btn_enable_all.setObjectName("masterEnableBtn")
        self.btn_enable_all.setFixedHeight(38)
        self.btn_enable_all.setToolTip("Enables power stage on Nodes 1, 2, and 3 (1EN, 2EN, 3EN)")
        self.btn_enable_all.clicked.connect(self._on_enable_all)
        layout.addWidget(self.btn_enable_all)

        # 2. Home All Button
        self.btn_home_all = QPushButton("⌂ Home All Nodes")
        self.btn_home_all.setObjectName("masterHomeBtn")
        self.btn_home_all.setFixedHeight(38)
        self.btn_home_all.setToolTip("Zero current coordinates on Nodes 1, 2, and 3 (1HO, 2HO, 3HO)")
        self.btn_home_all.clicked.connect(self._on_home_all)
        layout.addWidget(self.btn_home_all)

        # 3. Emergency Stop / Disable All Button
        self.btn_estop_all = QPushButton("🛑 EMERGENCY STOP / DISABLE ALL")
        self.btn_estop_all.setObjectName("masterEStopBtn")
        self.btn_estop_all.setFixedHeight(38)
        self.btn_estop_all.setToolTip("Immediately disable power stage on all nodes (1DI, 2DI, 3DI)")
        self.btn_estop_all.clicked.connect(self._on_estop_all)
        layout.addWidget(self.btn_estop_all)

    def _on_enable_all(self):
        for node_id in (1, 2, 3):
            self.sig_send_command.emit(node_id, "EN")

    def _on_home_all(self):
        for node_id in (1, 2, 3):
            self.sig_send_command.emit(node_id, "HO")

    def _on_estop_all(self):
        for node_id in (1, 2, 3):
            self.sig_send_command.emit(node_id, "DI")

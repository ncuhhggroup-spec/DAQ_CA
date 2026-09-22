"""
widgets/node_card.py - Individual Node Control Card for Nodes 1, 2, and 3.

Provides full calibration selection, live position telemetry, power controls,
homing, absolute positioning, and jog controls.
"""

from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QDoubleSpinBox,
    QFrame, QWidget
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont

from units import StageMode, UnitConverter


class LedIndicator(QLabel):
    """Circular LED status indicator widget."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.set_state(False)

    def set_state(self, is_on: bool):
        if is_on:
            self.setStyleSheet("""
                background-color: #10B981;
                border: 2px solid #059669;
                border-radius: 8px;
            """)
            self.setToolTip("Drive Power Stage: ENABLED")
        else:
            self.setStyleSheet("""
                background-color: #EF4444;
                border: 2px solid #B91C1C;
                border-radius: 8px;
            """)
            self.setToolTip("Drive Power Stage: DISABLED")


class NodeCardWidget(QGroupBox):
    """
    Control Card for an individual FAULHABER motion controller node.
    """
    # Signal emitted when a command needs to be sent: (node_id, cmd_string)
    sig_send_command = pyqtSignal(int, str)

    def __init__(self, node_id: int, title: str = "", parent=None):
        super().__init__(f" Node {node_id}: {title or f'Axis {node_id}'} ", parent)
        self.node_id = node_id
        self.current_mode = StageMode.LINEAR
        self.last_counts = 0
        self.is_enabled = False

        self._init_ui()
        self._update_unit_labels()

    def _init_ui(self):
        self.setObjectName(f"nodeCard_{self.node_id}")
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 16, 12, 14)

        # -------------------------------------------------------------
        # 1. Calibration Mode Selector
        # -------------------------------------------------------------
        calib_layout = QHBoxLayout()
        calib_lbl = QLabel("Stage Mode:")
        calib_lbl.setStyleSheet("font-weight: bold; color: #94A3B8;")
        self.combo_mode = QComboBox()
        for mode in StageMode:
            self.combo_mode.addItem(mode.value, mode)
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        calib_layout.addWidget(calib_lbl)
        calib_layout.addWidget(self.combo_mode, 1)
        layout.addLayout(calib_layout)

        # -------------------------------------------------------------
        # 2. Status & Telemetry Display Box
        # -------------------------------------------------------------
        telemetry_frame = QFrame()
        telemetry_frame.setObjectName("telemetryFrame")
        telemetry_frame.setStyleSheet("""
            QFrame#telemetryFrame {
                background-color: #0F172A;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 6px;
            }
        """)
        telem_layout = QVBoxLayout(telemetry_frame)
        telem_layout.setSpacing(4)
        telem_layout.setContentsMargins(8, 8, 8, 8)

        # Power Status Row
        pwr_row = QHBoxLayout()
        self.led_power = LedIndicator()
        self.lbl_power_status = QLabel("DISABLED")
        self.lbl_power_status.setStyleSheet("font-weight: bold; color: #EF4444; font-size: 11px;")
        pwr_row.addWidget(QLabel("Power:"))
        pwr_row.addWidget(self.led_power)
        pwr_row.addWidget(self.lbl_power_status)
        pwr_row.addStretch()

        self.btn_set_home = QPushButton("⌂ Set Home (HO)")
        self.btn_set_home.setToolTip("Set current physical position to 0 (HO)")
        self.btn_set_home.setObjectName("homeBtn")
        self.btn_set_home.setFixedHeight(26)
        self.btn_set_home.clicked.connect(self._on_set_home)
        pwr_row.addWidget(self.btn_set_home)
        telem_layout.addLayout(pwr_row)

        # Physical Position Display
        self.lbl_phys_pos = QLabel("+0.000 µm")
        self.lbl_phys_pos.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_phys_pos.setStyleSheet("""
            font-size: 24px;
            font-weight: 700;
            color: #38BDF8;
            font-family: 'Consolas', 'Courier New', monospace;
            padding: 4px;
        """)
        telem_layout.addWidget(self.lbl_phys_pos)

        # Raw Counts Display
        raw_row = QHBoxLayout()
        raw_row.addStretch()
        raw_lbl_title = QLabel("Raw Encoder:")
        raw_lbl_title.setStyleSheet("color: #64748B; font-size: 11px;")
        self.lbl_raw_counts = QLabel("0 cts")
        self.lbl_raw_counts.setStyleSheet("""
            color: #94A3B8;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 12px;
            font-weight: 600;
        """)
        raw_row.addWidget(raw_lbl_title)
        raw_row.addWidget(self.lbl_raw_counts)
        raw_row.addStretch()
        telem_layout.addLayout(raw_row)

        layout.addWidget(telemetry_frame)

        # -------------------------------------------------------------
        # 3. Power Action Buttons
        # -------------------------------------------------------------
        pwr_btn_layout = QHBoxLayout()
        self.btn_enable = QPushButton("⚡ Enable (EN)")
        self.btn_enable.setObjectName("enableBtn")
        self.btn_enable.setFixedHeight(32)
        self.btn_enable.clicked.connect(self._on_enable)

        self.btn_disable = QPushButton("⏻ Disable (DI)")
        self.btn_disable.setObjectName("disableBtn")
        self.btn_disable.setFixedHeight(32)
        self.btn_disable.clicked.connect(self._on_disable)

        pwr_btn_layout.addWidget(self.btn_enable)
        pwr_btn_layout.addWidget(self.btn_disable)
        layout.addLayout(pwr_btn_layout)

        # -------------------------------------------------------------
        # 4. Absolute Motion Section
        # -------------------------------------------------------------
        abs_group = QFrame()
        abs_group.setStyleSheet("background-color: #1E293B; border-radius: 6px; padding: 4px;")
        abs_layout = QVBoxLayout(abs_group)
        abs_layout.setSpacing(6)
        abs_layout.setContentsMargins(6, 6, 6, 6)

        abs_title = QLabel("Absolute Move (LA + M)")
        abs_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #94A3B8;")
        abs_layout.addWidget(abs_title)

        abs_input_row = QHBoxLayout()
        self.spin_target_pos = QDoubleSpinBox()
        self.spin_target_pos.setRange(-10000000.0, 10000000.0)
        self.spin_target_pos.setDecimals(3)
        self.spin_target_pos.setValue(0.0)
        self.spin_target_pos.setFixedHeight(30)

        self.btn_move_abs = QPushButton("Move Abs")
        self.btn_move_abs.setObjectName("moveAbsBtn")
        self.btn_move_abs.setFixedHeight(30)
        self.btn_move_abs.clicked.connect(self._on_move_absolute)

        abs_input_row.addWidget(self.spin_target_pos, 1)
        abs_input_row.addWidget(self.btn_move_abs)
        abs_layout.addLayout(abs_input_row)

        layout.addWidget(abs_group)

        # -------------------------------------------------------------
        # 5. Relative Jog Motion Section
        # -------------------------------------------------------------
        jog_group = QFrame()
        jog_group.setStyleSheet("background-color: #1E293B; border-radius: 6px; padding: 4px;")
        jog_layout = QVBoxLayout(jog_group)
        jog_layout.setSpacing(6)
        jog_layout.setContentsMargins(6, 6, 6, 6)

        jog_title = QLabel("Relative Step / Jog (LR + M)")
        jog_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #94A3B8;")
        jog_layout.addWidget(jog_title)

        step_row = QHBoxLayout()
        step_lbl = QLabel("Step:")
        step_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")
        self.spin_step_size = QDoubleSpinBox()
        self.spin_step_size.setRange(0.0001, 10000000.0)
        self.spin_step_size.setDecimals(3)
        self.spin_step_size.setValue(100.0)
        self.spin_step_size.setFixedHeight(28)
        step_row.addWidget(step_lbl)
        step_row.addWidget(self.spin_step_size, 1)
        jog_layout.addLayout(step_row)

        jog_btn_row = QHBoxLayout()
        self.btn_jog_neg = QPushButton("◀ Jog -")
        self.btn_jog_neg.setObjectName("jogNegBtn")
        self.btn_jog_neg.setFixedHeight(32)
        self.btn_jog_neg.clicked.connect(self._on_jog_negative)

        self.btn_jog_pos = QPushButton("Jog + ▶")
        self.btn_jog_pos.setObjectName("jogPosBtn")
        self.btn_jog_pos.setFixedHeight(32)
        self.btn_jog_pos.clicked.connect(self._on_jog_positive)

        jog_btn_row.addWidget(self.btn_jog_neg)
        jog_btn_row.addWidget(self.btn_jog_pos)
        jog_layout.addLayout(jog_btn_row)

        layout.addWidget(jog_group)
        layout.addStretch()

    def _on_mode_changed(self):
        self.current_mode = self.combo_mode.currentData()
        self._update_unit_labels()
        self.update_position(self.last_counts)

    def _update_unit_labels(self):
        suffix = UnitConverter.get_unit_suffix(self.current_mode)
        if self.current_mode == StageMode.LINEAR:
            self.spin_target_pos.setSuffix(" µm")
            self.spin_target_pos.setDecimals(3)
            self.spin_step_size.setSuffix(" µm")
            self.spin_step_size.setDecimals(3)
        elif self.current_mode == StageMode.ROTATOR:
            self.spin_target_pos.setSuffix(" °")
            self.spin_target_pos.setDecimals(4)
            self.spin_step_size.setSuffix(" °")
            self.spin_step_size.setDecimals(4)
        else:
            self.spin_target_pos.setSuffix(" cts")
            self.spin_target_pos.setDecimals(0)
            self.spin_step_size.setSuffix(" cts")
            self.spin_step_size.setDecimals(0)

    # -------------------------------------------------------------
    # Action Slots
    # -------------------------------------------------------------
    def _on_enable(self):
        self.sig_send_command.emit(self.node_id, "EN")

    def _on_disable(self):
        self.sig_send_command.emit(self.node_id, "DI")

    def _on_set_home(self):
        self.sig_send_command.emit(self.node_id, "HO")

    def _on_move_absolute(self):
        target_phys = self.spin_target_pos.value()
        target_counts = UnitConverter.physical_to_counts(target_phys, self.current_mode)
        # Send LA followed by M
        self.sig_send_command.emit(self.node_id, f"LA{target_counts}")
        self.sig_send_command.emit(self.node_id, "M")

    def _on_jog_positive(self):
        step_phys = self.spin_step_size.value()
        step_counts = UnitConverter.physical_to_counts(step_phys, self.current_mode)
        self.sig_send_command.emit(self.node_id, f"LR{step_counts}")
        self.sig_send_command.emit(self.node_id, "M")

    def _on_jog_negative(self):
        step_phys = self.spin_step_size.value()
        # Invert step for negative jog
        step_counts = UnitConverter.physical_to_counts(-step_phys, self.current_mode)
        self.sig_send_command.emit(self.node_id, f"LR{step_counts}")
        self.sig_send_command.emit(self.node_id, "M")

    # -------------------------------------------------------------
    # External Update Slots
    # -------------------------------------------------------------
    def update_position(self, counts: int):
        self.last_counts = counts
        phys_val = UnitConverter.counts_to_physical(counts, self.current_mode)
        self.lbl_phys_pos.setText(UnitConverter.format_physical(phys_val, self.current_mode))
        self.lbl_raw_counts.setText(f"{counts:+d} cts")

    def update_power_state(self, is_enabled: bool):
        self.is_enabled = is_enabled
        self.led_power.set_state(is_enabled)
        if is_enabled:
            self.lbl_power_status.setText("ENABLED")
            self.lbl_power_status.setStyleSheet("font-weight: bold; color: #10B981; font-size: 11px;")
        else:
            self.lbl_power_status.setText("DISABLED")
            self.lbl_power_status.setStyleSheet("font-weight: bold; color: #EF4444; font-size: 11px;")

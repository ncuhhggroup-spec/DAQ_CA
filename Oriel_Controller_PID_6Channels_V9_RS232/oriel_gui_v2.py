#!/usr/bin/env python3
"""
Oriel 6-Channel Stage Controller & Single-Shot DAQ Controller (V2)
Succeeds oriel_gui.py with:
  1. Auto-save parameters and UI settings on shutdown and upon changes.
  2. Auto-save comprehensive activity and communication logbook locally on shutdown to logs/.
  3. Built-in DAQ Sequence Controller with Stage motion interlock & CA (Channel Access) ready architecture.

Organized into Tabs:
  1. 🎮 Motion Control (Clean, responsive 6-channel dashboard)
  2. ⚡ DAQ & Trigger (Single/multi-shot sequence control, filename, notes, shot target 1~100)
  3. ⚙ Calibration & Settings (Stage types, scale factors, units, renaming)
  4. 📝 Activity Log (Detailed communication logs and diagnostics)

Persistent Header:
  - Serial Port & Baud selection (saved across runs), Connect / Disconnect
  - Hardware / Simulation Mode switch
  - Global Emergency Stop (E-STOP)
"""

import sys
import os
import time
import json
import struct
import datetime
import threading
from typing import Optional, Dict, Any, List

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QLabel, QPushButton, QComboBox,
    QDoubleSpinBox, QSpinBox, QLineEdit, QTextEdit, QTabWidget,
    QStatusBar, QFrame, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QProgressBar, QCheckBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor, QPalette, QIcon

# Ensure local packages are resolvable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from drivers import OrielStageDriver, MockStageDriver, MockDG645Driver, MockCameraDriver, DG645Driver, CameraDriver
from core import DataManager, SequenceController, SystemState

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
STAGE_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stage_config.json")
APP_CONFIG_FILE = os.path.join(CONFIG_DIR, "app_config.json")

os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# Default Calibration Constants
CALIBRATION_LINEAR_UM_PER_COUNT = 0.025            # 0.025 um / count
CALIBRATION_ROTATOR_DEG_PER_COUNT = 5.15611e-5     # 5.15611 * 10^-5 deg / count

DEFAULT_CHANNEL_CONFIGS = [
    {"channel": 1, "name": "Ch 1: Linear X", "stage_type": "Linear (0.025 µm/cnt)", "unit": "µm", "factor": CALIBRATION_LINEAR_UM_PER_COUNT, "step": 10.0},
    {"channel": 2, "name": "Ch 2: Linear Y", "stage_type": "Linear (0.025 µm/cnt)", "unit": "µm", "factor": CALIBRATION_LINEAR_UM_PER_COUNT, "step": 10.0},
    {"channel": 3, "name": "Ch 3: Linear Z", "stage_type": "Linear (0.025 µm/cnt)", "unit": "µm", "factor": CALIBRATION_LINEAR_UM_PER_COUNT, "step": 10.0},
    {"channel": 4, "name": "Ch 4: Rotator θ", "stage_type": "Rotator (5.15611e-5 °/cnt)", "unit": "°", "factor": CALIBRATION_ROTATOR_DEG_PER_COUNT, "step": 1.0},
    {"channel": 5, "name": "Ch 5: Rotator φ", "stage_type": "Rotator (5.15611e-5 °/cnt)", "unit": "°", "factor": CALIBRATION_ROTATOR_DEG_PER_COUNT, "step": 1.0},
    {"channel": 6, "name": "Ch 6: Auxiliary", "stage_type": "Linear (0.025 µm/cnt)", "unit": "µm", "factor": CALIBRATION_LINEAR_UM_PER_COUNT, "step": 10.0}
]

DEFAULT_APP_CONFIG = {
    "port": "COM7",
    "baudrate": 19200,
    "active_channel": 1,
    "simulation_mode": False,
    "shot_target": 10,
    "file_name": "exp_run",
    "note": ""
}


class CompactChannelCard(QGroupBox):
    """Clean, compact motion control card for an individual channel."""
    request_select = pyqtSignal(int)
    request_move_abs = pyqtSignal(int, int)  # channel, target_counts
    request_move_rel = pyqtSignal(int, int)  # channel, delta_counts
    request_zero = pyqtSignal(int)
    request_set_pos = pyqtSignal(int, int)
    step_changed = pyqtSignal(int, float)

    def __init__(self, channel_num: int, config: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.channel = channel_num
        self.config = config
        self.current_counts = 0
        self.is_running = False
        self.is_active_channel = (channel_num == 1)
        self.init_ui()

    def init_ui(self):
        self.setTitle(self.config.get("name", f"Channel {self.channel}"))
        self.update_card_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # 1. Header: Select / Active Button & Status Badge
        header_row = QHBoxLayout()
        header_row.setSpacing(6)

        self.btn_select = QPushButton("ACTIVE" if self.is_active_channel else "Select Ch")
        self.btn_select.setFixedHeight(26)
        self.btn_select.clicked.connect(lambda: self.request_select.emit(self.channel))
        header_row.addWidget(self.btn_select, 3)

        self.lbl_status_badge = QLabel("IDLE")
        self.lbl_status_badge.setAlignment(Qt.AlignCenter)
        self.lbl_status_badge.setFixedHeight(24)
        self.lbl_status_badge.setStyleSheet("""
            QLabel {
                background: #181a1f;
                border: 1px solid #333842;
                border-radius: 4px;
                color: #98c379;
                font-weight: bold;
                font-size: 10px;
                padding: 2px 6px;
            }
        """)
        header_row.addWidget(self.lbl_status_badge, 2)
        layout.addLayout(header_row)

        # 2. Position Readout Box
        pos_box = QFrame()
        pos_box.setStyleSheet("""
            QFrame {
                background-color: #181a1f;
                border: 1px solid #333842;
                border-radius: 6px;
                padding: 4px;
            }
        """)
        pos_layout = QVBoxLayout(pos_box)
        pos_layout.setContentsMargins(6, 4, 6, 4)
        pos_layout.setSpacing(2)

        self.lbl_pos_physical = QLabel(f"0.0000 {self.get_unit()}")
        self.lbl_pos_physical.setAlignment(Qt.AlignCenter)
        self.lbl_pos_physical.setStyleSheet("font-size: 17px; font-weight: bold; color: #61afef;")
        pos_layout.addWidget(self.lbl_pos_physical)

        self.lbl_pos_counts = QLabel("0 counts")
        self.lbl_pos_counts.setAlignment(Qt.AlignCenter)
        self.lbl_pos_counts.setStyleSheet("font-size: 10px; color: #7f848e;")
        pos_layout.addWidget(self.lbl_pos_counts)

        layout.addWidget(pos_box)

        # 3. Absolute Target Move Row
        abs_row = QHBoxLayout()
        abs_row.setSpacing(4)

        self.spin_target = QDoubleSpinBox()
        self.spin_target.setDecimals(4)
        self.spin_target.setRange(-999999.0, 999999.0)
        self.spin_target.setValue(0.0)
        self.spin_target.setSuffix(f" {self.get_unit()}")
        self.spin_target.setFixedHeight(28)
        abs_row.addWidget(self.spin_target, 5)

        self.btn_move_abs = QPushButton("Go Abs")
        self.btn_move_abs.setFixedHeight(28)
        self.btn_move_abs.setStyleSheet("background-color: #3e4451; color: #abb2bf; font-weight: bold; border-radius: 4px;")
        self.btn_move_abs.clicked.connect(self.on_click_move_abs)
        abs_row.addWidget(self.btn_move_abs, 2)
        layout.addLayout(abs_row)

        # 4. Relative Move Row
        rel_row = QHBoxLayout()
        rel_row.setSpacing(4)

        self.spin_step = QDoubleSpinBox()
        self.spin_step.setDecimals(4)
        self.spin_step.setRange(0.0001, 999999.0)
        default_step = float(self.config.get("step", 10.0 if "Linear" in self.config.get("stage_type", "") else 1.0))
        self.spin_step.setValue(default_step)
        self.spin_step.setSuffix(f" {self.get_unit()}")
        self.spin_step.setFixedHeight(28)
        self.spin_step.valueChanged.connect(lambda val: self.step_changed.emit(self.channel, val))
        rel_row.addWidget(self.spin_step, 3)

        self.btn_rel_neg = QPushButton("◀ Move -")
        self.btn_rel_neg.setFixedHeight(28)
        self.btn_rel_neg.setStyleSheet("""
            QPushButton {
                background-color: #e06c75;
                color: white;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #f17a83; }
        """)
        self.btn_rel_neg.clicked.connect(lambda: self.on_click_move_rel(-1))
        rel_row.addWidget(self.btn_rel_neg, 2)

        self.btn_rel_pos = QPushButton("Move + ▶")
        self.btn_rel_pos.setFixedHeight(28)
        self.btn_rel_pos.setStyleSheet("""
            QPushButton {
                background-color: #4facfe;
                color: white;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #61bafb; }
        """)
        self.btn_rel_pos.clicked.connect(lambda: self.on_click_move_rel(+1))
        rel_row.addWidget(self.btn_rel_pos, 2)

        layout.addLayout(rel_row)

        # 5. Bottom Actions: Set Zero & Set Position
        zero_row = QHBoxLayout()
        zero_row.setSpacing(6)

        self.btn_zero = QPushButton("Set Zero (0.0)")
        self.btn_zero.setFixedHeight(25)
        self.btn_zero.setStyleSheet("background: #3e4451; color: #dcdfe4; border-radius: 4px; font-size: 11px;")
        self.btn_zero.clicked.connect(lambda: self.request_zero.emit(self.channel))

        self.btn_set_val = QPushButton("Set Pos...")
        self.btn_set_val.setFixedHeight(25)
        self.btn_set_val.setStyleSheet("background: #3e4451; color: #dcdfe4; border-radius: 4px; font-size: 11px;")
        self.btn_set_val.clicked.connect(self.on_click_set_position)

        zero_row.addWidget(self.btn_zero)
        zero_row.addWidget(self.btn_set_val)
        layout.addLayout(zero_row)

        self.update_select_button_style()

    def get_unit(self) -> str:
        return self.config.get("unit", "µm").strip() or "units"

    def get_scale_factor(self) -> float:
        factor = float(self.config.get("factor", CALIBRATION_LINEAR_UM_PER_COUNT))
        return factor if factor != 0 else 1.0

    def counts_to_physical(self, counts: int) -> float:
        return counts * self.get_scale_factor()

    def physical_to_counts(self, physical_val: float) -> int:
        factor = self.get_scale_factor()
        return int(round(physical_val / factor))

    def update_config(self, new_config: Dict[str, Any]):
        self.config = new_config
        self.setTitle(self.config.get("name", f"Channel {self.channel}"))
        u = self.get_unit()
        self.spin_target.setSuffix(f" {u}")
        self.spin_step.setSuffix(f" {u}")
        if "step" in new_config:
            self.spin_step.setValue(float(new_config["step"]))
        self.update_position_display(self.current_counts, self.is_running)

    def update_card_style(self):
        if self.is_active_channel:
            self.setStyleSheet("""
                QGroupBox {
                    font-weight: bold;
                    font-size: 12px;
                    border: 2px solid #61afef;
                    border-radius: 8px;
                    margin-top: 8px;
                    padding-top: 10px;
                    background-color: #232830;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 12px;
                    padding: 0 4px;
                    color: #61afef;
                }
            """)
        else:
            self.setStyleSheet("""
                QGroupBox {
                    font-weight: bold;
                    font-size: 12px;
                    border: 1px solid #3d4450;
                    border-radius: 8px;
                    margin-top: 8px;
                    padding-top: 10px;
                    background-color: #21252b;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 12px;
                    padding: 0 4px;
                    color: #abb2bf;
                }
            """)

    def update_select_button_style(self):
        if self.is_active_channel:
            self.btn_select.setText("ACTIVE")
            self.btn_select.setStyleSheet("background-color: #61afef; color: #1e2227; font-weight: bold; border-radius: 4px;")
        else:
            self.btn_select.setText("Select Ch")
            self.btn_select.setStyleSheet("background-color: #3e4451; color: #abb2bf; border-radius: 4px;")
        self.update_card_style()

    def set_active_state(self, is_active: bool):
        self.is_active_channel = is_active
        self.update_select_button_style()

    def update_position_display(self, counts: int, is_running: bool):
        self.current_counts = counts
        self.is_running = is_running
        phys_val = self.counts_to_physical(counts)
        unit = self.get_unit()

        if abs(phys_val) >= 1000:
            phys_str = f"{phys_val:+.2f} {unit}"
        elif abs(phys_val) >= 1:
            phys_str = f"{phys_val:+.4f} {unit}"
        else:
            phys_str = f"{phys_val:+.5f} {unit}"

        self.lbl_pos_physical.setText(phys_str)
        self.lbl_pos_counts.setText(f"{counts:+,d} counts")

        if is_running:
            self.lbl_status_badge.setText("MOVING")
            self.lbl_status_badge.setStyleSheet("""
                QLabel {
                    background: #3b3524;
                    border: 1px solid #e5c07b;
                    border-radius: 4px;
                    color: #e5c07b;
                    font-weight: bold;
                    font-size: 10px;
                    padding: 2px 6px;
                }
            """)
        else:
            self.lbl_status_badge.setText("IDLE")
            self.lbl_status_badge.setStyleSheet("""
                QLabel {
                    background: #181a1f;
                    border: 1px solid #333842;
                    border-radius: 4px;
                    color: #98c379;
                    font-weight: bold;
                    font-size: 10px;
                    padding: 2px 6px;
                }
            """)

    def on_click_move_abs(self):
        phys_target = self.spin_target.value()
        target_counts = self.physical_to_counts(phys_target)
        self.request_move_abs.emit(self.channel, target_counts)

    def on_click_move_rel(self, direction: int):
        step_phys = self.spin_step.value() * direction
        delta_counts = self.physical_to_counts(step_phys)
        self.request_move_rel.emit(self.channel, delta_counts)

    def on_click_set_position(self):
        phys_val = self.spin_target.value()
        counts = self.physical_to_counts(phys_val)
        self.request_set_pos.emit(self.channel, counts)


class CalibrationSettingsTab(QWidget):
    """Settings Tab for Channel Names, Stage Types, Scale Factors, and Units."""
    config_changed = pyqtSignal()

    def __init__(self, configs: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.configs = configs
        self.rows: Dict[int, Dict[str, Any]] = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        info_label = QLabel(
            "<b>Channel Calibration & Configuration:</b> Configure stage types and calibration factors for each channel. "
            "All changes are automatically saved upon exit and update motion controls immediately."
        )
        info_label.setStyleSheet("color: #61afef; font-size: 12px;")
        layout.addWidget(info_label)

        # Settings Table
        self.table = QTableWidget(6, 5)
        self.table.setHorizontalHeaderLabels([
            "Channel", "Display Name", "Stage Type Preset", "Scale Factor (units/count)", "Unit"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #21252b;
                gridline-color: #333842;
                border: 1px solid #3d4450;
                border-radius: 6px;
            }
            QHeaderView::section {
                background-color: #1e2227;
                color: #abb2bf;
                font-weight: bold;
                padding: 6px;
                border: 1px solid #333842;
            }
        """)

        for i in range(6):
            ch_num = i + 1
            cfg = next((c for c in self.configs if c.get("channel") == ch_num), DEFAULT_CHANNEL_CONFIGS[i])

            # Col 0: Channel #
            lbl_ch = QLabel(f"<b>Ch {ch_num}</b>")
            lbl_ch.setAlignment(Qt.AlignCenter)
            self.table.setCellWidget(i, 0, lbl_ch)

            # Col 1: Name
            txt_name = QLineEdit(cfg.get("name", f"Ch {ch_num}"))
            self.table.setCellWidget(i, 1, txt_name)

            # Col 2: Stage Type Preset
            combo_type = QComboBox()
            combo_type.addItems([
                "Linear (0.025 µm/cnt)",
                "Rotator (5.15611e-5 °/cnt)",
                "Custom"
            ])
            cur_type = cfg.get("stage_type", "Linear (0.025 µm/cnt)")
            idx = combo_type.findText(cur_type)
            if idx >= 0:
                combo_type.setCurrentIndex(idx)
            self.table.setCellWidget(i, 2, combo_type)

            # Col 3: Scale Factor
            spin_factor = QDoubleSpinBox()
            spin_factor.setDecimals(8)
            spin_factor.setRange(1e-9, 10000.0)
            spin_factor.setValue(float(cfg.get("factor", CALIBRATION_LINEAR_UM_PER_COUNT)))
            self.table.setCellWidget(i, 3, spin_factor)

            # Col 4: Unit
            txt_unit = QLineEdit(cfg.get("unit", "µm"))
            txt_unit.setMaximumWidth(70)
            self.table.setCellWidget(i, 4, txt_unit)

            # Connect callbacks
            combo_type.currentIndexChanged.connect(lambda idx, c=combo_type, sf=spin_factor, tu=txt_unit: self.on_type_preset_changed(c, sf, tu))
            txt_name.textChanged.connect(self.notify_change)
            spin_factor.valueChanged.connect(self.notify_change)
            txt_unit.textChanged.connect(self.notify_change)

            self.rows[ch_num] = {
                "name": txt_name,
                "type": combo_type,
                "factor": spin_factor,
                "unit": txt_unit,
                "step": cfg.get("step", 10.0)
            }

        layout.addWidget(self.table)

        # Bottom presets reference note & buttons
        bottom_row = QHBoxLayout()
        ref_label = QLabel(
            "<b>Presets Reference:</b><br>"
            "• Oriel Linear Stage: <code>0.025 µm / count</code><br>"
            "• Rotator Stage: <code>5.15611 × 10⁻⁵ deg / count</code> (5.15611e-5 °/cnt)"
        )
        ref_label.setStyleSheet("color: #7f848e; font-size: 11px;")
        bottom_row.addWidget(ref_label)
        bottom_row.addStretch()

        self.btn_reset_defaults = QPushButton("Reset to Defaults")
        self.btn_reset_defaults.setStyleSheet("background-color: #3e4451; color: #abb2bf; padding: 6px 14px;")
        self.btn_reset_defaults.clicked.connect(self.reset_to_defaults)
        bottom_row.addWidget(self.btn_reset_defaults)

        layout.addLayout(bottom_row)

    def on_type_preset_changed(self, combo: QComboBox, spin_factor: QDoubleSpinBox, txt_unit: QLineEdit):
        text = combo.currentText()
        if "Linear" in text:
            spin_factor.setValue(CALIBRATION_LINEAR_UM_PER_COUNT)
            txt_unit.setText("µm")
        elif "Rotator" in text:
            spin_factor.setValue(CALIBRATION_ROTATOR_DEG_PER_COUNT)
            txt_unit.setText("°")
        self.notify_change()

    def notify_change(self):
        self.config_changed.emit()

    def reset_to_defaults(self):
        reply = QMessageBox.question(
            self, "Reset Defaults",
            "Reset all channels to default calibration presets?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            for i in range(6):
                ch_num = i + 1
                def_cfg = DEFAULT_CHANNEL_CONFIGS[i]
                row = self.rows[ch_num]
                row["name"].setText(def_cfg["name"])
                idx = row["type"].findText(def_cfg["stage_type"])
                if idx >= 0:
                    row["type"].setCurrentIndex(idx)
                row["factor"].setValue(def_cfg["factor"])
                row["unit"].setText(def_cfg["unit"])
            self.notify_change()

    def get_all_configs(self) -> List[Dict[str, Any]]:
        cfg_list = []
        for ch_num in range(1, 7):
            row = self.rows[ch_num]
            cfg_list.append({
                "channel": ch_num,
                "name": row["name"].text().strip(),
                "stage_type": row["type"].currentText(),
                "factor": row["factor"].value(),
                "unit": row["unit"].text().strip(),
                "step": row.get("step", 10.0)
            })
        return cfg_list


class DAQControlTab(QWidget):
    """Integrated DAQ & Trigger Automation Tab."""
    request_arm_start = pyqtSignal()

    def __init__(self, controller: SequenceController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Overview Banner
        banner = QLabel(
            "<b>Single-Shot / Multi-Shot DAQ Control:</b> Arm hardware trigger, fire DG645 burst, "
            "stream frames to zero-copy RAM buffer, compute live metrics, and append to <code>experiment_log.xlsx</code>."
        )
        banner.setStyleSheet("color: #61afef; font-size: 12px; margin-bottom: 4px;")
        layout.addWidget(banner)

        # Config Group Box
        cfg_box = QGroupBox("Experiment Configuration")
        cfg_box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #3d4450;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 14px;
                background-color: #21252b;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                color: #98c379;
            }
        """)
        cfg_grid = QGridLayout(cfg_box)
        cfg_grid.setContentsMargins(14, 14, 14, 14)
        cfg_grid.setSpacing(10)

        cfg_grid.addWidget(QLabel("<b>File Name Prefix:</b>"), 0, 0)
        self.txt_filename = QLineEdit("exp_run")
        cfg_grid.addWidget(self.txt_filename, 0, 1)

        cfg_grid.addWidget(QLabel("<b>Shot Target (1~100):</b>"), 0, 2)
        self.spin_shots = QSpinBox()
        self.spin_shots.setRange(1, 100)
        self.spin_shots.setValue(10)
        cfg_grid.addWidget(self.spin_shots, 0, 3)

        cfg_grid.addWidget(QLabel("<b>Experiment Note:</b>"), 1, 0)
        self.txt_note = QLineEdit("")
        self.txt_note.setPlaceholderText("e.g. Pump-probe scan at 100um pos")
        cfg_grid.addWidget(self.txt_note, 1, 1, 1, 3)

        layout.addWidget(cfg_box)

        # Sequence Control & Status Box
        ctrl_box = QGroupBox("Execution & Sequence State")
        ctrl_box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #3d4450;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 14px;
                background-color: #21252b;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                color: #e5c07b;
            }
        """)
        ctrl_layout = QVBoxLayout(ctrl_box)
        ctrl_layout.setContentsMargins(14, 14, 14, 14)
        ctrl_layout.setSpacing(12)

        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("<b>Current DAQ State:</b>"))
        self.lbl_daq_state = QLabel("IDLE")
        self.lbl_daq_state.setStyleSheet("""
            QLabel {
                background: #181a1f;
                border: 1px solid #333842;
                border-radius: 4px;
                color: #98c379;
                font-weight: bold;
                font-size: 13px;
                padding: 4px 12px;
            }
        """)
        status_row.addWidget(self.lbl_daq_state)
        status_row.addStretch()

        self.btn_arm_start = QPushButton("🚀 Arm & Start DAQ Sequence")
        self.btn_arm_start.setFixedHeight(36)
        self.btn_arm_start.setStyleSheet("""
            QPushButton {
                background-color: #98c379;
                color: #1e2227;
                font-size: 13px;
                font-weight: bold;
                padding: 6px 20px;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #a8d589; }
        """)
        self.btn_arm_start.clicked.connect(self.request_arm_start.emit)
        status_row.addWidget(self.btn_arm_start)
        ctrl_layout.addLayout(status_row)

        # Metrics display box
        metrics_box = QFrame()
        metrics_box.setStyleSheet("background: #181a1f; border: 1px solid #333842; border-radius: 6px; padding: 8px;")
        m_layout = QHBoxLayout(metrics_box)
        self.lbl_metrics = QLabel("Last Acquisition: No data captured yet.")
        self.lbl_metrics.setStyleSheet("color: #abb2bf; font-family: monospace;")
        m_layout.addWidget(self.lbl_metrics)
        ctrl_layout.addWidget(metrics_box)

        layout.addWidget(ctrl_box)
        layout.addStretch()

    def update_state_display(self, state: SystemState):
        self.lbl_daq_state.setText(state.value)
        color_map = {
            SystemState.IDLE: ("#98c379", "#181a1f"),
            SystemState.ARMED: ("#e5c07b", "#3b3524"),
            SystemState.ACQUIRING: ("#61afef", "#1f2d3d"),
            SystemState.SAVING: ("#c678dd", "#2d2036"),
            SystemState.ERROR: ("#e06c75", "#3a1e22")
        }
        fg, bg = color_map.get(state, ("#abb2bf", "#181a1f"))
        self.lbl_daq_state.setStyleSheet(f"""
            QLabel {{
                background: {bg};
                border: 1px solid {fg};
                border-radius: 4px;
                color: {fg};
                font-weight: bold;
                font-size: 13px;
                padding: 4px 12px;
            }}
        """)
        self.btn_arm_start.setEnabled(state == SystemState.IDLE or state == SystemState.ERROR)

    def update_metrics_display(self, metrics: Dict[str, Any], save_path: str):
        if not metrics:
            return
        self.lbl_metrics.setText(
            f"Saved: {os.path.basename(save_path)} | Frames: {metrics.get('frames_count')} | "
            f"Mean: {metrics.get('mean_intensity')} | Peak: {metrics.get('max_intensity')} | "
            f"Std: {metrics.get('std_intensity')}"
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.session_log_records: List[str] = []
        self.configs = self.load_stage_configs()
        self.app_config = self.load_app_config()

        self.simulation_mode = self.app_config.get("simulation_mode", False)
        self.active_channel = self.app_config.get("active_channel", 1)

        self.init_hardware_and_controllers()
        self.channel_cards: Dict[int, CompactChannelCard] = {}

        self.init_ui()
        self.init_polling_timer()
        self.refresh_com_ports()
        
        # If in simulation mode or connected, sync all channel positions immediately on startup
        if self.stage_driver.is_connected():
            self.sync_all_channels_positions()

    def init_hardware_and_controllers(self):
        """Instantiates drivers, DataManager, and SequenceController."""
        if self.simulation_mode:
            self.stage_driver = MockStageDriver()
            self.camera_driver = MockCameraDriver()
            self.dg645_driver = MockDG645Driver()
        else:
            self.stage_driver = OrielStageDriver()
            self.camera_driver = CameraDriver()
            self.dg645_driver = DG645Driver()

        self.data_manager = DataManager()
        self.seq_controller = SequenceController(
            stage_driver=self.stage_driver,
            camera_driver=self.camera_driver,
            dg645_driver=self.dg645_driver,
            data_manager=self.data_manager,
            on_state_change=self.on_seq_state_changed,
            on_log=self.log
        )

    def load_stage_configs(self) -> List[Dict[str, Any]]:
        if os.path.exists(STAGE_CONFIG_FILE):
            try:
                with open(STAGE_CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Failed to load {STAGE_CONFIG_FILE}: {e}")
        return DEFAULT_CHANNEL_CONFIGS

    def load_app_config(self) -> Dict[str, Any]:
        if os.path.exists(APP_CONFIG_FILE):
            try:
                with open(APP_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    merged = DEFAULT_APP_CONFIG.copy()
                    merged.update(cfg)
                    return merged
            except Exception as e:
                print(f"Failed to load {APP_CONFIG_FILE}: {e}")
        return DEFAULT_APP_CONFIG.copy()

    def save_all_configs(self):
        """Auto-saves all stage calibration parameters and UI settings."""
        # 1. Save Stage Configs
        cfg_list = self.settings_tab.get_all_configs()
        # Merge individual card steps
        for cfg in cfg_list:
            ch = cfg["channel"]
            if ch in self.channel_cards:
                cfg["step"] = self.channel_cards[ch].spin_step.value()

        try:
            with open(STAGE_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg_list, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log(f"Error saving stage config: {e}")

        # 2. Save App UI Config
        self.app_config["port"] = self.combo_port.currentText()
        self.app_config["baudrate"] = int(self.combo_baud.currentText()) if self.combo_baud.currentText().isdigit() else 19200
        self.app_config["active_channel"] = self.active_channel
        self.app_config["simulation_mode"] = self.chk_sim_mode.isChecked()
        self.app_config["shot_target"] = self.daq_tab.spin_shots.value()
        self.app_config["file_name"] = self.daq_tab.txt_filename.text().strip()
        self.app_config["note"] = self.daq_tab.txt_note.text().strip()

        try:
            with open(APP_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.app_config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log(f"Error saving app config: {e}")

    def save_local_logbook(self):
        """Auto-saves session activity and serial communications locally on shutdown."""
        if not self.session_log_records:
            return
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = os.path.join(LOG_DIR, f"activity_{timestamp}.log")
        try:
            with open(log_filename, "w", encoding="utf-8") as f:
                f.write(f"=== Oriel Stage & DAQ Activity Logbook - {timestamp} ===\n\n")
                for line in self.session_log_records:
                    f.write(line + "\n")
            print(f"[Logbook] Successfully saved local log to: {log_filename}")
        except Exception as e:
            print(f"[Logbook] Failed to write local logbook: {e}")

    def init_ui(self):
        self.setWindowTitle("Oriel 6-Channel Stage Controller & DAQ - Multi-Channel PID GUI (V2)")
        self.resize(1120, 700)
        self.setMinimumSize(960, 600)
        self.setStyleSheet("""
            QMainWindow { background-color: #1e2227; }
            QWidget { color: #abb2bf; font-family: 'Segoe UI', Arial, sans-serif; font-size: 12px; }
            QPushButton { border-radius: 4px; padding: 4px 10px; font-weight: 500; }
            QPushButton:hover { filter: brightness(1.15); }
            QPushButton:pressed { filter: brightness(0.9); }
            QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
                background-color: #282c34; border: 1px solid #3e4451; border-radius: 4px; padding: 3px 6px; color: #abb2bf;
            }
            QTabWidget::pane { border: 1px solid #3e4451; background-color: #1e2227; border-radius: 6px; }
            QTabBar::tab {
                background: #181a1f; border: 1px solid #3e4451; padding: 8px 18px; margin-right: 3px; font-weight: bold;
                border-top-left-radius: 6px; border-top-right-radius: 6px;
            }
            QTabBar::tab:selected { background: #282c34; border-bottom-color: #282c34; color: #61afef; }
            QTextEdit {
                background-color: #181a1f; border: 1px solid #333842; border-radius: 4px;
                font-family: 'Consolas', monospace; font-size: 11px; color: #98c379;
            }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(10)

        # 1. PERSISTENT TOP BAR: Connection & Global Controls
        top_bar = QFrame()
        top_bar.setStyleSheet("background-color: #21252b; border: 1px solid #3d4450; border-radius: 8px; padding: 4px;")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 5, 10, 5)
        top_layout.setSpacing(10)

        top_layout.addWidget(QLabel("<b>Serial Port:</b>"))
        self.combo_port = QComboBox()
        self.combo_port.setMinimumWidth(110)
        top_layout.addWidget(self.combo_port)

        self.btn_refresh_ports = QPushButton("⟳ Refresh")
        self.btn_refresh_ports.setStyleSheet("background-color: #3e4451; color: white;")
        self.btn_refresh_ports.clicked.connect(self.refresh_com_ports)
        top_layout.addWidget(self.btn_refresh_ports)

        top_layout.addWidget(QLabel("<b>Baud:</b>"))
        self.combo_baud = QComboBox()
        self.combo_baud.addItems(["19200", "9600", "38400", "57600", "115200"])
        saved_baud = str(self.app_config.get("baudrate", 19200))
        idx_baud = self.combo_baud.findText(saved_baud)
        if idx_baud >= 0:
            self.combo_baud.setCurrentIndex(idx_baud)
        top_layout.addWidget(self.combo_baud)

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setStyleSheet("background-color: #98c379; color: #1e2227; font-weight: bold; padding: 6px 16px;")
        self.btn_connect.clicked.connect(self.toggle_connection)
        top_layout.addWidget(self.btn_connect)

        self.lbl_conn_status = QLabel("Disconnected")
        self.lbl_conn_status.setStyleSheet("color: #e06c75; font-weight: bold; margin-left: 6px;")
        top_layout.addWidget(self.lbl_conn_status)

        # Simulation Mode checkbox
        self.chk_sim_mode = QCheckBox("Simulation Mock")
        self.chk_sim_mode.setChecked(self.simulation_mode)
        self.chk_sim_mode.toggled.connect(self.toggle_simulation_mode)
        top_layout.addWidget(self.chk_sim_mode)

        top_layout.addStretch()

        # Save config button
        self.btn_save_cfg = QPushButton("💾 Save Config")
        self.btn_save_cfg.setStyleSheet("background-color: #4facfe; color: white; padding: 6px 14px;")
        self.btn_save_cfg.clicked.connect(self.manual_save_configs)
        top_layout.addWidget(self.btn_save_cfg)

        # EMERGENCY STOP ALL
        self.btn_estop = QPushButton("🛑 EMERGENCY STOP")
        self.btn_estop.setStyleSheet("""
            QPushButton {
                background-color: #e06c75;
                color: white;
                font-weight: bold;
                font-size: 13px;
                padding: 6px 18px;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #ff5555; }
        """)
        self.btn_estop.clicked.connect(self.handle_estop)
        top_layout.addWidget(self.btn_estop)

        main_layout.addWidget(top_bar)

        # 2. TAB WIDGET
        self.tabs = QTabWidget()

        # --- TAB 1: MOTION CONTROL ---
        tab_motion = QWidget()
        motion_layout = QVBoxLayout(tab_motion)
        motion_layout.setContentsMargins(8, 8, 8, 8)

        grid_container = QWidget()
        channels_grid = QGridLayout(grid_container)
        channels_grid.setContentsMargins(0, 0, 0, 0)
        channels_grid.setSpacing(10)

        for i in range(6):
            ch_num = i + 1
            cfg = next((c for c in self.configs if c.get("channel") == ch_num), DEFAULT_CHANNEL_CONFIGS[i])
            card = CompactChannelCard(ch_num, cfg, self)
            card.request_select.connect(self.handle_select_channel)
            card.request_move_abs.connect(self.handle_move_abs)
            card.request_move_rel.connect(self.handle_move_rel)
            card.request_zero.connect(self.handle_zero)
            card.request_set_pos.connect(self.handle_set_position)
            card.step_changed.connect(self.handle_step_changed)
            self.channel_cards[ch_num] = card

            row = i // 3
            col = i % 3
            channels_grid.addWidget(card, row, col)

        motion_layout.addWidget(grid_container)
        self.tabs.addTab(tab_motion, "🎮 Motion Control")

        # --- TAB 2: DAQ CONTROL ---
        self.daq_tab = DAQControlTab(self.seq_controller, self)
        self.daq_tab.request_arm_start.connect(self.handle_arm_and_start)
        self.daq_tab.txt_filename.setText(self.app_config.get("file_name", "exp_run"))
        self.daq_tab.spin_shots.setValue(self.app_config.get("shot_target", 10))
        self.daq_tab.txt_note.setText(self.app_config.get("note", ""))
        self.tabs.addTab(self.daq_tab, "⚡ DAQ & Trigger")

        # --- TAB 3: CALIBRATION & SETTINGS ---
        self.settings_tab = CalibrationSettingsTab(self.configs, self)
        self.settings_tab.config_changed.connect(self.on_settings_updated)
        self.tabs.addTab(self.settings_tab, "⚙ Calibration & Settings")

        # --- TAB 4: ACTIVITY LOG ---
        tab_log = QWidget()
        log_layout = QVBoxLayout(tab_log)
        log_layout.setContentsMargins(8, 8, 8, 8)
        log_layout.setSpacing(6)

        log_top = QHBoxLayout()
        log_top.addWidget(QLabel("<b>Controller Activity & Serial Communication Log:</b>"))
        log_top.addStretch()
        self.btn_clear_log = QPushButton("Clear Log")
        self.btn_clear_log.setStyleSheet("background: #3e4451; color: #abb2bf;")
        self.btn_clear_log.clicked.connect(lambda: self.txt_log.clear())
        log_top.addWidget(self.btn_clear_log)
        log_layout.addLayout(log_top)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        log_layout.addWidget(self.txt_log)

        self.tabs.addTab(tab_log, "📝 Activity Log")

        main_layout.addWidget(self.tabs)

        self.handle_select_channel(self.active_channel)
        self.log("Oriel 6-Channel Controller & DAQ GUI Initialized.")
        self.log(f"Auto-save config directory: {CONFIG_DIR} | Log directory: {LOG_DIR}")

    def on_settings_updated(self):
        new_configs = self.settings_tab.get_all_configs()
        self.configs = new_configs
        for cfg in new_configs:
            ch_num = cfg.get("channel")
            if ch_num in self.channel_cards:
                self.channel_cards[ch_num].update_config(cfg)
        self.save_all_configs()

    def handle_step_changed(self, ch: int, val: float):
        for cfg in self.configs:
            if cfg.get("channel") == ch:
                cfg["step"] = val
        self.save_all_configs()

    def manual_save_configs(self):
        self.save_all_configs()
        self.log("Configuration parameters saved to disk.")
        QMessageBox.information(self, "Saved", "All configuration parameters saved successfully!")

    def toggle_simulation_mode(self, checked: bool):
        self.simulation_mode = checked
        if self.stage_driver.is_connected():
            self.toggle_connection()
        self.init_hardware_and_controllers()
        self.log(f"Switched mode: {'[SIMULATION MOCK]' if checked else '[REAL HARDWARE]'}")

    def init_polling_timer(self):
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(200)
        self.poll_timer.timeout.connect(self.poll_controller_status)

    def refresh_com_ports(self):
        saved_port = self.app_config.get("port", "COM7")
        self.combo_port.clear()
        if serial:
            ports = serial.tools.list_ports.comports()
            preferred_idx = 0
            for idx, p in enumerate(ports):
                self.combo_port.addItem(p.device)
                if p.device == saved_port:
                    preferred_idx = idx
            if self.combo_port.count() > 0:
                self.combo_port.setCurrentIndex(preferred_idx)
            else:
                self.combo_port.addItem(saved_port)
        else:
            self.combo_port.addItem(saved_port)

    def toggle_connection(self):
        if self.stage_driver.is_connected():
            self.stage_driver.disconnect()
            self.btn_connect.setText("Connect")
            self.btn_connect.setStyleSheet("background-color: #98c379; color: #1e2227; font-weight: bold;")
            self.lbl_conn_status.setText("Disconnected")
            self.lbl_conn_status.setStyleSheet("color: #e06c75; font-weight: bold; margin-left: 6px;")
            self.poll_timer.stop()
            self.log("Disconnected from stage controller.")
        else:
            port = self.combo_port.currentText()
            try:
                baud = int(self.combo_baud.currentText())
            except ValueError:
                baud = 19200
            
            try:
                self.log(f"Connecting to {port} @ {baud} baud...")
                self.stage_driver.connect(port=port, baudrate=baud)
                self.btn_connect.setText("Disconnect")
                self.btn_connect.setStyleSheet("background-color: #e06c75; color: white; font-weight: bold;")
                self.lbl_conn_status.setText(f"Connected ({port})")
                self.lbl_conn_status.setStyleSheet("color: #98c379; font-weight: bold; margin-left: 6px;")
                
                # Fetch positions of all channels immediately
                self.sync_all_channels_positions()
                
                self.poll_timer.start()
                self.log(f"Connected to {port} successfully. Synced all channel positions.")
                self.handle_select_channel(self.active_channel)
            except Exception as e:
                self.log(f"Connection Failed: {e}")
                QMessageBox.critical(self, "Connection Error", f"Could not connect to {port}:\n{e}")

    def sync_all_channels_positions(self):
        """Queries and updates positions for all 6 channels from the controller."""
        if not self.stage_driver.is_connected():
            return
        try:
            self.log("[Controller] Syncing current positions of all 6 channels...")
            all_pos = self.stage_driver.get_all_positions()
            for ch, stat in all_pos.items():
                pos = stat["position"]
                running = stat["running"]
                if ch in self.channel_cards:
                    self.channel_cards[ch].update_position_display(pos, running)
            self.log("[Controller] All 6 channels positions updated.")
        except Exception as e:
            self.log(f"[Warning] Failed to sync all channel positions: {e}")

    def poll_controller_status(self):
        if not self.stage_driver.is_connected():
            return
        try:
            status = self.stage_driver.get_status()
            if status:
                ch = status["channel"]
                pos = status["position"]
                running = status["running"]
                if ch in self.channel_cards:
                    self.channel_cards[ch].update_position_display(pos, running)
        except Exception:
            pass

    def handle_select_channel(self, ch: int):
        self.active_channel = ch
        for c, card in self.channel_cards.items():
            card.set_active_state(c == ch)
        if self.stage_driver.is_connected():
            try:
                self.stage_driver.select_channel(ch)
                self.log(f"Selected Channel {ch}")
            except Exception as e:
                self.log(f"Failed to switch channel to {ch}: {e}")

    def handle_move_abs(self, ch: int, target_counts: int):
        if not self.stage_driver.is_connected():
            QMessageBox.warning(self, "Not Connected", "Please connect to serial port or enable simulation mode first.")
            return
        try:
            if self.active_channel != ch:
                self.handle_select_channel(ch)
                time.sleep(0.05)
            self.stage_driver.move_to(target_counts)
            card = self.channel_cards.get(ch)
            phys = card.counts_to_physical(target_counts) if card else 0
            unit = card.get_unit() if card else ""
            self.log(f"Ch {ch} Moving to Target: {phys:.4f} {unit} ({target_counts} counts)")
        except Exception as e:
            self.log(f"Error moving Ch {ch}: {e}")

    def handle_move_rel(self, ch: int, delta_counts: int):
        if not self.stage_driver.is_connected():
            QMessageBox.warning(self, "Not Connected", "Please connect to serial port or enable simulation mode first.")
            return
        try:
            if self.active_channel != ch:
                self.handle_select_channel(ch)
                time.sleep(0.05)
            current_counts = self.channel_cards[ch].current_counts
            target_counts = current_counts + delta_counts
            self.stage_driver.move_to(target_counts)
            card = self.channel_cards.get(ch)
            delta_phys = card.counts_to_physical(delta_counts) if card else 0
            unit = card.get_unit() if card else ""
            self.log(f"Ch {ch} Relative Move: {delta_phys:+.4f} {unit} (Target: {target_counts} cnt)")
        except Exception as e:
            self.log(f"Error relative moving Ch {ch}: {e}")

    def handle_zero(self, ch: int):
        if not self.stage_driver.is_connected():
            QMessageBox.warning(self, "Not Connected", "Please connect to serial port or enable simulation mode first.")
            return
        reply = QMessageBox.question(
            self, f"Zero Channel {ch}",
            f"Are you sure you want to set the origin (0.0) for Channel {ch}?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                if self.active_channel != ch:
                    self.handle_select_channel(ch)
                    time.sleep(0.05)
                self.stage_driver.set_position(0)
                self.log(f"Ch {ch} Position Zeroed (Origin set).")
            except Exception as e:
                self.log(f"Error zeroing Ch {ch}: {e}")

    def handle_set_position(self, ch: int, new_counts: int):
        if not self.stage_driver.is_connected():
            QMessageBox.warning(self, "Not Connected", "Please connect to serial port or enable simulation mode first.")
            return
        try:
            if self.active_channel != ch:
                self.handle_select_channel(ch)
                time.sleep(0.05)
            self.stage_driver.set_position(new_counts)
            self.log(f"Ch {ch} Position set to {new_counts} counts.")
        except Exception as e:
            self.log(f"Error setting position Ch {ch}: {e}")

    def handle_estop(self):
        try:
            self.stage_driver.estop()
            self.log("!!! EMERGENCY STOP SENT (ALL MOTION HALTED) !!!")
        except Exception as e:
            self.log(f"Error sending E-STOP: {e}")

    def handle_arm_and_start(self):
        """Triggers single-shot/multi-shot DAQ in a background worker thread."""
        fn = self.daq_tab.txt_filename.text().strip() or "exp_run"
        shots = self.daq_tab.spin_shots.value()
        note = self.daq_tab.txt_note.text().strip()

        self.seq_controller.set_experiment_config(file_name=fn, note=note, shot_target=shots)

        def worker():
            success = self.seq_controller.arm_and_start()
            if not success:
                if self.stage_driver.is_moving():
                    self.log("[Warning] Arming aborted: Interlock triggered (Stage is currently in motion).")

        threading.Thread(target=worker, daemon=True).start()

    def on_seq_state_changed(self, state: SystemState):
        self.daq_tab.update_state_display(state)
        if state == SystemState.IDLE:
            self.daq_tab.update_metrics_display(
                self.data_manager.last_analysis_results,
                getattr(self.data_manager, "last_saved_path", "data_file")
            )

    def log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        record = f"[{timestamp}] {message}"
        self.session_log_records.append(record)
        self.txt_log.append(record)

    def closeEvent(self, event):
        """Auto-save parameters & logbook on application shutdown."""
        self.log("Application closing: saving parameters & logbook...")
        self.poll_timer.stop()
        self.save_all_configs()
        self.save_local_logbook()
        self.stage_driver.disconnect()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

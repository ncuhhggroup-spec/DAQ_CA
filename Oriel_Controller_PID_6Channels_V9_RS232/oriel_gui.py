#!/usr/bin/env python3
"""
Oriel 6-Channel Stage Controller - Modern GUI Application
Organized into Tabs:
  1. 🎮 Motion Control (Clean, compact 6-channel dashboard)
  2. ⚙ Calibration & Settings (Stage types, scale factors, units, renaming)
  3. 📝 Activity Log (Detailed communication logs and diagnostics)

Persistent Header:
  - Serial Port & Baud rate selection, Connect / Disconnect
  - Global Emergency Stop (E-STOP)
"""

import sys
import os
import time
import json
import struct
import threading
from typing import Optional, Dict, Any, List

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("Error: pyserial is required. Install via 'pip install pyserial'")
    sys.exit(1)

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QLabel, QPushButton, QComboBox,
    QDoubleSpinBox, QSpinBox, QLineEdit, QTextEdit, QTabWidget,
    QStatusBar, QFrame, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor, QPalette, QIcon

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stage_config.json")
COMMAND_LENGTH = 15
RESPONSE_LENGTH = 8

# Default Calibration Constants
CALIBRATION_LINEAR_UM_PER_COUNT = 0.025            # 0.025 um / count
CALIBRATION_ROTATOR_DEG_PER_COUNT = 5.15611e-5     # 5.15611 * 10^-5 deg / count

DEFAULT_CHANNEL_CONFIGS = [
    {
        "channel": 1,
        "name": "Ch 1: Linear X",
        "stage_type": "Linear (0.025 µm/cnt)",
        "unit": "µm",
        "factor": CALIBRATION_LINEAR_UM_PER_COUNT
    },
    {
        "channel": 2,
        "name": "Ch 2: Linear Y",
        "stage_type": "Linear (0.025 µm/cnt)",
        "unit": "µm",
        "factor": CALIBRATION_LINEAR_UM_PER_COUNT
    },
    {
        "channel": 3,
        "name": "Ch 3: Linear Z",
        "stage_type": "Linear (0.025 µm/cnt)",
        "unit": "µm",
        "factor": CALIBRATION_LINEAR_UM_PER_COUNT
    },
    {
        "channel": 4,
        "name": "Ch 4: Rotator θ",
        "stage_type": "Rotator (5.15611e-5 °/cnt)",
        "unit": "°",
        "factor": CALIBRATION_ROTATOR_DEG_PER_COUNT
    },
    {
        "channel": 5,
        "name": "Ch 5: Rotator φ",
        "stage_type": "Rotator (5.15611e-5 °/cnt)",
        "unit": "°",
        "factor": CALIBRATION_ROTATOR_DEG_PER_COUNT
    },
    {
        "channel": 6,
        "name": "Ch 6: Auxiliary",
        "stage_type": "Linear (0.025 µm/cnt)",
        "unit": "µm",
        "factor": CALIBRATION_LINEAR_UM_PER_COUNT
    }
]


class StageControllerBackend:
    """Thread-safe backend for Oriel 6-Channel Stage RS232 Controller."""
    def __init__(self):
        self.ser: Optional[serial.Serial] = None
        self.lock = threading.Lock()
        self.active_channel = 1
        self.last_status: Dict[int, Dict[str, Any]] = {}
        for ch in range(1, 7):
            self.last_status[ch] = {"position": 0, "running": False}

    def is_connected(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def connect(self, port: str, baudrate: int = 19200, timeout: float = 0.3) -> bool:
        with self.lock:
            try:
                if self.ser and self.ser.is_open:
                    self.ser.close()
                self.ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
                time.sleep(0.3)
                return True
            except Exception as e:
                self.ser = None
                raise e

    def disconnect(self):
        with self.lock:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                except Exception:
                    pass
            self.ser = None

    def _send_command(self, cmd_bytes: bytes):
        if not self.is_connected():
            raise RuntimeError("Serial port not connected")
        if len(cmd_bytes) < COMMAND_LENGTH:
            cmd_bytes = cmd_bytes + bytes([0] * (COMMAND_LENGTH - len(cmd_bytes)))
        elif len(cmd_bytes) > COMMAND_LENGTH:
            cmd_bytes = cmd_bytes[:COMMAND_LENGTH]
        self.ser.reset_input_buffer()
        self.ser.write(cmd_bytes)
        self.ser.flush()

    def select_channel(self, channel: int):
        with self.lock:
            if not (1 <= channel <= 6):
                raise ValueError("Channel must be 1-6")
            cmd = bytes([0xFF, 0x00, 0x04, channel])
            self._send_command(cmd)
            self.active_channel = channel

    def get_status(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            if not self.is_connected():
                return None
            cmd = bytes([0xFF, 0x00, 0x01])
            self._send_command(cmd)
            resp = self.ser.read(RESPONSE_LENGTH)
            if len(resp) < RESPONSE_LENGTH:
                return None
            if resp[0] != 0xFF:
                return None
            channel = resp[1]
            running = bool(resp[2])
            sign = 1 if resp[3] == 1 else -1
            magnitude = struct.unpack(">I", resp[4:8])[0]
            position = sign * magnitude
            
            stat = {
                "channel": channel,
                "running": running,
                "position": position,
                "raw": resp.hex(' ')
            }
            if 1 <= channel <= 6:
                self.last_status[channel] = {"position": position, "running": running}
            return stat

    def move_to(self, target_steps: int):
        with self.lock:
            sign_byte = 1 if target_steps >= 0 else 0
            mag = abs(target_steps)
            mag_bytes = struct.unpack("4B", struct.pack(">I", mag))
            cmd = bytes([
                0xFF, 0x00, 0x02,
                mag_bytes[0], mag_bytes[1], mag_bytes[2], mag_bytes[3],
                sign_byte
            ])
            self._send_command(cmd)

    def set_position(self, new_position_steps: int):
        with self.lock:
            sign_byte = 1 if new_position_steps >= 0 else 0
            mag = abs(new_position_steps)
            mag_bytes = struct.unpack("4B", struct.pack(">I", mag))
            cmd = bytes([
                0xFF, 0x00, 0x05,
                mag_bytes[0], mag_bytes[1], mag_bytes[2], mag_bytes[3],
                sign_byte
            ])
            self._send_command(cmd)

    def estop(self):
        with self.lock:
            if self.is_connected():
                cmd = bytes([0xFF, 0x00, 0x06])
                self._send_command(cmd)


class CompactChannelCard(QGroupBox):
    """Clean, compact motion control card for an individual channel."""
    request_select = pyqtSignal(int)
    request_move_abs = pyqtSignal(int, int)  # channel, target_counts
    request_move_rel = pyqtSignal(int, int)  # channel, delta_counts
    request_zero = pyqtSignal(int)
    request_set_pos = pyqtSignal(int, int)

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

        # 2. Position Display Box (Large Calibrated Unit + Subtitle Counts)
        pos_frame = QFrame()
        pos_frame.setStyleSheet("background: #181a1f; border: 1px solid #333842; border-radius: 6px; padding: 4px;")
        pos_layout = QVBoxLayout(pos_frame)
        pos_layout.setContentsMargins(4, 4, 4, 4)
        pos_layout.setSpacing(1)

        self.lbl_pos_physical = QLabel("0.0000 µm")
        self.lbl_pos_physical.setFont(QFont("Consolas", 15, QFont.Bold))
        self.lbl_pos_physical.setStyleSheet("color: #61afef;")
        self.lbl_pos_physical.setAlignment(Qt.AlignCenter)
        pos_layout.addWidget(self.lbl_pos_physical)

        self.lbl_pos_counts = QLabel("0 counts")
        self.lbl_pos_counts.setFont(QFont("Consolas", 9))
        self.lbl_pos_counts.setStyleSheet("color: #7f848e;")
        self.lbl_pos_counts.setAlignment(Qt.AlignCenter)
        pos_layout.addWidget(self.lbl_pos_counts)

        layout.addWidget(pos_frame)

        # 3. Target Position Move (Absolute Move)
        abs_row = QHBoxLayout()
        abs_row.setSpacing(6)
        self.spin_target = QDoubleSpinBox()
        self.spin_target.setDecimals(4)
        self.spin_target.setRange(-999999.0, 999999.0)
        self.spin_target.setValue(0.0)
        self.spin_target.setSuffix(f" {self.get_unit()}")
        self.spin_target.setFixedHeight(28)

        self.btn_move_abs = QPushButton("Move To")
        self.btn_move_abs.setFixedHeight(28)
        self.btn_move_abs.setStyleSheet("""
            QPushButton {
                background-color: #2bb673;
                color: white;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #34d084; }
        """)
        self.btn_move_abs.clicked.connect(self.on_click_move_abs)

        abs_row.addWidget(self.spin_target, 3)
        abs_row.addWidget(self.btn_move_abs, 2)
        layout.addLayout(abs_row)

        # 4. Relative Move Row (Step input + Move - / Move +)
        rel_row = QHBoxLayout()
        rel_row.setSpacing(4)

        self.spin_step = QDoubleSpinBox()
        self.spin_step.setDecimals(4)
        self.spin_step.setRange(0.0001, 999999.0)
        self.spin_step.setValue(10.0 if "Linear" in self.config.get("stage_type", "") else 1.0)
        self.spin_step.setSuffix(f" {self.get_unit()}")
        self.spin_step.setFixedHeight(28)
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
            "Changes are immediately applied to the motion controls."
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
                "unit": txt_unit
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
                "unit": row["unit"].text().strip()
            })
        return cfg_list


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.backend = StageControllerBackend()
        self.channel_cards: Dict[int, CompactChannelCard] = {}
        self.configs = self.load_configs()
        self.active_channel = 1

        self.init_ui()
        self.init_polling_timer()
        self.refresh_com_ports()

    def load_configs(self) -> list:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Failed to load {CONFIG_FILE}: {e}")
        return DEFAULT_CHANNEL_CONFIGS

    def save_configs(self):
        cfg_list = self.settings_tab.get_all_configs()
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg_list, f, indent=2, ensure_ascii=False)
            self.log("Configuration saved successfully to stage_config.json.")
            QMessageBox.information(self, "Saved", "Channel configurations saved successfully!")
        except Exception as e:
            self.log(f"Error saving config: {e}")
            QMessageBox.critical(self, "Error", f"Could not save settings:\n{e}")

    def init_ui(self):
        self.setWindowTitle("Oriel 6-Channel Stage Controller - Multi-Channel PID GUI")
        self.resize(1100, 680)
        self.setMinimumSize(950, 580)
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e2227;
            }
            QWidget {
                color: #abb2bf;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 12px;
            }
            QPushButton {
                border-radius: 4px;
                padding: 4px 10px;
                font-weight: 500;
            }
            QPushButton:hover {
                filter: brightness(1.15);
            }
            QPushButton:pressed {
                filter: brightness(0.9);
            }
            QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
                background-color: #282c34;
                border: 1px solid #3e4451;
                border-radius: 4px;
                padding: 3px 6px;
                color: #abb2bf;
            }
            QTabWidget::pane {
                border: 1px solid #3e4451;
                background-color: #1e2227;
                border-radius: 6px;
            }
            QTabBar::tab {
                background: #181a1f;
                border: 1px solid #3e4451;
                padding: 8px 20px;
                margin-right: 3px;
                font-weight: bold;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected {
                background: #282c34;
                border-bottom-color: #282c34;
                color: #61afef;
            }
            QTextEdit {
                background-color: #181a1f;
                border: 1px solid #333842;
                border-radius: 4px;
                font-family: 'Consolas', monospace;
                font-size: 11px;
                color: #98c379;
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
        self.combo_baud.setCurrentText("19200")
        top_layout.addWidget(self.combo_baud)

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setStyleSheet("background-color: #98c379; color: #1e2227; font-weight: bold; padding: 6px 16px;")
        self.btn_connect.clicked.connect(self.toggle_connection)
        top_layout.addWidget(self.btn_connect)

        self.lbl_conn_status = QLabel("Disconnected")
        self.lbl_conn_status.setStyleSheet("color: #e06c75; font-weight: bold; margin-left: 6px;")
        top_layout.addWidget(self.lbl_conn_status)

        top_layout.addStretch()

        # Save config button
        self.btn_save_cfg = QPushButton("💾 Save Settings")
        self.btn_save_cfg.setStyleSheet("background-color: #4facfe; color: white; padding: 6px 14px;")
        self.btn_save_cfg.clicked.connect(self.save_configs)
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
            QPushButton:hover {
                background-color: #ff5555;
            }
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
            self.channel_cards[ch_num] = card

            row = i // 3
            col = i % 3
            channels_grid.addWidget(card, row, col)

        motion_layout.addWidget(grid_container)
        self.tabs.addTab(tab_motion, "🎮 Motion Control")

        # --- TAB 2: CALIBRATION & SETTINGS ---
        self.settings_tab = CalibrationSettingsTab(self.configs, self)
        self.settings_tab.config_changed.connect(self.on_settings_updated)
        self.tabs.addTab(self.settings_tab, "⚙ Calibration & Settings")

        # --- TAB 3: ACTIVITY LOG ---
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

        self.log("Oriel 6-Channel Controller UI Initialized.")
        self.log("Presets loaded: Linear (0.025 µm/cnt) | Rotator (5.15611e-5 °/cnt)")

    def on_settings_updated(self):
        new_configs = self.settings_tab.get_all_configs()
        self.configs = new_configs
        for cfg in new_configs:
            ch_num = cfg.get("channel")
            if ch_num in self.channel_cards:
                self.channel_cards[ch_num].update_config(cfg)

    def init_polling_timer(self):
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(200)
        self.poll_timer.timeout.connect(self.poll_controller_status)

    def refresh_com_ports(self):
        current = self.combo_port.currentText()
        self.combo_port.clear()
        ports = serial.tools.list_ports.comports()
        preferred_idx = 0
        for idx, p in enumerate(ports):
            self.combo_port.addItem(p.device)
            if p.device == "COM7" or p.device == current:
                preferred_idx = idx
        if self.combo_port.count() > 0:
            self.combo_port.setCurrentIndex(preferred_idx)
        else:
            self.combo_port.addItem("COM7")

    def toggle_connection(self):
        if self.backend.is_connected():
            self.backend.disconnect()
            self.btn_connect.setText("Connect")
            self.btn_connect.setStyleSheet("background-color: #98c379; color: #1e2227; font-weight: bold;")
            self.lbl_conn_status.setText("Disconnected")
            self.lbl_conn_status.setStyleSheet("color: #e06c75; font-weight: bold; margin-left: 6px;")
            self.poll_timer.stop()
            self.log("Disconnected from serial port.")
        else:
            port = self.combo_port.currentText()
            try:
                baud = int(self.combo_baud.currentText())
            except ValueError:
                baud = 19200
            
            try:
                self.log(f"Connecting to {port} @ {baud} baud...")
                self.backend.connect(port=port, baudrate=baud)
                self.btn_connect.setText("Disconnect")
                self.btn_connect.setStyleSheet("background-color: #e06c75; color: white; font-weight: bold;")
                self.lbl_conn_status.setText(f"Connected ({port})")
                self.lbl_conn_status.setStyleSheet("color: #98c379; font-weight: bold; margin-left: 6px;")
                self.poll_timer.start()
                self.log(f"Connected to {port} successfully.")
                
                self.handle_select_channel(self.active_channel)
            except Exception as e:
                self.log(f"Connection Failed: {e}")
                QMessageBox.critical(self, "Connection Error", f"Could not open {port}:\n{e}")

    def poll_controller_status(self):
        if not self.backend.is_connected():
            return
        try:
            status = self.backend.get_status()
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
        if self.backend.is_connected():
            try:
                self.backend.select_channel(ch)
                self.log(f"Selected Channel {ch}")
            except Exception as e:
                self.log(f"Failed to switch channel to {ch}: {e}")

    def handle_move_abs(self, ch: int, target_counts: int):
        if not self.backend.is_connected():
            QMessageBox.warning(self, "Not Connected", "Please connect to serial port first.")
            return
        try:
            if self.active_channel != ch:
                self.handle_select_channel(ch)
                time.sleep(0.05)
            self.backend.move_to(target_counts)
            card = self.channel_cards.get(ch)
            phys = card.counts_to_physical(target_counts) if card else 0
            unit = card.get_unit() if card else ""
            self.log(f"Ch {ch} Moving to Target: {phys:.4f} {unit} ({target_counts} counts)")
        except Exception as e:
            self.log(f"Error moving Ch {ch}: {e}")

    def handle_move_rel(self, ch: int, delta_counts: int):
        if not self.backend.is_connected():
            QMessageBox.warning(self, "Not Connected", "Please connect to serial port first.")
            return
        try:
            if self.active_channel != ch:
                self.handle_select_channel(ch)
                time.sleep(0.05)
            current_counts = self.channel_cards[ch].current_counts
            target_counts = current_counts + delta_counts
            self.backend.move_to(target_counts)
            card = self.channel_cards.get(ch)
            delta_phys = card.counts_to_physical(delta_counts) if card else 0
            unit = card.get_unit() if card else ""
            self.log(f"Ch {ch} Relative Move: {delta_phys:+.4f} {unit} (Target: {target_counts} cnt)")
        except Exception as e:
            self.log(f"Error relative moving Ch {ch}: {e}")

    def handle_zero(self, ch: int):
        if not self.backend.is_connected():
            QMessageBox.warning(self, "Not Connected", "Please connect to serial port first.")
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
                self.backend.set_position(0)
                self.log(f"Ch {ch} Position Zeroed (Origin set).")
            except Exception as e:
                self.log(f"Error zeroing Ch {ch}: {e}")

    def handle_set_position(self, ch: int, new_counts: int):
        if not self.backend.is_connected():
            QMessageBox.warning(self, "Not Connected", "Please connect to serial port first.")
            return
        try:
            if self.active_channel != ch:
                self.handle_select_channel(ch)
                time.sleep(0.05)
            self.backend.set_position(new_counts)
            self.log(f"Ch {ch} Position set to {new_counts} counts.")
        except Exception as e:
            self.log(f"Error setting position Ch {ch}: {e}")

    def handle_estop(self):
        try:
            self.backend.estop()
            self.log("!!! EMERGENCY STOP SENT (ALL MOTION HALTED) !!!")
        except Exception as e:
            self.log(f"Error sending E-STOP: {e}")

    def log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.txt_log.append(f"[{timestamp}] {message}")

    def closeEvent(self, event):
        self.poll_timer.stop()
        self.backend.disconnect()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

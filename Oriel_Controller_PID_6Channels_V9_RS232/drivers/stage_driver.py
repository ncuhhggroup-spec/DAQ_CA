import time
import struct
import threading
from typing import Optional, Dict, Any
from drivers.base_driver import BaseStageDriver

try:
    import serial
except ImportError:
    serial = None

COMMAND_LENGTH = 15
RESPONSE_LENGTH = 8


class OrielStageDriver(BaseStageDriver):
    """Production driver for Oriel 6-Channel Stage RS232 Controller."""
    
    def __init__(self):
        self.ser: Optional[Any] = None
        self.lock = threading.Lock()
        self.active_channel = 1
        self.last_status: Dict[int, Dict[str, Any]] = {
            ch: {"position": 0, "running": False} for ch in range(1, 7)
        }

    def is_connected(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def connect(self, port: str, baudrate: int = 19200, timeout: float = 0.3) -> bool:
        if serial is None:
            raise RuntimeError("pyserial is not installed.")
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

    def disconnect(self) -> None:
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

    def select_channel(self, channel: int) -> None:
        with self.lock:
            if not (1 <= channel <= 6):
                raise ValueError("Channel must be 1-6")
            cmd = bytes([0xFF, 0x00, 0x04, channel])
            self._send_command(cmd)
            self.active_channel = channel

    def get_status(self, channel: Optional[int] = None) -> Optional[Dict[str, Any]]:
        with self.lock:
            if not self.is_connected():
                return None
            ch_byte = channel if (channel is not None and 1 <= channel <= 6) else 0x00
            cmd = bytes([0xFF, 0x00, 0x01, ch_byte])
            self._send_command(cmd)
            resp = self.ser.read(RESPONSE_LENGTH)
            if len(resp) < RESPONSE_LENGTH or resp[0] != 0xFF:
                return None
            rep_channel = resp[1]
            running = bool(resp[2])
            sign = 1 if resp[3] == 1 else -1
            magnitude = struct.unpack(">I", resp[4:8])[0]
            position = sign * magnitude
            
            stat = {
                "channel": rep_channel,
                "running": running,
                "position": position,
                "raw": resp.hex(' ')
            }
            if 1 <= rep_channel <= 6:
                self.last_status[rep_channel] = {"position": position, "running": running}
            return stat

    def get_all_positions(self) -> Dict[int, Dict[str, Any]]:
        """Queries the position of all 6 channels from the controller."""
        results = {}
        for ch in range(1, 7):
            stat = self.get_status(channel=ch)
            if stat:
                results[ch] = stat
            else:
                # Fallback for firmware versions that only report active channel: switch ch temporarily
                try:
                    self.select_channel(ch)
                    time.sleep(0.02)
                    st = self.get_status()
                    if st:
                        results[ch] = st
                except Exception:
                    pass
        # Restore active channel
        try:
            if self.active_channel:
                self.select_channel(self.active_channel)
        except Exception:
            pass
        return results

    def get_position(self, channel: Optional[int] = None) -> int:
        ch = channel if channel is not None else self.active_channel
        return self.last_status.get(ch, {}).get("position", 0)

    def is_moving(self, channel: Optional[int] = None) -> bool:
        if channel is not None:
            return self.last_status.get(channel, {}).get("running", False)
        # If no channel specified, check if ANY channel is moving
        return any(st.get("running", False) for st in self.last_status.values())

    def move_to(self, target_steps: int) -> None:
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

    def set_position(self, new_position_steps: int) -> None:
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

    def estop(self) -> None:
        with self.lock:
            if self.is_connected():
                cmd = bytes([0xFF, 0x00, 0x06])
                self._send_command(cmd)


class MockStageDriver(BaseStageDriver):
    """Mock stage driver for testing without physical hardware."""
    
    def __init__(self):
        self._connected = True
        self.active_channel = 1
        self.positions: Dict[int, int] = {ch: 0 for ch in range(1, 7)}
        self.targets: Dict[int, int] = {ch: 0 for ch in range(1, 7)}
        self._is_moving: Dict[int, bool] = {ch: False for ch in range(1, 7)}

    def connect(self, port: str, baudrate: int = 19200, timeout: float = 0.3) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def select_channel(self, channel: int) -> None:
        self.active_channel = channel

    def get_status(self, channel: Optional[int] = None) -> Optional[Dict[str, Any]]:
        ch = channel if channel is not None else self.active_channel
        if self._is_moving[ch]:
            diff = self.targets[ch] - self.positions[ch]
            if abs(diff) <= 100:
                self.positions[ch] = self.targets[ch]
                self._is_moving[ch] = False
            else:
                self.positions[ch] += 100 if diff > 0 else -100
        return {
            "channel": ch,
            "running": self._is_moving[ch],
            "position": self.positions[ch],
            "raw": "FF MOCK"
        }

    def get_all_positions(self) -> Dict[int, Dict[str, Any]]:
        return {
            ch: {
                "channel": ch,
                "running": self._is_moving[ch],
                "position": self.positions[ch],
                "raw": "FF MOCK"
            } for ch in range(1, 7)
        }

    def get_position(self, channel: Optional[int] = None) -> int:
        ch = channel if channel is not None else self.active_channel
        return self.positions.get(ch, 0)

    def is_moving(self, channel: Optional[int] = None) -> bool:
        if channel is not None:
            return self._is_moving.get(channel, False)
        return any(self._is_moving.values())

    def set_moving_state(self, channel: int, moving: bool):
        """Helper to force moving state during test fixtures."""
        self._is_moving[channel] = moving

    def move_to(self, target_steps: int) -> None:
        ch = self.active_channel
        self.targets[ch] = target_steps
        if self.positions[ch] != target_steps:
            self._is_moving[ch] = True

    def set_position(self, new_position_steps: int) -> None:
        ch = self.active_channel
        self.positions[ch] = new_position_steps
        self.targets[ch] = new_position_steps
        self._is_moving[ch] = False

    def estop(self) -> None:
        for ch in range(1, 7):
            self._is_moving[ch] = False
            self.targets[ch] = self.positions[ch]

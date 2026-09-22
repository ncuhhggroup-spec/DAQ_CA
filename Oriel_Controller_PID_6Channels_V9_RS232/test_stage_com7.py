"""
Oriel 6-Channel Stage Controller - Python Test Script for COM7
Baud Rate: 19200
"""

import time
import struct
import sys
try:
    import serial
except ImportError:
    print("pyserial is required. Install via: pip install pyserial")
    sys.exit(1)

COMMAND_LENGTH = 15
RESPONSE_LENGTH = 8

class OrielStageController:
    def __init__(self, port='COM7', baudrate=19200, timeout=1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None

    def connect(self):
        print(f"Connecting to {self.port} at {self.baudrate} baud...")
        self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        time.sleep(0.5)  # Wait for port stabilization
        print("Connected successfully.")

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("Serial connection closed.")

    def _send_command(self, cmd_bytes):
        """Pad command to 15 bytes and send."""
        if len(cmd_bytes) < COMMAND_LENGTH:
            cmd_bytes = cmd_bytes + bytes([0] * (COMMAND_LENGTH - len(cmd_bytes)))
        elif len(cmd_bytes) > COMMAND_LENGTH:
            cmd_bytes = cmd_bytes[:COMMAND_LENGTH]
        
        # Flush any stale input
        self.ser.reset_input_buffer()
        self.ser.write(cmd_bytes)
        self.ser.flush()

    def select_channel(self, channel: int):
        """Opcode 0x04: Select Motor Channel (1-6)."""
        if not (1 <= channel <= 6):
            raise ValueError("Channel must be between 1 and 6.")
        
        # [0xFF, 0x00 (Broadcast), 0x04 (Select Channel), channel_num, 0, ...]
        cmd = bytes([0xFF, 0x00, 0x04, channel])
        self._send_command(cmd)
        print(f"Sent: Select Channel {channel}")
        time.sleep(0.1)

    def get_status(self):
        """
        Opcode 0x01: Request Status.
        Returns: dict(channel, is_running, position)
        """
        # [0xFF, 0x00, 0x01, 0, ...]
        cmd = bytes([0xFF, 0x00, 0x01])
        self._send_command(cmd)
        
        resp = self.ser.read(RESPONSE_LENGTH)
        if len(resp) < RESPONSE_LENGTH:
            print(f"Warning: Expected {RESPONSE_LENGTH} bytes, got {len(resp)} bytes: {resp.hex(' ')}")
            return None
        
        # Parse Response:
        # byte 0: Header (0xFF)
        # byte 1: Channel number
        # byte 2: Running status (0 = idle, 1 = running)
        # byte 3: Position sign (1 = positive, 0 = negative)
        # byte 4..7: 32-bit unsigned magnitude (Big-endian)
        header = resp[0]
        channel = resp[1]
        running = bool(resp[2])
        sign = 1 if resp[3] == 1 else -1
        magnitude = struct.unpack(">I", resp[4:8])[0]
        position = sign * magnitude

        status = {
            "channel": channel,
            "running": running,
            "position": position,
            "raw_hex": resp.hex(' ')
        }
        return status

    def move_to(self, target_position: int):
        """
        Opcode 0x02: Move to Target Position (Steps).
        """
        sign_byte = 1 if target_position >= 0 else 0
        mag = abs(target_position)
        mag_bytes = struct.unpack("4B", struct.pack(">I", mag))
        
        # [0xFF, 0x00, 0x02, U8_a, U8_b, U8_c, U8_d, Sign]
        cmd = bytes([
            0xFF, 0x00, 0x02,
            mag_bytes[0], mag_bytes[1], mag_bytes[2], mag_bytes[3],
            sign_byte
        ])
        self._send_command(cmd)
        print(f"Sent: Move to Position {target_position}")

    def set_position(self, new_position: int):
        """
        Opcode 0x05: Set/Zero current position value.
        """
        sign_byte = 1 if new_position >= 0 else 0
        mag = abs(new_position)
        mag_bytes = struct.unpack("4B", struct.pack(">I", mag))
        
        # [0xFF, 0x00, 0x05, U8_a, U8_b, U8_c, U8_d, Sign]
        cmd = bytes([
            0xFF, 0x00, 0x05,
            mag_bytes[0], mag_bytes[1], mag_bytes[2], mag_bytes[3],
            sign_byte
        ])
        self._send_command(cmd)
        print(f"Sent: Set Position to {new_position}")

    def manual_jog(self, pwm=80, direction=1, duration_ms=200):
        """
        Opcode 0x00: Manual Move (Jog).
        pwm: 0-255
        direction: 1 (positive/forward) or 0 (negative/reverse)
        duration_ms: pulse length in milliseconds (0 to not auto-stop)
        """
        cmd = bytes([0xFF, 0x00, 0x00, pwm & 0xFF, 1 if direction else 0, duration_ms & 0xFF])
        self._send_command(cmd)
        print(f"Sent: Manual Jog (PWM={pwm}, Dir={direction}, Duration={duration_ms}ms)")

    def estop(self):
        """Opcode 0x06: Emergency Stop."""
        cmd = bytes([0xFF, 0x00, 0x06])
        self._send_command(cmd)
        print("Sent: Emergency Stop (E-STOP)")

    def wait_until_idle(self, timeout=30.0, poll_interval=0.2):
        """Polls status until motion is completed."""
        start = time.time()
        print("Waiting for motion to complete...")
        while time.time() - start < timeout:
            status = self.get_status()
            if status:
                print(f"Pos: {status['position']}, Moving: {status['running']}")
                if not status['running']:
                    print("Target reached / Motion stopped.")
                    return True
            time.sleep(poll_interval)
        print("Motion timed out!")
        return False


def main():
    stage = OrielStageController(port='COM7', baudrate=19200)
    
    try:
        stage.connect()
        
        print("\n--- 1. Switching to Channel 3 ---")
        stage.select_channel(3)
        time.sleep(0.2)
        
        print("\n--- 2. Checking Initial Status on Channel 3 ---")
        st = stage.get_status()
        if st:
            print(f"Active Channel: {st['channel']}")
            print(f"Is Running: {st['running']}")
            print(f"Current Encoder Position: {st['position']}")
        else:
            print("Failed to get status response. Check wiring, COM port, and baud rate.")
            return

        print("\n--- 3. Testing Small Move on Channel 3 (+500 steps) ---")
        current_pos = st['position']
        target = current_pos + 500
        stage.move_to(target)
        
        # Wait for motion to finish
        stage.wait_until_idle(timeout=10.0)
        
        print("\n--- 4. Checking Final Status ---")
        final_st = stage.get_status()
        if final_st:
            print(f"Final Encoder Position: {final_st['position']}")

    except KeyboardInterrupt:
        print("\nInterrupt received! Stopping...")
        stage.estop()
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        stage.close()

if __name__ == '__main__':
    main()

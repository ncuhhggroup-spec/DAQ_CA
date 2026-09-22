"""
SRS DG645 Digital Delay Generator Driver
========================================
A Python driver for communicating with and controlling the Stanford Research Systems
DG645 Digital Delay Generator over an RS-232 serial connection (e.g., COM5).

Features:
- Configures trigger sources (Single-shot external rising/falling, internal, line, etc.)
- Sets trigger threshold voltage (TLVL)
- Configures the 4 front-panel pulse output channels (AB, CD, EF, GH)
- Links trailing edge to leading edge for accurate pulse width (default: 1 ms)
- Single-shot trigger arming / execution (*TRG)
- Robust query/command handling and error buffer querying (LERR?)
"""

import time
import logging
from typing import Dict, Optional, Tuple, Union
import serial

logger = logging.getLogger(__name__)

# Channel identifier mappings
# The DG645 uses numeric indices for internal delay channels:
# 0: T0, 1: T1, 2: A, 3: B, 4: C, 5: D, 6: E, 7: F, 8: G, 9: H
CHANNEL_MAP = {
    'T0': 0, 0: 0,
    'T1': 1, 1: 1,
    'A': 2, 2: 2,
    'B': 3, 3: 3,
    'C': 4, 4: 4,
    'D': 5, 5: 5,
    'E': 6, 6: 6,
    'F': 7, 7: 7,
    'G': 8, 8: 8,
    'H': 9, 9: 9,
}

# Output BNC mapping
# Front panel BNCs: 0: T0, 1: AB, 2: CD, 3: EF, 4: GH
OUTPUT_MAP = {
    'T0': 0, 0: 0,
    'AB': 1, 1: 1,
    'CD': 2, 2: 2,
    'EF': 3, 3: 3,
    'GH': 4, 4: 4,
}

# The 4 output pulse channel definitions: (leading_edge_channel, trailing_edge_channel)
OUTPUT_PULSE_CHANNELS = {
    1: ('A', 'B', 2, 3),   # Channel 1: AB (A leading, B trailing)
    2: ('CD', 'D', 4, 5),  # Channel 2: CD (C leading, D trailing)
    3: ('EF', 'F', 6, 7),  # Channel 3: EF (E leading, F trailing)
    4: ('GH', 'H', 8, 9),  # Channel 4: GH (G leading, H trailing)
    'AB': ('A', 'B', 2, 3),
    'CD': ('C', 'D', 4, 5),
    'EF': ('E', 'F', 6, 7),
    'GH': ('G', 'H', 8, 9),
}

# Trigger Source definitions
TRIGGER_SOURCES = {
    'internal': 0,
    'ext_rising': 1,
    'ext_falling': 2,
    'single_shot_ext_rising': 3,
    'single_shot_ext_falling': 4,
    'single_shot': 5,
    'line': 6,
}

# DG645 Error code descriptions
ERROR_CODES = {
    0: "No Error",
    10: "Illegal Value (parameter out of range)",
    11: "Illegal Mode (action illegal in current mode)",
    12: "Illegal Delay (requested delay out of range)",
    13: "Illegal Link (requested delay linkage is illegal)",
    14: "Recall Failed",
    15: "Not Allowed (instrument locked)",
    16: "Failed Self Test",
    17: "Failed Auto Calibration",
    110: "Illegal Command",
    111: "Undefined Header",
    112: "Illegal Parameter",
    113: "Missing Parameter",
    114: "Extra Parameter",
    115: "Null Parameter",
    116: "Parameter Overflow",
    117: "Bad Floating Point",
    118: "Bad Integer",
    120: "Bad Integer Range",
    122: "Invalid Hexadecimal",
    126: "Syntax Error",
    170: "Communication Error (framing/parity)",
    171: "Over Run (input buffer overflow)",
    254: "Too Many Errors",
}


class DG645Error(Exception):
    """Exception raised for DG645 instrument errors."""
    pass


class DG645:
    """Driver class for SRS DG645 Digital Delay Generator via Serial (RS-232)."""

    def __init__(
        self,
        port: str = "COM5",
        baudrate: int = 9600,
        timeout: float = 2.0,
        rtscts: bool = False,
    ):
        """
        Initialize DG645 serial communication parameters.

        :param port: Serial COM port string (e.g. 'COM5' on Windows or '/dev/ttyUSB0' on Linux)
        :param baudrate: Baud rate (default: 9600; DG645 also supports 4800, 19200, 38400, 57600, 115200)
        :param timeout: Read timeout in seconds (default: 2.0s)
        :param rtscts: Use hardware RTS/CTS flow control (default: False for broad compatibility)
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.rtscts = rtscts
        self.ser: Optional[serial.Serial] = None

    def connect(self) -> str:
        """
        Open the serial port and query the device identification (*IDN?).

        :return: Identification string from DG645
        """
        if self.ser and self.ser.is_open:
            self.ser.close()

        self.ser = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout,
            rtscts=self.rtscts,
            write_timeout=self.timeout,
        )

        # Clear buffers
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        time.sleep(0.05)

        # Query *IDN? to verify communication
        idn = self.query("*IDN?")
        if not idn:
            # Retry once in case of startup noise on serial lines
            self.ser.reset_input_buffer()
            time.sleep(0.1)
            idn = self.query("*IDN?")

        return idn

    def disconnect(self):
        """Close the serial port connection."""
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.ser = None

    def is_connected(self) -> bool:
        """Check if serial connection is open."""
        return bool(self.ser and self.ser.is_open)

    def write(self, command: str):
        """
        Send a command string to the DG645 terminated with \\r\\n.

        :param command: Command string (e.g. 'TSRC 3' or '*TRG')
        """
        if not self.is_connected():
            raise DG645Error(f"Serial port {self.port} is not connected.")
        
        cmd_bytes = f"{command.strip()}\r\n".encode("ascii")
        self.ser.write(cmd_bytes)
        self.ser.flush()

    def read_line(self) -> str:
        """
        Read a line from the DG645 serial port until \\r\\n.

        :return: Stripped response string
        """
        if not self.is_connected():
            raise DG645Error(f"Serial port {self.port} is not connected.")
        line = self.ser.readline().decode("ascii", errors="replace").strip()
        return line

    def query(self, command: str) -> str:
        """
        Send a query command to the DG645 and return its response.

        :param command: Query string (e.g. '*IDN?', 'DLAY? 2')
        :return: Response string
        """
        self.write(command)
        return self.read_line()

    # =========================================================================
    # Status & Error Handling
    # =========================================================================

    def clear_status(self):
        """Clear status registers and error queue (*CLS)."""
        self.write("*CLS")

    def get_last_error(self) -> Tuple[int, str]:
        """
        Query the last error from the DG645 error buffer (LERR?).

        :return: Tuple of (error_code: int, error_description: str)
        """
        resp = self.query("LERR?")
        try:
            code = int(resp.strip())
        except (ValueError, TypeError):
            code = -1
        desc = ERROR_CODES.get(code, f"Unknown error code {code}")
        return code, desc

    def check_errors(self):
        """
        Check if any error occurred on the instrument and raise DG645Error if so.
        """
        code, desc = self.get_last_error()
        if code != 0 and code != -1:
            raise DG645Error(f"DG645 Error {code}: {desc}")

    def reset(self):
        """Reset instrument to factory default settings (*RST)."""
        self.write("*RST")
        time.sleep(0.5)

    def get_idn(self) -> str:
        """Query instrument identification (*IDN?)."""
        return self.query("*IDN?")

    # =========================================================================
    # Trigger Configuration
    # =========================================================================

    def set_trigger_source(self, source: Union[int, str]):
        """
        Set the trigger source (TSRC command).

        Supported modes:
        - 0 or 'internal': Internal oscillator
        - 1 or 'ext_rising': External continuous rising edge
        - 2 or 'ext_falling': External continuous falling edge
        - 3 or 'single_shot_ext_rising': Single shot on external rising edge
        - 4 or 'single_shot_ext_falling': Single shot on external falling edge
        - 5 or 'single_shot': Single shot manual / software trigger
        - 6 or 'line': AC power line

        :param source: Trigger mode code (0-6) or friendly string
        """
        if isinstance(source, str):
            source_lower = source.strip().lower()
            if source_lower in TRIGGER_SOURCES:
                code = TRIGGER_SOURCES[source_lower]
            else:
                raise ValueError(
                    f"Unknown trigger source string '{source}'. "
                    f"Choose from: {list(TRIGGER_SOURCES.keys())}"
                )
        else:
            code = int(source)
            if code not in range(7):
                raise ValueError(f"Trigger source code must be 0..6, got {code}")

        self.write(f"TSRC {code}")
        self.check_errors()

    def get_trigger_source(self) -> int:
        """
        Query the current trigger source.

        :return: Integer source code (0-6)
        """
        resp = self.query("TSRC?")
        return int(resp.strip())

    def set_trigger_level(self, level_volts: float):
        """
        Set the external trigger threshold voltage in volts (TLVL).
        Valid range is -3.50 V to +3.50 V with 10 mV resolution.

        :param level_volts: Trigger threshold in volts
        """
        if not (-3.5 <= level_volts <= 3.5):
            raise ValueError(f"Trigger level must be between -3.5V and +3.5V, got {level_volts}")
        self.write(f"TLVL {level_volts:.3f}")
        self.check_errors()

    def get_trigger_level(self) -> float:
        """
        Query current external trigger threshold voltage in volts.
        """
        resp = self.query("TLVL?")
        return float(resp.strip())

    def trigger(self):
        """
        Trigger or arm the DG645 (*TRG command).

        - When configured for 'Single Shot External Trigger' (modes 3 or 4),
          this arms the DG645 to fire on the NEXT detected external trigger event.
        - When configured for 'Single Shot' (mode 5),
          this immediately fires a single delay sequence.
        """
        self.write("*TRG")

    def arm_single_shot(self):
        """Alias for trigger() when operating in Single Shot mode."""
        self.trigger()

    # =========================================================================
    # Delay & Pulse Width Configuration
    # =========================================================================

    def set_delay(
        self,
        channel: Union[str, int],
        reference: Union[str, int],
        delay_seconds: float,
    ):
        """
        Set the delay for a channel relative to another channel (DLAY command).

        Channels:
        0: T0, 1: T1, 2: A, 3: B, 4: C, 5: D, 6: E, 7: F, 8: G, 9: H

        :param channel: Channel to configure (e.g. 'A' or 2)
        :param reference: Reference channel (e.g. 'T0' or 0)
        :param delay_seconds: Delay in seconds (e.g. 10e-6 or 0.001)
        """
        c = CHANNEL_MAP[channel] if isinstance(channel, str) else channel
        d = CHANNEL_MAP[reference] if isinstance(reference, str) else reference
        self.write(f"DLAY {c},{d},{delay_seconds:.12e}")
        self.check_errors()

    def get_delay(self, channel: Union[str, int]) -> Tuple[int, float]:
        """
        Query delay setting for a specific channel (DLAY? c).

        :param channel: Channel identifier ('A'..'H', 0..9)
        :return: Tuple of (reference_channel_index: int, delay_seconds: float)
        """
        c = CHANNEL_MAP[channel] if isinstance(channel, str) else channel
        resp = self.query(f"DLAY? {c}")
        # Response format is typically: 'd,+0.000010000000'
        parts = resp.split(",")
        if len(parts) == 2:
            ref_chan = int(parts[0])
            dlay_val = float(parts[1])
            return ref_chan, dlay_val
        raise DG645Error(f"Unexpected response to DLAY? {c}: '{resp}'")

    def set_channel_pulse(
        self,
        channel_index_or_name: Union[int, str],
        delay_seconds: float,
        pulse_width_seconds: float = 0.001,
    ):
        """
        Configure one of the 4 front-panel pulse output channels (AB, CD, EF, GH).
        
        The leading edge is set relative to T0 with `delay_seconds`.
        The trailing edge is linked directly to the leading edge with `pulse_width_seconds` (default: 1 ms).

        Channels:
        1 or 'AB': Output AB (Edge A starts at delay, Edge B ends at A + width)
        2 or 'CD': Output CD (Edge C starts at delay, Edge D ends at C + width)
        3 or 'EF': Output EF (Edge E starts at delay, Edge F ends at E + width)
        4 or 'GH': Output GH (Edge G starts at delay, Edge H ends at G + width)

        :param channel_index_or_name: 1..4 or 'AB', 'CD', 'EF', 'GH'
        :param delay_seconds: Pulse start time relative to T0 in seconds
        :param pulse_width_seconds: Pulse width in seconds (default: 1 ms = 0.001 s)
        """
        key = channel_index_or_name
        if key not in OUTPUT_PULSE_CHANNELS:
            raise ValueError(
                f"Invalid channel '{key}'. Valid options are 1, 2, 3, 4 or 'AB', 'CD', 'EF', 'GH'"
            )

        lead_name, trail_name, lead_idx, trail_idx = OUTPUT_PULSE_CHANNELS[key]

        # 1. Set leading edge delay relative to T0 (channel 0)
        self.set_delay(channel=lead_idx, reference=0, delay_seconds=delay_seconds)

        # 2. Set trailing edge delay relative to leading edge (defines the pulse width)
        self.set_delay(channel=trail_idx, reference=lead_idx, delay_seconds=pulse_width_seconds)

    def set_all_4_channels(
        self,
        delays: Dict[Union[int, str], float],
        pulse_width_seconds: float = 0.001,
    ):
        """
        Configure all 4 output pulse channels (AB, CD, EF, GH) in one call.

        :param delays: Dict mapping channel (1, 2, 3, 4 or 'AB', 'CD', 'EF', 'GH') to delay in seconds.
        :param pulse_width_seconds: Pulse width applied to all channels (default: 1 ms = 0.001 s).
        """
        for ch in [1, 2, 3, 4]:
            if ch in delays:
                val = delays[ch]
            elif list(OUTPUT_PULSE_CHANNELS.keys())[ch - 1] in delays:
                val = delays[list(OUTPUT_PULSE_CHANNELS.keys())[ch - 1]]
            else:
                continue
            self.set_channel_pulse(ch, val, pulse_width_seconds)

    def get_channel_settings(self, channel_index_or_name: Union[int, str]) -> Dict[str, float]:
        """
        Read the start delay and pulse width of an output channel (AB, CD, EF, GH).

        :return: Dict with {'delay': float, 'width': float}
        """
        key = channel_index_or_name
        if key not in OUTPUT_PULSE_CHANNELS:
            raise ValueError(f"Invalid channel '{key}'.")
        lead_name, trail_name, lead_idx, trail_idx = OUTPUT_PULSE_CHANNELS[key]

        _, lead_delay = self.get_delay(lead_idx)
        ref_trail, trail_offset = self.get_delay(trail_idx)

        # If trailing edge is linked to leading edge, trail_offset is directly the width
        if ref_trail == lead_idx:
            width = trail_offset
        else:
            # Trailing edge referenced to T0 or another channel
            width = trail_offset - lead_delay

        return {
            'channel': lead_name + trail_name if len(lead_name) == 1 else lead_name,
            'delay': lead_delay,
            'width': width,
        }

    def get_all_delays(self) -> Dict[str, Dict[str, float]]:
        """
        Retrieve settings for all 4 output pulse channels.

        :return: Dict mapping 'AB', 'CD', 'EF', 'GH' to delay and width
        """
        result = {}
        for name in ['AB', 'CD', 'EF', 'GH']:
            result[name] = self.get_channel_settings(name)
        return result

    # =========================================================================
    # Output Levels (TTL / Custom)
    # =========================================================================

    def set_output_amplitude(self, output: Union[str, int], volts: float):
        """
        Set output BNC amplitude in volts (LAMP b, v).
        Outputs: 0: T0, 1: AB, 2: CD, 3: EF, 4: GH
        """
        b = OUTPUT_MAP[output] if isinstance(output, str) else output
        self.write(f"LAMP {b},{volts:.3f}")
        self.check_errors()

    def set_output_offset(self, output: Union[str, int], volts: float):
        """
        Set output BNC offset in volts (LOFF b, v).
        Outputs: 0: T0, 1: AB, 2: CD, 3: EF, 4: GH
        """
        b = OUTPUT_MAP[output] if isinstance(output, str) else output
        self.write(f"LOFF {b},{volts:.3f}")
        self.check_errors()

    def set_ttl_output(self, output: Union[str, int]):
        """
        Configure an output to standard TTL level: 0 to 4.0 V (Amplitude 4.0 V, Offset 0.0 V).
        """
        self.set_output_amplitude(output, 4.0)
        self.set_output_offset(output, 0.0)

    # =========================================================================
    # Context Manager
    # =========================================================================

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

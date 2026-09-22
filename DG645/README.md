# SRS DG645 Python Driver & Controller

A complete, easy-to-use Python driver and graphical interface for controlling the **Stanford Research Systems (SRS) DG645 Digital Delay Generator** over RS-232 serial (`COM5`).

---

## Features

- **RS-232 Serial Communication**: Pre-configured for `COM5`, 9600 baud, 8 data bits, 1 stop bit, no parity (`8-N-1`).
- **Single-Shot External Trigger Mode**: Configures trigger source to single-shot triggered by external rising edge (`TSRC 3`) or falling edge (`TSRC 4`).
- **External Trigger Threshold**: Easily adjust the trigger comparator voltage level (`TLVL`, e.g. 1.0 V).
- **4 Output Channels with 1 ms Pulse Width**:
  - Sets start delay relative to $T_0$ for each channel (`AB`, `CD`, `EF`, `GH`).
  - Automatically links the trailing edge to the leading edge with a `+1.0 ms` delay (`DLAY 3,2,0.001`, etc.), ensuring pulse width is strictly preserved at 1 ms regardless of delay adjustments.
- **Dedicated Single-Shot Trigger Button**:
  - In GUI: Large, high-visibility **"SINGLE SHOT TRIGGER / ARM (*TRG)"** button.
  - In Code / CLI: Simple `.arm_single_shot()` or `.trigger()` method.
  - In single-shot external trigger mode, sending `*TRG` arms the DG645 to output upon receiving the next external trigger pulse.
- **Interactive Tkinter GUI**: Full control panel with port scanning, channel delay inputs, unit selectors, trigger configuration, and live communication logs.
- **Error Handling**: Reads instrument error queue (`LERR?`) with friendly human-readable descriptions.

---

## File Structure

| File | Description |
|------|-------------|
| [`dg645.py`](dg645.py) | Core instrument driver class (`DG645`) |
| [`dg645_gui.py`](dg645_gui.py) | Standalone desktop GUI application with trigger button |
| [`example_usage.py`](example_usage.py) | Ready-to-run automation script |
| [`test_dg645.py`](test_dg645.py) | Unit tests verifying commands, parsing, and mock communication |
| [`DG645m.pdf`](DG645m.pdf) | Official Stanford Research Systems DG645 user manual |

---

## Requirements & Installation

1. Make sure Python 3.8+ is installed.
2. Install `pyserial`:
   ```bash
   pip install pyserial
   ```

---

## Quick Start

### 1. Launch the Desktop GUI
To open the graphical interface:
```bash
python dg645_gui.py
```
Inside the GUI:
1. Select **COM5** (or click `↻ Refresh Ports`) and click **Connect**.
2. Select **Single Shot Ext Rising (TSRC 3)** and set your threshold (e.g. `1.000` V). Click **Apply Trigger Mode**.
3. Adjust the start delays for channels **AB**, **CD**, **EF**, **GH** (pulse widths are locked to 1.0 ms). Click **Apply All Delays**.
4. Click the big red button **⚡ SINGLE SHOT TRIGGER / ARM (*TRG) ⚡** to initiate / arm the single shot.

---

### 2. Run the Example Python Script
```bash
python example_usage.py
```
This script connects to `COM5`, configures external single-shot trigger mode, programs the 4 channels with 1 ms width, and lets you trigger single-shots interactively.

---

## Python Driver Usage Example

```python
from dg645 import DG645

# Connect via context manager
with DG645(port="COM5", baudrate=9600) as dg:
    print("Connected to:", dg.get_idn())

    # 1. Set Single-Shot External Trigger Mode (Rising edge)
    dg.set_trigger_source("single_shot_ext_rising")  # Sends TSRC 3
    dg.set_trigger_level(1.0)                        # 1.0 V threshold (TLVL 1.0)

    # 2. Configure 4 channels (AB, CD, EF, GH) with 1 ms pulse width
    # AB: start at 0 ms, width 1 ms
    dg.set_channel_pulse(channel_index_or_name='AB', delay_seconds=0.0, pulse_width_seconds=0.001)

    # CD: start at 10 ms, width 1 ms
    dg.set_channel_pulse(channel_index_or_name='CD', delay_seconds=10e-3, pulse_width_seconds=0.001)

    # EF: start at 20 ms, width 1 ms
    dg.set_channel_pulse(channel_index_or_name='EF', delay_seconds=20e-3, pulse_width_seconds=0.001)

    # GH: start at 30 ms, width 1 ms
    dg.set_channel_pulse(channel_index_or_name='GH', delay_seconds=30e-3, pulse_width_seconds=0.001)

    # 3. Arm / Trigger Single Shot
    dg.arm_single_shot()  # Sends *TRG
```

---

## DG645 Command Reference (from Manual)

- `*IDN?`: Returns device identification string.
- `TSRC 3`: Sets trigger mode to **Single-shot external rising edges**.
- `TSRC 4`: Sets trigger mode to **Single-shot external falling edges**.
- `TSRC 5`: Sets trigger mode to **Single-shot software trigger**.
- `TLVL <volts>`: Sets trigger threshold (e.g. `TLVL 1.000`).
- `DLAY <c>, <d>, <time>`: Sets channel `c` to `<time>` seconds relative to reference channel `d`.
  - Leading edges (`A=2, C=4, E=6, G=8`) are referenced to $T_0$ (`d=0`).
  - Trailing edges (`B=3, D=5, F=7, H=9`) are referenced to their respective leading edge with offset `0.001` (1 ms width).
- `*TRG`: Arms the DG645 to trigger on the next external trigger (in modes 3 and 4), or immediately initiates a delay sequence (in mode 5).
- `LERR?`: Queries and clears the last error from the error buffer.

# FAULHABER MCDC 3002 S RS 3-Axis Stage Controller GUI

A multi-threaded desktop GUI built with **PyQt6** and **pySerial** for controlling 3 **FAULHABER MCDC 3002 S RS** motion controllers connected across a single multi-drop RS232 serial network.

---

## Hardware & Protocol Specifications

- **Controller Model**: FAULHABER MCDC 3002 S RS
- **Bus Architecture**: RS232 multi-node bus controlling Nodes `1`, `2`, and `3` on a single COM port
- **Serial Configuration**: 9600 Baud (default, selectable up to 115200), 8 Data bits, No parity, 1 Stop bit (`8-N-1`)
- **Command Framing**: Standard ASCII strings formatted as `[NodeID][Command][Argument]\r` (Carriage Return `\r`, ASCII 13)

### Core Command Set
| Command | Description | Example (Node 1) |
|---|---|---|
| `EN` | Enable power stage | `1EN\r` |
| `DI` | Disable power stage / Stop | `1DI\r` |
| `LA [pos]` | Load absolute target position in raw counts | `1LA50000\r` |
| `LR [pos]` | Load relative target position in raw counts | `1LR-1000\r` |
| `M` | Initiate motion (sent after `LA` or `LR`) | `1M\r` |
| `HO` | Define home position (zeroes actual position) | `1HO\r` |
| `POS` | Query actual position in raw counts | `1POS\r` |

---

## Unit Calibration & Conversions

Each node supports independent calibration modes:

1. **Linear Stage Mode**:
   - Factor: $1\text{ count} = -0.025\ \mu\text{m}$
   - Position to Counts: $\text{Counts} = \text{round}\left(\frac{\text{Position in }\mu\text{m}}{-0.025}\right)$
   - Counts to Position: $\text{Position in }\mu\text{m} = \text{Counts} \times -0.025$

2. **Rotator Mode**:
   - Factor: $1\text{ count} = 5.15611 \times 10^{-5}\ \text{deg}$
   - Position to Counts: $\text{Counts} = \text{round}\left(\frac{\text{Position in deg}}{5.15611 \times 10^{-5}}\right)$
   - Counts to Position: $\text{Position in deg} = \text{Counts} \times 5.15611 \times 10^{-5}$

3. **Raw Counts Mode**:
   - Direct 1:1 encoder counts mapping without conversion.

---

## Application Structure

- `main.py`: Application entry point with high-DPI scaling and dark theme styling.
- `main_window.py`: Main dashboard integrating connection bar, global master controls, 3 node cards, and serial terminal.
- `serial_worker.py`: Dedicated background `QThread` with `queue.PriorityQueue` prioritizing immediate motion/safety commands over routine 200ms `POS` queries.
- `units.py`: Unit conversion and formatting engine for Linear, Rotator, and Raw counts modes.
- `widgets/node_card.py`: Control card component with live power LED, position readouts, homing, absolute move, and relative jog buttons.
- `widgets/master_panel.py`: Synchronized global actions (Enable All, Emergency Stop/Disable All, Home All).
- `widgets/log_panel.py`: Live color-coded ASCII traffic monitor (TX/RX) with auto-scroll, clear log, and direct manual command prompt with history recall.
- `test_stage_controller.py`: Unit test suite verifying conversions and GUI component instantiation.

---

## How to Run

```bash
# Launch GUI
python main.py

# Run verification test suite
python test_stage_controller.py
```

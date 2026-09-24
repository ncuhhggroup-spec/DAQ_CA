# System Operation Manual for **DAQ_CA**

## 1. System Overview & Quick Start

- **Architecture**: A local‑first data‑acquisition system with optional EPICS Channel Access (CA) integration. Core modules handle sequence control, data management, and hardware drivers. A PySide6 GUI provides operator interaction, while an optional IOC server exposes PVs for remote control.
- **Prerequisites**:
  - Python 3.13 (installed via Conda/Miniconda).
  - Packages from `Requirements.txt` (run `python -m pip install -r Requirements.txt`).
  - EPICS base installed and `PATH` configured if using CA.
- **Launch GUI**:
  ```bash
  cd C:\Users\BeamStablizer\Documents\GitHub\DAQ_CA
  python -m gui.main_gui
  ```
- **Launch IOC Server** (optional remote control):
  ```bash
  python -m ca_server.ioc_server
  ```

---

## 2. GUI Operator Guide (PySide6 Control Panel)

### 2.1 Control Panel Usage
- **Shot Target** – number of frames to acquire (`QSpinBox`).
- **File Name** – base name for HDF5/TIFF output (`QLineEdit`).
- **Note** – free‑form experiment description (`QLineEdit`).
- **ARM & START** – initiates sequence: stage position is logged, buffer allocated, camera armed.
- **DISARM & CANCEL** – aborts current run and resets system to `IDLE`.

### 2.2 State Machine & QSS Indicators
| State | Color (QSS) | UI Effect |
|------|-------------|-----------|
| **IDLE** | `#6c757d` (gray) | All input widgets enabled, DISARM disabled.
| **ARMED** | `#ffc107` (amber) | Widgets locked, live preview not started.
| **ACQUIRING** | `#0d6efd` (blue) | Live frame preview active, widgets remain locked.
| **SAVING** | `#6f42c1` (purple) | Save progress shown, widgets locked.
| **ERROR** | `#dc3545` (red) | UI shows error, DISARM enabled to reset.

The status label at the top of the window updates its background color automatically based on the `SystemState` enum.

### 2.3 2D Live Preview & Gaussian Fit
- The central `pyqtgraph.ImageView` displays the most recent camera frame in real time (≈20 fps).
- After acquisition the first frame is fitted with a 2‑D Gaussian (via `DataManager.fit_gaussian_2d`).
- Fit results (center X/Y, σ‑values, peak intensity) are over‑laid as a cross‑hair/ellipse and logged in the journal.

---

## 3. Laboratory Journaling & Logging System (流水帳實驗記錄)

- **Logger module**: `gui/journal_logger.py` creates a singleton logger (`gui_logger`).
- **File logger**: Writes to `experiment_journal.log` (root of the repository). Format:
  ```
  2026-09-24 10:45:12 | INFO     | ARM request – ShotTarget=10, FileName='run1', Note='test', StagePos={1: 12345, 2: 0, 3: 0}
  2026-09-24 10:45:45 | INFO     | Acquisition saved – HDF5: output/run1.h5, TIFF: output/run1.tif
  2026-09-24 10:45:45 | INFO     | Gaussian fit metrics: {'amplitude': ..., 'xo': ..., 'yo': ..., 'sigma_x': ..., 'sigma_y': ..., 'offset': ...}
  ```
- **Excel journal**: `experiment_log.xlsx` is updated by `DataManager.append_experiment_log`. Columns include `timestamp`, `shot_target`, `note`, `stage_x`, `stage_y`, `stage_z`.
- **HDF5 metadata**: When `DataManager.save_hdf5` is called, stage coordinates are stored as attributes `stage_x`, `stage_y`, `stage_z` on the dataset `/data`.

---

## 4. EPICS Channel Access (CA) Remote Integration

### 4.1 Starting the IOC Server
```bash
python -m ca_server.ioc_server
```
The server reads the same core objects used by the GUI, exposing a minimal set of PVs.

### 4.2 Exposed Process Variables
| PV | Type | Description |
|----|------|-------------|
| `EXP:Seq:ShotTarget` | `int` | Desired number of frames. |
| `EXP:Seq:Arm` | `int` (0/1) | Write `1` to arm/start acquisition; write `0` to abort/reset. |
| `EXP:Seq:State` | `string` | Current `SystemState` (`IDLE`, `ARMED`, `ACQUIRING`, `SAVING`, `ERROR`). |
| `EXP:Data:FileName` | `string` | Base name for output files. |
| `EXP:Data:Note` | `string` | Free‑form experiment note. |

### 4.3 Command‑line testing (same host or remote)
```bash
# Read current state
caget EXP:Seq:State

# Set shot target to 5 frames
caput EXP:Seq:ShotTarget 5

# Arm and start acquisition
caput EXP:Seq:Arm 1

# Cancel / reset
caput EXP:Seq:Arm 0
```
All PV changes propagate to the same `SequenceController` instance used by the GUI, ensuring synchronized local/remote operation.

---

## 5. Developer & Architecture Reference

- **Core modules**:
  - `core/sequence_controller.py` – Implements the state machine, interlock checks, and orchestrates hardware drivers.
  - `core/data_manager.py` – Handles zero‑copy RAM buffer allocation, HDF5/TIFF persistence, 2‑D Gaussian fitting, and Excel journal appending.
- **Drivers** (`drivers/`):
  - `mock_stage_driver.py`, `mock_camera_gui.py`, `mock_dg645_driver.py` – Software‑only stand‑ins.
  - Real drivers can replace these classes (same interface defined in `base_driver.py`).
- **Data persistence**:
  - RAM buffer allocated with `np.empty` and pre‑filled with zeros for fast page commitment.
  - `DataManager.save_hdf5` stores the buffer under `/data` with optional metadata attributes (`stage_x`, `stage_y`, `stage_z`).
  - `DataManager.save_tiff` writes a TIFF stack; `DataManager.append_experiment_log` updates the Excel log.
- **Switching drivers**:
  ```python
  from drivers.mock_stage_driver import MockStageDriver
  # Replace with hardware driver import when available
  # from drivers.faulhaber_stage_driver import FaulhaberStageDriver
  stage = MockStageDriver()  # or FaulhaberStageDriver()
  ```

---

## 6. Troubleshooting & Error Recovery

| Symptom | Likely Cause | Remedy |
|---------|--------------|-------|
| UI shows **ERROR** state, log contains `Stage is moving` | Interlock blocked because `stage.is_moving()` returned `True`. | Ensure stage motion is stopped. Click **DISARM & CANCEL** or run `stage.stop()` from Python console. |
| No live preview frames appear | Camera not initialized or `MockCameraGUI` failed to generate frames. | Verify `MockCameraGUI` is instantiated; check console log for errors. |
| Save step fails, HDF5 file not created | Buffer is `None` or disk permission issue. | Confirm `arm_and_start` succeeded and buffer allocated. Check write permissions to the output directory. |
| EPICS PV does not update UI | IOC server not running or network/firewall block. | Start `ca_server.ioc_server`; verify `caget`/`caput` work on the same host. |

### Resetting from **ERROR** to **IDLE**
1. Click **DISARM & CANCEL** – the controller calls `reset()`, clears the buffer, and forces state to `IDLE`.
2. If the UI does not respond, close the GUI and restart the application.
3. Review `experiment_journal.log` for the detailed traceback.

---

*Document version: 2026‑09‑24*

---

*(End of manual)*

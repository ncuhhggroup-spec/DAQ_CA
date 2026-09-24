# Development Log

## 2026-09-23

- Created `DEVELOPMENT_LOG.md` to track module creation and API signatures.
- Planned and approved implementation of drivers, core data manager, sequence controller, GUI, and tests.
- Added initial entries for driver abstractions and mock implementations.
- Implemented `core/data_manager.py` with zero‑copy RAM buffer pre‑allocation, HDF5/TIFF persistence, 2D Gaussian fitting, and experiment_log.xlsx auto‑appending.
- Implemented `core/sequence_controller.py` using the State Pattern (SystemState Enum) and enforced interlock rules for stage and camera arming.
- Updated API signatures and added function notes for the new modules.
- Simplified `arm_and_start` to perform all parameter and interlock checks; no mid‑acquisition validation.
- Implemented `tests/test_single_shot_sequence.py` and root runner `test_single_shot_sequence.py` with Mock drivers (`MockStageDriver`, `MockDG645Driver`, `MockCameraGUI`), `DataManager`, and `SequenceController`.
- Executed integration test suite verifying 3 test scenarios (100% Passed):
  - **Scenario A (1-Shot Run)**: Verified `arm_and_start(frames=1)` state progression (IDLE -> ARMED -> ACQUIRING -> SAVING -> IDLE), RAM buffer pre-allocation `(1, 512, 512)`, HDF5 compression dataset persistence, multi-frame TIFF export, and automatic row appending to `experiment_log.xlsx`.
  - **Scenario B (10-Shot Run)**: Verified 10-frame burst allocation `(10, 256, 256)`, full frame sequence acquisition, HDF5/TIFF persistence, and buffer deallocation / reset to IDLE.
  - **Scenario C (Interlock Check)**: Simulated `stage.is_moving() == True`; verified `arm_and_start()` strictly blocks arming, logs error, transitions state safely to `ERROR`, allocates no RAM, leaves camera disarmed, and safely restores to `IDLE` upon `reset()`.
- **Validation Status**: `pytest tests/test_single_shot_sequence.py` passed with 3/3 tests (100% OK).
- Implemented `ca_server/ioc_server.py` and `ca_server/__init__.py` providing lightweight EPICS Channel Access IOC using `caproto.server` (`PVGroup`, `pvproperty`).
- Exposed 5 Core Process Variables (PVs) as a thin wrapper over `SequenceController`:
  - `ShotTarget` (int, default=1, writable): Sets shot count target (1-100) for single-shot or multi-frame burst.
  - `Arm` (int, writable, 1=Arm & Start): Triggers DAQ acquisition asynchronously, auto-resets to 0 upon completion.
  - `State` (string, read-only): Reflects real-time controller state (`IDLE`, `ARMED`, `ACQUIRING`, `SAVING`, `ERROR`).
  - `FileName` (string, default="exp_run", writable): Configures raw output file prefix.
  - `Note` (string, default="", writable): Run comment and log annotations.
- Thread Isolation: Wrapped all blocking hardware I/O and data persistence calls using `asyncio.to_thread` (`SequenceController.run_full_sequence`), keeping the caproto network event loop completely non-blocking.
- Implemented `tests/test_ioc_server.py` validating PV creation, parameter updating, asynchronous arming, and interlock error handling.
- **Validation Status**: Full test suite (`pytest tests`) passed with 7/7 tests (100% OK).
- Created `ca_client_test.py` automated cross-PC test client and `CROSS_PC_EPICS_TEST_MANUAL.md` process manual covering LAN network setup, firewall rules, automated multi-PC validation, and command-line verification.
- Refined `ca_client_test.py` with `decode_epics_value`: robustly decodes EPICS char-waveform ASCII integer arrays (`[73, 68, 76, 69]` -> `"IDLE"`) and bytes; added empty-array safeguards for `Note` and `FileName` to prevent `IndexError` on zero-length responses. Updated `ca_server/ioc_server.py` `State` PV definition with `max_length=32`.
# Development Log

## 2026-09-23

- Created `DEVELOPMENT_LOG.md` to track module creation and API signatures.
- Planned and approved implementation of drivers, core data manager, sequence controller, GUI, and tests.
- Added initial entries for driver abstractions and mock implementations.
- Implemented `core/data_manager.py` with zero‑copy RAM buffer pre‑allocation, HDF5/TIFF persistence, 2D Gaussian fitting, and experiment_log.xlsx auto‑appending.
- Implemented `core/sequence_controller.py` using the State Pattern (SystemState Enum) and enforced interlock rules for stage and camera arming.
- Updated API signatures and added function notes for the new modules.
- Simplified `arm_and_start` to perform all parameter and interlock checks; no mid‑acquisition validation.
- Implemented `tests/test_single_shot_sequence.py` and root runner `test_single_shot_sequence.py` with Mock drivers (`MockStageDriver`, `MockDG645Driver`, `MockCameraGUI`), `DataManager`, and `SequenceController`.
- Executed integration test suite verifying 3 test scenarios (100% Passed):
  - **Scenario A (1-Shot Run)**: Verified `arm_and_start(frames=1)` state progression (IDLE -> ARMED -> ACQUIRING -> SAVING -> IDLE), RAM buffer pre-allocation `(1, 512, 512)`, HDF5 compression dataset persistence, multi-frame TIFF export, and automatic row appending to `experiment_log.xlsx`.
  - **Scenario B (10-Shot Run)**: Verified 10-frame burst allocation `(10, 256, 256)`, full frame sequence acquisition, HDF5/TIFF persistence, and buffer deallocation / reset to IDLE.
  - **Scenario C (Interlock Check)**: Simulated `stage.is_moving() == True`; verified `arm_and_start()` strictly blocks arming, logs error, transitions state safely to `ERROR`, allocates no RAM, leaves camera disarmed, and safely restores to `IDLE` upon `reset()`.
- **Validation Status**: `pytest tests/test_single_shot_sequence.py` passed with 3/3 tests (100% OK).
- Implemented `ca_server/ioc_server.py` and `ca_server/__init__.py` providing lightweight EPICS Channel Access IOC using `caproto.server` (`PVGroup`, `pvproperty`).
- Exposed 5 Core Process Variables (PVs) as a thin wrapper over `SequenceController`:
  - `ShotTarget` (int, default=1, writable): Sets shot count target (1-100) for single-shot or multi-frame burst.
  - `Arm` (int, writable, 1=Arm & Start): Triggers DAQ acquisition asynchronously, auto-resets to 0 upon completion.
  - `State` (string, read-only): Reflects real-time controller state (`IDLE`, `ARMED`, `ACQUIRING`, `SAVING`, `ERROR`).
  - `FileName` (string, default="exp_run", writable): Configures raw output file prefix.
  - `Note` (string, default="", writable): Run comment and log annotations.
- Thread Isolation: Wrapped all blocking hardware I/O and data persistence calls using `asyncio.to_thread` (`SequenceController.run_full_sequence`), keeping the caproto network event loop completely non‑blocking.
- Implemented `tests/test_ioc_server.py` validating PV creation, parameter updating, asynchronous arming, and interlock error handling.
- **Validation Status**: Full test suite (`pytest tests`) passed with 7/7 tests (100% OK).
- Created `ca_client_test.py` automated cross‑PC test client and `CROSS_PC_EPICS_TEST_MANUAL.md` process manual covering LAN network setup, firewall rules, automated multi‑PC validation, and command‑line verification.
- Refined `ca_client_test.py` with `decode_epics_value`: robustly decodes EPICS char‑waveform ASCII integer arrays (`[73, 68, 76, 69]` -> "IDLE") and bytes; added empty‑array safeguards for `Note` and `FileName` to prevent `IndexError` on zero‑length responses. Updated `ca_server/ioc_server.py` `State` PV definition with `max_length=32`.

## 2026-09-24

- Added GUI client application under `gui/` with main window `gui/main_window.py`. Implements EPICS PV interaction via `caproto`, UI controls for ShotTarget, FileName, Note, ARM/DISARM, state indicator, console log, and realtime image preview using PySide6 and pyqtgraph. Ensured no modifications to core or IOC server code.

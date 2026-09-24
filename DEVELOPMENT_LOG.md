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
- Added `gui/journal_logger.py` providing a persistent logger backing a read‑only `QTextEdit` console widget and auto‑logging parameter changes and run summaries (timestamped, stage coordinates, Gaussian fit metrics).
- Created `gui/main_window.py` (launchable via `main_gui.py`) with PySide6 UI: ShotTarget spin box, FileName/Note line edits, ARM/START & DISARM/CANCEL buttons, real‑time status label (dynamic QSS), and a `pyqtgraph.ImageView` for live frame preview and 2D Gaussian overlay.
- Implemented UI state management: input widgets disabled during ARMED, ACQUIRING, SAVING; status label colors follow State PV (IDLE gray, ARMED amber, ACQUIRING blue, SAVING purple, ERROR red).
- Integrated stage pre‑logging: before arming, current stage position is fetched from the driver and logged to console, Excel journal, and stored as HDF5 metadata attributes.
- Added `gui/main_gui.py` entry point to instantiate `QApplication`, `MainWindow`, and start the event loop.
- Updated DEVELOPMENT_LOG.md with GUI architecture, logging contracts, and API overview.

# System Architecture & Prompt Design Specification: Local-First DAQ & CA-Ready Server (v3.0)

This document serves as the updated technical design blueprint, architecture specification, and master context prompt for building low-level Python hardware drivers, the dual GigE camera GUI, the caproto Channel Access (EPICS) server, the PyQt/PySide6 Client GUI, and the project logbook.

## 1. Core Architecture Principles

### 1.1 Local-First Philosophy
- **Local Control & Tuning**: Stage micro-positioning (Faulhaber/Homemade), camera exposure/gain/ROI, and DG645 delay channels are configured and operated locally.
- **Local Data Persistence & Processing**: Images are stored directly to local SSD in HDF5/TIFF formats with metadata tags. Local image processing (e.g., 2D Gaussian fitting) and automatic Excel log appending (`experiment_log.xlsx`) run locally to avoid EPICS event loop network bottlenecks.
- **Experimental Running Journal (流水帳實驗記錄)**: All user actions, parameter adjustments (`ShotTarget`, `FileName`, `Note`), stage coordinates, and acquisition analytical summaries (Peak, Center, FWHM) are continuously logged into a persistent file (`experiment_journal.log`) and streamed to the GUI console log to ensure complete experiment reconstruction.

### 1.2 EPICS Channel Access Thin-Wrapper Pattern
- All business logic is encapsulated inside local `SequenceController` and `DataManager` modules.
- The `caproto` IOC acts strictly as a lightweight remote wrapper, exposing primary PVs (`ShotTarget`, `Arm`, `State`, `FileName`, `Note`).

---

## 2. Mandatory Software Design Patterns

1. **Strategy Pattern / Abstract Interfaces for Drivers**:
   - All drivers inherit from abstract base classes (`BaseCamera`, `BaseStage`, `BaseDelayGen`).
   - Implement both `RealDriver` and `MockDriver` for offline development and testing.
2. **State Pattern & Interlocks**:
   - Enforce strict state management via Enum (`IDLE`, `ARMED`, `ACQUIRING`, `SAVING`, `ERROR`).
   - Interlock rule: `arm_and_start()` must verify `stage.is_moving() == False` before arming cameras.
3. **Manager Pattern for Data & RAM**:
   - `DataManager` handles zero-copy RAM buffer pre-allocation, local HDF5 persistence, TIFF tag embedding, stage coordinate metadata embedding, and Excel log appending (`experiment_log.xlsx`).
4. **Thread Pool & Signal Isolation**:
   - All blocking I/O (Serial RS-232, C SDK calls, file saving) must be wrapped using `asyncio.to_thread()` or `ThreadPoolExecutor`.
   - GUI-to-EPICS or GUI-to-Controller communication must strictly use Qt Signals and Slots to prevent UI freezing.

---

## 3. Project Directory Structure

```text
DAQ_CA/
├── DEVELOPMENT_LOG.md         # Token-efficient logbook tracking APIs, state & tasks
├── SYSTEM_DESIGN_BLUEPRINT.md # System architecture & design blueprint
├── experiment_journal.log     # Chronological laboratory journal file (流水帳記錄)
├── experiment_log.xlsx        # Structured tabular run metadata logger
├── config.yaml                # Serial ports, baud rates, default paths
├── drivers/                   # Hardware Driver Layer (Strategy Pattern)
│   ├── base_driver.py         # Abstract base classes
│   ├── dg645_driver.py        # SRS DG645 driver (with Mock)
│   ├── stage_driver.py        # Stage driver (Faulhaber/Homemade with Mock)
│   └── camera_gui.py          # Dual GigE Camera GUI & Driver (with Mock)
├── core/                      # Local Core Logic & Data Layer
│   ├── data_manager.py        # RAM Buffer, HDF5, TIFF Tags, Excel Logger
│   └── sequence_controller.py # State machine controller (CA Hook)
├── ca_server/                 # EPICS IOC Directory (Phase 2)
│   └── ioc_server.py          # caproto.asyncio thin-wrapper server
├── gui/                       # GUI Client Directory (Phase 3)
│   ├── main_window.py         # PySide6 Control Panel, Dynamic QSS, 2D Preview Widget
│   └── journal_logger.py      # Stream & File Journal Logger for QTextEdit
└── main_gui.py                # Standalone GUI Launcher Script
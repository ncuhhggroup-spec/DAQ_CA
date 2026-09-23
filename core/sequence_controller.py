# core/sequence_controller.py
"""SequenceController – coordinates mock drivers and DataManager.

All experimental parameters are static once the system is armed. The
`arm_and_start()` method performs every required interlock and parameter check.
No validation or monitoring is performed during the active acquisition phase.
"""

from __future__ import annotations

import logging
from enum import Enum, auto
from typing import Any, Dict, Optional, Tuple

from .data_manager import DataManager
from drivers.mock_stage_driver import MockStageDriver
from drivers.mock_camera_gui import MockCameraGUI
from drivers.mock_dg645_driver import MockDG645Driver

logger = logging.getLogger(__name__)


class SystemState(Enum):
    IDLE = auto()
    ARMED = auto()
    ACQUIRING = auto()
    SAVING = auto()
    ERROR = auto()


class SequenceController:
    """Manages the acquisition sequence.

    The controller follows the State Pattern. All static experimental parameters
    (e.g., number of frames, buffer shape) and interlock checks are performed in
    :meth:`arm_and_start`. During the burst phase (`acquire`/`save`) the code
    assumes parameters remain unchanged.
    """

    def __init__(
        self,
        stage: MockStageDriver,
        cam: MockCameraGUI,
        data_mgr: DataManager,
        dg645: Optional[MockDG645Driver] = None
    ) -> None:
        self.stage = stage
        self.cam = cam
        self.data_mgr = data_mgr
        self.dg645 = dg645
        self.state = SystemState.IDLE
        self.shot_target: int = 1
        self.file_name: str = "exp_run"
        self.note: str = ""
        self._frames: int | None = None
        self._buffer_shape: tuple[int, int, int] | None = None

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------
    def _set_state(self, new_state: SystemState) -> None:
        logger.info("State transition: %s -> %s", self.state.name, new_state.name)
        self.state = new_state

    def set_experiment_config(self, file_name: str, note: str, shot_target: int = 1) -> None:
        """Configure experiment metadata and shot count."""
        self.file_name = file_name
        self.note = note
        self.shot_target = max(1, int(shot_target))

    def run_full_sequence(
        self,
        frames: Optional[int] = None,
        file_name: Optional[str] = None,
        note: Optional[str] = None,
        output_dir: str = "data",
    ) -> bool:
        """Run complete single-shot or multi-shot sequence synchronously.

        Designed to be dispatched to a background worker thread (e.g. via
        asyncio.to_thread) to prevent blocking the asyncio / EPICS event loop.
        """
        import pathlib
        from datetime import datetime

        if frames is not None:
            self.shot_target = max(1, int(frames))
        if file_name is not None:
            self.file_name = file_name
        if note is not None:
            self.note = note

        target_frames = self.shot_target
        out_dir = pathlib.Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        hdf5_path = out_dir / f"{self.file_name}_{timestamp}.h5"
        tiff_path = out_dir / f"{self.file_name}_{timestamp}.tif"

        try:
            # 1. Arm & start
            self.arm_and_start(frames=target_frames)
            # 2. Acquire
            self.acquire()
            # 3. Save
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "file_name": str(hdf5_path.name),
                "shot_target": target_frames,
                "stage_pos": self.stage.get_position(1) if hasattr(self.stage, "get_position") else 0,
                "note": self.note,
            }
            self.save(hdf5_path=hdf5_path, tiff_path=tiff_path, log_entry=log_entry)
            return True
        except Exception as e:
            logger.error("Sequence failed: %s", e)
            self._set_state(SystemState.ERROR)
            try:
                self.cam.disarm()
            except Exception:
                pass
            return False

    # ---------------------------------------------------------------------
    # Public API – arm_and_start performs all checks
    # ---------------------------------------------------------------------
    def arm_and_start(self, frames: int = 1) -> None:
        """Arm the system and allocate the RAM buffer.

        Parameters
        ----------
        frames : int, optional
            Number of frames to acquire. Treated as a static parameter – it must
            be supplied before acquisition begins.
        """
        # Interlock: stage must be stationary
        if self.stage.is_moving():
            self._set_state(SystemState.ERROR)
            logger.error("Interlock failure – stage is moving while arming.")
            raise RuntimeError("Stage is moving – cannot arm.")

        # Simple parameter validation (static at arm time)
        if frames < 1:
            self._set_state(SystemState.ERROR)
            logger.error("Invalid frame count %s – must be >= 1.", frames)
            raise ValueError("frames must be a positive integer")

        # Determine buffer shape from the camera and allocate
        height, width = self.cam.get_frame_shape()
        self._buffer_shape = (frames, height, width)
        self.data_mgr.allocate_buffer(self._buffer_shape)
        self._frames = frames

        # Arm the camera (mock implementation) and move to ARMED state
        self.cam.arm()
        if self.dg645 and hasattr(self.dg645, "connect") and not getattr(self.dg645, "_connected", False):
            self.dg645.connect()
        self._set_state(SystemState.ARMED)

    # ---------------------------------------------------------------------
    # Acquisition – no mid‑acquisition validation
    # ---------------------------------------------------------------------
    def acquire(self) -> None:
        """Capture frames into the pre-allocated RAM buffer.

        Assumes the system is already ARMED and that all parameters remain
        unchanged.
        """
        if self.state != SystemState.ARMED:
            self._set_state(SystemState.ERROR)
            raise RuntimeError("Controller not armed – cannot acquire.")

        self._set_state(SystemState.ACQUIRING)
        
        # Fire DG645 trigger if available
        if self.dg645:
            try:
                self.dg645.trigger()
            except Exception as e:
                logger.warning("DG645 trigger note: %s", e)

        if self.data_mgr.buffer is None:
            self._set_state(SystemState.ERROR)
            raise RuntimeError("Buffer not allocated.")

        num_frames = self._frames if self._frames is not None else self.data_mgr.buffer.shape[0]
        for i in range(num_frames):
            frame = self.cam.get_frame()
            self.data_mgr.buffer[i] = frame

        self._set_state(SystemState.SAVING)

    # ---------------------------------------------------------------------
    # Persistence
    # ---------------------------------------------------------------------
    def save(self, hdf5_path: str | Any, tiff_path: str | Any, log_entry: Dict[str, Any]) -> None:
        """Persist the buffer to HDF5/TIFF and append a log entry.
        """
        if self.state != SystemState.SAVING:
            self._set_state(SystemState.ERROR)
            raise RuntimeError("Nothing to save – controller not in SAVING state.")
        self.data_mgr.save_hdf5(hdf5_path)
        self.data_mgr.save_tiff(tiff_path)
        self.data_mgr.append_experiment_log(log_entry)
        self.cam.disarm()
        self._set_state(SystemState.IDLE)

    # ---------------------------------------------------------------------
    # Reset / cleanup
    # ---------------------------------------------------------------------
    def reset(self) -> None:
        """Return to IDLE and clear allocated resources.
        """
        self.data_mgr.buffer = None
        self.cam.disarm()
        self._frames = None
        self._buffer_shape = None
        self._set_state(SystemState.IDLE)

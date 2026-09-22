import time
from enum import Enum
from typing import Optional, Callable
from drivers.base_driver import BaseStageDriver, BaseCameraDriver, BaseDG645Driver
from core.data_manager import DataManager


class SystemState(Enum):
    IDLE = "IDLE"
    ARMED = "ARMED"
    ACQUIRING = "ACQUIRING"
    SAVING = "SAVING"
    ERROR = "ERROR"


class SequenceController:
    """Core DAQ Orchestrator managing hardware triggers, interlocks, and state transitions."""
    
    def __init__(
        self,
        stage_driver: BaseStageDriver,
        camera_driver: BaseCameraDriver,
        dg645_driver: BaseDG645Driver,
        data_manager: DataManager,
        on_state_change: Optional[Callable[[SystemState], None]] = None,
        on_log: Optional[Callable[[str], None]] = None
    ):
        self.stage = stage_driver
        self.camera = camera_driver
        self.dg645 = dg645_driver
        self.data_mgr = data_manager
        
        self.state = SystemState.IDLE
        self.shot_target = 10
        self.shot_current = 0
        self.file_name = "exp_run"
        self.note = ""
        
        self.on_state_change = on_state_change
        self.on_log = on_log

    def _set_state(self, state: SystemState):
        self.state = state
        if self.on_state_change:
            self.on_state_change(state)

    def _log(self, msg: str):
        if self.on_log:
            self.on_log(msg)
        else:
            print(msg)

    def set_experiment_config(self, file_name: str, note: str, shot_target: int):
        """Configure experiment metadata and shot count."""
        self.file_name = file_name
        self.note = note
        self.shot_target = max(1, min(100, int(shot_target)))

    def arm_and_start(self) -> bool:
        """Executes full DAQ sequence: Interlock Check -> Arming -> Auto-Fire -> Persistence & Analysis.
        Compatible with Phase 2 EPICS PV (EXP:Seq:Arm = 1).
        """
        # 1. Interlock Check: Stage must not be in motion
        if self.stage.is_moving():
            self._log("[Warning] Arming rejected: Stage is still in motion (Stage:IsMoving == True).")
            return False

        try:
            # 2. Enter ARMED state & allocate continuous RAM buffer
            self._set_state(SystemState.ARMED)
            self.shot_current = 0
            self._log(f"[DAQ] System ARMED for {self.shot_target} shots.")
            self.data_mgr.allocate_ram_buffer(self.shot_target)
            self.camera.set_trigger_mode("EXTERNAL_TTL")

            # 3. Enter ACQUIRING state & fire DG645 burst trigger
            self._set_state(SystemState.ACQUIRING)
            self._log(f"[DAQ] Firing DG645 burst ({self.shot_target} pulses)...")
            self.dg645.set_burst_count(self.shot_target)
            self.dg645.trigger()

            # Read frames from camera
            frames = self.camera.acquire_frames(self.shot_target)
            self.data_mgr.load_acquired_data(frames)
            self.shot_current = self.shot_target

            # 4. Enter SAVING state: HDF5/NPZ persistence, analysis, and Excel log
            self._set_state(SystemState.SAVING)
            self._log("[DAQ] Saving data and running local analysis...")
            current_pos = self.stage.get_position()
            
            # Local fast analysis
            metrics = self.data_mgr.run_local_analysis()
            
            # Persistence
            saved_path = self.data_mgr.save_to_hdf5(
                file_name=self.file_name,
                note=self.note,
                stage_pos=current_pos
            )
            self.data_mgr.append_excel_log(
                filename=saved_path,
                stage_pos=current_pos,
                shot_count=self.shot_target,
                note=self.note
            )
            self._log(f"[DAQ] Data saved to {saved_path}. Logbook updated.")
            self._log(f"[DAQ] Analysis: Mean={metrics.get('mean_intensity')} Peak={metrics.get('max_intensity')}")

            # 5. Restore camera mode & return to IDLE
            self.camera.set_trigger_mode("INTERNAL/OFF")
            self._set_state(SystemState.IDLE)
            self._log("[DAQ] Sequence completed successfully. System IDLE.")
            return True

        except Exception as e:
            self._set_state(SystemState.ERROR)
            self._log(f"[Error] DAQ Sequence failed: {e}")
            try:
                self.camera.set_trigger_mode("INTERNAL/OFF")
            except Exception:
                pass
            return False

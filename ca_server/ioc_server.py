#!/usr/bin/env python3
"""
ca_server/ioc_server.py
========================
Lightweight EPICS Channel Access IOC using caproto.server / caproto.asyncio.

Implements the Thin-Wrapper pattern over SequenceController:
Exposes 5 core PVs without blocking the caproto event loop:
1. ShotTarget (int, default=1, writable)
2. Arm (int/enum, 1=Arm & Start, writable)
3. State (string/enum, read-only: IDLE, ARMED, ACQUIRING, SAVING, ERROR)
4. FileName (string, writable)
5. Note (string, writable)

All hardware-bound or file-system-bound operations executed by SequenceController
are offloaded to background threads using asyncio.to_thread / loop.run_in_executor
so the EPICS CA network loop remains fully responsive.
"""

from __future__ import annotations

import asyncio
import logging
from .device_status import DeviceStatus
from typing import Optional

from caproto.server import PVGroup, pvproperty, run
from caproto import ChannelType

from core.data_manager import DataManager
from core.sequence_controller import SequenceController, SystemState
from drivers.mock_stage_driver import MockStageDriver
from drivers.mock_camera_gui import MockCameraGUI
from drivers.mock_dg645_driver import MockDG645Driver

logger = logging.getLogger(__name__)


class DAQIOC(PVGroup):
    """EPICS Channel Access IOC wrapping SequenceController.
    
    Exposes 5 core Process Variables:
    - `ShotTarget`: Number of shots/frames for burst acquisition (1-100).
    - `Arm`: Writing 1 triggers arm_and_start() and the acquisition sequence.
    - `State`: Read-only system state (IDLE, ARMED, ACQUIRING, SAVING, ERROR).
    - `FileName`: Output filename prefix for HDF5 and TIFF files.
    - `Note`: Run annotation and logbook comments.
    """

    # 1. ShotTarget PV (int, default=1, writable)
    ShotTarget = pvproperty(
        value=1,
        doc="Number of shots/frames to acquire in sequence (default 1)",
        dtype=int,
    )

    # 2. Arm PV (int/enum, 1=Arm & Start, writable)
    Arm = pvproperty(
        value=0,
        doc="Write 1 to Arm & Start acquisition sequence (self-resetting)",
        dtype=int,
    )

    # 3. State PV (string, read-only)
    State = pvproperty(
        value="IDLE",
        doc="Current DAQ system state (IDLE, ARMED, ACQUIRING, SAVING, ERROR)",
        dtype=str,
        max_length=32,
        read_only=True,
    )

    # 4. FileName PV (string, writable)
    FileName = pvproperty(
        value="exp_run",
        doc="Experiment file name prefix",
        dtype=str,
        max_length=64,
    )

    # 5. Note PV (string, writable)
    Note = pvproperty(
        value="",
        doc="User annotations and log comments",
        dtype=str,
        max_length=128,
    )

    # 6. StageStatus PV (string, read‑only, default DISCONNECTED)
    StageStatus = pvproperty(
        value="DISCONNECTED",
        doc="Stage connection status",
        dtype=str,
        max_length=32,
        read_only=True,
    )

    # 7. DG645Status PV (string, read‑only, default DISCONNECTED)
    DG645Status = pvproperty(
        value="DISCONNECTED",
        doc="DG645 timing module status",
        dtype=str,
        max_length=32,
        read_only=True,
    )

    # 8. CameraStatus PV (string, read‑only, default DISCONNECTED)
    CameraStatus = pvproperty(
        value="DISCONNECTED",
        doc="Camera connection status",
        dtype=str,
        max_length=32,
        read_only=True,
    )

    # 9. ErrorMessage PV (string, read‑only, default empty)
    ErrorMessage = pvproperty(
        value="",
        doc="Latest error message from server",
        dtype=str,
        max_length=256,
        read_only=True,
    )

    # 10. ResetError PV (int, write‑only trigger to clear error message)
    ResetError = pvproperty(
        value=0,
        doc="Write 1 to clear the ErrorMessage PV",
        dtype=int,
        read_only=False,
    )

    # 11. Rescan PV (int, write‑only trigger to refresh device statuses)
    Rescan = pvproperty(
        value=0,
        doc="Write 1 to re‑evaluate device connection statuses",
        dtype=int,
        read_only=False,
    )

    # 9. ErrorMessage PV (string, read‑only, default empty)
    ErrorMessage = pvproperty(
        value="",
        doc="Latest error message from server",
        dtype=str,
        max_length=256,
        read_only=True,
    )

    # 10. ResetError PV (int, write‑only trigger to clear error message)
    ResetError = pvproperty(
        value=0,
        doc="Write 1 to clear the ErrorMessage PV",
        dtype=int,
        read_only=False,
    )

    # 9. ShotInterval PV (float, writable, default 10.0, min 0.1, max 3600.0)
    ShotInterval = pvproperty(
        value=10.0,
        doc="Inter‑shot interval in seconds",
        dtype=float,
        read_only=False,
    )

    def __init__(self, *args, controller: Optional[SequenceController] = None, **kwargs):
        super().__init__(*args, **kwargs)
        if controller is None:
            # Provide default mock hardware stack
            stage = MockStageDriver()
            cam = MockCameraGUI()
            dg645 = MockDG645Driver()
            data_mgr = DataManager()
            self.controller = SequenceController(stage=stage, cam=cam, data_mgr=data_mgr, dg645=dg645)
        else:
            self.controller = controller

        # Determine hardware connection status (real drivers vs mocks)
        try:
            stage_connected = not isinstance(self.controller.stage, MockStageDriver)
        except Exception:
            stage_connected = False
        try:
            camera_connected = not isinstance(self.controller.cam, MockCameraGUI)
        except Exception:
            camera_connected = False
        try:
            dg_connected = not isinstance(self.controller.dg645, MockDG645Driver)
        except Exception:
            dg_connected = False

        # Store a reference to the diagnostic status group if it exists
        self._diag_status = getattr(self, "diagnostic_status", None)
        # Remember hardware connection flags for later status updates
        self._stage_connected = stage_connected
        self._camera_connected = camera_connected
        self._dg_connected = dg_connected

        # Sync initial state
        self._lock = asyncio.Lock()

    @ShotTarget.putter
    async def ShotTarget(self, instance, value):
        """Update target shot count."""
        val = max(1, int(value))
        logger.info("[IOC] ShotTarget set to %d", val)
        self.controller.shot_target = val
        return val

    @FileName.putter
    async def FileName(self, instance, value):
        """Update output file name prefix."""
        val = str(value).strip()
        logger.info("[IOC] FileName set to '%s'", val)
        self.controller.file_name = val
        return val

    @Note.putter
    async def Note(self, instance, value):
        """Update experiment user note."""
        val = str(value)
        logger.info("[IOC] Note updated: '%s'", val)
        self.controller.note = val
        return val

    @ShotInterval.putter
    async def ShotInterval(self, instance, value):
        """Validate and update shot interval (seconds)."""
        try:
            val = float(value)
        except (TypeError, ValueError):
            val = 10.0
        # Clamp to allowed range
        val = max(0.1, min(3600.0, val))
        logger.info("[IOC] ShotInterval set to %s", val)
        if hasattr(self.controller, "shot_interval"):
            self.controller.shot_interval = val
        return val

    @Arm.putter
    async def Arm(self, instance, value):
        """Handle Arm trigger (1 = Arm & Start sequence).
        
        Dispatches execution to a background thread to prevent blocking
        the caproto event loop.
        """
        int_val = int(value)
        if int_val != 1:
            return 0

        # Run acquisition asynchronously in background task
        asyncio.create_task(self._execute_daq_sequence())
        return 1

    async def _execute_daq_sequence(self):
        """Executes full DAQ sequence in worker thread while streaming state updates to PV."""
        async with self._lock:
            try:
                # Update State PV -> ARMED
                await self.State.write(value="ARMED")

                # Offload blocking hardware sequence to thread pool
                success = await asyncio.to_thread(
                    self.controller.run_full_sequence,
                    frames=self.controller.shot_target,
                    file_name=self.controller.file_name,
                    note=self.controller.note,
                )

                if success:
                    await self.State.write(value="IDLE")
                else:
                    await self.State.write(value="ERROR")

            except Exception as exc:
                logger.error("[IOC] DAQ sequence error: %s", exc)
                # Populate error message PV
                await self.ErrorMessage.write(value=str(exc))
                await self.State.write(value="ERROR")
            finally:
                # Reset Arm PV back to 0
                await self.Arm.write(value=0)


def create_ioc(
    prefix: str = "EXP:Seq:",
    controller: Optional[SequenceController] = None,
) -> tuple[DAQIOC, "DeviceStatus"]:
    """Factory creating DAQIOC and DeviceStatus instances with appropriate prefixes."""
    daq_ioc = DAQIOC(prefix=prefix, controller=controller)
    # Diagnostic status group uses its own prefix
    diagnostic_ioc = DeviceStatus(prefix="EXP:Dev:")
    # Link the diagnostic group to the main IOC for status updates
    daq_ioc.diagnostic_status = diagnostic_ioc
    return daq_ioc, diagnostic_ioc

    @ResetError.putter
    async def ResetError(self, instance, value):
        """Clear the ErrorMessage PV when a 1 is written."""
        if int(value) == 1:
            await self.ErrorMessage.write(value="")
            logger.info("[IOC] ErrorMessage cleared via ResetError PV")
        return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("=================================================================")
    print("       STARTING CAPROTO EPICS CHANNEL ACCESS IOC SERVER          ")
    print("=================================================================")
    print("PVs exposed under prefix 'EXP:Seq:':")
    print("  - EXP:Seq:ShotTarget (int, R/W)")
    print("  - EXP:Seq:Arm        (int, R/W)")
    print("  - EXP:Seq:State      (str, RO)")
    print("  - EXP:Seq:FileName   (str, R/W)")
    print("  - EXP:Seq:Note       (str, R/W)")
    print("  - EXP:Seq:StageStatus (str, RO)")
    print("  - EXP:Seq:DG645Status (str, RO)")
    print("  - EXP:Seq:CameraStatus (str, RO)")
    print("  - EXP:Seq:ShotInterval (float, R/W)")
    print("-----------------------------------------------------------------")
    
    daq_ioc, diag_ioc = create_ioc(prefix="EXP:Seq:")
    # Run both PVGroups together
    run({**daq_ioc.pvdb, **diag_ioc.pvdb}, startup_hook=None)

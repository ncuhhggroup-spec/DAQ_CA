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
                await self.State.write(value="ERROR")
            finally:
                # Reset Arm PV back to 0
                await self.Arm.write(value=0)


def create_ioc(
    prefix: str = "EXP:Seq:",
    controller: Optional[SequenceController] = None,
) -> DAQIOC:
    """Factory creating DAQIOC instance with custom PV prefix."""
    return DAQIOC(prefix=prefix, controller=controller)


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
    print("-----------------------------------------------------------------")
    
    ioc = create_ioc(prefix="EXP:Seq:")
    run(ioc.pvdb, startup_hook=None)

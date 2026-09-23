"""
tests/test_ioc_server.py
Unit and integration test for ca_server/ioc_server.py EPICS IOC.
Validates:
1. 5 Core PV definitions (ShotTarget, Arm, State, FileName, Note) and types
2. PV write updates: ShotTarget, FileName, Note
3. Asynchronous sequence trigger via Arm PV and non-blocking execution
4. Interlock rejection handling through EPICS IOC
"""

import sys
import pathlib
import pytest
import asyncio

# Ensure project root is in path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from ca_server.ioc_server import DAQIOC, create_ioc
from core.data_manager import DataManager
from core.sequence_controller import SequenceController, SystemState
from drivers.mock_stage_driver import MockStageDriver
from drivers.mock_camera_gui import MockCameraGUI
from drivers.mock_dg645_driver import MockDG645Driver


@pytest.mark.asyncio
async def test_ioc_pv_structure():
    """Verify all 5 required PVs exist and have correct types and initial values."""
    ioc = create_ioc(prefix="TEST:Seq:")
    
    assert "TEST:Seq:ShotTarget" in ioc.pvdb
    assert "TEST:Seq:Arm" in ioc.pvdb
    assert "TEST:Seq:State" in ioc.pvdb
    assert "TEST:Seq:FileName" in ioc.pvdb
    assert "TEST:Seq:Note" in ioc.pvdb

    # Verify initial values
    assert ioc.ShotTarget.value == 1
    assert ioc.Arm.value == 0
    assert ioc.State.value == "IDLE"
    assert ioc.FileName.value == "exp_run"
    assert ioc.Note.value == ""


@pytest.mark.asyncio
async def test_ioc_parameter_configuration():
    """Verify write operations to configuration PVs propagate to SequenceController."""
    ioc = create_ioc(prefix="TEST:Seq:")
    
    # Update ShotTarget
    await ioc.ShotTarget.write(10)
    assert ioc.ShotTarget.value == 10
    assert ioc.controller.shot_target == 10

    # Update FileName
    await ioc.FileName.write("run_scan_01")
    assert ioc.FileName.value == "run_scan_01"
    assert ioc.controller.file_name == "run_scan_01"

    # Update Note
    await ioc.Note.write("Testing 10-shot run via EPICS")
    assert ioc.Note.value == "Testing 10-shot run via EPICS"
    assert ioc.controller.note == "Testing 10-shot run via EPICS"


@pytest.mark.asyncio
async def test_ioc_arm_and_execution():
    """Verify writing 1 to Arm launches sequence asynchronously and completes."""
    stage = MockStageDriver()
    cam = MockCameraGUI(width=256, height=256)
    dg645 = MockDG645Driver()
    dm = DataManager()
    ctrl = SequenceController(stage=stage, cam=cam, data_mgr=dm, dg645=dg645)

    ioc = DAQIOC(prefix="TEST:Seq:", controller=ctrl)
    await ioc.ShotTarget.write(3)
    await ioc.FileName.write("test_epics_arm")

    # Trigger arm
    await ioc.Arm.write(1)
    
    # Await background sequence completion
    await asyncio.sleep(0.5)

    # Verify State is IDLE and Arm auto-reset to 0
    assert ioc.State.value == "IDLE"
    assert ioc.Arm.value == 0
    assert dm.buffer is not None
    assert dm.buffer.shape == (3, 256, 256)


@pytest.mark.asyncio
async def test_ioc_interlock_rejection():
    """Verify that if stage is moving, Arm trigger leads to ERROR state without crashing loop."""
    stage = MockStageDriver()
    cam = MockCameraGUI(width=256, height=256)
    dg645 = MockDG645Driver()
    dm = DataManager()
    ctrl = SequenceController(stage=stage, cam=cam, data_mgr=dm, dg645=dg645)

    # Force stage to moving
    stage._moving = True

    ioc = DAQIOC(prefix="TEST:Seq:", controller=ctrl)
    await ioc.Arm.write(1)

    # Await background execution
    await asyncio.sleep(0.3)

    # State must report ERROR
    assert ioc.State.value == "ERROR"
    assert ioc.Arm.value == 0

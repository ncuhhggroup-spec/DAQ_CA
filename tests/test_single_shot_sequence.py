"""
Integration test suite for Local-First Single-Shot / Multi-Shot DAQ Sequence.
Tests:
- Scenario A (1-Shot Run): Buffer creation, HDF5/TIFF export, Excel log appending.
- Scenario B (10-Shot Run): Multi-frame burst handling, shape verification, and reset buffer clearing.
- Scenario C (Interlock Check): Stage moving blocks arming, raises error, state goes to ERROR, no buffer.
"""

import os
import sys
import pathlib
import tempfile
import shutil
from datetime import datetime

import numpy as np
import pytest
import h5py
import tifffile
import pandas as pd

# Add repository root to python path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from core.data_manager import DataManager
from core.sequence_controller import SequenceController, SystemState
from drivers.mock_stage_driver import MockStageDriver
from drivers.mock_dg645_driver import MockDG645Driver
from drivers.mock_camera_gui import MockCameraGUI


@pytest.fixture
def temp_dir():
    dirpath = pathlib.Path(tempfile.mkdtemp())
    yield dirpath
    if dirpath.exists():
        shutil.rmtree(dirpath, ignore_errors=True)


def test_scenario_a_one_shot(temp_dir):
    """
    Scenario A (1-Shot Run):
    - Verify successful execution (arm_and_start -> acquire -> save)
    - Verify zero-copy RAM buffer creation (1, H, W)
    - Verify HDF5 and TIFF export
    - Verify Excel log appending
    """
    stage = MockStageDriver()
    cam = MockCameraGUI(width=512, height=512)
    dg645 = MockDG645Driver()
    data_mgr = DataManager()
    ctrl = SequenceController(stage=stage, cam=cam, data_mgr=data_mgr, dg645=dg645)

    assert ctrl.state == SystemState.IDLE
    assert data_mgr.buffer is None

    # 1. Arm and start 1 shot
    ctrl.arm_and_start(frames=1)
    assert ctrl.state == SystemState.ARMED
    assert cam.is_armed() is True
    assert data_mgr.buffer is not None
    assert data_mgr.buffer.shape == (1, 512, 512)
    assert data_mgr.buffer.dtype == np.float32

    # 2. Acquire
    ctrl.acquire()
    assert ctrl.state == SystemState.SAVING
    assert data_mgr.buffer is not None
    assert np.any(data_mgr.buffer[0] > 0)
    # Check that frame captured matches cam's last frame
    np.testing.assert_array_equal(data_mgr.buffer[0], cam.last_frame)

    # 3. Save
    hdf5_file = temp_dir / "single_shot.h5"
    tiff_file = temp_dir / "single_shot.tif"
    excel_file = temp_dir / "experiment_log.xlsx"

    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "shot_target": 1,
        "note": "Scenario A 1-shot test",
        "stage_x": stage.get_position(1),
    }

    # DataManager appends to excel
    data_mgr.append_experiment_log = lambda entry, log_path=excel_file: DataManager.append_experiment_log(entry, excel_file)
    ctrl.save(hdf5_path=hdf5_file, tiff_path=tiff_file, log_entry=log_entry)

    assert ctrl.state == SystemState.IDLE
    assert cam.is_armed() is False

    # Verify HDF5
    assert hdf5_file.exists()
    with h5py.File(hdf5_file, "r") as hf:
        assert "data" in hf
        assert hf["data"].shape == (1, 512, 512)

    # Verify TIFF
    assert tiff_file.exists()
    saved_tif = tifffile.imread(tiff_file)
    assert saved_tif.shape == (1, 512, 512) or saved_tif.shape == (512, 512)

    # Verify Excel
    assert excel_file.exists()
    df = pd.read_excel(excel_file, sheet_name="Log")
    assert len(df) == 1
    assert df.iloc[0]["shot_target"] == 1
    assert df.iloc[0]["note"] == "Scenario A 1-shot test"

    # Reset
    ctrl.reset()
    assert ctrl.state == SystemState.IDLE
    assert data_mgr.buffer is None


def test_scenario_b_ten_shot_run(temp_dir):
    """
    Scenario B (10-Shot Run):
    - Verify multi-frame burst handling (10, H, W)
    - Verify all frames filled in buffer
    - Verify persistence and buffer clearing upon reset
    """
    stage = MockStageDriver()
    cam = MockCameraGUI(width=256, height=256)
    dg645 = MockDG645Driver()
    data_mgr = DataManager()
    ctrl = SequenceController(stage=stage, cam=cam, data_mgr=data_mgr, dg645=dg645)

    # 1. Arm for 10 frames
    ctrl.arm_and_start(frames=10)
    assert ctrl.state == SystemState.ARMED
    assert data_mgr.buffer.shape == (10, 256, 256)

    # 2. Acquire 10-frame burst
    ctrl.acquire()
    assert ctrl.state == SystemState.SAVING
    assert data_mgr.buffer.shape == (10, 256, 256)
    for i in range(10):
        assert np.max(data_mgr.buffer[i]) > 0

    # 3. Save multi-frame burst
    hdf5_file = temp_dir / "burst_10shot.h5"
    tiff_file = temp_dir / "burst_10shot.tif"
    excel_file = temp_dir / "experiment_log.xlsx"

    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "shot_target": 10,
        "note": "Scenario B 10-shot burst",
        "stage_x": stage.get_position(1),
    }

    data_mgr.append_experiment_log = lambda entry, log_path=excel_file: DataManager.append_experiment_log(entry, excel_file)
    ctrl.save(hdf5_path=hdf5_file, tiff_path=tiff_file, log_entry=log_entry)
    assert ctrl.state == SystemState.IDLE

    # Verify HDF5 has 10 frames
    with h5py.File(hdf5_file, "r") as hf:
        assert hf["data"].shape == (10, 256, 256)

    # Verify TIFF has 10 frames
    saved_tif = tifffile.imread(tiff_file)
    assert saved_tif.shape == (10, 256, 256)

    # Verify buffer clearing on reset
    ctrl.reset()
    assert ctrl.state == SystemState.IDLE
    assert data_mgr.buffer is None


def test_scenario_c_interlock_check():
    """
    Scenario C (Interlock Check):
    - Set stage._moving = True
    - Call arm_and_start()
    - Verify interlock blocks arming, logs error, raises RuntimeError
    - Verify system state is ERROR
    - Verify no RAM buffer was pre-allocated
    - Verify camera remains disarmed
    """
    stage = MockStageDriver()
    cam = MockCameraGUI(width=512, height=512)
    dg645 = MockDG645Driver()
    data_mgr = DataManager()
    ctrl = SequenceController(stage=stage, cam=cam, data_mgr=data_mgr, dg645=dg645)

    # Simulate stage in motion
    stage._moving = True
    assert stage.is_moving() is True

    # Arming must be rejected
    with pytest.raises(RuntimeError, match="Stage is moving"):
        ctrl.arm_and_start(frames=5)

    # Verify system state is ERROR and safe
    assert ctrl.state == SystemState.ERROR
    assert data_mgr.buffer is None
    assert cam.is_armed() is False

    # Verify reset restores to IDLE
    ctrl.reset()
    assert ctrl.state == SystemState.IDLE


if __name__ == "__main__":
    pytest.main(["-v", __file__])

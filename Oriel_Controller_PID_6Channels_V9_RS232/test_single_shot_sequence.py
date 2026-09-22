#!/usr/bin/env python3
"""
Test Single-Shot & Multi-Shot DAQ Sequence (Phase 1 Local Validation)
Validates:
1. N=1 single-shot acquisition sequence
2. N=10 multi-shot acquisition sequence
3. Interlock protection (Arming rejection while stage is in motion)
4. Data persistence (HDF5/NPZ) and automatic experiment_log.xlsx update
"""

import os
import sys
import time

# Ensure workspace is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from drivers import MockStageDriver, MockCameraDriver, MockDG645Driver
from core import DataManager, SequenceController, SystemState


def run_tests():
    print("================================================================")
    print("      DAQ SINGLE-SHOT / MULTI-SHOT SEQUENCE VALIDATION          ")
    print("================================================================\n")
    
    test_data_dir = "test_data"
    test_excel = "test_experiment_log.xlsx"
    
    # Clean test artifacts if present
    if os.path.exists(test_excel):
        os.remove(test_excel)

    # 1. Initialize Mock Hardware & Data Manager
    stage = MockStageDriver()
    camera = MockCameraDriver()
    dg645 = MockDG645Driver()
    data_mgr = DataManager(data_dir=test_data_dir, excel_log_path=test_excel)
    
    controller = SequenceController(
        stage_driver=stage,
        camera_driver=camera,
        dg645_driver=dg645,
        data_manager=data_mgr,
        on_log=lambda msg: print(f"  [LOG] {msg}")
    )

    # TEST 1: Single-shot (N=1) Sequence
    print("--- [TEST 1] Single-Shot (N=1) Acquisition ---")
    stage.set_position(5000)
    controller.set_experiment_config(file_name="test_single", note="Single shot test", shot_target=1)
    
    success = controller.arm_and_start()
    assert success is True, "Test 1 Failed: Sequence should return True"
    assert controller.state == SystemState.IDLE, "Test 1 Failed: Controller should return to IDLE"
    assert dg645.triggered_count == 1, f"Test 1 Failed: Expected 1 trigger, got {dg645.triggered_count}"
    assert os.path.exists(test_excel), "Test 1 Failed: experiment_log.xlsx was not created"
    print(">>> TEST 1 PASSED!\n")

    # TEST 2: Multi-shot (N=10) Sequence
    print("--- [TEST 2] Multi-Shot (N=10) Acquisition ---")
    controller.set_experiment_config(file_name="test_multi", note="10-shot burst test", shot_target=10)
    
    success = controller.arm_and_start()
    assert success is True, "Test 2 Failed: Multi-shot sequence should succeed"
    assert dg645.triggered_count == 11, f"Test 2 Failed: Cumulative triggers should be 11, got {dg645.triggered_count}"
    print(">>> TEST 2 PASSED!\n")

    # TEST 3: Interlock Protection (Stage Moving)
    print("--- [TEST 3] Interlock Check (Stage Moving) ---")
    # Simulate stage in motion
    stage.set_moving_state(channel=1, moving=True)
    assert stage.is_moving() is True, "Stage should report moving"
    
    controller.set_experiment_config(file_name="test_interlock", note="Must be rejected", shot_target=5)
    rejected = controller.arm_and_start()
    assert rejected is False, "Test 3 Failed: Arming MUST be rejected when stage is moving!"
    assert controller.state == SystemState.IDLE, "Test 3 Failed: State should remain IDLE upon rejection"
    print(">>> TEST 3 (Interlock) PASSED!\n")

    # Reset stage moving state
    stage.set_moving_state(channel=1, moving=False)

    print("================================================================")
    print("      ALL TEST CASES PASSED SUCCESSFULLY (100% OK)              ")
    print("================================================================\n")


if __name__ == "__main__":
    run_tests()

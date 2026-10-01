"""
Standalone runner for test_single_shot_sequence.py
Allows running either directly via `python test_single_shot_sequence.py` or via `pytest`.
"""

import sys
import pathlib

# Forward to tests/test_single_shot_sequence.py
from tests.test_single_shot_sequence import (
    test_scenario_a_one_shot,
    test_scenario_b_ten_shot_run,
    test_scenario_c_interlock_check,
    temp_dir
)


def run_standalone():
    print("================================================================")
    print("     RUNNING DAQ INTEGRATION TEST SUITE (STANDALONE)            ")
    print("================================================================\n")
    import tempfile
    import shutil

    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        print("[TEST 1/3] Scenario A (1-Shot Run)...")
        test_scenario_a_one_shot(tmp)
        print(">>> Scenario A (1-Shot) PASSED!\n")

        print("[TEST 2/3] Scenario B (10-Shot Run)...")
        test_scenario_b_ten_shot_run(tmp)
        print(">>> Scenario B (10-Shot) PASSED!\n")

        print("[TEST 3/3] Scenario C (Interlock Check)...")
        test_scenario_c_interlock_check()
        print(">>> Scenario C (Interlock Check) PASSED!\n")

        print("================================================================")
        print("       ALL 3 SCENARIOS PASSED WITH ZERO ERRORS (100% OK)        ")
        print("================================================================\n")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    run_standalone()

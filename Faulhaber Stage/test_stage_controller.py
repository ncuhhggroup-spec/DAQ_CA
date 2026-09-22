"""
test_stage_controller.py - Automated verification tests for unit conversions and PyQt6 components.
"""

import math
import sys
import unittest
from units import StageMode, UnitConverter


class TestUnitConversions(unittest.TestCase):
    def test_linear_stage_conversion(self):
        # 1 count = -0.025 um
        # Position 100.0 um -> Counts = round(100.0 / -0.025) = -4000
        counts = UnitConverter.physical_to_counts(100.0, StageMode.LINEAR)
        self.assertEqual(counts, -4000)

        # Invert: -4000 counts -> -4000 * -0.025 = 100.0 um
        phys = UnitConverter.counts_to_physical(-4000, StageMode.LINEAR)
        self.assertAlmostEqual(phys, 100.0, places=4)

        # Position -25.0 um -> Counts = round(-25.0 / -0.025) = +1000
        counts_neg = UnitConverter.physical_to_counts(-25.0, StageMode.LINEAR)
        self.assertEqual(counts_neg, 1000)

    def test_rotator_conversion(self):
        # 1 count = 5.15611e-5 deg
        # Position 1.0 deg -> Counts = round(1.0 / 5.15611e-5) = 19394
        counts = UnitConverter.physical_to_counts(1.0, StageMode.ROTATOR)
        expected = round(1.0 / 5.15611e-5)
        self.assertEqual(counts, expected)

        phys = UnitConverter.counts_to_physical(counts, StageMode.ROTATOR)
        self.assertAlmostEqual(phys, 1.0, places=3)

    def test_raw_counts_conversion(self):
        counts = UnitConverter.physical_to_counts(12345.0, StageMode.RAW)
        self.assertEqual(counts, 12345)
        phys = UnitConverter.counts_to_physical(12345, StageMode.RAW)
        self.assertEqual(phys, 12345.0)

    def test_format_strings(self):
        s_lin = UnitConverter.format_physical(12.3456, StageMode.LINEAR)
        self.assertEqual(s_lin, "+12.346 µm")

        s_rot = UnitConverter.format_physical(-45.12346, StageMode.ROTATOR)
        self.assertTrue(s_rot.startswith("-45.1235"))

        s_raw = UnitConverter.format_physical(500.0, StageMode.RAW)
        self.assertEqual(s_raw, "+500 cts")


class TestUIInstantiation(unittest.TestCase):
    def test_ui_components(self):
        from PyQt6.QtWidgets import QApplication
        from main_window import MainWindow

        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)

        win = MainWindow()
        self.assertIsNotNone(win)
        self.assertEqual(len(win.node_cards), 3)
        self.assertIn(1, win.node_cards)
        self.assertIn(2, win.node_cards)
        self.assertIn(3, win.node_cards)

        # Check node card methods
        win.node_cards[1].update_position(1000)
        win.node_cards[1].update_power_state(True)
        self.assertTrue(win.node_cards[1].is_enabled)
        win.node_cards[1].update_power_state(False)
        self.assertFalse(win.node_cards[1].is_enabled)


if __name__ == "__main__":
    unittest.main()

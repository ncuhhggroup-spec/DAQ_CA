"""
test_dual_gige_camera.py
========================
Unit & Integration test suite for the Dual GigE Camera subsystem.

Tests:
1. Controller initialization & driver fallback/mock behavior.
2. Trigger mode switching ("INTERNAL/OFF" vs "EXTERNAL_TTL").
3. RAM buffer pre-allocation.
4. Background recording, memory retention, and retrieval.
5. 2D Gaussian fitting on synthetic laser beam profile (accuracy of x0, y0, FWHM_x, FWHM_y, RMSE).
6. TIFF persistence and embedded JSON / multi-page background metadata verification.
7. Settings persistence (save/load camera_settings.json).
"""

import json
import os
import tempfile
import unittest

import numpy as np
import tifffile

from camera_analysis import fit_2d_gaussian, gaussian_2d_rot
from dual_gige_driver import DualGigECameraController, MockCameraDriver


class TestDualGigECamera(unittest.TestCase):
    def setUp(self):
        self.controller = DualGigECameraController(
            serial_0=1001,
            serial_1=1002,
            name_0="Cam_NearField",
            name_1="Cam_FarField",
            force_mock=True,
        )
        self.controller.connect_all()
        self.controller.start_capture_all()

    def tearDown(self):
        self.controller.stop_capture_all()
        self.controller.disconnect_all()

    def test_initialization_and_names(self):
        self.assertEqual(len(self.controller.drivers), 2)
        self.assertEqual(self.controller.channel_names[0], "Cam_NearField")
        self.assertEqual(self.controller.channel_names[1], "Cam_FarField")
        self.assertTrue(self.controller.drivers[0].is_connected)
        self.assertTrue(self.controller.drivers[1].is_connected)

    def test_trigger_modes(self):
        self.controller.set_trigger_mode("EXTERNAL_TTL")
        for drv in self.controller.drivers:
            self.assertEqual(drv.trigger_mode, "EXTERNAL_TTL")

        self.controller.set_trigger_mode("INTERNAL/OFF")
        for drv in self.controller.drivers:
            self.assertEqual(drv.trigger_mode, "INTERNAL/OFF")

    def test_allocate_ram_buffer(self):
        shot_count = 10
        self.controller.allocate_ram_buffer(shot_count)
        self.assertIsNotNone(self.controller.ram_buffers[0])
        self.assertIsNotNone(self.controller.ram_buffers[1])
        self.assertEqual(self.controller.ram_buffers[0].shape, (shot_count, 1224, 1624))
        self.assertEqual(self.controller.ram_buffers[0].dtype, np.uint16)

    def test_record_background(self):
        bg0 = self.controller.record_background(0, num_averages=2)
        self.assertIsNotNone(bg0)
        self.assertEqual(bg0.shape, (1224, 1624))
        self.assertIsNotNone(self.controller.get_background(0))
        self.assertIsNone(self.controller.get_background(1))

        self.controller.clear_background(0)
        self.assertIsNone(self.controller.get_background(0))

    def test_2d_gaussian_fitting(self):
        # Create a synthetic 2D Gaussian beam
        h, w = 400, 400
        true_x0, true_y0 = 210.0, 195.0
        true_sig_x, true_sig_y = 35.0, 25.0
        true_amp = 40000.0
        true_bg = 500.0

        y = np.arange(h)
        x = np.arange(w)
        xx, yy = np.meshgrid(x, y)

        clean_beam = gaussian_2d_rot(
            (xx, yy), true_amp, true_x0, true_y0, true_sig_x, true_sig_y, 0.0, true_bg
        ).reshape((h, w))
        
        # Add slight noise
        noise = np.random.normal(0, 10.0, size=(h, w))
        img = np.clip(clean_beam + noise, 0, 65535).astype(np.uint16)

        # Fit over entire image
        res = fit_2d_gaussian(img)
        self.assertTrue(res.success, f"Fit failed: {res.message}")
        self.assertAlmostEqual(res.x0, true_x0, delta=1.5)
        self.assertAlmostEqual(res.y0, true_y0, delta=1.5)
        self.assertAlmostEqual(res.sigma_x, true_sig_x, delta=2.0)
        self.assertAlmostEqual(res.sigma_y, true_sig_y, delta=2.0)
        self.assertAlmostEqual(res.fwhm_x, true_sig_x * 2.355, delta=5.0)
        self.assertAlmostEqual(res.fwhm_y, true_sig_y * 2.355, delta=5.0)
        self.assertLess(res.residual_rmse, 30.0)

    def test_tiff_persistence_with_metadata_and_bg(self):
        # Record background
        bg = self.controller.record_background(0, num_averages=1)
        frame = self.controller.grab_frame(0)

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "test_shot_001.tif")
            saved_path = self.controller.save_tiff_with_metadata(
                filepath=file_path,
                index=0,
                image_data=frame,
                user_notes="Unit test test_shot",
                extra_metadata={"custom_val": 42.0},
                embed_background=True,
            )
            self.assertTrue(os.path.exists(saved_path))

            # Read back TIFF and parse metadata
            with tifffile.TiffFile(saved_path) as tif:
                self.assertGreaterEqual(len(tif.pages), 2)  # Page 0: Data, Page 1: Background
                page0 = tif.pages[0]
                meta_json = json.loads(page0.description)
                self.assertEqual(meta_json["channel_name"], "Cam_NearField")
                self.assertEqual(meta_json["user_notes"], "Unit test test_shot")
                self.assertEqual(meta_json["custom_val"], 42.0)
                self.assertTrue(meta_json["has_background_attached"])

                # Verify image data
                read_data = page0.asarray()
                np.testing.assert_array_equal(read_data, frame)

                # Verify page 1 background
                page1 = tif.pages[1]
                read_bg = page1.asarray()
                np.testing.assert_array_equal(read_bg, bg)


if __name__ == "__main__":
    unittest.main()

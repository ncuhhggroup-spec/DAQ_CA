"""
dual_gige_driver.py
===================
Single GigE Camera Driver & Controller for Point Grey / FLIR Grasshopper2 camera (Cam 0).
Supports ctypes (FlyCapture2_C.dll), PyCapture2, and Mock fallback mode for offline DAQ development.

Features:
- SingleGigECameraController managing Cam 0 exclusively.
- Unified trigger mode management (INTERNAL/OFF vs EXTERNAL_TTL).
- Snapshot background assignment and RAM buffer pre-allocation.
- TIFF persistence with embedded metadata tags (ImageDescription JSON + background data).
- Backward-compatible class alias for DualGigECameraController.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import tifffile

try:
    from pg_camera_driver import Grasshopper2Driver, FC2_ERROR_OK
except ImportError:
    Grasshopper2Driver = None

logger = logging.getLogger(__name__)


class MockCameraDriver:
    """Mock camera driver for testing and offline development."""
    
    SENSOR_WIDTH = 1624
    SENSOR_HEIGHT = 1224
    DEFAULT_EXPOSURE_S = 0.1
    DEFAULT_FPS = 10.0
    DEFAULT_GAIN_DB = 0.0

    def __init__(self, serial: int = 0, name: str = "Cam_0"):
        self.serial = serial
        self.name = name
        self.is_connected = False
        self.is_capturing = False
        self.exposure_s = self.DEFAULT_EXPOSURE_S
        self.fps = self.DEFAULT_FPS
        self.gain_db = self.DEFAULT_GAIN_DB
        self.trigger_mode = "INTERNAL/OFF"
        self._frame_count = 0
        self._beam_x = 812.0
        self._beam_y = 612.0
        self._beam_sigma_x = 45.0
        self._beam_sigma_y = 35.0

    @property
    def is_mock(self) -> bool:
        return True

    def connect(self) -> None:
        self.is_connected = True
        logger.info("[MockCamera:%s] Connected (S/N: %d)", self.name, self.serial)

    def disconnect(self) -> None:
        self.is_capturing = False
        self.is_connected = False
        logger.info("[MockCamera:%s] Disconnected", self.name)

    def start_capture(self) -> None:
        if not self.is_connected:
            raise RuntimeError("Camera not connected.")
        self.is_capturing = True
        logger.info("[MockCamera:%s] Capture started", self.name)

    def stop_capture(self) -> None:
        self.is_capturing = False
        logger.info("[MockCamera:%s] Capture stopped", self.name)

    def set_exposure_time(self, seconds: float) -> None:
        self.exposure_s = float(seconds)

    def set_gain(self, gain_db: float) -> None:
        self.gain_db = float(gain_db)

    def set_frame_rate(self, fps: float) -> None:
        self.fps = float(fps)

    def set_trigger_mode(self, enabled: bool, source: int = 0, mode: int = 0, polarity: int = 1) -> None:
        self.trigger_mode = "EXTERNAL_TTL" if enabled else "INTERNAL/OFF"
        logger.debug("[MockCamera:%s] Trigger mode set to %s", self.name, self.trigger_mode)

    def grab_frame_numpy(self) -> np.ndarray:
        if not self.is_capturing:
            raise RuntimeError("Camera is not capturing. Call start_capture() first.")
        
        self._frame_count += 1
        
        y = np.arange(self.SENSOR_HEIGHT, dtype=np.float32)
        x = np.arange(self.SENSOR_WIDTH, dtype=np.float32)
        yy, xx = np.meshgrid(y, x, indexing='ij')
        
        drift_x = 5.0 * np.sin(self._frame_count * 0.1)
        drift_y = 4.0 * np.cos(self._frame_count * 0.1)
        
        cx = self._beam_x + drift_x
        cy = self._beam_y + drift_y
        
        amp = 45000.0 * (1.0 + self.gain_db / 24.0) * (self.exposure_s / 0.1)
        amp = min(amp, 62000.0)
        
        beam = amp * np.exp(-(((xx - cx) ** 2) / (2 * self._beam_sigma_x ** 2) + 
                              ((yy - cy) ** 2) / (2 * self._beam_sigma_y ** 2)))
        
        bg = 600.0 + np.random.normal(0, 25.0, size=(self.SENSOR_HEIGHT, self.SENSOR_WIDTH))
        noise = np.random.normal(0, 15.0, size=(self.SENSOR_HEIGHT, self.SENSOR_WIDTH))
        
        img = np.clip(beam + bg + noise, 0, 65535).astype(np.uint16)
        return img

    def get_camera_info(self) -> dict:
        return {
            "serial": self.serial,
            "model": f"Mock Grasshopper2 ({self.name})",
            "firmware": "v1.0.0-mock",
        }

    def get_camera_status_info(self) -> dict:
        """Return simulated hardware status parameters."""
        return {
            "exposure_ms": self.exposure_s * 1000.0,
            "frame_rate_fps": self.fps,
            "gain_db": self.gain_db,
            "ip_address": "192.168.1.100 (Mock)",
            "pixel_format": "MONO16 (Mock)",
        }


class SingleGigECameraController:
    """
    High-level controller managing a single Point Grey GigE Camera (Cam 0).
    Provides unified trigger control, background persistence, and metadata-tagged TIFF output.
    """

    def __init__(
        self,
        serial_0: int = 0,
        serial_1: int = 0,
        name_0: str = "Cam_0",
        name_1: str = "Disabled",
        force_mock: bool = False,
    ):
        self.channel_names = [name_0]
        self.serials = [serial_0]
        self.force_mock = force_mock
        
        self.drivers: List[Union[Grasshopper2Driver, MockCameraDriver]] = []
        self.background_buffers: List[Optional[np.ndarray]] = [None]
        self.ram_buffers: List[Optional[np.ndarray]] = [None]
        self.user_notes: str = ""
        self._init_driver()

    @property
    def is_mock(self) -> bool:
        if self.drivers and hasattr(self.drivers[0], 'is_mock'):
            return self.drivers[0].is_mock
        return False

    def _init_driver(self) -> None:
        self.drivers = []
        serial = self.serials[0]
        name = self.channel_names[0]
        
        if not self.force_mock and Grasshopper2Driver is not None:
            try:
                drv = Grasshopper2Driver(serial=serial, auto_detect=(serial == 0))
                self.drivers.append(drv)
                return
            except Exception as e:
                logger.warning("Failed to initialize physical camera driver Cam 0: %s. Using Mock.", e)
        
        self.drivers.append(MockCameraDriver(serial=serial, name=name))

    def connect_all(self) -> Tuple[bool, bool]:
        drv = self.drivers[0]
        c0 = False
        try:
            drv.connect()
            c0 = True
        except Exception as e:
            logger.error("Error connecting camera 0 (%s): %s", self.channel_names[0], e)
            if not isinstance(drv, MockCameraDriver):
                logger.info("Switching camera 0 to Mock driver.")
                mock_drv = MockCameraDriver(serial=self.serials[0], name=self.channel_names[0])
                mock_drv.connect()
                self.drivers[0] = mock_drv
                c0 = True
        return (c0, False)

    def disconnect_all(self) -> None:
        for drv in self.drivers:
            try:
                if getattr(drv, "is_capturing", False):
                    drv.stop_capture()
                if getattr(drv, "is_connected", False):
                    drv.disconnect()
            except Exception as e:
                logger.error("Error disconnecting camera: %s", e)

    def start_capture_all(self) -> None:
        for drv in self.drivers:
            if getattr(drv, "is_connected", False) and not getattr(drv, "is_capturing", False):
                drv.start_capture()

    def stop_capture_all(self) -> None:
        for drv in self.drivers:
            if getattr(drv, "is_capturing", False):
                drv.stop_capture()

    def set_channel_name(self, index: int, name: str) -> None:
        self.channel_names[0] = name
        if isinstance(self.drivers[0], MockCameraDriver):
            self.drivers[0].name = name

    def set_exposure_time(self, index: int, seconds: float) -> None:
        if self.drivers:
            self.drivers[0].set_exposure_time(seconds)

    def set_gain(self, index: int, gain_db: float) -> None:
        if self.drivers:
            self.drivers[0].set_gain(gain_db)

    def set_trigger_mode(self, mode: str) -> None:
        enabled = (mode.upper() == "EXTERNAL_TTL")
        if self.drivers and getattr(self.drivers[0], "is_connected", False):
            self.drivers[0].set_trigger_mode(enabled=enabled)
        logger.info("GigECameraController trigger mode set to: %s", mode)

    def allocate_ram_buffer(self, shot_count: int) -> None:
        if shot_count <= 0:
            raise ValueError("shot_count must be positive.")
        
        h, w = 1224, 1624
        self.ram_buffers = [np.zeros((shot_count, h, w), dtype=np.uint16)]
        logger.info("Allocated RAM buffer for %d shots (shape: %s).", shot_count, self.ram_buffers[0].shape)

    def set_background(self, index: int = 0, bg_frame: Optional[np.ndarray] = None) -> None:
        """Assign an existing image array directly as background without re-acquisition."""
        if bg_frame is not None:
            self.background_buffers[0] = bg_frame.copy()
            logger.info("Camera 0 (%s) background set from snapshot (mean: %.1f).", self.channel_names[0], float(np.mean(bg_frame)))

    def record_background(self, index: int = 0, num_averages: int = 1) -> np.ndarray:
        drv = self.drivers[0]
        if not getattr(drv, "is_capturing", False):
            raise RuntimeError("Camera 0 is not capturing.")
        
        frames = []
        for _ in range(max(1, num_averages)):
            frames.append(drv.grab_frame_numpy().astype(np.float32))
            if num_averages > 1:
                time.sleep(0.02)
        
        avg_bg = np.mean(frames, axis=0).astype(np.uint16)
        self.background_buffers[0] = avg_bg
        logger.info("Camera 0 (%s) background recorded (mean: %.1f).", self.channel_names[0], float(np.mean(avg_bg)))
        return avg_bg

    def get_background(self, index: int = 0) -> Optional[np.ndarray]:
        return self.background_buffers[0]

    def clear_background(self, index: int = 0) -> None:
        self.background_buffers[0] = None

    def get_actual_status(self, index: int = 0) -> dict:
        """Query physical driver for actual hardware values."""
        drv = self.drivers[0]
        if hasattr(drv, "get_camera_status_info"):
            return drv.get_camera_status_info()
        return {
            "exposure_ms": 0.0,
            "frame_rate_fps": 0.0,
            "gain_db": 0.0,
            "ip_address": "0.0.0.0",
            "pixel_format": "N/A",
        }

    def grab_frame(self, index: int = 0) -> np.ndarray:
        return self.drivers[0].grab_frame_numpy()

    def get_latest_frames(self) -> Tuple[Optional[np.ndarray], None]:
        try:
            f0 = self.grab_frame(0)
            return (f0, None)
        except Exception:
            return (None, None)

    def save_tiff_with_metadata(
        self,
        filepath: str,
        index: int = 0,
        image_data: Optional[np.ndarray] = None,
        user_notes: str = "",
        extra_metadata: Optional[dict] = None,
        embed_background: bool = True,
    ) -> str:
        drv = self.drivers[0]
        exposure_s = getattr(drv, "exposure_s", getattr(drv, "DEFAULT_EXPOSURE_S", 0.1))
        gain_db = getattr(drv, "gain_db", getattr(drv, "DEFAULT_GAIN_DB", 0.0))
        
        if image_data is None:
            image_data = self.grab_frame(0)

        meta = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp_epoch": time.time(),
            "channel_name": self.channel_names[0],
            "camera_index": 0,
            "camera_serial": self.serials[0],
            "exposure_seconds": exposure_s,
            "gain_db": gain_db,
            "user_notes": user_notes or self.user_notes,
            "image_shape": list(image_data.shape),
            "dtype": str(image_data.dtype),
            "has_background_attached": (self.background_buffers[0] is not None) and embed_background,
        }
        
        if extra_metadata:
            meta.update(extra_metadata)
            
        json_meta = json.dumps(meta, indent=2)
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        
        bg = self.background_buffers[0]
        if embed_background and bg is not None:
            with tifffile.TiffWriter(filepath, bigtiff=False) as tif:
                tif.write(
                    image_data,
                    description=json_meta,
                    metadata={"Channel": self.channel_names[0], "Type": "RawData"},
                )
                bg_meta = json.dumps({
                    "type": "RawBackground",
                    "channel_name": self.channel_names[0],
                    "mean_intensity": float(np.mean(bg)),
                })
                tif.write(
                    bg,
                    description=bg_meta,
                    metadata={"Channel": self.channel_names[0], "Type": "Background"},
                )
        else:
            tifffile.imwrite(
                filepath,
                image_data,
                description=json_meta,
                metadata={"Channel": self.channel_names[0]},
            )
            
        logger.info("TIFF saved with metadata to %s", filepath)
        return os.path.abspath(filepath)


DualGigECameraController = SingleGigECameraController
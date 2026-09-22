"""
dual_gige_driver.py
===================
Dual GigE Camera Driver & Controller for Point Grey / FLIR Grasshopper2 cameras.
Supports ctypes (FlyCapture2_C.dll), PyCapture2, and Mock fallback mode for offline DAQ development.

Features:
- DualGigECameraController managing Cam_NearField and Cam_FarField (customizable names).
- RAM Buffer pre-allocation for high-speed TTL triggered burst acquisition.
- Trigger mode management (INTERNAL/OFF vs EXTERNAL_TTL).
- Background capture and memory persistence.
- TIFF persistence with embedded metadata tags (ImageDescription JSON + background data).
- Ready for integration with SequenceController and EPICS Channel Access (CA).

Author : Antigravity DAQ Module
Date   : 2026-09-22
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import tifffile

# Import base Grasshopper2Driver if available
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

    def __init__(self, serial: int = 0, name: str = "MockCam"):
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
        
        # Synthesize realistic beam image with noise
        y = np.arange(self.SENSOR_HEIGHT, dtype=np.float32)
        x = np.arange(self.SENSOR_WIDTH, dtype=np.float32)
        yy, xx = np.meshgrid(y, x, indexing='ij')
        
        # Small drift to simulate live beam
        drift_x = 5.0 * np.sin(self._frame_count * 0.1)
        drift_y = 4.0 * np.cos(self._frame_count * 0.1)
        
        cx = self._beam_x + drift_x
        cy = self._beam_y + drift_y
        
        # 2D Gaussian beam
        amp = 45000.0 * (1.0 + self.gain_db / 24.0) * (self.exposure_s / 0.1)
        amp = min(amp, 62000.0)
        
        beam = amp * np.exp(-(((xx - cx) ** 2) / (2 * self._beam_sigma_x ** 2) + 
                              ((yy - cy) ** 2) / (2 * self._beam_sigma_y ** 2)))
        
        # Background baseline + Poisson / Gaussian noise
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


class DualGigECameraController:
    """
    High-level controller managing two GigE Cameras (e.g. Near Field & Far Field).
    Provides unified trigger control, RAM buffer pre-allocation, background persistence,
    and metadata-tagged TIFF output.
    """

    def __init__(
        self,
        serial_0: int = 0,
        serial_1: int = 1,
        name_0: str = "Cam_NearField",
        name_1: str = "Cam_FarField",
        force_mock: bool = False,
    ):
        self.channel_names = [name_0, name_1]
        self.serials = [serial_0, serial_1]
        self.force_mock = force_mock
        
        self.drivers: List[Union[Grasshopper2Driver, MockCameraDriver]] = []
        self.background_buffers: List[Optional[np.ndarray]] = [None, None]
        self.ram_buffers: List[Optional[np.ndarray]] = [None, None]
        self.user_notes: str = ""
        self._init_drivers()

    def _init_drivers(self) -> None:
        """Initialize both camera drivers with real hardware or fallback mock."""
        self.drivers = []
        for idx in range(2):
            serial = self.serials[idx]
            name = self.channel_names[idx]
            
            if not self.force_mock and Grasshopper2Driver is not None:
                try:
                    drv = Grasshopper2Driver(serial=serial, auto_detect=(serial == 0))
                    self.drivers.append(drv)
                    continue
                except Exception as e:
                    logger.warning("Failed to initialize physical camera driver %d: %s. Using Mock.", idx, e)
            
            # Fallback to Mock driver
            self.drivers.append(MockCameraDriver(serial=serial, name=name))

    def connect_all(self) -> Tuple[bool, bool]:
        """Connect both cameras. Returns tuple of booleans (connected_0, connected_1)."""
        results = []
        for i, drv in enumerate(self.drivers):
            try:
                drv.connect()
                results.append(True)
            except Exception as e:
                logger.error("Error connecting camera %d (%s): %s", i, self.channel_names[i], e)
                # If physical connection failed, switch to mock and connect
                if not isinstance(drv, MockCameraDriver):
                    logger.info("Switching camera %d to Mock driver.", i)
                    mock_drv = MockCameraDriver(serial=self.serials[i], name=self.channel_names[i])
                    mock_drv.connect()
                    self.drivers[i] = mock_drv
                    results.append(True)
                else:
                    results.append(False)
        return (results[0], results[1])

    def disconnect_all(self) -> None:
        """Disconnect both cameras."""
        for drv in self.drivers:
            try:
                if getattr(drv, "is_capturing", False):
                    drv.stop_capture()
                if getattr(drv, "is_connected", False):
                    drv.disconnect()
            except Exception as e:
                logger.error("Error disconnecting camera: %s", e)

    def start_capture_all(self) -> None:
        """Start acquisition on both cameras."""
        for drv in self.drivers:
            if getattr(drv, "is_connected", False) and not getattr(drv, "is_capturing", False):
                drv.start_capture()

    def stop_capture_all(self) -> None:
        """Stop acquisition on both cameras."""
        for drv in self.drivers:
            if getattr(drv, "is_capturing", False):
                drv.stop_capture()

    def set_channel_name(self, index: int, name: str) -> None:
        """Update channel name for camera 0 or 1."""
        if index in (0, 1):
            self.channel_names[index] = name
            if isinstance(self.drivers[index], MockCameraDriver):
                self.drivers[index].name = name

    def set_exposure_time(self, index: int, seconds: float) -> None:
        """Set exposure time in seconds for camera index (0 or 1)."""
        if 0 <= index < len(self.drivers):
            self.drivers[index].set_exposure_time(seconds)

    def set_gain(self, index: int, gain_db: float) -> None:
        """Set gain in dB for camera index (0 or 1)."""
        if 0 <= index < len(self.drivers):
            self.drivers[index].set_gain(gain_db)

    def set_trigger_mode(self, mode: str) -> None:
        """
        Unified trigger mode setting for SequenceController integration.
        
        Parameters
        ----------
        mode : "EXTERNAL_TTL" or "INTERNAL/OFF"
        """
        enabled = (mode.upper() == "EXTERNAL_TTL")
        for drv in self.drivers:
            if getattr(drv, "is_connected", False):
                drv.set_trigger_mode(enabled=enabled)
        logger.info("DualGigECameraController trigger mode set to: %s", mode)

    def allocate_ram_buffer(self, shot_count: int) -> None:
        """
        Pre-allocate zero-copy RAM buffers (shape: [N, H, W], dtype: uint16) for both cameras.
        Used by SequenceController prior to firing TTL bursts.
        """
        if shot_count <= 0:
            raise ValueError("shot_count must be positive.")
        
        h, w = 1224, 1624
        self.ram_buffers = [
            np.zeros((shot_count, h, w), dtype=np.uint16),
            np.zeros((shot_count, h, w), dtype=np.uint16),
        ]
        logger.info("Allocated RAM buffers for %d shots (shape: %s, ~%.2f MB total).",
                    shot_count, self.ram_buffers[0].shape, 2 * shot_count * h * w * 2 / (1024 * 1024))

    def record_background(self, index: int, num_averages: int = 1) -> np.ndarray:
        """
        Capture raw background frame (or average of multiple frames) and hold in memory.
        
        Parameters
        ----------
        index : Camera index (0 or 1).
        num_averages : Number of frames to average for clean background.
        
        Returns
        -------
        np.ndarray : Raw background array (uint16).
        """
        if index not in (0, 1):
            raise IndexError("Camera index must be 0 or 1.")
        
        drv = self.drivers[index]
        if not getattr(drv, "is_capturing", False):
            raise RuntimeError(f"Camera {index} is not capturing.")
        
        frames = []
        for _ in range(max(1, num_averages)):
            frames.append(drv.grab_frame_numpy().astype(np.float32))
            if num_averages > 1:
                time.sleep(0.02)
        
        avg_bg = np.mean(frames, axis=0).astype(np.uint16)
        self.background_buffers[index] = avg_bg
        logger.info("Camera %d (%s) background recorded (shape: %s, mean: %.1f).",
                    index, self.channel_names[index], avg_bg.shape, float(np.mean(avg_bg)))
        return avg_bg

    def get_background(self, index: int) -> Optional[np.ndarray]:
        """Get stored background array for camera index."""
        if index in (0, 1):
            return self.background_buffers[index]
        return None

    def clear_background(self, index: int) -> None:
        """Clear recorded background array for camera index."""
        if index in (0, 1):
            self.background_buffers[index] = None

    def grab_frame(self, index: int) -> np.ndarray:
        """Grab a single raw frame from camera index."""
        if index not in (0, 1):
            raise IndexError("Camera index must be 0 or 1.")
        return self.drivers[index].grab_frame_numpy()

    def save_tiff_with_metadata(
        self,
        filepath: str,
        index: int,
        image_data: np.ndarray,
        user_notes: str = "",
        extra_metadata: Optional[dict] = None,
        embed_background: bool = True,
    ) -> str:
        """
        Save single shot or series array to a TIFF file with rich metadata embedded
        in the TIFF ImageDescription tag, including background reference.
        
        Parameters
        ----------
        filepath : Destination file path (.tif or .tiff).
        index : Camera index (0 or 1).
        image_data : 2D or 3D numpy array (uint16).
        user_notes : Optional user text annotation.
        extra_metadata : Optional dictionary of extra experiment parameters.
        embed_background : If True and background exists, embeds background as additional page or tag.
        
        Returns
        -------
        str : Absolute path of saved file.
        """
        drv = self.drivers[index]
        exposure_s = getattr(drv, "exposure_s", getattr(drv, "DEFAULT_EXPOSURE_S", 0.1))
        gain_db = getattr(drv, "gain_db", getattr(drv, "DEFAULT_GAIN_DB", 0.0))
        
        # Build comprehensive metadata dict
        meta = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp_epoch": time.time(),
            "channel_name": self.channel_names[index],
            "camera_index": index,
            "camera_serial": self.serials[index],
            "exposure_seconds": exposure_s,
            "gain_db": gain_db,
            "user_notes": user_notes or self.user_notes,
            "image_shape": list(image_data.shape),
            "dtype": str(image_data.dtype),
            "has_background_attached": (self.background_buffers[index] is not None) and embed_background,
        }
        
        if extra_metadata:
            meta.update(extra_metadata)
            
        json_meta = json.dumps(meta, indent=2)
        
        # Prepare data for saving
        # If embed_background is True and background exists, save as multi-page TIFF:
        # Page 0: Raw beam image(s)
        # Page 1: Raw background image
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        
        bg = self.background_buffers[index]
        if embed_background and bg is not None:
            with tifffile.TiffWriter(filepath, bigtiff=False) as tif:
                tif.write(
                    image_data,
                    description=json_meta,
                    metadata={"Channel": self.channel_names[index], "Type": "RawData"},
                )
                bg_meta = json.dumps({
                    "type": "RawBackground",
                    "channel_name": self.channel_names[index],
                    "mean_intensity": float(np.mean(bg)),
                })
                tif.write(
                    bg,
                    description=bg_meta,
                    metadata={"Channel": self.channel_names[index], "Type": "Background"},
                )
        else:
            tifffile.imwrite(
                filepath,
                image_data,
                description=json_meta,
                metadata={"Channel": self.channel_names[index]},
            )
            
        logger.info("TIFF saved with metadata to %s", filepath)
        return os.path.abspath(filepath)

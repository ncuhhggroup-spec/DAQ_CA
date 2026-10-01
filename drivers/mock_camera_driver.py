# drivers/mock_camera_driver.py
"""
Mock implementation of BaseCameraDriver for GigE cameras.
Provides synthetic beam images with 2D Gaussian profile and noise.
"""

from typing import Any, Tuple, Dict, Optional
import time
import threading
import numpy as np

from .base_driver import BaseCameraDriver


class MockCameraDriver(BaseCameraDriver):
    """Mock GigE camera driver adhering to BaseCameraDriver.
    
    Generates synthetic 2D Gaussian beam frames on demand or during streaming.
    """

    def __init__(self, width: int = 512, height: int = 512, serial: str = "MOCK-GIGE-001"):
        self._width = width
        self._height = height
        self._serial = serial
        self._connected = False
        self._streaming = False
        self._exposure_ms = 20.0
        self._roi = (0, 0, width, height)
        self._lock = threading.Lock()
        self._trigger_mode = "INTERNAL"
        
        # Beam synthetic params
        self._beam_center = (width / 2.0, height / 2.0)
        self._beam_sigma = 35.0
        self._last_frame: Optional[np.ndarray] = None

    def connect(self, *args, **kwargs) -> None:
        with self._lock:
            self._connected = True

    def disconnect(self) -> None:
        with self._lock:
            self._streaming = False
            self._connected = False

    def start_stream(self) -> None:
        if not self._connected:
            raise RuntimeError("Camera not connected")
        with self._lock:
            self._streaming = True

    def stop_stream(self) -> None:
        with self._lock:
            self._streaming = False

    def is_streaming(self) -> bool:
        with self._lock:
            return self._streaming

    def set_roi(self, x: int, y: int, width: int, height: int) -> None:
        with self._lock:
            self._roi = (x, y, width, height)

    def set_exposure(self, exposure_ms: float) -> None:
        with self._lock:
            self._exposure_ms = float(exposure_ms)

    def set_trigger_mode(self, mode: str) -> None:
        with self._lock:
            self._trigger_mode = mode

    def _generate_synthetic_frame(self) -> np.ndarray:
        """Create a synthetic 2D Gaussian beam image with noise."""
        w, h = self._width, self._height
        y, x = np.ogrid[:h, :w]
        cx, cy = self._beam_center
        sigma = self._beam_sigma
        
        # 2D Gaussian
        gaussian = np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * (sigma ** 2)))
        amplitude = 30000.0 * (self._exposure_ms / 20.0)
        noise = np.random.normal(50.0, 5.0, (h, w))
        raw = gaussian * amplitude + noise + 100.0
        frame = np.clip(raw, 0, 65535).astype(np.float32)
        
        # Apply ROI if configured
        rx, ry, rw, rh = self._roi
        if (rw, rh) != (w, h):
            frame = frame[ry : ry + rh, rx : rx + rw]
            
        self._last_frame = frame
        return frame

    def get_frame(self) -> np.ndarray:
        if not self._connected:
            raise RuntimeError("Camera not connected")
        with self._lock:
            return self._generate_synthetic_frame()

    def capture_image(self) -> np.ndarray:
        return self.get_frame()

    def get_metadata(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "serial": self._serial,
                "model": "Mock GigE Grasshopper",
                "width": self._width,
                "height": self._height,
                "exposure_ms": self._exposure_ms,
                "roi": self._roi,
                "trigger_mode": self._trigger_mode,
            }

    @property
    def last_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            return self._last_frame

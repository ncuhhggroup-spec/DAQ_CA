import time
import numpy as np
from typing import Any, Optional
from drivers.base_driver import BaseCameraDriver


class CameraDriver(BaseCameraDriver):
    """Production driver for Scientific Cameras (e.g. Andor SDK or GenICam)."""
    def __init__(self):
        self.connected = False
        self.trigger_mode = "INTERNAL"
        self.exposure_ms = 100.0

    def connect(self, camera_id: int = 0) -> bool:
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.connected = False

    def set_trigger_mode(self, mode: str) -> None:
        self.trigger_mode = mode

    def acquire_frames(self, num_frames: int) -> np.ndarray:
        # Placeholder for real SDK readout
        return np.zeros((num_frames, 512, 512), dtype=np.uint16)


class MockCameraDriver(BaseCameraDriver):
    """Mock Camera driver generating synthetic beam / sensor frames for testing."""
    def __init__(self):
        self.connected = True
        self.trigger_mode = "INTERNAL"
        self.frame_shape = (512, 512)

    def connect(self, camera_id: int = 0) -> bool:
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.connected = False

    def set_trigger_mode(self, mode: str) -> None:
        self.trigger_mode = mode

    def acquire_frames(self, num_frames: int) -> np.ndarray:
        """Generate synthetic gaussian beam spot frames with noise."""
        frames = np.empty((num_frames, self.frame_shape[0], self.frame_shape[1]), dtype=np.uint16)
        y, x = np.ogrid[:self.frame_shape[0], :self.frame_shape[1]]
        center_y, center_x = 256, 256
        sigma = 40.0
        
        # 2D Gaussian profile
        gaussian = np.exp(-((x - center_x)**2 + (y - center_y)**2) / (2 * sigma**2))
        
        for i in range(num_frames):
            noise = np.random.normal(50, 5, self.frame_shape)
            beam = (gaussian * (10000 + np.random.uniform(-500, 500))) + noise
            frames[i] = np.clip(beam, 0, 65535).astype(np.uint16)
            
        time.sleep(0.005 * num_frames)
        return frames

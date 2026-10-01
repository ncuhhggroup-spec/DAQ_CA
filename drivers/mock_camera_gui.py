# drivers/mock_camera_gui.py
"""
MockCameraGUI wrapper providing the interface expected by test suites and SequenceController.
Encapsulates MockCameraDriver to simulate the Dual Camera GUI module.
"""

from typing import Tuple, Dict, Any, Optional
import numpy as np

from .mock_camera_driver import MockCameraDriver


class MockCameraGUI:
    """Mock Dual GigE Camera GUI / Subsystem interface."""

    def __init__(self, width: int = 512, height: int = 512, channel_name: str = "Cam_NearField"):
        self.channel_name = channel_name
        self.driver = MockCameraDriver(width=width, height=height)
        self.driver.connect()
        self._armed = False

    def arm(self) -> None:
        """Arm camera for external trigger."""
        self._armed = True
        self.driver.set_trigger_mode("EXTERNAL_TTL")

    def disarm(self) -> None:
        """Disarm camera and restore internal trigger."""
        self._armed = False
        self.driver.set_trigger_mode("INTERNAL")

    def is_armed(self) -> bool:
        return self._armed

    def get_frame_shape(self) -> Tuple[int, int]:
        """Return (height, width)."""
        return (self.driver._height, self.driver._width)

    def get_frame(self) -> np.ndarray:
        """Grab a frame."""
        return self.driver.get_frame()

    @property
    def last_frame(self) -> Optional[np.ndarray]:
        return self.driver.last_frame

    def get_metadata(self) -> Dict[str, Any]:
        meta = self.driver.get_metadata()
        meta["channel_name"] = self.channel_name
        meta["is_armed"] = self._armed
        return meta

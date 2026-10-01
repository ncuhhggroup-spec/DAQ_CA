# drivers/base_driver.py
"""
Abstract base classes for hardware drivers used in the DAQ_CA project.
Provides a Strategy‑Pattern interface so that real and mock implementations
can be swapped interchangeably.
"""

import abc
from typing import Tuple, Any


class BaseStageDriver(abc.ABC):
    """Abstract interface for a 3‑axis stage controller.

    Concrete drivers must implement methods to move axes, query positions
    and report motion status.
    """

    @abc.abstractmethod
    def connect(self, *args, **kwargs) -> None:
        """Open communication with the hardware (e.g., open serial port)."""

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Close communication safely."""

    @abc.abstractmethod
    def move_to(self, axis: int, position: int) -> None:
        """Move a specific axis to the given position (counts)."""

    @abc.abstractmethod
    def get_position(self, axis: int) -> int:
        """Return the current position of the given axis (counts)."""

    @abc.abstractmethod
    def is_moving(self) -> bool:
        """Return ``True`` if any axis is currently in motion."""

    @abc.abstractmethod
    def stop(self) -> None:
        """Immediately stop all motion."""

    @abc.abstractmethod
    def home(self, axis: int) -> None:
        """Home the specified axis."""

    @abc.abstractmethod
    def get_limits(self, axis: int) -> Tuple[int, int]:
        """Return (min, max) limits for the given axis in counts."""


class BaseDG645Driver(abc.ABC):
    """Abstract interface for a DG645 pulse generator."""

    @abc.abstractmethod
    def connect(self, *args, **kwargs) -> None:
        """Open the connection to the DG645 device."""

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Close the connection safely."""

    @abc.abstractmethod
    def set_delay(self, channel: int, delay_ns: int) -> None:
        """Set delay (in nanoseconds) for a specific output channel."""

    @abc.abstractmethod
    def trigger(self) -> None:
        """Issue a single trigger event."""

    @abc.abstractmethod
    def get_status(self) -> Any:
        """Return a status object or dictionary describing the device state."""


class BaseCameraDriver(abc.ABC):
    """Abstract interface for a GigE camera.

    The driver should provide a continuous stream of frames and utility
    methods for ROI, exposure, and image capture.
    """

    @abc.abstractmethod
    def connect(self, *args, **kwargs) -> None:
        """Open connection to the camera hardware."""

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Terminate the connection and release resources."""

    @abc.abstractmethod
    def start_stream(self) -> None:
        """Begin continuous acquisition of frames."""

    @abc.abstractmethod
    def stop_stream(self) -> None:
        """Stop acquisition."""

    @abc.abstractmethod
    def get_frame(self) -> Any:
        """Return the latest frame as a NumPy array (H × W)."""

    @abc.abstractmethod
    def set_roi(self, x: int, y: int, width: int, height: int) -> None:
        """Configure the region‑of‑interest for acquisition."""

    @abc.abstractmethod
    def set_exposure(self, exposure_ms: float) -> None:
        """Set exposure time in milliseconds."""

    @abc.abstractmethod
    def capture_image(self) -> Any:
        """Capture a single image without affecting the continuous stream."""

    @abc.abstractmethod
    def get_metadata(self) -> dict:
        """Return a dictionary of static metadata (model, serial, etc.)."""

    @abc.abstractmethod
    def is_streaming(self) -> bool:
        """Return ``True`` if the driver is currently streaming frames."""

"""End of base driver definitions."""

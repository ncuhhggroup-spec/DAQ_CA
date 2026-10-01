# drivers/mock_dg645_driver.py
"""
Mock implementation of the DG645 pulse generator.
It simulates delay settings and trigger events without requiring
hardware.
"""

from typing import Any
import time
import threading

from .base_driver import BaseDG645Driver


class MockDG645Driver(BaseDG645Driver):
    """Simple mock that records channel delays and can fire triggers.

    Delays are stored in a dict; `trigger` just sleeps for the maximum
    configured delay to emulate the propagation time.
    """

    def __init__(self):
        self._delays = {}
        self._connected = False
        self._lock = threading.Lock()

    def connect(self, *args, **kwargs) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def set_delay(self, channel: int, delay_ns: int) -> None:
        if not self._connected:
            raise RuntimeError("DG645 not connected")
        with self._lock:
            self._delays[channel] = delay_ns

    def trigger(self) -> None:
        if not self._connected:
            raise RuntimeError("DG645 not connected")
        # Simulate the longest delay as the time the trigger takes.
        max_delay = max(self._delays.values(), default=0)
        # Convert ns to seconds.
        time.sleep(max_delay / 1e9)

    def get_status(self) -> Any:
        with self._lock:
            return {
                "connected": self._connected,
                "delays": dict(self._delays),
            }

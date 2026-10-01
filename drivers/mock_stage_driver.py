# drivers/mock_stage_driver.py
"""
Mock implementation of the stage driver for testing without hardware.
It simulates a three‑axis stage with configurable limits and simple
motion dynamics.
"""

from typing import Tuple
import time
import threading

from .base_driver import BaseStageDriver


class MockStageDriver(BaseStageDriver):
    """A lightweight mock stage that pretends to move instantly.

    The driver maintains an internal position dictionary and a moving flag.
    Motion is simulated with a short sleep to emulate latency.
    """

    def __init__(self, limits: Tuple[Tuple[int, int], Tuple[int, int], Tuple[int, int]] = None):
        # limits per axis: ((min1,max1), (min2,max2), (min3,max3))
        self._limits = limits or ((0, 100000), (0, 100000), (0, 100000))
        self._positions = {1: 0, 2: 0, 3: 0}
        self._moving = False
        self._lock = threading.Lock()

    def connect(self, *args, **kwargs) -> None:
        # No real connection needed.
        pass

    def disconnect(self) -> None:
        # Nothing to clean up.
        pass

    def move_to(self, axis: int, position: int) -> None:
        min_lim, max_lim = self._limits[axis - 1]
        if not (min_lim <= position <= max_lim):
            raise ValueError(f"Target position {position} out of limits {min_lim}-{max_lim} for axis {axis}")
        # Simulate motion delay.
        def _move():
            with self._lock:
                self._moving = True
            time.sleep(0.05)  # 50 ms simulated travel time
            with self._lock:
                self._positions[axis] = position
                self._moving = False
        threading.Thread(target=_move, daemon=True).start()

    def get_position(self, axis: int) -> int:
        with self._lock:
            return self._positions[axis]

    def is_moving(self) -> bool:
        with self._lock:
            return self._moving

    def stop(self) -> None:
        # In mock simply clear moving flag.
        with self._lock:
            self._moving = False

    def home(self, axis: int) -> None:
        # Home to the minimum limit.
        self.move_to(axis, self._limits[axis - 1][0])

    def get_limits(self, axis: int) -> Tuple[int, int]:
        return self._limits[axis - 1]

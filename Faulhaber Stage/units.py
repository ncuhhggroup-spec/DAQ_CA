"""
units.py - Calibration and coordinate conversion module for FAULHABER stage controller.

Handles conversions between user physical units (Linear [µm], Rotator [deg], Raw Counts)
and motor raw encoder counts.
"""

from enum import Enum
from typing import Tuple


class StageMode(Enum):
    LINEAR = "Linear Stage [µm]"
    ROTATOR = "Rotator [deg]"
    RAW = "Raw Counts"


class UnitConverter:
    """
    Unit converter supporting Linear, Rotator, and Raw Counts coordinate modes.

    Specifications:
    - Linear Stage Mode: 1 count = -0.025 µm
        Counts = round(Position_um / -0.025)
        Position_um = Counts * -0.025
    - Rotator Mode: 1 count = 5.15611e-5 deg
        Counts = round(Position_deg / 5.15611e-5)
        Position_deg = Counts * 5.15611e-5
    - Raw Counts Mode: 1:1 direct encoder counts mapping.
    """

    LINEAR_FACTOR = -0.025              # µm per count
    ROTATOR_FACTOR = 5.15611e-5         # deg per count

    @classmethod
    def physical_to_counts(cls, value: float, mode: StageMode) -> int:
        """
        Convert physical unit value to motor encoder counts.
        """
        if mode == StageMode.LINEAR:
            return int(round(value / cls.LINEAR_FACTOR))
        elif mode == StageMode.ROTATOR:
            return int(round(value / cls.ROTATOR_FACTOR))
        elif mode == StageMode.RAW:
            return int(round(value))
        else:
            raise ValueError(f"Unsupported stage mode: {mode}")

    @classmethod
    def counts_to_physical(cls, counts: int, mode: StageMode) -> float:
        """
        Convert motor encoder counts to physical unit value.
        """
        if mode == StageMode.LINEAR:
            return float(counts) * cls.LINEAR_FACTOR
        elif mode == StageMode.ROTATOR:
            return float(counts) * cls.ROTATOR_FACTOR
        elif mode == StageMode.RAW:
            return float(counts)
        else:
            raise ValueError(f"Unsupported stage mode: {mode}")

    @classmethod
    def get_unit_suffix(cls, mode: StageMode) -> str:
        """
        Return the physical unit symbol.
        """
        if mode == StageMode.LINEAR:
            return "µm"
        elif mode == StageMode.ROTATOR:
            return "°"
        elif mode == StageMode.RAW:
            return "cts"
        return ""

    @classmethod
    def format_physical(cls, value: float, mode: StageMode) -> str:
        """
        Format physical value with appropriate decimal precision and unit suffix.
        """
        if mode == StageMode.LINEAR:
            return f"{value:+.3f} µm"
        elif mode == StageMode.ROTATOR:
            return f"{value:+.4f}°"
        elif mode == StageMode.RAW:
            return f"{int(round(value)):+d} cts"
        return f"{value:f}"

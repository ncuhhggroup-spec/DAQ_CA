from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

class BaseStageDriver(ABC):
    """Abstract Base Class for multi-channel stage controllers."""
    
    @abstractmethod
    def connect(self, port: str, baudrate: int = 19200, timeout: float = 0.3) -> bool:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        pass

    @abstractmethod
    def select_channel(self, channel: int) -> None:
        pass

    @abstractmethod
    def get_status(self, channel: Optional[int] = None) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_position(self, channel: Optional[int] = None) -> int:
        pass

    @abstractmethod
    def get_all_positions(self) -> Dict[int, Dict[str, Any]]:
        pass

    @abstractmethod
    def is_moving(self, channel: Optional[int] = None) -> bool:
        pass

    @abstractmethod
    def move_to(self, target_steps: int) -> None:
        pass

    @abstractmethod
    def set_position(self, new_position_steps: int) -> None:
        pass

    @abstractmethod
    def estop(self) -> None:
        pass


class BaseDG645Driver(ABC):
    """Abstract Base Class for SRS DG645 Digital Delay / Pulse Generator."""
    
    @abstractmethod
    def connect(self, resource_name: str) -> bool:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def set_burst_count(self, count: int) -> None:
        pass

    @abstractmethod
    def trigger(self) -> None:
        pass


class BaseCameraDriver(ABC):
    """Abstract Base Class for Scientific Cameras (Andor, etc.)."""
    
    @abstractmethod
    def connect(self, camera_id: int = 0) -> bool:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def set_trigger_mode(self, mode: str) -> None:
        """e.g. 'INTERNAL', 'EXTERNAL_TTL', 'SOFTWARE'"""
        pass

    @abstractmethod
    def acquire_frames(self, num_frames: int) -> Any:
        pass

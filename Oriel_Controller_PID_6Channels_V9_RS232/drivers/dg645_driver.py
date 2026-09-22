import time
from typing import Optional
from drivers.base_driver import BaseDG645Driver


class DG645Driver(BaseDG645Driver):
    """Production driver for SRS DG645 Digital Delay/Pulse Generator via VISA/Serial/Ethernet."""
    def __init__(self):
        self.instrument = None
        self.connected = False
        self.burst_count = 1

    def connect(self, resource_name: str) -> bool:
        # Placeholder for PyVISA or Serial connection
        try:
            # import pyvisa
            # rm = pyvisa.ResourceManager()
            # self.instrument = rm.open_resource(resource_name)
            self.connected = True
            return True
        except Exception:
            self.connected = False
            return False

    def disconnect(self) -> None:
        if self.instrument:
            try:
                self.instrument.close()
            except Exception:
                pass
        self.connected = False

    def set_burst_count(self, count: int) -> None:
        self.burst_count = count
        if self.connected and self.instrument:
            self.instrument.write(f"BURC {count}")

    def trigger(self) -> None:
        if self.connected and self.instrument:
            self.instrument.write("*TRG")


class MockDG645Driver(BaseDG645Driver):
    """Mock driver for DG645 pulse generator."""
    def __init__(self):
        self.connected = True
        self.burst_count = 1
        self.triggered_count = 0

    def connect(self, resource_name: str = "MOCK_DG645") -> bool:
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.connected = False

    def set_burst_count(self, count: int) -> None:
        self.burst_count = count

    def trigger(self) -> None:
        self.triggered_count += self.burst_count
        time.sleep(0.01)  # Simulate hardware trigger propagation delay

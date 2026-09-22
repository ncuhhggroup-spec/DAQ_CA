"""
serial_worker.py - Multi-threaded serial communication worker for FAULHABER MCDC 3002 S RS.

Handles asynchronous serial transmission, priority queuing, routine polling of nodes 1-3,
and thread-safe communication via PyQt6 signals.
"""

import time
import queue
import re
from datetime import datetime
from typing import Optional, Tuple
import serial
from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition


class SerialWorker(QThread):
    """
    Dedicated QThread worker for managing FAULHABER RS232 serial communication.
    
    Features:
    - Priority-based command dispatching (Control/Motion commands > Polling queries).
    - Periodic position polling for Nodes 1, 2, 3 when idle.
    - Asynchronous TX/RX logging with microsecond/millisecond timestamps.
    - Robust disconnection detection and error recovery.
    """

    # Signals to UI
    sig_connected = pyqtSignal(str, int)          # port_name, baudrate
    sig_disconnected = pyqtSignal()
    sig_error = pyqtSignal(str)                   # error message
    sig_log_tx = pyqtSignal(str, str)             # timestamp, text
    sig_log_rx = pyqtSignal(str, str)             # timestamp, text
    sig_position_update = pyqtSignal(int, int)    # node_id (1..3), raw_counts
    sig_power_state = pyqtSignal(int, bool)       # node_id, is_enabled (heuristic/tracked)

    # Priority definitions
    PRIORITY_HIGH = 1   # User motion, enable/disable, homing, manual input
    PRIORITY_POLL = 5   # Background position polling

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial: Optional[serial.Serial] = None
        self._running = False
        self._port_name = ""
        self._baudrate = 9600
        self._poll_interval = 0.200  # 200 ms default polling period
        self._polling_enabled = True

        # Thread synchronization & queue
        # Queue item: (priority, sequence_id, node_id, raw_command, is_query)
        self._queue = queue.PriorityQueue()
        self._seq = 0
        self._mutex = QMutex()
        self._cond = QWaitCondition()

        # Track last known node power state locally
        self._power_states = {1: False, 2: False, 3: False}

    def configure(self, port: str, baudrate: int = 9600, poll_interval: float = 0.200):
        """Configure connection parameters before starting."""
        self._port_name = port
        self._baudrate = baudrate
        self._poll_interval = max(0.05, poll_interval)

    def set_polling_enabled(self, enabled: bool):
        """Enable or disable background status/position polling."""
        self._polling_enabled = enabled

    def send_command(self, node_id: int, cmd: str, priority: int = PRIORITY_HIGH, is_query: bool = False):
        """
        Enqueue a command to be sent to a specific node.
        Example: send_command(1, 'EN') -> transmits '1EN\\r'
        """
        self._mutex.lock()
        self._seq += 1
        seq = self._seq
        self._mutex.unlock()

        # Format full FAULHABER frame: [NodeID][Command]\r
        clean_cmd = cmd.strip()
        if node_id > 0:
            formatted_cmd = f"{node_id}{clean_cmd}\r"
        else:
            formatted_cmd = f"{clean_cmd}\r"

        self._queue.put((priority, seq, node_id, formatted_cmd, is_query))

    def send_raw(self, raw_cmd_str: str, priority: int = PRIORITY_HIGH):
        """Send raw string typed by user in manual console."""
        self._mutex.lock()
        self._seq += 1
        seq = self._seq
        self._mutex.unlock()

        # Ensure CR terminator
        clean = raw_cmd_str.strip("\r\n") + "\r"
        # Determine target node from first char if digit
        node_id = 0
        if len(clean) > 1 and clean[0] in "123":
            node_id = int(clean[0])
        
        is_query = "POS" in clean.upper() or "?" in clean
        self._queue.put((priority, seq, node_id, clean, is_query))

    def stop(self):
        """Signal worker thread to gracefully stop."""
        self._running = False
        self._polling_enabled = False
        self.wait(2000)

    def run(self):
        """Worker main loop running on dedicated background thread."""
        self._running = True
        try:
            # Open serial port (8-N-1, standard FAULHABER RS232 settings)
            self._serial = serial.Serial(
                port=self._port_name,
                baudrate=self._baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.08,  # Short timeout for responsive polling
                write_timeout=0.5
            )
            # Flush existing hardware buffers
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
            self.sig_connected.emit(self._port_name, self._baudrate)
        except Exception as e:
            self.sig_error.emit(f"Failed to open {self._port_name}: {str(e)}")
            self.sig_disconnected.emit()
            return

        last_poll_time = 0.0
        current_poll_node = 1

        while self._running:
            try:
                now = time.time()

                # 1. Enqueue periodic position poll if idle and time interval passed
                if self._polling_enabled and (now - last_poll_time >= self._poll_interval):
                    if self._queue.empty():
                        for nid in (1, 2, 3):
                            self._mutex.lock()
                            self._seq += 1
                            seq = self._seq
                            self._mutex.unlock()
                            self._queue.put((self.PRIORITY_POLL, seq, nid, f"{nid}POS\r", True))
                        last_poll_time = now

                # 2. Check for commands in priority queue
                try:
                    priority, seq, node_id, cmd_frame, is_query = self._queue.get(timeout=0.03)
                except queue.Empty:
                    continue

                # 3. Transmit command frame
                if not self._serial or not self._serial.is_open:
                    break

                ts_tx = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                raw_bytes = cmd_frame.encode("ascii", errors="replace")
                self._serial.write(raw_bytes)
                self._serial.flush()

                # Log TX (omit routine POS polling from spamming logs unless requested)
                is_routine_poll = (priority == self.PRIORITY_POLL and "POS" in cmd_frame)
                if not is_routine_poll:
                    display_tx = cmd_frame.replace("\r", "\\r").replace("\n", "\\n")
                    self.sig_log_tx.emit(ts_tx, display_tx)

                # Update local power state tracking
                if "EN" in cmd_frame.upper():
                    if node_id in self._power_states:
                        self._power_states[node_id] = True
                        self.sig_power_state.emit(node_id, True)
                elif "DI" in cmd_frame.upper():
                    if node_id in self._power_states:
                        self._power_states[node_id] = False
                        self.sig_power_state.emit(node_id, False)

                # 4. Read response
                # Small pause to allow controller MCU processing
                time.sleep(0.015)

                rx_data = b""
                start_read = time.time()
                while (time.time() - start_read) < 0.12:
                    chunk = self._serial.read(self._serial.in_waiting or 1)
                    if chunk:
                        rx_data += chunk
                        if b"\r" in chunk or b"\n" in chunk:
                            break
                    else:
                        break

                if rx_data:
                    ts_rx = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    rx_str = rx_data.decode("ascii", errors="ignore").strip()

                    if not is_routine_poll and rx_str:
                        display_rx = rx_str.replace("\r", "\\r").replace("\n", "\\n")
                        self.sig_log_rx.emit(ts_rx, display_rx)

                    # Check if response is numeric position value
                    if is_query and "POS" in cmd_frame.upper() and rx_str:
                        self._handle_pos_response(node_id, rx_str)

                self._queue.task_done()

            except serial.SerialException as se:
                self.sig_error.emit(f"Serial communication error: {str(se)}")
                break
            except Exception as ex:
                self.sig_error.emit(f"Unexpected worker error: {str(ex)}")
                time.sleep(0.05)

        # Cleanup serial port
        if self._serial:
            try:
                if self._serial.is_open:
                    self._serial.close()
            except Exception:
                pass
            self._serial = None

        self.sig_disconnected.emit()

    def _handle_pos_response(self, node_id: int, response_text: str):
        """
        Parse position response string and emit signal.
        FAULHABER response can be e.g. "12345", "-500", "p=12345", etc.
        """
        # Match integer count numbers (positive or negative)
        match = re.search(r"[-+]?\d+", response_text)
        if match:
            try:
                counts = int(match.group(0))
                self.sig_position_update.emit(node_id, counts)
            except ValueError:
                pass

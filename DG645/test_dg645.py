"""
Unit tests for SRS DG645 driver using mocked serial interface.
"""

import unittest
from unittest.mock import MagicMock, patch
from dg645 import DG645, DG645Error, OUTPUT_PULSE_CHANNELS, CHANNEL_MAP

class MockSerial:
    def __init__(self, *args, **kwargs):
        self.is_open = True
        self.write_history = []
        self.responses = {
            b"*IDN?\r\n": b"Stanford_Research_Systems,DG645,s/n001013,ver1.12\r\n",
            b"LERR?\r\n": b"0\r\n",
            b"TSRC?\r\n": b"3\r\n",
            b"TLVL?\r\n": b"1.000\r\n",
            b"DLAY? 2\r\n": b"0,+0.000010000000\r\n",
            b"DLAY? 3\r\n": b"2,+0.001000000000\r\n",
            b"DLAY? 4\r\n": b"0,+0.000020000000\r\n",
            b"DLAY? 5\r\n": b"4,+0.001000000000\r\n",
            b"DLAY? 6\r\n": b"0,+0.000030000000\r\n",
            b"DLAY? 7\r\n": b"6,+0.001000000000\r\n",
            b"DLAY? 8\r\n": b"0,+0.000040000000\r\n",
            b"DLAY? 9\r\n": b"8,+0.001000000000\r\n",
        }
        self.last_query = None

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        pass

    def write(self, data: bytes):
        self.write_history.append(data)
        self.last_query = data

    def flush(self):
        pass

    def readline(self) -> bytes:
        if self.last_query in self.responses:
            return self.responses[self.last_query]
        return b"0\r\n"

    def close(self):
        self.is_open = False


class TestDG645Driver(unittest.TestCase):
    def setUp(self):
        self.patcher = patch("serial.Serial", side_effect=MockSerial)
        self.mock_serial_cls = self.patcher.start()
        self.dg = DG645(port="COM5", baudrate=9600)
        self.dg.connect()

    def tearDown(self):
        self.dg.disconnect()
        self.patcher.stop()

    def test_connect_and_idn(self):
        self.assertTrue(self.dg.is_connected())
        idn = self.dg.get_idn()
        self.assertIn("DG645", idn)

    def test_set_trigger_source(self):
        # Single shot external rising edge -> TSRC 3
        self.dg.set_trigger_source("single_shot_ext_rising")
        self.assertEqual(self.dg.ser.write_history[-2], b"TSRC 3\r\n")

        # Code 3
        self.dg.set_trigger_source(3)
        self.assertEqual(self.dg.ser.write_history[-2], b"TSRC 3\r\n")

        # Code 4 (falling edge)
        self.dg.set_trigger_source("single_shot_ext_falling")
        self.assertEqual(self.dg.ser.write_history[-2], b"TSRC 4\r\n")

    def test_set_trigger_level(self):
        self.dg.set_trigger_level(1.25)
        self.assertEqual(self.dg.ser.write_history[-2], b"TLVL 1.250\r\n")

        with self.assertRaises(ValueError):
            self.dg.set_trigger_level(5.0)  # > 3.5V

    def test_set_channel_pulse_1ms(self):
        # Channel 1: AB -> A leading relative to T0 (0), B trailing relative to A (2) with 1 ms
        self.dg.set_channel_pulse(channel_index_or_name=1, delay_seconds=10e-6, pulse_width_seconds=0.001)
        
        # Check command sent for A: DLAY 2,0,1.000000000000e-05
        # Check command sent for B: DLAY 3,2,1.000000000000e-03
        sent_commands = [cmd.decode('ascii').strip() for cmd in self.dg.ser.write_history]
        self.assertTrue(any("DLAY 2,0," in cmd for cmd in sent_commands))
        self.assertTrue(any("DLAY 3,2,1.000000000000e-03" in cmd for cmd in sent_commands))

    def test_set_all_4_channels(self):
        delays = {
            1: 0.0,
            2: 100e-6,
            3: 200e-6,
            4: 300e-6,
        }
        self.dg.set_all_4_channels(delays, pulse_width_seconds=0.001)
        sent_commands = [cmd.decode('ascii').strip() for cmd in self.dg.ser.write_history]
        # Check all 4 leading edges: 2(A), 4(C), 6(E), 8(G)
        self.assertTrue(any("DLAY 2,0," in cmd for cmd in sent_commands))
        self.assertTrue(any("DLAY 4,0," in cmd for cmd in sent_commands))
        self.assertTrue(any("DLAY 6,0," in cmd for cmd in sent_commands))
        self.assertTrue(any("DLAY 8,0," in cmd for cmd in sent_commands))

    def test_trigger(self):
        self.dg.trigger()
        self.assertEqual(self.dg.ser.write_history[-1], b"*TRG\r\n")

    def test_get_channel_settings(self):
        res = self.dg.get_channel_settings('AB')
        self.assertAlmostEqual(res['delay'], 10e-6)
        self.assertAlmostEqual(res['width'], 1e-3)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""
ca_client_test.py
=================
Cross-PC EPICS Channel Access Test Client for DAQ_CA.

Run this script from a remote Client PC (e.g. 192.168.1.30) to verify Channel Access
communication with the DAQ IOC Server on Server PC (e.g. 192.168.1.32).

Features:
- Robust decoding for EPICS char-waveform arrays / ASCII code sequences into Python str.
- Zero-length / empty array safeguards preventing IndexError on empty strings.
- Network configuration helper for EPICS_CA_ADDR_LIST.

Usage:
    python ca_client_test.py --server-ip 192.168.1.32
    python ca_client_test.py --prefix EXP:Seq:
"""

import os
import sys
import time
import argparse


def setup_epics_env(server_ip: str | None = None):
    """Configure EPICS Channel Access network environment variables."""
    if server_ip:
        os.environ["EPICS_CA_ADDR_LIST"] = server_ip
        os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"
        print(f"[Config] Set EPICS_CA_ADDR_LIST = {server_ip} (AUTO_ADDR_LIST=NO)")
    else:
        print("[Config] Using default broadcast discovery (EPICS_CA_AUTO_ADDR_LIST=YES)")


def decode_epics_value(data, is_string: bool = False):
    """
    Robustly decode EPICS Channel Access data payloads into Python objects.
    
    Handles:
    - Empty / zero-length numpy arrays, lists, or None (safeguard against IndexError)
    - ASCII integer code arrays (e.g. numpy.ndarray([73, 68, 76, 69]) -> "IDLE")
    - Raw byte arrays (e.g. b'IDLE\x00')
    - Standard numeric values (int, float)
    """
    if data is None:
        return "" if is_string else 0

    # Handle empty sequences or numpy arrays
    if hasattr(data, "__len__") and len(data) == 0:
        return "" if is_string else 0

    # If it's a numpy ndarray
    try:
        import numpy as np
        if isinstance(data, np.ndarray):
            if data.size == 0:
                return "" if is_string else 0
            if is_string:
                # If array of integers representing ASCII characters
                if data.dtype.kind in ("u", "i", "b"):
                    return bytes(data.tolist()).decode("utf-8", errors="ignore").rstrip("\x00")
                elif data.dtype.kind in ("U", "S"):
                    return "".join(str(x) for x in data).rstrip("\x00")
            else:
                return data[0] if data.size > 0 else 0
    except ImportError:
        pass

    # If raw bytes or bytearray
    if isinstance(data, (bytes, bytearray)):
        decoded = data.decode("utf-8", errors="ignore").rstrip("\x00")
        return decoded if is_string else int(data[0] if len(data) > 0 else 0)

    # If python list or tuple
    if isinstance(data, (list, tuple)):
        if len(data) == 0:
            return "" if is_string else 0
        if is_string:
            if all(isinstance(x, int) for x in data):
                return bytes(data).decode("utf-8", errors="ignore").rstrip("\x00")
            elif len(data) == 1:
                return decode_epics_value(data[0], is_string=True)
            return "".join(str(x) for x in data).rstrip("\x00")
        else:
            return data[0]

    # Scalar values
    return str(data) if is_string else data


def test_ioc_connection(prefix: str):
    """Connect to the 5 core PVs using caproto or pyepics."""
    try:
        from caproto.sync.client import read, write
    except ImportError:
        try:
            from epics import caget, caput
            # Wrap in simple functions
            read = lambda pv, timeout=2.0: type("Resp", (), {"data": [caget(pv, timeout=timeout)]})()
            write = lambda pv, val: caput(pv, val)
        except ImportError:
            print("\n[Error] Neither 'caproto' nor 'pyepics' is installed on this PC.")
            print("Please install caproto:")
            print("    pip install caproto")
            sys.exit(1)

    pvs = {
        "ShotTarget": (f"{prefix}ShotTarget", False),
        "Arm": (f"{prefix}Arm", False),
        "State": (f"{prefix}State", True),
        "FileName": (f"{prefix}FileName", True),
        "Note": (f"{prefix}Note", True),
    }

    print("\n========================================================")
    print(f"  CONNECTING TO DAQ IOC SERVER (Prefix: {prefix})")
    print("========================================================\n")

    # Step 1: Read all PVs with robust decoding
    print("[1/4] Reading initial PV values...")
    for name, (pv, is_str) in pvs.items():
        try:
            res = read(pv, timeout=3.0)
            raw_data = getattr(res, "data", None)
            val = decode_epics_value(raw_data, is_string=is_str)
            print(f"  - {pv:22s} = {repr(val)}")
        except Exception as e:
            print(f"  - {pv:22s} -> TIMEOUT / UNREACHABLE ({e})")
            print("\n[Troubleshooting Tips]")
            print("1. Is the IOC Server running on Server PC A? (python -m ca_server.ioc_server)")
            print("2. Check Windows Firewall: allow UDP/TCP ports 5064 & 5065 on PC A.")
            print("3. Verify IP connectivity: ping <server-ip>")
            sys.exit(1)

    print("\n>>> Connection verified successfully!\n")

    # Step 2: Configure experiment settings
    print("[2/4] Writing test configuration parameters...")
    test_filename = f"remote_test_{int(time.time()) % 10000}"
    test_note = "Remote PC DAQ test"
    test_shots = 3

    print(f"  - Setting FileName   -> '{test_filename}'")
    write(pvs["FileName"][0], test_filename)

    print(f"  - Setting Note       -> '{test_note}'")
    write(pvs["Note"][0], test_note)

    print(f"  - Setting ShotTarget -> {test_shots}")
    write(pvs["ShotTarget"][0], test_shots)

    time.sleep(0.3)

    # Read back to verify
    rb_fn = decode_epics_value(read(pvs["FileName"][0], timeout=2.0).data, is_string=True)
    rb_nt = decode_epics_value(read(pvs["Note"][0], timeout=2.0).data, is_string=True)
    rb_st = decode_epics_value(read(pvs["ShotTarget"][0], timeout=2.0).data, is_string=False)
    print(f"  [Readback] FileName='{rb_fn}', Note='{rb_nt}', ShotTarget={rb_st}")

    # Step 3: Trigger Arm
    print("\n[3/4] Triggering Acquisition (Arm = 1)...")
    write(pvs["Arm"][0], 1)

    # Step 4: Monitor State
    print("\n[4/4] Monitoring State progression...")
    start_time = time.time()
    last_state = None
    completed = False

    while time.time() - start_time < 12.0:
        res = read(pvs["State"][0], timeout=2.0)
        state_str = decode_epics_value(res.data, is_string=True)

        if state_str != last_state:
            print(f"  [State Update] -> {state_str}")
            last_state = state_str

        if state_str == "IDLE" and (time.time() - start_time) > 0.5:
            completed = True
            break
        elif state_str == "ERROR":
            print("\n>>> System entered ERROR state (Check interlocks on Server PC).")
            break

        time.sleep(0.25)

    if completed:
        print("\n========================================================")
        print("  REMOTE DAQ SEQUENCE TEST PASSED (100% OK)!")
        print("========================================================\n")
    else:
        print("\n>>> Test completed with final state:", repr(last_state))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test EPICS DAQ IOC from a separate or local PC.")
    parser.add_argument(
        "--server-ip",
        type=str,
        default=None,
        help="IP address of the PC running the IOC server (e.g. 192.168.1.32)",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default="EXP:Seq:",
        help="PV prefix (default: 'EXP:Seq:')",
    )
    args = parser.parse_args()

    setup_epics_env(args.server_ip)
    test_ioc_connection(args.prefix)

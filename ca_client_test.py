#!/usr/bin/env python3
"""
ca_client_test.py
=================
Cross-PC EPICS Channel Access Test Client for DAQ_CA.

Run this script from a remote Client PC (or locally) to verify Channel Access
communication with the DAQ IOC Server.

Usage:
    python ca_client_test.py --server-ip 192.168.1.100
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


def test_ioc_connection(prefix: str):
    """Connect to the 5 core PVs using pyepics or caproto."""
    try:
        from caproto.sync.client import read, write
    except ImportError:
        try:
            from epics import caget, caput
            # Wrap in simple functions
            read = lambda pv: type("Resp", (), {"data": [caget(pv)]})()
            write = lambda pv, val: caput(pv, val)
        except ImportError:
            print("\n[Error] Neither 'caproto' nor 'pyepics' is installed on this PC.")
            print("Please install caproto:")
            print("    pip install caproto")
            sys.exit(1)

    pvs = {
        "ShotTarget": f"{prefix}ShotTarget",
        "Arm": f"{prefix}Arm",
        "State": f"{prefix}State",
        "FileName": f"{prefix}FileName",
        "Note": f"{prefix}Note",
    }

    print("\n========================================================")
    print(f"  CONNECTING TO DAQ IOC SERVER (Prefix: {prefix})")
    print("========================================================\n")

    # Step 1: Read all PVs
    print("[1/4] Reading initial PV values...")
    for name, pv in pvs.items():
        try:
            res = read(pv, timeout=2.0)
            val = res.data[0]
            if isinstance(val, bytes):
                val = val.decode("utf-8", errors="ignore")
            print(f"  - {pv:22s} = {val}")
        except Exception as e:
            print(f"  - {pv:22s} -> TIMEOUT / UNREACHABLE ({e})")
            print("\n[Troubleshooting Tips]")
            print("1. Is the IOC Server running on the target PC? (python -m ca_server.ioc_server)")
            print("2. Check Windows Firewall: allow UDP/TCP ports 5064 & 5065 on the server PC.")
            print("3. Verify IP connectivity: ping <server-ip>")
            sys.exit(1)

    print("\n>>> Connection verified successfully!\n")

    # Step 2: Configure experiment settings
    print("[2/4] Writing test configuration parameters...")
    test_filename = f"remote_test_{int(time.time()) % 10000}"
    test_note = "Remote PC DAQ test"
    test_shots = 3

    print(f"  - Setting FileName   -> '{test_filename}'")
    write(pvs["FileName"], test_filename)

    print(f"  - Setting Note       -> '{test_note}'")
    write(pvs["Note"], test_note)

    print(f"  - Setting ShotTarget -> {test_shots}")
    write(pvs["ShotTarget"], test_shots)

    time.sleep(0.2)

    # Step 3: Trigger Arm
    print("\n[3/4] Triggering Acquisition (Arm = 1)...")
    write(pvs["Arm"], 1)

    # Step 4: Monitor State
    print("\n[4/4] Monitoring State progression...")
    start_time = time.time()
    last_state = None
    completed = False

    while time.time() - start_time < 10.0:
        res = read(pvs["State"], timeout=2.0)
        state_str = res.data[0]
        if isinstance(state_str, bytes):
            state_str = state_str.decode("utf-8", errors="ignore")

        if state_str != last_state:
            print(f"  [State Update] -> {state_str}")
            last_state = state_str

        if state_str == "IDLE" and (time.time() - start_time) > 0.5:
            completed = True
            break
        elif state_str == "ERROR":
            print("\n>>> System entered ERROR state (Check interlocks on Server PC).")
            break

        time.sleep(0.2)

    if completed:
        print("\n========================================================")
        print("  REMOTE DAQ SEQUENCE TEST PASSED (100% OK)!")
        print("========================================================\n")
    else:
        print("\n>>> Test completed with state:", last_state)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test EPICS DAQ IOC from a separate or local PC.")
    parser.add_argument(
        "--server-ip",
        type=str,
        default=None,
        help="IP address of the PC running the IOC server (e.g. 192.168.1.100)",
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

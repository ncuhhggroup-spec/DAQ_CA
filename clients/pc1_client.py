#!/usr/bin/env python3
"""
clients/pc1_client.py
======================
EPICS Channel Access Control Client for PC_1.

Connects to PC_2 IOC Server and performs interlocked sequence trigger:
1. Checks EXP:Seq:CameraStatus interlock (must be "IDLE").
2. Writes EXP:Seq:FileName.
3. Sets EXP:Seq:Arm = 1.
4. Monitors execution until completed.

Usage:
    python clients/pc1_client.py --server-ip 192.168.1.32 --file-name exp_run_01
"""

import os
import sys
import time
import argparse
from typing import Any


def setup_epics_env(server_ip: str | None = None) -> None:
    """Configure EPICS CA network environment variables."""
    if server_ip:
        os.environ["EPICS_CA_ADDR_LIST"] = server_ip
        os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"
        print(f"[Config] Set EPICS_CA_ADDR_LIST = {server_ip} (AUTO_ADDR_LIST=NO)")
    else:
        print("[Config] Using broadcast discovery (EPICS_CA_AUTO_ADDR_LIST=YES)")


def decode_str(val: Any) -> str:
    """Decode raw caproto/EPICS data bytes/arrays into a clean string."""
    if val is None:
        return ""
    if isinstance(val, (bytes, bytearray)):
        return val.decode("utf-8", errors="ignore").rstrip("\x00")
    if hasattr(val, "size") and getattr(val, "size") > 0:
        # Numpy array support
        import numpy as np
        if isinstance(val, np.ndarray) and val.dtype.kind in ("u", "i", "b"):
            return bytes(val.tolist()).decode("utf-8", errors="ignore").rstrip("\x00")
    if isinstance(val, (list, tuple)):
        if len(val) > 0 and isinstance(val[0], int):
            return bytes(val).decode("utf-8", errors="ignore").rstrip("\x00")
        return "".join(str(x) for x in val).rstrip("\x00")
    return str(val).rstrip("\x00")


def run_client(prefix: str, file_name: str, server_ip: str | None = None) -> bool:
    """Execute interlocked acquisition sequence from PC_1."""
    setup_epics_env(server_ip)

    try:
        from caproto.sync.client import read, write
    except ImportError:
        print("[Error] caproto is required. Install via: pip install caproto")
        sys.exit(1)

    status_pv = f"{prefix}CameraStatus"
    filename_pv = f"{prefix}FileName"
    arm_pv = f"{prefix}Arm"
    shot_pv = f"{prefix}ShotNumber"

    print(f"\n[PC_1 Client] Connecting to IOC Server at prefix '{prefix}'...")

    # Step 1: Query CameraStatus Interlock
    try:
        res = read(status_pv, timeout=3.0)
        camera_status = decode_str(res.data)
    except Exception as e:
        print(f"[Error] Failed to connect to PV '{status_pv}': {e}")
        return False

    print(f"[PC_1 Client] Current CameraStatus: '{camera_status}'")

    # Interlock Check Rule
    if camera_status != "IDLE":
        print(f"[WARNING] Interlock Triggered: CameraStatus is '{camera_status}' (not IDLE). Aborting Arm process!")
        return False

    # Step 2: Write FileName
    print(f"[PC_1 Client] Setting {filename_pv} = '{file_name}'...")
    write(filename_pv, file_name.encode("utf-8"), timeout=2.0)

    # Step 3: Trigger Arm = 1
    print(f"[PC_1 Client] Issuing Arm Command: Setting {arm_pv} = 1...")
    write(arm_pv, 1, timeout=2.0)

    # Step 4: Monitor progress until completion
    print("[PC_1 Client] Acquisition in progress, waiting for sequence completion...")
    start_time = time.time()

    while time.monotonic() - start_time < 5.0:
        time.sleep(0.2)
        curr_status = decode_str(read(status_pv, timeout=2.0).data)
        if curr_status == "IDLE":
            curr_shot = read(shot_pv, timeout=2.0).data[0]
            print(f"[PC_1 Client] Acquisition Succeeded! Current ShotNumber: #{curr_shot}, Status: IDLE")
            return True

    print("[Error] Timed out waiting for acquisition sequence to finish.")
    return False


def main():
    parser = argparse.ArgumentParser(description="PC_1 EPICS Channel Access Control Client")
    parser.add_argument("--server-ip", type=str, default=None, help="Target PC_2 IOC IP address")
    parser.add_argument("--prefix", type=str, default="EXP:Seq:", help="PV prefix (default: EXP:Seq:)")
    parser.add_argument("--file-name", type=str, default="exp_run_pc1", help="Target filename prefix")
    args = parser.parse_args()

    run_client(prefix=args.prefix, file_name=args.file_name, server_ip=args.server_ip)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
ca_server/ioc_server_pc2.py
============================
EPICS Channel Access IOC Server for PC_2 (Distributed Test System).

Implements the Minimalist 4-PV Spec:
- EXP:Seq:Arm (int, 0/1)
- EXP:Seq:FileName (str)
- EXP:Seq:ShotNumber (int, auto-incremented)
- EXP:Seq:CameraStatus (str: "IDLE", "ACTIVATING", "ERROR")

Usage:
    python ca_server/ioc_server_pc2.py --prefix "EXP:Seq:"
"""

import asyncio
import logging
import argparse
from caproto.server import PVGroup, pvproperty, run
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PC2_IOC")


class PC2DAQServer(PVGroup):
    """EPICS IOC exposing 4 core control/status PVs."""

    # 1. Arm PV (int, 0 or 1, writable)
    Arm = pvproperty(
        value=0,
        doc="Write 1 to Arm and start sequence (self-resetting to 0)",
        dtype=int,
    )

    # 2. FileName PV (string, writable)
    FileName = pvproperty(
        value="exp_run",
        doc="Target filename for current experiment shot",
        dtype=str,
        max_length=64,
    )

    # 3. ShotNumber PV (int, read-only, auto-incremented)
    ShotNumber = pvproperty(
        value=0,
        doc="Auto-incrementing shot counter",
        dtype=int,
        read_only=True,
    )

    # 4. CameraStatus PV (string, read-only: IDLE, ACTIVATING, ERROR)
    CameraStatus = pvproperty(
        value="IDLE",
        doc="Camera hardware status (IDLE, ACTIVATING, ERROR)",
        dtype=str,
        max_length=32,
        read_only=True,
    )

    @Arm.putter
    async def Arm(self, instance, value: int):
        """Asynchronous Put Callback triggered when EXP:Seq:Arm is written to."""
        if value != 1:
            return 0  # Allow reset to 0

        current_status = self.CameraStatus.value
        if current_status == "ACTIVATING":
            logger.warning("[PC_2 IOC] Rejected Arm command: Camera is already ACTIVATING!")
            return 0

        # Step 1: Set status to ACTIVATING
        logger.info("[PC_2 IOC] Setting CameraStatus -> ACTIVATING")
        await self.CameraStatus.write("ACTIVATING")

        # Step 2: Increment ShotNumber by +1
        new_shot = self.ShotNumber.value + 1
        await self.ShotNumber.write(new_shot)

        # Step 3: Append ShotNumber to FileName to prevent overwriting
        base_filename = self.FileName.value
        # If filename doesn't already end with the shot suffix, append _shotN or format with _#N
        if not base_filename.endswith(f"_{new_shot}"):
            formatted_filename = f"{base_filename}_{new_shot}"
            await self.FileName.write(formatted_filename)
        else:
            formatted_filename = base_filename

        logger.info("[PC_2 IOC] Acquisition Started | Shot #%d | Target File: '%s'", new_shot, formatted_filename)

        # Step 4: Non-blocking async simulation (1.0s)
        await asyncio.sleep(1.0)

        # Step 5: Complete acquisition -> Reset CameraStatus to IDLE and Arm to 0
        logger.info("[PC_2 IOC] Acquisition Complete | Shot #%d | Resetting status -> IDLE", new_shot)
        await self.CameraStatus.write("IDLE")

        return 0  # Resets EXP:Seq:Arm to 0


def main():
    parser = argparse.ArgumentParser(description="PC_2 EPICS Channel Access IOC Server")
    parser.add_argument("--prefix", type=str, default="EXP:Seq:", help="PV prefix (default: EXP:Seq:)")
    args = parser.parse_args()

    logger.info("Starting PC_2 EPICS IOC Server with prefix: %s", args.prefix)
    ioc = PC2DAQServer(prefix=args.prefix)

    # 捕捉並忽略 Windows asyncio 背景 Socket 中斷 (WinError 995)
    def async_exception_handler(loop, context):
        exception = context.get('exception')
        if isinstance(exception, OSError) and getattr(exception, 'winerror', None) == 995:
            return
        loop.default_exception_handler(context)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_exception_handler(async_exception_handler)

    try:
        run(ioc.pvdb)
    except KeyboardInterrupt:
        logger.info("Server stopped by user.")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
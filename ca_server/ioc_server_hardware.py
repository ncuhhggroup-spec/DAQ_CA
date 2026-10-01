import asyncio
import logging
import pathlib
import signal
import sys
from datetime import datetime
from typing import Tuple

from caproto.server import PVGroup, pvproperty, run
from caproto import ChannelType

# -----------------------------------------------------------------------------
# 1. Dual Console & File Logging Setup
# -----------------------------------------------------------------------------
def setup_logging() -> Tuple[logging.Logger, str]:
    log_dir = pathlib.Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filepath = log_dir / f"ioc_hardware_{timestamp}.log"

    logger = logging.getLogger("IOC_Hardware")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File Handler
    file_handler = logging.FileHandler(log_filepath, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger, str(log_filepath)

logger, LOG_FILE_PATH = setup_logging()


# -----------------------------------------------------------------------------
# 2. PV Group Definition (10 Minimal EPICS PVs)
# -----------------------------------------------------------------------------
class HardwareDAQPVGroup(PVGroup):
    """
    10-PV EPICS IOC for DG645 + Camera Hardware Integration Test System.
    Exposes Hardware Connection Status and Hardware Mode (REAL vs SIMULATED).
    """

    # 1. EXP:Seq:ShotTarget (int, RW)
    shot_target = pvproperty(
        name='EXP:Seq:ShotTarget',
        value=1,
        dtype=ChannelType.INT,
        doc='Total target shots per run'
    )

    # 2. EXP:Seq:Arm (int, RW, self-resetting)
    arm = pvproperty(
        name='EXP:Seq:Arm',
        value=0,
        dtype=ChannelType.INT,
        doc='Arm trigger flag (1 = start sequence, auto-resets to 0)'
    )

    # 3. EXP:Seq:State (str, RO)
    state = pvproperty(
        name='EXP:Seq:State',
        value='IDLE',
        dtype=ChannelType.STRING,
        read_only=True,
        doc='System state: IDLE, ARMED, ACQUIRING, SAVING, ERROR'
    )

    # 4. EXP:Seq:FileName (str, RW)
    file_name = pvproperty(
        name='EXP:Seq:FileName',
        value='exp_run',
        dtype=ChannelType.STRING,
        doc='Data file prefix'
    )

    # 5. EXP:Seq:ShotNumber (int, RW)
    shot_number = pvproperty(
        name='EXP:Seq:ShotNumber',
        value=0,
        dtype=ChannelType.INT,
        doc='Current shot counter'
    )

    # 6. EXP:Seq:ErrorMessage (str, RO)
    error_message = pvproperty(
        name='EXP:Seq:ErrorMessage',
        value='',
        dtype=ChannelType.STRING,
        read_only=True,
        doc='System error message'
    )

    # 7. EXP:Seq:DG645Status (str, RW/RO permitted for client updates)
    dg645_status = pvproperty(
        name='EXP:Seq:DG645Status',
        value='CONNECTED',
        dtype=ChannelType.STRING,
        read_only=False,
        doc='DG645 connection status: CONNECTED / DISCONNECTED'
    )

    # 8. EXP:Seq:DG645Mode (str, RW/RO permitted for client updates)
    dg645_mode = pvproperty(
        name='EXP:Seq:DG645Mode',
        value='SIMULATED',
        dtype=ChannelType.STRING,
        read_only=False,
        doc='DG645 operation mode: REAL / SIMULATED'
    )

    # 9. EXP:Seq:CameraStatus (str, RW/RO permitted for client updates)
    camera_status = pvproperty(
        name='EXP:Seq:CameraStatus',
        value='CONNECTED',
        dtype=ChannelType.STRING,
        read_only=False,
        doc='Camera connection status: CONNECTED / DISCONNECTED'
    )

    # 10. EXP:Seq:CameraMode (str, RW/RO permitted for client updates)
    camera_mode = pvproperty(
        name='EXP:Seq:CameraMode',
        value='SIMULATED',
        dtype=ChannelType.STRING,
        read_only=False,
        doc='Camera operation mode: REAL / SIMULATED'
    )

    @arm.putter
    async def arm(self, instance, value):
        if value == 1:
            cur_state = self.state.value
            dg_stat = self.dg645_status.value
            cam_stat = self.camera_status.value

            if cur_state != "IDLE":
                err_msg = f"Cannot ARM: System is in '{cur_state}' state, must be IDLE."
                logger.warning(err_msg)
                await self.error_message.write(err_msg)
                await self.state.write("ERROR")
                return 0

            if dg_stat != "CONNECTED" or cam_stat != "CONNECTED":
                err_msg = f"Cannot ARM: Hardware not ready (DG645: {dg_stat}, Camera: {cam_stat})."
                logger.warning(err_msg)
                await self.error_message.write(err_msg)
                await self.state.write("ERROR")
                return 0

            asyncio.create_task(self._run_sequence())
        return value

    async def _run_sequence(self):
        try:
            logger.info("Starting DAQ Sequence...")
            await self.error_message.write("")
            
            # STAGE 1: ARMED
            await self.state.write("ARMED")
            logger.info("[ARMED] Pre-allocating zero-copy RAM buffers...")
            await asyncio.sleep(0.5)

            # STAGE 2: ACQUIRING
            await self.state.write("ACQUIRING")
            dg_mode = self.dg645_mode.value
            cam_mode = self.camera_mode.value
            logger.info(f"[ACQUIRING] Pulse trigger & frame capture (DG645: {dg_mode}, Camera: {cam_mode})...")
            await asyncio.sleep(1.0)

            # STAGE 3: SAVING
            await self.state.write("SAVING")
            logger.info(f"[SAVING] Persisting data for file '{self.file_name.value}' shot #{self.shot_number.value}...")
            await asyncio.sleep(0.5)

            # STAGE 4: RETURN TO IDLE & INCREMENT SHOT
            new_shot = self.shot_number.value + 1
            await self.shot_number.write(new_shot)
            logger.info(f"[COMPLETE] Sequence completed successfully. New ShotNumber: {new_shot}")
            await self.state.write("IDLE")

        except Exception as e:
            err_str = f"Sequence failed: {str(e)}"
            logger.error(err_str)
            await self.error_message.write(err_str)
            await self.state.write("ERROR")

        finally:
            await self.arm.write(0)


# -----------------------------------------------------------------------------
# 3. Main Entry & Graceful Shutdown Handler
# -----------------------------------------------------------------------------
def main():
    logger.info("Starting EPICS Hardware IOC Server with Dual Logging...")
    logger.info("Log file destination: %s", LOG_FILE_PATH)
    
    pvdb = HardwareDAQPVGroup(prefix='')

    try:
        run(pvdb.pvdb)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Received shutdown request (SIGINT / KeyboardInterrupt).")
    except Exception as e:
        logger.critical("Unexpected IOC Server error: %s", e, exc_info=True)
    finally:
        logger.info("IOC Server shutting down gracefully. Log saved to: %s", LOG_FILE_PATH)
        # Flush all handlers
        for handler in logger.handlers:
            handler.flush()
            handler.close()

if __name__ == '__main__':
    main()
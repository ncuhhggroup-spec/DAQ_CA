import asyncio
import logging
from caproto.server import PVGroup, pvproperty, run
from caproto import ChannelType

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class HardwareDAQPVGroup(PVGroup):
    """
    10-PV EPICS IOC for DG645 + Camera Hardware Integration Test System
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

    # 7. EXP:Seq:DG645Status (str, RW) -- 已修改為允許 GUI 寫入
    dg645_status = pvproperty(
        name='EXP:Seq:DG645Status',
        value='CONNECTED',
        dtype=ChannelType.STRING,
        read_only=False,
        doc='DG645 connection status: CONNECTED / DISCONNECTED'
    )

    # 8. EXP:Seq:DG645Mode (str, RW) -- 已修改為允許 GUI 寫入
    dg645_mode = pvproperty(
        name='EXP:Seq:DG645Mode',
        value='SIMULATED',
        dtype=ChannelType.STRING,
        read_only=False,
        doc='DG645 operation mode: REAL / SIMULATED'
    )

    # 9. EXP:Seq:CameraStatus (str, RW) -- 已修改為允許 GUI 寫入
    camera_status = pvproperty(
        name='EXP:Seq:CameraStatus',
        value='CONNECTED',
        dtype=ChannelType.STRING,
        read_only=False,
        doc='Camera connection status: CONNECTED / DISCONNECTED'
    )

    # 10. EXP:Seq:CameraMode (str, RW) -- 已修改為允許 GUI 寫入
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
                logging.warning(err_msg)
                await self.error_message.write(err_msg)
                await self.state.write("ERROR")
                return 0

            if dg_stat != "CONNECTED" or cam_stat != "CONNECTED":
                err_msg = f"Cannot ARM: Hardware not ready (DG645: {dg_stat}, Camera: {cam_stat})."
                logging.warning(err_msg)
                await self.error_message.write(err_msg)
                await self.state.write("ERROR")
                return 0

            asyncio.create_task(self._run_sequence())
        return value

    async def _run_sequence(self):
        try:
            logging.info("Starting DAQ Sequence...")
            await self.error_message.write("")
            
            # STAGE 1: ARMED
            await self.state.write("ARMED")
            logging.info("[ARMED] Pre-allocating zero-copy RAM buffers...")
            await asyncio.sleep(0.5)

            # STAGE 2: ACQUIRING
            await self.state.write("ACQUIRING")
            dg_mode = self.dg645_mode.value
            cam_mode = self.camera_mode.value
            logging.info(f"[ACQUIRING] Pulse trigger & acquiring frame (DG645: {dg_mode}, Camera: {cam_mode})...")
            await asyncio.sleep(1.0)

            # STAGE 3: SAVING
            await self.state.write("SAVING")
            logging.info(f"[SAVING] Persisting data for file '{self.file_name.value}' shot #{self.shot_number.value}...")
            await asyncio.sleep(0.5)

            # STAGE 4: RETURN TO IDLE & INCREMENT SHOT
            new_shot = self.shot_number.value + 1
            await self.shot_number.write(new_shot)
            logging.info(f"[COMPLETE] Sequence completed successfully. New ShotNumber: {new_shot}")
            await self.state.write("IDLE")

        except Exception as e:
            err_str = f"Sequence failed: {str(e)}"
            logging.error(err_str)
            await self.error_message.write(err_str)
            await self.state.write("ERROR")

        finally:
            await self.arm.write(0)

if __name__ == '__main__':
    logging.info("Starting EPICS Hardware IOC Server with Mode Indicators...")
    pvdb = HardwareDAQPVGroup(prefix='')
    run(pvdb.pvdb)
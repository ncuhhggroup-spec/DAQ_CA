"""
Phase 2 EPICS IOC Server Interface (CA Server).
Uses caproto or pcaspy to expose SequenceController state and Stage parameters as standard EPICS PVs.

PV Mapping:
--------------------------------------------------------------------------------------
EPICS PV Name        Type     Access   Bound Function / Property
--------------------------------------------------------------------------------------
EXP:Seq:State        ENUM     R        controller.state.value
EXP:Seq:Arm          BOOL     W        Writing 1 triggers controller.arm_and_start()
EXP:Seq:ShotTarget   INT      R/W      controller.shot_target (1..100)
EXP:Seq:ShotCurrent  INT      R        controller.shot_current (0..N)
EXP:Data:FileName    STRING   R/W      controller.file_name
EXP:Data:Note        STRING   R/W      controller.note
EXP:Stage:PosVal     FLOAT    R        stage.get_position()
EXP:Stage:IsMoving   BOOL     R        stage.is_moving()
--------------------------------------------------------------------------------------
"""

from typing import Optional
from core.sequence_controller import SequenceController, SystemState

try:
    import caproto
    CAPROTO_AVAILABLE = True
except Exception:
    CAPROTO_AVAILABLE = False


class DAQPVGroup:
    """PV Group mapping definition for Channel Access server."""
    def __init__(self, controller: SequenceController):
        self.controller = controller

    def get_pv_dict(self):
        return {
            "EXP:Seq:State": self.controller.state.value,
            "EXP:Seq:ShotTarget": self.controller.shot_target,
            "EXP:Seq:ShotCurrent": self.controller.shot_current,
            "EXP:Data:FileName": self.controller.file_name,
            "EXP:Data:Note": self.controller.note,
            "EXP:Stage:PosVal": self.controller.stage.get_position(),
            "EXP:Stage:IsMoving": self.controller.stage.is_moving(),
        }


def run_ioc_server(controller: SequenceController, prefix: str = "EXP:"):
    """Launch EPICS IOC Server if caproto is installed.
    Returns True if the server was started successfully.
    """
    if not CAPROTO_AVAILABLE:
        print("[CA Server] caproto is not installed. To enable Channel Access, install 'pip install caproto'.")
        return False
    print(f"[CA Server] Starting Channel Access server with prefix '{prefix}'...")
    # Create a simple PV database from the controller
    pvdb = {
        name: pvproperty(value=val, read_only=True)
        for name, val in DAQPVGroup(controller).get_pv_dict().items()
    }
    # Start the Caproto Context in the background
    ctx = Context(pvdb=pvdb)
    # Run the server in a separate asyncio task
    import asyncio
    async def _run():
        await ctx.run_forever()
    asyncio.create_task(_run())
    return True

if __name__ == "__main__":
    import asyncio
    from core.sequence_controller import SequenceController
    from drivers.mock_stage_driver import MockStageDriver
    from drivers.mock_camera_gui import MockCameraGUI
    from core.data_manager import DataManager

    # Create dummy controller with mock drivers
    controller = SequenceController(
        stage=MockStageDriver(),
        cam=MockCameraGUI(),
        data_mgr=DataManager(),
    )
    # Start the IOC server; if it starts, keep the event loop running
    if run_ioc_server(controller):
        try:
            asyncio.get_event_loop().run_forever()
        except KeyboardInterrupt:
            print("[CA Server] Shutting down.")

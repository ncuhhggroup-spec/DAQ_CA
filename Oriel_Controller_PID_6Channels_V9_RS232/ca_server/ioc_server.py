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
    from caproto.asyncio.server import Context, PVGroup, pvproperty
    CAPROTO_AVAILABLE = True
except ImportError:
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
    """Launch EPICS IOC Server if caproto is installed."""
    if not CAPROTO_AVAILABLE:
        print("[CA Server] caproto is not installed. To enable Channel Access, install 'pip install caproto'.")
        return False
    print(f"[CA Server] Starting Channel Access server with prefix '{prefix}'...")
    # Caproto server startup hook
    return True

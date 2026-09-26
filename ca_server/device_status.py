# ca_server/device_status.py
"""DeviceStatus PVGroup exposing hardware connection statuses for diagnostic GUI.

This PVGroup uses the prefix "EXP:Dev:" and provides read‑only string PVs for
Stage, DG645 timing module, and Camera connection states.
"""

from caproto.server import PVGroup, pvproperty


class DeviceStatus(PVGroup):
    """Diagnostic PVs exposing device connection statuses.

    The IOC will update these PVs based on whether real drivers are connected.
    They are intended to be displayed in the server‑side GUI.
    """

    # Stage connection status
    StageStatus = pvproperty(
        value="DISCONNECTED",
        doc="Stage connection status",
        dtype=str,
        max_length=32,
        read_only=True,
    )

    # DG645 timing module status
    DG645Status = pvproperty(
        value="DISCONNECTED",
        doc="DG645 timing module status",
        dtype=str,
        max_length=32,
        read_only=True,
    )

    # Camera connection status
    CameraStatus = pvproperty(
        value="DISCONNECTED",
        doc="Camera connection status",
        dtype=str,
        max_length=32,
        read_only=True,
    )

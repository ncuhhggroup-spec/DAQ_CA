"""
pg_camera_driver.py
===================
Low-level Python hardware wrapper for the Point Grey / FLIR FlyCapture2 SDK,
targeting the Grasshopper2 GS2-GE-20S4M (GigE, 1624×1224, Mono16).

Interface: ctypes → FlyCapture2_C.dll  (64-bit)
SDK root  : C:\\Program Files (x86)\\Point Grey Research\\FlyCapture2

Alternatively, if the `PyCapture2` wheel is importable in the active
Python environment it is used automatically instead of raw ctypes.

Author : <your-name>
Date   : 2026-09-21
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SDK constants (mirrored from FlyCapture2Defs.h / FlyCapture2_C.h)
# ---------------------------------------------------------------------------

FC2_PIXEL_FORMAT_MONO8  = 0x80000000
FC2_PIXEL_FORMAT_MONO16 = 0x04000000

FC2_PROPERTY_TYPE_BRIGHTNESS    = 0
FC2_PROPERTY_TYPE_AUTO_EXPOSURE = 1
FC2_PROPERTY_TYPE_SHARPNESS     = 2
FC2_PROPERTY_TYPE_WHITE_BALANCE = 3
FC2_PROPERTY_TYPE_HUE           = 4
FC2_PROPERTY_TYPE_SATURATION    = 5
FC2_PROPERTY_TYPE_GAMMA         = 6
FC2_PROPERTY_TYPE_IRIS          = 7
FC2_PROPERTY_TYPE_FOCUS         = 8
FC2_PROPERTY_TYPE_ZOOM          = 9
FC2_PROPERTY_TYPE_PAN           = 10
FC2_PROPERTY_TYPE_TILT          = 11
FC2_PROPERTY_TYPE_SHUTTER       = 12
FC2_PROPERTY_TYPE_GAIN          = 13
FC2_PROPERTY_TYPE_TRIGGER_MODE  = 14
FC2_PROPERTY_TYPE_TRIGGER_DELAY = 15
FC2_PROPERTY_TYPE_FRAME_RATE    = 16
FC2_PROPERTY_TYPE_TEMPERATURE   = 17

FC2_ERROR_OK           = 0
FC2_ERROR_FAILED       = 1
FC2_ERROR_NOT_CONNECTED = 2
FC2_ERROR_TIMEOUT      = 9

# ---------------------------------------------------------------------------
# ctypes structure definitions
# ---------------------------------------------------------------------------


class fc2Version(ctypes.Structure):
    _fields_ = [
        ("major", ctypes.c_uint),
        ("minor", ctypes.c_uint),
        ("type",  ctypes.c_uint),
        ("build", ctypes.c_uint),
    ]


class fc2PGRGuid(ctypes.Structure):
    _fields_ = [("value", ctypes.c_uint * 4)]


class fc2ConfigROM(ctypes.Structure):
    _fields_ = [
        ("nodeVendorId",       ctypes.c_uint),
        ("chipIdHi",           ctypes.c_uint),
        ("chipIdLo",           ctypes.c_uint),
        ("unitSpecId",         ctypes.c_uint),
        ("unitSWVer",          ctypes.c_uint),
        ("unitSubSWVer",       ctypes.c_uint),
        ("vendorUniqueInfo_0", ctypes.c_uint),
        ("vendorUniqueInfo_1", ctypes.c_uint),
        ("vendorUniqueInfo_2", ctypes.c_uint),
        ("vendorUniqueInfo_3", ctypes.c_uint),
        ("pszKeyword",         ctypes.c_char * 512),
        ("reserved",           ctypes.c_uint * 16),
    ]


class fc2CameraInfo(ctypes.Structure):
    _fields_ = [
        ("serialNumber",         ctypes.c_uint),
        ("interfaceType",        ctypes.c_int),
        ("driverType",           ctypes.c_int),
        ("isColorCamera",        ctypes.c_int),  # Windows BOOL is 4-byte int
        ("modelName",            ctypes.c_char * 512),
        ("vendorName",           ctypes.c_char * 512),
        ("sensorInfo",           ctypes.c_char * 512),
        ("sensorResolution",     ctypes.c_char * 512),
        ("driverName",           ctypes.c_char * 512),
        ("firmwareVersion",      ctypes.c_char * 512),
        ("firmwareBuildTime",    ctypes.c_char * 512),
        ("maximumBusSpeed",      ctypes.c_int),
        ("bayerTileFormat",      ctypes.c_int),
        ("pcieBusSpeed",         ctypes.c_int),
        ("nodeNumber",           ctypes.c_ushort),
        ("busNumber",            ctypes.c_ushort),
        ("iidcVer",              ctypes.c_uint),
        ("configROM",            fc2ConfigROM),
        ("gigEMajorVersion",     ctypes.c_uint),
        ("gigEMinorVersion",     ctypes.c_uint),
        ("userDefinedName",      ctypes.c_char * 512),
        ("xmlURL1",              ctypes.c_char * 512),
        ("xmlURL2",              ctypes.c_char * 512),
        ("macAddress",           ctypes.c_ubyte * 6),
        ("ipAddress",            ctypes.c_ubyte * 4),
        ("subnetMask",           ctypes.c_ubyte * 4),
        ("defaultGateway",       ctypes.c_ubyte * 4),
        ("ccpStatus",            ctypes.c_uint),
        ("applicationIPAddress", ctypes.c_uint),
        ("applicationPort",      ctypes.c_uint),
        ("reserved",             ctypes.c_uint * 16),
    ]


class fc2Property(ctypes.Structure):
    _fields_ = [
        ("type",            ctypes.c_int),
        ("present",         ctypes.c_int),  # Windows BOOL is 4-byte int
        ("absControl",      ctypes.c_int),
        ("onePush",         ctypes.c_int),
        ("onOff",           ctypes.c_int),
        ("autoManualMode",  ctypes.c_int),
        ("valueA",          ctypes.c_uint),
        ("valueB",          ctypes.c_uint),
        ("absValue",        ctypes.c_float),
        ("reserved",        ctypes.c_uint * 8),
    ]


class fc2TriggerMode(ctypes.Structure):
    _fields_ = [
        ("onOff",     ctypes.c_int),  # Windows BOOL is 4-byte int
        ("polarity",  ctypes.c_uint),
        ("source",    ctypes.c_uint),
        ("mode",      ctypes.c_uint),
        ("parameter", ctypes.c_uint),
        ("reserved",  ctypes.c_uint * 8),
    ]


class fc2Image(ctypes.Structure):
    _fields_ = [
        ("rows",             ctypes.c_uint),
        ("cols",             ctypes.c_uint),
        ("stride",           ctypes.c_uint),
        ("pData",            ctypes.c_void_p),
        ("dataSize",         ctypes.c_uint),
        ("receivedDataSize", ctypes.c_uint),
        ("format",           ctypes.c_int),
        ("bayerFormat",      ctypes.c_int),
        ("imageImpl",        ctypes.c_void_p),
    ]


class fc2GigEImageSettings(ctypes.Structure):
    _fields_ = [
        ("offsetX",     ctypes.c_uint),
        ("offsetY",     ctypes.c_uint),
        ("width",       ctypes.c_uint),
        ("height",      ctypes.c_uint),
        ("pixelFormat", ctypes.c_uint),
        ("reserved",    ctypes.c_uint * 8),
    ]


# ---------------------------------------------------------------------------
# DLL loader
# ---------------------------------------------------------------------------

_SDK_SEARCH_PATHS = [
    Path(r"C:\Program Files\Point Grey Research\FlyCapture2\bin64\vs2015"),
    Path(r"C:\Program Files\Point Grey Research\FlyCapture2\bin64\vs2013"),
    Path(r"C:\Program Files\Point Grey Research\FlyCapture2\bin64"),
    Path(r"C:\Program Files\Point Grey Research\FlyCapture2"),
    Path(r"C:\Program Files\FLIR Systems\FlyCapture2\bin64\vs2015"),
    Path(r"C:\Program Files\FLIR Systems\FlyCapture2\bin64\vs2013"),
    Path(r"C:\Program Files\FLIR Systems\FlyCapture2\bin64"),
    Path(r"C:\Program Files (x86)\Point Grey Research\FlyCapture2\bin64\vs2015"),
    Path(r"C:\Program Files (x86)\Point Grey Research\FlyCapture2\bin64\vs2013"),
    Path(r"C:\Program Files (x86)\Point Grey Research\FlyCapture2\bin64"),
]

_C_DLL_CANDIDATES = [
    "FlyCapture2_C_v140.dll",
    "FlyCapture2_C_v120.dll",
    "FlyCapture2_C_v100.dll",
    "FlyCapture2_C.dll",
]


def _load_flycapture_dll() -> ctypes.CDLL:
    """
    Attempt to load 64-bit FlyCapture2 C API DLL from known SDK install paths.
    Raises RuntimeError if the DLL cannot be found.
    """
    # First add all valid directory paths to DLL resolution (for dependencies like FlyCapture2_v140.dll, libiomp5md.dll, etc.)
    for sdk_bin in _SDK_SEARCH_PATHS:
        if sdk_bin.is_dir():
            try:
                os.add_dll_directory(str(sdk_bin))
            except (AttributeError, OSError):
                pass
            os.environ["PATH"] = f"{str(sdk_bin)};" + os.environ.get("PATH", "")

    # Look for the C-API DLL candidate
    for sdk_bin in _SDK_SEARCH_PATHS:
        if sdk_bin.is_dir():
            for dll_candidate in _C_DLL_CANDIDATES:
                dll_path = sdk_bin / dll_candidate
                if dll_path.is_file():
                    try:
                        logger.info("Attempting to load FlyCapture2 DLL from: %s", dll_path)
                        loaded_dll = ctypes.CDLL(str(dll_path))
                        logger.info("Successfully loaded: %s", dll_path)
                        return loaded_dll
                    except OSError as err:
                        logger.warning("Failed to load candidate %s: %s", dll_path, err)
                        continue

    # Fallback to system resolution
    for dll_candidate in _C_DLL_CANDIDATES:
        located = ctypes.util.find_library(dll_candidate.replace(".dll", ""))
        if located:
            try:
                return ctypes.CDLL(located)
            except OSError:
                continue

    raise RuntimeError(
        f"Cannot locate 64-bit FlyCapture2 C API DLL ({', '.join(_C_DLL_CANDIDATES)}).\n"
        r"Searched paths include C:\Program Files\Point Grey Research\FlyCapture2\bin64."
    )


# ---------------------------------------------------------------------------
# Try PyCapture2 first; fall back to ctypes wrapper
# ---------------------------------------------------------------------------

_USE_PYCAPTURE2 = False
_pc2 = None

try:
    import PyCapture2 as _pc2          # type: ignore[import]
    _USE_PYCAPTURE2 = True
    logger.info("PyCapture2 wheel found – using PyCapture2 backend.")
except ImportError:
    logger.info("PyCapture2 not installed – falling back to ctypes backend.")


# ---------------------------------------------------------------------------
# Grasshopper2Driver – unified public interface
# ---------------------------------------------------------------------------


class Grasshopper2Driver:
    """
    Hardware abstraction layer for the Point Grey Grasshopper2 GS2-GE-20S4M.

    Usage
    -----
    >>> cam = Grasshopper2Driver()
    >>> cam.connect()
    >>> cam.start_capture()
    >>> frame = cam.grab_frame_numpy()   # numpy uint16 array (1224, 1624)
    >>> cam.stop_capture()
    >>> cam.disconnect()

    The class also supports use as a context manager::

        with Grasshopper2Driver() as cam:
            frame = cam.grab_frame_numpy()
    """

    TARGET_SERIAL = 17360853
    SENSOR_WIDTH  = 1624
    SENSOR_HEIGHT = 1224

    DEFAULT_EXPOSURE_S = 0.1    # 100 ms
    DEFAULT_FPS        = 10.0
    DEFAULT_GAIN_DB    = 0.0

    def __init__(
        self,
        serial: int = TARGET_SERIAL,
        auto_detect: bool = True,
    ) -> None:
        """
        Parameters
        ----------
        serial      : Camera serial number to target (default 17360853).
        auto_detect : If True, connect to the first available camera when
                      the target serial is not found on the bus.
        """
        self._serial      = serial
        self._auto_detect = auto_detect
        self._connected   = False
        self._capturing   = False

        self._width       = self.SENSOR_WIDTH
        self._height      = self.SENSOR_HEIGHT

        # Backend handles – populated in connect()
        self._ctx: Optional[ctypes.c_void_p] = None   # fc2Context (ctypes)
        self._cam = None                               # PyCapture2 Camera
        self._image_obj: Optional[fc2Image] = None     # reusable image buffer

        if not _USE_PYCAPTURE2:
            self._dll = _load_flycapture_dll()
            self._setup_dll_argtypes()

    # ------------------------------------------------------------------
    # Internal – ctypes argtypes / restypes
    # ------------------------------------------------------------------

    def _setup_dll_argtypes(self) -> None:
        """Annotate every DLL function used so ctypes performs type checking."""
        d = self._dll

        # Context
        d.fc2CreateGigEContext.restype  = ctypes.c_int
        d.fc2CreateGigEContext.argtypes = [ctypes.POINTER(ctypes.c_void_p)]

        d.fc2DestroyContext.restype  = ctypes.c_int
        d.fc2DestroyContext.argtypes = [ctypes.c_void_p]

        # Discovery
        d.fc2GetNumOfCameras.restype  = ctypes.c_int
        d.fc2GetNumOfCameras.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)
        ]

        d.fc2GetCameraFromIndex.restype  = ctypes.c_int
        d.fc2GetCameraFromIndex.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(fc2PGRGuid)
        ]

        d.fc2GetCameraFromSerialNumber.restype  = ctypes.c_int
        d.fc2GetCameraFromSerialNumber.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(fc2PGRGuid)
        ]

        # Connect / Disconnect
        d.fc2Connect.restype  = ctypes.c_int
        d.fc2Connect.argtypes = [ctypes.c_void_p, ctypes.POINTER(fc2PGRGuid)]

        d.fc2Disconnect.restype  = ctypes.c_int
        d.fc2Disconnect.argtypes = [ctypes.c_void_p]

        # Info
        d.fc2GetCameraInfo.restype  = ctypes.c_int
        d.fc2GetCameraInfo.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(fc2CameraInfo)
        ]

        # Property
        d.fc2GetProperty.restype  = ctypes.c_int
        d.fc2GetProperty.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(fc2Property)
        ]

        d.fc2SetProperty.restype  = ctypes.c_int
        d.fc2SetProperty.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(fc2Property)
        ]

        # Trigger
        d.fc2GetTriggerMode.restype  = ctypes.c_int
        d.fc2GetTriggerMode.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(fc2TriggerMode)
        ]

        d.fc2SetTriggerMode.restype  = ctypes.c_int
        d.fc2SetTriggerMode.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(fc2TriggerMode)
        ]

        # GigE image settings
        d.fc2GetGigEImageSettings.restype  = ctypes.c_int
        d.fc2GetGigEImageSettings.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(fc2GigEImageSettings)
        ]

        d.fc2SetGigEImageSettings.restype  = ctypes.c_int
        d.fc2SetGigEImageSettings.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(fc2GigEImageSettings)
        ]

        # Capture
        d.fc2StartCapture.restype  = ctypes.c_int
        d.fc2StartCapture.argtypes = [ctypes.c_void_p]

        d.fc2StopCapture.restype  = ctypes.c_int
        d.fc2StopCapture.argtypes = [ctypes.c_void_p]

        # Image management
        d.fc2CreateImage.restype  = ctypes.c_int
        d.fc2CreateImage.argtypes = [ctypes.POINTER(fc2Image)]

        d.fc2DestroyImage.restype  = ctypes.c_int
        d.fc2DestroyImage.argtypes = [ctypes.POINTER(fc2Image)]

        d.fc2RetrieveBuffer.restype  = ctypes.c_int
        d.fc2RetrieveBuffer.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(fc2Image)
        ]

        d.fc2ConvertImageTo.restype  = ctypes.c_int
        d.fc2ConvertImageTo.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(fc2Image),
            ctypes.POINTER(fc2Image),
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check(self, err: int, msg: str) -> None:
        """Raise RuntimeError when a FlyCapture2 C-API call fails."""
        if err != FC2_ERROR_OK:
            raise RuntimeError(f"FlyCapture2 error {err}: {msg}")

    def _set_property_abs(
        self, prop_type: int, value: float, auto: bool = False
    ) -> None:
        """Set a camera property in absolute (physical-unit) mode via ctypes."""
        prop = fc2Property()
        prop.type           = prop_type
        prop.absControl     = True
        prop.autoManualMode = auto
        prop.onOff          = True
        prop.absValue       = ctypes.c_float(value)
        err = self._dll.fc2SetProperty(self._ctx, ctypes.byref(prop))
        self._check(err, f"SetProperty type={prop_type} value={value}")

    # ------------------------------------------------------------------
    # Public API – connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """
        Discover the camera on the GigE bus, connect, and apply defaults:
        MONO16 | 10 FPS | 100 ms exposure | 0 dB gain | internal trigger.
        """
        if _USE_PYCAPTURE2:
            self._connect_pc2()
        else:
            self._connect_ctypes()

        self._connected = True
        logger.info("Camera connected.")

        # Apply default imaging parameters
        self.set_pixel_format_mono16()
        self.set_exposure_time(self.DEFAULT_EXPOSURE_S)
        self.set_frame_rate(self.DEFAULT_FPS)
        self.set_gain(self.DEFAULT_GAIN_DB)
        self.set_trigger_mode(enabled=False)

    def _connect_ctypes(self) -> None:
        """ctypes backend – create GigE context and connect to camera."""
        ctx = ctypes.c_void_p()
        err = self._dll.fc2CreateGigEContext(ctypes.byref(ctx))
        self._check(err, "fc2CreateGigEContext")
        self._ctx = ctx

        guid = fc2PGRGuid()
        err = self._dll.fc2GetCameraFromSerialNumber(
            self._ctx, ctypes.c_uint(self._serial), ctypes.byref(guid)
        )

        if err != FC2_ERROR_OK:
            if self._auto_detect:
                num = ctypes.c_uint(0)
                self._dll.fc2GetNumOfCameras(self._ctx, ctypes.byref(num))
                if num.value == 0:
                    raise RuntimeError("No FlyCapture2 GigE cameras detected.")
                logger.warning(
                    "Serial %d not found; connecting to first camera (index 0).",
                    self._serial,
                )
                err = self._dll.fc2GetCameraFromIndex(
                    self._ctx, 0, ctypes.byref(guid)
                )
                self._check(err, "fc2GetCameraFromIndex")
            else:
                raise RuntimeError(
                    f"Camera serial {self._serial} not found on bus."
                )

        err = self._dll.fc2Connect(self._ctx, ctypes.byref(guid))
        self._check(err, "fc2Connect")

        info = fc2CameraInfo()
        if self._dll.fc2GetCameraInfo(self._ctx, ctypes.byref(info)) == FC2_ERROR_OK:
            logger.info(
                "Connected: %s | S/N: %d | Firmware: %s",
                info.modelName.decode(errors="replace"),
                info.serialNumber,
                info.firmwareVersion.decode(errors="replace"),
            )

        # Allocate a reusable image structure
        self._image_obj = fc2Image()
        self._dll.fc2CreateImage(ctypes.byref(self._image_obj))

    def _connect_pc2(self) -> None:
        """PyCapture2 backend – connect to camera."""
        bus = _pc2.BusManager()
        num_cams = bus.getNumOfCameras()
        if num_cams == 0:
            raise RuntimeError("No FlyCapture2 cameras detected.")

        uid = None
        try:
            uid = bus.getCameraFromSerialNumber(self._serial)
        except Exception:
            if self._auto_detect:
                uid = bus.getCameraFromIndex(0)
                logger.warning(
                    "Serial %d not found; using first camera.", self._serial
                )
            else:
                raise RuntimeError(
                    f"Camera serial {self._serial} not found on bus."
                )

        self._cam = _pc2.GigECamera()
        self._cam.connect(uid)
        info = self._cam.getCameraInfo()
        logger.info(
            "Connected: %s | S/N: %d",
            info.modelName.decode(errors="replace"),
            info.serialNumber,
        )

    def disconnect(self) -> None:
        """Stop capture (if running) and cleanly disconnect from the camera."""
        if self._capturing:
            self.stop_capture()

        if _USE_PYCAPTURE2:
            if self._cam is not None:
                self._cam.disconnect()
                self._cam = None
        else:
            if self._ctx is not None:
                if self._image_obj is not None:
                    self._dll.fc2DestroyImage(ctypes.byref(self._image_obj))
                    self._image_obj = None
                self._dll.fc2Disconnect(self._ctx)
                self._dll.fc2DestroyContext(self._ctx)
                self._ctx = None

        self._connected = False
        logger.info("Camera disconnected.")

    # ------------------------------------------------------------------
    # Public API – pixel format
    # ------------------------------------------------------------------

    def set_pixel_format_mono16(self) -> None:
        """Configure GigE streaming to MONO16."""
        if _USE_PYCAPTURE2:
            s = _pc2.GigEImageSettings()
            s.offsetX     = 0
            s.offsetY     = 0
            s.width       = self._width
            s.height      = self._height
            s.pixelFormat = _pc2.PIXEL_FORMAT.MONO16
            self._cam.setGigEImageSettings(s)
        else:
            s = fc2GigEImageSettings()
            err = self._dll.fc2GetGigEImageSettings(
                self._ctx, ctypes.byref(s)
            )
            self._check(err, "fc2GetGigEImageSettings")
            # Update driver dimensions to camera's active geometry if already set
            if s.width > 0 and s.height > 0:
                self._width = s.width
                self._height = s.height
            else:
                s.width = self._width
                s.height = self._height
            s.offsetX     = 0
            s.offsetY     = 0
            s.pixelFormat = ctypes.c_uint(FC2_PIXEL_FORMAT_MONO16)
            err = self._dll.fc2SetGigEImageSettings(
                self._ctx, ctypes.byref(s)
            )
            self._check(err, "fc2SetGigEImageSettings (MONO16)")
        logger.debug("Pixel format → MONO16 (%d x %d).", self._width, self._height)

    # ------------------------------------------------------------------
    # Public API – exposure time
    # ------------------------------------------------------------------

    def set_exposure_time(self, seconds: float) -> None:
        """
        Set absolute shutter (exposure) time.

        Parameters
        ----------
        seconds : Desired exposure in seconds (e.g. 0.1 = 100 ms).
                  Converted to milliseconds before passing to the SDK.
        """
        ms = seconds * 1000.0
        if _USE_PYCAPTURE2:
            p = _pc2.Property(_pc2.PROPERTY_TYPE.SHUTTER)
            p.autoManualMode = False
            p.absControl     = True
            p.onOff          = True
            p.absValue       = ms
            self._cam.setProperty(p)
        else:
            self._set_property_abs(FC2_PROPERTY_TYPE_SHUTTER, ms, auto=False)
        logger.debug("Exposure → %.3f s (%.1f ms).", seconds, ms)

    # ------------------------------------------------------------------
    # Public API – frame rate
    # ------------------------------------------------------------------

    def set_frame_rate(self, fps: float) -> None:
        """
        Set camera frame rate with auto-frame-rate disabled.

        Parameters
        ----------
        fps : Target acquisition rate in frames per second.
        """
        if _USE_PYCAPTURE2:
            p = _pc2.Property(_pc2.PROPERTY_TYPE.FRAME_RATE)
            p.autoManualMode = False
            p.absControl     = True
            p.onOff          = True
            p.absValue       = fps
            self._cam.setProperty(p)
        else:
            self._set_property_abs(FC2_PROPERTY_TYPE_FRAME_RATE, fps, auto=False)
        logger.debug("Frame rate → %.2f FPS.", fps)

    # ------------------------------------------------------------------
    # Public API – gain
    # ------------------------------------------------------------------

    def set_gain(self, gain_db: float) -> None:
        """
        Set analogue gain with auto-gain disabled.

        Parameters
        ----------
        gain_db : Gain in dB (0.0 – 24.0 dB for the GS2-GE-20S4M).
        """
        if _USE_PYCAPTURE2:
            p = _pc2.Property(_pc2.PROPERTY_TYPE.GAIN)
            p.autoManualMode = False
            p.absControl     = True
            p.onOff          = True
            p.absValue       = gain_db
            self._cam.setProperty(p)
        else:
            self._set_property_abs(FC2_PROPERTY_TYPE_GAIN, gain_db, auto=False)
        logger.debug("Gain → %.2f dB.", gain_db)

    # ------------------------------------------------------------------
    # Public API – trigger mode
    # ------------------------------------------------------------------

    def set_trigger_mode(
        self,
        enabled: bool,
        source: int = 0,
        mode: int = 0,
        polarity: int = 1,
    ) -> None:
        """
        Configure the hardware trigger.

        Parameters
        ----------
        enabled  : True  → external TTL trigger (GPIO source).
                   False → free-running internal trigger.
        source   : GPIO pin number used as trigger input (default 0 = GPIO0).
        mode     : FlyCapture2 trigger mode number (0 = standard single shot).
        polarity : 1 = rising edge (default), 0 = falling edge.
        """
        if _USE_PYCAPTURE2:
            t = _pc2.TriggerMode()
            t.onOff    = enabled
            t.source   = source
            t.mode     = mode
            t.polarity = polarity
            self._cam.setTriggerMode(t)
        else:
            t = fc2TriggerMode()
            t.onOff    = enabled
            t.source   = ctypes.c_uint(source)
            t.mode     = ctypes.c_uint(mode)
            t.polarity = ctypes.c_uint(polarity)
            err = self._dll.fc2SetTriggerMode(self._ctx, ctypes.byref(t))
            self._check(err, "fc2SetTriggerMode")

        desc = "External TTL" if enabled else "Internal (free-run)"
        logger.debug("Trigger → %s (source=%d).", desc, source)

    # ------------------------------------------------------------------
    # Public API – acquisition
    # ------------------------------------------------------------------

    def start_capture(self) -> None:
        """Begin continuous DMA-based image acquisition."""
        if not self._connected:
            raise RuntimeError("Camera not connected. Call connect() first.")
        if self._capturing:
            logger.warning("start_capture() called while already capturing.")
            return

        if _USE_PYCAPTURE2:
            self._cam.startCapture()
        else:
            err = self._dll.fc2StartCapture(self._ctx)
            self._check(err, "fc2StartCapture")

        self._capturing = True
        logger.info("Capture started.")

    def grab_frame_numpy(self) -> np.ndarray:
        """
        Retrieve one frame from the camera buffer.

        Returns
        -------
        np.ndarray
            2-D array of shape ``(SENSOR_HEIGHT, SENSOR_WIDTH)`` with
            dtype ``uint16``.  The ctypes backend returns a *copied* array
            so it is safe to store between grab calls.

        Raises
        ------
        RuntimeError
            If the camera is not capturing or the SDK reports an error.
        """
        if not self._capturing:
            raise RuntimeError(
                "Camera is not capturing. Call start_capture() first."
            )
        if _USE_PYCAPTURE2:
            return self._grab_pc2()
        return self._grab_ctypes()

    def _grab_ctypes(self) -> np.ndarray:
        """Internal – ctypes frame grab with zero-copy + safe copy."""
        err = self._dll.fc2RetrieveBuffer(
            self._ctx, ctypes.byref(self._image_obj)
        )
        self._check(err, "fc2RetrieveBuffer")

        img    = self._image_obj
        rows   = img.rows
        cols   = img.cols
        stride = img.stride          # bytes per row
        pdata  = img.pData

        if pdata is None or pdata == 0:
            raise RuntimeError(
                "fc2RetrieveBuffer returned a NULL data pointer."
            )

        # MONO16: stride == 2 * cols (in most configurations)
        # Build a numpy view into the SDK's pinned DMA buffer, then copy.
        n_bytes = int(rows) * int(stride)
        buf  = (ctypes.c_ubyte * n_bytes).from_address(pdata)
        raw  = np.frombuffer(buf, dtype=np.uint8).reshape(rows, stride)
        # Re-interpret as uint16 and slice to actual image width
        frame = raw.view(np.uint16)[:, :cols].copy()
        return frame

    def _grab_pc2(self) -> np.ndarray:
        """Internal – PyCapture2 frame grab."""
        image = _pc2.Image()
        self._cam.retrieveBuffer(image)
        converted = image.convert(_pc2.PIXEL_FORMAT.MONO16)
        data = converted.getData()
        arr  = np.frombuffer(data, dtype=np.uint16).copy()
        return arr.reshape(self.SENSOR_HEIGHT, self.SENSOR_WIDTH)

    def stop_capture(self) -> None:
        """Halt image acquisition and flush the DMA queue."""
        if not self._capturing:
            return
        if _USE_PYCAPTURE2:
            self._cam.stopCapture()
        else:
            self._dll.fc2StopCapture(self._ctx)
        self._capturing = False
        logger.info("Capture stopped.")

    # ------------------------------------------------------------------
    # Context-manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "Grasshopper2Driver":
        self.connect()
        self.start_capture()
        return self

    def __exit__(self, *_) -> None:
        self.stop_capture()
        self.disconnect()

    # ------------------------------------------------------------------
    # Properties / informational helpers
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """True if the driver has an active connection to the camera."""
        return self._connected

    @property
    def is_capturing(self) -> bool:
        """True if the camera is in acquisition mode."""
        return self._capturing

    def get_camera_info(self) -> dict:
        """
        Return a dictionary with basic camera information.

        Keys: ``serial``, ``model``, ``firmware``.
        Returns an empty dict when the camera is not connected.
        """
        if not self._connected:
            return {}

        if _USE_PYCAPTURE2:
            info = self._cam.getCameraInfo()
            return {
                "serial":   info.serialNumber,
                "model":    info.modelName.decode(errors="replace"),
                "firmware": info.firmwareVersion.decode(errors="replace"),
            }

        info = fc2CameraInfo()
        if self._dll.fc2GetCameraInfo(self._ctx, ctypes.byref(info)) == FC2_ERROR_OK:
            return {
                "serial":   info.serialNumber,
                "model":    info.modelName.decode(errors="replace"),
                "firmware": info.firmwareVersion.decode(errors="replace"),
            }
        return {}


# ---------------------------------------------------------------------------
# Quick stand-alone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
    )

    cam = Grasshopper2Driver()
    try:
        cam.connect()
        cam.start_capture()
        frame = cam.grab_frame_numpy()
        print(f"Frame shape : {frame.shape}")
        print(f"Frame dtype : {frame.dtype}")
        print(f"Min / Max   : {frame.min()} / {frame.max()}")
    finally:
        cam.stop_capture()
        cam.disconnect()

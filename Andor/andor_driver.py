"""
andor_driver.py
---------------
Low-level Python ctypes wrapper for the Andor SDK 2.x C-API.

Supports:
  - Real hardware via atmcd64d.dll / atmcd32d.dll
  - Simulation / mock fallback mode when the DLL or camera is not present
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import time
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Andor SDK return-code constants (DRV_*)
# ---------------------------------------------------------------------------
DRV_SUCCESS          = 20002
DRV_ACQUIRING        = 20072
DRV_IDLE             = 20073
DRV_NO_NEW_DATA      = 20024
DRV_ERROR_CODES      = {
    20001: "DRV_ERROR_CODES",
    20002: "DRV_SUCCESS",
    20003: "DRV_VXDNOTINSTALLED",
    20004: "DRV_ERROR_SCAN",
    20005: "DRV_ERROR_CHECK_SUM",
    20006: "DRV_ERROR_FILELOAD",
    20007: "DRV_UNKNOWN_FUNCTION",
    20008: "DRV_ERROR_VXD_INIT",
    20009: "DRV_ERROR_ADDRESS",
    20010: "DRV_ERROR_PAGELOCK",
    20011: "DRV_ERROR_PAGE_UNLOCK",
    20012: "DRV_ERROR_BOARDTEST",
    20013: "DRV_ERROR_ACK",
    20014: "DRV_ACQ_BUFFER",
    20015: "DRV_ACQ_DOWNFIFO_FULL",
    20016: "DRV_PROC_UNKNOWN_INSTRUCTION",
    20017: "DRV_ILLEGAL_OP_CODE",
    20018: "DRV_KINETIC_TIME_NOT_MET",
    20019: "DRV_ACCUM_TIME_NOT_MET",
    20020: "DRV_NO_NEW_DATA",
    20024: "DRV_NO_NEW_DATA",
    20026: "DRV_SPOOLERROR",
    20034: "DRV_TEMPERATURE_OFF",
    20035: "DRV_TEMP_NOT_STABILIZED",
    20036: "DRV_TEMPERATURE_STABILIZED",
    20037: "DRV_TEMPERATURE_NOT_REACHED",
    20038: "DRV_TEMPERATURE_OUT_RANGE",
    20039: "DRV_TEMPERATURE_NOT_SUPPORTED",
    20040: "DRV_TEMPERATURE_DRIFT",
    20049: "DRV_GENERAL_ERRORS",
    20050: "DRV_INVALID_AUX",
    20051: "DRV_COF_NOTLOADED",
    20052: "DRV_FPGAPROG",
    20053: "DRV_FLEXERROR",
    20054: "DRV_GPIBERROR",
    20064: "DRV_DATATYPE",
    20065: "DRV_DRIVER_ERRORS",
    20066: "DRV_P1INVALID",
    20067: "DRV_P2INVALID",
    20068: "DRV_P3INVALID",
    20069: "DRV_P4INVALID",
    20070: "DRV_INIERROR",
    20071: "DRV_COFERROR",
    20072: "DRV_ACQUIRING",
    20073: "DRV_IDLE",
    20074: "DRV_TEMPCYCLE",
    20075: "DRV_NOT_INITIALIZED",
    20076: "DRV_P5INVALID",
    20077: "DRV_P6INVALID",
    20083: "DRV_USBERROR",
    20084: "DRV_IOCERROR",
    20091: "DRV_NOT_SUPPORTED",
    20099: "DRV_BINNING_ERROR",
    20990: "DRV_NOCAMERA",
    20991: "DRV_NOT_SUPPORTED",
    20992: "DRV_NOT_AVAILABLE",
}


def _code_to_str(code: int) -> str:
    return DRV_ERROR_CODES.get(code, f"UNKNOWN_CODE_{code}")


class _MockDLL:
    def __init__(self) -> None:
        self._width  = 1024
        self._height = 1024
        self._frame_index = 0
        logger.info("[SIMULATION] MockDLL active – no real camera.")

    def _ok(self):
        return ctypes.c_uint32(DRV_SUCCESS)

    def Initialize(self, path: bytes) -> ctypes.c_uint32:
        logger.info("[SIMULATION] Initialize(%s)", path)
        return self._ok()

    def ShutDown(self) -> ctypes.c_uint32:
        logger.info("[SIMULATION] ShutDown()")
        return self._ok()

    def GetDetector(self, px, py) -> ctypes.c_uint32:
        px._obj.value = self._width
        py._obj.value = self._height
        return self._ok()

    def SetExposureTime(self, t: ctypes.c_float) -> ctypes.c_uint32:
        return self._ok()

    def SetTriggerMode(self, mode: ctypes.c_int) -> ctypes.c_uint32:
        return self._ok()

    def SetReadMode(self, mode: ctypes.c_int) -> ctypes.c_uint32:
        return self._ok()

    def SetAcquisitionMode(self, mode: ctypes.c_int) -> ctypes.c_uint32:
        return self._ok()

    def SetNumberKinetics(self, n: ctypes.c_int) -> ctypes.c_uint32:
        return self._ok()

    def SetImage(self, hbin, vbin, hstart, hend, vstart, vend) -> ctypes.c_uint32:
        return self._ok()

    def StartAcquisition(self) -> ctypes.c_uint32:
        self._frame_index = 0
        return self._ok()

    def AbortAcquisition(self) -> ctypes.c_uint32:
        return self._ok()

    def WaitForAcquisition(self) -> ctypes.c_uint32:
        time.sleep(0.05)
        return self._ok()

    def GetStatus(self, status_ptr) -> ctypes.c_uint32:
        status_ptr._obj.value = DRV_IDLE
        return self._ok()

    def GetAcquiredData16(self, buf_ptr, size: ctypes.c_ulong) -> ctypes.c_uint32:
        n = size.value
        w = self._width
        h = self._height
        x = np.linspace(-3, 3, w)
        y = np.linspace(-3, 3, h)
        cx = np.sin(self._frame_index * 0.15) * 1.5
        cy = np.cos(self._frame_index * 0.10) * 1.5
        xx, yy = np.meshgrid(x - cx, y - cy)
        spot  = np.exp(-(xx**2 + yy**2) / 0.8)
        noise = np.random.normal(100, 15, (h, w))
        frame = np.clip(spot * 55000 + noise, 0, 65535).astype(np.uint16)
        ctypes.memmove(buf_ptr, frame.ctypes.data, frame.nbytes)
        self._frame_index += 1
        return self._ok()


def _load_real_dll(sdk_dir: str) -> ctypes.CDLL:
    arch = platform.architecture()[0]
    dll_name = "atmcd64d.dll" if arch == "64bit" else "atmcd32d.dll"
    dll_path = os.path.join(sdk_dir, dll_name)
    if not os.path.isfile(dll_path):
        raise FileNotFoundError(f"Andor DLL not found: {dll_path}")
    dll = ctypes.CDLL(dll_path)
    logger.info("Loaded Andor DLL from: %s", dll_path)
    return dll


class AndorCameraDriver:
    SDK_DIR_DEFAULT = r"C:\Program Files\Andor SDK"

    def __init__(
        self,
        sdk_dir: str = SDK_DIR_DEFAULT,
        simulation: Optional[bool] = None,
    ) -> None:
        self.sdk_dir      = sdk_dir
        self.width        = 0
        self.height       = 0
        self._initialized = False
        self._simulated   = False
        self._dll: object = None
        self._last_exposure_s: float = 0.1
        self._last_trigger_mode: int = 0
        self._last_trigger_name: str = "INTERNAL/OFF"
        self._setup_dll(simulation)

    def _setup_dll(self, simulation: Optional[bool]) -> None:
        if simulation is True:
            self._dll = _MockDLL()
            self._simulated = True
            logger.info("Simulation mode forced.")
            return

        try:
            self._dll = _load_real_dll(self.sdk_dir)
            self._simulated = False
        except (FileNotFoundError, OSError) as exc:
            if simulation is False:
                raise RuntimeError(
                    f"Real hardware required but DLL could not be loaded: {exc}"
                ) from exc
            logger.warning("Andor DLL not found (%s). Falling back to simulation.", exc)
            self._dll = _MockDLL()
            self._simulated = True

    def _check(self, code: int, fn_name: str = "") -> None:
        if code != DRV_SUCCESS:
            msg = f"Andor SDK error in {fn_name}: {_code_to_str(code)} (code={code})"
            logger.error(msg)
            raise RuntimeError(msg)

    def _call(self, fn_name: str, *args) -> int:
        fn = getattr(self._dll, fn_name)
        result = fn(*args)
        return result.value if isinstance(result, ctypes.c_uint32) else int(result)

    def _sim_call(self, fn_name: str, *args) -> None:
        getattr(self._dll, fn_name)(*args)

    def initialize(self) -> None:
        if self._initialized:
            return

        logger.info("Initializing Andor camera (sim=%s)…", self._simulated)
        path_bytes = self.sdk_dir.encode("utf-8")

        if self._simulated:
            mock: _MockDLL = self._dll  # type: ignore[assignment]
            mock.Initialize(path_bytes)
            self.width  = mock._width
            self.height = mock._height
        else:
            code = self._call("Initialize", ctypes.c_char_p(path_bytes))
            self._check(code, "Initialize")
            c_w, c_h = ctypes.c_int(0), ctypes.c_int(0)
            code = self._call("GetDetector", ctypes.byref(c_w), ctypes.byref(c_h))
            self._check(code, "GetDetector")
            self.width, self.height = c_w.value, c_h.value

        logger.info("Detector size: %d x %d px", self.width, self.height)
        self._initialized = True

    def shutdown(self) -> None:
        if not self._initialized:
            return
        if self._simulated:
            self._sim_call("ShutDown")
        else:
            self._call("ShutDown")
        self._initialized = False
        logger.info("Camera shut down.")

    def set_exposure_time(self, exposure_s: float) -> None:
        self._require_init()
        self._last_exposure_s = exposure_s
        arg = ctypes.c_float(exposure_s)
        if self._simulated:
            self._sim_call("SetExposureTime", arg)
        else:
            self._check(self._call("SetExposureTime", arg), "SetExposureTime")
        logger.debug("Exposure time: %.4f s", exposure_s)

    def set_trigger_mode(self, mode: int) -> None:
        self._require_init()
        self._last_trigger_mode = mode
        self._last_trigger_name = "EXTERNAL_TTL" if mode == 1 else "INTERNAL/OFF"
        arg = ctypes.c_int(mode)
        if self._simulated:
            self._sim_call("SetTriggerMode", arg)
        else:
            self._check(self._call("SetTriggerMode", arg), "SetTriggerMode")
        logger.debug("Trigger mode: %d (%s)", mode, self._last_trigger_name)

    def set_trigger_mode_by_name(self, mode_str: str) -> None:
        mode_idx = 1 if mode_str.upper() == "EXTERNAL_TTL" else 0
        self.set_trigger_mode(mode_idx)

    def get_camera_status_info(self) -> dict:
        if not self._initialized:
            return {
                "exposure_ms": 0.0,
                "trigger_mode": "N/A",
                "detector_size": "0 x 0",
                "status_str": "UNINITIALIZED",
                "mode": "UNKNOWN",
            }

        st_code = self.get_status()
        st_str = _code_to_str(st_code)
        mode_str = "SIMULATED" if self._simulated else "REAL"

        return {
            "exposure_ms": self._last_exposure_s * 1000.0,
            "trigger_mode": self._last_trigger_name,
            "detector_size": f"{self.width} x {self.height} px",
            "status_str": st_str,
            "mode": mode_str,
        }

    def set_acquisition_params(
        self,
        num_frames: int = 1,
        acq_mode: int = 1,
        read_mode: int = 4,
    ) -> None:
        self._require_init()

        steps = [
            ("SetReadMode",        ctypes.c_int(read_mode)),
            ("SetAcquisitionMode", ctypes.c_int(acq_mode)),
            ("SetNumberKinetics",  ctypes.c_int(num_frames)),
        ]
        for fn, arg in steps:
            if self._simulated:
                self._sim_call(fn, arg)
            else:
                self._check(self._call(fn, arg), fn)

        img_args = (
            ctypes.c_int(1), ctypes.c_int(1),
            ctypes.c_int(1), ctypes.c_int(self.width),
            ctypes.c_int(1), ctypes.c_int(self.height),
        )
        if self._simulated:
            self._sim_call("SetImage", *img_args)
        else:
            self._check(self._call("SetImage", *img_args), "SetImage")

    def start_acquisition(self) -> None:
        self._require_init()
        if self._simulated:
            self._sim_call("StartAcquisition")
        else:
            self._check(self._call("StartAcquisition"), "StartAcquisition")

    def abort_acquisition(self) -> None:
        if not self._initialized:
            return
        if self._simulated:
            self._sim_call("AbortAcquisition")
        else:
            try:
                self._call("AbortAcquisition")
            except RuntimeError:
                pass

    def wait_for_acquisition(self) -> None:
        self._require_init()
        if self._simulated:
            self._sim_call("WaitForAcquisition")
        else:
            self._check(self._call("WaitForAcquisition"), "WaitForAcquisition")

    def get_status(self) -> int:
        if not self._initialized:
            return DRV_IDLE
        c_status = ctypes.c_int(DRV_IDLE)
        if self._simulated:
            self._sim_call("GetStatus", ctypes.byref(c_status))
        else:
            self._check(
                self._call("GetStatus", ctypes.byref(c_status)), "GetStatus"
            )
        return c_status.value

    def get_acquired_data16(self) -> np.ndarray:
        self._require_init()
        n_pixels = self.width * self.height
        buf  = (ctypes.c_uint16 * n_pixels)()
        size = ctypes.c_ulong(n_pixels)

        if self._simulated:
            self._sim_call("GetAcquiredData16", buf, size)
        else:
            self._check(
                self._call("GetAcquiredData16", buf, size), "GetAcquiredData16"
            )

        frame = np.frombuffer(buf, dtype=np.uint16).reshape(self.height, self.width)
        return frame.copy()

    def acquire_single_frame(
        self,
        exposure_s: float = 0.1,
        trigger_mode: int = 0,
    ) -> np.ndarray:
        self.set_exposure_time(exposure_s)
        self.set_trigger_mode(trigger_mode)
        self.set_acquisition_params(num_frames=1, acq_mode=1)
        self.start_acquisition()
        self.wait_for_acquisition()
        return self.get_acquired_data16()

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def is_simulated(self) -> bool:
        return self._simulated

    @property
    def detector_size(self) -> Tuple[int, int]:
        return self.width, self.height

    def _require_init(self) -> None:
        if not self._initialized:
            raise RuntimeError("Camera not initialized. Call initialize() first.")

    def __enter__(self) -> "AndorCameraDriver":
        self.initialize()
        return self

    def __exit__(self, *_) -> None:
        self.shutdown()
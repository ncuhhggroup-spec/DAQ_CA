# core/data_manager.py
"""
DataManager module – implements the Manager pattern for handling zero‑copy RAM buffers,
local persistence (HDF5/TIFF), basic image processing (2‑D Gaussian fit), and experiment
log bookkeeping.
"""

from __future__ import annotations

import pathlib
from typing import Tuple, Dict, Any, Optional

import numpy as np
import pandas as pd
import h5py
import tifffile
from scipy.optimize import curve_fit


class DataManager:
    """Central manager for data buffers and persistence.

    Attributes
    ----------
    buffer : np.ndarray
        Pre‑allocated zero‑copy RAM buffer used for image acquisition.
    shape : Tuple[int, ...]
        Shape of the allocated buffer.
    dtype : np.dtype
        Data type of the buffer (default ``np.float32``).
    """

    def __init__(self, shape: Tuple[int, int, int] | None = None, dtype: np.dtype = np.float32):
        """Create a DataManager.

        Parameters
        ----------
        shape : tuple or None
            Desired buffer shape ``(frames, height, width)``. If ``None`` the buffer is
            allocated later via :meth:`allocate_buffer`.
        dtype : np.dtype, optional
            Data type for the buffer.
        """
        self.buffer: Optional[np.ndarray] = None
        self.shape = shape
        self.dtype = np.dtype(dtype)
        if shape is not None:
            self.allocate_buffer(shape)

    # ---------------------------------------------------------------------
    # Buffer management
    # ---------------------------------------------------------------------
    def allocate_buffer(self, shape: Tuple[int, int, int]) -> None:
        """Allocate (or re‑allocate) a zero‑copy RAM buffer.

        The buffer is created with ``np.empty`` to avoid unnecessary zero‑initialisation
        and then explicitly ``fill(0)`` so the memory is committed.
        """
        self.shape = shape
        self.buffer = np.empty(shape, dtype=self.dtype)
        self.buffer.fill(0)  # ensure memory pages are touched

    # ---------------------------------------------------------------------
    # Persistence helpers
    # ---------------------------------------------------------------------
    def save_hdf5(self, file_path: str | pathlib.Path) -> None:
        """Save the current buffer to an HDF5 file.

        Parameters
        ----------
        file_path : str or Path
            Destination file. The dataset is stored under ``/data``.
        """
        if self.buffer is None:
            raise RuntimeError("Buffer not allocated – cannot save HDF5.")
        file_path = pathlib.Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with h5py.File(file_path, "w") as h5:
            h5.create_dataset("data", data=self.buffer, compression="gzip")

    def save_tiff(self, file_path: str | pathlib.Path, metadata: Dict[str, Any] | None = None) -> None:
        """Save a single frame (or stack) to a TIFF file with optional metadata.

        Parameters
        ----------
        file_path : str or Path
            Destination TIFF file.
        metadata : dict, optional
            Dictionary of TIFF tags. Keys must be valid TIFF tag identifiers or
            ``tifffile``‑compatible ``description`` strings.
        """
        if self.buffer is None:
            raise RuntimeError("Buffer not allocated – cannot save TIFF.")
        file_path = pathlib.Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        tifffile.imwrite(file_path, self.buffer, metadata=metadata)

    # ---------------------------------------------------------------------
    # Image processing – 2‑D Gaussian fitting
    # ---------------------------------------------------------------------
    @staticmethod
    def _gaussian_2d(xy: Tuple[np.ndarray, np.ndarray], amplitude: float, xo: float, yo: float, sigma_x: float, sigma_y: float, offset: float) -> np.ndarray:
        """2‑D Gaussian function used for curve fitting.
        """
        (x, y) = xy
        xo = float(xo)
        yo = float(yo)
        g = amplitude * np.exp(
            -(((x - xo) ** 2) / (2 * sigma_x ** 2) + ((y - yo) ** 2) / (2 * sigma_y ** 2))
        ) + offset
        return g.ravel()

    def fit_gaussian_2d(self, image: np.ndarray, roi: Tuple[int, int, int, int] | None = None) -> Dict[str, float]:
        """Fit a 2‑D Gaussian to *image* (or a region of interest).

        Parameters
        ----------
        image : np.ndarray
            2‑D image data.
        roi : tuple (x, y, w, h), optional
            Region of interest; if ``None`` the full image is used.

        Returns
        -------
        dict
            Fitted parameters ``amplitude``, ``xo``, ``yo``, ``sigma_x``, ``sigma_y``, ``offset``.
        """
        if roi is not None:
            x, y, w, h = roi
            img = image[y : y + h, x : x + w]
        else:
            img = image
        # Create meshgrid
        y_idx, x_idx = np.indices(img.shape)
        initial_guess = (
            img.max(),  # amplitude
            img.shape[1] / 2,  # xo
            img.shape[0] / 2,  # yo
            img.shape[1] / 4,  # sigma_x
            img.shape[0] / 4,  # sigma_y
            img.min(),  # offset
        )
        try:
            popt, _ = curve_fit(self._gaussian_2d, (x_idx, y_idx), img.ravel(), p0=initial_guess)
        except Exception as e:
            raise RuntimeError(f"Gaussian fit failed: {e}")
        keys = ["amplitude", "xo", "yo", "sigma_x", "sigma_y", "offset"]
        return dict(zip(keys, popt))

    # ---------------------------------------------------------------------
    # Experiment log handling (Excel) – auto‑append rows
    # ---------------------------------------------------------------------
    @staticmethod
    def append_experiment_log(entry: Dict[str, Any], log_path: str | pathlib.Path = "experiment_log.xlsx") -> None:
        """Append a single row to the experiment log Excel file.

        If the file does not exist it is created with a single sheet named ``Log``.
        ``entry`` keys become column headers; missing columns are filled with ``NaN``.
        """
        log_path = pathlib.Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if log_path.is_file():
            df = pd.read_excel(log_path, sheet_name="Log")
            new_df = pd.DataFrame([entry])
            df = pd.concat([df, new_df], ignore_index=True)
        else:
            df = pd.DataFrame([entry])
        with pd.ExcelWriter(log_path, engine="openpyxl", mode="w") as writer:
            df.to_excel(writer, sheet_name="Log", index=False)

# End of DataManager

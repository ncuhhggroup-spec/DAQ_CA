"""
camera_analysis.py
==================
Image analysis routines for beam diagnostics:
- 2D Gaussian Fitting over selected ROI
- Beam centroid (x0, y0), widths (sigma_x, sigma_y), FWHM_x, FWHM_y, orientation angle (theta), and RMSE residuals
- Projection profiles along X and Y axes
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from scipy.optimize import curve_fit


@dataclass
class GaussianFitResult:
    """Results from 2D Gaussian beam fitting."""
    success: bool
    x0: float
    y0: float
    sigma_x: float
    sigma_y: float
    fwhm_x: float
    fwhm_y: float
    amplitude: float
    offset: float
    theta_deg: float
    residual_rmse: float
    message: str = "Success"
    
    # Global coordinates in full sensor image
    global_x0: float = 0.0
    global_y0: float = 0.0


def gaussian_2d_rot(
    xy: Tuple[np.ndarray, np.ndarray],
    amplitude: float,
    x0: float,
    y0: float,
    sigma_x: float,
    sigma_y: float,
    theta: float,
    offset: float,
) -> np.ndarray:
    """General 2D elliptical Gaussian with arbitrary rotation."""
    x, y = xy
    cos_t = np.cos(theta)
    sin_t = np.sin(theta)
    
    x_rot = cos_t * (x - x0) + sin_t * (y - y0)
    y_rot = -sin_t * (x - x0) + cos_t * (y - y0)
    
    g = offset + amplitude * np.exp(
        -0.5 * ((x_rot / (sigma_x + 1e-7)) ** 2 + (y_rot / (sigma_y + 1e-7)) ** 2)
    )
    return g.ravel()


def fit_2d_gaussian(
    image: np.ndarray,
    roi_coords: Optional[Tuple[int, int, int, int]] = None,
) -> GaussianFitResult:
    """
    Perform 2D Gaussian fitting over the image or ROI.

    Parameters
    ----------
    image : 2D numpy array (uint16 or float).
    roi_coords : Optional (x_min, y_min, x_max, y_max) defining ROI box.

    Returns
    -------
    GaussianFitResult with fitted parameters and residuals.
    """
    if image is None or image.size == 0:
        return GaussianFitResult(
            success=False, x0=0, y0=0, sigma_x=0, sigma_y=0,
            fwhm_x=0, fwhm_y=0, amplitude=0, offset=0, theta_deg=0,
            residual_rmse=0, message="Empty image"
        )

    # Extract ROI sub-array
    if roi_coords is not None:
        x_min, y_min, x_max, y_max = roi_coords
        h, w = image.shape
        x_min = max(0, min(x_min, w - 2))
        x_max = max(x_min + 2, min(x_max, w))
        y_min = max(0, min(y_min, h - 2))
        y_max = max(y_min + 2, min(y_max, h))
        sub_img = image[y_min:y_max, x_min:x_max].astype(np.float64)
        offset_x, offset_y = x_min, y_min
    else:
        sub_img = image.astype(np.float64)
        offset_x, offset_y = 0, 0

    sub_h, sub_w = sub_img.shape
    if sub_h < 3 or sub_w < 3:
        return GaussianFitResult(
            success=False, x0=0, y0=0, sigma_x=0, sigma_y=0,
            fwhm_x=0, fwhm_y=0, amplitude=0, offset=0, theta_deg=0,
            residual_rmse=0, message="ROI too small"
        )

    # Coordinates grid for ROI
    x = np.arange(sub_w, dtype=np.float64)
    y = np.arange(sub_h, dtype=np.float64)
    xx, yy = np.meshgrid(x, y)

    # Initial parameter estimates (moments)
    bg_est = float(np.percentile(sub_img, 10))
    cleaned = np.maximum(sub_img - bg_est, 0)
    total = np.sum(cleaned)

    if total <= 0:
        # Flat / dark background
        x0_est = sub_w / 2.0
        y0_est = sub_h / 2.0
        sigma_x_est = sub_w / 6.0
        sigma_y_est = sub_h / 6.0
        amp_est = float(np.max(sub_img) - bg_est)
    else:
        x0_est = float(np.sum(xx * cleaned) / total)
        y0_est = float(np.sum(yy * cleaned) / total)
        var_x = float(np.sum(((xx - x0_est) ** 2) * cleaned) / total)
        var_y = float(np.sum(((yy - y0_est) ** 2) * cleaned) / total)
        sigma_x_est = max(1.0, np.sqrt(var_x))
        sigma_y_est = max(1.0, np.sqrt(var_y))
        amp_est = max(1.0, float(np.max(sub_img) - bg_est))

    p0 = [amp_est, x0_est, y0_est, sigma_x_est, sigma_y_est, 0.0, bg_est]
    
    # Parameter bounds
    bounds = (
        [0.0, 0.0, 0.0, 0.5, 0.5, -np.pi, 0.0],
        [65535.0 * 2, sub_w, sub_h, sub_w * 2, sub_h * 2, np.pi, 65535.0],
    )

    try:
        popt, _ = curve_fit(
            gaussian_2d_rot,
            (xx, yy),
            sub_img.ravel(),
            p0=p0,
            bounds=bounds,
            maxfev=1500,
        )
        
        amp, x0, y0, sig_x, sig_y, theta, bg = popt
        sig_x = abs(sig_x)
        sig_y = abs(sig_y)
        
        # Calculate fitted model & residuals (RMSE)
        fit_model = gaussian_2d_rot((xx, yy), *popt).reshape((sub_h, sub_w))
        residuals = sub_img - fit_model
        rmse = float(np.sqrt(np.mean(residuals ** 2)))
        
        fwhm_factor = 2.0 * np.sqrt(2.0 * np.log(2.0))  # ~2.35482
        fwhm_x = float(sig_x * fwhm_factor)
        fwhm_y = float(sig_y * fwhm_factor)
        
        return GaussianFitResult(
            success=True,
            x0=float(x0),
            y0=float(y0),
            sigma_x=float(sig_x),
            sigma_y=float(sig_y),
            fwhm_x=fwhm_x,
            fwhm_y=fwhm_y,
            amplitude=float(amp),
            offset=float(bg),
            theta_deg=float(np.degrees(theta) % 180.0),
            residual_rmse=rmse,
            message="Fit converged",
            global_x0=float(x0 + offset_x),
            global_y0=float(y0 + offset_y),
        )
    except Exception as e:
        return GaussianFitResult(
            success=False,
            x0=x0_est,
            y0=y0_est,
            sigma_x=sigma_x_est,
            sigma_y=sigma_y_est,
            fwhm_x=float(sigma_x_est * 2.355),
            fwhm_y=float(sigma_y_est * 2.355),
            amplitude=amp_est,
            offset=bg_est,
            theta_deg=0.0,
            residual_rmse=0.0,
            message=f"Fit failed: {e}",
            global_x0=float(x0_est + offset_x),
            global_y0=float(y0_est + offset_y),
        )

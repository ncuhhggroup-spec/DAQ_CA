"""
read_gige_tiff.py
=================
Reader utility for multi-page TIFF files saved by the Dual GigE Camera GUI
(dual_gige_gui.py / dual_gige_driver.py).

File Structure (written by DualGigECameraController.save_tiff_with_metadata):
    Page 0  – Raw 16-bit beam image (uint16, 1224 x 1624)
              ImageDescription tag contains a JSON blob with full metadata.
    Page 1  – Raw 16-bit background image (uint16, 1224 x 1624), OPTIONAL.
              Present only when "has_background_attached" is True in metadata.

Usage
-----
Command-line (show summary + save PNG):
    python read_gige_tiff.py path/to/file.tif

Programmatic:
    from read_gige_tiff import GigETiffReader

    r = GigETiffReader("Cam_NearField_20260922_143000.tif")
    print(r.metadata)
    img  = r.image          # np.ndarray uint16
    bg   = r.background     # np.ndarray uint16, or None
    diff = r.background_subtracted()   # float32 image, or None

Author : Antigravity DAQ Module
Date   : 2026-09-22
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import tifffile


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------

@dataclass
class GigETiffData:
    """All data extracted from a single GigE camera TIFF file."""

    filepath: str
    """Absolute path to the source TIFF file."""

    metadata: dict = field(default_factory=dict)
    """JSON metadata parsed from Page 0 ImageDescription tag."""

    image: Optional[np.ndarray] = None
    """Raw beam image (uint16, H x W)."""

    background: Optional[np.ndarray] = None
    """Raw background frame (uint16, H x W), or None if not embedded."""

    # Convenience properties derived from metadata ---------------------------

    @property
    def channel_name(self) -> str:
        return self.metadata.get("channel_name", "Unknown")

    @property
    def timestamp(self) -> str:
        return self.metadata.get("timestamp", "")

    @property
    def exposure_ms(self) -> float:
        return float(self.metadata.get("exposure_seconds", 0.0)) * 1000.0

    @property
    def gain_db(self) -> float:
        return float(self.metadata.get("gain_db", 0.0))

    @property
    def camera_index(self) -> int:
        return int(self.metadata.get("camera_index", -1))

    @property
    def camera_serial(self) -> int:
        return int(self.metadata.get("camera_serial", 0))

    @property
    def user_notes(self) -> str:
        return self.metadata.get("user_notes", "")

    @property
    def has_background(self) -> bool:
        return self.background is not None

    @property
    def analysis(self) -> Optional[dict]:
        """2D Gaussian fit results if stored in metadata, else None."""
        return self.metadata.get("analysis", None)

    def background_subtracted(self) -> Optional[np.ndarray]:
        """
        Return the beam image minus the background, clipped to >= 0.
        Returns a float32 array, or None if no background is available.
        """
        if self.image is None or self.background is None:
            return None
        return np.clip(
            self.image.astype(np.float32) - self.background.astype(np.float32),
            0.0,
            None,
        )

    def summary(self) -> str:
        """Human-readable one-page summary of the file contents."""
        lines = [
            f"File         : {self.filepath}",
            f"Channel      : {self.channel_name}  (Camera {self.camera_index}, S/N {self.camera_serial})",
            f"Timestamp    : {self.timestamp}",
            f"Exposure     : {self.exposure_ms:.2f} ms",
            f"Gain         : {self.gain_db:.1f} dB",
            f"User Notes   : {self.user_notes or '—'}",
        ]
        if self.image is not None:
            lines += [
                f"Image Shape  : {self.image.shape}  dtype={self.image.dtype}",
                f"Image Stats  : min={self.image.min()}  max={self.image.max()}  "
                f"mean={self.image.mean():.1f}  std={self.image.std():.1f}",
            ]
        if self.has_background:
            lines += [
                f"Background   : ATTACHED  mean={self.background.mean():.1f}  "
                f"std={self.background.std():.1f}",
            ]
        else:
            lines.append("Background   : not embedded")

        if self.analysis:
            a = self.analysis
            lines += [
                "",
                "--- 2D Gaussian Fit Results ---",
                f"  Beam Center   : ({a.get('center_x', '?'):.1f},  {a.get('center_y', '?'):.1f}) px",
                f"  FWHM X / Y    : {a.get('fwhm_x', '?'):.1f} / {a.get('fwhm_y', '?'):.1f} px",
                f"  Fit RMSE      : {a.get('rmse', '?'):.2f} ADU",
            ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Reader class
# ---------------------------------------------------------------------------

class GigETiffReader:
    """
    Load and parse a TIFF file saved by dual_gige_gui / DualGigECameraController.

    Parameters
    ----------
    filepath : str | Path
        Path to the .tif / .tiff file.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If the file cannot be parsed as a GigE camera TIFF.
    """

    def __init__(self, filepath: str | Path) -> None:
        self._path = Path(filepath).resolve()
        if not self._path.is_file():
            raise FileNotFoundError(f"TIFF file not found: {self._path}")
        self._data = self._load()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def data(self) -> GigETiffData:
        """Return the fully parsed :class:`GigETiffData` container."""
        return self._data

    @property
    def image(self) -> Optional[np.ndarray]:
        """Raw beam image (uint16)."""
        return self._data.image

    @property
    def background(self) -> Optional[np.ndarray]:
        """Embedded background frame (uint16) or None."""
        return self._data.background

    @property
    def metadata(self) -> dict:
        """Parsed JSON metadata dictionary from Page 0."""
        return self._data.metadata

    def background_subtracted(self) -> Optional[np.ndarray]:
        """Background-subtracted image (float32), or None."""
        return self._data.background_subtracted()

    def summary(self) -> str:
        """Human-readable summary string."""
        return self._data.summary()

    # ------------------------------------------------------------------
    # Internal loader
    # ------------------------------------------------------------------

    def _load(self) -> GigETiffData:
        result = GigETiffData(filepath=str(self._path))

        with tifffile.TiffFile(str(self._path)) as tif:
            pages = tif.pages

            if len(pages) == 0:
                raise ValueError("TIFF file has no pages.")

            # --- Page 0: raw beam image & metadata ---
            page0 = pages[0]
            result.image = page0.asarray()

            desc = page0.description
            if desc:
                try:
                    result.metadata = json.loads(desc)
                except json.JSONDecodeError:
                    # Fall back: try to extract JSON substring (some TIFF writers add extra text)
                    start = desc.find("{")
                    end = desc.rfind("}") + 1
                    if start != -1 and end > start:
                        try:
                            result.metadata = json.loads(desc[start:end])
                        except json.JSONDecodeError:
                            result.metadata = {"_raw_description": desc}
                    else:
                        result.metadata = {"_raw_description": desc}

            # --- Page 1: optional background ---
            if result.metadata.get("has_background_attached", False) and len(pages) >= 2:
                result.background = pages[1].asarray()

        return result


# ---------------------------------------------------------------------------
# Batch loader helper
# ---------------------------------------------------------------------------

def load_tiff(filepath: str | Path) -> GigETiffData:
    """
    Convenience function – load a single TIFF and return its :class:`GigETiffData`.

    Example
    -------
    >>> from read_gige_tiff import load_tiff
    >>> d = load_tiff("Cam_NearField_20260922_143000.tif")
    >>> print(d.summary())
    >>> img_sub = d.background_subtracted()
    """
    return GigETiffReader(filepath).data


def load_tiff_batch(directory: str | Path, pattern: str = "*.tif") -> list[GigETiffData]:
    """
    Load all matching TIFF files from a directory.

    Parameters
    ----------
    directory : str | Path
        Folder to search.
    pattern : str
        Glob pattern (default: ``"*.tif"``).

    Returns
    -------
    list[GigETiffData]
        Sorted list of loaded data objects.
    """
    folder = Path(directory)
    files = sorted(folder.glob(pattern)) + sorted(folder.glob(pattern.replace(".tif", ".tiff")))
    results = []
    for f in files:
        try:
            results.append(load_tiff(f))
        except Exception as exc:
            print(f"[WARN] Skipping {f.name}: {exc}", file=sys.stderr)
    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _cli():
    parser = argparse.ArgumentParser(
        prog="read_gige_tiff",
        description="Read and inspect TIFF files saved by the Dual GigE Camera GUI.",
    )
    parser.add_argument("filepath", help="Path to the .tif file (or directory for batch mode).")
    parser.add_argument("--batch", action="store_true",
                        help="Treat filepath as a directory and load all .tif files inside.")
    parser.add_argument("--pattern", default="*.tif",
                        help="Glob pattern for batch mode (default: '*.tif').")
    parser.add_argument("--save-png", action="store_true",
                        help="Save a normalised PNG preview alongside the TIFF (requires matplotlib).")
    parser.add_argument("--save-bg-subtracted", action="store_true",
                        help="Save a background-subtracted PNG preview (requires matplotlib).")
    parser.add_argument("--export-json", action="store_true",
                        help="Write metadata to a .json sidecar file.")
    args = parser.parse_args()

    def _process_one(d: GigETiffData):
        print("=" * 72)
        print(d.summary())
        print()

        if args.export_json:
            json_out = Path(d.filepath).with_suffix(".metadata.json")
            with open(json_out, "w", encoding="utf-8") as f:
                json.dump(d.metadata, f, indent=2)
            print(f"  [JSON] Metadata written to: {json_out}")

        if args.save_png or args.save_bg_subtracted:
            try:
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt

                def _save_img(arr: np.ndarray, out_path: Path, title: str):
                    fig, ax = plt.subplots(figsize=(10, 8))
                    im = ax.imshow(arr, cmap="inferno", origin="upper",
                                   vmin=np.percentile(arr, 0.5),
                                   vmax=np.percentile(arr, 99.9))
                    plt.colorbar(im, ax=ax, label="Intensity (ADU)")
                    ax.set_title(title, fontsize=11)
                    ax.set_xlabel("X (px)")
                    ax.set_ylabel("Y (px)")
                    plt.tight_layout()
                    plt.savefig(str(out_path), dpi=120)
                    plt.close(fig)
                    print(f"  [PNG] Saved: {out_path}")

                if args.save_png and d.image is not None:
                    out = Path(d.filepath).with_suffix(".preview.png")
                    _save_img(d.image.astype(np.float32), out,
                              f"{d.channel_name} — Raw Image  [{d.timestamp}]")

                if args.save_bg_subtracted:
                    sub = d.background_subtracted()
                    if sub is not None:
                        out = Path(d.filepath).with_suffix(".bg_sub.png")
                        _save_img(sub, out,
                                  f"{d.channel_name} — BG Subtracted  [{d.timestamp}]")
                    else:
                        print("  [WARN] No background attached – skipping BG-subtracted PNG.")

            except ImportError:
                print("  [ERROR] matplotlib is required for PNG export. Install with: pip install matplotlib")

    if args.batch:
        data_list = load_tiff_batch(args.filepath, pattern=args.pattern)
        print(f"Found {len(data_list)} TIFF file(s) in: {args.filepath}\n")
        for d in data_list:
            _process_one(d)
    else:
        d = load_tiff(args.filepath)
        _process_one(d)


if __name__ == "__main__":
    _cli()

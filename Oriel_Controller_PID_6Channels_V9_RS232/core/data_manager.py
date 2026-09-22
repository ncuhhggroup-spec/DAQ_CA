import os
import time
import datetime
from typing import Optional, Dict, Any
import numpy as np
import pandas as pd

try:
    import h5py
except ImportError:
    h5py = None


class DataManager:
    """Manager pattern for Zero-Copy RAM allocation, persistence (HDF5/NPZ), and Excel logging."""
    
    def __init__(self, data_dir: str = "data", excel_log_path: str = "experiment_log.xlsx"):
        self.data_dir = data_dir
        self.excel_log_path = excel_log_path
        os.makedirs(self.data_dir, exist_ok=True)
        
        self.ram_buffer: Optional[np.ndarray] = None
        self.last_analysis_results: Dict[str, Any] = {}

    def allocate_ram_buffer(self, num_shots: int, frame_shape: tuple = (512, 512), dtype=np.uint16) -> np.ndarray:
        """Pre-allocates continuous Zero-Copy RAM buffer."""
        self.ram_buffer = np.zeros((num_shots, *frame_shape), dtype=dtype)
        return self.ram_buffer

    def load_acquired_data(self, frames: np.ndarray) -> None:
        """Loads camera frames directly into preallocated RAM buffer."""
        if self.ram_buffer is not None and self.ram_buffer.shape == frames.shape:
            np.copyto(self.ram_buffer, frames)
        else:
            self.ram_buffer = frames.copy()

    def run_local_analysis(self) -> Dict[str, Any]:
        """Runs basic fast metrics (mean intensity, peak, std, estimated center)."""
        if self.ram_buffer is None or self.ram_buffer.size == 0:
            return {}
        
        mean_val = float(np.mean(self.ram_buffer))
        max_val = float(np.max(self.ram_buffer))
        min_val = float(np.min(self.ram_buffer))
        std_val = float(np.std(self.ram_buffer))
        
        self.last_analysis_results = {
            "mean_intensity": round(mean_val, 2),
            "max_intensity": int(max_val),
            "min_intensity": int(min_val),
            "std_intensity": round(std_val, 2),
            "frames_count": self.ram_buffer.shape[0]
        }
        return self.last_analysis_results

    def save_to_hdf5(self, file_name: str, note: str, stage_pos: int, channel: int = 1) -> str:
        """Saves acquired RAM buffer and experiment metadata to HDF5 (or NPZ fallback)."""
        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{file_name}_{timestamp_str}"
        
        if h5py is not None:
            save_path = os.path.join(self.data_dir, f"{base_name}.h5")
            with h5py.File(save_path, "w") as hf:
                hf.create_dataset("images", data=self.ram_buffer if self.ram_buffer is not None else np.array([]), compression="gzip")
                hf.attrs["timestamp"] = timestamp_str
                hf.attrs["note"] = note
                hf.attrs["stage_channel"] = channel
                hf.attrs["stage_pos_counts"] = stage_pos
                for k, v in self.last_analysis_results.items():
                    hf.attrs[f"analysis_{k}"] = v
        else:
            save_path = os.path.join(self.data_dir, f"{base_name}.npz")
            np.savez_compressed(
                save_path,
                images=self.ram_buffer if self.ram_buffer is not None else np.array([]),
                timestamp=timestamp_str,
                note=note,
                stage_channel=channel,
                stage_pos_counts=stage_pos,
                **self.last_analysis_results
            )
        return save_path

    def append_excel_log(self, filename: str, stage_pos: int, shot_count: int, note: str, channel: int = 1) -> None:
        """Auto-appends record to central experiment_log.xlsx with timestamp and metrics."""
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row_data = {
            "Timestamp": [now],
            "Data File": [os.path.basename(filename)],
            "Stage Channel": [channel],
            "Stage Pos (cnt)": [stage_pos],
            "Shot Count": [shot_count],
            "Mean Intensity": [self.last_analysis_results.get("mean_intensity", 0)],
            "Peak Intensity": [self.last_analysis_results.get("max_intensity", 0)],
            "Note": [note]
        }
        df_new = pd.DataFrame(row_data)

        if os.path.exists(self.excel_log_path):
            try:
                df_existing = pd.read_excel(self.excel_log_path)
                df_combined = pd.concat([df_existing, df_new], ignore_index=True)
            except Exception:
                df_combined = df_new
        else:
            df_combined = df_new

        df_combined.to_excel(self.excel_log_path, index=False)

"""
epics_file_watcher.py
=====================
使用 watchdog 監控原廠軟體輸出的資料夾。
當檢測到新檔案產生時，讀取 EPICS PV (FileName & ShotNumber)，
自動將檔案重命名為 `<FileName>_shot_<ShotNumber:04d>.<ext>` 並搬移至目標 DAQ 目錄。
"""

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

import epics
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("EPICSWatcher")


def wait_for_file_ready(file_path: Path, timeout: float = 10.0, check_interval: float = 0.2) -> bool:
    """
    等待硬體軟體完全寫入檔案（避免取得寫到一半的損壞檔案）。
    藉由檢查檔案大小是否停止變化來判斷。
    """
    start_time = time.time()
    last_size = -1

    while time.time() - start_time < timeout:
        if not file_path.exists():
            time.sleep(check_interval)
            continue
        
        try:
            current_size = file_path.stat().st_size
            # 檔案大小已不為 0，且連續兩次檢查大小一致，代表寫入完成
            if current_size > 0 and current_size == last_size:
                return True
            last_size = current_size
        except OSError:
            # 檔案可能被原廠軟體 Exclusive Lock，繼續等待
            pass
        
        time.sleep(check_interval)

    return False


class EPICSFileHandler(FileSystemEventHandler):
    def __init__(self, watch_dir: str, target_dir: str, allowed_extensions: Optional[tuple] = None):
        super().__init__()
        self.watch_dir = Path(watch_dir).resolve()
        self.target_dir = Path(target_dir).resolve()
        self.target_dir.mkdir(parents=True, exist_ok=True)
        
        # 允許監控的副檔名，如 ('.tif', '.tiff', '.dat', '.fits')；若為 None 則監控所有副檔名
        self.allowed_extensions = allowed_extensions
        self._processed_files = set()

    def on_created(self, event):
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        self.handle_new_file(file_path)

    def on_modified(self, event):
        # 部分軟體會先建立空檔再修改寫入，因此在 modified 補抓
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        self.handle_new_file(file_path)

    def handle_new_file(self, file_path: Path):
        # 過濾副檔名
        if self.allowed_extensions and file_path.suffix.lower() not in self.allowed_extensions:
            return

        # 避免重複處理同一張圖
        if file_path in self._processed_files:
            return

        logger.info(f"偵測到新檔案: {file_path.name}")

        # 1. 等待檔案寫入完畢
        if not wait_for_file_ready(file_path):
            logger.error(f"檔案寫入超時或無效，跳過處置: {file_path}")
            return

        # 將檔案納入已處理集合
        self._processed_files.add(file_path)

        # 2. 讀取 EPICS PV Metadata
        try:
            fn_val = epics.caget("EXP:Seq:FileName", as_string=True)
            sn_val = epics.caget("EXP:Seq:ShotNumber")

            fn = fn_val if fn_val is not None else "exp_run"
            sn = int(sn_val) if sn_val is not None else 0
        except Exception as e:
            logger.warning(f"讀取 EPICS PV 失敗，改用預設值: {e}")
            fn, sn = "exp_run", 0

        # 3. 建立目標檔名: <FileName>_shot_<ShotNumber:04d>.<ext>
        ext = file_path.suffix
        exact_filename = f"{fn}_shot_{sn:04d}{ext}"
        target_path = self.target_dir / exact_filename

        # 4. 複製或搬移至 DAQ 目錄
        try:
            shutil.copy2(file_path, target_path)
            logger.info(f"✔ 成功自動轉存 -> {target_path}")
        except Exception as e:
            logger.error(f"❌ 檔案搬移失敗: {e}")


def start_watcher(watch_dir: str, target_dir: str):
    event_handler = EPICSFileHandler(
        watch_dir=watch_dir,
        target_dir=target_dir,
        allowed_extensions=(".tif", ".tiff", ".dat", ".fits", ".raw")
    )
    
    observer = Observer()
    observer.schedule(event_handler, path=watch_dir, recursive=False)
    
    logger.info(f"開始監控資料夾: {watch_dir}")
    logger.info(f"DAQ 自動轉存目標: {target_dir}")
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("停止監控處理程序...")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    # 設定原廠軟體存檔目錄與 EPICS 自動歸檔目錄
    RAW_WATCH_FOLDER = r"C:\VendorSoftware\TempOutput"
    DAQ_TARGET_FOLDER = r"C:\Users\BeamStablizer\Documents\GitHub\DAQ_CA\data_epics"

    start_watcher(RAW_WATCH_FOLDER, DAQ_TARGET_FOLDER)
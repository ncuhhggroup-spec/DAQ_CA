# Point Grey GigE Camera (Cam 0) Diagnostic & EPICS DAQ System

本系統為專為 Point Grey / FLIR Grasshopper2 (GS2-GE-20S4M) GigE 相機設計的高階控制與 EPICS DAQ 擷取軟體[cite: 3, 1]。支援實際硬體驅動（FlyCapture2 SDK / PyCapture2）與離線開發模擬器（Mock Driver）[cite: 3, 1]。

---

## 1. 檔案結構與模組分工

| 檔案名稱 | 核心職責 | 主要功能與類別 |
| :--- | :--- | :--- |
| **`pg_camera_driver.py`** | 底層硬體抽象層 | • `Grasshopper2Driver`：透過 ctypes/C-DLL 或 PyCapture2 存取相機暫存器。<br>• 提供實際 IP、曝光時間、幀率、增益與 Pixel Format 讀取[cite: 3]。 |
| **`ioc_gige_driver.py`** | 高階相機控制器 | • `SingleGigECameraController`：管理 Cam 0 狀態與影像 Buffer。<br>• `MockCameraDriver`：無硬體時的離線模擬數據源。<br>• 提供快照背景設定與 TIFF 多頁檔/Metadata 儲存[cite: 1]。 |
| **`ioc_gige_gui.py`** | 介面與事件流程控制[cite: 2] | • `SingleGigECameraGUI`：基於 PyQt6/PySide6 與 PyQtGraph 的三頁式介面[cite: 2]。<br>• `CameraGrabberThread`：獨立背景影像擷取執行緒[cite: 2]。 |

---

## 2. 系統架構與特色

### 2.1 獨立分工迴路
* **影像擷取迴路 (`CameraGrabberThread`)**：獨立 `QThread` 背景迴路，不間斷拉取相機 DMA 緩衝區影像，避免 GUI 凍結[cite: 2]。
* **UI 刷新與狀態讀取迴路 (`display_timer`)**：10 Hz 定時器驅動，負責更新視埠畫面與定期向硬體查詢實際運作參數[cite: 2]。
* **EPICS 事件監聽迴路 (`_epics_state_pv`)**：以 PyEpics 背景 Callback 監聽序列狀態，透過 Thread-safe Signal 觸發存檔流程[cite: 2]。

### 2.2 三大功能分頁
1. **🎥 Live View & Local Operations（即時預覽與在地診斷）**[cite: 2]
   * 支持 CW (Continuous Wave) 流水線模式與單張快照 (Single Shot)[cite: 2]。
   * **即時背景扣除 (`Subtract BG on Display`)**：可在畫面呈現扣除背景後的影像，而不影響原始存檔[cite: 2]。
   * **快照錄製背景 (`Record BG`)**：點擊後直接使用當前記憶體中的影像作為背景，不需額外觸發新擷取。
   * 內建 2D 高斯光束擬合與 Target/ROI 標定[cite: 2]。
2. **⚡ EPICS DAQ Mode（EPICS 連動模式）**[cite: 2]
   * 切換至此頁面自動強制鎖定為外部 TTL 硬體觸發 (`EXTERNAL_TTL`)[cite: 2]。
   * 根據 `EXP:Seq:State`（如 `SAVING`）自動以 PV Metadata 命名將影像寫入指定目錄[cite: 2]。
3. **📜 System & Event Log（系統日誌與實際硬體參數）**[cite: 2]
   * **Actual Camera Hardware Parameters**：即時顯示相機實際回傳的 IP Address、曝光時間 (ms)、幀率 (FPS)、增益 (dB) 與 Pixel Format[cite: 3, 1, 2]。
   * 提供彩色富文本事件與 DAQ 狀態轉移記錄[cite: 2]。

---

## 3. 系統需求與環境建置

* **Python 版本**：Python 3.10+ (64-bit)
* **依賴套件**：
  ```bash
  pip install numpy pyqtgraph tifffile pyepics
  # PyQt6 或 PySide6 任選其一
  pip install PyQt6
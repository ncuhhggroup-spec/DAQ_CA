```markdown
# EPICS IOC Integration & Camera DAQ State Machine Note
> **目的**：紀錄此程式如何透過 EPICS IOC 完成硬體連動、狀態機控制（Sequence State Machine）與自動化數據擷取（DAQ Process），作為未來移植至 Andor Camera（Andor SDK2 / SDK3）之設計規範[cite: 2]。

---

## 1. 系統架構概觀 (System Architecture)

本程式採用 **「PyEpics C-CA 背景監聽 + Qt Signal 跨線程傳遞 + 自動化狀態機」** 的架構[cite: 2]：


```

[ EPICS IOC / Central Sequencer ]
│  (Channel Access PVs)
▼
[ PyEpics Listener Thread ]  ──(Qt Signal: epics_state_changed)──► [ Qt Main Thread ]
│
┌─────────────────────┴─────────────────────┐
▼                                           ▼
[ Trigger Mode & Armed ]                    [ Auto Saving & Metadata ]
(EXTERNAL_TTL / High Speed)                   (TIFF + Embedded JSON)

```

---

## 2. EPICS PV 介面規範 (PV Interface)

系統定義了兩類 Channel Access PVs，用於與實驗室中央控制系統進行雙向溝通[cite: 2]：

### 2.1 訂閱（讀取）PV： Sequence 控制與檔名標籤
| PV 名稱 | 類型 | 說明 |
| :--- | :--- | :--- |
| `EXP:Seq:State` | String | 狀態機狀態（`IDLE`, `ARMED`, `ACQUIRING`, `SAVING`）[cite: 2] |
| `EXP:Seq:FileName` | String | 當前實驗 Shot 的檔案名稱前綴（如 `hhg_pulse_01`）[cite: 2] |
| `EXP:Seq:ShotNumber` | Int / Double | 當前實驗 Shot 的編號（如 `1`, `2`, `3`）[cite: 2] |

### 2.2 發布（寫入）PV： 相機狀態回報
| PV 名稱 | 寫入值 | 說明 |
| :--- | :--- | :--- |
| `EXP:Seq:CameraMode` | `REAL` / `SIMULATED` | 回報當前連接的是真實硬體還是 Mock 模擬器[cite: 2] |
| `EXP:Seq:CameraStatus` | `CONNECTED` / `DISCONNECTED` | 回報相機物理連線與初始化狀態[cite: 2] |

---

## 3. DAQ 狀態機流程 (Sequence State Machine)

當 EPICS 主控端改變 `EXP:Seq:State` 時，相機程式會執行對應的控制動作[cite: 2]：


```

```
           ┌─────────────────────────────────────────────────┐
           │                     IDLE                        │
           └────────────────────────┬────────────────────────┘
                                    │ EXP:Seq:State -> "ARMED"
                                    ▼
           ┌─────────────────────────────────────────────────┐
           │                     ARMED                       │
           │  • 強制切換為 EXTERNAL_TTL 硬體觸發[cite: 2]        │
           │  • 啟動相機 DMA Capture Buffer Listening[cite: 2] │
           └────────────────────────┬────────────────────────┘
                                    │ EXP:Seq:State -> "ACQUIRING"
                                    ▼
           ┌─────────────────────────────────────────────────┐
           │                   ACQUIRING                     │
           │  • 等待外部觸發脈衝 (e.g. DG645 TTL)[cite: 2]  │
           │  • 相機將硬體抓到的 Frame 寫入記憶體[cite: 2]   │
           └────────────────────────┬────────────────────────┘
                                    │ EXP:Seq:State -> "SAVING"
                                    ▼
           ┌─────────────────────────────────────────────────┐
           │                     SAVING                      │
           │  • 讀取 EXP:Seq:FileName 與 ShotNumber[cite: 2] │
           │  • 自動寫入檔名: <FileName>_shot_<ShotNumber>.tif[cite: 2]
           │  • 渲染影像至 DAQ Viewport[cite: 2]              │
           └─────────────────────────────────────────────────┘

```

```

### 關鍵狀態邏輯程式碼結構 (`_handle_epics_auto_sequence`)
```python
def _handle_epics_auto_sequence(self, new_state: str):
    # 1. 讀取當前 Shot Metadata
    fn = epics.caget("EXP:Seq:FileName", as_string=True) or "exp_run"[cite: 2]
    sn = epics.caget("EXP:Seq:ShotNumber") or 0[cite: 2]

    # 2. 狀態切換處置
    if new_state == "ARMED":
        self.controller.set_trigger_mode("EXTERNAL_TTL")  # 鎖定外部硬體觸發[cite: 2]
        self.controller.start_capture_all()               # 進入監聽狀態[cite: 2]

    elif new_state == "ACQUIRING":
        self.controller.start_capture_all()               # 等待外部觸發 Pulse[cite: 2]

    elif new_state == "SAVING":
        filename = f"{fn}_shot_{int(sn):04d}.tif"[cite: 2]
        filepath = os.path.join(self.daq_save_dir, filename)[cite: 2]
        
        # 儲存 RAW 資料並將扣除背景後的畫面渲染至 DAQ Viewport[cite: 1, 2]
        self.controller.save_tiff_with_metadata(filepath, image_data=self.latest_frame)[cite: 1, 2]
        self.daq_img_item.setImage(self._get_display_frame(self.latest_frame))[cite: 2]

```

---

## 4. 跨線程安全機制 (Thread Safety)

* **問題**：PyEpics 的 PV Callback（`_on_epics_state_change`）是在底層 C-CA (Channel Access) 獨立 Thread 中執行。若直接在 Callback 中更新 Qt UI 元件，會導致 GUI 凍結或 Crash。


* **解決方案**：使用 **Qt Signal** 作為橋樑：


```python
# 1. 定義 Qt Signal[cite: 2]
epics_state_changed = Signal(str)[cite: 2]

# 2. 在 PyEpics Thread 中 emit Signal[cite: 2]
def _on_epics_state_change(self, pvname=None, value=None, **kwargs):
    if value is not None:
        self.epics_state_changed.emit(str(value))  # 安全轉交給主線程[cite: 2]

# 3. 在 Qt Main Thread 綁定處理 Slot[cite: 2]
self.epics_state_changed.connect(self._handle_epics_auto_sequence)[cite: 2]

```



---

## 5. 移植至 Andor Camera 的關鍵套用指南 (Migration Checklist)

將此模式套用至 Andor 相機（如 SDK2 `atmcd32d.dll` / `atmcd64d.dll` 或 SDK3 `Andor3`）時，主要替換**驅動介面**與**觸發模式映射**，狀態機架構完全不需要更動：

### 5.1 觸發模式對應 (Trigger Mode Mapping)

| 控制邏輯 | Point Grey (FlyCapture2) | Andor SDK2 / SDK3 對應 API |
| --- | --- | --- |
| **Free-Run (CW)** | `set_trigger_mode(enabled=False)`<br> | • SDK2: `SetTriggerMode(0)` (Internal)<br>

<br>• SDK3: `SetEnumString("TriggerMode", "Internal")` |
| **ARMED (Hardware TTL)** | `set_trigger_mode(enabled=True)`<br> | • SDK2: `SetTriggerMode(1)` (External) 或 `6` (External Start)<br>

<br>• SDK3: `SetEnumString("TriggerMode", "External")` |

### 5.2 擷取模式與 Buffer 設定 (Acquisition Setup)

* **Andor SDK2**：
* 在 `ARMED` 階段調用 `SetAcquisitionMode(1)` (Single Scan) 或 `5` (Run Till Abort)。
* 調用 `StartAcquisition()` 使相機進入等待 DG645 TTL 訊號狀態。


* **Andor SDK3**：
* 調用 `Command("AcquisitionStart")`，並從 Buffer Queue 中拉取 `WaitBuffer()`。



### 5.3 程式碼移植範本 (Andor Camera Driver Boilerplate)

```python
class AndorCameraDriver:
    def set_trigger_mode(self, mode: str) -> None:
        if mode.upper() == "EXTERNAL_TTL":
            # Andor SDK2 範例: 1 = External Trigger[cite: 3]
            self.sdk.SetTriggerMode(1) 
            logger.info("Andor Camera trigger set to External TTL.")
        else:
            # 0 = Internal Trigger[cite: 3]
            self.sdk.SetTriggerMode(0) 
            logger.info("Andor Camera trigger set to Internal Free-Run.")

    def arm_for_daq(self) -> None:
        """對應 EPICS [ARMED] 狀態[cite: 2]"""
        self.set_trigger_mode("EXTERNAL_TTL")[cite: 2]
        self.sdk.StartAcquisition()  # 進入 Armed 狀態等待外部 Pulse[cite: 2]

    def grab_acquired_frame() -> np.ndarray:
        """對應 EPICS [SAVING] 狀態擷取影像[cite: 2]"""
        # Andor SDK2 範例: 取得最新抵達 Buffer 的 Frame
        arr = self.sdk.GetMostRecentImage16()
        return arr

```

```

```
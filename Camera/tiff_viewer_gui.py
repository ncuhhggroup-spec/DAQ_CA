"""
tiff_viewer_gui.py
==================
Standalone GUI viewer for TIFF files saved by the Dual GigE Camera System.

Features:
- File browser to open individual TIFFs or scan an entire folder.
- Three-tab image viewer: Raw Image | Background | BG-Subtracted.
- Full metadata tag panel with color-coded key/value table.
- Interactive pyqtgraph image view with histogram LUT and crosshair readout.
- Batch file list with one-click navigation between shots.
- Export PNG or metadata JSON from within the GUI.

Author : Antigravity DAQ Module
Date   : 2026-09-22
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np

# Qt backend
try:
    from PyQt6.QtCore import Qt, QThread, pyqtSignal as Signal, QSortFilterProxyModel
    from PyQt6.QtGui import QColor, QStandardItem, QStandardItemModel, QFont
    from PyQt6.QtWidgets import (
        QApplication, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView,
        QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
        QSizePolicy, QSplitter, QTabWidget, QTableView, QVBoxLayout,
        QWidget, QListWidget, QListWidgetItem, QStatusBar, QAbstractItemView,
        QFrame, QScrollArea,
    )
    _QT = "PyQt6"
except ImportError:
    from PySide6.QtCore import Qt, QThread, Signal, QSortFilterProxyModel
    from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel, QFont
    from PySide6.QtWidgets import (
        QApplication, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView,
        QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
        QSizePolicy, QSplitter, QTabWidget, QTableView, QVBoxLayout,
        QWidget, QListWidget, QListWidgetItem, QStatusBar, QAbstractItemView,
        QFrame, QScrollArea,
    )
    _QT = "PySide6"

import pyqtgraph as pg

from read_gige_tiff import GigETiffData, GigETiffReader

pg.setConfigOptions(imageAxisOrder="row-major", antialias=True)

# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------

_STYLE = """
QMainWindow, QWidget {
    background-color: #0f1117;
    color: #e2e8f0;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 12px;
}
QGroupBox {
    background-color: #171a23;
    border: 1px solid #272d3d;
    border-radius: 6px;
    margin-top: 14px;
    padding: 10px 8px 6px 8px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
    color: #818cf8;
    font-size: 11px;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}
QLineEdit {
    background-color: #1e2230;
    border: 1px solid #31384e;
    border-radius: 4px;
    padding: 4px 6px;
    color: #f1f5f9;
}
QLineEdit:focus { border: 1px solid #6366f1; }
QPushButton {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #4f46e5,stop:1 #4338ca);
    color: #fff; border: none; border-radius: 4px;
    padding: 6px 14px; font-weight: 600;
}
QPushButton:hover {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #6366f1,stop:1 #4f46e5);
}
QPushButton:pressed { background: #3730a3; }
QPushButton:disabled { background: #232734; color: #555e75; }
QPushButton#openBtn {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #2563eb,stop:1 #1d4ed8);
}
QPushButton#folderBtn {
    background: #334155; color: #f8fafc;
    border: 1px solid #475569;
}
QPushButton#folderBtn:hover { background: #475569; }
QPushButton#exportPngBtn {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #059669,stop:1 #047857);
}
QPushButton#exportJsonBtn {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #d97706,stop:1 #b45309);
}
QListWidget {
    background-color: #0f1117;
    border: 1px solid #272d3d;
    border-radius: 4px;
    color: #cbd5e1;
    font-size: 11px;
}
QListWidget::item:selected {
    background-color: #1e2230;
    color: #38bdf8;
}
QListWidget::item:hover { background-color: #1a1f2e; }
QTableView {
    background-color: #0f1117;
    border: 1px solid #272d3d;
    gridline-color: #1e2230;
    color: #e2e8f0;
    selection-background-color: #1e2230;
    selection-color: #38bdf8;
    font-size: 12px;
}
QHeaderView::section {
    background-color: #171a23;
    color: #818cf8;
    border: 1px solid #272d3d;
    padding: 4px 8px;
    font-weight: bold;
    font-size: 11px;
}
QTabWidget::pane {
    border: 1px solid #272d3d;
    background-color: #0f1117;
    border-radius: 6px;
    top: -1px;
}
QTabBar::tab {
    background: #171a23; color: #94a3b8;
    border: 1px solid #272d3d;
    border-bottom: none;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
    padding: 7px 18px; margin-right: 3px;
    font-weight: 600; font-size: 12px;
}
QTabBar::tab:selected {
    background: #1e2230; color: #38bdf8;
    border-bottom: 2px solid #38bdf8;
}
QTabBar::tab:hover:!selected { background: #222736; color: #f1f5f9; }
QStatusBar {
    background-color: #0b0d12; color: #94a3b8;
    border-top: 1px solid #1e2230;
}
QLabel { color: #94a3b8; }
QScrollArea { border: none; }
"""

# Metadata key color coding
_META_COLORS = {
    "channel_name":   "#38bdf8",
    "timestamp":      "#a5b4fc",
    "exposure_seconds": "#10b981",
    "gain_db":        "#10b981",
    "user_notes":     "#fbbf24",
    "camera_serial":  "#94a3b8",
    "camera_index":   "#94a3b8",
    "dtype":          "#94a3b8",
    "image_shape":    "#94a3b8",
    "has_background_attached": "#f59e0b",
    "analysis":       "#fb923c",
}


# ---------------------------------------------------------------------------
# ImagePanel – pyqtgraph view + hover stats
# ---------------------------------------------------------------------------

class ImagePanel(QWidget):
    """Single-tab image view with histogram LUT, cursor stats, and auto-range."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.gl = pg.GraphicsLayoutWidget()
        self.gl.setBackground("#050709")
        self.view = self.gl.addViewBox(row=0, col=0, lockAspect=True, enableMouse=True)
        self.view.invertY(True)

        self.img_item = pg.ImageItem()
        self.view.addItem(self.img_item)

        self.hist = pg.HistogramLUTItem(self.img_item)
        self.hist.gradient.loadPreset("inferno")
        self.gl.addItem(self.hist, row=0, col=1)
        self.hist.setMaximumWidth(110)

        layout.addWidget(self.gl, stretch=1)

        self.info_label = QLabel(f"{label}   |   No data loaded")
        self.info_label.setStyleSheet("color: #38bdf8; font-family: monospace; font-size: 11px;")
        layout.addWidget(self.info_label)

        self.proxy = pg.SignalProxy(
            self.gl.scene().sigMouseMoved, rateLimit=30, slot=self._on_mouse
        )
        self._arr: Optional[np.ndarray] = None
        self._label = label

    def set_image(self, arr: Optional[np.ndarray]):
        self._arr = arr
        if arr is None:
            self.img_item.clear()
            self.info_label.setText(f"{self._label}   |   Not available")
            return
        self.img_item.setImage(arr, autoLevels=True)
        self.hist.setImageItem(self.img_item)
        h, w = arr.shape[:2]
        self.info_label.setText(
            f"{self._label}   |   {w} x {h} px   "
            f"min={arr.min()}   max={arr.max()}   mean={arr.mean():.1f}"
        )
        self.view.autoRange()

    def _on_mouse(self, evt):
        pos = evt[0]
        if self._arr is None:
            return
        if self.view.sceneBoundingRect().contains(pos):
            pt = self.view.mapSceneToView(pos)
            x, y = int(round(pt.x())), int(round(pt.y()))
            h, w = self._arr.shape[:2]
            if 0 <= x < w and 0 <= y < h:
                val = self._arr[y, x]
                self.info_label.setText(
                    f"{self._label}   |   Cursor ({x}, {y})   Intensity: {val}"
                )


# ---------------------------------------------------------------------------
# MetadataPanel – sortable table of JSON tag key/value pairs
# ---------------------------------------------------------------------------

class MetadataPanel(QWidget):
    """Flat key/value table view of all metadata tags in a loaded TIFF."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Filter bar
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Type to filter metadata keys...")
        self.filter_edit.textChanged.connect(self._on_filter)
        filter_row.addWidget(self.filter_edit)
        layout.addLayout(filter_row)

        # Table
        self._model = QStandardItemModel(0, 2)
        self._model.setHorizontalHeaderLabels(["Key", "Value"])

        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterKeyColumn(-1)  # search all columns
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self.table = QTableView()
        self.table.setModel(self._proxy)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("QTableView { alternate-background-color: #12151f; }")
        layout.addWidget(self.table, stretch=1)

    def _on_filter(self, text: str):
        if hasattr(self._proxy, "setFilterFixedString"):
            self._proxy.setFilterFixedString(text)
        else:
            self._proxy.setFilterWildcard(f"*{text}*")

    def load_metadata(self, meta: dict):
        self._model.setRowCount(0)
        self._flatten_and_fill("", meta)

    def _flatten_and_fill(self, prefix: str, obj, depth: int = 0):
        """Recursively flatten nested dicts/lists into key/value rows."""
        if isinstance(obj, dict):
            for k, v in obj.items():
                full_key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, (dict, list)):
                    self._flatten_and_fill(full_key, v, depth + 1)
                else:
                    self._add_row(full_key, v)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                full_key = f"{prefix}[{i}]"
                if isinstance(v, (dict, list)):
                    self._flatten_and_fill(full_key, v, depth + 1)
                else:
                    self._add_row(full_key, v)

    def _add_row(self, key: str, value):
        key_item = QStandardItem(str(key))
        val_str = (
            f"{value:.6g}" if isinstance(value, float) else str(value)
        )
        val_item = QStandardItem(val_str)

        # Color coding
        color_hex = _META_COLORS.get(key, "#cbd5e1")
        for item in (key_item, val_item):
            item.setForeground(QColor(color_hex))
            item.setFont(QFont("Consolas", 11))

        self._model.appendRow([key_item, val_item])


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class TiffViewerGUI(QMainWindow):
    """Standalone viewer for Dual GigE camera TIFF files."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("GigE Camera TIFF Viewer")
        self.resize(1420, 880)
        self.setStyleSheet(_STYLE)

        self._current_data: Optional[GigETiffData] = None
        self._file_list: list[Path] = []

        self._init_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ---- Left panel: file browser & controls ----
        left_panel = QWidget()
        left_panel.setFixedWidth(270)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        # Title
        title = QLabel("<b>GIGE TIFF VIEWER</b>")
        title.setStyleSheet("font-size: 14px; color: #818cf8; font-weight: bold;")
        left_layout.addWidget(title)

        # Open file / folder buttons
        io_group = QGroupBox("Open Files")
        io_layout = QVBoxLayout(io_group)

        self.btn_open_file = QPushButton("Open TIFF File...")
        self.btn_open_file.setObjectName("openBtn")
        self.btn_open_file.clicked.connect(self._on_open_file)
        io_layout.addWidget(self.btn_open_file)

        self.btn_open_folder = QPushButton("Open Folder (Batch)...")
        self.btn_open_folder.setObjectName("folderBtn")
        self.btn_open_folder.clicked.connect(self._on_open_folder)
        io_layout.addWidget(self.btn_open_folder)

        self.folder_label = QLabel("No folder selected")
        self.folder_label.setWordWrap(True)
        self.folder_label.setStyleSheet("color: #475569; font-size: 10px;")
        io_layout.addWidget(self.folder_label)
        left_layout.addWidget(io_group)

        # File list
        files_group = QGroupBox("Shot List")
        files_layout = QVBoxLayout(files_group)
        self.file_list_widget = QListWidget()
        self.file_list_widget.currentRowChanged.connect(self._on_file_selected)
        files_layout.addWidget(self.file_list_widget)
        self.file_count_label = QLabel("0 files")
        self.file_count_label.setStyleSheet("color: #475569; font-size: 10px;")
        files_layout.addWidget(self.file_count_label)
        left_layout.addWidget(files_group, stretch=1)

        # Export buttons
        export_group = QGroupBox("Export")
        export_layout = QVBoxLayout(export_group)
        self.btn_export_png = QPushButton("Export Preview PNG...")
        self.btn_export_png.setObjectName("exportPngBtn")
        self.btn_export_png.clicked.connect(self._on_export_png)
        self.btn_export_png.setEnabled(False)
        export_layout.addWidget(self.btn_export_png)

        self.btn_export_json = QPushButton("Export Metadata JSON...")
        self.btn_export_json.setObjectName("exportJsonBtn")
        self.btn_export_json.clicked.connect(self._on_export_json)
        self.btn_export_json.setEnabled(False)
        export_layout.addWidget(self.btn_export_json)
        left_layout.addWidget(export_group)

        root.addWidget(left_panel)

        # ---- Right panel: splitter with image tabs + metadata ----
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        # Image tabs (top portion)
        self.image_tabs = QTabWidget()
        self.panel_raw = ImagePanel("Raw Image")
        self.panel_bg = ImagePanel("Background")
        self.panel_sub = ImagePanel("BG Subtracted (float32)")
        self.image_tabs.addTab(self.panel_raw, "Raw Image")
        self.image_tabs.addTab(self.panel_bg, "Background")
        self.image_tabs.addTab(self.panel_sub, "BG Subtracted")
        right_splitter.addWidget(self.image_tabs)

        # Metadata table (bottom portion)
        meta_group = QGroupBox("Metadata Tags")
        meta_layout = QVBoxLayout(meta_group)
        meta_layout.setContentsMargins(4, 8, 4, 4)
        self.meta_panel = MetadataPanel()
        meta_layout.addWidget(self.meta_panel)
        right_splitter.addWidget(meta_group)

        right_splitter.setSizes([560, 280])
        root.addWidget(right_splitter, stretch=1)

        # Status bar
        self.statusBar().showMessage("Ready — Open a TIFF file to begin.")

    # ------------------------------------------------------------------
    # File opening
    # ------------------------------------------------------------------

    def _on_open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open GigE TIFF", "", "TIFF Files (*.tif *.tiff);;All Files (*)"
        )
        if path:
            self._load_file_list([Path(path)])
            self.file_list_widget.setCurrentRow(0)

    def _on_open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Open Folder", "")
        if folder:
            tifs = sorted(Path(folder).glob("*.tif")) + sorted(Path(folder).glob("*.tiff"))
            if not tifs:
                self.statusBar().showMessage("No TIFF files found in selected folder.")
                return
            self.folder_label.setText(folder)
            self._load_file_list(tifs)
            self.file_list_widget.setCurrentRow(0)

    def _load_file_list(self, paths: list[Path]):
        self._file_list = paths
        self.file_list_widget.clear()
        for p in paths:
            item = QListWidgetItem(p.name)
            item.setToolTip(str(p))
            self.file_list_widget.addItem(item)
        self.file_count_label.setText(f"{len(paths)} file(s)")

    def _on_file_selected(self, row: int):
        if row < 0 or row >= len(self._file_list):
            return
        path = self._file_list[row]
        self._load_tiff(path)

    # ------------------------------------------------------------------
    # TIFF loading & display
    # ------------------------------------------------------------------

    def _load_tiff(self, path: Path):
        self.statusBar().showMessage(f"Loading: {path.name}…")
        try:
            reader = GigETiffReader(path)
            self._current_data = reader.data
        except Exception as exc:
            self.statusBar().showMessage(f"Error loading {path.name}: {exc}")
            return

        d = self._current_data

        # Images
        self.panel_raw.set_image(d.image.astype(np.float32) if d.image is not None else None)
        self.panel_bg.set_image(d.background.astype(np.float32) if d.background is not None else None)
        self.panel_sub.set_image(d.background_subtracted())

        # Metadata table
        self.meta_panel.load_metadata(d.metadata)

        # Export buttons
        self.btn_export_png.setEnabled(True)
        self.btn_export_json.setEnabled(True)

        status = (
            f"{path.name}  |  Channel: {d.channel_name}  "
            f"|  {d.timestamp}  |  Exp: {d.exposure_ms:.1f} ms  "
            f"|  BG: {'YES' if d.has_background else 'NO'}"
        )
        self.statusBar().showMessage(status)

    # ------------------------------------------------------------------
    # Export actions
    # ------------------------------------------------------------------

    def _on_export_png(self):
        if self._current_data is None:
            return
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            QMessageBox.critical(self, "Export Error",
                                 "matplotlib is required for PNG export.\npip install matplotlib")
            return

        d = self._current_data
        tab_idx = self.image_tabs.currentIndex()
        arrays = [
            (d.image, "Raw Image"),
            (d.background, "Background"),
            (d.background_subtracted(), "BG Subtracted"),
        ]
        arr, label = arrays[tab_idx]
        if arr is None:
            self.statusBar().showMessage("No image data on this tab to export.")
            return

        default_name = Path(d.filepath).stem + f"_{label.replace(' ', '_')}.png"
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Export PNG", default_name, "PNG Files (*.png)"
        )
        if not out_path:
            return

        arr_f = arr.astype(np.float32)
        fig, ax = plt.subplots(figsize=(12, 9))
        im = ax.imshow(arr_f, cmap="inferno", origin="upper",
                       vmin=np.percentile(arr_f, 0.5), vmax=np.percentile(arr_f, 99.9))
        plt.colorbar(im, ax=ax, label="Intensity (ADU)")
        ax.set_title(f"{d.channel_name} — {label}  [{d.timestamp}]", fontsize=11)
        ax.set_xlabel("X (px)")
        ax.set_ylabel("Y (px)")
        plt.tight_layout()
        plt.savefig(out_path, dpi=150)
        plt.close(fig)
        self.statusBar().showMessage(f"PNG saved: {out_path}")

    def _on_export_json(self):
        if self._current_data is None:
            return
        d = self._current_data
        default_name = Path(d.filepath).stem + ".metadata.json"
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Export Metadata JSON", default_name, "JSON Files (*.json)"
        )
        if not out_path:
            return
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(d.metadata, f, indent=2)
        self.statusBar().showMessage(f"Metadata JSON saved: {out_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    win = TiffViewerGUI()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

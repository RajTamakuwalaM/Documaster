import sys
import csv
try:
    csv.field_size_limit(sys.maxsize)
except (OverflowError, ValueError):
    # Fallback for 32-bit systems or Windows legacy
    csv.field_size_limit(2147483647)
import os
import shutil
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTableView, QWidget, QSplitter, QTabWidget,
    QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox, QLabel, QTextEdit,
    QAbstractItemView, QScrollArea, QPushButton, QProgressDialog,
    QGraphicsView, QGraphicsScene, QRubberBand, QSpinBox, QDialog, 
    QDialogButtonBox, QListWidget, QListWidgetItem, QLineEdit, 
    QInputDialog
)
from PySide6.QtCore import Qt, QRect, QPoint, QSize
from PySide6.QtGui import QPixmap, QFontMetrics, QPainter, QAction, QShortcut, QKeySequence
# filename: main.py
from PIL import Image, ImageQt
import functools

# --- CUSTOM MODULE IMPORTS ---
import utils
import qc_logic
import branding_logic
from models import LazyDatTableModel
from dialogs import (
    FilterDialog, ExportDialog, FindReplaceDialog, ConditionsDialog,
    AddFieldDialog, NativeRenameDialog, OverlayIdentifierDialog, ConcatenateDialog, SplitDialog,
    OverlayFieldSelectDialog, ImportMappingDialog, MultiFieldSelectionDialog, DateTimeConfigDialog, TimeZoneConfigDialog, BrandingConfigDialog
)

@functools.lru_cache(maxsize=20)
def load_image_cached(path, page_num=0):
    """
    Loads image using PIL for:
    1. Multi-page support (TIFF/PDF)
    2. High Quality rendering
    """
    try:
        # Lazy load to identify frames
        with Image.open(path) as img:
            # Handle Multi-page files
            if getattr(img, "is_animated", False) and img.n_frames > 1:
                img.seek(min(page_num, img.n_frames - 1))
            
            if img.mode != "RGB":
                img = img.convert("RGB")
                
            # Convert PIL to QPixmap (High Quality)
            qim = ImageQt.ImageQt(img)
            pix = QPixmap.fromImage(qim)
            return pix
    except Exception as e:
        print(f"Image Load Error: {e}")
        return None
    
from PySide6.QtCore import QThread, Signal

from PySide6.QtCore import QThread, Signal
import time  # Naya import zaroori hai throttling ke liye

class TextQCWorker(QThread):
    progress_update = Signal(int)
    finished_scan = Signal(dict)
    error = Signal(str)

    def __init__(self, text_folder, search_terms, check_empty):
        super().__init__()
        self.text_folder = text_folder
        self.search_terms = search_terms
        self.check_empty = check_empty

    def run(self):
        try:
            self.last_emit = time.time()
            def update_p(i):
                # FIX: Signal Throttling - Update UI max 4 times a second
                # 17 Lakh files mein GUI ko hang hone se bachayega
                if time.time() - self.last_emit > 0.25:
                    self.progress_update.emit(i)
                    self.last_emit = time.time()
                    
            stats = qc_logic.scan_text_content_deep(self.text_folder, self.search_terms, self.check_empty, update_p)
            self.finished_scan.emit(stats)
        except Exception as e:
            self.error.emit(str(e))

class BackgroundQCWorker(QThread):
    finished = Signal() 
    error = Signal(str)

    def __init__(self, case_root, headers, data, field_map, opt_index):
        super().__init__()
        self.case_root = case_root
        self.headers = headers
        self.data = data 
        self.field_map = field_map
        self.opt_index = opt_index

    def run(self):
        try:
            # --- THE "TARGETED DIRECTORY" NETWORK SCANNER ---
            # Network drives (Z:\) hang when scanning recursively. 
            # We extract ONLY the required folders from DAT/OPT and scan them directly!
            
            native_field = self.field_map.get("native")
            text_field = self.field_map.get("text")
            
            nat_col = self.headers.index(native_field) if native_field in self.headers else -1
            txt_col = self.headers.index(text_field) if text_field in self.headers else -1
            
            exp_natives, exp_texts, exp_images = set(), set(), set()
            target_dirs = set()
            
            # 1. Parse DAT to find EXACT folder paths
            for row in self.data:
                if nat_col > -1 and nat_col < len(row):
                    val = row[nat_col].strip()
                    if val:
                        exp_natives.add(val)
                        fp = utils.resolve_relative_path(self.case_root, val)
                        if fp: target_dirs.add(os.path.dirname(fp))
                        
                if txt_col > -1 and txt_col < len(row):
                    val = row[txt_col].strip()
                    if val:
                        exp_texts.add(val)
                        fp = utils.resolve_relative_path(self.case_root, val)
                        if fp: target_dirs.add(os.path.dirname(fp))
                        
            # 2. Parse OPT to find EXACT image folder paths
            if self.opt_index:
                for pages in self.opt_index.values():
                    for page in pages:
                        path = page["path"] if isinstance(page, dict) else page
                        if path:
                            exp_images.add(path)
                            target_dirs.add(os.path.dirname(path))

            # --- NAYA FIX: Include ANY Loadfile folder (DATA, LOADFILES, etc.) ---
            if self.case_root and os.path.exists(self.case_root):
                target_dirs.add(self.case_root) 
                try:
                    for entry in os.scandir(self.case_root):
                        if entry.is_dir():
                            target_dirs.add(entry.path) 
                            
                            # Go one level deeper ONLY for non-data folders
                            if entry.name.lower() not in ["natives", "images", "text", "ocr"]:
                                try:
                                    for sub_entry in os.scandir(entry.path):
                                        if sub_entry.is_dir():
                                            target_dirs.add(sub_entry.path)
                                except: pass
                except: pass
            # ---------------------------------------------------------------------
            # ---------------------------------------------------------------------------------

            # 3. Super-Fast Targeted Scan (SMB/Network friendly)
            valid_files_cache = set()
            t_count, t_size = 0, 0
            
            for d in target_dirs:
                if os.path.exists(d):
                    try:
                        with os.scandir(d) as it:
                            for entry in it:
                                if entry.is_file(follow_symlinks=False):
                                    file_key = entry.path.lower()
                                    
                                    # 🚨 THE FIX: Pura check lagaya taaki koi file 2 baar count na ho
                                    if file_key not in valid_files_cache:
                                        valid_files_cache.add(file_key)
                                        t_count += 1
                                        try: 
                                            t_size += entry.stat(follow_symlinks=False).st_size
                                        except: 
                                            pass
                    except: pass

            # 4. In-Memory Resolution Check (Instant!)
            missing_natives, missing_texts, missing_images = set(), set(), set()
            
            for rel_path in exp_natives:
                fp = utils.resolve_relative_path(self.case_root, rel_path)
                if fp and fp.lower() not in valid_files_cache:
                    missing_natives.add(os.path.basename(rel_path))
                    
            for rel_path in exp_texts:
                fp = utils.resolve_relative_path(self.case_root, rel_path)
                if fp and fp.lower() not in valid_files_cache:
                    missing_texts.add(os.path.basename(rel_path))
                    
            for path in exp_images:
                if path and path.lower() not in valid_files_cache:
                    missing_images.add(os.path.basename(path))

            # Bates gap logic
            gap_results = None
            try:
                has_endbates = any(row[3] for row in self.data[:100] if len(row) > 3)
                if has_endbates:
                    gaps, overlaps = qc_logic.find_bates_issues(self.data, 0, 3)
                    gap_results = (gaps, overlaps)
            except: pass

            # Package results for the UI and Excel Report
            self.result_data = {
                "folders": {"natives": None, "text": None, "images": None},
                "scan_results": {
                    "natives": (set(), t_count, t_size), 
                    "text": (set(), 0, 0), 
                    "images": (set(), 0, 0), 
                    "total_stats": (t_count, t_size)
                },
                "exp_natives": exp_natives,
                "exp_texts": exp_texts,
                "exp_images": exp_images,
                "missing_natives": missing_natives,
                "missing_texts": missing_texts,
                "missing_images": missing_images,
                "gap_results": gap_results,
                "total_docs": len(self.data),
                "opt_loaded": bool(self.opt_index) 
            }
            
            self.finished.emit()
            
        except Exception as e:
            print("QC ERROR:", str(e))
            self.error.emit(str(e))

# ==========================================
# CUSTOM GRAPHICS VIEW FOR RUBBER-BAND ZOOM
# ==========================================
class ZoomImageView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)        
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.rubberBand = QRubberBand(QRubberBand.Rectangle, self)
        self.origin = QPoint()
        self.is_zooming = False

    def mousePressEvent(self, event):        
        if event.button() == Qt.LeftButton:
            self.origin = event.pos()
            self.rubberBand.setGeometry(QRect(self.origin, QSize()))
            self.rubberBand.show()
            self.is_zooming = True
            event.accept()        
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_zooming:
            self.rubberBand.setGeometry(QRect(self.origin, event.pos()).normalized())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.is_zooming and event.button() == Qt.LeftButton:
            self.rubberBand.hide()
            self.is_zooming = False
            rect = self.rubberBand.geometry()            
            if rect.width() > 10 and rect.height() > 10:
                scene_rect = self.mapToScene(rect).boundingRect()
                self.fitInView(scene_rect, Qt.KeepAspectRatio)
            event.accept()
        else:
            super().mouseReleaseEvent(event)            
    
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
             self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)
             event.accept()
        else:
            super().mouseDoubleClickEvent(event)
    
    def wheelEvent(self, event):
        zoomInFactor = 1.25
        zoomOutFactor = 1 / zoomInFactor
        if event.angleDelta().y() > 0:
            zoomFactor = zoomInFactor
        else:
            zoomFactor = zoomOutFactor
        self.scale(zoomFactor, zoomFactor)
        event.accept()

# ==========================================
# MAIN WINDOW
# ==========================================
class DatEditorFast(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DocuMaster")
        self.resize(1400, 800)
        
        # State
        self.headers = []
        self.data = []
        self.visible_idx = []
        self.filters = {}       
        self.filter_modes = {}  
        self.conditions = []
        self.case_root = None
        self.opt_index = {} 
        self.current_dat_path = None        
        
        self.field_map = {"id": None, "native": None, "text": None}
        self.native_path_cache = {} 
                
        self.current_image_paths = [] 
        self.current_page_idx = 0
        self.pixmap_item = None

        self.build_ui()
        self.build_menu()
        self.update_status()

        self.qc_thread = None
        self.cached_qc_results = None
        self.qc_status_label = QLabel("QC Status: Idle")
        self.statusBar().addPermanentWidget(self.qc_status_label)
        self.setAcceptDrops(True)

        # Setup Ctrl+C for Copying Grid Data
        self.copy_shortcut = QShortcut(QKeySequence("Ctrl+C"), self.table)
        self.copy_shortcut.activated.connect(self.copy_selected_rows)

    # =====================
    # UI BUILDER
    # =====================
    def build_ui(self):
        central = QWidget()
        main_layout = QVBoxLayout(central)
        self.setCentralWidget(central)
        
        self.main_tabs = QTabWidget()
        main_layout.addWidget(self.main_tabs)
        
        # --- TAB 1: DAT / CSV EDITOR ---
        self.dat_tab = QWidget()
        dat_layout = QHBoxLayout(self.dat_tab)
                
        self.outer_splitter = QSplitter(Qt.Horizontal)
        
        # --- COLUMN VISIBILITY PANEL (LEFT) ---
        self.column_panel = QWidget()
        col_layout = QVBoxLayout(self.column_panel)
        col_layout.setContentsMargins(2, 5, 2, 5)
        col_layout.addWidget(QLabel("<b>Toggle Columns</b>"))
        
        self.col_list_widget = QListWidget()
        self.col_list_widget.itemChanged.connect(self.on_column_toggle)
        col_layout.addWidget(self.col_list_widget)
        
        btn_lay = QHBoxLayout()
        self.btn_all_cols = QPushButton("Show All")
        self.btn_none_cols = QPushButton("Hide All")
        self.btn_all_cols.clicked.connect(self.show_all_cols)
        self.btn_none_cols.clicked.connect(self.hide_all_cols)
        btn_lay.addWidget(self.btn_all_cols)
        btn_lay.addWidget(self.btn_none_cols)
        col_layout.addLayout(btn_lay)
        
        self.outer_splitter.addWidget(self.column_panel)
        self.splitter = QSplitter(Qt.Horizontal)                
        self.preview_container = QWidget()                        
        preview_layout = QVBoxLayout(self.preview_container)
        self.preview_tabs = QTabWidget()
                
        self.text_preview = QTextEdit()
        self.text_preview.setReadOnly(True)
        self.preview_tabs.addTab(self.text_preview, "Text")
                
        self.native_container = QWidget()
        self.native_layout = QVBoxLayout(self.native_container)
        self.native_msg = QLabel("Select a row")
        self.native_msg.setAlignment(Qt.AlignCenter)
        self.native_layout.addWidget(self.native_msg)
        self.preview_tabs.addTab(self.native_container, "Native")
                
        image_tab_widget = QWidget()
        image_tab_layout = QVBoxLayout(image_tab_widget)
                
        self.image_scene = QGraphicsScene()
        self.image_view = ZoomImageView(self.image_scene)
        self.image_view.setBackgroundBrush(Qt.lightGray)
        image_tab_layout.addWidget(self.image_view, 1)
        
        self.nav_controls = QWidget()
        nav_layout = QHBoxLayout(self.nav_controls)
        nav_layout.setContentsMargins(0, 5, 0, 0)
        
        self.btn_prev_page = QPushButton("◀")
        self.btn_prev_page.clicked.connect(self.prev_page)
        self.btn_next_page = QPushButton("▶")
        self.btn_next_page.clicked.connect(self.next_page)
        
        self.lbl_page_count = QLabel("Page 0 of 0")
        
        self.spin_goto = QSpinBox()
        self.spin_goto.setMinimum(1)
        self.spin_goto.setMaximum(1)
        self.btn_goto = QPushButton("Go")
        self.btn_goto.clicked.connect(self.goto_page_btn)

        nav_layout.addWidget(self.btn_prev_page)
        nav_layout.addWidget(self.lbl_page_count)
        nav_layout.addWidget(self.btn_next_page)
        nav_layout.addStretch()
        nav_layout.addWidget(QLabel("Go to:"))
        nav_layout.addWidget(self.spin_goto)
        nav_layout.addWidget(self.btn_goto)
        
        image_tab_layout.addWidget(self.nav_controls)
        self.nav_controls.hide()

        self.preview_tabs.addTab(image_tab_widget, "Image")
        self.preview_tabs.currentChanged.connect(self.on_tab_changed)

        preview_layout.addWidget(QLabel("<b>Preview Panel</b> (Right-click image to reset zoom)"))
        preview_layout.addWidget(self.preview_tabs)
        self.splitter.addWidget(self.preview_container)
        self.preview_container.hide() 
        
        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().sectionClicked.connect(self.open_filter_popup)
        self.table.verticalHeader().setDefaultSectionSize(24)
        
        self.splitter.addWidget(self.table)
        self.splitter.setSizes([0, 1]) 

        # Inner splitter ko Outer splitter mein daala
        self.outer_splitter.addWidget(self.splitter)
        self.outer_splitter.setSizes([200, 1200]) # Left panel default width
        
        dat_layout.addWidget(self.outer_splitter)
        self.main_tabs.addTab(self.dat_tab, "DAT/CSV Editor")

        # --- TAB 2: STANDALONE OPT EDITOR ---
        self.opt_tab = QWidget()
        opt_layout = QVBoxLayout(self.opt_tab)
        
        self.opt_toolbar = QHBoxLayout()
        
        self.btn_save_opt = QPushButton("💾 Save Standalone OPT")
        self.btn_save_opt.setStyleSheet("background-color: #005A9E; color: #FFFFFF; font-weight: bold; padding: 5px;")
        self.btn_save_opt.clicked.connect(self.save_standalone_opt)
        self.opt_toolbar.addWidget(self.btn_save_opt)
        
        self.btn_renumber_opt = QPushButton("🔢 Renumber Suffixes")
        self.btn_renumber_opt.setStyleSheet("background-color: #005A9E; color: #FFFFFF; font-weight: bold; padding: 5px;")
        self.btn_renumber_opt.clicked.connect(self.renumber_opt_sequential)
        self.opt_toolbar.addWidget(self.btn_renumber_opt)
        
        self.opt_toolbar.addStretch()
        
        self.opt_table = QTableView()
        self.opt_table.setAlternatingRowColors(True)
        
        opt_layout.addLayout(self.opt_toolbar)
        opt_layout.addWidget(self.opt_table)
        
        self.main_tabs.addTab(self.opt_tab, "Standalone OPT Editor")
        
        self.status_lbl = QLabel("Ready")
        self.statusBar().addWidget(self.status_lbl)
        
        # Add Encoding Label to Status Bar
        self.lbl_encoding = QLabel(" Encoding: Not Loaded  |  ")
        self.lbl_encoding.setStyleSheet("font-weight: bold; color: #333;")
        self.statusBar().addPermanentWidget(self.lbl_encoding)

    def update_status(self):
        total = len(self.data)
        filtered = len(self.visible_idx)
        if hasattr(self, 'status_lbl'):
            map_str = f"ID: {self.field_map['id']}" if self.field_map['id'] else "No Map"
            self.status_lbl.setText(f"Docs: {total:,} | Filtered: {filtered:,} | {map_str}")

    # =====================
    # COLUMN PANEL LOGIC
    # =====================
    def update_column_list(self):        
        unchecked = set()
        if hasattr(self, 'col_list_widget'):
            for i in range(self.col_list_widget.count()):
                item = self.col_list_widget.item(i)
                if item.checkState() == Qt.Unchecked:
                    unchecked.add(item.text())
        
        self.col_list_widget.blockSignals(True)
        self.col_list_widget.clear()
        
        for i, h in enumerate(self.headers):
            item = QListWidgetItem(h)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            
            if h in unchecked:
                item.setCheckState(Qt.Unchecked)
            else:
                item.setCheckState(Qt.Checked)
                
            item.setData(Qt.UserRole, i)
            self.col_list_widget.addItem(item)
            
        self.col_list_widget.blockSignals(False)
        self.apply_column_visibility()

    def on_column_toggle(self, item):
        col_idx = item.data(Qt.UserRole)
        is_checked = item.checkState() == Qt.Checked
        self.table.setColumnHidden(col_idx, not is_checked)

    def show_all_cols(self):
        self.col_list_widget.blockSignals(True)
        for i in range(self.col_list_widget.count()):
            item = self.col_list_widget.item(i)
            item.setCheckState(Qt.Checked)
            self.table.setColumnHidden(item.data(Qt.UserRole), False)
        self.col_list_widget.blockSignals(False)

    def hide_all_cols(self):
        self.col_list_widget.blockSignals(True)
        for i in range(self.col_list_widget.count()):
            item = self.col_list_widget.item(i)
            item.setCheckState(Qt.Unchecked)
            self.table.setColumnHidden(item.data(Qt.UserRole), True)
        self.col_list_widget.blockSignals(False)

    def apply_column_visibility(self):
        for i in range(self.col_list_widget.count()):
            item = self.col_list_widget.item(i)
            col_idx = item.data(Qt.UserRole)
            is_checked = item.checkState() == Qt.Checked
            self.table.setColumnHidden(col_idx, not is_checked)

    def build_menu(self):
        bar = self.menuBar()
        file_m = bar.addMenu("File")
        file_m.addAction("Open DAT").triggered.connect(self.open_file)
        file_m.addAction("Load OPT (Images)").triggered.connect(self.load_opt)
        file_m.addAction("Export").triggered.connect(self.open_export)
        file_m.addAction("Exit").triggered.connect(self.close)
        
        edit_m = bar.addMenu("Edit")
        edit_m.addAction("Find / Replace").triggered.connect(self.open_find_replace)
        edit_m.addAction("Add Field").triggered.connect(self.open_add_field)
        edit_m.addAction("Native Rename (Disk)").triggered.connect(self.open_native_rename)
        edit_m.addAction("Overlay Data").triggered.connect(self.open_overlay)

        process_menu = bar.addMenu("Process")       
        datetime_multi_action = process_menu.addAction("Date Time Format Tool")
        datetime_multi_action.triggered.connect(self.open_datetime_format_tool)
        tz_action = process_menu.addAction("Time Zone Converter")
        tz_action.triggered.connect(self.open_timezone_tool)        
        process_menu.addAction("Concatenate Fields").triggered.connect(self.open_concatenate_tool)
        process_menu.addAction("Split Field").triggered.connect(self.open_split_tool)
        process_menu.addAction("Metadata Scrub").triggered.connect(self.open_metadata_scrub_tool)
        process_menu.addAction("Image Branding / Endorsement").triggered.connect(self.open_branding_tool)
        process_menu.addSeparator()
        process_menu.addAction("Custom Structured Export (Rename & Folders)").triggered.connect(self.run_custom_structured_export)

        view_m = bar.addMenu("View")
        view_m.addAction("Toggle Preview").triggered.connect(self.toggle_preview)
        view_m.addAction("Clear Filters").triggered.connect(self.clear_filters)
        view_m.addAction("Advanced Conditions").triggered.connect(self.open_conditions)

        qc_m = bar.addMenu("QC")
        qc_m.addAction("Run Basic QC (Structure)").triggered.connect(self.run_basic_qc)
        qc_m.addAction("Run Deep Text QC (Content)").triggered.connect(self.run_text_content_qc)
        qc_m.addAction("Check Bates Gaps & Duplicates").triggered.connect(self.run_bates_gap_check)        
        qc_m.addAction("Run Post-Export QC (Delivery Report)").triggered.connect(self.open_post_export_qc)

        # Added New Validation Tools to QC Menu
        bates_action = QAction("Validate Bates Ranges", self)
        bates_action.triggered.connect(self.validate_bates)
        qc_m.addAction(bates_action) 

        pm_action = QAction("Validate PM Metadata CSV", self)
        pm_action.triggered.connect(self.validate_pm_metadata)
        qc_m.addAction(pm_action)

    # =====================
    # FILE OPERATIONS
    # =====================    

    def open_file(self, path=None):
        if not isinstance(path, str): # Handle click from menu
            path, _ = QFileDialog.getOpenFileName(self, "Open DAT/CSV", "", "DAT/CSV (*.dat *.csv *.txt)")
        if not path: return
                
        progress = QProgressDialog("Reading file... Please wait.", "Cancel", 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()

        try:
            self.status_lbl.setText("Reading file...")
            
            self.current_dat_path = path
            self.case_root = utils.detect_case_root(path)
            enc = utils.detect_encoding(path)
            self.lbl_encoding.setText(f" Encoding: {enc.upper()}  |  ")
            
            # --- Auto-Detect Delimiter based on Extension ---
            if path.lower().endswith(".csv"):
                delimiter = ","
                quotechar = '"'
            else:
                # Default for .dat (Concordance)
                delimiter = "\x14"
                quotechar = "\xFE"
            # -----------------------------------------------------
            
            with open(path, "r", encoding=enc, errors="ignore") as f:            
                if progress.wasCanceled(): return
                
                # Reader with dynamic delimiter
                reader = csv.reader(f, delimiter=delimiter, quotechar=quotechar)
                
                # --- FIX: Prevent crash/freeze on large files (>10k docs) ---
                rows = []
                for i, r in enumerate(reader):
                    rows.append(r)
                    if i % 15000 == 0:  # Keep UI responsive
                        progress.setLabelText(f"Reading row {i:,}...")
                        QApplication.processEvents()
                        if progress.wasCanceled(): return
                # --------------------------------------------------------------
            
            if not rows: raise Exception("File is empty")
                        
            progress.setLabelText("Parsing headers...")
            QApplication.processEvents()

            # Clean headers based on file type
            if path.lower().endswith(".csv"):                
                self.headers = [h.strip() for h in rows[0]]
            else:                
                self.headers = [h.replace("\xfe", "").replace("\x14", "").replace("\ufeff", "").strip() for h in rows[0]]
            
            self.data = rows[1:]
            self.visible_idx = list(range(len(self.data)))
            
            # Reset UI
            progress.close() 
            self.table.setUpdatesEnabled(True)
            
            # Show Import Dialog
            from dialogs import ImportMappingDialog
            dlg = ImportMappingDialog(self.headers)
            if not dlg.exec(): 
                self.status_lbl.setText("Import Cancelled")
                return 
            self.field_map = dlg.get_mapping()
            
            from dialogs import ImportFieldSelectionDialog
            field_dlg = ImportFieldSelectionDialog(self.headers, self)
            if field_dlg.exec() != QDialog.Accepted:
                self.status_lbl.setText("Import Cancelled")
                return
                
            selected_fields = field_dlg.get_selected_fields()
            
            # Ensure mapped fields (DocID, Native, Text) are never missed
            mapped_keys = [self.field_map.get('id'), self.field_map.get('native'), self.field_map.get('text')]
            for k in mapped_keys:
                if k and k not in selected_fields:
                    selected_fields.insert(0, k)
                    
            if not selected_fields:
                QMessageBox.warning(self, "Error", "No fields selected!")
                return
                
            # Filter Data based on selection
            col_indices = [self.headers.index(f) for f in selected_fields]
            self.headers = selected_fields
            
            # --- FIX: Prevent freeze during grid build ---
            filtered_data = []
            progress.setLabelText("Building Grid Data...")
            for i, row in enumerate(self.data):
                filtered_row = [row[j] if j < len(row) else "" for j in col_indices]
                filtered_data.append(filtered_row)
                if i % 15000 == 0:
                    QApplication.processEvents()
            self.data = filtered_data                      
            # -----------------------------------------------
            self.update_column_list()
                        
            # Cache Native Paths (Optional)
            self.native_path_cache = {}
            if self.field_map["native"]:
                try:
                    nat_col = self.headers.index(self.field_map["native"])
                    self.status_lbl.setText("Caching native paths...")
                    QApplication.processEvents()
                    
                    for idx, row in enumerate(self.data):
                        if idx > 5000: break 
                        rel_path = row[nat_col] if nat_col < len(row) else None
                        if rel_path:
                            full_path = utils.resolve_relative_path(self.case_root, rel_path)
                            if full_path: self.native_path_cache[idx] = full_path
                except Exception as e: print(f"Caching Warning: {e}")
            
            # Render Table
            self.table.setUpdatesEnabled(False)
            self.refresh_table(auto_resize=True)
            self.update_status()
            self.table.setUpdatesEnabled(True)
            
            sel = self.table.selectionModel()
            if sel: sel.currentChanged.connect(self.on_row_select)
            self.start_background_qc()

        except Exception as e:
            progress.close()            
            QMessageBox.critical(self, "Load Error", f"Could not load file:\n{str(e)}")
        finally:
            progress.close()
            self.table.setUpdatesEnabled(True)

    def refresh_table(self, auto_resize=False):        
        locked_idx = -1
        if self.field_map.get("id"):
            try:                
                nf = utils.normalize_header(self.field_map["id"])
                for i, h in enumerate(self.headers):
                    if utils.normalize_header(h) == nf:
                        locked_idx = i
                        break
            except: 
                pass
        
        model = LazyDatTableModel(self.headers, self.data, self.visible_idx, locked_col=locked_idx)
        self.table.setModel(model)
                
        if hasattr(self, 'apply_column_visibility'):
            self.apply_column_visibility()
        
        if auto_resize: 
            self.resize_columns_fast()

    def resize_columns_fast(self):
        fm = QFontMetrics(self.table.font())
        padding = 20
        max_rows = 100
        for col in range(len(self.headers)):
            max_w = fm.horizontalAdvance(self.headers[col]) + padding
            for r in range(min(len(self.data), max_rows)):
                try: 
                    w = fm.horizontalAdvance(str(self.data[r][col])[:50]) + padding
                    max_w = max(max_w, w)
                except: pass
            self.table.setColumnWidth(col, min(max_w, 300))

    def load_opt(self, path=None):
        if not self.case_root or not self.field_map.get("id"):
            QMessageBox.warning(self, "Error", "Load DAT & Map ID first.")
            return

        if not isinstance(path, str):
            path, _ = QFileDialog.getOpenFileName(self, "Load OPT", "", "OPT (*.opt)")
        if not path: return

        self.opt_index = {}
        
        # Track current document being processed
        current_doc_id = None
        
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line: continue

                    # Standard OPT: DocID, Volume, Path, DocBreak(Y), ...
                    parts = [p.strip() for p in line.split(",")]
                    
                    # Need at least ID, Vol, Path
                    if len(parts) < 3: continue

                    bates_val = parts[0].replace("\ufeff", "")
                    img_rel = parts[2]
                                        
                    # Column 3 usually holds 'Y' for Document Break
                    is_new_doc = False
                    
                    # Check if 'Y' flag exists in column 3
                    if len(parts) > 3 and parts[3].upper() == 'Y':
                        is_new_doc = True
                    
                    # Fallback: If it's the very first line, start a doc
                    if current_doc_id is None:
                        is_new_doc = True
                        
                    # Update Current Doc ID only if it's a new document
                    if is_new_doc:
                        current_doc_id = bates_val
                    
                    # Resolve Path
                    img_full = utils.resolve_relative_path(self.case_root, img_rel)
                    
                    self.opt_index.setdefault(current_doc_id, []).append({
                        "page": 0, # Page numbering will be auto-sorted by list order
                        "path": img_full,
                        "bates": bates_val
                    })
            
            total_docs = len(self.opt_index)
            total_images = sum(len(pages) for pages in self.opt_index.values())
            
            msg = f"OPT Images Loaded Successfully!\n\n📄 Total Documents: {total_docs}\n🖼️ Total Images: {total_images}"
            QMessageBox.information(self, "Import Status", msg)
            self.start_background_qc()
        except Exception as e:
            QMessageBox.critical(self, "OPT Error", str(e))
    
    def open_native_rename(self):
        # 1. Validation: Checks if naitves are mapped
        native_field = self.field_map.get("native")
        if not self.case_root or not native_field:
            QMessageBox.warning(self, "Error", "Please map a Native column first (File > Open DAT).")
            return
        
        try:
            native_col_idx = self.headers.index(native_field)
        except:
            QMessageBox.warning(self, "Error", f"Mapped column '{native_field}' not found in grid.")
            return

        # --- NEW FIX: Pre-flight existence check ---
        missing_preview = 0
        for r_idx in self.visible_idx:
            rp = self.data[r_idx][native_col_idx]
            if rp and not os.path.exists(utils.resolve_relative_path(self.case_root, rp)):
                missing_preview += 1
        if missing_preview > 0:
            if QMessageBox.warning(self, "Dry-Run Warning", f"{missing_preview} files are missing on disk and will fail. Continue?", QMessageBox.Yes|QMessageBox.No) != QMessageBox.Yes:
                return

        # 2. Open Config Dialog
        from dialogs import NativeRenameConfigDialog
        dlg = NativeRenameConfigDialog(native_field)
        if dlg.exec() != QDialog.Accepted:
            return

        cfg = dlg.get_values()
        sep = cfg["separator"]
        suffix = cfg["suffix"]

        if not suffix:
            QMessageBox.warning(self, "Error", "Suffix text cannot be empty.")
            return

        # 3. Confirmation
        total_files = len(self.visible_idx)
        confirm_msg = (
            f"⚠️ WARNING: You are about to RENAME {total_files} files on the DISK.\n\n"
            f"Pattern: [OriginalName]{sep}{suffix}.[ext]\n"
            "The DAT grid will also be updated with new paths.\n\n"
            "Are you sure you want to proceed?"
        )
        
        if QMessageBox.question(self, "Confirm Disk Rename", confirm_msg, QMessageBox.Yes|QMessageBox.No) != QMessageBox.Yes:
            return
        
        # 4. Processing
        progress = QProgressDialog("Renaming files...", "Cancel", 0, total_files, self)
        progress.setWindowModality(Qt.WindowModal)
        
        renamed_count = 0
        skipped_count = 0
        errors = 0
        
        self.table.setUpdatesEnabled(False) # UI Freeze for speed

        for i, r_idx in enumerate(self.visible_idx):
            if i % 10 == 0:
                progress.setValue(i)
                QApplication.processEvents()
            if progress.wasCanceled(): break
            
            # Get Current Values
            rel_path = self.data[r_idx][native_col_idx]
            
            # Skip empty cells
            if not rel_path:
                skipped_count += 1
                continue

            # Resolve Absolute Path
            full_old_path = utils.resolve_relative_path(self.case_root, rel_path)
            
            # Check if file exists
            if not full_old_path or not os.path.exists(full_old_path):
                skipped_count += 1 # File missing on disk
                continue
                
            # Construct New Name
            dir_name = os.path.dirname(full_old_path)
            file_name = os.path.basename(full_old_path)
            name, ext = os.path.splitext(file_name)
            
            # Logic: ABC.xls -> ABC_Confidential.xls
            new_filename = f"{name}{sep}{suffix}{ext}"
            full_new_path = os.path.join(dir_name, new_filename)
            
            # Prevent overwrite
            if os.path.exists(full_new_path):                
                errors += 1 
                continue

            try:
                # A. Rename on Disk
                os.rename(full_old_path, full_new_path)
                
                # B. Update Grid (Relative Path)                
                old_rel_dir = os.path.dirname(rel_path)
                new_rel_path = os.path.join(old_rel_dir, new_filename)
                
                # Windows slashes fix
                if "\\" in rel_path:
                    new_rel_path = new_rel_path.replace("/", "\\")
                else:
                    new_rel_path = new_rel_path.replace("\\", "/")

                self.data[r_idx][native_col_idx] = new_rel_path
                
                # C. Update Cache
                if r_idx in self.native_path_cache:
                    self.native_path_cache[r_idx] = full_new_path

                renamed_count += 1
                
            except Exception as e:
                print(f"Rename Error: {e}")
                errors += 1

        self.table.setUpdatesEnabled(True)
        progress.setValue(total_files)
        
        self.table.model().layoutChanged.emit() # Refresh Grid
        
        msg = (
            f"Operation Complete.\n\n"
            f"✅ Renamed: {renamed_count}\n"
            f"⏭ Skipped (Missing/Empty): {skipped_count}\n"
            f"❌ Errors (Perms/Exists): {errors}"
        )
        QMessageBox.information(self, "Result", msg)

    # =====================
    # PREVIEW LOGIC
    # =====================
    def toggle_preview(self):
        if self.preview_container.isVisible():
            self.preview_container.hide()
            self.splitter.setSizes([0, 1])
        else:
            self.preview_container.show()
            self.splitter.setSizes([400, 1000])

    def on_tab_changed(self, index):
        if not self.preview_container.isVisible(): return
        selection = self.table.selectionModel()
        if not selection or not selection.hasSelection(): return
        current_idx = selection.currentIndex()
        if current_idx.isValid():
            self.update_preview_content(current_idx)

    def on_row_select(self, current, previous):
        if not current.isValid(): return
        if not self.preview_container.isVisible(): return
        self.update_preview_content(current)

    def update_preview_content(self, index_obj):
        real_row = self.visible_idx[index_obj.row()]
        idx = self.preview_tabs.currentIndex()
        if idx == 0: self.load_text_preview(real_row)
        elif idx == 1: self.load_native_preview(real_row)
        elif idx == 2: self.load_image_preview(real_row)

    def load_text_preview(self, row_idx):
        fname = self.field_map.get("text")
        if not fname: self.text_preview.setText("Text path not mapped."); return
        try: col = self.headers.index(fname)
        except: self.text_preview.setText("Mapped field missing."); return
        
        path = utils.resolve_relative_path(self.case_root, self.data[row_idx][col])
        if path and os.path.exists(path):
            try: 
                with open(path, "r", encoding="utf-8", errors="ignore") as f: 
                    self.text_preview.setText(f.read())
            except: self.text_preview.setText("Error reading text.")
        else:
            self.text_preview.setText("File not found.")

    # ==========================================
    # PATCH: SMART NATIVE PREVIEW (Excel/Office)
    # ==========================================
    def load_native_preview(self, row_idx):        
        for i in reversed(range(self.native_layout.count())): 
            if self.native_layout.itemAt(i).widget(): 
                self.native_layout.itemAt(i).widget().setParent(None)
                
        fname = self.field_map.get("native")
        if not fname: 
            self.native_layout.addWidget(QLabel("Native not mapped."))
            return
        
        try: col = self.headers.index(fname)
        except: 
            self.native_layout.addWidget(QLabel("Mapped field missing."))
            return
        
        path = utils.resolve_relative_path(self.case_root, self.data[row_idx][col])
        
        if not path or not os.path.exists(path): 
            self.native_layout.addWidget(QLabel("File not found."))
            return
        
        ext = os.path.splitext(path)[1].lower()

        # ---------------------------
        # CASE A: IMAGES (Existing)
        # ---------------------------
        if ext in [".jpg", ".png", ".jpeg", ".bmp", ".gif", ".tif", ".tiff"]:
            lbl = QLabel()
            pix = QPixmap(path)
            if not pix.isNull():                
                scaled_pix = pix.scaledToWidth(min(pix.width(), 1000), Qt.SmoothTransformation)
                lbl.setPixmap(scaled_pix)
                lbl.setAlignment(Qt.AlignCenter)
                
                scroll = QScrollArea()
                scroll.setWidget(lbl)
                scroll.setWidgetResizable(True)
                self.native_layout.addWidget(scroll)
            else:
                self.native_layout.addWidget(QLabel("Invalid Image."))
            return

        # ---------------------------
        # CASE B: EXCEL / CSV (New Grid View)
        # ---------------------------
        if ext in [".csv", ".xlsx", ".xls"]:
            self.render_excel_preview(path, ext)
            return

        # ---------------------------
        # CASE C: TEXT BASED (Log, Txt, Py, Eml)
        # ---------------------------
        if ext in [".txt", ".log", ".py", ".ini", ".eml", ".xml", ".json"]:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(10000)
                
                text_viewer = QTextEdit()
                text_viewer.setReadOnly(True)
                text_viewer.setPlainText(content)
                self.native_layout.addWidget(text_viewer)
                return
            except:
                pass

        # ---------------------------
        # CASE D: DEFAULT FALLBACK (Open Button)
        # ---------------------------        
        msg_lbl = QLabel(f"Preview not available for {ext.upper()}\nClick to open in default application.")
        msg_lbl.setAlignment(Qt.AlignCenter)
        self.native_layout.addWidget(msg_lbl)
        
        btn = QPushButton(f"Open Externally: {os.path.basename(path)}")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("padding: 10px; font-weight: bold; background-color: #f0f0f0;")
        btn.clicked.connect(lambda: utils.open_native_file(path))
        self.native_layout.addWidget(btn)
        self.native_layout.addStretch()

    def render_excel_preview(self, path, ext):
        """
        Uses openpyxl to render Excel with layout and basic colors.
        Falls back to pandas for CSV.
        """
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem
        from PySide6.QtGui import QColor, QBrush
        
        if ext == ".csv":
            self.render_simple_csv(path)
            return
        
        try:
            import openpyxl
            from openpyxl.utils import get_column_letter
                        
            wb = openpyxl.load_workbook(path, data_only=True)
            ws = wb.active
            
            max_rows = min(ws.max_row, 100)
            max_cols = min(ws.max_column, 20)
            
            table = QTableWidget(max_rows, max_cols)
            
            table.setHorizontalHeaderLabels([get_column_letter(i) for i in range(1, max_cols + 1)])
            table.verticalHeader().setVisible(True)
            table.setAlternatingRowColors(False)
            
            for r in range(1, max_rows + 1):
                for c in range(1, max_cols + 1):
                    cell = ws.cell(row=r, column=c)
                    val = cell.value
                                        
                    display_text = str(val) if val is not None else ""
                    item = QTableWidgetItem(display_text)
                                        
                    if cell.fill and cell.fill.patternType == "solid":
                        fg = cell.fill.start_color
                        color_code = None
                        
                        if fg.type == "rgb":                            
                            if len(fg.rgb) == 8:
                                color_code = "#" + fg.rgb[2:]
                            else:
                                color_code = "#" + fg.rgb
                                                
                        if color_code:
                            item.setBackground(QColor(color_code))
                                            
                    table.setItem(r-1, c-1, item)

            self.native_layout.addWidget(QLabel(f"Spreadsheet Preview (First {max_rows} rows):"))
            self.native_layout.addWidget(table)

        except ImportError:
            self.native_layout.addWidget(QLabel("Install 'openpyxl' for formatted Excel preview."))
            btn = QPushButton(f"Open Externally")
            btn.clicked.connect(lambda: utils.open_native_file(path))
            self.native_layout.addWidget(btn)
            
        except Exception as e:            
            self.native_layout.addWidget(QLabel(f"Preview Error: {str(e)}"))
            btn = QPushButton(f"Open Externally")
            btn.clicked.connect(lambda: utils.open_native_file(path))
            self.native_layout.addWidget(btn)

    def render_simple_csv(self, path):
        """Fallback CSV viewer without pandas"""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.reader(f)
                rows = list(reader)
            
            if not rows: return
            
            headers = rows[0]
            data = rows[1:101]
            
            tbl = QTableView()
            model = LazyDatTableModel(headers, data, list(range(len(data))))
            tbl.setModel(model)
            self.native_layout.addWidget(tbl)
        except:
            pass

    def build_page_map(self, image_paths):
        """
        Converts list of file paths -> list of (path, frame_index).
        Handles Multi-Page TIFFs where 1 file = multiple pages.
        """
        page_map = []        
    
        check_frames = len(image_paths) < 50 

        for entry in image_paths:
            path = entry["path"] if isinstance(entry, dict) else entry
            
            if not os.path.exists(path):
                page_map.append((path, 0))
                continue
            
            check_ext = path.lower().endswith((".tif", ".tiff", ".jpg", ".jpeg"))
            
            if check_frames and check_ext:
                try:
                    with Image.open(path) as img:
                        frames = getattr(img, "n_frames", 1)
                        if frames > 1:
                            for f in range(frames):
                                page_map.append((path, f))
                        else:
                            page_map.append((path, 0))
                except:
                    page_map.append((path, 0)) # Fallback if corrupt
            else:
                page_map.append((path, 0))
                
        return page_map

    # --- Load Image Preview ---
    def load_image_preview(self, row_idx):
        self.image_scene.clear()
        self.pixmap_item = None
        self.nav_controls.hide()

        # Validation
        if not hasattr(self, "opt_index") or not self.opt_index:
            self.image_scene.addText("Load OPT first.")
            return
            
        field_name = self.field_map.get("id")
        if not field_name:
            self.image_scene.addText("Identifier (DocID) not mapped.")
            return
        
        try: col = self.headers.index(field_name)
        except ValueError: return

        # Get DocID
        raw_val = self.data[row_idx][col]
        docid = raw_val.strip().replace("\ufeff", "")
        
        if docid in self.opt_index:
            raw_paths = self.opt_index[docid]
                        
            self.current_page_map = self.build_page_map(raw_paths)
            
            total_pages = len(self.current_page_map)
            
            if total_pages > 0:
                self.nav_controls.show()
                self.spin_goto.setMaximum(total_pages)
                self.current_page_idx = 0
                self.load_current_page_image()
                
                # Update label immediately
                self.lbl_page_count.setText(f"Page 1 of {total_pages}")
            else:
                 self.image_scene.addText("No valid images found.")
        else:
            self.image_scene.addText(f"DocID '{docid}' not found in OPT.")

    # --- Load Current Page (With Cache & Sharpness) ---
    def load_current_page_image(self):
        if not hasattr(self, "current_page_map") or not self.current_page_map: return
        
        # Get Path AND Frame Number (for multi-page TIFFs)
        path, frame_idx = self.current_page_map[self.current_page_idx]
        
        self.image_scene.clear()
        
        if os.path.exists(path):
            try:
                # Use cached loader (defined outside class)
                pixmap = load_image_cached(path, frame_idx)
                
                if pixmap and not pixmap.isNull():
                    self.pixmap_item = self.image_scene.addPixmap(pixmap)
                    
                    # Fix Blur: Set Smooth Transformation
                    self.pixmap_item.setTransformationMode(Qt.SmoothTransformation)
                    
                    self.image_view.fitInView(self.pixmap_item, Qt.KeepAspectRatio)
                    self.image_scene.setSceneRect(self.pixmap_item.boundingRect())
                else:
                    self.image_scene.addText("Failed to load image (Corrupt or Unsupported).")
            except Exception as e:
                self.image_scene.addText(f"Error: {e}")
        else:
            self.image_scene.addText(f"Image missing on disk:\n{path}")
            
        total = len(self.current_page_map)
        self.lbl_page_count.setText(f"Page {self.current_page_idx + 1} of {total}")
        self.spin_goto.setValue(self.current_page_idx + 1)
        self.btn_prev_page.setEnabled(self.current_page_idx > 0)
        self.btn_next_page.setEnabled(self.current_page_idx < total - 1)

    def prev_page(self):
        if self.current_page_idx > 0:
            self.current_page_idx -= 1
            self.load_current_page_image()

    def next_page(self):        
        if hasattr(self, "current_page_map") and self.current_page_map:
            if self.current_page_idx < len(self.current_page_map) - 1:
                self.current_page_idx += 1
                self.load_current_page_image()
            
    def goto_page_btn(self):        
        if not hasattr(self, "current_page_map") or not self.current_page_map:
            return

        page_num = self.spin_goto.value()
        if 1 <= page_num <= len(self.current_page_map):
            self.current_page_idx = page_num - 1
            self.load_current_page_image()

    # ==========================================
    # MISSING CORE LOGIC FUNCTIONS
    # ==========================================

    def _get_operation_rows(self, scope="filtered"):
        """Helper to determine which rows to process."""
        if scope == "all":
            return list(range(len(self.data)))
        
        elif scope == "selected":            
            selection = self.table.selectionModel()
            if selection:                
                rows = set()
                for idx in selection.selectedIndexes():
                    rows.add(idx.row())
                return sorted(list(rows))
            return []
        
        else:            
            return list(self.visible_idx)

    def _check_condition(self, row, cond):
        """Helper for Advanced Conditions filtering."""
        try:
            col_idx = int(cond["col"])
            op = cond["op"]
            val = str(cond["value"]).lower().strip()
            
            # Safe row access for jagged arrays and strict String conversion
            cell_val = str(row[col_idx]).lower() if col_idx < len(row) else ""

            if op == "is empty": return cell_val == ""
            if op == "is not empty": return cell_val != ""
            if op == "equals": return cell_val == val
            if op == "contains": return val in cell_val
            if op == "starts with": return cell_val.startswith(val)
            if op == "ends with": return cell_val.endswith(val)
            
            return True
        except:
            return False

    def preview_operation(self, ctx):
        """Calculates how many rows will be affected by Find/Replace."""
        rows = self._get_operation_rows(ctx.scope)
        count = 0

        for r in rows:
            if ctx.target_column >= len(self.data[r]): continue
            
            val = self.data[r][ctx.target_column]

            if ctx.action == "search_replace":
                if ctx.find_text in val:
                    count += 1
            else:                
                count += 1
        return count

    def execute_operation(self, ctx):
        """Executes bulk operations: Replace, Append, Insert, Search/Replace, DateTime."""
                
        if self.is_locked_column(ctx.target_column):
            QMessageBox.critical(self, "Security Alert", 
                f"❌ ACCESS DENIED\n\n"
                f"You cannot modify the Identifier field: '{self.headers[ctx.target_column]}'.\n"
                "This field is locked to prevent database corruption."
            )
            return 0
        # ----------------------------------------------

        rows = self._get_operation_rows(ctx.scope)
        updated = 0

        # ---------- 1. DATETIME FORMAT OPERATION ----------
        if ctx.action == "datetime_format":
            from datetime import datetime
            src_py_fmt = utils.convert_format(ctx.datetime_src_format)
            tgt_py_fmt = utils.convert_format(ctx.datetime_tgt_format)

            for r in rows:
                if ctx.datetime_src_column >= len(self.data[r]): continue
                raw = self.data[r][ctx.datetime_src_column]
                if not raw: continue
                try:
                    dt = datetime.strptime(raw.strip(), src_py_fmt)
                    new_val = datetime.strftime(dt, tgt_py_fmt)
                    if ctx.datetime_tgt_column < len(self.data[r]):
                        self.data[r][ctx.datetime_tgt_column] = new_val
                        updated += 1
                except ValueError: continue
            
            self.table.model().layoutChanged.emit()
            self.update_status()
            return updated

        # ---------- 2. TEXT OPERATIONS ----------
        for r in rows:
            if ctx.target_column >= len(self.data[r]): continue
            
            old_val = self.data[r][ctx.target_column]
            new_val = old_val 

            src_val = ""
            if ctx.source_type == "text":
                src_val = ctx.source_value
            elif ctx.source_type == "field":
                try:
                    s_idx = int(ctx.source_value)
                    if s_idx < len(self.data[r]): src_val = self.data[r][s_idx]
                except: pass

            if ctx.action == "replace": new_val = src_val
            elif ctx.action == "append": new_val = (old_val + ctx.separator + src_val) if old_val else src_val
            elif ctx.action == "insert": new_val = (src_val + ctx.separator + old_val) if old_val else src_val
            elif ctx.action == "search_replace":
                if ctx.find_text in old_val: new_val = old_val.replace(ctx.find_text, ctx.replace_text)

            if new_val != old_val:
                self.data[r][ctx.target_column] = new_val
                updated += 1

        self.table.model().layoutChanged.emit()
        self.update_status()
        return updated
        
    def open_filter_popup(self, col_idx):
        if not self.headers: return
        field = self.headers[col_idx]
        
        # Get unique values
        values = sorted(list(set(self.data[r][col_idx] for r in range(len(self.data)))))
        
        # --- FIX 1: Prevent UI Freeze on DocID/Bates column ---
        if len(values) > 15000:
            QMessageBox.warning(self, "Too Many Unique Values", 
                f"This column has {len(values):,} unique values!\n\n"
                "Loading them all in a checklist will freeze the software.\n"
                "Please use 'View > Advanced Conditions' to search/filter this specific column."
            )
            return
        # --------------------------------------------------------

        dlg = FilterDialog(field, values)
        if dlg.exec():
            self.filters[col_idx] = set(dlg.selected_values())
            # --- FIX 2: Removed 'dlg.large_mode' which was causing the Silent Crash ---
            self.apply_filters()

    def apply_filters(self):
        self.table.setUpdatesEnabled(False)
        self.visible_idx = []
                
        for r_idx, row in enumerate(self.data):
            visible = True
                        
            if self.filters:
                for col, allowed in self.filters.items():
                    val = row[col] if col < len(row) else ""
                    if val not in allowed:
                        visible = False; break
                        
            if not visible: 
                continue 
            
            if self.conditions:
                current_result = self._check_condition(row, self.conditions[0])
                
                for i in range(1, len(self.conditions)):
                    cond = self.conditions[i]
                    res = self._check_condition(row, cond)
                    
                    if cond["join"] == "OR":
                        current_result = current_result or res
                    else:
                        current_result = current_result and res
                
                if not current_result:
                    visible = False

            if visible:
                self.visible_idx.append(r_idx)

        self.refresh_table()
        self.update_status()
        self.table.setUpdatesEnabled(True)

    def clear_filters(self):
        self.filters.clear()
        self.conditions.clear() # 🚨 THE FIX: Ab advanced conditions bhi properly delete hongi
        self.visible_idx = list(range(len(self.data)))
        self.refresh_table()
        self.update_status()

    # ==========================================
    # RENAMED FUNCTION TO MATCH MENU
    # ==========================================
    def open_export(self):
        if not self.headers:
            QMessageBox.warning(self, "Export", "No DAT loaded.")
            return

        dlg = ExportDialog(self.headers)
        if dlg.exec() != QDialog.Accepted:
            return

        opts = dlg.export_options()
        fields = opts["fields"]
        renames = opts.get("renames", {})

        if not fields:
            QMessageBox.warning(self, "Export", "No fields selected.")
            return

        is_dat = opts["type"] == "DAT"
        ext = ".dat" if is_dat else ".csv"

        path, _ = QFileDialog.getSaveFileName(self, "Export File", "", f"{opts['type']} Files (*{ext})")
        if not path: return
        if not path.lower().endswith(ext): path += ext

        encoding = utils.get_python_encoding(opts["encoding"])

        col_indexes = []
        for f in fields:
            nf = utils.normalize_header(f)
            for i, h in enumerate(self.headers):
                if utils.normalize_header(h) == nf:
                    col_indexes.append(i); break
        
        rows = list(self.visible_idx)
                
        if opts.get("sort"):
            self.status_lbl.setText("Sorting data...")
            QApplication.processEvents()
            for field, direction in reversed(opts["sort"]):
                col = None
                for i, h in enumerate(self.headers):
                    if utils.normalize_header(h) == utils.normalize_header(field):
                        col = i; break
                if col is not None:
                    rows.sort(key=lambda r: utils.sort_value(self.data[r][col]), reverse=(direction == "DESC"))
        
        try:
            total = len(rows)
            progress = QProgressDialog("Exporting records...", "Cancel", 0, total, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)

            with open(path, "w", encoding=encoding, newline="") as f:
                if is_dat:
                    writer = csv.writer(f, delimiter="\x14", quotechar="\xFE", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
                else:
                    writer = csv.writer(f, lineterminator="\r\n")

                export_headers = [renames.get(f, f) for f in fields]
                writer.writerow(export_headers)
                
                for i, r in enumerate(rows):
                    if i % 500 == 0:
                        progress.setValue(i)
                        if progress.wasCanceled(): 
                            f.close()
                            os.remove(path)
                            return

                    row = self.data[r]
                    writer.writerow([row[i] if i < len(row) else "" for i in col_indexes])
            
            progress.setValue(total)
            QMessageBox.information(self, "Export Complete", f"Exported {total} records.\nFile: {path}")

        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))
        finally:
            self.status_lbl.setText("Ready")

    def open_find_replace(self):
        dlg = FindReplaceDialog(self.headers)
        if dlg.exec():
            ctx = dlg.get_context()
            count = self.execute_operation(ctx)
            if count > 0:
                QMessageBox.information(self, "Done", f"Updated {count} rows.")
            
    def is_locked_column(self, col_idx):
        """Checks if the column is the Mapped Identifier (DocID)."""        
        if not self.field_map.get("id"): 
            return False
            
        if col_idx < 0 or col_idx >= len(self.headers):
            return False
        
        try:
            col_name = self.headers[col_idx]
            id_name = self.field_map["id"]
            return utils.normalize_header(col_name) == utils.normalize_header(id_name)
        except:
            return False

    # =====================
    # QC OPERATIONS
    # =====================
    def start_background_qc(self):
        """Starts QC in background safely using detached data snapshot"""
        if not self.case_root or not self.field_map.get("id"):
            return
        
        # --- CRITICAL FIX 1: Prevent QThread Garbage Collection (Segfault) ---
        if not hasattr(self, 'old_threads'):
            self.old_threads = []
            
        # Clean up finished threads to free memory
        self.old_threads = [t for t in self.old_threads if t.isRunning()]
        
        if self.qc_thread and self.qc_thread.isRunning():
            self.qc_thread.requestInterruption()
            self.old_threads.append(self.qc_thread) # Save reference so it doesn't crash!
        # ---------------------------------------------------------------------

        self.qc_status_label.setText("QC Status: ⏳ Running in Background...")
        self.qc_status_label.setStyleSheet("color: orange; font-weight: bold;")
        self.cached_qc_results = None

        # Prevent Memory Crash by taking a fast, lightweight string-only copy 
        id_field = self.field_map.get("id")
        nat_field = self.field_map.get("native")
        txt_field = self.field_map.get("text")

        # --- NAYA FIX: Auto-Detect New LST/Text Columns if not mapped initially ---
        if not txt_field:
            possible_texts = ["lst_text_path", "textpath", "ocrpath", "textlink", "text_path", "fulltext"]
            for h in self.headers:
                if utils.normalize_header(h) in possible_texts:
                    txt_field = h
                    self.field_map["text"] = h  # Map it permanently for previews & future QCs!
                    self.update_status() # Update status bar 
                    break
        # -------------------------------------------------------------------------
        
        id_col = self.headers.index(id_field) if id_field in self.headers else -1
        nat_col = self.headers.index(nat_field) if nat_field in self.headers else -1
        txt_col = self.headers.index(txt_field) if txt_field in self.headers else -1
        
        end_col = -1
        possible_ends = ["endbates", "enddoc", "end_bates", "prodend", "lastbates", "end"]
        for i, h in enumerate(self.headers):
            if utils.normalize_header(h) in possible_ends:
                end_col = i; break

        snap_headers = ["id", "native", "text", "endbates"]
        snap_data = []
        
        for r in self.data:
            r_len = len(r)
            snap_data.append([
                r[id_col] if id_col != -1 and id_col < r_len else "",
                r[nat_col] if nat_col != -1 and nat_col < r_len else "",
                r[txt_col] if txt_col != -1 and txt_col < r_len else "",
                r[end_col] if end_col != -1 and end_col < r_len else ""
            ])
            
        snap_opt = {k: list(v) for k, v in self.opt_index.items()}

        self.qc_thread = BackgroundQCWorker(
            self.case_root, snap_headers, snap_data, 
            {"id": "id", "native": "native", "text": "text"}, 
            snap_opt
        )
        self.qc_thread.finished.connect(self.on_qc_finished)
        self.qc_thread.start()

    def on_qc_finished(self):
        # --- CRITICAL FIX 2: Ignore signals from old/dead threads ---
        sender_thread = self.sender()
        if sender_thread != self.qc_thread:
            return # Agar yeh signal purane thread se aaya hai, toh use ignore karo
            
        if hasattr(self.qc_thread, "result_data"):
            self.cached_qc_results = self.qc_thread.result_data
            self.qc_status_label.setText("QC Status: ✅ Ready")
            self.qc_status_label.setStyleSheet("color: green; font-weight: bold;")   

    def run_basic_qc(self):
        if not self.case_root:
            QMessageBox.warning(self, "Error", "Case Root not detected.")
            return

        # 1. Check if Cache is Ready
        if self.cached_qc_results:
            # USE CACHE (INSTANT)
            results = self.cached_qc_results
            self.generate_report_from_cache(results)
            return

        # 2. If running, wait or ask user
        if self.qc_thread and self.qc_thread.isRunning():
            QMessageBox.information(self, "Please Wait", "Background QC is still running.\nPlease try again in a few seconds.")
            return

        # 3. Fallback: Run manually if background failed/wasn't started
        self.start_background_qc()
        QMessageBox.information(self, "Started", "Background QC started. You can continue working.\nClick this button again when status says 'Ready'.")

    def generate_report_from_cache(self, r):
        """Generates report instantly using pre-calculated results"""
        
        # Unpack Data
        scan = r["scan_results"]
        act_natives, n_count, n_size = scan["natives"]
        act_texts, t_count, t_size = scan["text"]
        act_images, i_count, i_size = scan["images"]
        
        # Force Accurate Total Stats (Includes all loose/DATA files)
        total_count, total_bytes = scan.get("total_stats", (0, 0))
        if total_count == 0:
             total_count = n_count + t_count + i_count
             total_bytes = n_size + t_size + i_size
        
        # --- FIX: ROBUST BATES RANGE LOGIC WITH USER PROMPT ---
        id_col = self.headers.index(self.field_map["id"])
        first = self.data[0][id_col]
        bates_range = f"{first} - Unknown"
        
        try:
             # Added "end_doc" to auto-detect list
             possible_ends = ["endbates", "enddoc", "end_bates", "end_doc", "prodend", "lastbates", "end"]
             end_col = -1
             
             # 1. Try to auto-detect
             for i, h in enumerate(self.headers):
                if utils.normalize_header(h) in possible_ends:
                    end_col = i; break
             
             # 2. If auto-detect fails, ASK THE USER
             if end_col == -1:
                 item, ok = QInputDialog.getItem(
                     self, 
                     "Select End Bates Column", 
                     "End Doc column not found automatically.\nPlease select the END BATES column:", 
                     self.headers, 
                     0, 
                     False
                 )
                 if ok and item:
                     end_col = self.headers.index(item)
             
             # 3. Apply the selection
             if end_col != -1 and end_col != id_col:
                 last = self.data[-1][end_col]
             else:
                 last = self.data[-1][id_col] # Fallback
                 
             bates_range = f"{first} - {last}"
        except Exception as e: 
             print(f"Bates logic error: {e}")
        # ------------------------------------------------------

        # OPT Validation Check
        if not r["opt_loaded"] and i_count > 0:
             QMessageBox.warning(self, "Warning", 
                f"⚠️ Images detected on disk ({i_count:,}), but software thinks OPT is empty.\n\n"
                "Please reload the OPT file via 'File > Load OPT (Images)' and try again.")

        ctx = {
            "root": self.case_root,
            "disk_stats": (total_count, total_bytes),
            "folders": r["folders"],
            "total_docs": r["total_docs"],
            
            "exp_natives": r["exp_natives"],
            "exp_texts": r["exp_texts"],
            "exp_images": r["exp_images"],
            
            "native_disk_count": len(r["exp_natives"]) - len(r["missing_natives"]),
            "text_disk_count": len(r["exp_texts"]) - len(r["missing_texts"]),
            "image_disk_count": len(r["exp_images"]) - len(r["missing_images"]),

            "missing_natives": r["missing_natives"],
            "extra_natives": act_natives - r["exp_natives"] if act_natives else set(),
            "missing_texts": r["missing_texts"],
            "extra_texts": act_texts - r["exp_texts"] if act_texts else set(),
            "missing_images": r["missing_images"],
            "extra_images": act_images - r["exp_images"] if act_images else set(),
            
            "bates_range": bates_range
        }

        default_name = os.path.join(self.case_root, "QC_REPORT.txt")
        report_path, _ = QFileDialog.getSaveFileName(self, "Save QC Report", default_name, "Text Files (*.txt)")

        if report_path:
            qc_logic.generate_qc_report(ctx, report_path)
            QMessageBox.information(self, "Done", f"Report Generated Instantly!\n{report_path}")
            utils.open_native_file(report_path)

    def run_text_content_qc(self):
        """Dynamic Text Content QC (Threaded for Large Datasets)"""
        if not self.case_root: return

        folders = qc_logic.detect_export_folders(self.case_root)
        text_folder = folders.get("text")
        
        if not text_folder:
            QMessageBox.warning(self, "Error", "No 'TEXT' or 'OCR' folder found in export root.")
            return

        from dialogs import TextQCSettingsDialog
        dlg = TextQCSettingsDialog()
        if dlg.exec() != QDialog.Accepted:
            return
            
        settings = dlg.get_settings()
        search_terms = settings["search_terms"]
        check_empty = settings["check_empty"]

        if not check_empty and not search_terms:
            QMessageBox.information(self, "Info", "Nothing selected to scan.")
            return

        self.text_progress = QProgressDialog("Scanning Text Content (Finding files...). Please wait.", "Cancel", 0, 0, self)
        self.text_progress.setWindowModality(Qt.WindowModal)
        self.text_progress.show()
        
        self.text_worker = TextQCWorker(text_folder, search_terms, check_empty)
        
        def on_progress(i):
            self.text_progress.setLabelText(f"Scanned {i:,} files...")
            if self.text_progress.wasCanceled():
                self.text_worker.requestInterruption()

        def on_finished(stats):
            self.text_progress.close()
            
            # Calculate Counts from the Lists
            empty_count = len(stats.get('empty_docs', []))
            total_hits = empty_count
            
            msg = f"<b>Scan Complete ({stats['scanned']:,} files)</b><br><br>"
            if check_empty:
                msg += f"• Empty Files: {empty_count:,}<br>"
                
            if search_terms:
                msg += "<hr><b>Keywords Found:</b><br>"
                found_any = False
                for term in search_terms:
                    term_lower = term.lower()
                    count = len(stats.get("terms_found", {}).get(term_lower, []))
                    msg += f"• '{term}': {count:,}<br>"
                    if count > 0: found_any = True
                    total_hits += count
                if not found_any: msg += "(No keywords found)"
                
            QMessageBox.information(self, "Text QC Result", msg)

            # ⚡ EXCEL EXPORT LOGIC
            if total_hits > 0:
                export_ans = QMessageBox.question(
                    self, 
                    "Export Details", 
                    f"Issues or Keywords were found!\nWould you like to export the detailed Bates numbers to an Excel file?",
                    QMessageBox.Yes | QMessageBox.No
                )
                
                if export_ans == QMessageBox.Yes:
                    try:
                        import openpyxl
                        from openpyxl.styles import Font, PatternFill
                        
                        default_name = os.path.join(self.case_root if self.case_root else "", "Deep_Text_QC_Hits.xlsx")
                        save_path, _ = QFileDialog.getSaveFileName(self, "Save QC Report", default_name, "Excel Files (*.xlsx)")
                        
                        if save_path:
                            wb = openpyxl.Workbook()
                            ws = wb.active
                            ws.title = "Text QC Hits"
                            
                            # Headers
                            ws.append(["Category / Keyword", "Bates Number (DocID)"])
                            header_font = Font(bold=True, color="FFFFFF")
                            header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
                            ws["A1"].font = header_font
                            ws["A1"].fill = header_fill
                            ws["B1"].font = header_font
                            ws["B1"].fill = header_fill
                            
                            # Dump Data
                            if check_empty:
                                for doc in stats.get('empty_docs', []):
                                    ws.append(["Empty Text File", doc])
                                    
                            for term, docs in stats.get("terms_found", {}).items():
                                for doc in docs:
                                    ws.append([f"Keyword: {term}", doc])
                            
                            ws.column_dimensions["A"].width = 30
                            ws.column_dimensions["B"].width = 40
                            
                            wb.save(save_path)
                            QMessageBox.information(self, "Exported", f"Excel report generated successfully!")
                            utils.open_native_file(save_path)
                    except ImportError:
                        QMessageBox.warning(self, "Error", "openpyxl library is required for Excel export.")
                    except Exception as e:
                        QMessageBox.critical(self, "Error", f"Failed to save Excel file:\n{str(e)}")

        def on_error(err):
            self.text_progress.close()
            QMessageBox.warning(self, "Aborted", err)

        self.text_worker.progress_update.connect(on_progress)
        self.text_worker.finished_scan.connect(on_finished)
        self.text_worker.error.connect(on_error)
        self.text_worker.start()

    # =====================
    # POST-EXPORT QC
    # =====================
    def open_post_export_qc(self):
        # 1. Validation check
        if not self.headers or not self.data:
            QMessageBox.warning(self, "Error", "No Data Loaded.\nPlease load a DAT file first.")
            return

        # 2. Case Root check
        if not self.case_root:
            QMessageBox.warning(self, "Error", "Case Root not detected.")
            return
            
        # --- NEW FIX: Force user to use Background Cache to Bypass 20 min Disk Scan ---
        if not self.cached_qc_results:
            QMessageBox.warning(self, "Error", "Please run 'QC > Run Basic QC' first and wait for the 'Ready' status.\nWe need this to scan files into memory instantly.")
            return

        # 3. Save Path Only
        default_name = os.path.join(self.case_root, "Delivery_QC_Report.xlsx")
        save_path, _ = QFileDialog.getSaveFileName(self, "Save QC Report", default_name, "Excel Files (*.xlsx)")
        
        if not save_path: return

        progress = QProgressDialog("Generating QC Report (This will only take seconds now!)...", "Cancel", 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        QApplication.processEvents()
        
        try:
            # 4. Pass EXACT USER MAPPING & CACHE to logic
            result = qc_logic.validate_export_delivery(
                self.headers,
                self.data, 
                self.opt_index, 
                self.cached_qc_results,
                self.field_map,       # <-- NAYA: Ab software aapki mapping yaad rakhega!
                self.case_root,       # <-- NAYA: Disk check fallback ke liye
                save_path
            )
            progress.close()
            
            if result is True:
                QMessageBox.information(self, "Success", f"QC Report Generated Instantly!\n\nFile: {save_path}")
                utils.open_native_file(save_path)
            else:
                QMessageBox.critical(self, "Error", f"Failed to generate report:\n{result}")
                
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Error", str(e))

    # ==========================================
    # LOGIC: CHECK BATES GAPS (UPDATED)
    # ==========================================
    def run_bates_gap_check(self):
        if not self.headers: return
        
        # 1. Identify Start Column
        beg_field = self.field_map.get("id")
        if not beg_field:
            # Fallback: Try to guess if not mapped
            possible_begs = ["begbates", "begdoc", "beg_bates", "beg doc", "bdoc", "prodbeg", "prod_beg", "beg"]
            for h in self.headers:
                if utils.normalize_header(h) in possible_begs:
                    beg_field = h
                    break
        
        if not beg_field:
            QMessageBox.warning(self, "Error", "Identifier (BegBates) is not mapped.\nPlease map it first or ensure a 'BegDoc' column exists.")
            return
            
        try: beg_col_idx = self.headers.index(beg_field)
        except: return

        # 2. Identify End Column (Improved Auto-Detect)
        end_col_idx = -1
        # Added 'prodend', 'lastbates' etc.
        possible_ends = ["endbates", "enddoc", "end_bates", "end doc", "prodend", "prod_end", "lastbates"]
        
        for i, h in enumerate(self.headers):
            if utils.normalize_header(h) in possible_ends:
                end_col_idx = i
                break

        # 3. Fallback: Ask User if not found
        if end_col_idx == -1:
            item, ok = QInputDialog.getItem(self, "Select End Bates Column", 
                                            f"Could not auto-detect End Bates column matching 'Beg: {beg_field}'.\nPlease select the END BATES column:", 
                                            self.headers, 0, False)
            if ok and item:
                end_col_idx = self.headers.index(item)
            else:
                return # User cancelled

        self.status_lbl.setText(f"Analyzing Bates: {self.headers[beg_col_idx]} -> {self.headers[end_col_idx]}...")
        QApplication.processEvents()
        
        # 4. Run Analysis
        gaps, overlaps = qc_logic.find_bates_issues(self.data, beg_col_idx, end_col_idx)
        
        self.status_lbl.setText("Ready")

        if not gaps and not overlaps:
            QMessageBox.information(self, "Success", "✅ Perfect Sequence!\nNo gaps or overlaps found.")
            return

        msg = (
            f"⚠️ ISSUES FOUND:\n\n"
            f"• Gaps detected: {len(gaps)}\n"
            f"• Overlaps detected: {len(overlaps)}\n\n"
            "Would you like to save the Error Report?"
        )
        
        if QMessageBox.question(self, "Sequence Errors", msg, QMessageBox.Yes|QMessageBox.No) == QMessageBox.Yes:
            default_name = os.path.join(self.case_root if self.case_root else "", "Bates_Gap_Report.txt")
            path, _ = QFileDialog.getSaveFileName(self, "Save Report", default_name, "Text Files (*.txt)")
            
            if path:
                qc_logic.generate_bates_report(gaps, overlaps, path)
                utils.open_native_file(path)

    def open_add_field(self): 
        dlg = AddFieldDialog(self.headers)
        if dlg.exec():
            name = dlg.value()
            if name not in self.headers:
                self.headers.append(name)
                for r in self.data: r.append("")
                self.refresh_table()

    # =====================
    # BRANDING / ENDORSEMENT
    # =====================
    def open_branding_tool(self):
        if not self.headers: return
        if not self.opt_index:
             QMessageBox.warning(self, "Error", "No Images Loaded (OPT).\nPlease load an OPT file first.")
             return

        from dialogs import BrandingConfigDialog
        import branding_logic

        dlg = BrandingConfigDialog(self.headers)
        if dlg.exec() != QDialog.Accepted: return
        
        cfg = dlg.get_config()
        if not cfg["branding"]:
            QMessageBox.warning(self, "Error", "No branding positions configured.")
            return

        out_dir = QFileDialog.getExistingDirectory(self, "Select Output Folder for Branded Images")
        if not out_dir: return

        # --- NAYA CODE: Ask for OPT Save Path ---
        opt_save_path, _ = QFileDialog.getSaveFileName(self, "Save Updated OPT File", os.path.join(out_dir, "Branded_Images.opt"), "OPT Files (*.opt)")
        if not opt_save_path: return
        
        new_opt_data = [] # OPT lines yahan store hongi
        # ----------------------------------------

        rows = self.visible_idx
        progress = QProgressDialog("Branding Images...", "Cancel", 0, len(rows), self)
        progress.setWindowModality(Qt.WindowModal)
        
        success_count = 0
        skip_count = 0
        error_count = 0 # New tracker for errors

        field_indices = {}
        for key, item in cfg["branding"].items():
            if item["type"] == "field":
                try: field_indices[key] = self.headers.index(item["value"])
                except: pass

        for i, r_idx in enumerate(rows):
            if i % 10 == 0: 
                progress.setValue(i)
                QApplication.processEvents()
            if progress.wasCanceled(): break

            row = self.data[r_idx]
            docid_col = self.headers.index(self.field_map["id"])
            docid = row[docid_col]
            
            images = self.opt_index.get(docid, [])
            if not images:
                skip_count += 1
                continue

            doc_branding_map = {}
            for pos, item in cfg["branding"].items():
                text = ""
                if item["type"] == "manual":
                    text = item["value"]
                elif item["type"] == "field" and pos in field_indices:
                    col = field_indices[pos]
                    if col < len(row): text = row[col]
                
                doc_branding_map[pos] = {
                    "text": text,
                    "color": item.get("color", "black")
                }

            is_first_page = True # --- NAYA CODE: Track First Page for DocBreak 'Y' ---

            for img_item in images:                
                if isinstance(img_item, dict):
                    img_path = img_item.get("path")                    
                    page_id = img_item.get("image_key", img_item.get("id", os.path.splitext(os.path.basename(img_path))[0]))
                else:
                    img_path = img_item
                    page_id = os.path.splitext(os.path.basename(img_path))[0]
                
                if not os.path.exists(img_path):
                    skip_count += 1 
                    continue
                
                page_branding_map = {}
                has_color = False # --- NAYA CODE: Check for color ---
                for k, v in doc_branding_map.items():
                    page_branding_map[k] = {"text": v["text"], "color": v["color"]}
                    c = str(v["color"]).lower()
                    if c not in ["black", "#000000", "white", "#ffffff"]:
                        has_color = True
                                
                for pos, item in cfg["branding"].items():
                    if item["type"] == "field" and page_branding_map[pos]["text"] == docid:
                        page_branding_map[pos]["text"] = page_id

                fname = os.path.basename(img_path)
                save_path = os.path.join(out_dir, fname)
                                
                ok = branding_logic.apply_branding_to_image(
                    img_path, 
                    save_path, 
                    page_branding_map, 
                    cfg["font"], 
                    cfg["margin"]
                )
                if ok: 
                    success_count += 1
                    
                    # --- NAYA CODE: Auto-Generate OPT Record ---
                    final_ext = os.path.splitext(fname)[1].lower()
                    
                    # Agar image TIFF hai aur Color use hua hai, toh final image JPG banegi
                    if final_ext in [".tif", ".tiff"] and has_color:
                        final_ext = ".jpg"
                        
                    final_fname = os.path.splitext(fname)[0] + final_ext
                    
                    # --- NEW FIX: Get Full UNC / Absolute Path ---
                    full_unc_path = os.path.abspath(os.path.join(out_dir, final_fname))
                    
                    doc_break = "Y" if is_first_page else ""
                    
                    # OPT format: ImageKey, Volume, Path, DocBreak, Box, Folder, PageCount
                    new_opt_data.append([page_id, "BRANDED_VOL", full_unc_path, doc_break, "", "", ""])
                    is_first_page = False
                    # -------------------------------------------
                else:
                    error_count += 1

        progress.setValue(len(rows))
        
        # --- NAYA CODE: Save the New OPT File ---
        if new_opt_data and opt_save_path:
            try:
                with open(opt_save_path, "w", encoding="utf-8", newline="") as f:
                    for opt_row in new_opt_data:
                        line = ",".join(str(item) for item in opt_row)
                        f.write(line + "\r\n") # E-Discovery Standard CRLF
            except Exception as e:
                QMessageBox.critical(self, "OPT Save Error", f"Could not save OPT file:\n{e}")
        # ----------------------------------------

        msg = f"Processed {success_count} images.\n"
        msg += f"Skipped/Missing on disk: {skip_count}\n"
        if error_count > 0:
            msg += f"Errors during branding: {error_count}\n(Check terminal for details)\n"
            
        if new_opt_data:
            msg += f"\n✅ Updated OPT saved successfully:\n{opt_save_path}"
            
        QMessageBox.information(self, "Branding Complete", msg)

    # ==========================================
    # MISSING HELPER: ADD NEW FIELD
    # ==========================================
    def add_new_field(self, field_name):        
        self.headers.append(field_name)
        target_length = len(self.headers)

        for row in self.data:
            # 🚨 THE FIX: Jab tak row poori lambi na ho jaye, usme blank space bharo
            while len(row) < target_length:
                row.append("") 

        if self.table.model():
            self.table.model().beginResetModel()
            self.table.model().endResetModel()
            
        self.update_status()

    def is_locked_column(self, col_idx):
        if not self.field_map.get("id"): return False
        try:            
            col_name = self.headers[col_idx]
            return utils.normalize_header(col_name) == utils.normalize_header(self.field_map["id"])
        except:
            return False

    def open_datetime_format_tool(self):
        if not self.headers:
            QMessageBox.warning(self, "Error", "No DAT loaded.")
            return

        sel_dlg = MultiFieldSelectionDialog(self.headers)
        if sel_dlg.exec() != QDialog.Accepted:
            return

        selected_fields = sel_dlg.get_selected_indices()
        if not selected_fields:
            return

        from datetime import datetime

        for src_field_name, src_col_idx in selected_fields:

            conf_dlg = DateTimeConfigDialog(src_field_name)
            if conf_dlg.exec() != QDialog.Accepted:
                continue 

            cfg = conf_dlg.get_values()
            
            target_name = cfg["tgt_field"]
            if not target_name: target_name = src_field_name 

            try:
                py_src_fmt = utils.convert_format(cfg["src_fmt"])
                py_tgt_fmt = utils.convert_format(cfg["tgt_fmt"])
            except Exception as e:
                QMessageBox.critical(self, "Format Error", f"Error converting formats: {e}")
                return

            tgt_col_idx = -1
            found_existing = False
            tgt_norm = utils.normalize_header(target_name)
            
            for i, h in enumerate(self.headers):
                if utils.normalize_header(h) == tgt_norm:
                    tgt_col_idx = i
                    found_existing = True
                    break
            
            if not found_existing:
                self.add_new_field(target_name)
                tgt_col_idx = len(self.headers) - 1

            updated_count = 0
            rows_to_process = self.visible_idx 
            first_error = None

            for r_idx in rows_to_process:
                if src_col_idx >= len(self.data[r_idx]): continue
                
                original_val = self.data[r_idx][src_col_idx]
                
                if not original_val or not original_val.strip():
                    continue

                try:
                    clean_val = original_val.strip()
                    dt_obj = datetime.strptime(clean_val, py_src_fmt)
                    new_val = datetime.strftime(dt_obj, py_tgt_fmt)
                    
                    if tgt_col_idx < len(self.data[r_idx]):
                        self.data[r_idx][tgt_col_idx] = new_val
                        updated_count += 1
                except ValueError as e:
                    if first_error is None:
                        first_error = (clean_val, cfg['src_fmt'])
                    continue

            if updated_count == 0 and first_error:
                val, fmt = first_error
                QMessageBox.warning(
                    self, 
                    "Format Mismatch", 
                    f"Could not format any rows for field '{src_field_name}'.\n\n"
                    f"First failed value: '{val}'\n"
                    f"Your Source Format: '{fmt}'\n\n"
                    "Tip: Check AM/PM (tt), 24-hour (HH vs hh), or separators."
                )
            else:
                print(f"Field '{src_field_name}' -> '{target_name}': Updated {updated_count} rows.")

        self.table.resizeColumnsToContents()
        self.table.model().layoutChanged.emit()
        self.update_status()
        if updated_count > 0:
            QMessageBox.information(self, "Done", f"Date Formatting Completed.\nUpdated {updated_count} rows.")

    # ==========================================
    # LOGIC: TIME ZONE CONVERTER
    # ==========================================
    def open_timezone_tool(self):
        if not self.headers: return
        
        sel_dlg = MultiFieldSelectionDialog(self.headers)
        if sel_dlg.exec() != QDialog.Accepted: return
        selected_fields = sel_dlg.get_selected_indices()
        if not selected_fields: return

        try:
            import pytz
            from datetime import datetime
        except ImportError:
            QMessageBox.critical(self, "Error", "pytz library missing.")
            return

        total_updates = 0

        for src_field_name, src_col_idx in selected_fields:
            conf_dlg = TimeZoneConfigDialog(src_field_name)
            if conf_dlg.exec() != QDialog.Accepted: continue

            cfg = conf_dlg.get_values()
            target_name = cfg["tgt_field"] if cfg["tgt_field"] else src_field_name

            try:
                py_src_fmt = utils.convert_format(cfg["src_fmt"])
                py_tgt_fmt = utils.convert_format(cfg["tgt_fmt"])
                src_tz = pytz.timezone(cfg["src_tz"])
                tgt_tz = pytz.timezone(cfg["tgt_tz"])
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e)); return

            tgt_col_idx = -1; found = False; tgt_norm = utils.normalize_header(target_name)
            for i, h in enumerate(self.headers):
                if utils.normalize_header(h) == tgt_norm: tgt_col_idx = i; found = True; break
            if not found:
                self.add_new_field(target_name)
                tgt_col_idx = len(self.headers) - 1

            rows = self.visible_idx
            progress = QProgressDialog(f"Converting {src_field_name}...", "Cancel", 0, len(rows), self)
            progress.setWindowModality(Qt.WindowModal)
            
            field_updates = 0
            for i, r_idx in enumerate(rows):
                if i % 500 == 0: 
                    progress.setValue(i)
                    if progress.wasCanceled(): break
                
                if src_col_idx >= len(self.data[r_idx]): continue
                raw = self.data[r_idx][src_col_idx]
                if not raw or not raw.strip(): continue

                try:
                    dt = datetime.strptime(raw.strip(), py_src_fmt)
                    dt_aware = src_tz.localize(dt)
                    dt_target = dt_aware.astimezone(tgt_tz)
                    new_val = dt_target.strftime(py_tgt_fmt)
                    
                    if tgt_col_idx < len(self.data[r_idx]):
                        self.data[r_idx][tgt_col_idx] = new_val
                        field_updates += 1
                except: continue
            
            progress.setValue(len(rows))
            total_updates += field_updates
            print(f"Processed {src_field_name}: {field_updates} updates")

        self.table.resizeColumnsToContents()
        self.table.model().layoutChanged.emit()
        self.update_status()
        QMessageBox.information(self, "Done", f"Timezone conversion complete.\nTotal updates: {total_updates}")

    # ==========================================
    # LOGIC: CONCATENATE & SPLIT
    # ==========================================
    def open_concatenate_tool(self):
        if not self.headers:
            QMessageBox.warning(self, "Error", "No DAT loaded.")
            return

        dlg = ConcatenateDialog(self.headers)
        if dlg.exec() != QDialog.Accepted:
            return

        data = dlg.get_values()
        fields = data["fields"]
        sep = data["sep"]
        target_name = data["target"]

        if not fields or not target_name:
            QMessageBox.warning(self, "Error", "Please select fields and enter a target name.")
            return

        try:
            src_indices = [self.headers.index(f) for f in fields]
        except ValueError:
            return

        tgt_col_idx = -1
        found = False
        tgt_norm = utils.normalize_header(target_name)
        for i, h in enumerate(self.headers):
            if utils.normalize_header(h) == tgt_norm:
                tgt_col_idx = i; found = True; break
        
        if not found:
            self.add_new_field(target_name)
            tgt_col_idx = len(self.headers) - 1

        rows_to_process = self.visible_idx
        total_rows = len(rows_to_process)
        
        progress = QProgressDialog("Concatenating...", "Cancel", 0, total_rows, self)
        progress.setWindowModality(Qt.WindowModal)
        
        updated_count = 0
        
        for i, r_idx in enumerate(rows_to_process):
            if i % 500 == 0:
                progress.setValue(i)
                if progress.wasCanceled(): break

            values = []
            for col_idx in src_indices:
                if col_idx < len(self.data[r_idx]):
                    val = self.data[r_idx][col_idx]
                    if val and val.strip():
                        values.append(val.strip())
            
            result = sep.join(values)
            
            if tgt_col_idx < len(self.data[r_idx]):
                self.data[r_idx][tgt_col_idx] = result
                updated_count += 1

        progress.setValue(total_rows)

        self.table.model().layoutChanged.emit()
        self.update_status()
        QMessageBox.information(self, "Done", f"Concatenated {updated_count} rows.")

    def open_split_tool(self):
        if not self.headers:
            QMessageBox.warning(self, "Error", "No DAT loaded.")
            return

        dlg = SplitDialog(self.headers)
        if dlg.exec() != QDialog.Accepted:
            return

        data = dlg.get_values()
        src_field = data["source"]
        sep = data["sep"]
        target_names = data["targets"]

        if not target_names or not sep:
            QMessageBox.warning(self, "Error", "Invalid inputs.")
            return

        try: src_idx = self.headers.index(src_field)
        except: return

        target_indices = []
        for t_name in target_names:
            t_idx = -1; found = False; t_norm = utils.normalize_header(t_name)
            for i, h in enumerate(self.headers):
                if utils.normalize_header(h) == t_norm:
                    t_idx = i; found = True; break
            if not found:
                self.add_new_field(t_name)
                t_idx = len(self.headers) - 1
            target_indices.append(t_idx)

        rows = self.visible_idx
        progress = QProgressDialog("Splitting fields...", "Cancel", 0, len(rows), self)
        progress.setWindowModality(Qt.WindowModal)
        
        updated_count = 0
        
        for i, r_idx in enumerate(rows):
            if i % 500 == 0:
                progress.setValue(i)
                if progress.wasCanceled(): break

            if src_idx >= len(self.data[r_idx]): continue
            val = self.data[r_idx][src_idx]
            if not val: continue

            parts = val.split(sep)
            
            did_update = False
            for p_idx, part in enumerate(parts):
                if p_idx < len(target_indices):
                    tgt = target_indices[p_idx]
                    if tgt < len(self.data[r_idx]):
                        self.data[r_idx][tgt] = part.strip()
                        did_update = True
            
            if did_update: updated_count += 1

        progress.setValue(len(rows))
        self.table.model().layoutChanged.emit()
        self.update_status()
        QMessageBox.information(self, "Done", f"Split complete on {updated_count} rows.")

    # ==========================================
    # LOGIC: METADATA SCRUB
    # ==========================================
    def open_metadata_scrub_tool(self):
        if not self.headers: return

        sel_dlg = MultiFieldSelectionDialog(self.headers)
        sel_dlg.setWindowTitle("Select Fields to Scrub (Clear)")
        if sel_dlg.exec() != QDialog.Accepted: return

        selected_fields = sel_dlg.get_selected_indices()
        if not selected_fields: return

        safe_fields = []
        locked_found = False
        
        for name, idx in selected_fields:
            if self.is_locked_column(idx):
                locked_found = True
            else:
                safe_fields.append((name, idx))
        
        if locked_found:
            QMessageBox.warning(self, "Security Warning", 
                "⚠️ One or more selected fields were Identifiers (Locked).\n"
                "They have been automatically deselected to prevent data loss."
            )
        
        if not safe_fields: return
        count = len(self.visible_idx)
        confirm_msg = f"SCRUB {len(safe_fields)} fields for {count} rows?\nThis cannot be undone."
        if QMessageBox.question(self, "Confirm", confirm_msg, QMessageBox.Yes|QMessageBox.No) != QMessageBox.Yes:
            return

        progress = QProgressDialog("Scrubbing...", "Cancel", 0, count, self)
        progress.setWindowModality(Qt.WindowModal)
        
        targets = [idx for _, idx in safe_fields]
        
        for i, r_idx in enumerate(self.visible_idx):
            if i % 500 == 0: 
                progress.setValue(i)
                if progress.wasCanceled(): break
            
            row = self.data[r_idx]
            for col in targets:
                if col < len(row): row[col] = ""

        progress.setValue(count)
        self.table.model().layoutChanged.emit()
        self.update_status()

    def copy_selected_rows(self):
        """Copies selected rows from the QTableView to the clipboard."""
        selection = self.table.selectionModel()
        if not selection.hasSelection(): return
        
        copied_text = ""
        # Sort selection by row then column to maintain grid format
        indexes = sorted(selection.selectedIndexes(), key=lambda x: (x.row(), x.column()))
        
        if not indexes: return
        
        prev_row = indexes[0].row()
        for idx in indexes:
            if idx.row() != prev_row:
                copied_text += "\n" # New line for new row
                prev_row = idx.row()
            else:
                if idx != indexes[0]:
                    copied_text += "\t" # Tab separated for columns
            
            item_data = self.table.model().data(idx, Qt.DisplayRole)
            copied_text += str(item_data) if item_data else ""
            
        QApplication.clipboard().setText(copied_text)

    def validate_bates(self):
        if not self.data:
            QMessageBox.warning(self, "Error", "Please load DAT file first.")
            return
            
        expected_begin, ok = QInputDialog.getText(self, "Bates Validation", "Enter Expected Begin Bates:")
        if not ok or not expected_begin.strip(): return
        expected_begin = expected_begin.strip()
        
        id_field = self.field_map.get("id")
        id_col = self.headers.index(id_field) if id_field in self.headers else 0
        
        end_col = -1
        possible_ends = ["endbates", "enddoc", "end_bates", "end_doc", "prodend", "prod_end", "lastbates", "end"]
        for i, h in enumerate(self.headers):
            if utils.normalize_header(h) in possible_ends:
                end_col = i
                break
                
        dat_beg = str(self.data[0][id_col]).strip()
        dat_end = str(self.data[-1][end_col]).strip() if end_col > -1 else str(self.data[-1][id_col]).strip()
        
        opt_beg, opt_end = "Not Loaded", "Not Loaded"
        if self.opt_index:
            doc_keys = list(self.opt_index.keys())
            if doc_keys:
                opt_beg_doc = doc_keys[0]
                opt_end_doc = doc_keys[-1]
                first_page = self.opt_index[opt_beg_doc][0]
                last_page = self.opt_index[opt_end_doc][-1]
                
                opt_beg = str(first_page.get("bates", opt_beg_doc) if isinstance(first_page, dict) else first_page).strip()
                opt_end = str(last_page.get("bates", opt_end_doc) if isinstance(last_page, dict) else last_page).strip()

        msg = f"<h3 style='color:#005A9E;'>Bates Validation Report</h3>"
        msg += f"<b>Expected Begin Bates:</b> {expected_begin}<br><hr>"
        
        dat_beg_match = "<span style='color:green;'>✅ MATCH</span>" if dat_beg.lower() == expected_begin.lower() else "<span style='color:red;'>❌ MISMATCH (vs Expected)</span>"
        msg += f"<b>DAT Begin Bates:</b> {dat_beg} {dat_beg_match}<br>"
        msg += f"<b>DAT End Bates:</b> {dat_end}<br><br>"
        
        if self.opt_index:
            opt_beg_match = "<span style='color:green;'>✅ MATCH (vs DAT)</span>" if opt_beg.lower() == dat_beg.lower() else "<span style='color:red;'>❌ MISMATCH (vs DAT)</span>"
            opt_end_match = "<span style='color:green;'>✅ MATCH (vs DAT)</span>" if opt_end.lower() == dat_end.lower() else "<span style='color:red;'>❌ MISMATCH (vs DAT)</span>"
            
            msg += f"<b>OPT Begin Bates:</b> {opt_beg} {opt_beg_match}<br>"
            msg += f"<b>OPT End Bates:</b> {opt_end} {opt_end_match}<br><hr>"
            
            if opt_beg.lower() == dat_beg.lower() and opt_end.lower() == dat_end.lower():
                msg += "<h4 style='color:green; margin-top:5px;'>✅ SUCCESS: DAT and OPT Boundaries Match Perfectly!</h4>"
            else:
                msg += "<h4 style='color:red; margin-top:5px;'>❌ WARNING: DAT and OPT Boundaries DO NOT MATCH!</h4>"
            
        QMessageBox.information(self, "Bates Validation", msg)

    def validate_pm_metadata(self):
        if not self.headers:
            QMessageBox.warning(self, "Error", "Please load a DAT file first to compare headers.")
            return
            
        path, _ = QFileDialog.getOpenFileName(self, "Select PM Metadata CSV", "", "CSV Files (*.csv)")
        if not path: return
        
        try:
            import csv
            import os
            from datetime import datetime
            
            pm_headers_list = []
            with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                reader = csv.reader(f)
                csv_rows = list(reader)
                
            if not csv_rows: return QMessageBox.warning(self, "Error", "CSV is empty.")
            
            header_row = [str(x).strip().lower() for x in csv_rows[0]]
            dat_header_idx = -1
            
            for i, col in enumerate(header_row):
                valid_keywords = ["dat file field name", "dat header", "dat field", "field name", "fieldname", "header"]
                if any(kw in col for kw in valid_keywords):
                    dat_header_idx = i; break
            
            if dat_header_idx == -1:
                for i, col in enumerate(header_row):
                    if "dat" in col: dat_header_idx = i; break
            if dat_header_idx == -1: dat_header_idx = 0 
                
            for row in csv_rows[1:]:
                if len(row) > dat_header_idx:
                    val = str(row[dat_header_idx]).strip()
                    if val: pm_headers_list.append(val)
                    
            dat_set = set(self.headers)
            pm_set = set(pm_headers_list)
            missing_in_dat = pm_set - dat_set
            extra_in_dat = dat_set - pm_set
            
            if not missing_in_dat and not extra_in_dat:
                QMessageBox.information(self, "Perfect Match", "✅ SUCCESS: All headers in your DAT file exactly match the PM Metadata CSV!")
            else:
                msg = "<h3 style='color:red;'>Header Mismatch Found!</h3>"
                if missing_in_dat:
                    msg += f"<b>Missing in DAT (But requested by PM):</b><br><ul>"
                    for h in missing_in_dat: msg += f"<li>{h}</li>"
                    msg += "</ul>"
                if extra_in_dat:
                    msg += f"<b>Extra in DAT (Not in PM CSV):</b><br><ul>"
                    for h in extra_in_dat: msg += f"<li>{h}</li>"
                    msg += "</ul>"
                QMessageBox.warning(self, "Validation Result", msg)

            try:
                import openpyxl
                from openpyxl.styles import Font, PatternFill
                
                downloads_folder = os.path.join(os.path.expanduser('~'), 'Downloads')
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                excel_path = os.path.join(downloads_folder, f"Header_Validation_{timestamp}.xlsx")
                
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = "Validation Report"
                
                ws["A1"] = "PM CSV DAT HEADERS"
                ws["B1"] = "ACTUAL DAT HEADERS"
                ws["C1"] = "EXACT MATCH"
                
                header_font = Font(bold=True, color="FFFFFF")
                header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
                for col in ["A1", "B1", "C1"]:
                    ws[col].font = header_font
                    ws[col].fill = header_fill
                    
                max_len = max(len(pm_headers_list), len(self.headers))
                for i in range(max_len):
                    row_num = i + 2
                    ws[f"A{row_num}"] = pm_headers_list[i] if i < len(pm_headers_list) else ""
                    ws[f"B{row_num}"] = self.headers[i] if i < len(self.headers) else ""
                    ws[f"C{row_num}"] = f"=EXACT(A{row_num}, B{row_num})"
                    
                ws.column_dimensions["A"].width = 40
                ws.column_dimensions["B"].width = 40
                ws.column_dimensions["C"].width = 20
                
                wb.save(excel_path)
                QMessageBox.information(self, "Report Saved", f"Excel report generated automatically in Downloads:\n{excel_path}")
                
            except ImportError:
                pass
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to process CSV:\n{str(e)}")

    def open_overlay(self, path=None):
        if not isinstance(path, str):
            # FIX: Added .lst support
            path, _ = QFileDialog.getOpenFileName(self, "Overlay File", "", "Data Files (*.dat *.csv *.lst)")
        if not path: return

        progress_read = QProgressDialog("Reading overlay file...", "Cancel", 0, 0, self)
        progress_read.show()
        QApplication.processEvents()

        try:
            enc = utils.detect_encoding(path)
            
            # --- FIX: Smart Ext & Delimiter Check for LST ---
            ext = path.lower().split('.')[-1]
            
            with open(path, "r", encoding=enc, errors="ignore") as f:
                first_line = f.readline()
                f.seek(0)
                
                if ext == "csv":
                    reader = csv.reader(f)
                elif ext == "lst":
                    # LST files usually use Pipe (|), Comma (,) or Concordance (\x14)
                    if '\x14' in first_line:
                        reader = csv.reader(f, delimiter="\x14", quotechar="\xFE")
                    elif '|' in first_line:
                        reader = csv.reader(f, delimiter="|")
                    else:
                        reader = csv.reader(f) # Fallback to comma
                else:
                    # Standard DAT
                    reader = csv.reader(f, delimiter="\x14", quotechar="\xFE")
                
                ov_rows = list(reader)
            # -------------------------------------------

            progress_read.close()

            if not ov_rows: 
                QMessageBox.warning(self, "Error", "Overlay file is empty.")
                return

            # --- FIX: Handle Headerless LST Files ---
            if ext == "lst":
                # Create standard headers automatically
                ov_headers = ["LST_DOCID", "LST_TEXT_PATH"]
                
                # Fallback: Agar LST mein 2 se zyada columns hue toh unhe LST_COL_3 etc. naam de dega
                if len(ov_rows[0]) > 2:
                    for i in range(2, len(ov_rows[0])):
                        ov_headers.append(f"LST_COL_{i+1}")
                        
                # Use ALL rows as data (Pehli row ko skip nahi karega)
                ov_data = ov_rows 
            else:
                # Standard DAT/CSV: Headers clean karo aur pehli row (header) ko skip karo
                ov_headers = [h.replace("\xfe", "").replace("\x14", "").replace("\ufeff", "").strip() for h in ov_rows[0]]
                ov_data = ov_rows[1:]
            # ----------------------------------------
            
            # 1. Identifier Selection Dialog
            dlg = OverlayIdentifierDialog(self.headers, ov_headers)
            if dlg.exec() != QDialog.Accepted: return
            main_id, ov_id = dlg.values()
            
            # 2. Field Selection Dialog
            dlg_fields = OverlayFieldSelectDialog(ov_headers)
            if dlg_fields.exec() != QDialog.Accepted: return
            fields_to_map = dlg_fields.selected_fields()

            if not fields_to_map: return

            # Resolve Indexes
            main_idx = None
            for i, h in enumerate(self.headers):
                if utils.normalize_header(h) == utils.normalize_header(main_id):
                    main_idx = i; break
            
            if main_idx is None: 
                QMessageBox.warning(self, "Error", f"Main ID '{main_id}' not found in grid."); return

            ov_idx = None
            for i, h in enumerate(ov_headers):
                if utils.normalize_header(h) == utils.normalize_header(ov_id):
                    ov_idx = i; break

            if ov_idx is None: 
                QMessageBox.warning(self, "Error", f"Overlay ID '{ov_id}' not found in file."); return

            # Build Lookup Dictionary
            # Key = ID, Value = Row List
            lookup = {r[ov_idx]: r for r in ov_data if len(r) > ov_idx}

            # Add New Columns if they don't exist
            for f in fields_to_map:
                if f not in self.headers:
                    self.add_new_field(f)
            
            updated_count = 0
            
            # Pre-calculate column indexes for speed
            headers_map = {f: self.headers.index(f) for f in fields_to_map}
            ov_headers_map = {f: ov_headers.index(f) for f in fields_to_map}
                        
            total_rows = len(self.data)
            progress = QProgressDialog("Applying overlay...", "Cancel", 0, total_rows, self)
            progress.setWindowModality(Qt.WindowModal)
            
            self.table.setUpdatesEnabled(False)
            
            for i, row in enumerate(self.data):
                if i % 500 == 0:
                    progress.setValue(i)
                    if progress.wasCanceled(): break

                if main_idx >= len(row): continue
                key = row[main_idx]
                
                if key in lookup:
                    src_row = lookup[key]
                    for f in fields_to_map:
                        tgt_col = headers_map[f]
                        src_col = ov_headers_map[f]
                                                
                        while len(row) <= tgt_col:
                            row.append("")
                            
                        # Safety check: ensure column exists in source row
                        if src_col < len(src_row):
                            val = src_row[src_col]
                            row[tgt_col] = val
                            
                    updated_count += 1
            
            progress.setValue(total_rows)
            
            self.refresh_table()
            self.table.setUpdatesEnabled(True)
            self.update_status()
            QMessageBox.information(self, "Done", f"Overlay complete. Updated {updated_count} rows.")

            self.start_background_qc()
            
        except Exception as e:
            self.table.setUpdatesEnabled(True)
            QMessageBox.critical(self, "Overlay Error", str(e))
    
    def open_conditions(self):
        if not self.headers: return
        # 🚨 THE FIX: Dialog ko purani conditions pass ki ja rahi hain
        dlg = ConditionsDialog(self.headers, existing_conditions=self.conditions)
        if dlg.exec():            
            self.conditions = dlg.values()                        
            self.apply_filters()
                
# ==========================================
# DRAG & DROP AND ADVANCED FILE HANDLING
# ==========================================
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        # --- NAYA CODE: Window ko turant front mein laane ke liye ---
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        self.raise_()
        self.activateWindow()
        # -----------------------------------------------------------

        urls = event.mimeData().urls()
        if not urls: return
        
        file_path = urls[0].toLocalFile()
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext in [".dat", ".csv", ".txt"]:
            self.handle_dat_drop(file_path)
        elif ext in [".opt"]:
            self.handle_opt_drop(file_path)

    def handle_dat_drop(self, file_path):
        if not self.data:
            self.open_file(file_path)
            return
            
        msg = QMessageBox(self)
        msg.setWindowTitle("DAT/CSV Dropped")
        msg.setText(f"File: {os.path.basename(file_path)}\n\nWhat would you like to do with this file?")
        
        btn_load = msg.addButton("Load New (Replace)", QMessageBox.ActionRole)
        btn_append = msg.addButton("Append Rows", QMessageBox.ActionRole)
        btn_overlay = msg.addButton("Overlay Data", QMessageBox.ActionRole)
        btn_cancel = msg.addButton("Cancel", QMessageBox.RejectRole)
        
        msg.exec()
        
        clicked = msg.clickedButton()
        if clicked == btn_load:
            self.open_file(file_path)
        elif clicked == btn_append:
            self.append_file(file_path)
        elif clicked == btn_overlay:
            self.open_overlay(file_path)

    def handle_opt_drop(self, file_path):
        msg = QMessageBox(self)
        msg.setWindowTitle("OPT File Dropped")
        msg.setText(f"OPT File: {os.path.basename(file_path)}\n\nWhere do you want to load this?")
        
        btn_viewer = msg.addButton("Load as Images (For current DAT)", QMessageBox.ActionRole)
        btn_standalone = msg.addButton("Open in Standalone OPT Editor", QMessageBox.ActionRole)
        msg.addButton("Cancel", QMessageBox.RejectRole)
        
        msg.exec()
        
        clicked = msg.clickedButton()
        if clicked == btn_viewer:
            self.load_opt(file_path)
        elif clicked == btn_standalone:
            self.open_standalone_opt(file_path)

    def append_file(self, path):
        enc = utils.detect_encoding(path)
        is_csv = path.lower().endswith(".csv")
        delimiter = "," if is_csv else "\x14"
        quotechar = '"' if is_csv else "\xFE"
        
        try:
            with open(path, "r", encoding=enc, errors="ignore") as f:
                reader = csv.reader(f, delimiter=delimiter, quotechar=quotechar)
                rows = list(reader)
                
            if not rows: return
            
            if is_csv:
                new_headers = [h.strip() for h in rows[0]]
            else:
                new_headers = [h.replace("\xfe", "").replace("\x14", "").replace("\ufeff", "").strip() for h in rows[0]]
                
            if new_headers != self.headers:
                QMessageBox.warning(self, "Header Mismatch", "The headers in this file do not match the currently loaded file.\nAppend cancelled.")
                return
                
            new_data = rows[1:]
            start_idx = len(self.data)
            
            self.data.extend(new_data)
            self.visible_idx.extend(range(start_idx, start_idx + len(new_data)))
            
            self.refresh_table()
            self.update_status()
            
            QMessageBox.information(self, "Append Success", f"Successfully appended {len(new_data)} rows!")
            self.start_background_qc()
            
        except Exception as e:
            QMessageBox.critical(self, "Append Error", str(e))

    def open_standalone_opt(self, path):
        self.standalone_opt_path = path
        enc = utils.detect_encoding(path)
        try:
            with open(path, "r", encoding=enc, errors="ignore") as f:
                reader = csv.reader(f)
                self.opt_data = list(reader)
                
            opt_headers = ["Image Key", "Volume", "Path", "Doc Break", "Box", "Folder", "Page Count"]
            
            for r in self.opt_data:
                while len(r) < 7: r.append("")
                
            model = LazyDatTableModel(opt_headers, self.opt_data, list(range(len(self.opt_data))))
            self.opt_table.setModel(model)
            self.opt_table.resizeColumnsToContents()
            
            self.main_tabs.setCurrentIndex(1)
            
            total_images = len(self.opt_data)
            total_docs = sum(1 for r in self.opt_data if len(r) > 3 and str(r[3]).strip().upper() == 'Y')
            
            msg = f"Standalone OPT Imported Successfully!\n\n📄 Total Documents: {total_docs}\n🖼️ Total Images: {total_images}"
            QMessageBox.information(self, "Import Status", msg)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load standalone OPT:\n{e}")
            
    def save_standalone_opt(self):
        if not hasattr(self, 'opt_data') or not self.opt_data:
            QMessageBox.warning(self, "Empty", "No OPT data to save.")
            return
            
        path, _ = QFileDialog.getSaveFileName(self, "Save OPT", getattr(self, "standalone_opt_path", ""), "OPT Files (*.opt)")
        if not path: return
        
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                for row in self.opt_data:
                    writer.writerow(row)
                    
            QMessageBox.information(self, "Saved", f"OPT File saved successfully:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    # ==========================================
    # LOGIC: RENUMBER OPT PAGES SEQUENTIALLY & OPTIONAL DISK RENAME
    # ==========================================
    def renumber_opt_sequential(self):
        if not hasattr(self, 'opt_data') or not self.opt_data:
            QMessageBox.warning(self, "Empty", "No OPT data loaded in Standalone Editor.")
            return

        # 1. Ask User Choice: Rename Disk Files or Only OPT
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Renumber Suffixes")
        msg_box.setIcon(QMessageBox.Question)
        msg_box.setText(
            "<b>Sequential Renumbering Setup</b><br><br>"
            "This will sequentially renumber all child pages based on the Bates number of their Parent ('Y') document.<br><br>"
            "Do you also want to <b>RENAME the physical image files on DISK</b>?"
        )
        btn_rename_both = msg_box.addButton("Yes (Rename Disk & OPT)", QMessageBox.YesRole)
        btn_opt_only = msg_box.addButton("No (Only Renumber OPT)", QMessageBox.NoRole)
        btn_cancel = msg_box.addButton("Cancel", QMessageBox.RejectRole)
        
        msg_box.exec()
        clicked = msg_box.clickedButton()

        if clicked == btn_cancel:
            return

        do_disk_rename = (clicked == btn_rename_both)

        import re
        import os
        
        current_pfx = ""
        current_num = 0
        current_pad = 0
        
        updated_rows = 0
        renamed_files = 0
        failed_errors = []

        opt_root = os.path.abspath(os.path.dirname(self.standalone_opt_path)) if hasattr(self, 'standalone_opt_path') and self.standalone_opt_path else os.getcwd()
        base_root = self.case_root if hasattr(self, 'case_root') and self.case_root else opt_root

        total_rows = len(self.opt_data)
        
        progress_title = "Renumbering OPT and Renaming Files on Disk..." if do_disk_rename else "Renumbering OPT Data..."
        progress = QProgressDialog(progress_title, "Cancel", 0, total_rows, self)
        progress.setWindowModality(Qt.WindowModal)

        if hasattr(self, 'opt_table'):
            self.opt_table.setUpdatesEnabled(False) 

        for idx, row in enumerate(self.opt_data):
            # Batch update UI every 5000 records for maximum throughput
            if idx % 5000 == 0:
                progress.setValue(idx)
                QApplication.processEvents()
            if progress.wasCanceled(): 
                break
                
            if len(row) == 0: continue
            while len(row) < 7: row.append("")
            
            bates = row[0].strip().replace('\ufeff', '')
            old_path = row[2].strip()
            doc_break = row[3].strip().upper()

            # Parent Document ('Y') or First Row
            if doc_break == 'Y' or idx == 0:                
                match = re.match(r"^(.*?)(\d+)$", bates)
                if match:
                    current_pfx = match.group(1)
                    current_num = int(match.group(2))
                    current_pad = len(match.group(2))
                else:
                    current_pfx = bates
                    current_num = 0
                    current_pad = 0
            else:
                # Child Page (No 'Y')
                if current_pad > 0:
                    current_num += 1                    
                    new_bates = f"{current_pfx}{str(current_num).zfill(current_pad)}"
                    
                    if bates != new_bates:
                        old_bates = row[0]
                        row[0] = new_bates
                        updated_rows += 1
                        
                        # --- DISK RENAMING LOGIC ---
                        if old_path:
                            ext = os.path.splitext(old_path)[1]
                            dir_path = os.path.dirname(old_path)
                            
                            new_path = os.path.join(dir_path, f"{new_bates}{ext}")
                            if "\\" in old_path: 
                                new_path = new_path.replace("/", "\\")
                            else:
                                new_path = new_path.replace("\\", "/")

                            if do_disk_rename:
                                if os.path.isabs(old_path):
                                    old_abs = old_path
                                    new_abs = new_path
                                else:
                                    clean_old = old_path.replace('.\\', '').replace('./', '').lstrip('\\/')
                                    old_abs = os.path.join(base_root, clean_old) if base_root else old_path
                                    
                                    clean_new = new_path.replace('.\\', '').replace('./', '').lstrip('\\/')
                                    new_abs = os.path.join(base_root, clean_new) if base_root else new_path

                                try:
                                    if not os.path.exists(old_abs):
                                        failed_errors.append(f"Row {idx+1} | {old_bates} -> {new_bates} | File missing on disk: {old_abs}")
                                    elif os.path.exists(new_abs):
                                        failed_errors.append(f"Row {idx+1} | {old_bates} -> {new_bates} | Destination file already exists: {new_abs}")
                                    else:
                                        os.rename(old_abs, new_abs)
                                        renamed_files += 1
                                except Exception as e:
                                    failed_errors.append(f"Row {idx+1} | {old_bates} -> {new_bates} | OS Error: {str(e)}")
                                
                            # Update OPT row path
                            row[2] = new_path

        progress.setValue(total_rows)
        if hasattr(self, 'opt_table'):
            self.opt_table.setUpdatesEnabled(True)

        # Refresh Grid View
        if hasattr(self, 'opt_table') and self.opt_table.model():
            self.opt_table.model().layoutChanged.emit()
            
        summary_msg = f"<b>Operation Complete!</b><br><br>"
        summary_msg += f"• Mode: {'Rename Disk & OPT' if do_disk_rename else 'OPT Renumber Only'}<br>"
        summary_msg += f"• OPT Records Updated: {updated_rows:,}<br>"
        
        if do_disk_rename:
            summary_msg += f"• Files Renamed on Disk: {renamed_files:,}<br>"
            summary_msg += f"• Failed / Missing Files: {len(failed_errors):,}<br>"
            
        QMessageBox.information(self, "Result", summary_msg)

        # 2. Generate Error Report if any failures occurred
        if failed_errors:
            if QMessageBox.question(
                self, 
                "Save Error Report?", 
                f"There were {len(failed_errors)} file renaming errors.\nWould you like to save the Error Report?", 
                QMessageBox.Yes | QMessageBox.No
            ) == QMessageBox.Yes:
                default_path = os.path.join(base_root, "Renumber_Rename_Errors.txt")
                save_err_path, _ = QFileDialog.getSaveFileName(self, "Save Renaming Error Report", default_path, "Text Files (*.txt)")
                if save_err_path:
                    try:
                        with open(save_err_path, "w", encoding="utf-8") as f_err:
                            f_err.write("SEQUENTIAL RENUMBERING / RENAMING ERROR REPORT\n")
                            f_err.write("=" * 60 + "\n\n")
                            f_err.write(f"Total Errors: {len(failed_errors)}\n\n")
                            for err_line in failed_errors:
                                f_err.write(f"{err_line}\n")
                        utils.open_native_file(save_err_path)
                    except Exception as e:
                        QMessageBox.critical(self, "Error", f"Could not save report: {e}")

    # ==========================================
    # LOGIC: CUSTOM STRUCTURED EXPORT (FOLDERS & RENAME)
    # ==========================================
    def run_custom_structured_export(self):
        if not hasattr(self, 'headers') or not self.headers or not self.data:
            QMessageBox.warning(self, "Error", "Please load a DAT file first.")
            return
            
        docid_field = self.field_map.get("id")
        if not docid_field:
            QMessageBox.warning(self, "Error", "Please map the Document ID field first.")
            return

        from dialogs import CustomExportConfigDialog
        import shutil
        import re

        dlg = CustomExportConfigDialog(self.headers, self)
        if dlg.exec() != QDialog.Accepted:
            return
            
        cfg = dlg.get_config()
        out_root = cfg["out_dir"]
        
        if not out_root or not os.path.exists(out_root):
            QMessageBox.warning(self, "Error", "Invalid output directory.")
            return
            
        # New Configs
        vol_name = cfg["vol_name"]
        
        # Proper Encoding Setup
        enc = cfg["encoding"]
        if enc == "utf-8-sig (BOM)": enc = "utf-8-sig"
        elif enc == "ansi": enc = "mbcs"
        
        cust_field = cfg["custodian_field"]
        suff_field = cfg["suffix_field"]
        sep = cfg["sep"]
        
        do_img = cfg["do_images"]
        do_nat = cfg["do_natives"]
        do_txt = cfg["do_text"]
        
        # Volume Setup
        base_export_dir = os.path.join(out_root, vol_name) if vol_name else out_root
        os.makedirs(base_export_dir, exist_ok=True)
        rel_prefix = f".\\{vol_name}" if vol_name else "."
        
        cust_idx = self.headers.index(cust_field) if cust_field in self.headers else -1
        suff_idx = self.headers.index(suff_field) if suff_field in self.headers else -1
        docid_idx = self.headers.index(docid_field)
        
        nat_idx = self.headers.index(self.field_map["native"]) if self.field_map.get("native") in self.headers else -1
        txt_idx = self.headers.index(self.field_map["text"]) if self.field_map.get("text") in self.headers else -1
        
        def clean_folder_path(name):            
            return re.sub(r'[*?:"<>|]', "", str(name)).strip() if name else "Unknown_Folder"

        def clean_file_name(name):            
            return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip() if name else ""

        progress = QProgressDialog("Exporting custom production...", "Cancel", 0, len(self.visible_idx), self)
        progress.setWindowModality(Qt.WindowModal)
        
        new_dat_data = []
        new_opt_data = []
        
        success_files = 0
        error_files = 0

        for progress_idx, r_idx in enumerate(self.visible_idx):
            if progress_idx % 10 == 0:
                progress.setValue(progress_idx)
                QApplication.processEvents()
            if progress.wasCanceled(): break

            row = list(self.data[r_idx]) 
            docid = row[docid_idx].strip()
                        
            raw_cust = row[cust_idx].strip() if cust_idx != -1 else "No_Folder"
            cust_name = clean_folder_path(raw_cust)
            if cust_field == "<None (Root)>": cust_name = ""
                        
            suffix_val = ""
            if suff_idx != -1 and row[suff_idx].strip():
                clean_suf = clean_file_name(row[suff_idx])
                if clean_suf:
                    suffix_val = f"{sep}{clean_suf}"

            # 1. Process NATIVES
            if nat_idx != -1 and row[nat_idx]:
                old_nat_path = utils.resolve_relative_path(self.case_root, row[nat_idx])
                if old_nat_path and os.path.exists(old_nat_path):
                    ext = os.path.splitext(old_nat_path)[1]
                    orig_name = os.path.basename(old_nat_path)
                    
                    # If box checked then rename, else original name
                    new_filename = f"{docid}{suffix_val}{ext}" if do_nat else orig_name
                    
                    dest_dir = os.path.join(base_export_dir, "NATIVES", cust_name) if cust_name else os.path.join(base_export_dir, "NATIVES")
                    os.makedirs(dest_dir, exist_ok=True)
                    
                    try:
                        shutil.copy2(old_nat_path, os.path.join(dest_dir, new_filename))
                        rel_folder = f"{rel_prefix}\\NATIVES\\{cust_name}" if cust_name else f"{rel_prefix}\\NATIVES"
                        row[nat_idx] = f"{rel_folder}\\{new_filename}"
                        success_files += 1
                    except: error_files += 1

            # 2. Process TEXT
            if txt_idx != -1 and row[txt_idx]:
                old_txt_path = utils.resolve_relative_path(self.case_root, row[txt_idx])
                if old_txt_path and os.path.exists(old_txt_path):
                    ext = os.path.splitext(old_txt_path)[1]
                    orig_name = os.path.basename(old_txt_path)
                    
                    new_filename = f"{docid}{suffix_val}{ext}" if do_txt else orig_name
                    
                    dest_dir = os.path.join(base_export_dir, "TEXT", cust_name) if cust_name else os.path.join(base_export_dir, "TEXT")
                    os.makedirs(dest_dir, exist_ok=True)
                    
                    try:
                        shutil.copy2(old_txt_path, os.path.join(dest_dir, new_filename))
                        rel_folder = f"{rel_prefix}\\TEXT\\{cust_name}" if cust_name else f"{rel_prefix}\\TEXT"
                        row[txt_idx] = f"{rel_folder}\\{new_filename}"
                        success_files += 1
                    except: error_files += 1

            # 3. Process IMAGES (from OPT)
            if hasattr(self, 'opt_index') and docid in self.opt_index:
                images = self.opt_index[docid]
                is_first_page = True
                
                for img in images:
                    img_path = img["path"] if isinstance(img, dict) else img
                    page_bates = img["bates"] if isinstance(img, dict) else docid
                    
                    if img_path and os.path.exists(img_path):
                        ext = os.path.splitext(img_path)[1]
                        orig_name = os.path.basename(img_path)
                        
                        new_img_name = f"{page_bates}{suffix_val}{ext}" if do_img else orig_name                        
                        opt_bates = page_bates

                        dest_dir = os.path.join(base_export_dir, "IMAGES", cust_name) if cust_name else os.path.join(base_export_dir, "IMAGES")
                        os.makedirs(dest_dir, exist_ok=True)
                        
                        try:
                            shutil.copy2(img_path, os.path.join(dest_dir, new_img_name))
                            
                            rel_folder = f"{rel_prefix}\\IMAGES\\{cust_name}" if cust_name else f"{rel_prefix}\\IMAGES"
                            rel_img_path = f"{rel_folder}\\{new_img_name}"
                            doc_break = "Y" if is_first_page else ""
                            
                            # Add to OPT data list
                            v_name = vol_name if vol_name else "VOL001"
                            new_opt_data.append([opt_bates, v_name, rel_img_path, doc_break, "", "", ""])
                            
                            success_files += 1
                            is_first_page = False
                        except: error_files += 1
            
            new_dat_data.append(row)

        progress.setValue(len(self.visible_idx))

        # 4. Export Updated DAT
        dat_filename = f"{vol_name}.dat" if vol_name else "Exported_Data.dat"
        dat_save_path = os.path.join(base_export_dir, dat_filename)
        try:
            with open(dat_save_path, "w", encoding=enc, newline="") as f:
                # FIX: Added lineterminator="\r\n"
                writer = csv.writer(f, delimiter="\x14", quotechar="\xFE", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
                writer.writerow(self.headers)
                writer.writerows(new_dat_data)
        except Exception as e:
            QMessageBox.critical(self, "DAT Export Error", str(e))

        # 5. Export Updated OPT (NO QUOTES)
        if new_opt_data:
            opt_filename = f"{vol_name}.opt" if vol_name else "Exported_Images.opt"
            opt_save_path = os.path.join(base_export_dir, opt_filename)
            try:
                with open(opt_save_path, "w", encoding=enc, newline="") as f:
                    for opt_row in new_opt_data:
                        line = ",".join(str(item) for item in opt_row)
                        # FIX: Replaced \n with \r\n for OPT
                        f.write(line + "\r\n")
                        
            except Exception as e:
                QMessageBox.critical(self, "OPT Export Error", str(e))

        QMessageBox.information(self, "Custom Export Complete", 
            f"✅ Files Copied Successfully: {success_files}\n"
            f"❌ Errors (Missing/Locked): {error_files}\n\n"
            f"New Volume Data saved in:\n{base_export_dir}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Built-in Fusion style (clean base)
    app.setStyle("Fusion")
    
    # Custom "All-Blue Corporate" QSS Styling
    all_blue_style = """
        QMainWindow {
            background-color: #EBF3FA; /* Soft ice blue background */
        }
        QPushButton {
            background-color: #005A9E; /* Solid Corporate Blue */
            color: white;
            font-weight: bold;
            border-radius: 4px;
            padding: 6px 12px;
            border: none;
        }
        QPushButton:hover {
            background-color: #00457A; /* Darker blue on hover */
        }
        QPushButton:disabled {
            background-color: #99BADD; /* Faded blue for disabled buttons */
            color: #EBF3FA;
        }
        QTableView {
            background-color: #FFFFFF;
            alternate-background-color: #F0F8FF; /* Alice Blue alternating rows */
            gridline-color: #A9C4EB; /* Light blue grid lines instead of grey */
            selection-background-color: #8CC3F5; /* Bright blue selection */
            selection-color: black;
            border: 1px solid #A9C4EB;
        }
        QHeaderView::section {
            background-color: #D3E3F5; /* Soft blue headers */
            color: #003366; /* Dark blue text */
            font-weight: bold;
            padding: 4px;
            border: 1px solid #A9C4EB;
        }
        QTabWidget::pane {
            border: 1px solid #A9C4EB;
            background: white;
        }
        QTabBar::tab {
            background: #D3E3F5; /* Soft blue unselected tabs */
            color: #003366;
            padding: 8px 16px;
            margin-right: 2px;
            border: 1px solid #A9C4EB;
            border-bottom: none;
        }
        QTabBar::tab:selected {
            background: #FFFFFF; /* White for active tab */
            color: #005A9E;
            border-top: 3px solid #005A9E; /* Thick blue highlight */
            font-weight: bold;
        }
    """
    app.setStyleSheet(all_blue_style)
    
    window = DatEditorFast()
    window.show()
    sys.exit(app.exec())
        
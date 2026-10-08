import csv
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QDialogButtonBox,
    QListWidget, QListWidgetItem, QLineEdit, QCheckBox, QPushButton, QWidget,
    QGroupBox, QTextEdit, QGridLayout, QRadioButton, QButtonGroup, QAbstractItemView,
    QFontDialog, QColorDialog, QDoubleSpinBox, QFileDialog,QMessageBox, QSpinBox, QStackedWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QFont
from PySide6.QtGui import QColor

# =====================
# DATA STRUCTURES
# =====================
class OperationContext:
    """Holds data for bulk operations like Replace/Append."""
    def __init__(self, target_column, action, source_type=None, source_value=None, 
                 separator="", scope="filtered", find_text=None, replace_text=None,
                 datetime_src_column=None, datetime_src_format=None, 
                 datetime_tgt_format=None, datetime_tgt_column=None):
        self.target_column = target_column
        self.action = action
        self.source_type = source_type
        self.source_value = source_value
        self.separator = separator
        self.scope = scope
        self.find_text = find_text
        self.replace_text = replace_text
        # DateTime specific
        self.datetime_src_column = datetime_src_column
        self.datetime_src_format = datetime_src_format
        self.datetime_tgt_format = datetime_tgt_format
        self.datetime_tgt_column = datetime_tgt_column

# =====================
# FILTER & SEARCH DIALOGS
# =====================
class FilterDialog(QDialog):
    def __init__(self, field_name, values):
        super().__init__()
        self.setWindowTitle(f"Filter: {field_name}")
        self.resize(350, 400)

        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search values")
        self.search.textChanged.connect(self.filter_list)
        layout.addWidget(self.search)

        self.select_all = QCheckBox("Select All")
        self.select_all.setChecked(True)
        self.select_all.clicked.connect(self.toggle_select_all)
        layout.addWidget(self.select_all)

        self.list = QListWidget()
        for v in values:
            item = QListWidgetItem(v if v else "(Blank)")
            item.setCheckState(Qt.Checked)
            self.list.addItem(item)
        layout.addWidget(self.list)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def filter_list(self, text):
        text = text.lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(text not in item.text().lower())

    def toggle_select_all(self, checked):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def selected_values(self):
        return ["" if self.list.item(i).text() == "(Blank)" else self.list.item(i).text() 
                for i in range(self.list.count()) 
                if not self.list.item(i).isHidden() and self.list.item(i).checkState() == Qt.Checked]

class ConditionsDialog(QDialog):
    def __init__(self, headers, existing_conditions=None):
        super().__init__()
        self.setWindowTitle("Advanced Conditions")
        self.resize(600, 400)
        self.headers = headers
        self.rows = []
        
        layout = QVBoxLayout(self)
        self.rows_container = QVBoxLayout()
        layout.addLayout(self.rows_container)
        
        add_btn = QPushButton("Add Condition")
        add_btn.clicked.connect(self.add_row)
        layout.addWidget(add_btn)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        if existing_conditions:
            for cond in existing_conditions:
                self.add_row(cond)
        else:
            self.add_row()

    def add_row(self, prefill_data=None):
        if isinstance(prefill_data, bool): 
            prefill_data = None

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        
        connector = QComboBox()
        connector.addItems(["AND", "OR"])
        if not self.rows: 
            connector.hide()
        
        field = QComboBox()
        for idx, name in enumerate(self.headers): 
            field.addItem(name, idx)
        
        op = QComboBox()
        op.addItems(["is empty", "is not empty", "equals", "contains", "starts with", "ends with"])
        
        value = QLineEdit()
        remove_btn = QPushButton("❌")
        remove_btn.setFixedWidth(30)
        
        layout.addWidget(connector)
        layout.addWidget(field)
        layout.addWidget(op)
        layout.addWidget(value)
        layout.addWidget(remove_btn)
        
        self.rows_container.addWidget(container)
        row_data = {"widget": container, "conn": connector, "field": field, "op": op, "val": value}
        self.rows.append(row_data)
        
        if prefill_data:
            if prefill_data.get("join"):
                connector.setCurrentText(prefill_data.get("join"))
            
            if "col" in prefill_data:
                idx = field.findData(prefill_data["col"])
                if idx >= 0:
                    field.setCurrentIndex(idx)
            
            if "op" in prefill_data:
                op.setCurrentText(prefill_data["op"])
            
            if "value" in prefill_data:
                value.setText(str(prefill_data["value"]))

        remove_btn.clicked.connect(lambda: self.remove_row(row_data))

    def remove_row(self, row_data):
        self.rows_container.removeWidget(row_data["widget"])
        row_data["widget"].deleteLater()
        self.rows.remove(row_data)
        if self.rows:
            self.rows[0]["conn"].hide()

    def values(self):
        results = []
        for i, r in enumerate(self.rows):
            results.append({
                "col": r["field"].currentData(),
                "op": r["op"].currentText(),
                "value": r["val"].text().strip(),
                "join": r["conn"].currentText() if i > 0 else None
            })
        return results

# =====================
# OPERATION DIALOGS
# =====================
class FindReplaceDialog(QDialog):
    def __init__(self, headers):
        super().__init__()
        self.setWindowTitle("Find / Replace")
        self.resize(520, 360)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Field to Update:"))
        self.target_field = QComboBox()
        for i, h in enumerate(headers): self.target_field.addItem(h, i)
        layout.addWidget(self.target_field)

        layout.addWidget(QLabel("Action:"))
        self.action = QComboBox()
        self.action.addItems(["Replace Entire Field", "Append to End", "Insert at Beginning", "Search and Replace"])
        self.action.currentTextChanged.connect(self._toggle_ui)
        layout.addWidget(self.action)
        
        self.std_widget = QWidget()
        std_layout = QVBoxLayout(self.std_widget)
        std_layout.setContentsMargins(0,0,0,0)
        self.source_type = QComboBox()
        self.source_type.addItems(["Text", "Field"])
        self.source_type.currentTextChanged.connect(self._toggle_source)
        std_layout.addWidget(QLabel("Update With:"))
        std_layout.addWidget(self.source_type)
        self.source_val = QLineEdit()
        self.source_field = QComboBox()
        for i, h in enumerate(headers): self.source_field.addItem(h, i)
        self.source_field.hide()
        std_layout.addWidget(self.source_val)
        std_layout.addWidget(self.source_field)
        std_layout.addWidget(QLabel("Separator:"))
        self.separator = QLineEdit()
        std_layout.addWidget(self.separator)
        layout.addWidget(self.std_widget)
        
        self.search_widget = QWidget()
        sr_layout = QVBoxLayout(self.search_widget)
        sr_layout.setContentsMargins(0,0,0,0)
        self.find_text = QLineEdit()
        self.replace_text = QLineEdit()
        sr_layout.addWidget(QLabel("Find:"))
        sr_layout.addWidget(self.find_text)
        sr_layout.addWidget(QLabel("Replace:"))
        sr_layout.addWidget(self.replace_text)
        layout.addWidget(self.search_widget)
        self.search_widget.hide()

        self.preview_label = QLabel("Affected rows: 0")
        layout.addWidget(self.preview_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _toggle_ui(self, text):
        is_sr = (text == "Search and Replace")
        self.search_widget.setVisible(is_sr)
        self.std_widget.setVisible(not is_sr)

    def _toggle_source(self, text):
        self.source_val.setVisible(text == "Text")
        self.source_field.setVisible(text == "Field")

    def get_context(self):
        action_map = {
            "Replace Entire Field": "replace", "Append to End": "append",
            "Insert at Beginning": "insert", "Search and Replace": "search_replace"
        }
        act = action_map[self.action.currentText()]
        
        if act == "search_replace":
            return OperationContext(self.target_field.currentData(), act, find_text=self.find_text.text(), replace_text=self.replace_text.text())
        
        src_val = self.source_val.text() if self.source_type.currentText() == "Text" else self.source_field.currentData()
        return OperationContext(self.target_field.currentData(), act, source_type=self.source_type.currentText().lower(), source_value=src_val, separator=self.separator.text())

class ExportDialog(QDialog):
    def __init__(self, headers):
        super().__init__()
        self.setWindowTitle("Export DAT / CSV")
        self.resize(900, 550)
        self.headers = headers
        self.field_map = {}
        
        main_layout = QVBoxLayout(self)
                
        fields_layout = QHBoxLayout()
                
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("Available Fields"))
        self.available = QListWidget()
        self.available.setSelectionMode(QListWidget.ExtendedSelection)
        self.available.addItems(headers)
        left_layout.addWidget(self.available)
        fields_layout.addLayout(left_layout)
                
        btn_layout = QVBoxLayout()
        btn_layout.addStretch()
                
        self.btn_load_map = QPushButton("📂 Load Map")
        self.btn_load_map.setToolTip("Import Mapping (CSV/Excel)\nCol A: Current Field\nCol B: Export Header")
        self.btn_load_map.clicked.connect(self.load_mapping)
        self.btn_load_map.setStyleSheet("background-color: #e1f5fe; font-weight: bold;")
        btn_layout.addWidget(self.btn_load_map)
        
        self.btn_add = QPushButton(">"); self.btn_add.clicked.connect(self.add_sel)
        self.btn_rem = QPushButton("<"); self.btn_rem.clicked.connect(self.rem_sel)
        self.btn_add_all = QPushButton(">>"); self.btn_add_all.clicked.connect(self.add_all)
        self.btn_rem_all = QPushButton("<<"); self.btn_rem_all.clicked.connect(self.rem_all)
        self.btn_up = QPushButton("↑"); self.btn_up.clicked.connect(self.move_up)
        self.btn_down = QPushButton("↓"); self.btn_down.clicked.connect(self.move_down)        
                                                
        for b in [self.btn_add, self.btn_rem, self.btn_add_all, self.btn_rem_all, self.btn_up, self.btn_down]:
            b.setFixedWidth(50)
            btn_layout.addWidget(b)
            
        btn_layout.addStretch()
        fields_layout.addLayout(btn_layout)
                
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("Selected Fields (Export Order)"))
        self.selected = QListWidget()
        self.selected.setSelectionMode(QListWidget.ExtendedSelection)
        right_layout.addWidget(self.selected)
        self.available.itemDoubleClicked.connect(self.add_sel)
        self.selected.itemDoubleClicked.connect(self.rem_sel)
                
        self.sort_group = QGroupBox("Sort Export By")
        sort_inner = QVBoxLayout(self.sort_group)
        self.sort_list = QListWidget()
        sort_inner.addWidget(self.sort_list)
        
        sort_btns = QHBoxLayout()
        self.btn_sort_add = QPushButton("+ Add")
        self.btn_sort_rem = QPushButton("- Remove")
        self.btn_sort_up = QPushButton("↑")
        self.btn_sort_down = QPushButton("↓")
        
        self.btn_sort_add.clicked.connect(self.add_sort)
        self.btn_sort_rem.clicked.connect(self.rem_sort)
        self.btn_sort_up.clicked.connect(self.sort_up)
        self.btn_sort_down.clicked.connect(self.sort_down)
        
        for b in [self.btn_sort_add, self.btn_sort_rem, self.btn_sort_up, self.btn_sort_down]:
            sort_btns.addWidget(b)
            
        sort_inner.addLayout(sort_btns)
        right_layout.addWidget(self.sort_group)
        
        fields_layout.addLayout(right_layout)
        main_layout.addLayout(fields_layout)
        
        opts_layout = QHBoxLayout()
        self.encoding = QComboBox()
        self.encoding.addItems(["UTF-8 with BOM", "UTF-8", "CP1252", "UTF-16 LE"])
        self.file_type = QComboBox()
        self.file_type.addItems(["DAT", "CSV"])
        opts_layout.addWidget(QLabel("Encoding:")); opts_layout.addWidget(self.encoding)
        opts_layout.addWidget(QLabel("Type:")); opts_layout.addWidget(self.file_type)
        main_layout.addLayout(opts_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)
    
    def load_mapping(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Mapping File", "", "CSV Files (*.csv);;Excel Files (*.xlsx)")
        if not path: return

        try:
            mapping = {}
                        
            if path.lower().endswith(".csv"):
                with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if len(row) >= 2:
                            src = row[0].strip()
                            tgt = row[1].strip()
                            if src: mapping[src] = tgt
            
            elif path.lower().endswith(".xlsx"):
                try:
                    import openpyxl
                    wb = openpyxl.load_workbook(path, data_only=True)
                    ws = wb.active
                    for row in ws.iter_rows(values_only=True):
                        if row and len(row) >= 2:
                            src = str(row[0]).strip() if row[0] else ""
                            tgt = str(row[1]).strip() if row[1] else ""
                            if src: mapping[src] = tgt
                except ImportError:
                    QMessageBox.warning(self, "Error", "openpyxl library required for Excel import.")
                    return

            if not mapping:
                QMessageBox.warning(self, "Error", "No valid mapping data found (Col A -> Col B).")
                return
            
            self.selected.clear()
            self.available.clear()
            self.available.addItems(self.headers)
            self.field_map = mapping
            
            found_count = 0
            missing_fields = []
            
            for src_field in mapping.keys():                
                match_item = None
                for i in range(self.available.count()):
                    item = self.available.item(i)
                    if item.text().lower() == src_field.lower():
                        match_item = item
                        break
                
                if match_item:                    
                    self.available.takeItem(self.available.row(match_item))
                    self.selected.addItem(match_item.text())
                                        
                    if match_item.text() != src_field:
                        self.field_map[match_item.text()] = self.field_map.pop(src_field)
                        
                    found_count += 1
                else:
                    missing_fields.append(src_field)

            msg = f"✅ Mapped {found_count} fields successfully."
            if missing_fields:
                msg += f"\n\n⚠️ {len(missing_fields)} fields not found in DAT:\n" + ", ".join(missing_fields[:5])
            
            QMessageBox.information(self, "Mapping Result", msg)

        except Exception as e:
            QMessageBox.critical(self, "Mapping Error", str(e))
    
    def add_sel(self):
        for item in self.available.selectedItems():
            self.selected.addItem(item.text())
            self.available.takeItem(self.available.row(item))
    
    def rem_sel(self):
        for item in self.selected.selectedItems():
            self.available.addItem(item.text())
            self.selected.takeItem(self.selected.row(item))
            
    def add_all(self):
        while self.available.count() > 0:
            item = self.available.takeItem(0)
            self.selected.addItem(item.text())
            
    def rem_all(self):
        while self.selected.count() > 0:
            item = self.selected.takeItem(0)
            self.available.addItem(item.text())
            
    def move_up(self):
        for item in self.selected.selectedItems():
            row = self.selected.row(item)
            if row > 0:
                self.selected.takeItem(row)
                self.selected.insertItem(row - 1, item)
                item.setSelected(True)
                
    def move_down(self):
        for item in reversed(self.selected.selectedItems()):
            row = self.selected.row(item)
            if row < self.selected.count() - 1:
                self.selected.takeItem(row)
                self.selected.insertItem(row + 1, item)
                item.setSelected(True)
    
    def add_sort(self):
        for item in self.selected.selectedItems():
            txt = f"{item.text()} | ASC"
            exists = False
            for i in range(self.sort_list.count()):
                if self.sort_list.item(i).text().startswith(item.text() + " |"):
                    exists = True; break
            if not exists: self.sort_list.addItem(txt)

    def rem_sort(self):
        for item in self.sort_list.selectedItems():
            self.sort_list.takeItem(self.sort_list.row(item))
            
    def sort_up(self):
        for item in self.sort_list.selectedItems():
            row = self.sort_list.row(item)
            if row > 0:
                self.sort_list.takeItem(row)
                self.sort_list.insertItem(row - 1, item)
                item.setSelected(True)
                
    def sort_down(self):
        for item in reversed(self.sort_list.selectedItems()):
            row = self.sort_list.row(item)
            if row < self.sort_list.count() - 1:
                self.sort_list.takeItem(row)
                self.sort_list.insertItem(row + 1, item)
                item.setSelected(True)

    def export_options(self):
        sort_rules = []
        for i in range(self.sort_list.count()):
            txt = self.sort_list.item(i).text()
            field, direction = txt.split(" | ")
            sort_rules.append((field, direction))
            
        return {
            "fields": [self.selected.item(i).text() for i in range(self.selected.count())],
            "encoding": self.encoding.currentText(),
            "type": self.file_type.currentText(),
            "sort": sort_rules,
            "renames": self.field_map
        }

# =====================
# MISC DIALOGS
# =====================
class AddFieldDialog(QDialog):
    def __init__(self, headers):
        super().__init__()
        self.setWindowTitle("Add New Field")
        layout = QVBoxLayout(self)
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.addItems(headers)
        layout.addWidget(QLabel("Field Name:"))
        layout.addWidget(self.combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    def value(self): return self.combo.currentText().strip()

class NativeRenameDialog(QDialog):
    def __init__(self, headers):
        super().__init__()
        self.setWindowTitle("Native Rename")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select Designation Field:"))
        self.combo = QComboBox()
        self.combo.addItems(headers)
        layout.addWidget(self.combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    def selected_field(self): return self.combo.currentText()

class OverlayIdentifierDialog(QDialog):
    def __init__(self, main_fields, overlay_fields):
        super().__init__()
        self.setWindowTitle("Overlay Mapping")
        layout = QVBoxLayout(self)
        self.main_id = QComboBox(); self.main_id.addItems(main_fields)
        self.overlay_id = QComboBox(); self.overlay_id.addItems(overlay_fields)
        layout.addWidget(QLabel("Main ID Field:")); layout.addWidget(self.main_id)
        layout.addWidget(QLabel("Overlay ID Field:")); layout.addWidget(self.overlay_id)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    def values(self): return (self.main_id.currentText(), self.overlay_id.currentText())

class OverlayFieldSelectDialog(QDialog):
    def __init__(self, fields):
        super().__init__()
        self.setWindowTitle("Select Fields to Overlay")
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        for f in fields:
            item = QListWidgetItem(f)
            item.setCheckState(Qt.Checked)
            self.list.addItem(item)
        layout.addWidget(self.list)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    def selected_fields(self):
        return [self.list.item(i).text() for i in range(self.list.count()) if self.list.item(i).checkState() == Qt.Checked]
    
class ImportMappingDialog(QDialog):
    def __init__(self, headers):
        super().__init__()
        self.setWindowTitle("Map Load File Fields")
        self.resize(450, 300)
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Map Essential Columns</b><br>Select the correct fields from your DAT/CSV."))
                
        form_layout = QVBoxLayout()
                
        form_layout.addWidget(QLabel("Unique Identifier (DocID / BegDoc): *"))
        self.id_combo = QComboBox()
        self.id_combo.addItems(headers)
        self._auto_select(self.id_combo, ["begdoc", "docid", "begbates", "control number", "bates"])
        form_layout.addWidget(self.id_combo)
        
        form_layout.addSpacing(10)
        
        form_layout.addWidget(QLabel("Native File Path:"))
        self.native_combo = QComboBox()
        self.native_combo.addItem("<None>")
        self.native_combo.addItems(headers)
        self._auto_select(self.native_combo, ["native", "filename", "file_path"])
        form_layout.addWidget(self.native_combo)

        form_layout.addSpacing(10)
        
        form_layout.addWidget(QLabel("Text / OCR File Path:"))
        self.text_combo = QComboBox()
        self.text_combo.addItem("<None>")
        self.text_combo.addItems(headers)
        self._auto_select(self.text_combo, ["text", "ocr", "body"])
        form_layout.addWidget(self.text_combo)

        layout.addLayout(form_layout)
        layout.addStretch()
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _auto_select(self, combo, keywords):
        """Smartly pre-selects column if keyword matches"""
        for i in range(combo.count()):
            text = combo.itemText(i).lower()            
            if text in keywords:
                combo.setCurrentIndex(i)
                return            
            for k in keywords:
                if k in text:
                    combo.setCurrentIndex(i)
                    return

    def get_mapping(self):
        return {
            "id": self.id_combo.currentText(),
            "native": self.native_combo.currentText() if self.native_combo.currentText() != "<None>" else None,
            "text": self.text_combo.currentText() if self.text_combo.currentText() != "<None>" else None
        }
    
# ==========================================
# DATE TIME TOOL DIALOGS
# ==========================================
class MultiFieldSelectionDialog(QDialog):
    def __init__(self, headers):
        super().__init__()
        self.setWindowTitle("Select Fields for Date Formatting")
        self.resize(400, 500)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Select Date/Time fields to process:"))
        
        self.list_widget = QListWidget()
        for col_idx, h in enumerate(headers):
            item = QListWidgetItem(h)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, col_idx) 
            self.list_widget.addItem(item)
        
        layout.addWidget(self.list_widget)
        
        btn_layout = QHBoxLayout()
        btn_all = QPushButton("Select All")
        btn_none = QPushButton("Select None")
        btn_all.clicked.connect(self.select_all)
        btn_none.clicked.connect(self.select_none)
        btn_layout.addWidget(btn_all)
        btn_layout.addWidget(btn_none)
        layout.addLayout(btn_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def select_all(self):
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(Qt.Checked)

    def select_none(self):
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(Qt.Unchecked)

    def get_selected_indices(self):
        selected = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                selected.append((item.text(), item.data(Qt.UserRole)))
        return selected

class DateTimeConfigDialog(QDialog):
    def __init__(self, field_name):
        super().__init__()
        self.setWindowTitle(f"Configure: {field_name}")
        self.resize(450, 300)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"<b>Settings for field: {field_name}</b>"))        
        
        layout.addWidget(QLabel("Source Format (e.g. M/d/yyyy hh:mm:ss tt):"))
        self.src_format = QLineEdit("M/d/yyyy hh:mm:ss tt")
        layout.addWidget(self.src_format)
        
        layout.addWidget(QLabel("Target Format (e.g. yyyy-MM-dd HH:mm:ss):"))
        self.tgt_format = QLineEdit("yyyy-MM-dd HH:mm:ss")
        layout.addWidget(self.tgt_format)
        
        layout.addWidget(QLabel("Target Field Name:"))
        self.tgt_field = QLineEdit(field_name)
        self.tgt_field.setPlaceholderText("Enter name to create new column")
        layout.addWidget(self.tgt_field)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self):
        return {
            "src_fmt": self.src_format.text().strip(),
            "tgt_fmt": self.tgt_format.text().strip(),
            "tgt_field": self.tgt_field.text().strip()
        }
    
# ==========================================
# TIME ZONE DIALOG
# ==========================================
class TimeZoneConfigDialog(QDialog):
    def __init__(self, field_name):
        super().__init__()
        self.setWindowTitle(f"Time Zone: {field_name}")
        self.resize(500, 450)        
        
        try:
            import pytz
            self.all_zones = pytz.common_timezones
        except ImportError:
            self.all_zones = ["UTC", "US/Eastern", "US/Pacific", "Europe/London", "Asia/Kolkata"]

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>Convert Time Zone for: {field_name}</b>"))

        # --- FORMATS ---
        group_fmt = QGroupBox("Date Formats")
        fmt_layout = QVBoxLayout(group_fmt)
        
        fmt_layout.addWidget(QLabel("Source Date Format (e.g. MM/dd/yyyy hh:mm tt):"))
        self.src_format = QLineEdit("MM/dd/yyyy hh:mm:ss tt")
        fmt_layout.addWidget(self.src_format)
        
        fmt_layout.addWidget(QLabel("Target Date Format:"))
        self.tgt_format = QLineEdit("MM/dd/yyyy hh:mm:ss tt")
        fmt_layout.addWidget(self.tgt_format)
        layout.addWidget(group_fmt)

        # --- TIME ZONES ---
        group_tz = QGroupBox("Time Zones")
        tz_layout = QVBoxLayout(group_tz)
        
        tz_layout.addWidget(QLabel("Source Time Zone:"))
        self.src_tz = QComboBox()
        self.src_tz.setEditable(True)
        self.src_tz.addItems(self.all_zones)
        self.src_tz.setCurrentText("UTC")
        tz_layout.addWidget(self.src_tz)

        tz_layout.addWidget(QLabel("Target Time Zone:"))
        self.tgt_tz = QComboBox()
        self.tgt_tz.setEditable(True)
        self.tgt_tz.addItems(self.all_zones)
        self.tgt_tz.setCurrentText("US/Eastern")
        tz_layout.addWidget(self.tgt_tz)
        layout.addWidget(group_tz)

        # --- TARGET FIELD ---
        layout.addWidget(QLabel("Target Field Name:"))
        self.tgt_field = QLineEdit(field_name + "_Converted")
        layout.addWidget(self.tgt_field)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self):
        return {
            "src_fmt": self.src_format.text().strip(),
            "tgt_fmt": self.tgt_format.text().strip(),
            "src_tz": self.src_tz.currentText(),
            "tgt_tz": self.tgt_tz.currentText(),
            "tgt_field": self.tgt_field.text().strip()
        }
    
# ==========================================
# CONCATENATE & SPLIT DIALOGS
# ==========================================
class ConcatenateDialog(QDialog):
    def __init__(self, headers):
        super().__init__()
        self.setWindowTitle("Concatenate Fields")
        self.resize(600, 450)
        
        layout = QVBoxLayout(self)        
        
        field_layout = QHBoxLayout()
                
        left_lay = QVBoxLayout()
        left_lay.addWidget(QLabel("Available Fields:"))
        self.available = QListWidget()
        self.available.addItems(headers)
        self.available.setSelectionMode(QListWidget.ExtendedSelection)
        left_lay.addWidget(self.available)
        field_layout.addLayout(left_lay)
        
        btn_lay = QVBoxLayout()
        btn_lay.addStretch()
        self.btn_add = QPushButton(">")
        self.btn_rem = QPushButton("<")
        self.btn_add.clicked.connect(self.add_field)
        self.btn_rem.clicked.connect(self.rem_field)
        btn_lay.addWidget(self.btn_add)
        btn_lay.addWidget(self.btn_rem)
        btn_lay.addStretch()
        field_layout.addLayout(btn_lay)
        
        right_lay = QVBoxLayout()
        right_lay.addWidget(QLabel("Selected Fields (In Order):"))
        self.selected = QListWidget()
        self.selected.setSelectionMode(QListWidget.ExtendedSelection)
        right_lay.addWidget(self.selected)
        field_layout.addLayout(right_lay)
        
        layout.addLayout(field_layout)
        
        form_layout = QVBoxLayout()
        
        self.separator = QLineEdit()
        self.separator.setPlaceholderText("e.g. , or - or | (Leave empty for no separator)")
        form_layout.addWidget(QLabel("Separator:"))
        form_layout.addWidget(self.separator)

        self.target_field = QLineEdit()
        self.target_field.setPlaceholderText("Enter new field name")
        form_layout.addWidget(QLabel("Target Field Name:"))
        form_layout.addWidget(self.target_field)
        
        layout.addLayout(form_layout)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add_field(self):
        for item in self.available.selectedItems():
            self.selected.addItem(item.text())
            self.available.takeItem(self.available.row(item))

    def rem_field(self):
        for item in self.selected.selectedItems():
            self.available.addItem(item.text())
            self.selected.takeItem(self.selected.row(item))

    def get_values(self):
        return {
            "fields": [self.selected.item(i).text() for i in range(self.selected.count())],
            "sep": self.separator.text(),
            "target": self.target_field.text().strip()
        }

class SplitDialog(QDialog):
    def __init__(self, headers):
        super().__init__()
        self.setWindowTitle("Split Field")
        self.resize(400, 300)
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("Source Field to Split:"))
        self.source_combo = QComboBox()
        self.source_combo.addItems(headers)
        layout.addWidget(self.source_combo)

        layout.addWidget(QLabel("Separator (Delimiter):"))
        self.separator = QLineEdit()
        self.separator.setPlaceholderText("e.g. , or | or _")
        layout.addWidget(self.separator)

        layout.addWidget(QLabel("Target Field Names (Comma separated):"))
        self.targets = QLineEdit()
        self.targets.setPlaceholderText("e.g. First Name, Middle Name, Last Name")
        layout.addWidget(self.targets)
        
        layout.addWidget(QLabel("<i>Note: If split results exceed target fields, extras are ignored.</i>"))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self):        
        raw_targets = self.targets.text().split(',')
        clean_targets = [t.strip() for t in raw_targets if t.strip()]
        
        return {
            "source": self.source_combo.currentText(),
            "sep": self.separator.text(),
            "targets": clean_targets
        }

class BrandingConfigDialog(QDialog):
    def __init__(self, headers, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Branding & Endorsement Settings")
        self.setMinimumWidth(650)
        self.headers = headers
        self.pos_widgets = {}
        self.build_ui()

    def build_ui(self):
        layout = QVBoxLayout(self)
        
        # --- 1. Global Font & Layout Settings ---
        font_group = QGroupBox("Global Font & Layout Settings")
        font_layout = QGridLayout()
        
        font_layout.addWidget(QLabel("Font Family:"), 0, 0)
        self.font_family = QComboBox()
        self.font_family.addItems(["arial.ttf", "times.ttf", "calibri.ttf", "consola.ttf"])
        font_layout.addWidget(self.font_family, 0, 1)
        
        font_layout.addWidget(QLabel("Font Size (pt):"), 0, 2)
        self.font_size = QSpinBox()
        self.font_size.setRange(6, 72)
        self.font_size.setValue(10)
        font_layout.addWidget(self.font_size, 0, 3)
        
        font_layout.addWidget(QLabel("Base Margin (pt):"), 0, 4)
        self.margin_spin = QSpinBox()
        self.margin_spin.setRange(0, 100)
        self.margin_spin.setValue(15)
        font_layout.addWidget(self.margin_spin, 0, 5)

        font_layout.addWidget(QLabel("X-Offset (Left/Right):"), 1, 0)
        self.x_offset = QSpinBox()
        self.x_offset.setRange(-500, 500)
        self.x_offset.setValue(3)
        self.x_offset.setToolTip("Positive moves text Right, Negative moves Left")
        font_layout.addWidget(self.x_offset, 1, 1)

        font_layout.addWidget(QLabel("Y-Offset (Up/Down):"), 1, 2)
        self.y_offset = QSpinBox()
        self.y_offset.setRange(-500, 500)
        self.y_offset.setValue(25) 
        self.y_offset.setToolTip("Positive moves text Down (Below), Negative moves Up")
        font_layout.addWidget(self.y_offset, 1, 3)
        
        font_group.setLayout(font_layout)
        layout.addWidget(font_group)
        
        # --- 2. Independent Positions & Colors ---
        pos_group = QGroupBox("Endorsement Positions & Colors")
        pos_layout = QGridLayout()
        
        positions = [
            ("TL", "Top Left", 0), ("TC", "Top Center", 1), ("TR", "Top Right", 2),
            ("BL", "Bottom Left", 3), ("BC", "Bottom Center", 4), ("BR", "Bottom Right", 5)
        ]
        
        for code, name, row in positions:
            pos_layout.addWidget(QLabel(f"<b>{name}:</b>"), row, 0)
            
            type_cb = QComboBox()
            type_cb.addItems(["None", "Manual Text", "DAT Field"])
            pos_layout.addWidget(type_cb, row, 1)
            
            stack = QStackedWidget()
            empty_w = QWidget() 
            manual_w = QLineEdit()
            manual_w.setPlaceholderText("Enter custom text...")
            field_w = QComboBox()
            field_w.addItems(self.headers)
            
            stack.addWidget(empty_w)   
            stack.addWidget(manual_w)  
            stack.addWidget(field_w)   
            pos_layout.addWidget(stack, row, 2)
            
            color_btn = QPushButton("⬛ Color")
            color_btn.setStyleSheet("background-color: #000000; color: white; font-weight: bold;")
            color_btn.color_val = "#000000" 
            color_btn.clicked.connect(lambda checked, b=color_btn: self.pick_color(b))
            color_btn.setEnabled(False) 
            pos_layout.addWidget(color_btn, row, 3)
            
            type_cb.currentIndexChanged.connect(lambda idx, s=stack, cb=color_btn: self.toggle_input(idx, s, cb))
            self.pos_widgets[code] = {"type": type_cb, "stack": stack, "manual": manual_w, "field": field_w, "color": color_btn}
        
        pos_group.setLayout(pos_layout)
        layout.addWidget(pos_group)
        
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        
    def toggle_input(self, idx, stack, color_btn):
        stack.setCurrentIndex(idx)
        color_btn.setEnabled(idx != 0) 
            
    def pick_color(self, btn):
        color = QColorDialog.getColor()
        if color.isValid():
            hex_color = color.name()
            btn.color_val = hex_color
            text_col = "black" if color.lightness() > 128 else "white"
            btn.setStyleSheet(f"background-color: {hex_color}; color: {text_col}; font-weight: bold;")
            
    def get_config(self):
        cfg = {
            "font": {
                "family": self.font_family.currentText(), 
                "size": self.font_size.value(),
                "x_offset": self.x_offset.value(),
                "y_offset": self.y_offset.value()
            },
            "margin": self.margin_spin.value(),
            "branding": {}
        }
        for code, widgets in self.pos_widgets.items():
            t_idx = widgets["type"].currentIndex()
            if t_idx != 0: 
                val = widgets["manual"].text().strip() if t_idx == 1 else widgets["field"].currentText()
                col = widgets["color"].color_val
                if val:
                    cfg["branding"][code] = {
                        "type": "manual" if t_idx == 1 else "field",
                        "value": val,
                        "color": col
                    }
        return cfg
    
class TextQCSettingsDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Text QC Settings")
        self.resize(500, 400)
        
        layout = QVBoxLayout(self)
                
        self.chk_empty = QCheckBox("Check for Empty Text Files (0 KB)")
        self.chk_empty.setChecked(True)
        layout.addWidget(self.chk_empty)
        
        layout.addSpacing(10)
                
        layout.addWidget(QLabel("<b>Search Phrases (One per line):</b>"))
        layout.addWidget(QLabel("<i>Enter exact phrases to find (e.g. 'Document withheld'). Case-insensitive.</i>"))
        
        self.txt_terms = QTextEdit()        
        defaults = (
            "Document withheld for Privilege\n"
            "Document cannot be Rendered\n"
            "Document cannot be Viewed\n"
            "Redact"
        )
        self.txt_terms.setPlainText(defaults)
        layout.addWidget(self.txt_terms)
                
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
    def get_settings(self):        
        raw_text = self.txt_terms.toPlainText()
        terms = [line.strip().lower() for line in raw_text.split('\n') if line.strip()]
        
        return {
            "check_empty": self.chk_empty.isChecked(),
            "search_terms": terms
        }

class NativeRenameConfigDialog(QDialog):
    def __init__(self, current_native_field):
        super().__init__()
        self.setWindowTitle("Native File Rename Settings")
        self.resize(400, 250)
        
        layout = QVBoxLayout(self)
        
        info = QLabel(f"<b>Target Field:</b> {current_native_field}")
        info.setStyleSheet("color: blue; font-size: 13px;")
        layout.addWidget(info)
        layout.addWidget(QLabel("<i>Files on disk will be renamed. File extension will remain unchanged.</i>"))
        
        layout.addSpacing(10)
        
        form_layout = QGridLayout()
        
        self.separator = QLineEdit("_")
        self.separator.setPlaceholderText("e.g. _ or -")
        form_layout.addWidget(QLabel("Separator:"), 0, 0)
        form_layout.addWidget(self.separator, 0, 1)
        
        self.suffix = QLineEdit("Confidential")
        self.suffix.setPlaceholderText("Text to append (e.g. Confidential)")
        form_layout.addWidget(QLabel("Text to Append:"), 1, 0)
        form_layout.addWidget(self.suffix, 1, 1)
        
        layout.addLayout(form_layout)
        
        layout.addSpacing(10)
        self.preview_lbl = QLabel("Example: DOC001.xls -> DOC001_Confidential.xls")
        self.preview_lbl.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self.preview_lbl)
        
        self.separator.textChanged.connect(self.update_preview)
        self.suffix.textChanged.connect(self.update_preview)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def update_preview(self):
        sep = self.separator.text()
        suf = self.suffix.text()
        self.preview_lbl.setText(f"Example: DOC001.xls -> DOC001{sep}{suf}.xls")

    def get_values(self):
        return {
            "separator": self.separator.text(),
            "suffix": self.suffix.text()
        }

class ImportFieldSelectionDialog(QDialog):
    def __init__(self, fields, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Fields to Import")
        self.resize(550, 450)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select which fields you want to load into the grid.\n(Use Shift/Ctrl to select multiple, or Double-Click to move)"))

        h_layout = QHBoxLayout()
        
        self.avail_list = QListWidget()
        self.avail_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.avail_list.addItems(fields)
        self.avail_list.itemDoubleClicked.connect(self.add_field)

        self.sel_list = QListWidget()
        self.sel_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.sel_list.itemDoubleClicked.connect(self.remove_field)

        v_btn_layout = QVBoxLayout()
        self.btn_add = QPushButton(">> Add >>")
        self.btn_remove = QPushButton("<< Remove <<")
        self.btn_add.clicked.connect(self.add_field)
        self.btn_remove.clicked.connect(self.remove_field)
        
        v_btn_layout.addStretch()
        v_btn_layout.addWidget(self.btn_add)
        v_btn_layout.addWidget(self.btn_remove)
        v_btn_layout.addStretch()

        h_layout.addWidget(self.avail_list)
        h_layout.addLayout(v_btn_layout)
        h_layout.addWidget(self.sel_list)

        layout.addLayout(h_layout)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def add_field(self):
        for item in self.avail_list.selectedItems():
            self.sel_list.addItem(item.text())
            self.avail_list.takeItem(self.avail_list.row(item))

    def remove_field(self):
        for item in self.sel_list.selectedItems():
            self.avail_list.addItem(item.text())
            self.sel_list.takeItem(self.sel_list.row(item))

    def get_selected_fields(self):
        return [self.sel_list.item(i).text() for i in range(self.sel_list.count())]

class CustomExportConfigDialog(QDialog):
    def __init__(self, headers, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Custom Structured Export")
        self.resize(550, 480)
        
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Setup Custom Folder Structure & File Renaming</b>"))
        
        form = QGridLayout()
        
        self.out_dir_input = QLineEdit()
        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.clicked.connect(self.browse_dir)
        form.addWidget(QLabel("Output Root Folder:"), 0, 0)
        form.addWidget(self.out_dir_input, 0, 1)
        form.addWidget(self.btn_browse, 0, 2)

        self.vol_input = QLineEdit("Please Enter Volume Name")
        form.addWidget(QLabel("Volume Name:"), 1, 0)
        form.addWidget(self.vol_input, 1, 1, 1, 2)
        
        self.encoding_cb = QComboBox()
        self.encoding_cb.addItems(["utf-8", "utf-8-sig (BOM)", "ansi", "windows-1252", "ascii", "utf-16"])
        form.addWidget(QLabel("Export Encoding:"), 2, 0)
        form.addWidget(self.encoding_cb, 2, 1, 1, 2)
        
        self.custodian_cb = QComboBox()
        self.custodian_cb.addItems(["<None (Root)>"] + headers)
        form.addWidget(QLabel("Foldering Field:"), 3, 0)
        form.addWidget(self.custodian_cb, 3, 1, 1, 2)
        
        self.suffix_cb = QComboBox()
        self.suffix_cb.addItems(["<None>"] + headers)
        form.addWidget(QLabel("Suffix Field:"), 4, 0)
        form.addWidget(self.suffix_cb, 4, 1, 1, 2)
        
        self.separator = QLineEdit("_")
        form.addWidget(QLabel("Suffix Separator:"), 5, 0)
        form.addWidget(self.separator, 5, 1, 1, 2)
        
        layout.addLayout(form)
        layout.addSpacing(10)
        
        layout.addWidget(QLabel("<b>Files to Rename (Unchecked = Keep Original Filename):</b>\n*Note: Files will still be copied to new Volume structure."))
        comp_layout = QHBoxLayout()
        self.chk_images = QCheckBox("Rename Images")
        self.chk_images.setChecked(True)
        self.chk_natives = QCheckBox("Rename Natives")
        self.chk_natives.setChecked(True)
        self.chk_text = QCheckBox("Rename Text")
        self.chk_text.setChecked(True)
        
        comp_layout.addWidget(self.chk_images)
        comp_layout.addWidget(self.chk_natives)
        comp_layout.addWidget(self.chk_text)
        layout.addLayout(comp_layout)

        layout.addStretch()

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if d: self.out_dir_input.setText(d)

    def get_config(self):
        return {
            "out_dir": self.out_dir_input.text().strip(),
            "vol_name": self.vol_input.text().strip(),
            "encoding": self.encoding_cb.currentText(),
            "custodian_field": self.custodian_cb.currentText(),
            "suffix_field": self.suffix_cb.currentText(),
            "sep": self.separator.text(),
            "do_images": self.chk_images.isChecked(),
            "do_natives": self.chk_natives.isChecked(),
            "do_text": self.chk_text.isChecked()
        }
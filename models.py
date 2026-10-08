from PySide6.QtCore import Qt, QAbstractTableModel
from PySide6.QtGui import QColor

class LazyDatTableModel(QAbstractTableModel):
    def __init__(self, headers, data, visible_idx, locked_col=-1):
        super().__init__()
        self.headers = headers
        self._data = data
        self.visible_idx = visible_idx
        self.locked_col = locked_col 

    def rowCount(self, parent=None):
        return len(self.visible_idx)

    def columnCount(self, parent=None):
        return len(self.headers)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        
        if role == Qt.DisplayRole or role == Qt.EditRole:
            r_idx = self.visible_idx[index.row()]
            c_idx = index.column()            
            if c_idx < len(self._data[r_idx]):
                return self._data[r_idx][c_idx]

        if role == Qt.BackgroundRole and index.column() == self.locked_col:
            return QColor("#f0f0f0")

        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role == Qt.EditRole:
            if index.column() == self.locked_col:
                return False

            r_idx = self.visible_idx[index.row()]
            c_idx = index.column()

            while len(self._data[r_idx]) <= c_idx:
                self._data[r_idx].append("")
                
            self._data[r_idx][c_idx] = value
            self.dataChanged.emit(index, index, [Qt.DisplayRole])
            return True
        return False

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            if section < len(self.headers):
                return self.headers[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags

        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable

        if index.column() != self.locked_col:
            f |= Qt.ItemIsEditable
            
        return f
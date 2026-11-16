"""Reusable native file selectors and bounded previews."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QPushButton, QFileDialog, QLabel


class PathField(QWidget):
    def __init__(self, mode='file', file_filter='All files (*)', value=''):
        super().__init__()
        self.mode, self.file_filter = mode, file_filter
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(str(value))
        button = QPushButton('浏览…')
        button.clicked.connect(self.browse)
        layout.addWidget(self.edit, 1)
        layout.addWidget(button)

    def browse(self):
        if self.mode == 'directory':
            value = QFileDialog.getExistingDirectory(self, '选择目录', self.text())
        else:
            value, _ = QFileDialog.getOpenFileName(self, '选择文件', self.text(), self.file_filter)
        if value:
            self.edit.setText(value)

    def text(self):
        return self.edit.text().strip()


class Preview(QLabel):
    def __init__(self):
        super().__init__('处理结果将在这里显示\n原始观测缺测区域保持透明')
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(340, 200)
        self.setStyleSheet('background: #172332; color: #c3d0e2; border-radius: 8px;')

    def show_file(self, path):
        reader = QImageReader(str(path))
        size = reader.size()
        if size.isValid():
            size.scale(1000, 560, Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(size)
        image = reader.read()
        if not image.isNull():
            self.setPixmap(QPixmap.fromImage(image).scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

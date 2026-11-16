"""Explicit adapters for existing verified composition contracts."""
from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import QLabel, QDateTimeEdit, QComboBox
from .pages import WorkflowPage
from .widgets import PathField


class CompositePage(WorkflowPage):
    def __init__(self):
        super().__init__()
        notice = QLabel('高级合成入口沿用现有来源与质量检查。\n'
                        '昼夜合成需先准备匹配的日侧与夜间产品，不会自动补齐缺失波段。')
        notice.setWordWrap(True)
        self.form.addRow(notice)
        self.manifest = PathField(file_filter='ABI scene (*.json)')
        self.form.addRow('GOES 日侧原始清单', self.manifest)
        self.width = QComboBox()
        self.width.addItems(['2048', '4096', '8192'])
        self.form.addRow('输出宽度', self.width)
        self.button('生成实测 GOES 日侧 RGB', 'daylight', lambda: {
            'manifest': self.manifest.text(), 'width': int(self.width.currentText())})
        self.day = PathField(file_filter='Day product (*.png)')
        self.night = PathField(file_filter='Night product (*.png)')
        self.form.addRow('日侧产品', self.day)
        self.form.addRow('夜间产品', self.night)
        self.utc = QDateTimeEdit(QDateTime.fromString('2020-10-29T16:40:00', 'yyyy-MM-ddTHH:mm:ss'))
        self.utc.setDisplayFormat("yyyy-MM-dd HH:mm 'UTC'")
        self.form.addRow('合成参考 UTC', self.utc)
        self.button('合成昼夜地球贴图', 'day-night', lambda: {
            'day': self.day.text(), 'night': self.night.text(), 'utc': self.utc_text()})
        self.sources = PathField(file_filter='Geometry sources (*.json)')
        self.form.addRow('红外源投影清单', self.sources)
        self.button('按观测角度混合红外接缝', 'blend-ir', lambda: {
            'sources': self.sources.text(), 'utc': self.utc_text()})
        self.form.addRow(QLabel('此红外混合为派生显示，不能用作单传感器亮温测量。'))

    def utc_text(self):
        return self.utc.dateTime().toString("yyyy-MM-ddTHH:mm:00'Z'")

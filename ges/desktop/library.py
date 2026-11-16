"""Small task index; never recursively scans the raw satellite archive."""
from pathlib import Path
import json
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QListWidget, QLabel
from ges.storage import load_config
from .widgets import PathField


class LibraryPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('本次桌面整合产生的任务；双击打开任务目录和完整日志。'))
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self.open_job)
        layout.addWidget(self.list)
        refresh = QPushButton('刷新任务记录')
        refresh.clicked.connect(self.refresh)
        layout.addWidget(refresh)
        layout.addWidget(QLabel('也可选择已有的 .blend、图片或研究报告打开：'))
        self.existing = PathField(file_filter='Results (*.blend *.png *.jpg *.html *.mp4 *.json);;All files (*)')
        layout.addWidget(self.existing)
        button = QPushButton('打开已有成果')
        button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.existing.text())))
        layout.addWidget(button)
        self.directories = []
        self.refresh()

    def refresh(self):
        self.list.clear()
        self.directories = []
        root = load_config().processed_dir / 'desktop_jobs'
        if not root.is_dir():
            return
        states = {'succeeded': '完成', 'failed': '失败', 'cancelled': '中断',
                  'running': '上次运行状态，详见日志', 'queued': '已创建'}
        for directory in sorted(root.iterdir(), reverse=True)[:200]:
            try:
                job = json.loads((directory / 'job.json').read_text(encoding='utf-8'))
                self.list.addItem(f"{directory.name}  |  {job['action']}  |  {states.get(job['status'], job['status'])}")
                self.directories.append(directory)
            except (OSError, ValueError, KeyError):
                continue

    def open_job(self, item):
        directory = self.directories[self.list.row(item)]
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

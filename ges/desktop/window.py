"""Application controller: navigation, task dispatch and result handoff."""
from pathlib import Path
import sys
from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QSplitter, QPlainTextEdit, QLabel, QPushButton, QProgressBar,
    QMessageBox, QScrollArea)
from ges.storage import load_config
from .jobs import Job
from .runner import TaskRunner
from .pages import SourcesPage, ProcessingPage, BlenderPage, StoragePage
from .widgets import Preview
from .library import LibraryPage
from .composite import CompositePage


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Satellite Earth Studio · 桌面整合预览版')
        self.resize(1250, 850)
        self.settings = QSettings()
        self.result = ''
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        heading = QLabel('Satellite Earth Studio')
        heading.setStyleSheet('font-size: 24px; font-weight: 600; padding: 10px;')
        layout.addWidget(heading)
        layout.addWidget(QLabel('真实卫星数据 → 经纬度贴图 → 多卫星覆盖 → Blender 场景'))
        split = QSplitter()
        self.tabs = QTabWidget()
        self.sources = SourcesPage()
        self.processing = ProcessingPage()
        self.blender = BlenderPage(self.settings)
        self.storage = StoragePage()
        self.composite = CompositePage()
        for title, page in [('数据下载', self.sources), ('处理与拼图', self.processing),
                            ('昼夜合成', self.composite), ('Blender 与导出', self.blender), ('存储设置', self.storage)]:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.tabs.addTab(scroll, title)
            page.requested.connect(self.dispatch)
        self.library = LibraryPage()
        self.tabs.addTab(self.library, '成果与任务')
        split.addWidget(self.tabs)
        self.preview = Preview()
        split.addWidget(self.preview)
        split.setSizes([650, 550])
        layout.addWidget(split, 3)
        row = QHBoxLayout()
        self.status = QLabel('就绪 · 任务在独立进程运行')
        row.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(130)
        self.progress.setRange(0, 1)
        row.addWidget(self.progress)
        self.cancel = QPushButton('中断任务')
        self.cancel.setEnabled(False)
        row.addWidget(self.cancel)
        self.open_result = QPushButton('打开结果')
        self.open_result.setEnabled(False)
        self.open_result.clicked.connect(self.show_result)
        row.addWidget(self.open_result)
        self.open_folder = QPushButton('打开任务目录')
        self.open_folder.clicked.connect(self.show_folder)
        row.addWidget(self.open_folder)
        layout.addLayout(row)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(1200)
        self.log.setPlaceholderText('实时任务日志；完整日志会保存在任务目录。')
        layout.addWidget(self.log, 1)
        self.runner = TaskRunner(self)
        self.runner.output.connect(self.append_log)
        self.runner.busy_changed.connect(self.set_busy)
        self.runner.completed.connect(self.finished)
        self.cancel.clicked.connect(self.runner.cancel)
        self.setStyleSheet('QMainWindow { background: #f3f5f8; } '
                           'QPushButton { padding: 6px 12px; } QTabWidget::pane { border: 1px solid #d6dce5; }')
        self.job_directory = None

    def append_log(self, text):
        cursor = self.log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    def dispatch(self, action, options):
        try:
            for field in ('manifest', 'inventory', 'image', 'blender', 'day', 'night', 'sources'):
                if field in options and not Path(options[field]).is_file():
                    raise ValueError(f'请先选择有效文件：{field}')
            if action == 'mosaic' and len(options['images']) < 2:
                raise ValueError('拼图至少需要两张输入贴图。')
            if action == 'render-batch' and not options['manifests']:
                raise ValueError('请先选择批量处理的原始场景清单。')
            cfg = load_config()
            job = Job.create(action, options, cfg.processed_dir)
            self.job_directory = job.directory
            self.log.clear()
            self.preview.clear()
            self.preview.setText('任务运行中，完成后显示图像预览')
            self.result = ''
            self.open_result.setEnabled(False)
            python = Path(sys.executable).with_name('python.exe') if sys.platform == 'win32' else Path(sys.executable)
            self.runner.start(job, python)
            self.status.setText(f'运行中：{action} · 具体阶段见日志')
        except (OSError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self, '无法启动任务', str(error))

    def set_busy(self, busy):
        self.tabs.setEnabled(not busy)
        self.cancel.setEnabled(busy)
        self.progress.setRange(0, 0 if busy else 1)

    def finished(self, status, result):
        self.result = result
        names = {'succeeded': '完成', 'failed': '失败，请查看日志', 'cancelled': '已中断，已归档文件保留'}
        self.status.setText(names[status])
        self.open_result.setEnabled(bool(result))
        self.library.refresh()
        if not result:
            return
        path = Path(result)
        if path.name == 'scene.json':
            self.processing.manifest.edit.setText(result)
        if path.name == 'meteosat_inventory.json':
            self.sources.inventory.edit.setText(result)
        if path.suffix.lower() == '.png':
            self.blender.image.edit.setText(result)
            self.preview.show_file(path)
        if path.suffix.lower() == '.blend' and path.with_suffix('.png').is_file():
            self.preview.show_file(path.with_suffix('.png'))

    def show_result(self):
        if self.result:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.result))

    def show_folder(self):
        if self.job_directory:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.job_directory)))

    def closeEvent(self, event):
        if self.runner.busy:
            self.status.setText('任务仍在运行，请先中断或等待结束再关闭。')
            event.ignore()
        else:
            event.accept()

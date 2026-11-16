"""Workflow forms only; task execution is owned by the application controller."""
from pathlib import Path
from PySide6.QtCore import QDateTime, Signal
from PySide6.QtWidgets import (QWidget, QFormLayout, QComboBox, QDateTimeEdit,
    QPushButton, QLabel, QPlainTextEdit, QFileDialog, QDoubleSpinBox)
from ges.storage import StorageConfig, load_config, save_config
from .widgets import PathField


class WorkflowPage(QWidget):
    requested = Signal(str, dict)

    def __init__(self):
        super().__init__()
        self.form = QFormLayout(self)
        self.form.setSpacing(14)

    def button(self, text, action, options):
        button = QPushButton(text)
        button.setMinimumHeight(36)
        button.clicked.connect(lambda: self.requested.emit(action, options()))
        self.form.addRow(button)
        return button


class SourcesPage(WorkflowPage):
    def __init__(self):
        super().__init__()
        self.form.addRow(QLabel('按 UTC 查询真实存档；下载前自动检查体积与磁盘预算。'))
        self.utc = QDateTimeEdit(QDateTime.fromString('2020-10-29T16:40:00', 'yyyy-MM-ddTHH:mm:ss'))
        self.utc.setDisplayFormat("yyyy-MM-dd HH:mm 'UTC'")
        self.utc.setMinimumDateTime(QDateTime.fromString('2018-01-01', 'yyyy-MM-dd'))
        self.utc.setCalendarPopup(True)
        self.form.addRow('观测时间（UTC）', self.utc)
        self.satellite = QComboBox()
        self.satellite.addItems(['auto', 'himawari8', 'himawari9', 'goes16', 'goes17', 'goes18', 'goes19'])
        self.form.addRow('NOAA 卫星', self.satellite)
        self.product = QComboBox()
        self.product.addItems(['ir-gray', 'rgb', 'ir-bd'])
        self.form.addRow('数据产品', self.product)
        self.button('查询 NOAA 数据', 'search', self.options)
        self.button('下载 NOAA 原始数据', 'download', self.options)
        self.button('查询 Meteosat 双星目录', 'meteosat-search', self.options)
        self.inventory = PathField(file_filter='Inventory (*.json)')
        self.form.addRow('Meteosat 候选目录', self.inventory)
        self.button('下载目录中的 Meteosat 数据', 'meteosat-download',
                    lambda: {'inventory': self.inventory.text()})
        self.form.addRow(QLabel('Meteosat 需先运行 configure_eumetsat.bat 配置本机凭据。\n'
                               'IR 灰度与 IR-BD 用于数据检查，不代表最终电影画面。'))

    def options(self):
        return {'utc': self.utc.dateTime().toString("yyyy-MM-ddTHH:mm:00'Z'"),
                'satellite': self.satellite.currentText(), 'product': self.product.currentText()}


class ProcessingPage(WorkflowPage):
    def __init__(self):
        super().__init__()
        self.manifest = PathField(file_filter='Scene manifest (*.json)')
        self.form.addRow('原始数据 scene.json', self.manifest)
        self.product = QComboBox()
        self.product.addItems(['ir-gray', 'rgb', 'ir-bd'])
        self.form.addRow('处理产品', self.product)
        self.width = QComboBox()
        self.width.addItems(['2048', '4096', '8192'])
        self.form.addRow('全球网格宽度', self.width)
        self.button('生成经纬度贴图', 'render', lambda: {
            'manifest': self.manifest.text(), 'product': self.product.currentText(),
            'width': int(self.width.currentText())})
        self.manifests = []
        self.batch_label = QLabel('批量任务：尚未选择场景')
        self.form.addRow(self.batch_label)
        select_batch = QPushButton('选择多个原始 scene.json…')
        select_batch.clicked.connect(self.select_batch)
        self.form.addRow(select_batch)
        self.button('顺序批量处理所选场景', 'render-batch', lambda: {
            'manifests': self.manifests, 'product': self.product.currentText(),
            'width': int(self.width.currentText())})
        self.images = QPlainTextEdit()
        self.images.setPlaceholderText('每行一个 PNG 路径；必须附带来源 JSON，网格和产品一致。')
        self.images.setMaximumHeight(130)
        self.form.addRow('多卫星拼图输入', self.images)
        select = QPushButton('添加多个贴图…')
        select.clicked.connect(self.add_images)
        self.form.addRow(select)
        self.utc = QDateTimeEdit(QDateTime.fromString('2020-10-29T16:40:00', 'yyyy-MM-ddTHH:mm:ss'))
        self.utc.setDisplayFormat("yyyy-MM-dd HH:mm 'UTC'")
        self.form.addRow('拼图参考 UTC', self.utc)
        self.button('生成覆盖拼图（保留缺测）', 'mosaic', lambda: {
            'images': [p.strip() for p in self.images.toPlainText().splitlines() if p.strip()],
            'utc': self.utc.dateTime().toString("yyyy-MM-ddTHH:mm:00'Z'")})
        self.form.addRow(QLabel('此入口为按顺序叠加真实覆盖，仍可能有接缝。\n极地不纳入本版补齐范围。'))

    def add_images(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '选择处理贴图', '', 'PNG (*.png)')
        if paths:
            old = self.images.toPlainText().strip()
            self.images.setPlainText('\n'.join(([old] if old else []) + paths))

    def select_batch(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '选择原始场景清单', '', 'Scene manifests (*.json)')
        if paths:
            self.manifests = paths
            self.batch_label.setText(f'批量任务：已选择 {len(paths)} 个场景（依次处理）')


class BlenderPage(WorkflowPage):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.blender = PathField(file_filter='Blender (blender.exe)', value=settings.value('blender', ''))
        self.form.addRow('Blender 程序', self.blender)
        self.image = PathField(file_filter='Global texture (*.png)')
        self.form.addRow('地球贴图（带来源 JSON）', self.image)
        self.earth = PathField(file_filter='Earth texture (*.png *.jpg *.jpeg)')
        self.form.addRow('可选静态地表', self.earth)
        self.button('生成 Blender 场景和预览', 'blender', self.options)
        self.button('永久导出当前 PNG 和来源', 'export', lambda: {'image': self.image.text()})
        self.form.addRow(QLabel('场景打包贴图，生成后可在 Blender 手动运镜。\n'
                               '未选地表时为占位球面；高级体积云与大气尚未整合。'))

    def options(self):
        self.settings.setValue('blender', self.blender.text())
        return {'blender': self.blender.text(), 'image': self.image.text(), 'earth': self.earth.text()}


class StoragePage(WorkflowPage):
    def __init__(self):
        super().__init__()
        cfg = load_config()
        self.raw = PathField('directory', value=cfg.raw_dir)
        self.processed = PathField('directory', value=cfg.processed_dir)
        self.exports = PathField('directory', value=cfg.export_dir)
        for label, field in [('原始数据目录', self.raw), ('处理与任务目录', self.processed), ('永久导出目录', self.exports)]:
            self.form.addRow(label, field)
        self.budget = QDoubleSpinBox()
        self.budget.setRange(0.1, 100)
        self.budget.setValue(cfg.max_single_scene_gb)
        self.reserve = QDoubleSpinBox()
        self.reserve.setRange(0, 500)
        self.reserve.setValue(cfg.reserve_free_gb)
        self.form.addRow('单景下载上限（GB）', self.budget)
        self.form.addRow('磁盘保留空间（GB）', self.reserve)
        self.save = QPushButton('保存存储设置')
        self.form.addRow(self.save)
        self.message = QLabel('三个目录须互相独立；不会自动清理原始数据和导出。')
        self.message.setWordWrap(True)
        self.form.addRow(self.message)
        self.save.clicked.connect(self.persist)

    def persist(self):
        try:
            if not all(field.text() for field in (self.raw, self.processed, self.exports)):
                raise ValueError('请填写全部三个存储目录。')
            save_config(StorageConfig(Path(self.raw.text()), Path(self.processed.text()),
                Path(self.exports.text()), self.budget.value(), self.reserve.value()))
            self.message.setText('已保存，下一个任务使用新设置。')
        except (OSError, ValueError) as error:
            self.message.setText(str(error))

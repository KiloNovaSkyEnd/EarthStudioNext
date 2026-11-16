"""Asynchronous process lifecycle, bounded UI logs and persistent full logs."""
import codecs
import json
import os
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal
from .jobs import ROOT


class TaskRunner(QObject):
    output = Signal(str)
    completed = Signal(str, str)
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(ROOT))
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.insert('PYTHONUTF8', '1')
        env.insert('PYTHONIOENCODING', 'utf-8')
        self.process.setProcessEnvironment(env)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.process.started.connect(lambda: self._stop_process() if self.cancelled else None)
        self.job = None
        self.cancelled = False

    @property
    def busy(self):
        return self.job is not None

    def start(self, job, python):
        if self.busy:
            raise RuntimeError('请等待当前任务结束。')
        self.job = job
        self.cancelled = False
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.log = (job.directory / 'task.log').open('ab')
        job.update('running')
        self.busy_changed.emit(True)
        executable, arguments = job.command(python)
        self.process.start(executable, arguments)

    def _read(self):
        data = bytes(self.process.readAllStandardOutput())
        if self.job and data:
            self.log.write(data)
            self.log.flush()
            self.output.emit(self.decoder.decode(data))

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart and self.job:
            self.output.emit(self.process.errorString())
            self._finish('failed', '')

    def _finished(self, code, exit_status):
        if not self.job:
            return
        self._read()
        status = 'cancelled' if self.cancelled else 'succeeded' if code == 0 else 'failed'
        result = ''
        try:
            if status == 'succeeded':
                result = json.loads((self.job.directory / 'result.json').read_text(encoding='utf-8'))['path']
        except (OSError, ValueError, KeyError):
            status = 'failed'
        self._finish(status, result)

    def _finish(self, status, result):
        self.log.close()
        self.job.update(status, result=result)
        self.job = None
        self.busy_changed.emit(False)
        self.completed.emit(status, result)

    def cancel(self):
        if not self.busy:
            return
        self.cancelled = True
        if self.process.processId():
            self._stop_process()

    def _stop_process(self):
        if os.name == 'nt':
            # Asynchronous taskkill /T also stops Blender, without a shell/window.
            self.killer = QProcess(self)
            self.killer.start('taskkill', ['/PID', str(self.process.processId()), '/T', '/F'])
        else:
            self.process.kill()

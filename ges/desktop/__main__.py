import sys
import traceback
from pathlib import Path
from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox
from .window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName('Deepsky')
    app.setApplicationName('Satellite Earth Studio')
    app.setStyle('Fusion')
    def report_error(kind, value, tb):
        directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / 'desktop_errors.log').open('a', encoding='utf-8') as log:
                traceback.print_exception(kind, value, tb, file=log)
        except OSError:
            pass
        QMessageBox.critical(None, '桌面程序发生错误',
                             f'{value}\n\n错误日志：{directory / "desktop_errors.log"}')
    sys.excepthook = report_error
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()

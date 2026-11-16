"""Offline native-window and optional real Blender process smoke check.

Run with project Python from project root:
  python scripts/verify_desktop.py --out <new-review-directory>
Optional: --image <existing GES PNG> --blender <blender.exe>
Never downloads satellite data or rewrites existing scenes/textures.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from ges.desktop.window import MainWindow
from ges.desktop.jobs import Job


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--image')
    parser.add_argument('--blender')
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.processEvents()
    if args.image:
        window.preview.show_file(args.image)
        window.blender.image.edit.setText(str(Path(args.image).resolve()))
    if args.blender:
        window.blender.blender.edit.setText(str(Path(args.blender).resolve()))
    app.processEvents()
    window.grab().save(str(out / 'desktop.png'))
    report = {'tabs': window.tabs.count(), 'screenshot': str(out / 'desktop.png')}
    if args.image and args.blender:
        job = Job.create('blender', {'image': str(Path(args.image).resolve()),
            'blender': str(Path(args.blender).resolve()), 'earth': ''}, out)
        window.job_directory = job.directory
        loop = QEventLoop()
        ticks = []
        heartbeat = QTimer()
        heartbeat.timeout.connect(lambda: ticks.append(1))
        heartbeat.start(25)
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(window.runner.cancel)
        timeout.start(180000)
        def finished(status, result):
            report.update(status=status, result=result, responsive_ticks=len(ticks))
            loop.quit()
        window.runner.completed.connect(finished)
        window.runner.start(job, sys.executable)
        loop.exec()
        heartbeat.stop()
        timeout.stop()
        app.processEvents()
        window.grab().save(str(out / 'desktop_completed.png'))
    window.close()
    (out / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    if report.get('status', 'succeeded') != 'succeeded':
        raise SystemExit(1)


if __name__ == '__main__':
    main()

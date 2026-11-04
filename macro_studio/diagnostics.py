"""No-input diagnostics for testing a packaged application without Python."""
import json
from pathlib import Path
import tempfile
import traceback
import os


def self_test(output):
    result = {'ok': False, 'checks': []}
    try:
        from PySide6.QtCore import QSettings, QByteArray, QBuffer, QIODevice
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QIcon, QImage, QPainter, QFont, QColor, QFontDatabase
        from . import launcher
        from .app import MainWindow, STYLE
        from .workflow import Workflow, Module, save_workflow, load_workflow
        from .model import Action
        from .run_control import RunControl, WindowGuard
        from .engine import DesktopBackend, execute
        from .reporting import ReportConfig, contains
        from .screen_ocr import read_png
        from .discord_notifications import protect
        from .version import VERSION
        import cv2
        import numpy as np
        import mss
        from pynput import keyboard, mouse
        result['version'] = VERSION
        app = QApplication.instance() or QApplication([])
        for font in ('arial.ttf', 'segoeui.ttf'):
            QFontDatabase.addApplicationFont(str(Path(os.environ['SystemRoot']) / 'Fonts' / font))
        app.setStyle('Fusion')
        app.setStyleSheet(STYLE)
        with tempfile.TemporaryDirectory(prefix='macro-studio-diagnostic-') as folder:
            folder = Path(folder)
            launcher.default_settings = lambda: QSettings(str(folder / 'test.ini'), QSettings.IniFormat)
            launcher.PROJECT_FOLDER = folder
            icon = QIcon(str(Path(__file__).parent / 'icons' / 'app.ico'))
            assert not icon.pixmap(64, 64).isNull()
            assert not QIcon(str(Path(__file__).parent / 'icons' / 'check.svg')).pixmap(16, 16).isNull()
            result['checks'].append('icônes et plugins Qt')
            window = MainWindow()
            workflow = Workflow([Module('Premier', [Action.create('wait')]), Module('Second', [Action.create('text')])])
            workflow.connect(workflow.modules[0].id, workflow.modules[1].id)
            workflow.report = ReportConfig(terms=['Texte de test'])
            path = folder / 'workflow.json'
            save_workflow(path, workflow)
            restored = load_workflow(path)
            assert len(restored.modules) == 2 and restored.report.terms == ['Texte de test']
            window.set_document(restored)
            window.resize(960, 720)
            window.show()
            app.processEvents()
            assert window.tabs.count() == 5
            assert window.grab().save(str(folder / 'ui.png'))
            window.dirty = False
            window.close()
            result['checks'].append('interface, cinq onglets et sauvegarde JSON')
            launcher_dialog = launcher.LaunchDialog(launcher.DocumentLibrary(project_folder=folder))
            launcher_dialog.show()
            app.processEvents()
            assert launcher_dialog.files.count() == 1
            launcher_dialog.reject()
            result['checks'].append('menu de lancement')
            assert protect(protect(b'test-local'), decrypt=True) == b'test-local'
            WindowGuard().arm()
            DesktopBackend()  # Initialize native libraries, never send input.
            result['checks'].append('DPAPI, garde Windows et initialisation clavier/souris')
            assert cv2.matchTemplate(np.zeros((20, 20), np.uint8), np.ones((4, 4), np.uint8), cv2.TM_SQDIFF).shape == (17, 17)
            assert mss.MSS is not None
            result['checks'].append('OpenCV, NumPy et MSS')
            control = RunControl()
            assert execute([], object(), control, lambda text: None, countdown=0) == 'Terminé'
            image = QImage(1000, 160, QImage.Format_RGB32)
            image.fill(QColor('white'))
            painter = QPainter(image)
            painter.setPen(QColor('black'))
            painter.setFont(QFont('Arial', 32))
            painter.drawText(20, 90, 'Ajout de data a relever')
            painter.end()
            image.save(str(folder / 'ocr.png'))
            assert contains(read_png(folder / 'ocr.png'), 'Ajout de data a relever')
            result['checks'].append('OCR Windows local sur image synthétique')
        result['ok'] = True
    except Exception:
        result['error'] = traceback.format_exc()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1

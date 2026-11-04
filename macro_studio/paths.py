"""Writable user folders are separate from the installed application."""
from pathlib import Path
import sys
from PySide6.QtCore import QStandardPaths


def default_workflow_folder():
    if not getattr(sys, 'frozen', False):
        return Path(__file__).resolve().parent.parent
    documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
    documents = Path(documents or str(Path.home() / 'Documents'))
    legacy = documents / 'Windows Macro Studio' / 'Workflows'
    return legacy if legacy.is_dir() else documents / 'Macro Studio' / 'Workflows'


def prepare_workflow_folder():
    folder = default_workflow_folder()
    folder.mkdir(parents=True, exist_ok=True)
    return folder

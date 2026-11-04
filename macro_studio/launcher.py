"""Launch menu and local recent-document library."""
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
from PySide6.QtCore import Qt, QSettings, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QListWidget, QListWidgetItem, QLineEdit, QFileDialog, QInputDialog, QMessageBox)
from .ui_style import FlowLayout
from .paths import default_workflow_folder

PROJECT_FOLDER = default_workflow_folder()

def default_settings():
    return QSettings("WindowsMacroStudio", "Documents")

def document_filename(name):
    name = name.strip()
    stem = name[:-5] if name.lower().endswith(".json") else name
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if (not stem or stem in (".", "..") or stem.endswith((".", " "))
        or any(c in '<>:"/\\|?*' or ord(c) < 32 for c in name)
        or stem.split(".")[0].upper() in reserved):
        raise ValueError("Choisissez un nom de fichier valide, sans chemin ni caractères interdits par Windows.")
    filename = stem + ".json"
    if len(filename.encode("utf-16-le")) // 2 > 255:
        raise ValueError("Le nom du fichier est trop long.")
    return filename

def document_type(path):
    try:
        with Path(path).open("r", encoding="utf-8-sig") as handle:
            header = handle.read(4096)
        match = re.search(r'"version"\s*:\s*([12])\b', header)
        return {"1": "Séquence", "2": "Workflow"}.get(match.group(1)) if match else None
    except (OSError, UnicodeError):
        return None

@dataclass
class SavedDocument:
    path: str
    kind: str
    modified: float

class DocumentLibrary:
    def __init__(self, settings=None, project_folder=None):
        self.settings = settings if settings is not None else default_settings()
        self.project_folder = Path(project_folder) if project_folder else PROJECT_FOLDER

    def recent_paths(self):
        value = self.settings.value("recent", [])
        return [p for p in value if isinstance(p, str)] if isinstance(value, list) else []

    def remember(self, path):
        path = str(Path(path).resolve())
        key = os.path.normcase(path)
        recent = [p for p in self.recent_paths() if os.path.normcase(p) != key]
        self.settings.setValue("recent", [path, *recent][:50])
        self.settings.setValue("folder", str(Path(path).parent))
        self.settings.sync()

    def set_folder(self, path):
        self.settings.setValue("folder", str(Path(path).resolve()))
        self.settings.sync()

    def rename(self, path, name):
        source = Path(path).resolve()
        target = source.with_name(document_filename(name))
        if source.name == target.name:
            return str(source)
        if not source.is_file():
            raise FileNotFoundError("Ce fichier n’existe plus à cet emplacement.")
        if target.exists() and os.path.normcase(str(source)) != os.path.normcase(str(target)):
            raise FileExistsError("Un fichier porte déjà ce nom. Choisissez un autre nom.")
        source.rename(target)
        recent = [p for p in self.recent_paths() if os.path.normcase(p) != os.path.normcase(str(source))]
        self.settings.setValue("recent", recent)
        self.remember(target)
        return str(target)

    def documents(self):
        recent = self.recent_paths()
        candidates = list(recent)
        folder = self.settings.value("folder", str(self.project_folder))
        for directory in {self.project_folder, Path(folder) if isinstance(folder, str) else self.project_folder}:
            try:
                candidates.extend(str(p) for p in directory.glob("*.json"))
            except OSError:
                continue
        found = {}
        for candidate in candidates:
            path = Path(candidate).resolve()
            key = os.path.normcase(str(path))
            if key in found or not path.is_file():
                continue
            kind = document_type(path)
            if kind:
                try:
                    found[key] = SavedDocument(str(path), kind, path.stat().st_mtime)
                except OSError:
                    continue
        ranks = {os.path.normcase(p): i for i, p in enumerate(recent)}
        return sorted(found.values(), key=lambda d: (ranks.get(os.path.normcase(d.path), len(recent)), -d.modified))

class LaunchDialog(QDialog):
    renamed = Signal(str, str)
    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.library = library
        self.choice = None
        self.selected_path = None
        self.setWindowTitle("Windows Macro Studio — Accueil")
        self.resize(780, 590)
        layout = QVBoxLayout(self)
        title = QLabel("Ouvrir un workflow ou une séquence")
        title.setProperty('role', 'heading')
        title.setWordWrap(True)
        layout.addWidget(title)
        info = QLabel("Retrouvez vos fichiers enregistrés, ou créez un nouveau document.")
        info.setWordWrap(True)
        layout.addWidget(info)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher un fichier…")
        self.search.textChanged.connect(self.filter_documents)
        layout.addWidget(self.search)
        self.files = QListWidget()
        self.files.setObjectName("saved_documents")
        self.files.itemDoubleClicked.connect(lambda _: self.open_selected())
        self.files.currentItemChanged.connect(self.selection_changed)
        layout.addWidget(self.files, 1)
        self.location = QLabel()
        self.location.setWordWrap(True)
        layout.addWidget(self.location)
        self.rename_button = QPushButton("Renommer le fichier sélectionné…")
        self.rename_button.setObjectName("rename_saved_document")
        self.rename_button.clicked.connect(self.rename_selected)
        layout.addWidget(self.rename_button)
        row = FlowLayout()
        self.open_button = QPushButton("Ouvrir le fichier sélectionné")
        self.open_button.setObjectName("open_saved_document")
        self.open_button.clicked.connect(self.open_selected)
        row.addWidget(self.open_button)
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self.browse)
        row.addWidget(browse)
        folder = QPushButton("Choisir un dossier…")
        folder.clicked.connect(self.choose_folder)
        row.addWidget(folder)
        layout.addLayout(row)
        row = FlowLayout()
        for label, choice in (("Nouveau workflow", "new_workflow"), ("Nouvelle séquence", "new_sequence")):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, c=choice: self.create(c))
            row.addWidget(button)
        close = QPushButton("Fermer")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        layout.addLayout(row)
        self.refresh()

    def refresh(self):
        self.files.clear()
        for document in self.library.documents():
            date = datetime.fromtimestamp(document.modified).strftime("%d/%m/%Y %H:%M")
            item = QListWidgetItem(f"{Path(document.path).name}\n{document.kind} · Modifié le {date}")
            item.setData(Qt.UserRole, document.path)
            item.setToolTip(document.path)
            self.files.addItem(item)
        self.filter_documents(self.search.text())
        if not self.files.count():
            self.location.setText("Aucun fichier trouvé ici. Utilisez Parcourir ou Choisir un dossier.")
        self.open_button.setEnabled(self.files.currentItem() is not None)

    def filter_documents(self, text):
        query = text.casefold()
        for i in range(self.files.count()):
            item = self.files.item(i)
            item.setHidden(query not in (item.text() + item.data(Qt.UserRole)).casefold())
        if self.files.currentItem() is None or self.files.currentItem().isHidden():
            first = next((i for i in range(self.files.count()) if not self.files.item(i).isHidden()), -1)
            self.files.setCurrentRow(first)
        self.selection_changed(self.files.currentItem())

    def selection_changed(self, item, previous=None):
        enabled = item is not None and not item.isHidden()
        self.open_button.setEnabled(enabled)
        self.rename_button.setEnabled(enabled)
        self.location.setText(item.data(Qt.UserRole) if enabled else "Sélectionnez un fichier à ouvrir.")

    def rename_selected(self):
        item = self.files.currentItem()
        if item is None or item.isHidden():
            return
        old_path = item.data(Qt.UserRole)
        name, ok = QInputDialog.getText(self, "Renommer le fichier", "Nouveau nom :", text=Path(old_path).stem)
        if not ok:
            return
        try:
            new_path = self.library.rename(old_path, name)
            self.renamed.emit(old_path, new_path)
            self.search.clear()
            self.refresh()
            for i in range(self.files.count()):
                if self.files.item(i).data(Qt.UserRole) == new_path:
                    self.files.setCurrentRow(i)
                    break
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Renommage impossible", str(exc))

    def open_selected(self):
        item = self.files.currentItem()
        if item is not None and not item.isHidden():
            self.selected_path = item.data(Qt.UserRole)
            self.choice = "open"
            self.accept()

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir un workflow ou une séquence", "", "Workflow / Séquence JSON (*.json)")
        if path:
            self.selected_path, self.choice = path, "open"
            self.accept()

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Dossier des workflows et séquences")
        if path:
            self.library.set_folder(path)
            self.refresh()

    def create(self, choice):
        self.choice = choice
        self.accept()

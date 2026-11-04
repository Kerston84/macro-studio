import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox, QFileDialog
from macro_studio.launcher import DocumentLibrary, LaunchDialog, document_filename
from macro_studio.app import MainWindow
from macro_studio.model import Action, save, load
from macro_studio.workflow import Workflow, Module, save_workflow, load_workflow

app = QApplication.instance() or QApplication([])

def library(tmp_path):
    return DocumentLibrary(QSettings(str(tmp_path / "library.ini"), QSettings.IniFormat), tmp_path)

@pytest.mark.parametrize("name", ["", ".", "..", ".json", "../autre", "a/b", "a\\b", "a:b", "a?b", "CON", "nul.json", "LPT1", "fin."])
def test_invalid_windows_filenames(name):
    with pytest.raises(ValueError): document_filename(name)

def test_file_rename_preserves_bytes_and_recent_list(tmp_path):
    old = tmp_path / "avant.json"
    save(old, [Action.create("wait")], name="Ma séquence")
    original = old.read_bytes()
    store = library(tmp_path)
    store.remember(old)
    target = Path(store.rename(old, "Après été"))
    assert target.name == "Après été.json"
    assert not old.exists()
    assert target.read_bytes() == original
    assert store.recent_paths() == [str(target)]
    assert [Path(d.path).name for d in store.documents()] == ["Après été.json"]

def test_existing_filename_is_never_overwritten(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    save(a, [Action.create("wait")])
    save(b, [Action.create("text")])
    before = a.read_bytes(), b.read_bytes()
    with pytest.raises(FileExistsError): library(tmp_path).rename(a, "b")
    assert (a.read_bytes(), b.read_bytes()) == before

def test_case_only_file_rename(tmp_path):
    old = tmp_path / "avant.json"
    save(old, [])
    target = library(tmp_path).rename(old, "Avant")
    assert Path(target).name == "Avant.json"
    assert "Avant.json" in [p.name for p in tmp_path.glob("*.json")]

def test_launcher_rename_refreshes_selection_and_updates_current_path(tmp_path, monkeypatch):
    old = tmp_path / "avant.json"
    save_workflow(old, Workflow())
    window = MainWindow()
    window.open_path(str(old))
    dialog = LaunchDialog(window.library_store)
    dialog.renamed.connect(window.document_renamed)
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("après", True))
    dialog.rename_selected()
    new = tmp_path / "après.json"
    assert window.path == str(new)
    assert dialog.files.currentItem().data(256) == str(new)
    window.add_action("wait")
    assert window.save_file()
    assert not old.exists()
    assert len(load_workflow(new).modules[0].actions) == 1
    dialog.close()
    window.dirty = False
    window.close()

def test_editor_sequence_name_persists_in_sequence_and_workflow(tmp_path, monkeypatch):
    old = tmp_path / "sequence.json"
    save(old, [Action.create("wait")])
    window = MainWindow()
    window.open_path(str(old))
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Ma séquence renommée", True))
    window.rename_sequence()
    assert window.module_selector.currentText() == "Ma séquence renommée"
    assert window.dirty
    assert window.save_file()
    assert load_workflow(old).modules[0].name == "Ma séquence renommée"
    assert load(old) == [Action.create("wait")]
    window.document_format = "workflow"
    assert window.save_file()
    assert load_workflow(old).modules[0].name == "Ma séquence renommée"
    window.close()

def test_rename_open_file_keeps_unsaved_actions_and_save_target(tmp_path, monkeypatch):
    old = tmp_path / "avant.json"
    save_workflow(old, Workflow())
    window = MainWindow()
    window.open_path(str(old))
    window.add_action("text")
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("après", True))
    window.rename_current_file()
    assert window.dirty
    assert len(window.actions) == 1
    assert window.path == str(tmp_path / "après.json")
    assert window.save_file()
    assert len(load_workflow(window.path).modules[0].actions) == 1
    assert not old.exists()
    window.close()

def test_cancel_and_invalid_module_name_do_not_change_document(monkeypatch):
    window = MainWindow()
    name = window.workflow.modules[0].name
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("autre", False))
    window.rename_sequence()
    assert window.workflow.modules[0].name == name and not window.dirty
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("", True))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    window.rename_sequence()
    assert window.workflow.modules[0].name == name and not window.dirty
    window.close()

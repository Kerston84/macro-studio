import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QDialog
from macro_studio.launcher import DocumentLibrary, LaunchDialog, document_type
from macro_studio.app import MainWindow
from macro_studio.workflow import Module, Workflow, save_workflow, load_workflow
from macro_studio.model import Action, save, load

app = QApplication.instance() or QApplication([])

def library(tmp_path):
    return DocumentLibrary(QSettings(str(tmp_path / "library.ini"), QSettings.IniFormat), tmp_path)

def test_discover_workflows_and_sequences_without_opening_them(tmp_path):
    save_workflow(tmp_path / "Mon workflow.json", Workflow())
    save(tmp_path / "Ma séquence.json", [Action.create("wait")])
    (tmp_path / "autre.json").write_text('{"autre": 1}')
    files = library(tmp_path).documents()
    assert {f.kind for f in files} == {"Workflow", "Séquence"}
    assert len(files) == 2

def test_recent_files_persist_and_are_deduplicated(tmp_path):
    outside = tmp_path / "ailleurs"
    outside.mkdir()
    path = outside / "workflow.json"
    save_workflow(path, Workflow())
    store = library(tmp_path)
    store.remember(path)
    store.remember(path)
    reopened = library(tmp_path)
    assert reopened.recent_paths() == [str(path.resolve())]
    assert [d.path for d in reopened.documents()] == [str(path.resolve())]
    path.unlink()
    assert reopened.documents() == []

def test_launcher_search_selects_visible_result(tmp_path):
    save_workflow(tmp_path / "Alpha.json", Workflow())
    path = tmp_path / "Bravo.json"
    save(path, [Action.create("wait")])
    dialog = LaunchDialog(library(tmp_path))
    dialog.search.setText("bravo")
    assert dialog.open_button.isEnabled()
    dialog.open_selected()
    assert dialog.result() == QDialog.Accepted
    assert dialog.choice == "open"
    assert dialog.selected_path == str(path.resolve())

def test_launcher_empty_and_new_document(tmp_path):
    dialog = LaunchDialog(library(tmp_path))
    assert not dialog.open_button.isEnabled()
    dialog.create("new_sequence")
    assert dialog.choice == "new_sequence"

def test_save_normal_uses_opened_path_without_dialog(tmp_path, monkeypatch):
    path = tmp_path / "mon workflow.json"
    save_workflow(path, Workflow())
    window = MainWindow()
    assert window.open_path(str(path))
    window.add_action("wait")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (_ for _ in ()).throw(AssertionError("Dialogue Enregistrer sous inattendu")))
    assert window.save_file()
    assert len(load_workflow(path).modules[0].actions) == 1
    assert not window.dirty
    assert "mon workflow.json" in window.file_label.text()
    assert "Enregistré" in window.file_label.text()
    window.close()

def test_first_save_prompts_once_then_ctrl_s_updates_same_file(tmp_path, monkeypatch):
    window = MainWindow()
    window.add_action("wait")
    path = tmp_path / "nouveau.json"
    prompts = []
    def choose(*args):
        prompts.append(True)
        return str(path), ""
    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    assert window.save_file()
    window.add_action("text")
    window.show()
    window.activateWindow()
    app.processEvents()
    QTest.keyClick(window, Qt.Key_S, Qt.ControlModifier)
    app.processEvents()
    assert prompts == [True]
    assert len(load_workflow(path).modules[0].actions) == 2
    assert not window.dirty
    window.close()

def test_sequence_normal_save_keeps_sequence_format(tmp_path, monkeypatch):
    path = tmp_path / "sequence.json"
    save(path, [Action.create("wait")])
    window = MainWindow()
    assert window.open_path(str(path))
    assert window.tabs.currentIndex() == 0
    window.add_action("keyboard")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (_ for _ in ()).throw(AssertionError("Dialogue inattendu")))
    assert window.save_file()
    assert len(load(path)) == 2
    assert document_type(path) == "Séquence"
    window.close()

def test_sequence_with_multiple_modules_saves_complete_workflow(tmp_path):
    path = tmp_path / "sequence.json"
    save(path, [Action.create("wait")])
    window = MainWindow()
    window.open_path(str(path))
    window.workflow_panel.insert(Module("Autre", [Action.create("text")]))
    assert window.save_file()
    assert len(load_workflow(path).modules) == 2
    assert window.document_format == "workflow"
    window.close()

def test_launcher_opens_selected_file_and_associates_save_path(tmp_path):
    path = tmp_path / "saved.json"
    save_workflow(path, Workflow())
    window = MainWindow()
    def choose():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, LaunchDialog)
        QTimer.singleShot(500, dialog.reject)
        dialog.selected_path, dialog.choice = str(path), "open"
        dialog.accept()
    QTimer.singleShot(0, choose)
    assert window.show_launcher(initial=True)
    assert window.path == str(path.resolve())
    window.close()

def test_launcher_new_sequence_starts_in_editor():
    window = MainWindow()
    QTimer.singleShot(0, lambda: app.activeModalWidget().create("new_sequence"))
    assert window.show_launcher(initial=True)
    assert window.document_format == "sequence"
    assert window.path is None
    assert window.tabs.currentIndex() == 0
    window.close()

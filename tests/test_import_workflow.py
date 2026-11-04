import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import copy
import pytest
from PySide6.QtWidgets import QApplication, QFileDialog
from macro_studio.app import MainWindow
from macro_studio.model import Action
from macro_studio.workflow import Module, Workflow, save_workflow, load_workflow

app = QApplication.instance() or QApplication([])

def source():
    a = Module("Connexion", [Action.create("keyboard")], x=100, y=150, repeat=10)
    b = Module("Déconnexion", [Action.create("wait")], x=500, y=220, repeat=2)
    workflow = Workflow([a, b])
    workflow.connect(a.id, b.id)
    return workflow

def test_two_module_import_and_save_on_blank_board(tmp_path, monkeypatch):
    path = tmp_path / "deux_modules.json"
    save_workflow(path, source())
    before = path.read_bytes()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    window = MainWindow()
    window.workflow_panel.import_module()
    assert len(window.workflow.modules) == 2
    a, b = window.workflow.modules
    assert (a.name, b.name) == ("Connexion", "Déconnexion")
    assert (a.repeat, b.repeat) == (10, 2)
    assert a.next_id == b.id and window.workflow.entry == a.id
    assert [(m.x, m.y) for m in window.workflow.modules] == [(100, 150), (500, 220)]
    assert len(a.actions) == len(b.actions) == 1
    assert window.actions is a.actions
    assert path.read_bytes() == before
    window.path = str(tmp_path / "copie.json")
    assert window.save_file()
    assert len(load_workflow(window.path).modules) == 2
    window.dirty = False
    window.close()

def test_append_preserves_current_graph_and_relative_positions():
    target = source()
    old, old_entry = list(target.modules), target.entry
    imported, entry = target.import_modules(source())
    assert target.modules[:2] == old and target.entry == old_entry
    assert len(target.modules) == 4
    assert imported[0].next_id == imported[1].id
    assert imported[1].x - imported[0].x == 400
    assert imported[1].y - imported[0].y == 70
    assert imported[0].x > max(m.x + 260 for m in old)
    assert entry == imported[0].id

def test_repeated_import_remaps_ids_and_does_not_share_actions():
    original, target = source(), Workflow()
    a, _ = target.import_modules(original, replace_empty=True)
    b, _ = target.import_modules(original)
    assert len({m.id for m in target.modules}) == 4
    assert a[0].next_id == a[1].id and b[0].next_id == b[1].id
    a[0].actions[0].params["keys"] = "enter"
    assert b[0].actions[0].params["keys"] == "ctrl+a"
    assert original.modules[0].actions[0].params["keys"] == "ctrl+a"

def test_disconnected_modules_and_nonfirst_entry_are_preserved():
    original = source()
    original.entry = original.modules[1].id
    original.modules.append(Module("Réserve", [Action.create("text")], repeat=3))
    target = Workflow()
    modules, entry = target.import_modules(original, replace_empty=True)
    assert len(modules) == 3
    assert target.entry == entry == modules[1].id
    assert modules[2].name == "Réserve" and modules[2].repeat == 3

def test_import_is_not_limited_to_500_modules():
    target = Workflow([Module() for _ in range(499)])
    target.import_modules(source())
    assert len(target.modules) == 501
    target.validate()

def test_invalid_source_is_not_partially_imported():
    target, incoming = source(), source()
    before = copy.deepcopy(target)
    incoming.modules[0].next_id = "inexistant"
    with pytest.raises(ValueError):
        target.import_modules(incoming)
    assert target == before

def test_ui_import_adds_to_existing_module(tmp_path, monkeypatch):
    path = tmp_path / "deux_modules.json"
    save_workflow(path, source())
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    window = MainWindow()
    window.add_action("text")
    first = window.workflow.modules[0]
    window.workflow_panel.import_module()
    assert len(window.workflow.modules) == 3
    assert window.workflow.modules[0] is first and len(first.actions) == 1
    assert window.workflow.entry == first.id
    window.dirty = False
    window.close()

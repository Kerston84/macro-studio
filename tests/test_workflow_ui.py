import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox
from PySide6.QtCore import Qt, QPointF
from PySide6.QtTest import QTest
from macro_studio.app import MainWindow
from macro_studio.workflow import Module, Workflow, load_workflow
from macro_studio.model import Action, load

app = QApplication.instance() or QApplication([])

def close(window):
    window.dirty = False
    window.close()

def test_switch_modules_keeps_edited_actions():
    window = MainWindow()
    window.add_action("text")
    first = window.workflow.modules[0]
    second = Module("Deuxième")
    window.workflow_panel.insert(second)
    window.edit_module(second.id)
    window.add_action("wait")
    window.edit_module(first.id)
    assert window.actions is first.actions
    assert [a.kind for a in first.actions] == ["text"]
    assert [a.kind for a in second.actions] == ["wait"]
    close(window)

def test_canvas_connect_move_and_cycle():
    window = MainWindow()
    a = window.workflow.modules[0]
    b = Module("Après", x=450, y=80)
    window.workflow_panel.insert(b)
    canvas = window.workflow_panel.canvas
    canvas.port_clicked(a.id, True)
    canvas.port_clicked(b.id, False)
    assert a.next_id == b.id
    old_path = canvas.edges[0][2].path().boundingRect()
    canvas.nodes[b.id].setPos(620, 300)
    assert (b.x, b.y) == (620, 300)
    assert old_path != canvas.edges[0][2].path().boundingRect()
    canvas.port_clicked(b.id, True)
    canvas.port_clicked(a.id, False)
    assert b.next_id == a.id
    assert window.workflow_panel.loop_editor.isEnabled()
    assert "boucle" in window.workflow_panel.hint.text().lower()
    assert window.dirty
    close(window)

def test_workflow_save_and_sequence_export(tmp_path, monkeypatch):
    window = MainWindow()
    window.add_action("wait")
    window.workflow_panel.insert(Module("Suite", [Action.create("text")]))
    path = tmp_path / "flow.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    assert window.save_file()
    assert len(load_workflow(path).modules) == 2
    assert not window.dirty
    export = tmp_path / "seulement.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(export), ""))
    window.export_sequence()
    assert load(export) == window.actions
    assert load_workflow(path).modules[1].name == "Suite"
    close(window)

def test_delete_current_module_and_reset(monkeypatch):
    window = MainWindow()
    first = window.workflow.modules[0]
    second = Module("Suite")
    window.workflow_panel.insert(second)
    window.edit_module(second.id)
    canvas = window.workflow_panel.canvas
    canvas.scene().clearSelection()
    canvas.nodes[second.id].setSelected(True)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    window.workflow_panel.remove()
    assert window.current_module == first.id
    assert window.actions is first.actions
    window.dirty = False
    window.new()
    assert len(window.workflow.modules) == 1
    assert window.actions == []
    close(window)

def test_running_disables_workflow_and_progress_selects_module():
    window = MainWindow()
    second = Module("Suite", [Action.create("wait")])
    window.workflow_panel.insert(second)
    window.run_mapping = [(second.id, 0, 1)]
    window.set_running(True)
    assert not window.workflow_panel.isEnabled()
    assert not window.module_selector.isEnabled()
    window.execution_progress(0)
    assert window.current_module == second.id
    assert window.workflow_panel.canvas.active_id == second.id
    assert window.sequence.currentRow() == 0
    window.set_running(False)
    close(window)

def test_real_port_clicks_and_double_click_edit():
    window = MainWindow()
    a = window.workflow.modules[0]
    b = Module("Suite", x=480, y=80)
    window.workflow.modules.append(b)
    window.refresh_modules()
    window.show()
    window.tabs.setCurrentIndex(1)
    app.processEvents()
    canvas = window.workflow_panel.canvas
    canvas.fit_nodes()
    for identifier, offset in ((a.id, QPointF(260, 69)), (b.id, QPointF(0, 69))):
        point = canvas.mapFromScene(canvas.nodes[identifier].pos() + offset)
        QTest.mouseClick(canvas.viewport(), Qt.LeftButton, pos=point)
        app.processEvents()
    assert a.next_id == b.id
    point = canvas.mapFromScene(canvas.nodes[b.id].pos() + QPointF(130, 20))
    QTest.mouseDClick(canvas.viewport(), Qt.LeftButton, pos=point)
    app.processEvents()
    assert window.tabs.currentIndex() == 0
    assert window.current_module == b.id
    close(window)

def test_import_existing_sequence(tmp_path, monkeypatch):
    from macro_studio.model import save
    path = tmp_path / "Mon ancienne séquence.json"
    save(path, [Action.create("text")])
    before = path.read_bytes()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    window = MainWindow()
    window.workflow_panel.import_module()
    assert len(window.workflow.modules) == 1
    imported = window.workflow.modules[0]
    assert imported.actions == [Action.create("text")]
    assert imported.name == "Mon ancienne séquence"
    assert path.read_bytes() == before
    close(window)

def test_repeat_control_duplicate_and_progress():
    window = MainWindow()
    window.add_action("wait")
    panel = window.workflow_panel
    canvas = panel.canvas
    module = window.workflow.modules[0]
    canvas.nodes[module.id].setSelected(True)
    canvas.nodes[module.id].repeat_editor.setValue(10)
    assert module.repeat == 10
    assert window.dirty
    panel.duplicate()
    duplicate = window.workflow.modules[1]
    assert duplicate.repeat == 10
    assert duplicate.actions == module.actions
    duplicate.actions[0].params["seconds"] = 2
    assert module.actions[0].params["seconds"] == 1
    window.run_mapping = [(module.id, 0, 1), (module.id, 0, 2)]
    window.execution_progress(0)
    window.execution_progress(1)
    assert canvas.active_repeat == 2
    journal = window.journal.toPlainText()
    assert "répétition 1/10" in journal
    assert "répétition 2/10" in journal
    close(window)

def test_repeat_inputs_on_cards_are_independent_and_persist(tmp_path):
    window = MainWindow()
    first = window.workflow.modules[0]
    second = Module("Module suivant")
    window.workflow_panel.insert(second)
    canvas = window.workflow_panel.canvas
    canvas.nodes[first.id].repeat_editor.setValue(10)
    canvas.nodes[second.id].repeat_editor.setValue(3)
    assert (first.repeat, second.repeat) == (10, 3)
    window.workflow.connect(first.id, second.id)
    window.path = str(tmp_path / "modules.json")
    assert window.save_file()
    loaded = load_workflow(window.path)
    assert [m.repeat for m in loaded.modules] == [10, 3]
    assert loaded.modules[0].next_id == loaded.modules[1].id
    window.set_document(loaded, window.path)
    assert window.workflow_panel.canvas.nodes[first.id].repeat_editor.value() == 10
    assert window.workflow_panel.canvas.nodes[second.id].repeat_editor.value() == 3
    close(window)

def test_save_as_creates_copy_and_cancellation_keeps_document(tmp_path, monkeypatch):
    window = MainWindow()
    window.add_action("wait")
    original = tmp_path / "original.json"
    window.path = str(original)
    assert window.save_file()
    original_bytes = original.read_bytes()
    module = window.workflow.modules[0]
    window.workflow_panel.canvas.nodes[module.id].repeat_editor.setValue(10)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    assert window.save_as() is False
    assert window.path == str(original)
    assert window.dirty
    target = tmp_path / "copie"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    assert window.save_as()
    assert window.path == str(target) + ".json"
    assert load_workflow(window.path).modules[0].repeat == 10
    assert original.read_bytes() == original_bytes
    assert not window.dirty
    close(window)

def test_save_as_write_failure_keeps_current_path(tmp_path, monkeypatch):
    import macro_studio.app as app_module
    window = MainWindow()
    window.path = str(tmp_path / "old.json")
    window.changed()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(tmp_path / "new.json"), ""))
    monkeypatch.setattr(app_module, "save_workflow", lambda *args: (_ for _ in ()).throw(OSError("Écriture refusée")))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    assert window.save_as() is False
    assert window.path == str(tmp_path / "old.json")
    assert window.dirty
    close(window)

def test_repeat_widget_accepts_keyboard_inside_canvas():
    window = MainWindow()
    window.show()
    window.tabs.setCurrentIndex(1)
    app.processEvents()
    module = window.workflow.modules[0]
    editor = window.workflow_panel.canvas.nodes[module.id].repeat_editor
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClicks(editor, "10")
    QTest.keyClick(editor, Qt.Key_Return)
    assert module.repeat == 10
    assert window.tabs.currentIndex() == 1
    close(window)

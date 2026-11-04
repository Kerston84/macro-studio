import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication
from macro_studio.model import Action
from macro_studio.workflow import Module, Workflow, save_workflow, load_workflow
from macro_studio.workflow_view import Canvas

app = QApplication.instance() or QApplication([])

def make_workflow(count, text_size=0):
    modules = [Module(name=f"Module {i}", id=f"module-{i}", x=(i % 100) * 400, y=(i // 100) * 260,
                      actions=[Action("text", {"text": f"Action {i} " + "x" * text_size})], repeat=i % 5 + 1)
               for i in range(count)]
    for a, b in zip(modules, modules[1:]):
        a.next_id = b.id
    return Workflow(modules)

@pytest.mark.parametrize("count", [2, 37, 13000])
def test_save_load_and_import_keep_every_module(count, tmp_path):
    original = make_workflow(count, text_size=800 if count == 13000 else 0)
    path = tmp_path / "workflow.json"
    save_workflow(path, original)
    if count == 13000:
        assert path.stat().st_size > 10_000_000
    restored = load_workflow(path)
    assert restored == original
    destination = Workflow()
    imported, entry = destination.import_modules(restored, replace_empty=True)
    assert len(imported) == count
    assert len(destination.modules) == count
    assert destination.entry == entry == imported[0].id
    assert len({m.id for m in imported}) == count
    for i, module in enumerate(imported):
        source = original.modules[i]
        assert (module.name, module.actions, module.repeat, module.x, module.y) == (
            source.name, source.actions, source.repeat, source.x, source.y)
        assert module.next_id == (imported[i + 1].id if i + 1 < count else None)
    assert len(destination.chain()) == count

def test_canvas_handles_13000_nodes_without_13000_editors():
    workflow = make_workflow(13000)
    canvas = Canvas(workflow)
    canvas.resize(1200, 650)
    canvas.show()
    canvas.fit_nodes()
    app.processEvents()
    assert len(canvas.nodes) == 13000
    assert len(canvas.edges) == 12999
    assert all(n.repeat_editor is None for n in canvas.nodes.values())
    last = workflow.modules[-1]
    node = canvas.nodes[last.id]
    node.setSelected(True)
    assert node.repeat_editor is not None
    node.repeat_editor.setValue(10)
    assert last.repeat == 10
    count_editors = sum(n.repeat_editor is not None for n in canvas.nodes.values())
    assert count_editors == 1
    canvas.rebuild()
    assert canvas.nodes[last.id] is node
    assert canvas.sceneRect().contains(node.sceneBoundingRect())
    canvas.close()

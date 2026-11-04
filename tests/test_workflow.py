import copy
import json
import threading
import pytest
from macro_studio.model import Action, save
from macro_studio.workflow import Module, Workflow, save_workflow, load_workflow
from macro_studio.engine import execute
from test_engine import FakeBackend

def sample():
    a = Module("Ouvrir", [Action("text", {"text": "A"})], x=120, y=100)
    b = Module("Valider", [Action("text", {"text": "B"})], x=520, y=250)
    c = Module("Réserve", [Action("text", {"text": "C"})])
    workflow = Workflow([a, b, c])
    workflow.connect(a.id, b.id)
    return workflow

def test_link_order_and_parked_modules():
    workflow = sample()
    actions, mapping = workflow.compile()
    backend = FakeBackend()
    assert execute(actions, backend, threading.Event(), lambda _: None, countdown=0) == "Terminé"
    assert backend.calls == [("text", "A"), ("text", "B")]
    assert mapping == [(workflow.modules[0].id, 0, 1), (workflow.modules[1].id, 0, 1)]
    workflow.entry = workflow.modules[1].id
    assert [m.name for m in workflow.chain()] == ["Valider"]

def test_close_cycle_and_preserve_link_on_invalid_double_input():
    workflow = sample()
    a, b, _ = workflow.modules
    workflow.connect(b.id, a.id)
    assert b.next_id == a.id
    assert workflow.is_loop() and workflow.chain() == [a, b]
    with pytest.raises(ValueError):
        workflow.connect(a.id, a.id)
    assert a.next_id == b.id

def test_no_double_input():
    workflow = sample()
    a, b, c = workflow.modules
    with pytest.raises(ValueError, match="entrée"):
        workflow.connect(c.id, b.id)
    assert c.next_id is None

def test_workflow_roundtrip(tmp_path):
    workflow = sample()
    path = tmp_path / "workflow.json"
    save_workflow(path, workflow)
    restored = load_workflow(path)
    assert restored == workflow
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 2

def test_legacy_import_keeps_actions_and_original(tmp_path):
    path = tmp_path / "ancienne.json"
    actions = [Action.create("wait"), Action.create("keyboard")]
    save(path, actions)
    before = path.read_bytes()
    workflow = load_workflow(path)
    assert workflow.modules[0].actions == actions
    assert workflow.modules[0].name == "ancienne"
    assert path.read_bytes() == before

@pytest.mark.parametrize("change", ["duplicate_id", "missing_target", "double_input_parked", "nan", "entry", "name"])
def test_invalid_graph(change):
    workflow = sample()
    a, b, c = workflow.modules
    if change == "duplicate_id": c.id = a.id
    if change == "missing_target": b.next_id = "absent"
    if change == "double_input_parked": c.next_id = b.id
    if change == "nan": a.x = float("nan")
    if change == "entry": workflow.entry = "absent"
    if change == "name": a.name = ""
    with pytest.raises(ValueError):
        workflow.validate()

def test_invalid_load_and_atomic_preservation(tmp_path):
    path = tmp_path / "flow.json"
    workflow = sample()
    save_workflow(path, workflow)
    before = path.read_bytes()
    workflow.modules[0].next_id = "absent"
    with pytest.raises(ValueError):
        save_workflow(path, workflow)
    assert path.read_bytes() == before
    data = json.loads(before)
    data["modules"][0]["actions"] = "invalid"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_workflow(path)

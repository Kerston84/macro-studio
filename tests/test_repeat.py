import json
import threading
import pytest
from macro_studio.model import Action
from macro_studio.workflow import Module, Workflow, save_workflow, load_workflow
from macro_studio.engine import execute
from test_engine import FakeBackend

def repeated_workflow():
    first = Module("À répéter", [Action("text", {"text": "A"}), Action("text", {"text": "B"})], repeat=10)
    last = Module("Suite", [Action("text", {"text": "C"})], repeat=2)
    workflow = Workflow([first, last])
    workflow.connect(first.id, last.id)
    return workflow

def test_ten_module_repeats_before_next_module():
    workflow = repeated_workflow()
    actions, mapping = workflow.compile()
    backend = FakeBackend()
    assert execute(actions, backend, threading.Event(), lambda _: None, countdown=0) == "Terminé"
    assert [value for _, value in backend.calls] == ["A", "B"] * 10 + ["C"] * 2
    first, last = workflow.modules
    assert mapping[:4] == [(first.id, 0, 1), (first.id, 1, 1), (first.id, 0, 2), (first.id, 1, 2)]
    assert mapping[-2:] == [(last.id, 0, 1), (last.id, 0, 2)]

def test_current_module_only_respects_repeat():
    workflow = repeated_workflow()
    actions, mapping = workflow.compile(module_id=workflow.modules[1].id)
    assert [a.params["text"] for a in actions] == ["C", "C"]

def test_stop_mid_repeat_skips_remaining_iterations_and_next_module():
    workflow = repeated_workflow()
    actions, _ = workflow.compile()
    stop = threading.Event()
    class Backend(FakeBackend):
        def type_text(self, text, event):
            super().type_text(text, event)
            if len(self.calls) == 3:
                event.set()
    backend = Backend()
    assert execute(actions, backend, stop, lambda _: None, countdown=0) == "Arrêté"
    assert [text for _, text in backend.calls] == ["A", "B", "A"]

def test_error_stops_repeats():
    workflow = repeated_workflow()
    actions, _ = workflow.compile()
    class Backend(FakeBackend):
        def type_text(self, text, stop):
            super().type_text(text, stop)
            if len(self.calls) == 3:
                raise RuntimeError("Erreur de saisie")
    backend = Backend()
    with pytest.raises(RuntimeError):
        execute(actions, backend, threading.Event(), lambda _: None, countdown=0)
    assert len(backend.calls) == 3

@pytest.mark.parametrize("count", [0, -1, 1001, True, 1.5, "10", None])
def test_invalid_repeat(count):
    workflow = Workflow([Module(repeat=count)])
    with pytest.raises(ValueError, match="répétitions"):
        workflow.compile()

def test_repeat_roundtrip_and_legacy_default(tmp_path):
    workflow = repeated_workflow()
    path = tmp_path / "repetitions.json"
    save_workflow(path, workflow)
    assert load_workflow(path) == workflow
    data = json.loads(path.read_text(encoding="utf-8"))
    for module in data["modules"]:
        del module["repeat"]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert [m.repeat for m in load_workflow(path).modules] == [1, 1]

def test_expansion_limit_before_allocation():
    workflow = Workflow([Module(actions=[Action.create("wait")] * 101, repeat=1000)])
    with pytest.raises(ValueError, match="100 000"):
        workflow.compile()

def test_empty_module_repeat_does_not_skip_next_module():
    a = Module(repeat=1000)
    b = Module(actions=[Action.create("wait")])
    workflow = Workflow([a, b])
    workflow.connect(a.id, b.id)
    actions, mapping = workflow.compile()
    assert len(actions) == 1
    assert mapping == [(b.id, 0, 1)]

import json
import threading
import pytest
from test_vision import sample
from macro_studio.workflow import Workflow, Module, save_workflow, load_workflow
from macro_studio.model import Action
from macro_studio.engine import execute
from macro_studio.run_control import RunControl
from macro_studio.app import MainWindow
from test_engine import FakeBackend
from test_ui import app


def loop():
    a = Module('A', [Action('text', {'text': 'A'})], repeat=2)
    b = Module('B', [Action('text', {'text': 'B'})])
    workflow = Workflow([a, b])
    workflow.connect(a.id, b.id)
    workflow.connect(b.id, a.id)
    return workflow


def test_ring_compiles_one_pass_even_with_many_rounds():
    workflow = loop()
    workflow.loop_count = 10000
    actions, mapping = workflow.compile()
    assert len(actions) == len(mapping) == 3
    assert [a.params['text'] for a in actions] == ['A', 'A', 'B']
    assert len(workflow.chain()) == 2 and workflow.is_loop()


def test_engine_repeats_complete_pass_and_preserves_module_repeats():
    workflow = loop()
    actions, _ = workflow.compile()
    backend, cycles = FakeBackend(), []
    assert execute(actions, backend, threading.Event(), lambda _: None, countdown=0,
                   cycles=3, cycle_progress=lambda n, total: cycles.append((n, total))) == 'Terminé'
    assert backend.calls == [('text', 'A'), ('text', 'A'), ('text', 'B')] * 3
    assert cycles == [(1, 3), (2, 3), (3, 3)]


def test_infinite_loop_stops_and_arms_only_once():
    control = RunControl()
    arms = []
    original = control.arm
    control.arm = lambda: (arms.append(True), original())
    class Backend(FakeBackend):
        def type_text(self, text, stop):
            super().type_text(text, stop)
            if len(self.calls) == 7: stop.set()
    backend = Backend()
    actions, _ = loop().compile()
    result = execute(actions, backend, control, lambda _: None, countdown=0, cycles=0)
    assert result == 'Arrêté' and len(backend.calls) == 7 and arms == [True]


def test_empty_infinite_plan_exits_without_spinning():
    assert execute([], FakeBackend(), threading.Event(), lambda _: None, countdown=0, cycles=0) == 'Terminé'


def test_pause_between_rounds_does_not_replay_completed_round():
    control, paused = RunControl(), threading.Event()
    backend, result = FakeBackend(), []
    actions, _ = loop().compile()
    def cycle(n, total):
        if n == 2:
            control.pause()
            paused.set()
    thread = threading.Thread(target=lambda: result.append(execute(actions, backend, control, lambda _: None,
        countdown=0, cycles=2, cycle_progress=cycle)))
    thread.start()
    try:
        assert paused.wait(1)
        assert len(backend.calls) == 3
        control.resume()
        thread.join(1)
        assert result == ['Terminé'] and len(backend.calls) == 6
    finally:
        control.set()
        thread.join(1)


def test_popup_intervention_budget_is_shared_between_rounds(sample, monkeypatch):
    import macro_studio.popups as popups
    from test_popups import Stop, Backend
    stop = Stop()
    class Reappearing(Backend):
        def type_text(self, text, token):
            self.visible = True
            stop.now += 1
    backend = Reappearing(sample[0])
    mode = popups.PopupMode(True, [popups.PopupRule(image=sample[1], cooldown=.5, max_triggers=2)])
    original, monitors = popups.PopupMonitor, []
    def factory(*args):
        monitor = original(*args, clock=lambda: stop.now)
        monitors.append(monitor)
        return monitor
    monkeypatch.setattr(popups, 'PopupMonitor', factory)
    with pytest.raises(RuntimeError):
        execute([Action('text', {'text': 'test'})], backend, stop, lambda _: None, countdown=0, cycles=5, popup_mode=mode)
    assert len(monitors) == 1 and monitors[0].counts[mode.rules[0].id] == 2


def test_round_trip_and_import_preserve_return_link(tmp_path):
    workflow = loop()
    workflow.loop_count = 0
    path = tmp_path/'loop.json'
    save_workflow(path, workflow)
    restored = load_workflow(path)
    assert restored.is_loop() and restored.loop_count == 0
    target = Workflow()
    target.import_modules(restored, replace_empty=True)
    assert target.is_loop() and target.loop_count == 0
    assert target.chain()[-1].next_id == target.entry


@pytest.mark.parametrize('value', [-1, 10001, True, 1.5, '2'])
def test_invalid_round_count_rejected(value):
    workflow = loop()
    workflow.loop_count = value
    with pytest.raises(ValueError): workflow.validate()


def test_parked_ring_not_run_and_disconnect_restores_linear_path():
    workflow = loop()
    parked = Module('Réserve', [Action('text', {'text': 'X'})])
    parked.next_id = parked.id
    workflow.modules.append(parked)
    assert [m.name for m in workflow.chain()] == ['A', 'B']
    workflow.chain()[-1].next_id = None
    assert not workflow.is_loop() and len(workflow.compile()[0]) == 3


def test_single_module_loop_and_return_edge_controls():
    window = MainWindow()
    module = window.workflow.modules[0]
    canvas = window.workflow_panel.canvas
    canvas.port_clicked(module.id, True)
    canvas.port_clicked(module.id, False)
    assert window.workflow.is_loop()
    assert window.workflow_panel.loop_editor.isEnabled()
    window.workflow_panel.loop_editor.setValue(0)
    assert window.workflow.loop_count == 0 and window.dirty
    edge = canvas.edges[0][2]
    assert 'F8' in edge.toolTip()
    assert edge.path().boundingRect().height() > 50
    window.dirty = False
    window.close()


def test_widget_progress_includes_workflow_round():
    window = MainWindow()
    workflow = loop()
    window.set_document(workflow)
    actions, window.run_mapping = workflow.compile()
    window.run_cycles = 3
    window.run_widget.begin(RunControl(), len(actions) * 3)
    window.execution_cycle(2, 3)
    window.execution_progress(0)
    assert 'Tour 2/3' in window.run_widget.details.text()
    assert window.run_widget.progress.value() == 4
    window.run_widget.finish('Terminé')
    window.close()

import base64
import copy
import json
import threading
import cv2
import numpy as np
import pytest
from macro_studio.conditions import ImageCondition, load_condition, wait_for_condition
from macro_studio.workflow import Workflow, Module, save_workflow, load_workflow
from macro_studio.model import Action
from macro_studio.engine import execute
from macro_studio.app import MainWindow, Worker
from test_engine import FakeBackend
from test_ui import app


def reference():
    pixels = np.random.default_rng(88).integers(0, 255, (24, 32, 3), dtype=np.uint8)
    return ImageCondition(base64.b64encode(cv2.imencode('.png', pixels)[1]).decode(), 'depart.png'), pixels


def planned():
    condition, pixels = reference()
    a = Module('A', [Action('text', {'text': 'A'})], repeat=2, condition=copy.deepcopy(condition))
    b = Module('B', [Action('text', {'text': 'B'})])
    c = Module('C', [Action('text', {'text': 'C'})], condition=copy.deepcopy(condition))
    workflow = Workflow([a, b, c])
    workflow.connect(a.id, b.id)
    workflow.connect(b.id, c.id)
    return workflow, pixels


def test_no_image_has_no_wait_or_capture():
    assert wait_for_condition(ImageCondition(), threading.Event(), lambda: pytest.fail('Capture inattendue'))
    workflow = Workflow([Module('A', [Action('text', {'text': 'A'})])])
    actions, mapping = workflow.compile()
    assert workflow.conditions(mapping) == {}
    assert execute(actions, FakeBackend(), threading.Event(), lambda _: None, countdown=0, conditions={}) == 'Terminé'


def test_import_tick_thumbnail_and_trash_reset_on_the_same_card(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog
    _, pixels = reference()
    path = tmp_path/'depart.png'
    cv2.imwrite(str(path), pixels)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: (str(path), ''))
    window = MainWindow()
    node = next(iter(window.workflow_panel.canvas.nodes.values()))
    assert node.condition_status.text() == '' and not node.condition_clear.isEnabled()
    node.condition_import.click()
    app.processEvents()
    assert not node.condition_status.pixmap().isNull() and not node.condition_import.icon().isNull()
    assert node.condition_status.accessibleName() == 'Image importée'
    assert node.condition_clear.isEnabled() and window.workflow.modules[0].condition.image
    assert window.dirty and window.tabs.count() == 5
    node.condition_clear.click()
    assert window.workflow.modules[0].condition == ImageCondition()
    assert node.condition_status.text() == '' and not node.condition_clear.isEnabled()
    window.dirty = False
    window.close()


def test_cancel_import_keeps_existing_image(monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    window = MainWindow()
    condition, _ = reference()
    module = window.workflow.modules[0]
    module.condition = condition
    window.workflow_panel.refresh()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: ('', ''))
    next(iter(window.workflow_panel.canvas.nodes.values())).choose_condition()
    assert module.condition == condition and not window.dirty
    window.close()


def test_check_every_three_seconds_then_match_once():
    condition, pixels = reference()
    screens = [np.zeros_like(pixels), pixels]
    class Stop:
        waits = []
        def is_set(self): return False
        def wait(self, seconds): self.waits.append(seconds); return False
    stop = Stop()
    assert wait_for_condition(condition, stop, lambda: (screens.pop(0), 0, 0))
    assert len(stop.waits) == 1 and 2.5 < stop.waits[0] <= 3


def test_condition_once_before_module_repeats_and_again_each_workflow_tour():
    workflow, pixels = planned()
    actions, mapping = workflow.compile()
    gates = workflow.conditions(mapping)
    assert set(gates) == {0, 3}
    class Backend(FakeBackend):
        captures = 0
        def capture_popup(self, region): self.captures += 1; return pixels, 0, 0
    backend, waits = Backend(), []
    assert execute(actions, backend, threading.Event(), lambda _: None, countdown=0, cycles=2,
        conditions=gates, condition_progress=lambda i, on, msg: waits.append((i, on))) == 'Terminé'
    assert backend.calls == [('text', c) for c in 'AABCAABC']
    assert backend.captures == 4
    assert waits == [(0, True), (0, False), (3, True), (3, False)] * 2


def test_stop_during_wait_does_not_run_next_sequence():
    workflow, pixels = planned()
    workflow.modules[0].condition = ImageCondition()
    actions, mapping = workflow.compile()
    class Stop(threading.Event):
        def wait(self, seconds=None):
            if seconds and seconds > 1: self.set()
            return self.is_set()
    class Backend(FakeBackend):
        def capture_popup(self, region): return np.zeros_like(pixels), 0, 0
    backend = Backend()
    assert execute(actions, backend, Stop(), lambda _: None, countdown=0, conditions=workflow.conditions(mapping)) == 'Arrêté'
    assert backend.calls == [('text', c) for c in 'AAB']


def test_stop_after_capture_and_pause_checkpoint_prevent_start():
    condition, pixels = reference()
    stop = threading.Event()
    def capture(): stop.set(); return pixels, 0, 0
    assert not wait_for_condition(condition, stop, capture)
    class PausedStop:
        def is_set(self): return False
        def checkpoint(self): return False
    assert not wait_for_condition(condition, PausedStop(), lambda: pytest.fail('Capture pendant pause'))


def test_capture_error_does_not_execute_conditioned_actions():
    workflow, _ = planned()
    actions, mapping = workflow.compile()
    class Backend(FakeBackend):
        def capture_popup(self, region): raise RuntimeError('Capture impossible')
    backend = Backend()
    with pytest.raises(RuntimeError, match='Capture impossible'):
        execute(actions, backend, threading.Event(), lambda _: None, countdown=0, conditions=workflow.conditions(mapping))
    assert backend.calls == []


def test_save_load_import_and_duplicate_preserve_independent_conditions(tmp_path):
    workflow, _ = planned()
    path = tmp_path/'conditions.json'
    save_workflow(path, workflow)
    restored = load_workflow(path)
    assert restored.modules[0].condition == workflow.modules[0].condition
    target = Workflow()
    target.import_modules(restored, replace_empty=True)
    assert target.modules[0].condition is not restored.modules[0].condition
    window = MainWindow()
    window.set_document(restored)
    panel = window.workflow_panel
    panel.canvas.nodes[restored.modules[0].id].setSelected(True)
    panel.duplicate()
    copied = restored.modules[-1]
    assert copied.condition == restored.modules[0].condition and copied.condition is not restored.modules[0].condition
    window.dirty = False
    window.close()


def test_export_sequence_preserves_condition_and_repeat(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog
    workflow, _ = planned()
    path = tmp_path/'sequence.json'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(path), ''))
    window = MainWindow()
    window.set_document(workflow)
    window.export_sequence()
    module = load_workflow(path).modules[0]
    assert module.condition == workflow.modules[0].condition and module.repeat == 2
    assert module.next_id is None
    window.close()


def test_legacy_files_without_condition_remain_normal_and_worker_copies_config(tmp_path):
    workflow, _ = planned()
    path = tmp_path/'old.json'
    save_workflow(path, workflow)
    data = json.loads(path.read_text(encoding='utf-8'))
    for module in data['modules']: del module['condition']
    path.write_text(json.dumps(data), encoding='utf-8')
    assert all(not m.condition.image for m in load_workflow(path).modules)
    actions, mapping = workflow.compile()
    gates = workflow.conditions(mapping)
    worker = Worker(actions, conditions=gates)
    gates[0]['condition'].image = ''
    assert worker.conditions[0]['condition'].image


@pytest.mark.parametrize('data', [{'image': 123}, {'name': []}, {'image': 'not-png'}, {'extra': True}])
def test_invalid_image_condition_rejected(data):
    with pytest.raises(ValueError): load_condition(data)

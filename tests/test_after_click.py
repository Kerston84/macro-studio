import copy
import threading
import numpy as np
import pytest
from PySide6.QtWidgets import QGroupBox, QDoubleSpinBox
from macro_studio.model import Action, AFTER_CLICK_DEFAULTS, save, load
from macro_studio.workflow import Workflow, Module, save_workflow, load_workflow
from macro_studio.engine import execute
from macro_studio import vision
from macro_studio.app import MainWindow
from test_vision import sample
from test_wait_image import ClockStop
from test_ui import app

def config(encoded, **changes):
    p = copy.deepcopy(AFTER_CLICK_DEFAULTS)
    p.update(enabled=True, image=encoded, name="Chargement.png", **changes)
    return p

def run(monkeypatch, sample, frames, **changes):
    template, encoded = sample
    clock = ClockStop()
    monkeypatch.setattr(vision.time, "monotonic", lambda: clock.now)
    states = iter(frames)
    captures, logs = [], []
    def capture():
        present = next(states)
        captures.append(present)
        return template.copy() if present else np.zeros_like(template), 0, 0
    result = vision.wait_after_click(config(encoded, **changes), clock, capture, logs.append)
    return result, captures, logs

def test_loading_appears_after_click_then_disappears(monkeypatch, sample):
    done, captures, logs = run(monkeypatch, sample, [False, True, True, False, False], absent_for=.25)
    assert done is True
    assert len(captures) == 5
    assert any("détecté" in message for message in logs)
    assert "terminé" in logs[-1]

def test_no_loading_is_not_an_error(monkeypatch, sample):
    done, captures, logs = run(monkeypatch, sample, [False, False, False], appearance_timeout=.5)
    assert done is True
    assert captures == [False] * 3
    assert "Aucun chargement" in logs[-1]

def test_immediate_check_can_skip_optional_wait(monkeypatch, sample):
    done, captures, _ = run(monkeypatch, sample, [False], appearance_timeout=0)
    assert done and len(captures) == 1

def test_reappearing_loader_restarts_confirmation(monkeypatch, sample):
    done, captures, _ = run(monkeypatch, sample, [True, False, True, False, False], absent_for=.25)
    assert done and len(captures) == 5

def test_stuck_loader_is_error_not_success(monkeypatch, sample):
    with pytest.raises(TimeoutError, match="chargement"):
        run(monkeypatch, sample, [True, True, True], timeout=.5, absent_for=.25)

def test_cancel_during_detection(sample):
    clock = ClockStop(cancel_on_wait=True)
    assert vision.wait_after_click(config(sample[1]), clock,
        lambda: (np.zeros_like(sample[0]), 0, 0)) is False

@pytest.mark.parametrize("kind", ["mouse", "mouse_image", "scroll_image"])
def test_wait_runs_after_click_before_next_action(sample, kind):
    class Backend:
        def __init__(self): self.calls = []
        def find_image(self, p, stop): return 20, 30, 1
        def find_scrolling_image(self, p, stop, log): return 20, 30, 1
        def click(self, *args): self.calls.append("click")
        def wait_after_click(self, p, stop, log):
            self.calls.append("loading")
            return True
        def type_text(self, text, stop): self.calls.append(text)
    action = Action.create(kind)
    if kind != "mouse": action.params["image"] = sample[1]
    action.params["after_click"] = config(sample[1])
    backend = Backend()
    assert execute([action, Action("text", {"text": "suite"})], backend, threading.Event(), lambda _: None, countdown=0) == "Terminé"
    assert backend.calls == ["click", "loading", "suite"]

def test_disabled_optional_wait_keeps_old_behavior():
    class Backend:
        calls = []
        def click(self, *args): self.calls.append("click")
        def wait_after_click(self, *args): pytest.fail("Option désactivée")
    action = Action.create("mouse")
    action.params["after_click"] = copy.deepcopy(AFTER_CLICK_DEFAULTS)
    backend = Backend()
    execute([action], backend, threading.Event(), lambda _: None, countdown=0)
    assert backend.calls == ["click"]

def test_cancel_skips_following_action(sample):
    class Backend:
        calls = []
        def click(self, *args): self.calls.append("click")
        def wait_after_click(self, p, stop, log): return False
        def type_text(self, *args): pytest.fail("Suite exécutée après annulation")
    action = Action.create("mouse")
    action.params["after_click"] = config(sample[1])
    assert execute([action, Action.create("text")], Backend(), threading.Event(), lambda _: None, countdown=0) == "Arrêté"

@pytest.mark.parametrize("key,value", [("enabled", 1), ("image", ""), ("appearance_timeout", -1),
    ("appearance_timeout", True), ("timeout", -1), ("interval", 0), ("threshold", float("nan")),
    ("absent_for", -1), ("region", {}), ("name", 3)])
def test_invalid_loading_configuration(sample, key, value):
    action = Action.create("mouse")
    action.params["after_click"] = config(sample[1])
    action.params["after_click"][key] = value
    with pytest.raises(ValueError): action.validate()

def test_optional_config_roundtrip_and_legacy_unchanged(sample, tmp_path):
    action = Action.create("mouse")
    action.params["after_click"] = config(sample[1])
    path = tmp_path / "optional.json"
    save(path, [action])
    assert load(path) == [action]
    workflow = Workflow([Module(actions=[action], repeat=2)])
    save_workflow(path, workflow)
    assert load_workflow(path) == workflow
    old = Action.create("mouse")
    save(path, [old])
    assert "after_click" not in load(path)[0].params

def test_group_configuration_and_zone_stay_separate_from_click(sample):
    window = MainWindow()
    window.add_action("mouse")
    action = window.actions[0]
    group = window.properties.findChild(QGroupBox, "after_click_group")
    assert not group.isChecked()
    group.setChecked(True)
    action.params["after_click"]["image"] = sample[1]
    window.properties.findChild(QDoubleSpinBox, "after_click_appearance_timeout").setValue(5)
    assert action.params["after_click"]["appearance_timeout"] == 5
    region = {"left": 100, "top": 200, "width": 300, "height": 400}
    window.apply_scroll_region(action, region, after_click=True)
    assert action.params["after_click"]["region"] == region
    assert action.params["x"] == 0 and action.params["y"] == 0
    action.validate()
    window.properties.findChild(QGroupBox, "after_click_group").setChecked(False)
    assert not action.params["after_click"]["enabled"]
    assert action.params["after_click"]["image"] == sample[1]
    window.dirty = False
    window.close()

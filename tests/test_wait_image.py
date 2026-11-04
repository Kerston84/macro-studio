import threading
import numpy as np
import pytest
from macro_studio.model import Action, save, load
from macro_studio.workflow import Workflow, Module, save_workflow, load_workflow
from macro_studio.engine import execute, DesktopBackend
from macro_studio import vision
from test_vision import sample

def params(encoded, **changes):
    p = Action.create("wait_image_absent").params
    p.update(image=encoded, name="Chargement.png", **changes)
    return p

class ClockStop:
    def __init__(self, cancel_on_wait=False):
        self.now = 0
        self.stopped = False
        self.cancel_on_wait = cancel_on_wait
    def is_set(self): return self.stopped
    def wait(self, seconds):
        self.now += seconds
        if self.cancel_on_wait: self.stopped = True
        return self.stopped

def run_frames(monkeypatch, sample, frames, **changes):
    template, encoded = sample
    clock = ClockStop()
    monkeypatch.setattr(vision.time, "monotonic", lambda: clock.now)
    captured, logs = [], []
    states = iter(frames)
    def capture():
        present = next(states)
        captured.append(present)
        return (template.copy() if present else np.zeros_like(template)), 0, 0
    result = vision.wait_until_absent(params(encoded, **changes), clock, capture, logs.append)
    return result, captured, logs, clock.now

def test_present_waits_then_resumes(monkeypatch, sample):
    result, frames, logs, elapsed = run_frames(monkeypatch, sample,
        [True, True, False, False, False], absent_for=.5)
    assert result is True
    assert len(frames) == 5
    assert elapsed == 1
    assert any("Image présente" in message for message in logs)
    assert "reprise" in logs[-1]

def test_reappearing_resets_confirmation(monkeypatch, sample):
    result, frames, _, elapsed = run_frames(monkeypatch, sample,
        [True, False, True, False, False, False], absent_for=.5)
    assert result is True
    assert len(frames) == 6
    assert elapsed == 1.25

def test_initially_absent_can_skip(monkeypatch, sample):
    result, frames, _, _ = run_frames(monkeypatch, sample, [False], absent_for=0)
    assert result is True
    assert frames == [False]

def test_wait_for_delayed_appearance(monkeypatch, sample):
    result, frames, _, _ = run_frames(monkeypatch, sample,
        [False, False, True, False], absent_for=0, wait_for_appearance=True)
    assert result is True
    assert frames == [False, False, True, False]

@pytest.mark.parametrize("present,wait_first", [(True, False), (False, True)])
def test_timeout_stops_on_stuck_or_never_appearing_image(monkeypatch, sample, present, wait_first):
    template, encoded = sample
    clock = ClockStop()
    monkeypatch.setattr(vision.time, "monotonic", lambda: clock.now)
    screen = template if present else np.zeros_like(template)
    with pytest.raises(TimeoutError, match="arrêtée"):
        vision.wait_until_absent(params(encoded, timeout=.5, absent_for=0,
            wait_for_appearance=wait_first), clock, lambda: (screen.copy(), 0, 0))

def test_cancel_during_wait(monkeypatch, sample):
    template, encoded = sample
    clock = ClockStop(cancel_on_wait=True)
    monkeypatch.setattr(vision.time, "monotonic", lambda: clock.now)
    assert vision.wait_until_absent(params(encoded), clock, lambda: (template.copy(), 0, 0)) is False

def test_multiple_visible_images_still_mean_wait(sample):
    template, encoded = sample
    screen = np.zeros((100, 150, 3), np.uint8)
    screen[10:30, 10:42] = template
    screen[60:80, 90:122] = template
    with pytest.raises(TimeoutError):
        vision.wait_until_absent(params(encoded, timeout=0, absent_for=0), threading.Event(),
                                 lambda: (screen, 0, 0))

def test_zone_smaller_than_template_is_error(sample):
    with pytest.raises(ValueError, match="plus petite"):
        vision.wait_until_absent(params(sample[1]), threading.Event(),
                                 lambda: (np.zeros((8, 8, 3), np.uint8), 0, 0))

def test_wait_backend_uses_selected_zone(monkeypatch, sample):
    region = {"left": 100, "top": 100, "width": 200, "height": 200}
    captures = []
    monkeypatch.setattr(vision, "capture_region", lambda r: (captures.append(r) or np.zeros((200, 200, 3), np.uint8), 100, 100))
    monkeypatch.setattr(vision, "capture_desktop", lambda: pytest.fail("Capture hors zone"))
    backend = DesktopBackend.__new__(DesktopBackend)
    assert backend.wait_image_absent(params(sample[1], region=region, absent_for=0), threading.Event(), lambda _: None)
    assert captures == [region]

def test_engine_resumes_only_after_wait_and_stops_on_cancel(sample):
    class Backend:
        def __init__(self, done): self.done, self.calls = done, []
        def wait_image_absent(self, p, stop, log):
            self.calls.append("wait")
            return self.done
        def type_text(self, text, stop): self.calls.append(text)
    actions = [Action("wait_image_absent", params(sample[1])), Action("text", {"text": "suite"})]
    backend = Backend(True)
    assert execute(actions, backend, threading.Event(), lambda _: None, countdown=0) == "Terminé"
    assert backend.calls == ["wait", "suite"]
    backend = Backend(False)
    assert execute(actions, backend, threading.Event(), lambda _: None, countdown=0) == "Arrêté"
    assert backend.calls == ["wait"]

@pytest.mark.parametrize("key,value", [("interval", 0), ("interval", True), ("absent_for", -1),
    ("absent_for", float("nan")), ("wait_for_appearance", 1), ("region", {}), ("timeout", -1)])
def test_invalid_parameters(sample, key, value):
    p = params(sample[1])
    p[key] = value
    with pytest.raises(ValueError): Action("wait_image_absent", p).validate()

def test_confirmation_must_fit_timeout(sample):
    with pytest.raises(ValueError, match="confirmation"):
        Action("wait_image_absent", params(sample[1], timeout=.5, absent_for=1)).validate()

def test_wait_persistence_and_repeats(sample, tmp_path):
    action = Action("wait_image_absent", params(sample[1]))
    path = tmp_path / "wait.json"
    save(path, [action])
    assert load(path) == [action]
    workflow = Workflow([Module("Attendre la fin du chargement", [action], repeat=2)])
    save_workflow(path, workflow)
    assert load_workflow(path) == workflow
    assert len(workflow.compile()[0]) == 2

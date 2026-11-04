import threading
import numpy as np
import pytest
from macro_studio.engine import DesktopBackend, execute, scroll_vector
from macro_studio.model import Action, save, load
from macro_studio.vision import find_with_scroll
from macro_studio.workflow import Module, Workflow, save_workflow, load_workflow
from test_vision import sample

def params(encoded, **changes):
    action = Action.create("scroll_image")
    action.params.update(image=encoded, name="bouton.png", pause=.05, **changes)
    return action.params

@pytest.mark.parametrize("direction,expected", [("down", (0, -1)), ("up", (0, 1)),
                                               ("left", (-1, 0)), ("right", (1, 0))])
def test_native_scroll_direction_and_target(direction, expected):
    class Mouse:
        position = (50, 60)
        def __init__(self): self.calls = []
        def scroll(self, dx, dy): self.calls.append((dx, dy))
    backend = DesktopBackend.__new__(DesktopBackend)
    backend.mouse = Mouse()
    p = Action.create("scroll").params
    p.update(direction=direction, use_position=True, x=-300, y=250)
    backend.scroll(p, threading.Event())
    assert backend.mouse.calls == [expected] * 3
    assert backend.mouse.position == (-300, 250)

def test_stop_during_native_scroll_preserves_cursor_by_default():
    stop = threading.Event()
    class Mouse:
        position = (90, 100)
        calls = 0
        def scroll(self, dx, dy):
            self.calls += 1
            stop.set()
    backend = DesktopBackend.__new__(DesktopBackend)
    backend.mouse = Mouse()
    backend.scroll(Action.create("scroll").params, stop)
    assert backend.mouse.calls == 1
    assert backend.mouse.position == (90, 100)

def test_search_after_scroll_and_origin(sample):
    template, encoded = sample
    empty = np.zeros((100, 150, 3), np.uint8)
    visible = empty.copy()
    visible[30:50, 60:92] = template
    pages = iter((empty, empty, visible))
    scrolls, logs = [], []
    found = find_with_scroll(params(encoded), threading.Event(), lambda: scrolls.append(True),
                             capture=lambda: (next(pages), -100, 20), log=logs.append)
    assert found[:2] == (-24, 60)
    assert len(scrolls) == len(logs) == 2

def test_visible_image_needs_no_scroll(sample):
    template, encoded = sample
    scrolls = []
    found = find_with_scroll(params(encoded), threading.Event(), lambda: scrolls.append(True),
                             capture=lambda: (template.copy(), 0, 0))
    assert found[:2] == (16, 10)
    assert scrolls == []

def test_scroll_limit_and_no_click(sample):
    _, encoded = sample
    scrolls, captures = [], []
    def capture():
        captures.append(True)
        return np.zeros((100, 150, 3), np.uint8), 0, 0
    with pytest.raises(TimeoutError, match="après 2"):
        find_with_scroll(params(encoded, max_scrolls=2), threading.Event(),
                         lambda: scrolls.append(True), capture=capture)
    assert len(scrolls) == 2
    assert len(captures) == 3

def test_deadline_prevents_scroll(sample):
    _, encoded = sample
    scrolls = []
    with pytest.raises(TimeoutError, match="Délai"):
        find_with_scroll(params(encoded, timeout=0), threading.Event(), lambda: scrolls.append(True),
                         capture=lambda: (np.zeros((100, 150, 3), np.uint8), 0, 0))
    assert scrolls == []

def test_ambiguity_does_not_scroll(sample):
    template, encoded = sample
    screen = np.zeros((100, 150, 3), np.uint8)
    screen[10:30, 10:42] = template
    screen[60:80, 90:122] = template
    scrolls = []
    with pytest.raises(ValueError, match="Plusieurs"):
        find_with_scroll(params(encoded), threading.Event(), lambda: scrolls.append(True),
                         capture=lambda: (screen, 0, 0))
    assert scrolls == []

def test_cancel_in_scroll_callback(sample):
    _, encoded = sample
    stop = threading.Event()
    calls = []
    def scroll():
        calls.append(True)
        stop.set()
    assert find_with_scroll(params(encoded), stop, scroll,
        capture=lambda: (np.zeros((100, 150, 3), np.uint8), 0, 0)) is None
    assert calls == [True]

def test_scroll_engine_order(sample):
    class Backend:
        def __init__(self): self.calls = []
        def scroll(self, p, stop): self.calls.append("scroll")
        def find_scrolling_image(self, p, stop, log):
            self.calls.append("search")
            return 120, 80, 1.0
        def click(self, x, y, button): self.calls.append((x, y, button))
    backend = Backend()
    scroll = Action.create("scroll")
    scroll.params["pause"] = .05
    actions = [scroll, Action("scroll_image", params(sample[1]))]
    assert execute(actions, backend, threading.Event(), lambda _: None, countdown=0) == "Terminé"
    assert backend.calls == ["scroll", "search", (120, 80, "left")]

def test_cancel_after_search_prevents_click(sample):
    stop = threading.Event()
    class Backend:
        def find_scrolling_image(self, p, event, log):
            event.set()
            return 120, 80, 1.0
        def click(self, *args): pytest.fail("Clic après annulation")
    assert execute([Action("scroll_image", params(sample[1]))], Backend(), stop,
                   lambda _: None, countdown=0) == "Arrêté"

@pytest.mark.parametrize("key,value", [("direction", "bad"), ("amount", 0), ("amount", True),
    ("pause", float("nan")), ("pause", 0), ("use_position", 1), ("x", .5),
    ("max_scrolls", 0), ("max_scrolls", True), ("max_scrolls", 201)])
def test_invalid_scroll_parameters(sample, key, value):
    p = params(sample[1])
    p[key] = value
    with pytest.raises(ValueError):
        Action("scroll_image", p).validate()

def test_scroll_json_and_workflow_roundtrip(sample, tmp_path):
    actions = [Action.create("scroll"), Action("scroll_image", params(sample[1]))]
    path = tmp_path / "sequence.json"
    save(path, actions)
    assert load(path) == actions
    workflow = Workflow([Module("Recherche en bas de page", actions)])
    target = tmp_path / "workflow.json"
    save_workflow(target, workflow)
    assert load_workflow(target) == workflow

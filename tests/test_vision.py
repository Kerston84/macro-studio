import base64
import threading
import cv2
import numpy as np
import pytest
from macro_studio.vision import decode_template, locate, find_on_screen
from macro_studio.model import Action, save, load
from macro_studio.engine import execute

@pytest.fixture
def sample():
    template = np.random.default_rng(42).integers(0, 256, (20, 32, 3), dtype=np.uint8)
    ok, png = cv2.imencode(".png", template)
    assert ok
    return template, base64.b64encode(png).decode("ascii")

def image_action(encoded):
    return Action("mouse_image", {"image": encoded, "name": "bouton.png", "threshold": .9,
                                  "timeout": 0, "button": "left", "occurrence": "unique"})

def test_find_center(sample):
    template, _ = sample
    screen = np.zeros((100, 150, 3), dtype=np.uint8)
    screen[30:50, 60:92] = template
    found = locate(screen, template, .9)
    assert found[:2] == (76, 40)
    assert found[2] > .99

def test_absent_and_larger(sample):
    template, _ = sample
    assert locate(np.zeros((100, 150, 3), np.uint8), template, .9) is None
    assert locate(np.zeros((8, 8, 3), np.uint8), template, .9) is None

def test_ambiguous(sample):
    template, _ = sample
    screen = np.zeros((100, 150, 3), np.uint8)
    screen[10:30, 10:42] = template
    screen[60:80, 90:122] = template
    with pytest.raises(ValueError, match="Plusieurs"):
        locate(screen, template, .9)

def test_explicit_first_and_last(sample):
    template, _ = sample
    screen = np.zeros((100, 150, 3), np.uint8)
    screen[10:30, 10:42] = template
    screen[60:80, 90:122] = template
    assert locate(screen, template, .9, "first")[:2] == (26, 20)
    assert locate(screen, template, .9, "last")[:2] == (106, 70)

def test_legacy_image_macro(sample, tmp_path):
    import json
    action = image_action(sample[1])
    del action.params["occurrence"]
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"version": 1, "actions": [{"kind": action.kind, "params": action.params}]}))
    assert load(path)[0].params["occurrence"] == "unique"

def test_negative_monitor_origin(sample):
    template, encoded = sample
    screen = np.zeros((100, 150, 3), np.uint8)
    screen[30:50, 60:92] = template
    found = find_on_screen(encoded, .9, 0, threading.Event(),
                           capture=lambda: (screen, -1920, -200))
    assert found[:2] == (-1844, -160)

def test_timeout(sample):
    _, encoded = sample
    with pytest.raises(TimeoutError):
        find_on_screen(encoded, .9, 0, threading.Event(),
                       capture=lambda: (np.zeros((100, 150, 3), np.uint8), 0, 0))

def test_cancel_during_search(sample):
    _, encoded = sample
    stop = threading.Event()
    entered = threading.Event()
    def capture():
        entered.set()
        return np.zeros((100, 150, 3), np.uint8), 0, 0
    result = []
    thread = threading.Thread(target=lambda: result.append(find_on_screen(encoded, .9, 60, stop, capture)))
    thread.start()
    assert entered.wait(2)
    stop.set()
    thread.join(2)
    assert not thread.is_alive()
    assert result == [None]

@pytest.mark.parametrize("encoded", ["", "bad!", base64.b64encode(b"not png").decode()])
def test_invalid_image(encoded):
    with pytest.raises(ValueError):
        decode_template(encoded)

def test_uniform_rejected():
    _, png = cv2.imencode(".png", np.full((20, 20, 3), 128, np.uint8))
    with pytest.raises(ValueError, match="uniforme"):
        decode_template(base64.b64encode(png).decode())

def test_embedded_roundtrip(sample, tmp_path):
    _, encoded = sample
    action = image_action(encoded)
    path = tmp_path / "macro.json"
    save(path, [action])
    restored = load(path)
    assert restored == [action]
    assert np.array_equal(decode_template(restored[0].params["image"]), sample[0])

def test_image_engine_click_and_cancellation(sample):
    _, encoded = sample
    class Backend:
        def __init__(self):
            self.calls = []
        def find_image(self, params, stop):
            return 120, 80, .99
        def click(self, *args):
            self.calls.append(args)
    stop = threading.Event()
    backend = Backend()
    execute([image_action(encoded)], backend, stop, lambda _: None, countdown=0)
    assert backend.calls == [(120, 80, "left")]
    def cancelled(params, event):
        event.set()
        return 120, 80, .99
    backend.calls.clear()
    backend.find_image = cancelled
    assert execute([image_action(encoded)], backend, stop, lambda _: None, countdown=0) == "Arrêté"
    assert backend.calls == []

@pytest.mark.parametrize("key,value", [("threshold", 0), ("threshold", float("nan")),
                                        ("timeout", -1), ("timeout", True), ("button", "bad")])
def test_image_parameters(sample, key, value):
    action = image_action(sample[1])
    action.params[key] = value
    with pytest.raises(ValueError):
        action.validate()

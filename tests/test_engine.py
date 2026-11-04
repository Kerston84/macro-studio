import threading
from macro_studio.engine import execute, DesktopBackend
from macro_studio.model import Action

class FakeBackend:
    def __init__(self):
        self.calls = []
    def click(self, *args):
        self.calls.append(("mouse", args))
    def hotkey(self, keys, stop):
        self.calls.append(("keyboard", keys))
    def type_text(self, text, stop):
        self.calls.append(("text", text))

def test_order():
    backend = FakeBackend()
    progress = []
    actions = [Action.create(k) for k in ("mouse", "keyboard", "text")]
    assert execute(actions, backend, threading.Event(), lambda _: None, progress.append, 0) == "Terminé"
    assert [c[0] for c in backend.calls] == ["mouse", "keyboard", "text"]
    assert progress == [0, 1, 2]

def test_interrupt_wait():
    stop = threading.Event()
    backend = FakeBackend()
    result = []
    entered = threading.Event()
    thread = threading.Thread(target=lambda: result.append(execute(
        [Action("wait", {"seconds": 60}), Action.create("mouse")], backend,
        stop, lambda message: entered.set() if message.startswith("Bloc") else None, countdown=0)))
    thread.start()
    assert entered.wait(1)
    stop.set()
    thread.join(1)
    assert not thread.is_alive()
    assert result == ["Arrêté"]
    assert backend.calls == []

def test_cancel_countdown():
    stop = threading.Event()
    stop.set()
    backend = FakeBackend()
    assert execute([Action.create("mouse")], backend, stop, lambda _: None) == "Arrêté"
    assert backend.calls == []

def test_release_keys_on_error():
    class Keyboard:
        def __init__(self):
            self.released = []
        def press(self, key):
            if key == "x":
                raise RuntimeError("input failure")
        def release(self, key):
            self.released.append(key)
    backend = DesktopBackend.__new__(DesktopBackend)
    backend.keyboard = Keyboard()
    import pytest
    with pytest.raises(RuntimeError):
        backend.hotkey(["a", "x"], threading.Event())
    assert backend.keyboard.released == ["a"]

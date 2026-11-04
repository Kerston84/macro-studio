import ctypes
import threading
from types import SimpleNamespace
import pytest
from macro_studio.text_input import Input, character_events, WindowsTextSender
from macro_studio.engine import DesktopBackend

@pytest.mark.parametrize("character", [".", "@", "+", "_", "-", "é", "A", "漢", "🙂"])
def test_characters_use_unicode_events(character):
    events = character_events(character)
    data = bytearray()
    for press, release in zip(events[::2], events[1::2]):
        assert press.type == release.type == 1
        assert press.value.ki.wVk == release.value.ki.wVk == 0
        assert press.value.ki.dwFlags == 4
        assert release.value.ki.dwFlags == 6
        assert press.value.ki.wScan == release.value.ki.wScan
        data.extend(int(press.value.ki.wScan).to_bytes(2, "little"))
    assert data.decode("utf-16-le") == character

def test_native_input_structure_matches_windows():
    assert ctypes.sizeof(Input) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

def test_email_keeps_both_dots_and_suffix():
    text = "prenom.nom+test@example.fr"
    sent = []
    def send_input(count, events, size):
        assert size == ctypes.sizeof(Input)
        data = b"".join(int(events[i].value.ki.wScan).to_bytes(2, "little") for i in range(0, count, 2))
        sent.append(data.decode("utf-16-le"))
        return count
    backend = DesktopBackend.__new__(DesktopBackend)
    backend.text_sender = WindowsTextSender(send_input)
    backend.keyboard = SimpleNamespace(type=lambda _: pytest.fail("Fallback inattendu"))
    backend.type_text(text, threading.Event())
    assert "".join(sent) == text

def test_cancel_between_characters():
    stop = threading.Event()
    sent = []
    def send(character):
        sent.append(character)
        if character == ".": stop.set()
    backend = DesktopBackend.__new__(DesktopBackend)
    backend.text_sender = SimpleNamespace(send_character=send)
    backend.type_text("a.b@example.fr", stop)
    assert sent == ["a", "."]

def test_native_failure_is_reported_instead_of_false_success():
    sender = WindowsTextSender(lambda count, events, size: 0)
    with pytest.raises(RuntimeError, match="refusé"):
        sender.send_character(".")

def test_tab_and_newline_use_control_keys():
    characters, controls = [], []
    backend = DesktopBackend.__new__(DesktopBackend)
    backend.text_sender = SimpleNamespace(send_character=characters.append)
    backend.keyboard = SimpleNamespace(type=controls.append)
    backend.type_text("a\tb\nc", threading.Event())
    assert characters == ["a", "b", "c"]
    assert controls == ["\t", "\n"]

def test_finish_does_not_restore_or_activate_editor(monkeypatch):
    from macro_studio.app import MainWindow
    from test_ui import app
    window = MainWindow()
    deleted = []
    window.worker = SimpleNamespace(deleteLater=lambda: deleted.append(True))
    monkeypatch.setattr(window, "showNormal", lambda: pytest.fail("Le focus serait repris"))
    monkeypatch.setattr(window, "activateWindow", lambda: pytest.fail("Le focus serait repris"))
    window.finished()
    assert window.worker is None
    assert deleted == [True]
    window.dirty = False
    window.close()

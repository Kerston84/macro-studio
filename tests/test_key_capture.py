import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace
import threading
import pytest
from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit
from macro_studio.key_capture import KeyCaptureDialog, format_keys
from macro_studio.app import MainWindow
from macro_studio.engine import DesktopBackend
from macro_studio.model import Action, save, load, parse_keys

app = QApplication.instance() or QApplication([])

@pytest.mark.parametrize("key,modifiers,expected", [
    (Qt.Key_Return, Qt.NoModifier, "enter"), (Qt.Key_Tab, Qt.NoModifier, "tab"),
    (Qt.Key_Escape, Qt.NoModifier, "esc"), (Qt.Key_Space, Qt.NoModifier, "space"),
    (Qt.Key_Delete, Qt.NoModifier, "delete"), (Qt.Key_Left, Qt.NoModifier, "left"),
    (Qt.Key_F5, Qt.NoModifier, "f5"), (Qt.Key_F24, Qt.NoModifier, "f24"),
    (Qt.Key_C, Qt.ControlModifier, "ctrl+c"),
    (Qt.Key_S, Qt.ControlModifier | Qt.ShiftModifier, "ctrl+shift+s"),
    (Qt.Key_Tab, Qt.ShiftModifier, "shift+tab"),
    (Qt.Key_Plus, Qt.ControlModifier, "ctrl+plus"),
    (Qt.Key_Insert, Qt.NoModifier, "insert"),
])
def test_capture_direct_key_and_chords(key, modifiers, expected):
    dialog = KeyCaptureDialog()
    dialog.show()
    QTest.keyClick(dialog, key, modifiers)
    assert dialog.result() == QDialog.Accepted
    assert dialog.value == expected
    parse_keys(dialog.value)
    dialog.close()

def test_waits_until_all_modifiers_released():
    dialog = KeyCaptureDialog()
    dialog.show()
    app.sendEvent(dialog, QKeyEvent(QEvent.KeyPress, Qt.Key_Control, Qt.ControlModifier))
    app.sendEvent(dialog, QKeyEvent(QEvent.KeyPress, Qt.Key_C, Qt.ControlModifier, "c"))
    app.sendEvent(dialog, QKeyEvent(QEvent.KeyRelease, Qt.Key_C, Qt.ControlModifier, "c"))
    assert dialog.isVisible()
    app.sendEvent(dialog, QKeyEvent(QEvent.KeyRelease, Qt.Key_Control, Qt.NoModifier))
    assert dialog.result() == QDialog.Accepted
    assert dialog.value == "ctrl+c"

def test_modifier_alone_can_be_captured():
    dialog = KeyCaptureDialog()
    dialog.show()
    QTest.keyClick(dialog, Qt.Key_Shift)
    assert dialog.result() == QDialog.Accepted
    assert dialog.value == "shift"

def test_f8_rejected_then_another_key_can_be_captured():
    dialog = KeyCaptureDialog()
    dialog.show()
    QTest.keyClick(dialog, Qt.Key_F8, Qt.ControlModifier)
    assert dialog.value is None
    assert dialog.isVisible()
    assert "réservé" in dialog.feedback.text()
    QTest.keyClick(dialog, Qt.Key_A)
    assert dialog.result() == QDialog.Accepted
    assert dialog.value == "a"

def test_modal_capture_ctrl_s_does_not_save_parent():
    window = MainWindow()
    window.show()
    activated = []
    window.save_shortcut.activated.connect(lambda: activated.append(True))
    dialog = KeyCaptureDialog(window)
    dialog.show()
    app.processEvents()
    QTest.keyClick(dialog, Qt.Key_S, Qt.ControlModifier)
    assert dialog.value == "ctrl+s"
    assert activated == []
    window.dirty = False
    window.close()

def test_capture_applies_to_action_and_cancel_preserves_it(tmp_path):
    window = MainWindow()
    window.add_action("keyboard")
    action = window.actions[0]
    def press():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, KeyCaptureDialog)
        QTimer.singleShot(500, dialog.reject)
        QTest.keyClick(dialog, Qt.Key_F6)
    QTimer.singleShot(0, press)
    window.capture_keys(action)
    assert action.params["keys"] == "f6"
    field = window.properties.findChild(QLineEdit, "captured_keys")
    assert field.isReadOnly()
    assert field.text() == "F6"
    QTimer.singleShot(0, lambda: app.activeModalWidget().reject())
    window.capture_keys(action)
    assert action.params["keys"] == "f6"
    path = tmp_path / "keys.json"
    save(path, [action])
    assert load(path) == [action]
    window.dirty = False
    window.close()

def test_plus_alias_replays_as_character():
    events = []
    backend = DesktopBackend.__new__(DesktopBackend)
    backend.keyboard = SimpleNamespace(press=lambda key: events.append(("press", key)),
                                       release=lambda key: events.append(("release", key)))
    backend.hotkey(["plus"], threading.Event())
    assert events == [("press", "+"), ("release", "+")]

def test_friendly_labels():
    assert format_keys("ctrl+shift+s") == "Ctrl + Maj + S"
    assert format_keys("enter") == "Entrée"

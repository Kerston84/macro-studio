import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QPlainTextEdit
from PySide6.QtTest import QTest
from macro_studio.app import MainWindow, Worker
from macro_studio.model import Action
from test_engine import FakeBackend

app = QApplication.instance() or QApplication([])

def test_editor():
    window = MainWindow()
    window.show()
    window.add_action("wait")
    window.add_action("text")
    editor = window.properties.findChild(QPlainTextEdit)
    editor.setPlainText("Texte modifié")
    assert window.actions[1].params["text"] == "Texte modifié"
    window.move(-1)
    assert [a.kind for a in window.actions] == ["text", "wait"]
    window.duplicate()
    assert len(window.actions) == 3
    window.remove()
    assert len(window.actions) == 2
    window.set_running(True)
    assert not window.start_button.isEnabled()
    assert window.stop_button.isEnabled()
    window.set_running(False)
    window.dirty = False
    window.close()

def test_worker_nonblocking_and_stop():
    worker = Worker([Action("wait", {"seconds": 60})], FakeBackend)
    results = []
    worker.result.connect(results.append)
    worker.start()
    QTest.qWait(100)
    assert worker.isRunning()
    worker.stop_event.set()
    assert worker.wait(3000)
    app.processEvents()
    assert results == ["Arrêté"]

def test_import_button_image(tmp_path, monkeypatch):
    import cv2
    import numpy as np
    from PySide6.QtWidgets import QFileDialog
    from macro_studio.model import save, load
    path = tmp_path / "bouton_été.png"
    pixels = np.random.default_rng(7).integers(0, 256, (20, 40, 3), dtype=np.uint8)
    _, png = cv2.imencode(".png", pixels)
    path.write_bytes(png.tobytes())
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    window = MainWindow()
    window.add_action("mouse_image")
    action = window.actions[0]
    window.choose_image(action)
    action.validate()
    assert action.params["name"] == "bouton_été.png"
    assert window.properties.findChildren(QPlainTextEdit) == []
    destination = tmp_path / "macro.json"
    save(destination, window.actions)
    assert load(destination) == window.actions
    window.dirty = False
    window.close()

def test_scroll_property_editors():
    from PySide6.QtWidgets import QSpinBox, QCheckBox, QComboBox
    window = MainWindow()
    window.add_action("scroll")
    window.properties.findChild(QSpinBox, "param_amount").setValue(7)
    window.properties.findChild(QCheckBox, "param_use_position").setChecked(True)
    window.properties.findChild(QSpinBox, "param_x").setValue(-100)
    combo = window.properties.findChild(QComboBox)
    combo.setCurrentIndex(combo.findData("up"))
    assert window.actions[0].params["amount"] == 7
    assert window.actions[0].params["use_position"] is True
    assert window.actions[0].params["x"] == -100
    assert window.actions[0].params["direction"] == "up"
    window.actions[0].validate()
    window.add_action("scroll_image")
    assert window.properties.findChild(QSpinBox, "param_max_scrolls").value() == 20
    window.dirty = False
    window.close()

def test_image_wait_properties_and_region():
    from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox
    window = MainWindow()
    window.add_action("wait_image_absent")
    window.properties.findChild(QCheckBox, "param_wait_for_appearance").setChecked(True)
    window.properties.findChild(QDoubleSpinBox, "param_absent_for").setValue(2)
    action = window.actions[0]
    assert action.params["wait_for_appearance"] is True
    assert action.params["absent_for"] == 2
    region = {"left": 100, "top": 200, "width": 400, "height": 300}
    window.apply_scroll_region(action, region)
    assert action.params["region"] == region
    assert "use_position" not in action.params
    assert "x" not in action.params
    window.clear_scroll_region(action)
    assert action.params["region"] is None
    window.dirty = False
    window.close()

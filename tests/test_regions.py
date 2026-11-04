import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import threading
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from macro_studio.model import Action, save, load
from macro_studio.workflow import Workflow, Module, save_workflow, load_workflow
from macro_studio.engine import DesktopBackend
from macro_studio.region_picker import RegionPicker, physical_region
from macro_studio.app import MainWindow
from test_vision import sample

app = QApplication.instance() or QApplication([])
REGION = {"left": -500, "top": 100, "width": 200, "height": 300}

def test_reverse_drag_negative_physical_coordinates():
    assert physical_region((-300, 400), (-500, 100)) == REGION

def test_picker_drag_and_escape():
    points = iter(((-500, 100), (-300, 400)))
    picker = RegionPicker(cursor_position=lambda: next(points))
    results = []
    picker.selected.connect(results.append)
    picker.show()
    QTest.mousePress(picker, Qt.LeftButton, pos=QPoint(30, 40))
    QTest.mouseMove(picker, QPoint(230, 340))
    QTest.mouseRelease(picker, Qt.LeftButton, pos=QPoint(230, 340))
    assert results == [REGION]
    picker = RegionPicker(cursor_position=lambda: (0, 0))
    cancelled = []
    picker.cancelled.connect(lambda: cancelled.append(True))
    picker.show()
    QTest.keyClick(picker, Qt.Key_Escape)
    assert cancelled == [True]

def test_picker_close_also_cancels():
    picker = RegionPicker(cursor_position=lambda: (0, 0))
    cancelled = []
    picker.cancelled.connect(lambda: cancelled.append(True))
    picker.show()
    picker.close()
    assert cancelled == [True]

@pytest.mark.parametrize("region", [{}, {**REGION, "width": 0}, {**REGION, "height": 19},
                                    {**REGION, "left": .5}, {**REGION, "width": True}, "bad"])
def test_invalid_regions(region):
    action = Action.create("scroll")
    action.params["region"] = region
    with pytest.raises(ValueError):
        action.validate()

def test_region_center_and_optional_focus():
    class Mouse:
        position = (0, 0)
        def __init__(self): self.calls = []
        def click(self, button): self.calls.append(("click", button, self.position))
        def scroll(self, x, y): self.calls.append(("scroll", x, y, self.position))
    backend = DesktopBackend.__new__(DesktopBackend)
    backend.mouse = Mouse()
    backend.mouse_module = SimpleNamespace(Button=SimpleNamespace(left="left"))
    p = Action.create("scroll").params
    p.update(region=REGION, amount=1, focus_click=True)
    backend.scroll(p, threading.Event())
    assert backend.mouse.calls == [("click", "left", (-400, 250)), ("scroll", 0, -1, (-400, 250))]
    backend.mouse.calls.clear()
    p["focus_click"] = False
    backend.scroll(p, threading.Event())
    assert backend.mouse.calls == [("scroll", 0, -1, (-400, 250))]

def test_search_captures_only_selected_panel(monkeypatch, sample):
    from macro_studio import vision
    template, encoded = sample
    captures = []
    def capture(region):
        captures.append(region)
        return template.copy(), region["left"], region["top"]
    monkeypatch.setattr(vision, "capture_region", capture)
    monkeypatch.setattr(vision, "capture_desktop", lambda: pytest.fail("Capture globale inattendue"))
    backend = DesktopBackend.__new__(DesktopBackend)
    p = Action.create("scroll_image").params
    p.update(image=encoded, region=REGION)
    found = backend.find_scrolling_image(p, threading.Event(), lambda _: None)
    assert found[:2] == (-484, 110)
    assert captures == [REGION]

def test_region_roundtrip_and_old_formats(tmp_path):
    action = Action.create("scroll")
    action.params.update(region=REGION, focus_click=True)
    path = tmp_path / "scroll.json"
    save(path, [action])
    assert load(path) == [action]
    legacy = json.loads(path.read_text(encoding="utf-8"))
    del legacy["actions"][0]["params"]["region"]
    del legacy["actions"][0]["params"]["focus_click"]
    path.write_text(json.dumps(legacy), encoding="utf-8")
    assert load(path)[0].params["region"] is None
    workflow = Workflow([Module(actions=[action])])
    save_workflow(path, workflow)
    assert load_workflow(path) == workflow
    legacy = json.loads(path.read_text(encoding="utf-8"))
    del legacy["modules"][0]["actions"][0]["params"]["region"]
    del legacy["modules"][0]["actions"][0]["params"]["focus_click"]
    path.write_text(json.dumps(legacy), encoding="utf-8")
    assert load_workflow(path).modules[0].actions[0].params["focus_click"] is False

def test_apply_and_clear_panel_in_editor():
    window = MainWindow()
    window.add_action("scroll")
    action = window.actions[0]
    window.apply_scroll_region(action, REGION)
    assert action.params["region"] == REGION
    assert (action.params["x"], action.params["y"]) == (-400, 250)
    assert action.params["use_position"] is True
    assert window.centralWidget().isEnabled()
    window.clear_scroll_region(action)
    assert action.params["region"] is None
    assert action.params["use_position"] is False
    window.dirty = False
    window.close()

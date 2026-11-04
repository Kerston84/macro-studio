import copy
import json
import threading
import numpy as np
import pytest
from macro_studio.popups import PopupMode, PopupRule, PopupMonitor, MonitoredStop
from macro_studio.model import Action
from macro_studio.workflow import Workflow, Module, save_workflow, load_workflow
from macro_studio.engine import execute
from test_vision import sample

class Stop:
    def __init__(self): self.now, self.stopped = 0, False
    def is_set(self): return self.stopped
    def set(self): self.stopped = True
    def wait(self, seconds):
        self.now += seconds
        return self.stopped

class Backend:
    def __init__(self, template):
        self.template = template
        self.visible = True
        self.calls = []
    def capture_popup(self, region):
        self.calls.append(("capture", region))
        return (self.template.copy() if self.visible else np.zeros_like(self.template)), -100, 200
    def click(self, x, y, button):
        self.calls.append(("click", x, y, button))
        self.visible = False

def setup(sample, **fields):
    template, encoded = sample
    stop = Stop()
    backend = Backend(template)
    rule = PopupRule(name="Fermer une publicité", image=encoded, **fields)
    mode = PopupMode(True, [rule])
    logs = []
    monitor = PopupMonitor(mode, backend, stop, logs.append, clock=lambda: stop.now)
    return rule, mode, backend, stop, monitor, logs

def test_detected_image_click_and_resume(sample):
    rule, mode, backend, stop, monitor, logs = setup(sample)
    monitor.check()
    assert ("click", -84, 210, "left") in backend.calls
    assert monitor.counts[rule.id] == 1
    assert monitor.paused_time == .2
    assert "reprise" in logs[-1]

def test_click_chosen_point(sample):
    _, _, backend, _, monitor, _ = setup(sample, response="click_point", x=600, y=450, point_selected=True)
    monitor.check()
    assert ("click", 600, 450, "left") in backend.calls

def test_click_separate_target_image(sample):
    _, _, backend, _, monitor, _ = setup(sample, response="click_image", target_image=sample[1])
    monitor.check()
    assert ("click", -84, 210, "left") in backend.calls

def test_missing_target_stops_without_click(sample):
    template, _ = sample
    import base64, cv2
    other = np.random.default_rng(99).integers(0, 256, template.shape, dtype=np.uint8)
    _, png = cv2.imencode(".png", other)
    _, _, backend, _, monitor, _ = setup(sample, response="click_image", target_image=base64.b64encode(png).decode())
    with pytest.raises(RuntimeError, match="introuvable"):
        monitor.check()
    assert not any(call[0] == "click" for call in backend.calls)

def test_wait_ten_seconds_and_pause_workflow_clock(sample):
    _, _, backend, stop, monitor, _ = setup(sample, response="wait", seconds=10)
    token = MonitoredStop(stop, monitor)
    assert token.wait(2) is False
    assert stop.now == pytest.approx(12)
    assert token.active_time() == pytest.approx(2)
    assert not any(c[0] == "click" for c in backend.calls)

def test_cooldown_and_maximum_prevent_click_loop(sample):
    rule, _, backend, stop, monitor, _ = setup(sample, max_triggers=1)
    monitor.check()
    backend.visible = True
    monitor.check(force=True)
    assert monitor.counts[rule.id] == 1
    stop.now = 4
    with pytest.raises(RuntimeError, match="limite"):
        monitor.check(force=True)

def test_rule_disabled_or_global_disabled_never_captures(sample):
    rule, mode, backend, stop, _, _ = setup(sample)
    mode.enabled = False
    PopupMonitor(mode, backend, stop, lambda _: None).check(force=True)
    mode.enabled, rule.enabled = True, False
    PopupMonitor(mode, backend, stop, lambda _: None).check(force=True)
    assert backend.calls == []

def test_suspended_typing_does_not_interleave_popup_clicks(sample):
    _, _, backend, stop, monitor, _ = setup(sample)
    token = MonitoredStop(stop, monitor)
    with token.atomic_input():
        token.wait(1)
        assert backend.calls == []
    monitor.check()
    assert any(call[0] == "click" for call in backend.calls)

def test_stop_prevents_popup_input(sample):
    _, _, backend, stop, monitor, _ = setup(sample)
    stop.set()
    monitor.check(force=True)
    assert backend.calls == []

def test_ambiguous_detected_button_stops(sample):
    template, _ = sample
    _, _, backend, _, monitor, _ = setup(sample)
    frame = np.zeros((100, 150, 3), np.uint8)
    frame[10:30, 10:42] = template
    frame[60:80, 90:122] = template
    backend.capture_popup = lambda region: (frame, 0, 0)
    with pytest.raises(ValueError, match="Plusieurs"):
        monitor.check()
    assert not any(call[0] == "click" for call in backend.calls)

def test_engine_applies_global_rule_before_normal_actions(sample):
    template, encoded = sample
    backend = Backend(template)
    backend.type_text = lambda text, stop: backend.calls.append(("text", text))
    mode = PopupMode(True, [PopupRule(image=encoded)])
    assert execute([Action.create("text")], backend, threading.Event(), lambda _: None,
                   countdown=0, popup_mode=mode) == "Terminé"
    actions = [c[0] for c in backend.calls if c[0] != "capture"]
    assert actions == ["click", "text"]

def test_popup_during_long_wait_is_handled_before_next_action(sample):
    template, encoded = sample
    backend = Backend(template)
    captures = []
    def capture(region):
        captures.append(True)
        backend.visible = len(captures) >= 2 and not any(c[0] == "click" for c in backend.calls)
        return (template.copy() if backend.visible else np.zeros_like(template)), 0, 0
    backend.capture_popup = capture
    backend.type_text = lambda text, stop: backend.calls.append(("text", text))
    mode = PopupMode(True, [PopupRule(image=encoded)])
    assert execute([Action("wait", {"seconds": .6}), Action.create("text")], backend,
                   threading.Event(), lambda _: None, countdown=0, popup_mode=mode) == "Terminé"
    assert [c[0] for c in backend.calls] == ["click", "text"]

def test_persistence_legacy_and_import(sample, tmp_path):
    workflow = Workflow([Module(actions=[Action.create("wait")])], popups=PopupMode(True, [PopupRule(image=sample[1])]))
    path = tmp_path / "popups.json"
    save_workflow(path, workflow)
    assert load_workflow(path) == workflow
    target = Workflow()
    target.import_modules(workflow, replace_empty=True)
    assert target.popups == workflow.popups
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["popups"]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert not load_workflow(path).popups.enabled

@pytest.mark.parametrize("key,value", [("threshold", 0), ("response", "unknown"), ("cooldown", 0),
    ("seconds", -1), ("max_triggers", True), ("enabled", 1), ("region", {}), ("image", "bad")])
def test_invalid_rules(sample, key, value):
    rule = PopupRule(image=sample[1])
    setattr(rule, key, value)
    with pytest.raises(ValueError): PopupMode(True, [rule]).validate()

def test_point_must_be_chosen_before_activation(sample):
    with pytest.raises(ValueError, match="où cliquer"):
        PopupMode(True, [PopupRule(image=sample[1], response="click_point")]).validate()

def test_stop_during_popup_wait_does_not_resume(sample):
    _, _, backend, stop, monitor, logs = setup(sample, response="wait", seconds=10)
    def wait(seconds):
        stop.set()
        return True
    stop.wait = wait
    token = MonitoredStop(stop, monitor)
    assert token.wait(20) is True
    assert not any("reprise" in line for line in logs)
    assert not any(c[0] == "click" for c in backend.calls)

def test_popup_panel_create_toggle_choose_image_and_save(sample, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog
    from macro_studio.app import MainWindow
    import base64
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "popup.png"
    path.write_bytes(base64.b64decode(sample[1]))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    window = MainWindow()
    panel = window.popup_panel
    panel.add_rule()
    rule = window.workflow.popups.rules[0]
    panel.choose_image(rule)
    panel.enable.setChecked(True)
    assert window.workflow.popups.enabled
    assert rule.image_name == "popup.png"
    panel.update_rule(rule, "response", "wait")
    panel.update_rule(rule, "seconds", 10)
    window.path = str(tmp_path / "workflow.json")
    assert window.save_file()
    restored = load_workflow(window.path)
    assert restored.popups == window.workflow.popups
    window.set_running(True)
    assert not panel.isEnabled()
    window.set_running(False)
    window.close()

def test_popup_point_and_region_pickers_do_not_change_module_actions(sample):
    from PySide6.QtWidgets import QApplication
    from macro_studio.app import MainWindow
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.add_action("text")
    window.popup_panel.add_rule()
    rule = window.workflow.popups.rules[0]
    rectangle = {"left": 100, "top": 200, "width": 400, "height": 300}
    window.apply_popup_region(rule, "point", rectangle)
    assert (rule.x, rule.y) == (300, 350)
    assert rule.point_selected
    window.apply_popup_region(rule, "region", rectangle)
    assert rule.region == rectangle
    assert len(window.actions) == 1
    window.dirty = False
    window.close()

def test_popup_mode_on_sequence_is_saved_as_workflow(sample, tmp_path):
    from PySide6.QtWidgets import QApplication
    from macro_studio.app import MainWindow
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.document_format = "sequence"
    window.workflow.popups = PopupMode(True, [PopupRule(image=sample[1])])
    window.path = str(tmp_path / "sequence.json")
    assert window.save_file()
    assert window.document_format == "workflow"
    assert load_workflow(window.path).popups.enabled
    window.close()

def test_import_rules_remaps_identifiers_and_keeps_current_activation(sample):
    source = Workflow(popups=PopupMode(True, [PopupRule(image=sample[1])]))
    target = Workflow(popups=PopupMode(True, [PopupRule(image=sample[1])]))
    target.import_modules(source)
    assert len(target.popups.rules) == 2
    assert len({r.id for r in target.popups.rules}) == 2
    assert target.popups.enabled
    source.popups = PopupMode(False, [PopupRule()])
    target.import_modules(source)
    assert not target.popups.rules[-1].enabled
    target.validate()

def test_rule_target_can_be_chosen_in_panel_without_destroying_source(sample, tmp_path, monkeypatch):
    import base64
    from PySide6.QtWidgets import QApplication, QFileDialog
    from macro_studio.app import MainWindow
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "fermer.png"
    path.write_bytes(base64.b64decode(sample[1]))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    window = MainWindow()
    window.popup_panel.add_rule()
    rule = window.workflow.popups.rules[0]
    rule.image = sample[1]
    window.popup_panel.choose_image(rule, target=True)
    assert rule.image == sample[1]
    from macro_studio.vision import decode_template
    assert np.array_equal(decode_template(rule.target_image), sample[0])
    assert rule.target_name == "fermer.png"
    window.dirty = False
    window.close()

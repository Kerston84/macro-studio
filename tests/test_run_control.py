import threading

from macro_studio.run_control import RunControl, WindowGuard
from macro_studio.run_widget import RunWidget, duration
from test_ui import app


def test_workflow_safety_persistence_and_legacy_default(tmp_path):
    import json
    from macro_studio.workflow import Workflow, Module, save_workflow, load_workflow
    from macro_studio.model import Action
    path = tmp_path / 'workflow.json'
    workflow = Workflow([Module('Test', [Action.create('wait')])], safety_enabled=False)
    save_workflow(path, workflow)
    assert load_workflow(path).safety_enabled is False
    data = json.loads(path.read_text(encoding='utf-8'))
    del data['safety_enabled']
    path.write_text(json.dumps(data), encoding='utf-8')
    assert load_workflow(path).safety_enabled is True


def test_pause_freezes_active_time_and_stop_unblocks():
    clock = [10.0]
    control = RunControl(clock=lambda: clock[0])
    control.pause()
    clock[0] = 110
    assert control.active_time() == 10
    result = []
    thread = threading.Thread(target=lambda: result.append(control.checkpoint()))
    thread.start()
    assert thread.is_alive()
    control.set()
    thread.join(1)
    assert result == [False]


def test_resume_excludes_pause_duration():
    clock = [10.0]
    control = RunControl(clock=lambda: clock[0])
    control.pause()
    clock[0] = 40
    control.resume()
    clock[0] = 45
    assert control.active_time() == 15


class Guard:
    issue = None
    obstruction = None
    def arm(self): pass
    def reason(self): return self.issue
    def point_reason(self, x, y): return self.obstruction


def test_safety_blocks_until_explicit_valid_resume():
    guard = Guard()
    guard.issue = 'Fenêtre inattendue'
    paused = threading.Event()
    control = RunControl(guard=guard, on_state=lambda p, r: paused.set() if p else None)
    control.arm()
    result = []
    thread = threading.Thread(target=lambda: result.append(control.checkpoint()))
    thread.start()
    assert paused.wait(1)
    control.resume()
    assert control.paused
    guard.issue = None
    assert control.paused
    control.resume()
    thread.join(1)
    assert result == [True]


def test_covered_click_is_blocked_then_rechecked():
    guard = Guard()
    guard.obstruction = 'Clic masqué'
    paused = threading.Event()
    control = RunControl(guard=guard, on_state=lambda p, r: paused.set() if p else None)
    control.arm()
    result = []
    thread = threading.Thread(target=lambda: result.append(control.ensure_point(2, 3)))
    thread.start()
    assert paused.wait(1)
    assert result == []
    guard.obstruction = None
    control.resume()
    thread.join(1)
    assert result == [True]


def test_known_popup_can_suspend_guard():
    guard = Guard()
    guard.issue = 'Popup connue'
    control = RunControl(guard=guard)
    control.arm()
    with control.suspend_safety():
        assert control.checkpoint()
        assert control.ensure_point(1, 1)
    assert control.safety_suspended == 0


def test_window_guard_ignores_widget_but_blocks_editor():
    guard = WindowGuard(ignored=(2,), blocked=(3,))
    guard.foreground = lambda: 1
    guard.arm()
    guard.foreground = lambda: 2
    assert guard.reason() is None
    guard.foreground = lambda: 3
    assert guard.reason()
    guard.arm()
    assert guard.expected == 1
    guard.foreground = lambda: 4
    assert guard.reason()


def test_widget_timers_pause_repeat_and_module_transition():
    clock = [100.0]
    control = RunControl(clock=lambda: clock[0])
    widget = RunWidget()
    widget.begin(control, 5)
    widget.update_progress('a', 'Connexion', 1, 2, 0, 2, 0)
    clock[0] = 110
    widget.update_progress('a', 'Connexion', 2, 2, 0, 2, 2)
    assert widget.last_times == (10, 10)
    control.pause()
    clock[0] = 150
    widget.tick()
    assert widget.last_times == (10, 10)
    control.resume()
    widget.update_progress('b', 'Lecture', 1, 1, 0, 1, 4)
    assert widget.last_times == (10, 0)
    clock[0] = 155
    widget.finish('Terminé')
    clock[0] = 200
    widget.tick()
    assert widget.last_times == (15, 5)
    assert not widget.pause_button.isEnabled()
    widget.close()


def test_widget_controls_and_close_request_stop():
    widget = RunWidget()
    events = []
    widget.pause_requested.connect(lambda: events.append('pause'))
    widget.resume_requested.connect(lambda: events.append('resume'))
    widget.stop_requested.connect(lambda: events.append('stop'))
    widget.begin(RunControl(), 1)
    widget.pause_button.click()
    widget.set_paused(True, 'Sécurité')
    widget.pause_button.click()
    widget.close()
    assert events == ['pause', 'resume', 'stop']
    widget.finish('Arrêté')
    widget.close()
    assert duration(3661) == '01:01:01'


def test_compact_widget_preserves_execution_and_native_window():
    from PySide6.QtCore import Qt
    clock = [100.0]
    control = RunControl(clock=lambda: clock[0])
    widget = RunWidget()
    events = []
    widget.pause_requested.connect(lambda: events.append('pause'))
    widget.resume_requested.connect(lambda: events.append('resume'))
    widget.stop_requested.connect(lambda: events.append('stop'))
    widget.begin(control, 3)
    widget.update_progress('a', 'Connexion', 1, 1, 0, 3, 0)
    handle = int(widget.winId())
    widget.collapse_button.click()
    assert widget.compact and widget.size().width() == widget.size().height() == 44
    assert not widget.content.isVisible() and widget.restore_button.isVisible()
    clock[0] = 112
    widget.update_progress('a', 'Connexion', 1, 1, 1, 3, 1)
    assert widget.last_times == (12, 12)
    assert widget.timer.isActive() and widget.running and not control.paused
    assert '00:00:12' in widget.restore_button.toolTip()
    widget.restore_button.click()
    assert not widget.compact and widget.content.isVisible() and widget.width() == 355
    assert widget.progress.value() == 2 and widget.last_times == (12, 12)
    assert int(widget.winId()) == handle
    assert widget.windowFlags() & Qt.WindowDoesNotAcceptFocus
    assert events == []
    widget.finish('Terminé')
    widget.close()


def test_compact_widget_keeps_safety_pause_and_finish_state():
    widget = RunWidget()
    widget.begin(RunControl(), 1)
    widget.set_compact(True)
    widget.set_paused(True, 'Sécurité : vérifier la cible')
    widget.set_compact(False)
    assert widget.paused and widget.state.text() == 'Sécurité : vérifier la cible'
    assert widget.pause_button.text() == 'Reprendre'
    widget.set_compact(True)
    widget.finish('Terminé')
    widget.set_compact(False)
    assert widget.state.text() == 'Terminé'
    assert not widget.pause_button.isEnabled() and not widget.stop_button.isEnabled()
    widget.close()

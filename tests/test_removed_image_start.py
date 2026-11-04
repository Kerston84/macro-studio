import threading
from dataclasses import asdict
from macro_studio.app import MainWindow
from macro_studio.workflow import Workflow, Module, save_workflow, load_workflow
from macro_studio.image_start import ImageStart
from macro_studio.model import Action, LABELS
from macro_studio.engine import execute
from test_engine import FakeBackend
from test_ui import app


def test_start_ui_removed_but_other_image_actions_remain():
    window = MainWindow()
    assert window.tabs.count() == 5
    assert all('Top départ' not in window.tabs.tabText(i) for i in range(window.tabs.count()))
    node = next(iter(window.workflow_panel.canvas.nodes.values()))
    assert not hasattr(node, 'start_button') and node.repeat_editor is not None
    assert 'mouse_image' in LABELS and 'wait_image_absent' in LABELS
    window.close()


def test_old_enabled_settings_do_not_wait_and_are_preserved(tmp_path):
    legacy = ImageStart(enabled=True, image='legacy-image-no-longer-executed', name='ancien.png')
    module = Module('Séquence', [Action('text', {'text': 'A'})], image_start=legacy)
    workflow = Workflow([module], image_start=legacy)
    path = tmp_path/'ancien.json'
    save_workflow(path, workflow)
    loaded = load_workflow(path)
    actions, mapping = loaded.compile()
    backend = FakeBackend()  # No capture method: execution must not try to see an image.
    assert execute(actions, backend, threading.Event(), lambda _: None, countdown=0) == 'Terminé'
    assert backend.calls == [('text', 'A')]
    assert asdict(loaded.modules[0].image_start) == asdict(legacy)
    assert asdict(loaded.image_start) == asdict(legacy)
    save_workflow(path, loaded)
    assert load_workflow(path).modules[0].image_start == legacy


def test_loop_with_old_start_options_runs_normally():
    module = Module('A', [Action('text', {'text': 'A'})], image_start=ImageStart(enabled=True))
    workflow = Workflow([module])
    workflow.connect(module.id, module.id)
    actions, _ = workflow.compile()
    backend = FakeBackend()
    assert execute(actions, backend, threading.Event(), lambda _: None, countdown=0, cycles=2) == 'Terminé'
    assert backend.calls == [('text', 'A')] * 2


def test_workflow_fullscreen_still_restores_editor():
    window = MainWindow()
    window.show()
    window.tabs.setCurrentIndex(1)
    app.processEvents()
    window.toggle_workflow_focus()
    app.processEvents()
    assert window.isFullScreen() and window.start_button.isVisible()
    window.edit_module(window.current_module)
    assert not window.focus_mode and window.tabs.currentIndex() == 0
    window.close()

import json
import pytest
from macro_studio.model import Action, DEFAULTS, IMAGE_KINDS, load, save, parse_keys

def test_roundtrip(tmp_path):
    actions = [Action.create(kind) for kind in DEFAULTS if kind not in IMAGE_KINDS]
    actions[2].params["text"] = "Été\n日本語"
    path = tmp_path / "macro.json"
    save(path, actions)
    assert load(path) == actions

@pytest.mark.parametrize("action", [Action("unknown", {}), Action("wait", {"seconds": -1}),
    Action("wait", {"seconds": float("nan")}), Action("wait", {"seconds": True}),
    Action("mouse", {"x": 0.5, "y": 1, "button": "left"}),
    Action("keyboard", {"keys": "ctrl++"}), Action("text", {"text": 1})])
def test_invalid_actions(action):
    with pytest.raises(ValueError):
        action.validate()

@pytest.mark.parametrize("data", [{"version": 2, "actions": []}, {"version": True, "actions": []},
    {"version": 1, "actions": [{"kind": "wait", "params": {}}]}, [],
    {"version": 1, "actions": "bad"}])
def test_reject_invalid_json(tmp_path, data):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load(path)

def test_invalid_save_preserves_original(tmp_path):
    path = tmp_path / "macro.json"
    save(path, [])
    before = path.read_bytes()
    with pytest.raises(ValueError):
        save(path, [Action("wait", {"seconds": -1})])
    assert path.read_bytes() == before

def test_keys():
    assert parse_keys("Ctrl + Shift + s") == ["ctrl", "shift", "s"]

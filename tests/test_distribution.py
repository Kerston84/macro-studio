from pathlib import Path
from PySide6.QtCore import QStandardPaths
from macro_studio import paths


def test_installed_documents_are_outside_program(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(QStandardPaths, 'writableLocation', lambda kind: str(tmp_path))
    folder = paths.prepare_workflow_folder()
    assert folder == tmp_path / 'Windows Macro Studio' / 'Workflows'
    assert folder.is_dir()


def test_development_keeps_existing_document_folder(monkeypatch):
    monkeypatch.delattr(paths.sys, 'frozen', raising=False)
    assert paths.default_workflow_folder() == Path(paths.__file__).resolve().parent.parent


def test_release_versions_are_consistent():
    import tomllib
    from macro_studio.version import VERSION
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    assert project['project']['version'] == VERSION

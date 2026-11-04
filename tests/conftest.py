"""Keep recent-file preferences isolated from the user's real library."""
import pytest
from PySide6.QtCore import QSettings

@pytest.fixture(autouse=True)
def isolated_document_library(tmp_path, monkeypatch):
    import macro_studio.launcher as launcher
    monkeypatch.setattr(launcher, "default_settings", lambda: QSettings(str(tmp_path / "recent.ini"), QSettings.IniFormat))
    monkeypatch.setattr(launcher, "PROJECT_FOLDER", tmp_path)

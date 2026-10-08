from pathlib import Path

import pytest

from backend import desktop_paths, launcher


def test_portable_keeps_existing_database_and_profile_root(tmp_path, monkeypatch):
    monkeypatch.delenv("QUICKMEMORY_DB", raising=False)
    monkeypatch.setattr(desktop_paths, "package_family_name", lambda: None)
    monkeypatch.setattr(launcher, "application_root", lambda: tmp_path)
    assert launcher.database_path() == tmp_path / "data" / "quickmemory.db"
    monkeypatch.setenv("QUICKMEMORY_DB", str(launcher.database_path()))
    assert desktop_paths.runtime_root() == tmp_path


def test_msix_uses_package_localstate_and_leaves_install_folder_alone(tmp_path, monkeypatch):
    monkeypatch.delenv("QUICKMEMORY_DB", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(desktop_paths, "package_family_name", lambda: "QuickMemory_testid")
    monkeypatch.setattr(launcher, "application_root", lambda: tmp_path / "readonly-install")
    expected = tmp_path / "local" / "Packages" / "QuickMemory_testid" / "LocalState"
    assert desktop_paths.runtime_root() == expected
    assert launcher.database_path() == expected / "data" / "quickmemory.db"
    monkeypatch.setenv("QUICKMEMORY_DB", str(launcher.database_path()))
    assert desktop_paths.runtime_root() == expected
    assert not (tmp_path / "readonly-install").exists()


def test_explicit_test_database_isolates_logs_and_webview(tmp_path, monkeypatch):
    selected = tmp_path / "qa" / "isolated.db"
    monkeypatch.setattr(desktop_paths, "package_family_name", lambda: None)
    monkeypatch.setenv("QUICKMEMORY_DB", str(selected))
    assert launcher.database_path() == selected
    assert desktop_paths.runtime_root() == selected.parent


def test_packaged_app_does_not_fall_back_to_readonly_install(tmp_path, monkeypatch):
    monkeypatch.delenv("QUICKMEMORY_DB", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(desktop_paths, "package_family_name", lambda: "QuickMemory_testid")
    with pytest.raises(RuntimeError, match="本地应用数据目录"):
        desktop_paths.runtime_root()

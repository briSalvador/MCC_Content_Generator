from pathlib import Path

from app import desktop


def test_desktop_storage_uses_per_user_directory(monkeypatch, tmp_path: Path) -> None:
    data_directory = tmp_path / "desktop-data"
    monkeypatch.setattr(desktop, "desktop_data_directory", lambda: data_directory)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    configured_directory = desktop.configure_desktop_storage()

    assert configured_directory == data_directory
    assert data_directory.is_dir()
    assert (data_directory / "generated_posters").is_dir()
    assert desktop.os.environ["DATABASE_URL"] == (
        f"sqlite:///{(data_directory / 'cyber_awareness.db').as_posix()}"
    )
    assert desktop.os.environ["POSTER_STORAGE_PATH"] == str(
        data_directory / "generated_posters"
    )

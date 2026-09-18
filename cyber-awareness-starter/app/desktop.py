"""Desktop launcher for the Cyber Awareness Platform.

The launcher starts the existing FastAPI application on a private, random
localhost port and displays it inside a native desktop window. Closing the
window also stops the local API server and scheduler.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn
from dotenv import load_dotenv


def desktop_data_directory() -> Path:
    """Return the operating system's normal per-user application-data folder."""
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "CyberAwarenessPlatform"


def desktop_program_directory() -> Path:
    """Return the source folder or the folder containing the packaged program."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def configure_desktop_storage() -> Path:
    """Use a writable, persistent desktop folder unless configuration overrides it."""
    load_dotenv(desktop_program_directory() / ".env", override=False)
    data_directory = desktop_data_directory()
    poster_directory = data_directory / "generated_posters"
    data_directory.mkdir(parents=True, exist_ok=True)
    poster_directory.mkdir(parents=True, exist_ok=True)

    if os.environ.get("DATABASE_URL") in {None, "sqlite:///./cyber_awareness.db"}:
        os.environ["DATABASE_URL"] = (
            f"sqlite:///{(data_directory / 'cyber_awareness.db').as_posix()}"
        )
    if os.environ.get("POSTER_STORAGE_PATH") in {None, "./generated_posters"}:
        os.environ["POSTER_STORAGE_PATH"] = str(poster_directory)
    return data_directory


def available_port() -> int:
    """Ask the operating system for an unused local TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_until_ready(
    url: str,
    server_thread: threading.Thread,
    timeout_seconds: float = 15,
) -> None:
    """Wait until the local API responds or raise a useful startup error."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not server_thread.is_alive():
            raise RuntimeError("The local application server stopped during startup.")
        try:
            with urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            time.sleep(0.1)
    raise TimeoutError("The desktop application did not start within 15 seconds.")
def main() -> None:
    """Start the local API and display it in a native application window."""
    configure_desktop_storage()

    # Import only after setting desktop storage so SQLAlchemy uses the right path.
    from app.main import app

    try:
        import webview
    except ImportError as exc:
        raise SystemExit(
            'Desktop support is not installed. Run: pip install -e ".[desktop]"'
        ) from exc

    port = available_port()
    base_url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        )
    )
    server_thread = threading.Thread(
        target=server.run,
        name="cyber-awareness-api",
        daemon=True,
    )
    server_thread.start()

    try:
        wait_until_ready(f"{base_url}/health", server_thread)
        webview.create_window(
            "Cyber Awareness Platform",
            base_url,
            width=1280,
            height=850,
            min_size=(900, 650),
            text_select=True,
        )
        webview.start(private_mode=False)
    finally:
        server.should_exit = True
        server_thread.join(timeout=5)


if __name__ == "__main__":
    main()

"""PyInstaller entry point for the packaged sidecar (Tauri runs it as `ziko-backend`)."""

from app.main import main

if __name__ == "__main__":
    main()

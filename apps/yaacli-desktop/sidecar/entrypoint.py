"""PyInstaller entry point for the YAACLI Desktop sidecar."""

import os

os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "__all__")

from yaacli.desktop.sidecar import main

if __name__ == "__main__":
    main()

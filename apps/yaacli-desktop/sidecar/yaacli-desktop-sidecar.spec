# PyInstaller specification for the self-contained macOS arm64 sidecar.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata


ROOT = Path(SPECPATH).parents[2]
ENTRYPOINT = ROOT / "apps" / "yaacli-desktop" / "sidecar" / "entrypoint.py"
COLLECT_PACKAGES = (
    "pymupdf",
    "ya_agent_sdk",
    "ya_oauth",
    "ya_oauth_provider",
    "yaacli",
)

datas = []
binaries = []
hiddenimports = []
for package in COLLECT_PACKAGES:
    datas.extend(collect_data_files(package))
for distribution in ("genai-prices", "pydantic-ai-slim", "yaacli"):
    datas.extend(copy_metadata(distribution))

analysis = Analysis(
    [str(ENTRYPOINT)],
    pathex=[str(ROOT / "packages" / "yaacli"), str(ROOT / "packages" / "ya-agent-sdk")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="yaacli-desktop-sidecar",
    console=True,
    target_arch="arm64",
)

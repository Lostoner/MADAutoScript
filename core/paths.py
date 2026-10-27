"""Project paths resolved from this source file, never from the launch cwd."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"
DEFAULT_PROFILE_DIR = CONFIG_DIR / "default"


def project_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    return (candidate if candidate.is_absolute() else REPO_ROOT / candidate).resolve()

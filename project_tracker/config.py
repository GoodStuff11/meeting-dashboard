"""Per-machine configuration: where `dashboard-data` and `HANDOFF.md` live.

`dashboard-config.json` sits at the project root. It is gitignored on purpose:
its paths are specific to this machine and this checkout, not something to
share. A fresh clone has no config file yet; `load()` falls back to the
defaults below and writes the file out so the choice this machine is making
is durable and visible rather than silently re-guessed on every run.
"""

import json
from pathlib import Path

# project_tracker/config.py -> project_tracker -> project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "dashboard-config.json"

DEFAULT_DATA_DIR = "dashboard-data"
DEFAULT_HANDOFF = "/home/jek354/research/68f6bef0eaaf5c0928a922c6/HANDOFF.md"


def defaults():
    return {"data_dir": DEFAULT_DATA_DIR, "handoff": DEFAULT_HANDOFF}


def load(config_path=None):
    """Return the config dict, writing the defaults to disk if none exists yet."""
    path = Path(config_path) if config_path else CONFIG_PATH
    if path.exists():
        return json.loads(path.read_text())
    cfg = defaults()
    save(cfg, path)
    return cfg


def save(cfg, config_path=None):
    path = Path(config_path) if config_path else CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n")


def resolve_data_dir(cfg, root=None):
    """A relative `data_dir` resolves against the project root; an absolute
    one is used as-is."""
    base = Path(root) if root else PROJECT_ROOT
    data_dir = Path(cfg.get("data_dir") or DEFAULT_DATA_DIR)
    if data_dir.is_absolute():
        return data_dir
    return base / data_dir


def resolve_handoff(cfg):
    return Path(cfg.get("handoff") or DEFAULT_HANDOFF)

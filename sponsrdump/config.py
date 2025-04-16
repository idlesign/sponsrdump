import json
from pathlib import Path

def load_config(config_path: Path):
    if not config_path or not config_path.exists():
        return {}
    with config_path.open('r') as f:
        return json.load(f)
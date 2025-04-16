import json
import re
from contextlib import contextmanager
from pathlib import Path

RE_FILENAME_INVALID = re.compile(r'[:?"/<>\\|*]')

PATH_BASE = Path.cwd()


@contextmanager
def configuration(fname: str, dumped: dict):
    fname = Path(fname)
    if fname.exists():
        with fname.open('r') as f:
            data = json.load(f)
        dumped.update(data.get('dumped', {}))

    try:
        yield
    finally:
        with fname.open('w') as f:
            json.dump({'dumped': dumped}, f, ensure_ascii=False, indent=2)

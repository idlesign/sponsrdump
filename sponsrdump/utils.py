import json
from contextlib import contextmanager
from pathlib import Path
import re

RE_FILENAME_INVALID = re.compile(r'[:?"/<>\\|*]')


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
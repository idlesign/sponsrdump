from pathlib import Path
from typing import ClassVar, TypeVar

from ..utils import MAX_FILENAME_LENGTH, truncate_filename

TypeTextConverter = TypeVar('TypeTextConverter', bound='TextConverter')


class TextConverter:

    alias: str = ''

    register: ClassVar[dict[str, TypeTextConverter]] = {}

    def __init_subclass__(cls):
        super().__init_subclass__()
        cls.register[cls.alias] = cls

    def _convert(self, value: str) -> str:
        raise NotImplementedError

    def dump(self, value: str, *, dest: Path) -> Path:
        target = dest.with_suffix(f'.{self.alias}')
        target = target.parent / truncate_filename(target.name, max_len=MAX_FILENAME_LENGTH)
        
        with target.open('w') as f:
            f.write(self._convert(value))

        return target

    @classmethod
    def spawn(cls, alias: str) -> 'TypeTextConverter':
        return cls.register[alias]()

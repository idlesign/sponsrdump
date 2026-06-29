from pathlib import Path
from typing import ClassVar, TypeVar

from ..utils import truncate_filename

TypeTextConverter = TypeVar('TypeTextConverter', bound='TextConverter')


class TextConverter:

    alias: str = ''

    register: ClassVar[dict[str, TypeTextConverter]] = {}

    def __init_subclass__(cls):
        super().__init_subclass__()
        cls.register[cls.alias] = cls

    def _convert(self, value: str) -> str:
        raise NotImplementedError

    def dump(self, value: str, *, dest: Path, max_len: int | None = None) -> Path:
        target = dest.with_suffix(f'.{self.alias}')
        if max_len is not None:
            target = target.parent / truncate_filename(target.name, max_len=max_len)

        with target.open('w') as f:
            f.write(self._convert(value))

        return target

    @classmethod
    def spawn(cls, alias: str) -> 'TypeTextConverter':
        return cls.register[alias]()

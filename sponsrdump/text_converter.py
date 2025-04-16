from pathlib import Path
from typing import Dict, TypeVar, Type

from html2text import html2text

TypeTextConverter = TypeVar('TypeTextConverter', bound='TextConverter')


class TextConverter:
    alias = ''
    register: Dict[str, Type[TypeTextConverter]] = {}

    def __init_subclass__(cls):
        cls.register[cls.alias] = cls

    def _convert(self, value: str):
        raise NotImplementedError

    def dump(self, value: str, *, dest: Path):
        target = dest.with_suffix(f'.{self.alias}')
        with open(target, 'w') as f:
            f.write(self._convert(value))
        return target

    @classmethod
    def spawn(cls, alias: str):
        return cls.register[alias]()


class HtmlConverter(TextConverter):
    alias = 'html'

    def _convert(self, value: str):
        return value


class MarkdownConverter(TextConverter):
    alias = 'md'

    def _convert(self, value: str):
        return html2text(value)

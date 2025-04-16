import logging
from typing import Dict, TypeVar, Type
from pathlib import Path
from html2text import html2text

logger = logging.getLogger(__name__)

TypeTextConverter = TypeVar('TypeTextConverter', bound='TextConverter')


class TextConverter:
    alias = ''
    register: Dict[str, Type[TypeTextConverter]] = {}

    def __init_subclass__(cls):
        cls.register[cls.alias] = cls

    def _convert(self, value: str) -> str:
        raise NotImplementedError

    def dump(self, value: str, *, dest: Path) -> Path:
        if not value.strip():
            logger.warning(f"Empty text content for {dest}")
            return dest

        logger.debug(f"Converting text for {dest}: {value[:100]}...")
        target = dest.with_suffix(f'.{self.alias}')
        logger.info(f"Writing text to {target}")
        target.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(target, 'w', encoding='utf-8') as f:
                f.write(self._convert(value))
            logger.debug(f"Text successfully written to {target}")
            return target
        except Exception as e:
            logger.error(f"Failed to write text to {target}: {str(e)}")
            raise

    @classmethod
    def spawn(cls, alias: str) -> 'TextConverter':
        try:
            return cls.register[alias]()
        except KeyError:
            logger.error(f"Unknown text format: {alias}")
            raise ValueError(f"Unsupported text format: {alias}")


class HtmlConverter(TextConverter):
    alias = 'html'

    def _convert(self, value: str) -> str:
        return value


class MarkdownConverter(TextConverter):
    alias = 'md'

    def _convert(self, value: str):
        return html2text(value).replace('\u200f', '').replace('\u200e', '')
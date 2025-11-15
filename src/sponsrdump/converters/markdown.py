from html2text import html2text

from .base import TextConverter


class MarkdownConverter(TextConverter):

    alias = 'md'

    def _convert(self, value: str) -> str:
        return html2text(value)

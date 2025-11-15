from .base import TextConverter


class HtmlConverter(TextConverter):

    alias = 'html'

    def _convert(self, value: str) -> str:
        return value

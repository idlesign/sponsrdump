import argparse
import logging

from .base import SponsrDumper, TextConverter, VideoPreference
from .converters import HtmlConverter

LOGGER = logging.getLogger(__name__)


def main(*arguments: str | None) -> None:

    parser = argparse.ArgumentParser()
    parser.add_argument(
        'project_url', help='URL проекта на sponsr.ru')
    parser.add_argument(
        '--debug', help='Вывести отладочную информацию', action='store_true')
    parser.add_argument(
        '--title', help='Фильтр заголовка для отбора статей', default='')
    parser.add_argument(
        '--to', help='Путь назначения для файлов', default='dump/')
    parser.add_argument(
        '--prefer-video', help='Предпочтительное разрешение видео', default='best')
    parser.add_argument(
        '--text-fmt', help=(
            f'Формат для текстовых данных. Варианты: {", ".join(sorted(TextConverter.register.keys()))}'),
        default=HtmlConverter.alias)
    parser.add_argument(
        '--no-audio', help='Не следует скачивать аудио', action='store_true')
    parser.add_argument(
        '--no-video', help='Не следует скачивать видео', action='store_true')
    parser.add_argument(
        '--no-text', help='Не следует скачивать текст', action='store_true')
    parser.add_argument(
        '--no-images', help='Не следует скачивать изображения', action='store_true')
    parser.add_argument(
        '--text-to-video', help='Следует ли создать видео с текстом статьи', action='store_true')

    args = parser.parse_args(arguments)

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format='%(levelname)-8s: %(message)s')

    dumper = SponsrDumper(args.project_url)

    filter_func = None

    if title := args.title.strip():
        filter_func = lambda post_info: title in post_info['post_title']  # noqa: E731

    dumper.search(func_filter=filter_func)
    dumper.dump(
        args.to,
        prefer_video=VideoPreference(frame=args.prefer_video),
        audio=not args.no_audio,
        video=not args.no_video,
        images=not args.no_images,
        text=False if args.no_text else args.text_fmt.lower(),
        text_to_video=args.text_to_video
    )


if __name__ == '__main__':
    main()

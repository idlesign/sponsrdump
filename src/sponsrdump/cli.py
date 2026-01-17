import argparse
import logging
from typing import Optional, Sequence

from .base import SponsrDumper, TextConverter, VideoPreference
from .converters import HtmlConverter

LOGGER = logging.getLogger(__name__)


def main(*arguments: str | None) -> None:

    parser = argparse.ArgumentParser()
    parser.add_argument('project_url', help='URL проекта на sponsr.ru')
    parser.add_argument('--debug', help='Вывести отладочную информацию', action='store_true')
    parser.add_argument('--post_id', help='Айди поста', default='')
    parser.add_argument('--title', help='Фильтр заголовка для отбор статей', default='')
    parser.add_argument('--to', help='Путь назначения для файлов', default='dump/')
    parser.add_argument('--prefer-video', help='Предпочтительное разрешение видео', default='best')
    parser.add_argument(
        '--text-fmt',
        help=f'Формат для текстовых данных. Варианты: {", ".join(sorted(TextConverter.register.keys()))}',
        default=HtmlConverter.alias
    )
    parser.add_argument('--no-audio', help='Не следует скачивать аудио', action='store_true')
    parser.add_argument('--no-video', help='Не следует скачивать видео', action='store_true')
    parser.add_argument('--no-text', help='Не следует скачивать текст', action='store_true')
    parser.add_argument('--no-images', help='Не следует скачивать изображения', action='store_true')
    parser.add_argument('--text-to-video', help='Следует ли создать видео с текстом статьи', action='store_true')

    args = parser.parse_args(arguments)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(levelname)-8s: %(message)s'
    )

    dumper = SponsrDumper(args.project_url)

    def post_id_filter(post_info: dict) -> bool:
        post_id_from_info = post_info.get('post_id', '')
        return str(args.post_id.strip()) == str(post_id_from_info)

    def title_filter(post_info: dict) -> bool:
        title = post_info.get('post_title', '')
        return args.title.strip() in title

    filter_func = None
    
    if args.post_id.strip():
        filter_func = post_id_filter
        logging.info(f"Используется фильтр по post_id: '{args.post_id.strip()}'")
    elif args.title.strip():
        filter_func = title_filter
        logging.info(f"Используется фильтр по заголовку: '{args.title.strip()}'")
    else:
        logging.info("Не определена функция фильтрации")

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

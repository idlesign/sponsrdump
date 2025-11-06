import logging
import re

from sponsrdump.base import SponsrDumper, VideoPreference

logging.basicConfig(level=logging.INFO, format='%(levelname)-8s: %(message)s')

RE_LESSON = re.compile(r'Урок (\d+)')


def filter_me(post_info: dict) -> bool:

    title = post_info['post_title']

    if matched := RE_LESSON.search(title):
        num = int(matched[1])
        if num > 226:
            return True

    return False


dumper = SponsrDumper('https://sponsr.ru/uzhukoffa_lessons/')
dumper.search(func_filter=filter_me)

dumper.dump(
    'dumped/',
    prefer_video=VideoPreference(frame='640x360'),
    audio=False,
    text=False,
    images=False,
    text_to_video=True,
)

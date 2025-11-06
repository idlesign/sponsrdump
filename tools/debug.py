import logging

from sponsrdump.base import SponsrDumper, VideoPreference

logging.basicConfig(level=logging.DEBUG, format='%(levelname)-8s: %(message)s')


def filter_me(post_info: dict):
    return 'Урок 386' in post_info['post_title']


dumper = SponsrDumper('https://sponsr.ru/uzhukoffa_lessons/')
dumper.search(func_filter=filter_me)

dumper.dump(
    'dumped/',
    prefer_video=VideoPreference(frame='640x360'),
    audio=False,
    text_to_video=False,
)

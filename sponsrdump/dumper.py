import logging
from pathlib import Path
from typing import Callable, List, Dict, Union
from .file_manager import FileManager
from .parser import PostParser
from .utils import configuration

logger = logging.getLogger(__name__)


class SponsrDumper:
    def __init__(self, url: str, ffmpeg_path: str = None, mp4decrypt_path: str = None, referer: str = None):
        self.url = url
        self.project_id = ''
        self._collected: List[dict] = []
        self._dumped: Dict[str, str] = {}
        self.file_manager = FileManager(ffmpeg_path, mp4decrypt_path, referer)
        self.parser = PostParser()

    def search(self, func_filter: Callable = None):
        logger.info(f'Searching data for {self.url} ...')
        self.project_id = self.parser.get_project_id(self.url)
        logger.debug(f'Project ID: {self.project_id}')
        self._collected = self.parser.collect_posts(self.project_id, func_filter)
        logger.info(f'Found articles: {len(self._collected)}')

    def dump(
            self,
            dest: Union[str, Path],
            *,
            prefer_video: str = 'best',
            audio: bool = True,
            video: bool = True,
            images: bool = True,
            text: Union[bool, str] = True,
            text_to_video: bool = True,
            parallel: int = 1
    ):
        logger.info(f'Start dump using video preference: {prefer_video} ...')
        dest = Path(dest).absolute()
        dest.mkdir(parents=True, exist_ok=True)

        realms = []
        if audio:
            realms.append('audio')
        if video:
            realms.append('video')
        if images:
            realms.append('images')
        if text:
            realms.append('text')

        with configuration('sponsrdump.json', self._dumped):
            for idx, post_info in enumerate(reversed(self._collected), 1):
                post_info['__idx'] = idx
                msg_prefix = f'[{idx}/{len(self._collected)} {round(100 * idx / len(self._collected), 1)}%] '

                for realm in realms:
                    for file_info in post_info['__files'][realm]:
                        file_id = file_info['file_id']
                        file_title = file_info['file_title']
                        msg_postfix = f'File {file_id} [{file_title}]:'
                        file_id_conf = f'f_{file_id}'

                        if file_id_conf in self._dumped:
                            logger.warning(f'{msg_prefix} Skipped {msg_postfix}')
                            continue

                        logger.info(f'{msg_prefix} Downloading {msg_postfix} ...')
                        filename = self.file_manager.generate_filename(post_info, file_info)
                        dest_filename = dest / filename

                        if filepath := file_info['file_path']:
                            self.file_manager.download_file(
                                filepath,
                                dest_filename,
                                file_info['file_type'],
                                prefer_video
                            )

                        if file_info['file_type'] == 'text' and text:
                            self.file_manager.handle_text(
                                file_info,
                                dest_filename,
                                text,
                                text_to_video
                            )

                        self._dumped[file_id_conf] = filename
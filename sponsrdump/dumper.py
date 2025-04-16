import logging
import shutil
from pathlib import Path
from typing import Callable, List, Dict, Union
from multiprocessing import Pool
from uuid import uuid4

from . import FileType
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

    def _process_file(self, args: tuple):
        """Обработка одного файла в отдельном процессе."""
        post_info, file_info, realm, dest, text, text_to_video, prefer_video, temp_dir = args
        file_id = file_info['file_id']
        file_title = file_info['file_title']
        file_id_conf = f'f_{file_id}'

        msg_prefix = f'[{post_info["__idx"]}/{len(self._collected)} {round(100 * post_info["__idx"] / len(self._collected), 1)}%] '
        msg_postfix = f'File {file_id} [{file_title}]:'

        if file_id_conf in self._dumped:
            logger.warning(f'{msg_prefix} Skipped {msg_postfix}')
            return file_id_conf, None

        logger.info(f'{msg_prefix} Processing {msg_postfix} ...')
        filename = self.file_manager.generate_filename(post_info, file_info, text)
        dest_filename = dest / filename

        try:
            if file_info.get('file_path'):
                self.file_manager.download_file(
                    file_info['file_path'],
                    dest_filename,
                    file_info['file_type'],
                    prefer_video,
                    temp_dir=temp_dir
                )
                if dest_filename.exists():
                    logger.debug(f"File saved to {dest_filename}")
                    return file_id_conf, filename
                else:
                    logger.error(f'{msg_prefix} Failed to save {dest_filename}')
                    return file_id_conf, None

            if file_info['file_type'] == FileType.TEXT and text:
                text_path = self.file_manager.handle_text(
                    file_info,
                    dest_filename,
                    text,
                    text_to_video,
                    temp_dir=temp_dir
                )
                if text_path and text_path.exists():
                    logger.debug(f"Text file registered: {text_path}")
                    return file_id_conf, filename
                else:
                    logger.error(f'{msg_prefix} Failed to save text to {dest_filename}')
                    return file_id_conf, None

        except Exception as e:
            logger.error(f'{msg_prefix} Error processing {msg_postfix}: {str(e)}')
            return file_id_conf, None

        return file_id_conf, None

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
        logger.info(f'Start dump using video preference: {prefer_video}, parallel processes: {parallel} ...')
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

        tasks = []
        for idx, post_info in enumerate(reversed(self._collected), 1):
            post_info['__idx'] = idx
            for realm in realms:
                for file_idx, file_info in enumerate(post_info['__files'][realm], 1):
                    file_info['__idx'] = file_idx
                    temp_dir = dest / f'temp_{uuid4()}'
                    tasks.append((
                        post_info,
                        file_info,
                        realm,
                        dest,
                        text,
                        text_to_video,
                        prefer_video,
                        temp_dir
                    ))

        with configuration('sponsrdump.json', self._dumped):
            try:
                if parallel > 1:
                    with Pool(processes=min(parallel, len(tasks))) as pool:
                        results = pool.imap_unordered(self._process_file, tasks)
                        for file_id_conf, filename in results:
                            if filename:
                                self._dumped[file_id_conf] = filename
                else:
                    for task in tasks:
                        file_id_conf, filename = self._process_file(task)
                        if filename:
                            self._dumped[file_id_conf] = filename
            finally:
                for task in tasks:
                    temp_dir = task[-1]
                    if temp_dir.exists():
                        shutil.rmtree(temp_dir, ignore_errors=True)
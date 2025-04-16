import logging
from pathlib import Path
from typing import Union
import shutil
from .video import Video
from .video_downloader import VideoDownloader
from .text_to_video import text_to_video
from .utils import RE_FILENAME_INVALID
from . import FileType

logger = logging.getLogger(__name__)


class FileManager:
    def __init__(self, ffmpeg_path: str = None, mp4decrypt_path: str = None, referer: str = None):
        self.ffmpeg_path = self._validate_path(ffmpeg_path, 'ffmpeg')
        self.mp4decrypt_path = self._validate_path(mp4decrypt_path, 'mp4decrypt')
        self.referer = referer

    def _validate_path(self, path: str, name: str):
        if path:
            path_obj = Path(path)
            if not path_obj.is_file():
                raise FileNotFoundError(f"{name} not found at {path}")
            return str(path_obj)

        # Автопоиск пути
        found_path = shutil.which(name)
        if not found_path:
            raise FileNotFoundError(
                f"{name} not found in PATH. Please install it or specify the path with --{name}-path."
            )
        return found_path

    def generate_filename(self, post_info: dict, file_info: dict):
        return RE_FILENAME_INVALID.sub(
            '',
            f"{post_info['__idx']:>03}. "
            f"{file_info['file_id']:>03}. "
            f"{post_info['post_title'].rstrip('.')}"
            f"{Path(file_info['file_title']).suffix}"
        )

    def download_file(self, url: str, dest: Path, file_type: str, prefer_video: str):
        if file_type == FileType.VIDEO and url.endswith('.mpd') and 'kinescope.io' in url:
            video_id = url.split('/')[-2]
            video = Video(video_id=video_id, referer_url=self.referer)
            with VideoDownloader(
                    video,
                    dest.parent / 'temp',
                    self.ffmpeg_path,
                    self.mp4decrypt_path
            ) as downloader:
                resolutions = downloader.get_resolutions()
                resolution = resolutions[-1] if prefer_video == 'best' else next(
                    (r for r in resolutions if str(r[1]) in prefer_video), resolutions[-1]
                )
                downloader.download(dest, resolution)
        else:
            self._download_non_video(url, dest, file_type)

    def _download_non_video(self, url: str, dest: Path, file_type: str):
        import requests
        stream = file_type != FileType.IMAGE
        headers = {'Referer': 'https://kinescope.io/'} if file_type == FileType.AUDIO else {}

        with requests.get(url, stream=stream, headers=headers) as response:
            response.raise_for_status()
            with open(dest, 'wb') as f:
                if stream:
                    for chunk in response.iter_content(chunk_size=1024):
                        f.write(chunk)
                else:
                    f.write(response.content)

    def handle_text(self, file_info: dict, dest: Path, text_format: Union[bool, str], text_to_video_flag: bool):
        from .text_converter import TextConverter, MarkdownConverter

        converter_alias_md = MarkdownConverter.alias
        converter_alias = converter_alias_md if isinstance(text_format, bool) else text_format

        if text_to_video_flag:
            conversion_required = converter_alias != converter_alias_md
            text_to_video_src = TextConverter.spawn(converter_alias_md).dump(file_info['__content'], dest=dest)
            text_to_video(text_to_video_src, self.ffmpeg_path)
            if conversion_required:
                text_to_video_src.unlink(missing_ok=True)

        if converter_alias != converter_alias_md:
            TextConverter.spawn(converter_alias).dump(file_info['__content'], dest=dest)
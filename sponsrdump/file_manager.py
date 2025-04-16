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

        found_path = shutil.which(name)
        if not found_path:
            raise FileNotFoundError(
                f"{name} not found in PATH. Please install it or specify the path with --{name}-path."
            )
        return found_path

    def generate_filename(self, post_info: dict, file_info: dict, text_format: Union[bool, str] = 'md'):
        if file_info['file_type'] == FileType.TEXT:
            extension = '.md' if isinstance(text_format, bool) or text_format == 'md' else '.html'
        else:
            extension = Path(file_info['file_title']).suffix

        return RE_FILENAME_INVALID.sub(
            '',
            f"{post_info['__idx']:>03}. "
            f"{file_info['file_id']:>03}. "
            f"{post_info['post_title'].rstrip('.')}"
            f"{extension}"
        )

    def download_file(self, url: str, dest: Path, file_type: str, prefer_video: str, temp_dir: Path):
        temp_dir.mkdir(parents=True, exist_ok=True)
        if file_type == FileType.VIDEO and url.endswith('.mpd') and 'kinescope.io' in url:
            video_id = url.split('/')[-2]
            video = Video(video_id=video_id, referer_url=self.referer)
            with VideoDownloader(
                    video,
                    temp_dir,
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

    def handle_text(self, file_info: dict, dest: Path, text_format: Union[bool, str], text_to_video_flag: bool,
                    temp_dir: Path):
        from .text_converter import TextConverter, MarkdownConverter

        if not file_info.get('__content'):
            logger.warning(f"No text content for file {file_info['file_id']} [{file_info['file_title']}]")
            return None

        converter_alias = MarkdownConverter.alias if isinstance(text_format, bool) else text_format.lower()
        logger.debug(f"Processing text content: {file_info['__content'][:100]}...")
        logger.info(f"Saving text as {converter_alias} to {dest}")

        try:
            text_path = TextConverter.spawn(converter_alias).dump(file_info['__content'], dest=dest)
            logger.debug(f"Text saved to {text_path}")
            if not text_path.exists():
                logger.error(f"Text file not created at {text_path}")
                return None

            if text_to_video_flag:
                md_converter = MarkdownConverter.alias
                temp_text_path = text_path
                if converter_alias != md_converter:
                    temp_text_path = dest.with_suffix('.md')
                    TextConverter.spawn(md_converter).dump(file_info['__content'], dest=temp_text_path)
                    logger.debug(f"Temporary MD file created at {temp_text_path}")
                logger.info(f"Generating text-to-video from {temp_text_path}")
                video_path = text_to_video(temp_text_path, self.ffmpeg_path, temp_dir=temp_dir)
                if converter_alias != md_converter and temp_text_path.exists():
                    temp_text_path.unlink(missing_ok=True)
                    logger.debug(f"Temporary MD file {temp_text_path} removed")
                if not video_path.exists():
                    logger.error(f"Failed to generate text-to-video at {video_path}")

            return text_path

        except Exception as e:
            logger.error(f"Failed to process text for {file_info['file_id']} [{file_info['file_title']}]: {str(e)}")
            return None
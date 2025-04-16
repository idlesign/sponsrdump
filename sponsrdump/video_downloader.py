import logging
import sys
from io import BytesIO
from pathlib import Path
from typing import Union, List, Tuple
from requests import Session
from requests.exceptions import ChunkedEncodingError
from shutil import copyfileobj, rmtree
from subprocess import Popen
from base64 import b64decode, b64encode
from tqdm import tqdm
from mpegdash.parser import MPEGDASHParser
from .video import Video
from .const import BASE_URL
from .exceptions import *

logger = logging.getLogger(__name__)


class VideoDownloader:
    def __init__(self, video: Video, temp_dir: Union[str, Path], ffmpeg_path: str, mp4decrypt_path: str):
        self.video = video
        self.temp_path = Path(temp_dir)
        self.temp_path.mkdir(parents=True, exist_ok=True)
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            meipass_path = Path(sys._MEIPASS).resolve()
            self.ffmpeg_path = meipass_path / 'ffmpeg'
            self.mp4decrypt_path = meipass_path / 'mp4decrypt'
        else:
            self.ffmpeg_path = ffmpeg_path
            self.mp4decrypt_path = mp4decrypt_path
        self.http = Session()
        self.mpd_master = self._fetch_mpd_master()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.temp_path.exists():
            rmtree(self.temp_path)

    def _merge_tracks(self, source_video: Union[str, Path], source_audio: Union[str, Path], target: Union[str, Path]):
        Popen((self.ffmpeg_path, '-i', str(source_video), '-i', str(source_audio),
               '-c', 'copy', str(target), '-y', '-loglevel', 'error')).communicate()

    def _decrypt_video(self, source: Union[str, Path], target: Union[str, Path], key: str):
        Popen((self.mp4decrypt_path, '--key', f'1:{key}', str(source), str(target))).communicate()

    def _get_license_key(self):
        if not self.mpd_master.periods[0].adaptation_sets[0].content_protections:
            return None
        kid = self.mpd_master.periods[0].adaptation_sets[0].content_protections[0].cenc_default_kid.replace('-', '')
        response = self.http.post(
            url=self.video.get_clearkey_license_url(),
            headers={'origin': BASE_URL},
            json={'kids': [b64encode(bytes.fromhex(kid)).decode().replace('=', '')], 'type': 'temporary'}
        ).json()
        return b64decode(response['keys'][0]['k'] + '==').hex()

    def _fetch_segment(self, segment_url: str, file):
        for _ in range(5):
            try:
                copyfileobj(BytesIO(self.http.get(segment_url, stream=True).content), file)
                return
            except ChunkedEncodingError:
                pass
        raise SegmentDownloadError(f'Failed to download segment {segment_url}')

    def _fetch_segments(self, segments_urls: List[str], filepath: Union[str, Path], label: str = ''):
        segments_urls = list(dict.fromkeys(segments_urls))
        with open(filepath, 'wb') as f:
            with tqdm(desc=label, total=len(segments_urls),
                      bar_format='{desc}: {percentage:3.0f}%|{bar:10}| [{n_fmt}/{total_fmt}]') as bar:
                for segment_url in segments_urls:
                    self._fetch_segment(segment_url, f)
                    bar.update()

    def _get_segments_urls(self, resolution: Tuple[int, int]):
        result = {}
        for adaptation_set in self.mpd_master.periods[0].adaptation_sets:
            resolutions = [(r.width, r.height) for r in adaptation_set.representations]
            idx = resolutions.index(resolution) if adaptation_set.representations[0].height else 0
            representation = adaptation_set.representations[idx]
            base_url = representation.base_urls[0].base_url_value if representation.base_urls else ''
            result[adaptation_set.mime_type] = [
                f'{base_url}{segment_url.media or ""}'
                for segment_url in representation.segment_lists[0].segment_urls
            ]
        return result

    def _fetch_mpd_master(self):
        return MPEGDASHParser.parse(self.http.get(
            self.video.get_mpd_master_playlist_url(),
            headers={'Referer': BASE_URL}
        ).text)

    def get_resolutions(self):
        for adaptation_set in self.mpd_master.periods[0].adaptation_sets:
            if adaptation_set.representations[0].height:
                return [(r.width, r.height) for r in sorted(adaptation_set.representations, key=lambda r: r.height)]
        return []

    def download(self, filepath: Union[str, Path], resolution: Tuple[int, int] = None):
        if not resolution:
            resolutions = self.get_resolutions()
            resolution = resolutions[-1] if resolutions else None
        if not resolution:
            raise ValueError('No valid resolutions')

        key = self._get_license_key()
        video_path = self.temp_path / f'{self.video.video_id}_video.mp4{".enc" if key else ""}'
        audio_path = self.temp_path / f'{self.video.video_id}_audio.mp4{".enc" if key else ""}'

        segments_urls = self._get_segments_urls(resolution)
        self._fetch_segments(segments_urls['video/mp4'], video_path, 'Video')
        self._fetch_segments(segments_urls['audio/mp4'], audio_path, 'Audio')

        if key:
            logger.info('Decrypting...')
            decrypted_video = self.temp_path / f'{self.video.video_id}_video.mp4'
            decrypted_audio = self.temp_path / f'{self.video.video_id}_audio.mp4'
            self._decrypt_video(video_path, decrypted_video, key)
            self._decrypt_video(audio_path, decrypted_audio, key)
            video_path, audio_path = decrypted_video, decrypted_audio

        filepath = Path(filepath).with_suffix('.mp4')
        filepath.parent.mkdir(parents=True, exist_ok=True)
        logger.info('Merging tracks...')
        self._merge_tracks(video_path, audio_path, filepath)
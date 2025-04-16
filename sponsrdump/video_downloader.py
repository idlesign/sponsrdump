import logging
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from typing import Union, List, Tuple
import requests
from requests.exceptions import ChunkedEncodingError
from shutil import copyfileobj, rmtree
from subprocess import Popen, CalledProcessError
from base64 import b64decode, b64encode
from tqdm import tqdm
from mpegdash.parser import MPEGDASHParser
from .video import Video
from .const import BASE_URL
from .exceptions import SegmentDownloadError

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
        self.http = requests.Session()
        self.http.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': BASE_URL})
        self.mpd_master = self._fetch_mpd_master()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.temp_path.exists():
            rmtree(self.temp_path, ignore_errors=True)

    def _run_cmd(self, cmd: list, cwd: Path = None):
        process = Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            logger.error(f"Command failed: {' '.join(str(c) for c in cmd)}\n{stderr}")
            raise CalledProcessError(process.returncode, cmd, stdout, stderr)
        return stdout, stderr

    def _merge_tracks(self, source_video: Path, source_audio: Path, target: Path):
        cmd = [
            self.ffmpeg_path, '-i', str(source_video), '-i', str(source_audio),
            '-c', 'copy', str(target), '-y', '-loglevel', 'error'
        ]
        self._run_cmd(cmd, cwd=self.temp_path)

    def _decrypt_video(self, source: Path, target: Path, key: str):
        cmd = [self.mp4decrypt_path, '--key', f'1:{key}', str(source), str(target)]
        self._run_cmd(cmd, cwd=self.temp_path)

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
        for attempt in range(5):
            try:
                with self.http.get(segment_url, stream=True) as response:
                    response.raise_for_status()
                    copyfileobj(BytesIO(response.content), file)
                return
            except (ChunkedEncodingError, requests.RequestException) as e:
                logger.warning(f"Attempt {attempt + 1}/5 failed for {segment_url}: {e}")
        raise SegmentDownloadError(f'Failed to download segment {segment_url}')

    def _fetch_segments(self, segments_urls: List[str], filepath: Path, label: str = ''):
        segments_urls = list(dict.fromkeys(segments_urls))
        with open(filepath, 'wb') as f:
            with tqdm(
                desc=label,
                total=len(segments_urls),
                bar_format='{desc}: {percentage:3.0f}%|{bar:10}| [{n_fmt}/{total_fmt}]',
                leave=False
            ) as bar:
                for segment_url in segments_urls:
                    self._fetch_segment(segment_url, f)
                    bar.update()

    def _get_segments_urls(self, resolution: Tuple[int, int]):
        result = {}
        for adaptation_set in self.mpd_master.periods[0].adaptation_sets:
            mime_type = adaptation_set.mime_type
            if mime_type not in ('video/mp4', 'audio/mp4'):
                continue
            resolutions = [(r.width, r.height) for r in adaptation_set.representations if r.width and r.height]
            idx = resolutions.index(resolution) if resolutions and mime_type == 'video/mp4' else 0
            representation = adaptation_set.representations[idx]
            base_url = representation.base_urls[0].base_url_value if representation.base_urls else ''
            segment_urls = representation.segment_lists[0].segment_urls if representation.segment_lists else []
            result[mime_type] = [f'{base_url}{segment_url.media or ""}' for segment_url in segment_urls]
        return result

    def _fetch_mpd_master(self):
        response = self.http.get(self.video.get_mpd_master_playlist_url())
        response.raise_for_status()
        return MPEGDASHParser.parse(response.text)

    def get_resolutions(self) -> List[Tuple[int, int]]:
        for adaptation_set in self.mpd_master.periods[0].adaptation_sets:
            if adaptation_set.mime_type == 'video/mp4' and adaptation_set.representations[0].height:
                return [(r.width, r.height) for r in sorted(
                    adaptation_set.representations, key=lambda r: (r.width * r.height) if r.width else 0
                )]
        return []

    def download(self, dest: Path, resolution: Tuple[int, int]):
        logger.info(f"Downloading video {self.video.video_id} at resolution {resolution} to {dest}")
        dest = Path(dest).with_suffix('.mp4')
        dest.parent.mkdir(parents=True, exist_ok=True)

        video_path = self.temp_path / f'video_{self.video.video_id}.mp4'
        audio_path = self.temp_path / f'audio_{self.video.video_id}.m4a'

        segments_urls = self._get_segments_urls(resolution)
        if not segments_urls.get('video/mp4') or not segments_urls.get('audio/mp4'):
            raise ValueError("No video or audio segments found")

        self._fetch_segments(segments_urls['video/mp4'], video_path, 'Video')
        self._fetch_segments(segments_urls['audio/mp4'], audio_path, 'Audio')

        key = self._get_license_key()
        if key:
            logger.info('Decrypting video and audio...')
            decrypted_video = self.temp_path / f'video_dec_{self.video.video_id}.mp4'
            decrypted_audio = self.temp_path / f'audio_dec_{self.video.video_id}.m4a'
            self._decrypt_video(video_path, decrypted_video, key)
            self._decrypt_video(audio_path, decrypted_audio, key)
            video_path, audio_path = decrypted_video, decrypted_audio

        logger.info('Merging video and audio tracks...')
        self._merge_tracks(video_path, audio_path, dest)
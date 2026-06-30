import json
import re
import shlex
import shutil
from collections import defaultdict
from collections.abc import Callable
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from pprint import pformat
from typing import ClassVar, NamedTuple
from urllib.parse import parse_qs, urljoin, urlparse
from uuid import uuid4

import requests
from bs4 import BeautifulSoup
from lxml import etree
from requests import HTTPError
from requests.cookies import cookiejar_from_dict

from .converters import MarkdownConverter, TextConverter
from .exceptions import SponsrDumperError
from .utils import LOGGER, MAX_FILENAME_LENGTH, call, concat_files, convert_text_to_video, progress, truncate_filename

RE_FILENAME_INVALID = re.compile(r'[:?"/<>\\|*]')
RE_PROJECT_ID = re.compile(r'"project_id":\s*(\d+)\s*,')
RE_PLAYER_OPTIONS = re.compile(r'var playerOptions\s*=\s*(\{.*?\});', re.DOTALL)
RE_HLS_STREAM = re.compile(r'#EXT-X-STREAM-INF:[^\n]*?RESOLUTION=(\d+x\d+)[^\n]*\n([^\n#][^\n]*)')
RE_HLS_AUDIO = re.compile(r'#EXT-X-MEDIA:TYPE=AUDIO[^\n]*?URI="([^"]+)"')
RE_HLS_MAP = re.compile(r'#EXT-X-MAP:URI="([^"]+)"(?:,BYTERANGE="(\d+)(?:@(\d+))?")?')
RE_HLS_BYTERANGE = re.compile(r'#EXT-X-BYTERANGE:(\d+)(?:@(\d+))?')


def sort_idents(container: dict) -> dict:
    # idents are 'WxH' for video or a numeric string for audio; sort ascending by the leading number
    return dict(sorted(container.items(), key=lambda items: int(items[0].split('x', 1)[0])))


class FileType(Enum):

    TEXT = 0
    VIDEO = 1
    AUDIO = 2
    IMAGE = 3
    ATTACH = 4


_CLEANUP = True


class VideoPreference(NamedTuple):

    frame: str = 'best'
    sound: str = 'best'


class SponsrDumper:

    _url_base: str = 'https://sponsr.ru'

    _fname_conf: str = 'sponsrdump.json'
    _fname_auth: str = 'sponsrdump_auth.txt'

    _headers: ClassVar[dict] = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0',
        'Accept-Encoding': 'gzip, deflate',
        'Accept-Language': 'ru,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'cross-site',
        'sec-ch-ua': '"Not.A/Brand";v="8", "Chromium";v="114", "YaBrowser";v="23"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
    }

    def __init__(self, url: str):
        self.url = url
        self.project_id: str = ''
        self._collected: list[dict] = []
        self._dumped: dict[str, str] = {}

        session = requests.Session()
        session.headers = self._headers

        self._session = session

        self._auth_read()

    @classmethod
    def _concat_chunks(cls, *, src: Path, suffix: str) -> Path:
        return concat_files(src=src, suffix=suffix, target_name=f'{uuid4()}.mp4')

    @classmethod
    def _get_soup(cls, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, 'lxml')

    @staticmethod
    def _kinescope_embed_url(src: str | None) -> str:
        # an iframe src like 'https://kinescope.io/<embed_id>' points to a player page
        # exposing signed manifests; legacy '/post/video/?...' forms are not embed urls
        if not src:
            return ''
        parsed = urlparse(src)
        path = parsed.path.strip('/')
        if parsed.netloc == 'kinescope.io' and path and '/' not in path:
            return f'https://kinescope.io/{path}'
        return ''

    @classmethod
    def _mpd_parse(cls, fpath: Path):

        with fpath.open() as f:
            xml = f.read()

        xml = re.sub('xmlns(:[^=]*)?="[^"]+"', '', xml)

        root = etree.fromstring(xml, etree.XMLParser(
            no_network=True,
            huge_tree=True,
            remove_blank_text=True,
            resolve_entities=False,
        ))

        video = defaultdict(list)
        trash = defaultdict(list)
        audio = defaultdict(list)

        for aset in root.findall('.//AdaptationSet'):
            mime = aset.attrib['mimeType']

            if mime.startswith('video'):
                bucket = video

            elif mime.startswith('audio'):
                bucket = audio

            else:
                bucket = trash

            for repres in aset.findall('Representation'):
                repres_attrib = repres.attrib

                LOGGER.debug(f'Representation found: {repres_attrib}')

                if audio_rate := repres_attrib.get('audioSamplingRate'):
                    ident = audio_rate

                else:
                    ident = f"{repres_attrib['width']}x{repres_attrib['height']}"

                base_url = repres.find('BaseURL').text

                for segment_element in repres.find('SegmentList'):
                    attrib = segment_element.attrib
                    url = attrib.get('sourceURL') or attrib.get('media')
                    range = attrib.get('range') or attrib.get('mediaRange')

                    if url:
                        # prepend base
                        url = f'{base_url}{url}'

                    elif range:
                        # range without url. typically for audio
                        url = base_url

                    if url and url not in bucket[ident]:
                        bucket[ident].append((url, range))

        video = sort_idents(video)
        audio = sort_idents(audio)

        LOGGER.info(f"  Found media formats: video - {', '.join(video)}; audio - {', '.join(audio)}.")

        return video, audio

    def _kinescope_get(self, url: str, *, referer: str) -> requests.Response:
        response = self._session.get(url, headers={'Referer': referer})
        response.raise_for_status()
        return response

    @staticmethod
    def _hls_range(length: str, offset: str | None, cursor: dict) -> str:
        # HLS byte range is 'length@offset' (offset optional, then continues the previous sub-range).
        # Convert to an inclusive 'start-end' string as used by Range: bytes=.
        length = int(length)
        start = int(offset) if offset is not None else cursor.get('pos', 0)
        end = start + length - 1
        cursor['pos'] = end + 1
        return f'{start}-{end}'

    def _m3u8_segments(self, media_url: str) -> list[tuple[str, str]]:
        # Fetch a media playlist and return [(segment_url, 'start-end'), ...] with the init segment first.
        media = self._kinescope_get(media_url, referer='https://kinescope.io/').text

        segments: list[tuple[str, str]] = []
        cursors: dict[str, dict] = defaultdict(dict)

        if matched := RE_HLS_MAP.search(media):
            init_url = urljoin(media_url, matched[1])
            init_range = self._hls_range(matched[2], matched[3], cursors[init_url]) if matched[2] else ''
            segments.append((init_url, init_range))

        pending_range = ''
        for line in media.splitlines():
            line = line.strip()

            if byterange := RE_HLS_BYTERANGE.match(line):
                pending_range = (byterange[1], byterange[2])

            elif line and not line.startswith('#'):
                seg_url = urljoin(media_url, line)
                rng = self._hls_range(*pending_range, cursors[seg_url]) if pending_range else ''
                segments.append((seg_url, rng))
                pending_range = ''

        return segments

    def _m3u8_parse(self, master_text: str, master_url: str):

        video = defaultdict(list)
        audio = defaultdict(list)

        for ident, media_rel in RE_HLS_STREAM.findall(master_text):
            media_url = urljoin(master_url, media_rel.strip())
            video[ident].extend(self._m3u8_segments(media_url))

        for media_rel in RE_HLS_AUDIO.findall(master_text):
            media_url = urljoin(master_url, media_rel.strip())
            # audio idents must be numeric-leading for sort_idents; a single rendition is selected via 'best'
            audio[f'{len(audio)}'].extend(self._m3u8_segments(media_url))

        video = sort_idents(video)
        audio = sort_idents(audio)

        LOGGER.info(f"  Found media formats: video - {', '.join(video)}; audio - {', '.join(audio)}.")

        return video, audio

    def _resolve_kinescope(self, embed_url: str, *, dest: Path, prefer_video: VideoPreference):
        # Fetch the kinescope embed page, read the signed manifest from playerOptions, then download.
        html = self._kinescope_get(embed_url, referer=f'{self._url_base}/').text

        matched = RE_PLAYER_OPTIONS.search(html)
        if not matched:
            raise SponsrDumperError(f'Unable to find player options at {embed_url}')

        sources = json.loads(matched[1])['playlist'][0]['sources']

        if hls_src := (sources.get('hls') or {}).get('src'):
            master = self._kinescope_get(hls_src, referer='https://kinescope.io/').text
            video, audio = self._m3u8_parse(master, hls_src)
            self._media_process(video, audio, dest=dest, prefer_video=prefer_video)

        elif mpd_src := (sources.get('dash') or {}).get('src'):
            # fall back to the signed DASH manifest
            self._download_file(mpd_src, dest=dest, prefer_video=prefer_video)

        else:
            raise SponsrDumperError(f'No playable HLS/DASH source found at {embed_url}')

    def _download_file(
            self,
            url: str,
            *,
            dest: Path,
            stream: bool = True,
            prefer_video: VideoPreference,
            range: str = ''
    ):

        if not url.startswith('http'):
            url = f'{self._url_base}{url}'

        parsed = urlparse(url)

        # a bare kinescope embed url (https://kinescope.io/<embed_id>) — resolve the signed manifest
        if not range and parsed.netloc == 'kinescope.io' and parsed.path.strip('/').count('/') == 0 \
                and not parsed.path.endswith('.mpd'):
            self._resolve_kinescope(url, dest=dest, prefer_video=prefer_video)
            return

        headers = {}

        if range:
            headers.update({
                'Accept': '*/*',
                'Accept-Encoding': 'identity',
                'Connection': 'keep-alive',
                'Range': f'bytes={range}',
                'Referer': 'https://kinescope.io/',
            })

        is_mpd = parsed.path.endswith('.mpd')
        dest_tmp = None

        if is_mpd:
            headers['Referer'] = (
                'https://kinescope.io/203245765?enableIframeApi'
                '&playerId=player&size%5Bwidth%5D=100%25&size%5Bheight%5D=100%25&preload=none'
            )
            dest_tmp = dest.with_suffix('.tmp')

        with self._session.get(url, stream=stream, headers=headers) as response:

            if response.status_code == 403:
                LOGGER.error('Access denied.')

            response.raise_for_status()

            with Path(dest_tmp or dest).open('wb') as f:
                f.writelines(response.iter_content(chunk_size=1024))

        if is_mpd:
            try:
                # download mpd chunks
                self._mpd_process(mpd=dest_tmp, dest=dest, prefer_video=prefer_video)

            finally:
                _CLEANUP and dest_tmp.unlink(missing_ok=True)

    def _mpd_process(self, *, mpd: Path, dest: Path, prefer_video: VideoPreference):
        video, audio = self._mpd_parse(mpd)
        self._media_process(video, audio, dest=dest, prefer_video=prefer_video, work_dir=mpd.parent)

    def _media_process(
            self,
            video: dict,
            audio: dict,
            *,
            dest: Path,
            prefer_video: VideoPreference,
            work_dir: Path | None = None,
    ):
        dest_tmp = ((work_dir or dest.parent) / 'tmp').absolute()
        dest_tmp.mkdir(parents=True, exist_ok=True)

        def download_all(urls: list[tuple[str, str]], *, suffix: str, label: str):

            total = len(urls)
            for idx, (url, range) in enumerate(urls, 1):
                file_dest = dest_tmp / f'{idx:>05}_{suffix}{dest.suffix}'
                self._download_file(url, dest=file_dest, prefer_video=prefer_video, range=range)
                progress(label, idx, total)

        try:
            videos = video.get(prefer_video.frame) or (video[list(video.keys())[-1]] if video else [])
            audios = audio.get(prefer_video.sound) or (audio[list(audio.keys())[-1]] if audio else [])

            LOGGER.debug(f'Found: video {len(videos)}; audio {len(audios)}.')

            download_all(videos, suffix='vid', label='video')

            inputs = []
            if videos:
                LOGGER.info('  Joining video chunks ...')
                inputs.append(self._concat_chunks(src=dest_tmp, suffix='vid'))

            download_all(audios, suffix='aud', label='audio')

            if audios:
                LOGGER.info('  Joining audio chunks ...')
                inputs.append(self._concat_chunks(src=dest_tmp, suffix='aud'))

            if inputs:
                # join video + audio (only the streams that are actually present)
                LOGGER.info('  Compiling final video ...')
                args_in = ' '.join(f'-i "{src}"' for src in inputs)
                call(
                    f'ffmpeg {args_in} -c copy {shlex.quote(str(dest))}',
                    cwd=dest_tmp,
                )

        finally:
            _CLEANUP and shutil.rmtree(dest_tmp)

    def _get_response(self, url: str, *, xhr: bool = False) -> requests.Response:

        if not url.startswith('http'):
            url = f'{self._url_base}{url}'

        headers = {}

        if xhr:
            headers.update({
                'X-Requested-With': 'XMLHttpRequest',
                'e': 'true',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Sec-Fetch-Site': 'same-origin',
            })

        response = self._session.get(url, headers=headers)
        response.raise_for_status()

        return response

    def _normalize_files(self, post: dict):

        audio = []
        video = []
        text = []
        images = []
        attaches = []

        post['__files'] = {
            'audio': audio,
            'video': video,
            'text': text,
            'images': images,
            'attaches': attaches,
        }

        for file_info in post.get('files') or []:
            category = file_info['file_category']

            match category:
                case 'podcast':
                    if not file_info['file_duration']:
                        LOGGER.debug(f'Probably missing {file_info["file_link"]}. Skipped.')
                        continue

                    file_info['file_type'] = FileType.AUDIO
                    audio.append(file_info)

                case 'attach':
                    file_info['file_type'] = FileType.ATTACH
                    attaches.append(file_info)

                case _:
                    raise AssertionError(f"Unsupported file category '{category}' found at {post}")


        post_title = post['post_title'].rstrip('.')
        post_text = post.get('post_text', post.get('post_small_text', '')).strip()

        text.append({
            'file_id': f"{post['post_id']}",
            'file_title': f'{post_title}.html',
            'file_path': '',
            'file_type': FileType.TEXT,
            '__content': post_text,
        })

        soup = self._get_soup(post_text)

        for image in soup.find_all('img'):
            if (src := image['src']) and (image_name := Path(urlparse(src).path).name):
                images.append({  # noqa: PERF401
                    'file_id': image_name,
                    'file_title': image_name,
                    'file_path': src,
                    'file_type': FileType.IMAGE,
                })

        for iframe in soup.find_all('iframe'):

            attr_src = iframe.get('data-url') or iframe.get('src')  # 'src' is legacy location

            if 'video' in attr_src and (file_id := parse_qs(urlparse(attr_src).query).get('video_id')):
                # workaround bogus links like /post/video/?video_id=xxx?poster_id=yyy
                file_id = file_id[0].partition('?')[0]

                # prefer the kinescope embed url from 'src' — it yields a signed (HLS/DASH) manifest;
                # fall back to the legacy unsigned master.mpd when no embed id is present
                embed_url = self._kinescope_embed_url(iframe.get('src'))
                file_path = embed_url or f'https://kinescope.io/{file_id}/master.mpd'

                LOGGER.debug(f'Video source url: {file_path}')

                video.append({
                    'file_id': file_id,
                    'file_title': f'{post_title}.mp4',
                    'file_path': file_path,
                    'file_type': FileType.VIDEO,
                })

    def _collect_posts(self, *, project_id: str, func_filter: Callable[[dict], bool] | None = None) -> list[dict]:

        posts_all = []
        rows_seen = 0
        rows_total = 1

        func_filter = func_filter or (lambda post_info: post_info)

        while rows_seen < rows_total:
            data = self._get_response(f'/project/{project_id}/more-posts/?offset={rows_seen}').json()['response']
            posts_current = data['rows']

            rows_seen += len(posts_current)
            posts_current = [post for post in posts_current if func_filter(post)]

            for post in posts_current:
                self._normalize_files(post)

            posts_all.extend(posts_current)
            rows_total = data['rows_count']

            LOGGER.debug(f'Searched {rows_seen}/{rows_total} ...')

        return posts_all

    def _get_project_id(self) -> str:

        html = self._get_response(self.url).text
        matched = RE_PROJECT_ID.search(html)

        if not matched:
            raise SponsrDumperError('Unable to get project ID')

        project_id = matched[1]

        return project_id

    def _auth_read(self):

        path = Path(self._fname_auth)

        if not path.exists():
            raise SponsrDumperError(f'File {path} is not found in the current directory.')

        try:

            with path.open() as f:
                data = f.read().strip().rstrip(';')
                self._session.cookies = cookiejar_from_dict(
                    dict(
                        line.strip().split('=', 1)
                        for line in data.split(';')
                    )
                )

        except ValueError:
            raise SponsrDumperError(f'File {path} contents is not valid.') from None

    def _auth_write(self):
        with Path(self._fname_auth).open('w') as f:
            return f.write(
                ';'.join([
                    f'{key}={val}'
                    for key, val in self._session.cookies.get_dict().items()
                ])
            )

    def _conf_load(self):

        fname = Path(self._fname_conf)

        if not fname.exists():
            self._conf_save()

        else:
            LOGGER.info(f'Configuration is loaded from {fname} ...')

        with fname.open() as f:
            data = json.load(f)

        self._dumped = data.get('dumped', {})

    def _conf_save(self):

        fname = Path(self._fname_conf)

        with fname.open('w') as f:
            json.dump(
                {
                    'dumped': self._dumped,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

    @contextmanager
    def _configuration(self):
        self._conf_load()
        try:
            yield

        finally:
            self._conf_save()

    def search(self, *, func_filter: Callable[[dict], bool] | None = None) -> int:

        LOGGER.info(f'Searching data for {self.url} ...')

        project_id = self._get_project_id()

        self.project_id = project_id

        LOGGER.debug(f'Project ID: {project_id}')

        collected = self._collect_posts(project_id=project_id, func_filter=func_filter)

        self._collected = collected
        found = len(collected)

        LOGGER.info(f'Found articles: {found}')

        return found

    def dump(
        self,
        dest: str | Path,
        *,
        func_filename: Callable[[dict], bool] | None = None,
        reverse: bool = True,
        audio: bool = True,
        video: bool = True,
        images: bool = True,
        attaches: bool = True,
        text: bool | str = True,
        text_to_video: bool = True,
        prefer_video: VideoPreference | None = None,
    ):
        prefer_video = prefer_video or VideoPreference()

        LOGGER.info(f'Start dump using preference: {prefer_video} ...')

        func_filename = func_filename or (
            lambda post_inf, file_inf: RE_FILENAME_INVALID.sub(
                '',
                f"{post_inf['__idx']:>03}. "
                f"{file_inf['__idx']:>03}. "
                f"{post_inf['post_title'].rstrip('.')}"
                f"{Path(file_inf['file_title']).suffix}"
            )
        )

        dest = Path(dest).absolute()
        dest.mkdir(parents=True, exist_ok=True)

        collected = self._collected
        if reverse:
            collected = list(reversed(collected))

        realms = []

        audio and realms.append('audio')
        video and realms.append('video')
        images and realms.append('images')
        text and realms.append('text')
        attaches and realms.append('attaches')

        with self._configuration():

            post_idx = 0
            posts_total = len(collected)

            for idx, post_info in enumerate(collected, 1):

                # 'post_id' 'level_id' 'post_date' 'post_title' 'post_text' 'post_url' 'tags'
                file_idx = 0
                post_idx += 1
                post_info['__idx'] = post_idx

                msg_prefix = f'[{idx}/{posts_total} {round(100 * idx / posts_total, 1)}%] '

                for realm in realms:

                    for file_info in post_info['__files'][realm]:

                        # 'files': 'file_id' 'file_path' 'file_title' 'file_link' 'file_duration' 'file_order'

                        file_id = file_info['file_id']
                        file_title = file_info['file_title']

                        msg_postfix = f'File {file_id} [{file_title}]:'

                        file_id_conf = f'f_{file_id}'

                        file_idx += 1
                        file_info['__idx'] = file_idx

                        if file_id_conf in self._dumped:
                            LOGGER.warning(f'{msg_prefix} Skipped {msg_postfix}')
                            continue

                        LOGGER.info(f'{msg_prefix} Downloading {msg_postfix}  ...')
                        file_type = file_info['file_type']

                        filename = truncate_filename(
                            func_filename(post_info, file_info),
                            max_len=MAX_FILENAME_LENGTH,
                        )
                        dest_filename = dest / filename

                        if filepath := file_info['file_path']:

                            try:
                                self._download_file(
                                    filepath,
                                    dest=dest_filename,
                                    stream=file_type is not FileType.IMAGE,
                                    prefer_video=prefer_video
                                )

                            except HTTPError:
                                LOGGER.debug('%s', pformat(file_info, indent=2))
                                raise

                        if file_type is FileType.TEXT and text:

                            converter_alias_md = MarkdownConverter.alias
                            converter_alias = converter_alias_md if isinstance(text, bool) else text

                            if text_to_video:

                                conversion_required = converter_alias != converter_alias_md

                                text_to_video_src_filename = TextConverter.spawn(
                                    converter_alias_md
                                ).dump(file_info['__content'], dest=dest_filename)

                                convert_text_to_video(text_to_video_src_filename)

                                if conversion_required:
                                    text_to_video_src_filename.unlink(missing_ok=True)

                            if converter_alias != converter_alias_md:

                                dest_filename = TextConverter.spawn(
                                    converter_alias
                                ).dump(file_info['__content'], dest=dest_filename)

                            filename = dest_filename.name

                        self._dumped[file_id_conf] = filename

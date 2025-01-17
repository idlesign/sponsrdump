#! /usr/bin/env python3
import json
import logging
import os
import re
import shlex
import shutil
from collections import defaultdict
from contextlib import contextmanager
from os import listdir
from pathlib import Path
from pprint import pformat
from subprocess import Popen, PIPE
from textwrap import wrap
from typing import List, Callable, Union, Dict, NamedTuple, Tuple, TypeVar, Type
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import requests
from bs4 import BeautifulSoup
from html2text import html2text
from lxml import etree
from requests import HTTPError
from requests.cookies import cookiejar_from_dict

LOGGER = logging.getLogger(__name__)
PATH_BASE = Path(__file__).parent.absolute()
RE_FILENAME_INVALID = re.compile(r'[:?"/<>\\|*]')

_CLEANUP = True


TypeTextConverter = TypeVar('TypeTextConverter', bound='TextConverter')


class TextConverter:

    alias: str = ''

    register: Dict[str, Type[TypeTextConverter]] = {}

    def __init_subclass__(cls):
        super().__init_subclass__()
        cls.register[cls.alias] = cls

    def _convert(self, value: str) -> str:
        raise NotImplementedError

    def dump(self, value: str, *, dest: Path) -> Path:
        target = dest.with_suffix(f'.{self.alias}')
        with open(target, 'w') as f:
            f.write(self._convert(value))
        return target

    @classmethod
    def spawn(cls, alias: str) -> 'TypeTextConverter':
        return cls.register[alias]()


class HtmlConverter(TextConverter):

    alias = 'html'

    def _convert(self, value: str) -> str:
        return value


class TxtConverter(TextConverter):

    alias = 'txt'

    def _convert(self, value: str) -> str:
        return html2text(value)


class VideoPreference(NamedTuple):

    frame: str = 'best'
    sound: str = 'best'


@contextmanager
def chdir(where: Path):

    current_dir = Path.cwd()

    try:
        os.chdir(where)
        yield

    finally:
        os.chdir(current_dir)


class SponsrDumperError(Exception):
    """Base exception."""


class SponsrDumper:

    _url_base: str = 'https://sponsr.ru'

    _fname_conf: str = 'sponsrdump.json'
    _fname_auth: str = 'sponsrdump_auth.txt'

    _headers: dict = {
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
        self._collected: List[dict] = []
        self._dumped: Dict[str, str] = {}

        session = requests.Session()
        session.headers = self._headers

        self._session = session

        self._auth_read()

    @classmethod
    def text_to_video(cls, src: Path) -> Path:

        font = 'tahoma.ttf'
        line_width = 80
        sec_per_line = 3
        sec_plus = 5
        line_space = 20
        font_size = 25

        fname_stem = src.stem

        path_bg = PATH_BASE / 'bg.png'
        path_tmp_bg = src.with_suffix('.mp4').with_stem(f'{fname_stem}_bg')
        path_tmp_bg.unlink(missing_ok=True)

        path_tmp_text = src.with_suffix('.txt').with_stem(f'{fname_stem}_txt')
        path_tmp_text.unlink(missing_ok=True)

        path_target = src.with_suffix('.mp4').with_stem(f'{fname_stem} [txt]')
        path_target.unlink(missing_ok=True)

        LOGGER.info(f'  Generating text video: {path_target} ...')

        with open(src) as f:
            text = f.read()

        text = text.strip().strip('_ ').strip().replace('\u200e', '').replace('\u200f', '')

        lines = []
        for line in text.splitlines():
            lines.extend(wrap(line, width=line_width))

        vid_len = (len(lines) * sec_per_line) + sec_plus

        with open(path_tmp_text, 'w') as f:
            f.write('\r\n'.join(lines))

        cls.call(f'ffmpeg -loop 1 -t {vid_len} -i "{path_bg}" "{path_tmp_bg}"', cwd=src.parent)

        try:
            cls.call(
                (
                    f'ffmpeg -i "{path_tmp_bg}" -filter_complex "'
                    '[0]split[txt][orig];'
                    '[txt]drawtext='
                    f'fontfile={font}:'
                    f'fontsize={font_size}:'
                    'fontcolor=white:'
                    f'x=(w-text_w)/2+{line_space}:'
                    f'y=h-{line_space}*t:'
                    f'textfile=\'{path_tmp_text}\':'
                    'bordercolor=black:'
                    f'line_spacing={line_space}:'
                    'borderw=3[txt];'
                    '[orig]crop=iw:50:0:0[orig];'
                    '[txt][orig]overlay" '
                    f'-c:v libx264 -y -preset ultrafast -t {vid_len} "{path_target}"'
                ),
                cwd=src.parent,
            )

        finally:
            path_tmp_bg.unlink(missing_ok=True)
            path_tmp_text.unlink(missing_ok=True)

        return path_target

    @classmethod
    def call(cls, cmd: str, *, cwd: Path, capture_out: bool = True):
        prc = Popen(cmd, cwd=cwd, shell=True, stdout=PIPE if capture_out else None, stderr=PIPE)
        out, err = [item.decode() if item else '' for item in prc.communicate()]

        if prc.returncode:
            raise SponsrDumperError(f'Command error:\n{cmd}\n\n{out}\n\n{err}\n----------')

    @classmethod
    def _concat_chunks(cls, *, src: Path, suffix: str) -> Path:

        with chdir(src):
            src_files = sorted([f'{fname}' for fname in listdir(src) if f'_{suffix}.' in fname])
            target = f'{uuid4()}.mp4'
            src_files_str = '" "'.join(src_files)
            cls.call(f'cat "{src_files_str}" > "{target}"', cwd=src)

            for src_file in src_files:
                (src / src_file).unlink()

        return src / target

    @classmethod
    def _get_soup(cls, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, 'lxml')

    @classmethod
    def _mpd_parse(cls, fpath: Path):

        with open(fpath) as f:
            xml = f.read()

        xml = re.sub("xmlns(:[^=]*)?='[^']+'", '', xml)

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

                if audio_rate := repres.attrib.get('audioSamplingRate'):
                    ident = audio_rate

                else:
                    ident = f"{repres.attrib['width']}x{repres.attrib['height']}"

                for url_element in repres[0]:
                    url = url_element.attrib.get('sourceURL') or url_element.attrib.get('media')
                    range = url_element.attrib.get('range') or url_element.attrib.get('mediaRange')

                    if url and url not in bucket[ident]:
                        bucket[ident].append((url, range))

        def sort_idents(container):
            return dict(sorted(container.items(), key=lambda items: int(items[0].split('x', 1)[0])))

        video = sort_idents(video)
        audio = sort_idents(audio)

        LOGGER.info(f"  Found media formats: video - {', '.join(video)}; audio - {', '.join(audio)}.")

        return video, audio

    def _download_file(self, url: str, *, dest: Path, prefer_video: VideoPreference, range: str = ''):

        if not url.startswith('http'):
            url = f'{self._url_base}{url}'

        headers = {}

        if range:
            headers.update({
                'Accept': '*/*',
                'Accept-Encoding': 'identity',
                'Connection': 'keep-alive',
                'Range': f'bytes={range}',
                'Referer': 'https://kinescope.io/',
            })

        is_mpd = url.endswith('.mpd')
        dest_tmp = None

        if is_mpd:
            headers['Referer'] = (
                'https://kinescope.io/203245765?enableIframeApi'
                '&playerId=player&size%5Bwidth%5D=100%25&size%5Bheight%5D=100%25&preload=none'
            )
            dest_tmp = dest.with_suffix('.tmp')

        with self._session.get(url, stream=True, headers=headers) as response:

            if response.status_code == 403:
                LOGGER.error('Access denied.')

            response.raise_for_status()

            with open(dest_tmp or dest, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024):
                    f.write(chunk)

        if is_mpd:
            try:
                # download mpd chunks
                self._mpd_process(mpd=dest_tmp, dest=dest, prefer_video=prefer_video)

            finally:
                _CLEANUP and dest_tmp.unlink(missing_ok=True)

    def _mpd_process(self, *, mpd: Path, dest: Path, prefer_video: VideoPreference):

        dest_tmp = (mpd.parent / 'tmp').absolute()
        dest_tmp.mkdir(parents=True, exist_ok=True)

        def download_all(urls: List[Tuple[str, str]], *, suffix: str):

            for idx, (url, range) in enumerate(urls, 1):
                file_dest = dest_tmp / f'{idx:>05}_{suffix}{dest.suffix}'
                self._download_file(url, dest=file_dest, prefer_video=prefer_video, range=range)

        try:
            video, audio = self._mpd_parse(mpd)

            download_all(
                video.get(prefer_video.frame) or video[list(video.keys())[-1]],
                suffix='vid'
            )
            LOGGER.info('  Joining video chunks ...')
            f_video = self._concat_chunks(src=dest_tmp, suffix='vid')

            download_all(
                audio.get(prefer_video.sound) or audio[list(audio.keys())[-1]],
                suffix='aud'
            )
            LOGGER.info('  Joining audio chunks ...')
            f_audio = self._concat_chunks(src=dest_tmp, suffix='aud')

            # join video + audio
            LOGGER.info('  Compiling final video ...')
            self.call(
                f'ffmpeg -i "{f_video}" -i "{f_audio}" -c copy {shlex.quote(str(dest))}',
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

        post['__files'] = {
            'audio': audio,
            'video': video,
            'text': text,

        }

        for file_info in post.get('files') or []:
            assert file_info['file_category'] == 'podcast', f'Unsupported file category found: {file_info}'
            if not file_info['file_duration']:
                LOGGER.debug(f'Probably missing {file_info["file_link"]}. Skipped.')
                continue
            audio.append(file_info)

        post_title = post['post_title'].rstrip('.')
        post_text = post.get('post_text', post.get('post_small_text', '')).strip()

        text.append({
            'file_id': f"{post['post_id']}",
            'file_title': f'{post_title}.html',
            'file_path': '',
            '__content': post_text,
        })

        for iframe in self._get_soup(post_text).find_all('iframe'):

            if 'video' in (src := iframe['src']) and (file_id := parse_qs(urlparse(src).query).get('video_id')):
                # workaround bogus links like /post/video/?video_id=xxx?poster_id=yyy
                file_id = file_id[0].partition('?')[0]
                video.append({
                    'file_id': file_id,
                    'file_title': f'{post_title}.mp4',
                    'file_path': f'https://kinescope.io/{file_id}/master.mpd',
                })

    def _collect_posts(self, *, project_id: str, func_filter: Callable = None) -> List[dict]:

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

        soup = self._get_soup(self._get_response(self.url).text)
        project_id = soup.find_all(id='project_id')[0]['value']

        return project_id

    def _auth_read(self):

        path = Path(self._fname_auth)

        if not path.exists():
            raise SponsrDumperError(f'File {path} is not found in the current directory.')

        try:

            with open(path) as f:
                data = f.read().rstrip(';')
                self._session.cookies = cookiejar_from_dict(
                    dict(
                        line.strip().split('=', 1)
                        for line in data.split(';')
                    )
                )
        except ValueError:
            raise SponsrDumperError(f'File {path} contents is not valid.')

    def _auth_write(self):
        with open(Path(self._fname_auth), 'w') as f:
            return f.write(
                ';'.join([
                    '%s=%s' % (key, val)
                    for key, val in self._session.cookies.get_dict().items()
                ])
            )

    def _conf_load(self):

        fname = Path(self._fname_conf)

        if not fname.exists():
            self._conf_save()

        else:
            LOGGER.info(f'Configuration is loaded from {fname} ...')

        with open(fname) as f:
            data = json.load(f)

        self._dumped = data.get('dumped', {})

    def _conf_save(self):

        fname = Path(self._fname_conf)

        with open(fname, 'w') as f:
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

    def search(self, *, func_filter: Callable = None) -> int:

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
        dest: Union[str, Path],
        *,
        func_filename: Callable = None,
        reverse: bool = True,
        audio: bool = True,
        video: bool = True,
        text: Union[bool, str] = True,
        text_to_video: bool = True,
        prefer_video: VideoPreference = VideoPreference(),
    ):

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
        text and realms.append('text')

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

                        filename = func_filename(post_info, file_info)
                        dest_filename = dest / filename

                        if filepath := file_info['file_path']:

                            try:
                                self._download_file(filepath, dest=dest_filename, prefer_video=prefer_video)

                            except HTTPError:
                                LOGGER.debug(f'{pformat(file_info, indent=2)}')
                                raise

                        else:
                            dest_filename = TextConverter.spawn(
                                'txt' if isinstance(text, bool) else text
                            ).dump(
                                file_info['__content'],
                                dest=dest_filename
                            )

                            if text_to_video:
                                self.text_to_video(dest_filename)

                            filename = dest_filename.name

                        self._dumped[file_id_conf] = filename


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        'project_url', help='URL проекта на sponsr.ru')
    parser.add_argument(
        '--debug', help='Вывести отладочную информацию', action='store_true')
    parser.add_argument(
        '--title', help='Фильтр заголовка для отбора статей', default='')
    parser.add_argument(
        '--to', help='Путь назначения для файлов', default='dump/')
    parser.add_argument(
        '--prefer-video', help='Предпочтительное разрешение видео', default='best')
    parser.add_argument(
        '--no-audio', help='Не следует скачивать аудио', action='store_true')
    parser.add_argument(
        '--no-video', help='Не следует скачивать видео', action='store_true')
    parser.add_argument(
        '--no-text', help='Не следует скачивать текст', action='store_true')
    parser.add_argument(
        '--text-to-video', help='Следует ли создать видео с текстом статьи', action='store_true')

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format='%(levelname)-8s: %(message)s')

    dumper = SponsrDumper(args.project_url)

    filter_func = None

    if title := args.title.strip():
        filter_func = lambda post_info: title in post_info['post_title']

    dumper.search(func_filter=filter_func)
    dumper.dump(
        args.to,
        prefer_video=VideoPreference(frame=args.prefer_video),
        audio=not args.no_audio,
        video=not args.no_video,
        text=not args.no_text,
        text_to_video=args.text_to_video
    )

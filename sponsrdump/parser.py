import logging
from pathlib import Path
from typing import Callable, List
from urllib.parse import parse_qs, urlparse
from bs4 import BeautifulSoup
import requests
from requests.cookies import cookiejar_from_dict
from . import FileType

logger = logging.getLogger(__name__)


class PostParser:
    def __init__(self):
        self._url_base = 'https://sponsr.ru'
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'ru,en;q=0.9',
        })
        self._auth_read()

    def _auth_read(self):
        from pathlib import Path
        path = Path('sponsrdump_auth.txt')
        if not path.exists():
            raise ValueError(f'Auth file {path} not found')
        with path.open('r') as f:
            data = f.read().rstrip(';')
            self.session.cookies = cookiejar_from_dict(
                dict(line.strip().split('=', 1) for line in data.split(';'))
            )

    def _get_soup(self, html: str):
        return BeautifulSoup(html, 'lxml')

    def get_project_id(self, url: str):
        response = self._get_response(url)
        soup = self._get_soup(response.text)
        return soup.find(id='project_id')['value']

    def _get_response(self, url: str, xhr: bool = False):
        if not url.startswith('http'):
            url = f'{self._url_base}{url}'
        headers = {
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
        } if xhr else {}
        response = self.session.get(url, headers=headers)
        response.raise_for_status()
        return response

    def collect_posts(self, project_id: str, func_filter: Callable = None):
        posts_all = []
        rows_seen = 0
        rows_total = 1
        func_filter = func_filter or (lambda x: x)

        while rows_seen < rows_total:
            data = self._get_response(
                f'/project/{project_id}/more-posts/?offset={rows_seen}',
                xhr=True
            ).json()['response']
            posts_current = data['rows']
            rows_seen += len(posts_current)
            posts_current = [post for post in posts_current if func_filter(post)]
            for post in posts_current:
                self._normalize_files(post)
            posts_all.extend(posts_current)
            rows_total = data['rows_count']
            logger.debug(f'Searched {rows_seen}/{rows_total} ...')

        return posts_all

    def _normalize_files(self, post: dict):
        audio = []
        video = []
        text = []
        images = []
        post['__files'] = {
            'audio': audio,
            'video': video,
            'text': text,
            'images': images,
        }

        for file_info in post.get('files') or []:
            if file_info['file_category'] != 'podcast':
                logger.warning(f'Unsupported file category: {file_info["file_category"]}')
                continue
            if not file_info.get('file_duration'):
                logger.debug(f'Missing duration for {file_info["file_link"]}')
                continue
            file_info['file_type'] = FileType.AUDIO
            audio.append(file_info)

        post_title = post['post_title'].rstrip('.')
        post_text = post.get('post_text', post.get('post_small_text', '')).strip()
        if not post_text:
            logger.warning(f'Empty post text for {post_title}')

        text.append({
            'file_id': f"{post['post_id']}",
            'file_title': post_title,
            'file_path': '',
            'file_type': FileType.TEXT,
            '__content': post_text,
        })

        soup = self._get_soup(post_text)
        for image in soup.find_all('img'):
            src = image.get('src')
            if src and (image_name := Path(urlparse(src).path).name):
                images.append({
                    'file_id': image_name,
                    'file_title': image_name,
                    'file_path': src,
                    'file_type': FileType.IMAGE,
                })

        for iframe in soup.find_all('iframe'):
            src = iframe.get('src')
            if src and 'video' in src and (file_id := parse_qs(urlparse(src).query).get('video_id')):
                file_id = file_id[0].partition('?')[0]
                video.append({
                    'file_id': file_id,
                    'file_title': f'{post_title}.mp4',
                    'file_path': f'https://kinescope.io/{file_id}/master.mpd',
                    'file_type': FileType.VIDEO,
                })
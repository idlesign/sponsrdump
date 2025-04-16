from typing import Optional
from requests import Session
from .const import BASE_URL, MASTER_PLAYLIST_URL, CLEARKEY_LICENSE_URL
from .exceptions import UrlOrVideoIdRequired, VideoNotFound, AccessDenied


class Video:
    def __init__(self, url: Optional[str] = None, video_id: Optional[str] = None, referer_url: Optional[str] = None):
        if not (url or video_id):
            raise UrlOrVideoIdRequired('URL or video ID required')
        self.url = url
        self.video_id = video_id
        self.referer_url = referer_url
        self.http = Session()
        if not self.video_id:
            self.video_id = self._get_video_id()

    def _get_video_id(self):
        r = self.http.get(self.url, headers={'Referer': self.referer_url})
        if r.status_code == 404:
            raise VideoNotFound('Video not found')
        if 'id: "' not in r.text:
            raise AccessDenied('Access denied. Wrong referer?')
        return r.text.split('id: "')[1].split('"')[0]

    def get_mpd_master_playlist_url(self):
        return MASTER_PLAYLIST_URL.format(video_id=self.video_id)

    def get_clearkey_license_url(self):
        return CLEARKEY_LICENSE_URL.format(video_id=self.video_id)
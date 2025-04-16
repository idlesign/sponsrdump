from typing import Tuple
from .const import BASE_URL

class Video:
    def __init__(self, video_id: str, referer_url: str):
        self.video_id = video_id
        self.referer_url = referer_url

    def get_mpd_master_playlist_url(self) -> str:
        return f"{BASE_URL}/{self.video_id}/master.mpd"

    def get_clearkey_license_url(self) -> str:
        return f"{BASE_URL}/license/clearkey"
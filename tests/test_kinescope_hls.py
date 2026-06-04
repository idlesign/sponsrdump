"""Tests for the kinescope HLS (m3u8) support added to fix the video 403 error.

The legacy code requested an unsigned ``master.mpd`` and got a 403. The new flow
takes the iframe ``src`` (a kinescope embed url), fetches the embed page, reads the
signed manifest from ``playerOptions`` and parses the HLS master/media playlists into
the same ``(video, audio)`` shape the MPD path produces, reusing the download pipeline.

Fixtures in ``tests/datafixtures/`` (``kinescope_embed*.html``, ``master.m3u8``,
``media_video.m3u8``, ``media_audio.m3u8``) are trimmed copies of real responses from
https://sponsr.ru/greenpig/ (video post 157553, kinescope embed 5Ff4dcABMcX8zPez93kB9D).
"""

import json
from urllib.parse import parse_qs, urlparse

import pytest
from requests import HTTPError

from sponsrdump.base import (
    SponsrDumper,
    SponsrDumperError,
    VideoPreference,
    sort_idents,
)
from sponsrdump.utils import progress

EMBED_ID = '5Ff4dcABMcX8zPez93kB9D'
EMBED_URL = f'https://kinescope.io/{EMBED_ID}'
MASTER_URL = 'https://kinescope.io/25df393d-09bf-43a3-b466-7d222c6ce9b9/master.m3u8?expires=1780640928&sign=7b17afd553c3c390'


@pytest.fixture
def dumper(auth_file):
    return SponsrDumper('https://sponsr.ru/greenpig/')


@pytest.fixture
def hls_rules(datafix_read):
    """responses rules that serve the embed page, master playlist and media playlists.

    The three video renditions and the audio rendition all hit ``media.m3u8`` and differ
    only by query string, so they are dispatched by the ``type``/``quality`` params.
    """
    embed = datafix_read('kinescope_embed.html')
    master = datafix_read('master.m3u8')
    media_video = datafix_read('media_video.m3u8')
    media_audio = datafix_read('media_audio.m3u8')

    base = 'https://kinescope.io/25df393d-09bf-43a3-b466-7d222c6ce9b9/'

    def register(mock):
        mock.add('GET', EMBED_URL, body=embed)
        # match the signed master url regardless of query
        mock.add('GET', base + 'master.m3u8', body=master)

        def media_callback(request):
            params = parse_qs(urlparse(request.url).query)
            body = media_audio if params.get('type') == ['audio'] else media_video
            return 200, {}, body

        mock.add_callback('GET', base + 'media.m3u8', callback=media_callback)

        # every segment / init request (any byte range) returns dummy bytes
        for url in (
            'https://edge-msk-1.kinescopecdn.net/videos/869b5dec/assets/019e7bce/360p.mp4',
            'https://edge-msk-1.kinescopecdn.net/videos/869b5dec/assets/019e7bce-aud/audio_0.mp4',
        ):
            mock.add('GET', url, body=b'chunk')

    return register


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(('src', 'expected'), [
    ('https://kinescope.io/5Ff4dcABMcX8zPez93kB9D', 'https://kinescope.io/5Ff4dcABMcX8zPez93kB9D'),
    ('https://kinescope.io/5Ff4dcABMcX8zPez93kB9D/', 'https://kinescope.io/5Ff4dcABMcX8zPez93kB9D'),
    # legacy / non-embed forms yield no embed url
    ('https://kinescope.io/post/video/?video_id=xxx', ''),
    ('https://kinescope.io/abc/master.mpd', ''),
    ('/post/video/?video_id=xxx', ''),
    ('', ''),
    (None, ''),
])
def test_kinescope_embed_url(src, expected):
    assert SponsrDumper._kinescope_embed_url(src) == expected


def test_sort_idents_orders_by_leading_number():
    container = {'1280x720': ['c'], '640x360': ['a'], '854x480': ['b']}
    assert list(sort_idents(container)) == ['640x360', '854x480', '1280x720']


def test_sort_idents_audio_numeric():
    assert list(sort_idents({'2': [], '0': [], '10': [], '1': []})) == ['0', '1', '2', '10']


@pytest.mark.parametrize(('length', 'offset', 'cursor', 'expected', 'next_pos'), [
    # explicit offset
    ('100', '0', {}, '0-99', 100),
    ('50', '200', {}, '200-249', 250),
    # offset omitted -> continues from cursor position
    ('100', None, {}, '0-99', 100),
    ('40', None, {'pos': 100}, '100-139', 140),
])
def test_hls_range(length, offset, cursor, expected, next_pos):
    assert SponsrDumper._hls_range(length, offset, cursor) == expected
    assert cursor['pos'] == next_pos


# --------------------------------------------------------------------------- #
# m3u8 parsing
# --------------------------------------------------------------------------- #

def test_m3u8_parse(dumper, hls_rules, response_mock, datafix_read):
    master = datafix_read('master.m3u8')
    with response_mock([], assert_all_requests_are_fired=False) as mock:
        hls_rules(mock)
        video, audio = dumper._m3u8_parse(master, MASTER_URL)

    # video keyed by resolution, sorted ascending by width
    assert list(video) == ['640x360', '854x480', '1280x720']
    # single audio rendition keyed numerically
    assert list(audio) == ['0']

    # init segment first, then 3 media segments, byte ranges computed from EXT-X-BYTERANGE
    segments = video['1280x720']
    assert [rng for _, rng in segments] == ['0-770', '771-280269', '280270-766793', '766794-1310367']
    # all segments of a rendition resolve to absolute urls
    assert all(url.startswith('https://edge-msk-1.kinescopecdn.net/') for url, _ in segments)

    audio_segments = audio['0']
    assert [rng for _, rng in audio_segments] == ['0-659', '660-95946', '95947-191742']


def test_m3u8_segments_without_byteranges(dumper, response_mock):
    # a media playlist with plain segment urls and no byte ranges
    media = (
        '#EXTM3U\n'
        '#EXT-X-MAP:URI="https://cdn.example/init.mp4"\n'
        '#EXTINF:4.0,\n'
        'https://cdn.example/seg1.mp4\n'
        '#EXTINF:4.0,\n'
        'seg2.mp4\n'
        '#EXT-X-ENDLIST\n'
    )
    media_url = 'https://kinescope.io/x/media.m3u8'
    with response_mock([f'GET {media_url} -> 200 :{media}']):
        segments = dumper._m3u8_segments(media_url)

    assert segments == [
        ('https://cdn.example/init.mp4', ''),
        ('https://cdn.example/seg1.mp4', ''),
        # relative segment resolved against the media playlist url
        ('https://kinescope.io/x/seg2.mp4', ''),
    ]


def test_m3u8_segments_init_with_byterange(dumper, response_mock):
    media = (
        '#EXTM3U\n'
        '#EXT-X-MAP:URI="init.mp4",BYTERANGE="500@0"\n'
        '#EXTINF:4.0,\n'
        '#EXT-X-BYTERANGE:1000@500\n'
        'data.mp4\n'
        '#EXT-X-ENDLIST\n'
    )
    media_url = 'https://kinescope.io/x/media.m3u8'
    with response_mock([f'GET {media_url} -> 200 :{media}']):
        segments = dumper._m3u8_segments(media_url)

    assert segments == [
        ('https://kinescope.io/x/init.mp4', '0-499'),
        ('https://kinescope.io/x/data.mp4', '500-1499'),
    ]


# --------------------------------------------------------------------------- #
# embed resolution
# --------------------------------------------------------------------------- #

def test_resolve_kinescope_hls(dumper, hls_rules, response_mock, mock_popen, tmp_path):
    dest = tmp_path / 'video.mp4'
    with response_mock([], assert_all_requests_are_fired=False) as mock:
        hls_rules(mock)
        dumper._resolve_kinescope(
            EMBED_URL,
            dest=dest,
            prefer_video=VideoPreference(frame='1280x720', sound='best'),
        )

    # the pipeline muxes the downloaded streams with ffmpeg
    assert any('ffmpeg' in cmd for cmd in mock_popen.commands)


def test_resolve_kinescope_dash_fallback(dumper, response_mock, datafix_read, monkeypatch):
    # embed page exposing only a signed DASH manifest must fall back to the MPD download path
    embed = datafix_read('kinescope_embed_dash.html')
    captured = {}

    def fake_download(self, url, *, dest, prefer_video, **kwargs):
        captured['url'] = url

    monkeypatch.setattr(SponsrDumper, '_download_file', fake_download)

    with response_mock([f'GET {EMBED_URL} -> 200 :{embed}']):
        dumper._resolve_kinescope(EMBED_URL, dest='/tmp/out.mp4', prefer_video=VideoPreference())

    assert captured['url'].endswith('master.mpd?expires=1780640928&sign=7b17afd553c3c390')


def test_resolve_kinescope_no_player_options(dumper, response_mock):
    with response_mock([f'GET {EMBED_URL} -> 200 :<html>no options here</html>']):
        with pytest.raises(SponsrDumperError, match='Unable to find player options'):
            dumper._resolve_kinescope(EMBED_URL, dest='/tmp/out.mp4', prefer_video=VideoPreference())


def test_resolve_kinescope_no_playable_source(dumper, response_mock, datafix_read):
    embed = datafix_read('kinescope_embed_nosource.html')
    with response_mock([f'GET {EMBED_URL} -> 200 :{embed}']):
        with pytest.raises(SponsrDumperError, match='No playable HLS/DASH source'):
            dumper._resolve_kinescope(EMBED_URL, dest='/tmp/out.mp4', prefer_video=VideoPreference())


def test_kinescope_get_raises_on_error(dumper, response_mock):
    url = 'https://kinescope.io/denied'
    with response_mock([f'GET {url} -> 403 :nope']):
        with pytest.raises(HTTPError):
            dumper._kinescope_get(url, referer='https://kinescope.io/')


# --------------------------------------------------------------------------- #
# _download_file dispatch to the embed resolver
# --------------------------------------------------------------------------- #

def test_download_file_dispatches_embed_url(dumper, monkeypatch):
    called = {}

    def fake_resolve(self, embed_url, *, dest, prefer_video):
        called['embed_url'] = embed_url

    monkeypatch.setattr(SponsrDumper, '_resolve_kinescope', fake_resolve)
    dumper._download_file(EMBED_URL, dest='/tmp/out.mp4', prefer_video=VideoPreference())

    assert called['embed_url'] == EMBED_URL


def test_download_file_mpd_url_not_dispatched_to_resolver(dumper, monkeypatch, response_mock, tmp_path):
    # a bare master.mpd kinescope url keeps using the legacy MPD path, not the embed resolver
    monkeypatch.setattr(
        SponsrDumper,
        '_resolve_kinescope',
        lambda *a, **k: pytest.fail('mpd url must not go through the embed resolver'),
    )
    seen = {}
    monkeypatch.setattr(SponsrDumper, '_mpd_process', lambda self, **kw: seen.setdefault('mpd', kw['mpd']))

    rule_url = 'https://kinescope.io/abc/master.mpd'
    with response_mock([f'GET {rule_url} -> 200 :<MPD></MPD>']):
        dumper._download_file(rule_url, dest=tmp_path / 'out.mp4', prefer_video=VideoPreference())

    assert 'mpd' in seen


def test_download_file_segment_with_range_not_dispatched(dumper, monkeypatch, response_mock, tmp_path):
    # a kinescope url carrying a byte range is a media segment, not an embed page
    monkeypatch.setattr(
        SponsrDumper,
        '_resolve_kinescope',
        lambda *a, **k: pytest.fail('ranged request must not go through the embed resolver'),
    )
    url = 'https://kinescope.io/segment'
    dest = tmp_path / 'seg.mp4'
    with response_mock([f'GET {url} -> 200 :data']):
        dumper._download_file(url, dest=dest, prefer_video=VideoPreference(), range='0-9')
    assert dest.read_bytes() == b'data'


# --------------------------------------------------------------------------- #
# _normalize_files now prefers the signed embed url
# --------------------------------------------------------------------------- #

def test_normalize_files_prefers_embed_url(dumper):
    # iframe with both legacy data-url and a real kinescope embed src
    post = {
        'post_id': '157553',
        'post_title': 'Клуб Зеленой Свиньи (#323).',
        'post_text': (
            '<iframe src="https://kinescope.io/5Ff4dcABMcX8zPez93kB9D" '
            'data-url="/post/video/?video_id=25df393d?poster_id=4a462b28"></iframe>'
        ),
        'files': [],
    }
    dumper._normalize_files(post)
    video = post['__files']['video']
    assert len(video) == 1
    assert video[0]['file_path'] == EMBED_URL
    # file_id still derived from the legacy video_id (poster suffix stripped)
    assert video[0]['file_id'] == '25df393d'


def test_normalize_files_falls_back_to_mpd_without_embed_src(dumper):
    # no usable embed src -> legacy unsigned master.mpd url
    post = {
        'post_id': '1',
        'post_title': 'No embed.',
        'post_text': '<iframe data-url="/post/video/?video_id=abc123"></iframe>',
        'files': [],
    }
    dumper._normalize_files(post)
    assert post['__files']['video'][0]['file_path'] == 'https://kinescope.io/abc123/master.mpd'


# --------------------------------------------------------------------------- #
# end-to-end: search + dump a post with a real-shaped kinescope embed
# --------------------------------------------------------------------------- #

def test_dump_video_via_hls(auth_file, hls_rules, response_mock, datafix_read, mock_popen, tmp_path):
    project_html = datafix_read('project.html')
    post_text = f'<p>Видео</p><iframe src="{EMBED_URL}" data-url="/post/video/?video_id=25df393d"></iframe>'
    posts = {
        'response': {
            'rows': [{
                'post_id': '157553',
                'post_title': 'Клуб Зеленой Свиньи (#323)',
                'post_text': post_text,
                'files': [],
            }],
            'rows_count': 1,
        }
    }
    rules = [
        'GET https://sponsr.ru/greenpig/ -> 200 :' + project_html,
        'GET https://sponsr.ru/project/187/more-posts/?offset=0 -> 200 :' + json.dumps(posts),
    ]
    with response_mock(rules, assert_all_requests_are_fired=False) as mock:
        hls_rules(mock)
        dumper = SponsrDumper('https://sponsr.ru/greenpig/')
        # project.html fixture exposes project_id 248; override to match our mocked posts url
        dumper.project_id = '187'
        dumper._collected = dumper._collect_posts(project_id='187')

        dest = tmp_path / 'dump'
        dumper.dump(
            dest,
            audio=False,
            video=True,
            images=False,
            text=False,
            attaches=False,
            text_to_video=False,
            prefer_video=VideoPreference(frame='1280x720', sound='best'),
        )

    # ffmpeg muxes the downloaded video+audio streams into the post's output file
    # (the final mux is mocked, so we assert on the command rather than the file on disk)
    ffmpeg_cmds = [cmd for cmd in mock_popen.commands if cmd.startswith('ffmpeg')]
    assert ffmpeg_cmds
    assert any('001. 001. Клуб Зеленой Свиньи (#323).mp4' in cmd for cmd in ffmpeg_cmds)
    # both a video and an audio input stream were passed to the final mux
    assert ffmpeg_cmds[-1].count('-i ') == 2


# --------------------------------------------------------------------------- #
# progress reporting
# --------------------------------------------------------------------------- #

def test_progress_writes_line():
    class Stream:
        def __init__(self):
            self.buf = ''

        def write(self, s):
            self.buf += s

        def flush(self):
            pass

    stream = Stream()
    progress('video', 3, 10, stream=stream)
    assert stream.buf == '\r  video: 3/10 (30.0%)   '
    # no trailing newline mid-progress
    assert not stream.buf.endswith('\n')


def test_progress_final_newline():
    class Stream:
        def __init__(self):
            self.buf = ''

        def write(self, s):
            self.buf += s

        def flush(self):
            pass

    stream = Stream()
    progress('audio', 10, 10, stream=stream)
    assert stream.buf.endswith('\n')
    assert '100.0%' in stream.buf


def test_progress_zero_total_noop():
    class Stream:
        def __init__(self):
            self.buf = ''

        def write(self, s):  # pragma: no cover - must not be called
            self.buf += s

        def flush(self):  # pragma: no cover
            pass

    stream = Stream()
    progress('video', 0, 0, stream=stream)
    assert stream.buf == ''

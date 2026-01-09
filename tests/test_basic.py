import json

import pytest
from requests import HTTPError
from responses import matchers

from sponsrdump.base import (
    FileType,
    SponsrDumper,
    SponsrDumperError,
    VideoPreference,
)
from sponsrdump.converters import (
    HtmlConverter,
    MarkdownConverter,
    TextConverter,
)


def test_sponsr_dumper_smoke(remote_data, mock_popen, response_mock, tmp_path, data_audio):

    remote_data.text = '<p>Test content</p><iframe data-url="/post/video/?video_id=test123"></iframe>'
    remote_data.files = [data_audio]

    with response_mock(remote_data.rules, assert_all_requests_are_fired=False) as mock:
        # Добавляем дополнительные моки для Range запросов через responses API

        base_video_url_1080 = (
            'https://edge-msk-8.kinescopecdn.net/3e324c4c-4135-42a7-a393-6399d9062f6c/videos/'
            'ac8b012d-a851-4c00-a718-69fd4666932e/assets/01931d08-e0c8-771a-bc60-bd7f73e50dcb/0/80482014/1080p.mp4'
        )
        # Инициализация
        mock.add(
            'GET',
            base_video_url_1080,
            body=b'fake_video_init_data',
            match=[matchers.header_matcher({'Range': 'bytes=36-799'})],
        )
        # Сегменты
        for range_val in ['800-2127871', '2127872-4300309', '4300310-6602431']:
            mock.add(
                'GET',
                base_video_url_1080,
                body=b'fake_video_segment_data',
                match=[matchers.header_matcher({'Range': f'bytes={range_val}'})],
            )

        # аудио сегменты
        audio_base_url = (
            'https://edge-msk-8.kinescopecdn.net/3e324c4c-4135-42a7-a393-6399d9062f6c/'
            'videos/ac8b012d-a851-4c00-a718-69fd4666932e/assets/01931d05-7824-71d5-8698-7d4f989c43d6/audio_0.mp4'
        )
        # Инициализация
        mock.add(
            'GET',
            audio_base_url,
            body=b'fake_audio_init_data',
            match=[matchers.header_matcher({'Range': 'bytes=32-659'})],
        )
        # Сегменты
        for range_val in ['660-65523', '65524-130612', '130613-195333']:
            mock.add(
                'GET',
                audio_base_url,
                body=b'fake_audio_segment_data',
                match=[matchers.header_matcher({'Range': f'bytes={range_val}'})],
            )

        dumper = SponsrDumper(remote_data.url)
        found = dumper.search()

        assert found == 1
        assert dumper.project_id == remote_data.project_id

        dest = tmp_path / 'dump'
        dumper.dump(
            dest,
            audio=True,
            video=True,
            images=True,
            text=True,
            text_to_video=False,
            prefer_video=VideoPreference(frame='1920x1080', sound='44100'),
        )

        # Проверяем, что были вызваны команды
        assert len(mock_popen.commands) > 0

        # Проверяем наличие ожидаемых команд
        commands_str = ' '.join(mock_popen.commands)
        assert 'ffmpeg' in commands_str or 'cat' in commands_str

        # Проверяем конкретные команды
        expected_commands = ['cat', 'ffmpeg']
        found_commands = [cmd for cmd in expected_commands if cmd in commands_str]
        assert len(found_commands) > 0, f'Expected commands {expected_commands}, but got: {mock_popen.commands}'

        # Проверяем, что файлы были созданы
        assert dest.exists()
        files = list(dest.iterdir())
        assert len(files) > 0


def test_text_converter_dump(tmp_path):
    converter = HtmlConverter()
    dest = tmp_path / 'test.txt'
    result = converter.dump('<p>test</p>', dest=dest)
    assert result.exists()
    assert result.suffix == '.html'
    assert result.read_text() == '<p>test</p>'


def test_text_converter_spawn():
    converter = TextConverter.spawn('html')
    assert isinstance(converter, HtmlConverter)
    converter = TextConverter.spawn('md')
    assert isinstance(converter, MarkdownConverter)


def test_html_converter_convert():
    converter = HtmlConverter()
    assert converter._convert('<p>test</p>') == '<p>test</p>'


def test_markdown_converter_convert():
    converter = MarkdownConverter()
    result = converter._convert('<p>test</p>')
    assert 'test' in result


def test_get_project_id_error(auth_file, response_mock):
    url = 'https://sponsr.ru/test_project'
    rules = [f'GET {url} -> 200 :<html>no project id here</html>']
    with response_mock(rules):
        dumper = SponsrDumper(url)
        with pytest.raises(SponsrDumperError, match='Unable to get project ID'):
            dumper._get_project_id()


def test_auth_read_file_not_found(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SponsrDumperError, match='is not found'):
        SponsrDumper('https://sponsr.ru/test')


def test_auth_read_invalid_format(auth_file):
    auth_file.write_text('invalid_format_no_equals')
    with pytest.raises(SponsrDumperError, match='is not valid'):
        SponsrDumper('https://sponsr.ru/test')


def test_auth_write(auth_file):
    dumper = SponsrDumper('https://sponsr.ru/test')
    dumper._session.cookies.set('test_key', 'test_value')
    result = dumper._auth_write()
    assert result > 0
    content = auth_file.read_text()
    assert 'test_key=test_value' in content


def test_conf_load_existing(auth_file, tmp_path):
    conf_file = tmp_path / 'sponsrdump.json'
    conf_file.write_text('{"dumped": {"f_123": "test.txt"}}')
    dumper = SponsrDumper('https://sponsr.ru/test')
    dumper._conf_load()
    assert dumper._dumped == {'f_123': 'test.txt'}


def test_normalize_files_with_images(response_mock, remote_data):
    remote_data.text = '<p>Test content</p><img src="https://example.com/image.jpg" />'
    with response_mock(remote_data.rules):
        dumper = SponsrDumper(remote_data.url)
        dumper.search()
        post = dumper._collected[0]
        assert len(post['__files']['images']) > 0
        assert post['__files']['images'][0]['file_id'] == 'image.jpg'


def test_normalize_files_no_duration(response_mock, remote_data, data_audio):
    data_audio['file_duration'] = 0
    remote_data.files = [data_audio]
    remote_data.request_file = False

    with response_mock(remote_data.rules):
        dumper = SponsrDumper(remote_data.url)
        dumper.search()
        post = dumper._collected[0]
        assert len(post['__files']['audio']) == 0


def test_normalize_files_unsupported_category(response_mock, remote_data, data_unknown):
    remote_data.files = [data_unknown]
    remote_data.request_file = False

    dumper = SponsrDumper(remote_data.url)
    with response_mock(remote_data.rules), pytest.raises(AssertionError, match='Unsupported file category'):
        dumper.search()


def test_download_file_relative_url(response_mock, remote_data, data_audio, tmp_path):
    data_audio['file_link'] = data_audio['file_link'].replace('https://example.com', '')
    data_audio['file_path'] = data_audio['file_path'].replace('https://example.com', '')
    remote_data.files = [data_audio]

    with response_mock(remote_data.rules):
        dumper = SponsrDumper(remote_data.url)
        dumper.search()
        dest = tmp_path / 'test.mp3'
        dumper._download_file(
            '/audio.mp3',
            dest=dest,
            prefer_video=VideoPreference(),
        )
        assert dest.exists()


def test_download_file_403_error(response_mock, tmp_path, remote_data):
    rules = [*remote_data.rules, 'GET https://example.com/file.mp3 -> 403 :Access denied']
    with response_mock(rules):
        dumper = SponsrDumper(remote_data.url)
        dumper.search()
        dest = tmp_path / 'test.mp3'
        with pytest.raises(HTTPError):
            dumper._download_file(
                'https://example.com/file.mp3',
                dest=dest,
                prefer_video=VideoPreference(),
            )


def test_get_response_xhr(auth_file, response_mock, datafix_read):
    url = 'https://sponsr.ru/test_project'
    project_id = '248'
    project_html = datafix_read('project.html')
    posts_response = {
        'response': {
            'rows': [],
            'rows_count': 0,
        }
    }
    posts_json = json.dumps(posts_response)
    rules = [
        f'GET {url} -> 200 :{project_html}',
        f'GET https://sponsr.ru/project/{project_id}/more-posts/?offset=0 -> 200 :{posts_json}',
    ]
    with response_mock(rules, assert_all_requests_are_fired=False):
        dumper = SponsrDumper(url)
        dumper.search()
        response = dumper._get_response(f'/project/{project_id}/more-posts/?offset=0', xhr=True)
        assert response.status_code == 200


def test_dump_skip_existing_file(remote_data, tmp_path, response_mock):
    conf_file = tmp_path / 'sponsrdump.json'
    conf_file.write_text('{"dumped": {"f_123": "001. 001. Test Post.html"}}')
    with response_mock(remote_data.rules):
        dumper = SponsrDumper(remote_data.url)
        dumper.search()
        dest = tmp_path / 'dump'
        dumper.dump(dest, text=True, audio=False, video=False, images=False)
        assert dest.exists()


@pytest.mark.parametrize(('text_format', 'text_to_video_enabled'), [
    ('md', True),
    ('html', True),
    ('md', False),
    ('html', False),
])
def test_dump_text_to_video(
        remote_data, tmp_path, mock_popen, response_mock, text_format, text_to_video_enabled
):
    with response_mock(remote_data.rules):
        dumper = SponsrDumper(remote_data.url)
        dumper.search()
        dest = tmp_path / 'dump'
        dumper.dump(
            dest,
            text=text_format,
            audio=False,
            video=False,
            images=False,
            text_to_video=text_to_video_enabled,
        )
        assert dest.exists()
        files = list(dest.iterdir())
        if text_format == 'html':
            html_files = [f for f in files if f.suffix == '.html']
            assert len(html_files) > 0
        if text_to_video_enabled:
            assert any('ffmpeg' in cmd for cmd in mock_popen.commands)


def test_dump_http_error_handling(remote_data, tmp_path, response_mock):
    rules = [*remote_data.rules, 'GET https://example.com/error.jpg -> 500 :Server Error']
    with response_mock(rules):
        dumper = SponsrDumper(remote_data.url)
        dumper.search()
        post = dumper._collected[0]
        post['__files']['images'] = [
            {
                'file_id': 'error_image',
                'file_title': 'error.jpg',
                'file_path': 'https://example.com/error.jpg',
                'file_type': FileType.IMAGE,
            }
        ]
        dest = tmp_path / 'dump'
        with pytest.raises(HTTPError):
            dumper.dump(dest, text=False, audio=False, video=False, images=True)


def test_conf_save(auth_file, tmp_path):
    dumper = SponsrDumper('https://sponsr.ru/test')
    dumper._dumped = {'f_123': 'test.txt'}
    dumper._conf_save()
    conf_file = tmp_path / 'sponsrdump.json'
    assert conf_file.exists()
    data = json.loads(conf_file.read_text())
    assert data['dumped'] == {'f_123': 'test.txt'}


def test_conf_load_new_file(auth_file, tmp_path):
    dumper = SponsrDumper('https://sponsr.ru/test')
    dumper._conf_load()
    conf_file = tmp_path / 'sponsrdump.json'
    assert conf_file.exists()
    data = json.loads(conf_file.read_text())
    assert 'dumped' in data


def test_dump_func_filename_custom(remote_data, tmp_path, response_mock):
    def custom_filename(post_info, file_info):
        return f"custom_{post_info['post_id']}_{file_info['file_id']}.html"
    with response_mock(remote_data.rules):
        dumper = SponsrDumper(remote_data.url)
        dumper.search()
        dest = tmp_path / 'dump'
        dumper.dump(
            dest, text=True, audio=False, video=False, images=False, func_filename=custom_filename
        )
        assert dest.exists()
        files = list(dest.iterdir())
        assert any('custom_' in f.name for f in files)


@pytest.mark.parametrize(('iframe_attr', 'iframe_value', 'expected_id'), [
    ('data-url', '/post/video/?video_id=test123', 'test123'),
    ('src', '/post/video/?video_id=legacy123', 'legacy123'),
    ('data-url', '/post/video/?video_id=test123?poster_id=456', 'test123'),
])
def test_normalize_files_with_video_iframe(auth_file, iframe_attr, iframe_value, expected_id):
    dumper = SponsrDumper('https://sponsr.ru/test')
    post = {
        'post_id': '123',
        'post_title': 'Test Post.',
        'post_text': f'<iframe {iframe_attr}="{iframe_value}"></iframe>',
        'files': [],
    }
    dumper._normalize_files(post)
    assert len(post['__files']['video']) > 0
    assert post['__files']['video'][0]['file_id'] == expected_id


def test_collect_posts_with_filter(remote_data, response_mock):
    with response_mock(remote_data.rules):
        dumper = SponsrDumper(remote_data.url)
        dumper.search()
        original_count = len(dumper._collected)

        def filter_func(post):
            return 'Test' in post['post_title']

        filtered = dumper._collect_posts(project_id=dumper.project_id, func_filter=filter_func)
        assert len(filtered) <= original_count


def test_collect_posts_multiple_pages(auth_file, response_mock, project_html):
    url = 'https://sponsr.ru/test_project'
    project_id = '248'
    posts_response_page1 = {
        'response': {
            'rows': [{'post_id': '1', 'post_title': 'Post 1', 'post_text': '<p>1</p>', 'files': []}],
            'rows_count': 2,
        }
    }
    posts_response_page2 = {
        'response': {
            'rows': [{'post_id': '2', 'post_title': 'Post 2', 'post_text': '<p>2</p>', 'files': []}],
            'rows_count': 2,
        }
    }
    rules = [
        f'GET {url} -> 200 :{project_html}',
        f'GET https://sponsr.ru/project/{project_id}/more-posts/?offset=0 -> 200 :{json.dumps(posts_response_page1)}',
        f'GET https://sponsr.ru/project/{project_id}/more-posts/?offset=1 -> 200 :{json.dumps(posts_response_page2)}',
    ]
    with response_mock(rules, assert_all_requests_are_fired=False):
        dumper = SponsrDumper(url)
        collected = dumper._collect_posts(project_id=project_id)
        assert len(collected) == 2

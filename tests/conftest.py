import json
from dataclasses import dataclass, field
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def mock_popen(monkeypatch):
    commands: list[str] = []

    class MockPopen:
        def __init__(self, cmd: str, **kwargs):
            self.cmd = cmd
            self.kwargs = kwargs
            self.returncode = 0
            self.stdout_data = b''
            self.stderr_data = b''
            commands.append(cmd)

        def communicate(self):
            return self.stdout_data, self.stderr_data

    monkeypatch.setattr('sponsrdump.utils.Popen', MockPopen)

    class Fixture:
        pass

    fixture = Fixture()
    fixture.commands = commands
    return fixture


@pytest.fixture
def auth_file(tmp_path, monkeypatch):
    auth_path = tmp_path / 'sponsrdump_auth.txt'
    auth_path.write_text('session_id=test_session;csrf_token=test_token')
    monkeypatch.chdir(tmp_path)
    return auth_path


@pytest.fixture
def project_html(datafix_read):
    return datafix_read('project.html')


@pytest.fixture
def remote_data(auth_file, project_html, datafix_read):

    @dataclass
    class RemoteData:
        url: str = 'https://sponsr.ru/test_project'
        project_id: str = '248'
        text: str = '<p>Test content</p>'
        files: list[dict[str, Any]] = field(default_factory=list)
        request_file: bool = True

        @property
        def response(self):
            out = {
                'response': {
                    'rows': [
                        {
                            'post_id': '123',
                            'level_id': '1',
                            'post_date': '2024-01-01',
                            'post_title': 'Test Post',
                            'post_text': self.text,
                            'post_url': '/post/123',
                            'tags': [],
                            'files': self.files,
                        }
                    ],
                    'rows_count': 1,
                }
            }
            return out

        @property
        def rules(self) -> list[str]:
            response = self.response

            posts_json = json.dumps(response)
            rules = [
                f'GET {self.url} -> 200 :{project_html}',
                f'GET https://sponsr.ru/project/{self.project_id}/more-posts/?offset=0 -> 200 :{posts_json}',
            ]

            row = response['response']['rows'][0]

            if 'iframe' in row['post_text']:
                some_mpd = datafix_read('some_mpd.xml')
                rules.append('GET https://kinescope.io/test123/master.mpd -> 200 :' + some_mpd)

            if self.request_file:
                for file in row['files']:
                    url = file['file_path']
                    if url.startswith('/'):
                        url = f'https://sponsr.ru{url}'
                    rules.append(f'GET {url} -> 200 :fake_binary_data')

            return rules

    return RemoteData()


@pytest.fixture
def data_audio() -> dict:
    return {
        'file_id': 'audio123',
        'file_category': 'podcast',
        'file_duration': 100,
        'file_link': 'https://example.com/audio.mp3',
        'file_title': 'audio.mp3',
        'file_path': 'https://example.com/audio.mp3',
    }


@pytest.fixture
def data_unknown() -> dict:
    return {
        'file_id': 'file123',
        'file_category': 'unsupported',
        'file_duration': 100,
        'file_link': 'https://example.com/file',
        'file_title': 'file',
        'file_path': 'https://example.com/file',
    }

import json

import pytest
from responses import matchers

from sponsrdump.base import SponsrDumper, VideoPreference


@pytest.fixture
def mock_popen(monkeypatch):
    """Фикстура для замены Popen на MockPopen."""
    commands: list[str] = []

    class MockPopen:
        """Имитатор Popen, который сохраняет все полученные команды."""

        def __init__(self, cmd: str, **kwargs):
            self.cmd = cmd
            self.kwargs = kwargs
            self.returncode = 0
            self.stdout_data = b""
            self.stderr_data = b""
            commands.append(cmd)

        def communicate(self):
            return self.stdout_data, self.stderr_data

    monkeypatch.setattr("sponsrdump.base.Popen", MockPopen)
    class Fixture:
        pass
    fixture = Fixture()
    fixture.commands = commands
    return fixture


@pytest.fixture
def auth_file(tmp_path, monkeypatch):
    """Создает временный файл авторизации."""
    auth_path = tmp_path / "sponsrdump_auth.txt"
    auth_path.write_text("session_id=test_session;csrf_token=test_token")
    monkeypatch.chdir(tmp_path)
    return auth_path


def test_sponsr_dumper_smoke(mock_popen, datafix_read, auth_file, response_mock, tmp_path):
    url = "https://sponsr.ru/test_project"
    project_id = "248"

    project_html = datafix_read("project.html")
    some_mpd = datafix_read("some_mpd.xml")

    posts_response = {
        "response": {
            "rows": [
                {
                    "post_id": "123",
                    "level_id": "1",
                    "post_date": "2024-01-01",
                    "post_title": "Test Post",
                    "post_text": '<p>Test content</p><iframe data-url="/post/video/?video_id=test123"></iframe>',
                    "post_url": "/post/123",
                    "tags": [],
                    "files": [
                        {
                            "file_id": "audio123",
                            "file_category": "podcast",
                            "file_duration": 100,
                            "file_link": "https://example.com/audio.mp3",
                            "file_title": "audio.mp3",
                            "file_path": "https://example.com/audio.mp3",
                        }
                    ],
                }
            ],
            "rows_count": 1,
        }
    }

    posts_json = json.dumps(posts_response)

    # Формируем правила для response_mock
    rules = [
        f"GET {url} -> 200 :{project_html}",
        f"GET https://sponsr.ru/project/{project_id}/more-posts/?offset=0 -> 200 :{posts_json}",
        "GET https://kinescope.io/test123/master.mpd -> 200 :" + some_mpd,
        "GET https://example.com/audio.mp3 -> 200 :fake_audio_data",
    ]

    with response_mock(rules, assert_all_requests_are_fired=False) as mock:
        # Добавляем дополнительные моки для Range запросов через responses API

        base_video_url_1080 = (
            "https://edge-msk-8.kinescopecdn.net/3e324c4c-4135-42a7-a393-6399d9062f6c/videos/"
            "ac8b012d-a851-4c00-a718-69fd4666932e/assets/01931d08-e0c8-771a-bc60-bd7f73e50dcb/0/80482014/1080p.mp4"
        )
        # Инициализация
        mock.add(
            "GET",
            base_video_url_1080,
            body=b"fake_video_init_data",
            match=[matchers.header_matcher({"Range": "bytes=36-799"})],
        )
        # Сегменты
        for range_val in ["800-2127871", "2127872-4300309", "4300310-6602431"]:
            mock.add(
                "GET",
                base_video_url_1080,
                body=b"fake_video_segment_data",
                match=[matchers.header_matcher({"Range": f"bytes={range_val}"})],
            )

        # аудио сегменты
        audio_base_url = (
            "https://edge-msk-8.kinescopecdn.net/3e324c4c-4135-42a7-a393-6399d9062f6c/"
            "videos/ac8b012d-a851-4c00-a718-69fd4666932e/assets/01931d05-7824-71d5-8698-7d4f989c43d6/audio_0.mp4"
        )
        # Инициализация
        mock.add(
            "GET",
            audio_base_url,
            body=b"fake_audio_init_data",
            match=[matchers.header_matcher({"Range": "bytes=32-659"})],
        )
        # Сегменты
        for range_val in ["660-65523", "65524-130612", "130613-195333"]:
            mock.add(
                "GET",
                audio_base_url,
                body=b"fake_audio_segment_data",
                match=[matchers.header_matcher({"Range": f"bytes={range_val}"})],
            )

        dumper = SponsrDumper(url)
        found = dumper.search()

        assert found == 1
        assert dumper.project_id == project_id

        dest = tmp_path / "dump"
        dumper.dump(
            dest,
            audio=True,
            video=True,
            images=True,
            text=True,
            text_to_video=False,
            prefer_video=VideoPreference(frame="1920x1080", sound="44100"),
        )

        # Проверяем, что были вызваны команды
        assert len(mock_popen.commands) > 0

        # Проверяем наличие ожидаемых команд
        commands_str = " ".join(mock_popen.commands)
        assert "ffmpeg" in commands_str or "cat" in commands_str

        # Проверяем конкретные команды
        expected_commands = ["cat", "ffmpeg"]
        found_commands = [cmd for cmd in expected_commands if cmd in commands_str]
        assert len(found_commands) > 0, f"Expected commands {expected_commands}, but got: {mock_popen.commands}"

        # Проверяем, что файлы были созданы
        assert dest.exists()
        files = list(dest.iterdir())
        assert len(files) > 0

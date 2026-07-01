from pathlib import Path

import pytest

from sponsrdump.exceptions import SponsrDumperError
from sponsrdump.utils import call, convert_text_to_video, match_value, truncate_filename


def test_match_value():

    assert match_value('something', rule='met')
    assert match_value('so met hing', rule='met')
    assert not match_value('anything', rule='met')
    assert match_value('anything', rule='(met|nyt)')
    assert match_value('some 1234thing', rule='\\d{3}')
    assert not match_value('some 12thing', rule='\\d{3}')


def test_call_error(mock_popen, monkeypatch):
    class ErrorMockPopen:
        def __init__(self, cmd: str, **kwargs):
            self.cmd = cmd
            self.returncode = 1
            self.stdout_data = b"stdout error"
            self.stderr_data = b"stderr error"

        def communicate(self):
            return self.stdout_data, self.stderr_data

    monkeypatch.setattr("sponsrdump.utils.Popen", ErrorMockPopen)
    with pytest.raises(SponsrDumperError, match="Command error"):
        call("false", cwd=Path.cwd())


def test_text_to_video(mock_popen, tmp_path):
    src = tmp_path / "test.md"
    src.write_text("Test content\nwith multiple lines\nfor video generation")
    result = convert_text_to_video(src)
    assert result.suffix == ".mp4"
    assert "[txt]" in result.stem
    assert any("ffmpeg" in cmd for cmd in mock_popen.commands)


def test_truncate_filename_short_unchanged():
    assert truncate_filename('short.html') == 'short.html'


def test_truncate_filename_exact_max_len():
    name = 'A' * 255
    assert truncate_filename(name, max_len=255) == name


def test_truncate_filename_long_truncated():
    # 250 + 5 = 255 bytes, within limit, unchanged
    assert truncate_filename('A' * 250 + '.html', max_len=255) == 'A' * 250 + '.html'


def test_truncate_filename_multi_dot_extension():
    # 300 + 7 = 307 bytes, exceeds limit. Only last suffix '.gz' is preserved.
    # stem = 'A'*300 + '.tar' (304 bytes), available = 255 - 3 = 252 bytes for stem
    # truncated stem = 'A'*252 → result = 'A'*252 + '.gz'
    assert truncate_filename('A' * 300 + '.tar.gz', max_len=255) == 'A' * 252 + '.gz'


def test_truncate_filename_no_extension():
    name = 'A' * 250
    # 250 bytes, within limit
    assert truncate_filename(name, max_len=255) == name


def test_truncate_filename_long_extension():
    name = 'A.' + 'B' * 250
    # 252 bytes, within limit
    assert truncate_filename(name, max_len=255) == name


def test_truncate_filename_custom_max_len():
    expected = 'A' * 45 + '.html'
    assert truncate_filename('A' * 100 + '.html', max_len=50) == expected

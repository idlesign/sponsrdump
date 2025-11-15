import pytest


@pytest.fixture(autouse=True)
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

    monkeypatch.setattr("sponsrdump.utils.Popen", MockPopen)
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


@pytest.fixture
def project_html(datafix_read):
    """Фикстура для HTML проекта."""
    return datafix_read("project.html")

from sponsrdump.cli import main


def test_main_smoke(remote_data, response_mock):
    with response_mock(remote_data.rules):
        main('https://sponsr.ru/test_project', '--title', 'Test', '--prefer-video', '640x480')

def test_main_smoke_filter(remote_data, response_mock):
    with response_mock(remote_data.rules):
        main('https://sponsr.ru/test_project', '--filter', 'Test', '--prefer-video', '640x480')

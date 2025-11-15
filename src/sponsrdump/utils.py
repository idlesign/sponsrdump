import logging
from contextlib import chdir
from pathlib import Path
from shutil import copyfileobj
from subprocess import PIPE, Popen
from textwrap import wrap

from .exceptions import SponsrDumperError

PATH_BASE = Path(__file__).parent.absolute()
LOGGER = logging.getLogger('sponsrdump')


def call(cmd: str, *, cwd: Path, capture_out: bool = True):
    prc = Popen(cmd, cwd=cwd, shell=True, stdout=PIPE if capture_out else None, stderr=PIPE)
    out, err = [item.decode() if item else '' for item in prc.communicate()]

    if prc.returncode:
        raise SponsrDumperError(f'Command error:\n{cmd}\n\n{out}\n\n{err}\n----------')


def convert_text_to_video(src: Path) -> Path:

    font = 'tahoma.ttf'
    line_width = 80
    sec_per_line = 3
    sec_plus = 5
    line_space = 20
    font_size = 25

    fname_stem = src.stem

    path_bg = PATH_BASE / 'bg.png'
    path_tmp_bg = src.with_suffix('.mp4').with_stem(f'{fname_stem}_bg')
    path_tmp_bg.unlink(missing_ok=True)

    path_tmp_text = src.with_suffix('.txt').with_stem(f'{fname_stem}_txt')
    path_tmp_text.unlink(missing_ok=True)

    path_target = src.with_suffix('.mp4').with_stem(f'{fname_stem} [txt]')
    path_target.unlink(missing_ok=True)

    LOGGER.info(f'  Generating text video: {path_target} ...')

    with src.open() as f:
        text = f.read()

    text = text.strip().strip('_ ').strip().replace('\u200e', '').replace('\u200f', '')

    lines = []
    for line in text.splitlines():
        lines.extend(wrap(line, width=line_width))

    vid_len = (len(lines) * sec_per_line) + sec_plus

    with path_tmp_text.open('w') as f:
        f.write('\r\n'.join(lines))

    call(f'ffmpeg -loop 1 -t {vid_len} -i "{path_bg}" "{path_tmp_bg}"', cwd=src.parent)

    try:
        call(
            (
                f'ffmpeg -i "{path_tmp_bg}" -filter_complex "'
                '[0]split[txt][orig];'
                '[txt]drawtext='
                f'fontfile={font}:'
                f'fontsize={font_size}:'
                'fontcolor=white:'
                f'x=(w-text_w)/2+{line_space}:'
                f'y=h-{line_space}*t:'
                f'textfile=\'{path_tmp_text}\':'
                'bordercolor=black:'
                f'line_spacing={line_space}:'
                'borderw=3[txt];'
                '[orig]crop=iw:50:0:0[orig];'
                '[txt][orig]overlay" '
                f'-c:v libx264 -y -preset ultrafast -t {vid_len} "{path_target}"'
            ),
            cwd=src.parent,
        )

    finally:
        path_tmp_bg.unlink(missing_ok=True)
        path_tmp_text.unlink(missing_ok=True)

    return path_target


def concat_files(*, src: Path, suffix: str, target_name: str) -> Path:

    with chdir(src):
        src_files = sorted([f'{fname}' for fname in src.iterdir() if f'_{suffix}.' in f'{fname}'])
        target = src / target_name

        with target.open("wb") as out:
            for src_file in src_files:
                source = src / src_file
                with source.open("rb") as f:
                    copyfileobj(f, out)
                source.unlink()

    return target

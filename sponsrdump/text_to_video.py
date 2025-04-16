import logging
from pathlib import Path
from subprocess import Popen, PIPE
from textwrap import wrap

logger = logging.getLogger(__name__)


def text_to_video(src: Path, ffmpeg_path: str):
    font = 'tahoma.ttf'
    line_width = 80
    sec_per_line = 3
    sec_plus = 5
    line_space = 20
    font_size = 25
    fname_stem = src.stem

    path_base = Path(__file__).parent
    path_bg = path_base / 'bg.png'
    path_tmp_bg = src.with_suffix('.mp4').with_stem(f'{fname_stem}_bg')
    path_tmp_text = src.with_suffix('.txt').with_stem(f'{fname_stem}_txt')
    path_target = src.with_suffix('.mp4').with_stem(f'{fname_stem} [txt]')

    path_tmp_bg.unlink(missing_ok=True)
    path_tmp_text.unlink(missing_ok=True)
    path_target.unlink(missing_ok=True)

    logger.info(f'Generating text video: {path_target} ...')
    with open(src) as f:
        text = f.read()
    text = text.strip().replace('\u200e', '').replace('\u200f', '')
    lines = []
    for line in text.splitlines():
        lines.extend(wrap(line, width=line_width))
    vid_len = (len(lines) * sec_per_line) + sec_plus

    with open(path_tmp_text, 'w') as f:
        f.write('\r\n'.join(lines))

    call(f'ffmpeg -loop 1 -t {vid_len} -i "{path_bg}" "{path_tmp_bg}"', src.parent, ffmpeg_path)
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
            src.parent,
            ffmpeg_path
        )
    finally:
        path_tmp_bg.unlink(missing_ok=True)
        path_tmp_text.unlink(missing_ok=True)

    return path_target


def call(cmd: str, cwd: Path, ffmpeg_path: str):
    prc = Popen(cmd.replace('ffmpeg', ffmpeg_path), cwd=cwd, shell=True, stdout=PIPE, stderr=PIPE)
    out, err = [item.decode() if item else '' for item in prc.communicate()]
    if prc.returncode:
        raise RuntimeError(f'Command error: {cmd}\n{out}\n{err}')
import logging
import subprocess
from pathlib import Path
from textwrap import wrap

from .utils import PATH_BASE

logger = logging.getLogger(__name__)


def text_to_video(src: Path, ffmpeg_path: str, temp_dir: Path = None) -> Path:
    font = 'tahoma.ttf'
    line_width = 80
    sec_per_line = 3
    sec_plus = 5
    line_space = 20
    font_size = 25

    fname_stem = src.stem
    temp_dir = temp_dir or src.parent
    temp_dir.mkdir(parents=True, exist_ok=True)

    path_bg = PATH_BASE / 'bg.png'
    if not path_bg.exists():
        raise FileNotFoundError(f"Background image {path_bg} not found")

    path_tmp_bg = temp_dir / f'{fname_stem}_bg.mp4'
    path_tmp_text = temp_dir / f'{fname_stem}_txt.txt'
    path_target = src.with_suffix('.mp4').with_stem(f'{fname_stem} [txt]')

    path_tmp_bg.unlink(missing_ok=True)
    path_tmp_text.unlink(missing_ok=True)
    path_target.unlink(missing_ok=True)

    logger.info(f'Generating text video: {path_target} ...')

    with open(src, encoding='utf-8') as f:
        text = f.read()

    text = text.strip().strip('_ ').strip().replace('\u200e', '').replace('\u200f', '')

    lines = []
    for line in text.splitlines():
        lines.extend(wrap(line, width=line_width))

    vid_len = (len(lines) * sec_per_line) + sec_plus

    with open(path_tmp_text, 'w', encoding='utf-8') as f:
        f.write('\r\n'.join(lines))

    try:
        cmd = (
            f'"{ffmpeg_path}" -loop 1 -t {vid_len} -i "{path_bg}" '
            f'-c:v libx264 -y -preset ultrafast "{path_tmp_bg}"'
        )
        subprocess.run(cmd, shell=True, check=True, cwd=temp_dir)

        cmd = (
            f'"{ffmpeg_path}" -i "{path_tmp_bg}" -filter_complex "'
            f'[0]split[txt][orig];'
            f'[txt]drawtext='
            f'fontfile={font}:'
            f'fontsize={font_size}:'
            f' FONT_SIZE: {font_size}:'
            f'fontcolor=white:'
            f'x=(w-text_w)/2+{line_space}:'
            f'y=h-{line_space}*t:'
            f'textfile=\'{path_tmp_text}\':'
            f'bordercolor=black:'
            f'line_spacing={line_space}:'
            f'borderw=3[txt];'
            f'[orig]crop=iw:50:0:0[orig];'
            f'[txt][orig]overlay" '
            f'-c:v libx264 -y -preset ultrafast -t {vid_len} "{path_target}"'
        )
        subprocess.run(cmd, shell=True, check=True, cwd=temp_dir)

    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error: {e}")
        raise

    finally:
        path_tmp_bg.unlink(missing_ok=True)
        path_tmp_text.unlink(missing_ok=True)

    return path_target

import argparse
import logging
from pathlib import Path
from sponsrdump.config import load_config
from sponsrdump.dumper import SponsrDumper


def setup_logging(debug: bool):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=level, format='%(levelname)-8s: %(message)s')


def parse_args():
    parser = argparse.ArgumentParser(description="Dump content from sponsr.ru")
    parser.add_argument('project_url', help='Project URL')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--title', default='', help='Filter posts by title')
    parser.add_argument('--to', default='dump/', help='Output directory')
    parser.add_argument('--prefer-video', default='best', help='Preferred video resolution')
    parser.add_argument('--text-fmt', default='md', choices=['html', 'md'], help='Text format')
    parser.add_argument('--no-audio', action='store_true', help='Skip audio')
    parser.add_argument('--no-video', action='store_true', help='Skip video')
    parser.add_argument('--no-text', action='store_true', help='Skip text')
    parser.add_argument('--no-images', action='store_true', help='Skip images')
    parser.add_argument('--text-to-video', action='store_true', help='Convert text to video')
    parser.add_argument('--ffmpeg-path', help='Path to ffmpeg (auto-detected if not specified)')
    parser.add_argument('--mp4decrypt-path', help='Path to mp4decrypt (auto-detected if not specified)')
    parser.add_argument('--parallel', type=int, default=1, help='Parallel downloads')
    parser.add_argument('--referer', default=None, help='Referer for videos')
    parser.add_argument('--config', type=Path, help='Configuration file')
    return parser.parse_args()


def main():
    args = parse_args()
    setup_logging(args.debug)

    config = load_config(args.config) if args.config else {}
    config.update({
        'ffmpeg_path': args.ffmpeg_path,
        'mp4decrypt_path': args.mp4decrypt_path,
        'referer': args.referer,
        'parallel': args.parallel,
    })

    dumper = SponsrDumper(
        url=args.project_url,
        ffmpeg_path=config.get('ffmpeg_path'),
        mp4decrypt_path=config.get('mp4decrypt_path'),
        referer=config.get('referer')
    )

    filter_func = None
    if title := args.title.strip():
        filter_func = lambda post_info: title in post_info['post_title']

    dumper.search(func_filter=filter_func)
    dumper.dump(
        dest=args.to,
        prefer_video=args.prefer_video,
        audio=not args.no_audio,
        video=not args.no_video,
        images=not args.no_images,
        text=False if args.no_text else args.text_fmt.lower(),
        text_to_video=args.text_to_video,
        parallel=config['parallel']
    )


if __name__ == '__main__':
    main()
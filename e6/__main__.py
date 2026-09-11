import argparse
import logging
from pathlib import Path

from .gpio import GPIOBus
from .panel import COLORS, FRAME_BYTES, Panel, color_bars, solid, validate_frame


def pin(value):
    try:
        chip, number = value.rsplit(':', 1)
        offset = int(number)
        if not chip.startswith('/dev/gpiochip') or offset < 0:
            raise ValueError
        return chip, offset
    except ValueError:
        raise argparse.ArgumentTypeError('use /dev/gpiochipN:OFFSET (nonnegative line offset)')


def main():
    parser = argparse.ArgumentParser(description='GDEH037E01 720x480 six-color GPIO software SPI')
    for signal in ('mosi', 'clk', 'cs', 'dc', 'rst', 'busy'):
        parser.add_argument('--' + signal, type=pin, help='/dev/gpiochipN:OFFSET')
    parser.add_argument('--busy-level', type=int, choices=(0, 1), default=0)
    parser.add_argument('--half-period-us', type=float, default=5,
                        help='minimum SPI half period; actual clock is slower (default: 5)')
    content = parser.add_mutually_exclusive_group(required=True)
    content.add_argument('--solid', choices=COLORS)
    content.add_argument('--bars', action='store_true')
    content.add_argument('--image', type=Path, help='172800-byte packed 4bpp raw frame')
    parser.add_argument('--dry-run', action='store_true', help='validate frame only; no GPIO access')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    try:
        if args.image:
            with args.image.open('rb') as stream:
                frame = stream.read(FRAME_BYTES + 1)
        else:
            frame = color_bars() if args.bars else solid(args.solid)
        validate_frame(frame)
        if args.dry_run:
            logging.info('valid frame: %d bytes; no hardware accessed', len(frame))
            return 0
        pins = {s: getattr(args, s) for s in ('mosi', 'clk', 'cs', 'dc', 'rst', 'busy')}
        if any(v is None for v in pins.values()):
            parser.error('hardware access requires all six GPIO arguments')
        with GPIOBus(pins, args.half_period_us) as bus:
            Panel(bus, args.busy_level).display(frame)
        return 0
    except (OSError, ValueError, RuntimeError, ImportError) as error:
        logging.error('%s', error)
        return 1
    except KeyboardInterrupt:
        logging.error('interrupted; refresh may be incomplete; verify panel power/BUSY before retry')
        return 130


if __name__ == '__main__':
    raise SystemExit(main())

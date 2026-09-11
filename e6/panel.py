"""Panel protocol ported from refs/main/GDEH037E01_idf.c (normal init)."""
import logging
import time

WIDTH, HEIGHT = 720, 480
FRAME_BYTES = WIDTH * HEIGHT // 2
COLORS = dict(black=0, white=1, yellow=2, red=3, blue=5, green=6)


def validate_frame(frame):
    if len(frame) != FRAME_BYTES:
        raise ValueError(f'frame must contain exactly {FRAME_BYTES} bytes')
    valid = set(COLORS.values())
    if any(b >> 4 not in valid or b & 15 not in valid for b in frame):
        raise ValueError('frame contains unsupported color code (allowed: 0,1,2,3,5,6)')


def solid(color):
    value = COLORS[color]
    return bytes([value * 17]) * FRAME_BYTES


def color_bars():
    return b''.join(bytes([COLORS[c] * 17]) * (FRAME_BYTES // 6)
                    for c in ('red', 'yellow', 'blue', 'black', 'white', 'green'))


class Panel:
    def __init__(self, bus, busy_level=0, sleep=time.sleep, clock=time.monotonic):
        self.bus = bus
        self.busy_level = busy_level
        self.sleep = sleep
        self.clock = clock

    def wait_ready(self, stage, timeout):
        deadline = self.clock() + timeout
        while self.bus.busy() == self.busy_level:
            if self.clock() >= deadline:
                raise TimeoutError(f'{stage}: BUSY remained {self.busy_level} for {timeout}s')
            self.sleep(0.005)

    def wait_refresh_cycle(self, timeout=120):
        # A refresh should spend a substantial period BUSY. An idle-only check
        # can falsely succeed when the command was not accepted or BUSY is disconnected.
        deadline = self.clock() + 1.0
        while self.bus.busy() != self.busy_level:
            if self.clock() >= deadline:
                raise TimeoutError('refresh: BUSY did not assert within 1s; check BUSY wiring, polarity and command transmission')
            self.sleep(0.001)
        logging.info('refresh: BUSY asserted')
        self.wait_ready('refresh', timeout)
        logging.info('refresh: BUSY released')

    def command(self, command, data=b''):
        self.bus.write(False, bytes([command]))
        if data:
            self.bus.write(True, data)

    def display(self, frame, progress=lambda stage: None):
        # Reject invalid input before touching hardware.
        validate_frame(frame)
        progress('reset')
        self.sleep(0.3)
        self.bus.reset(0)
        self.sleep(0.02)
        self.bus.reset(1)
        self.sleep(0.02)
        self.wait_ready('reset', 15)
        self.sleep(0.01)
        self.command(0xE9, b'\x01')
        self.command(0x10)
        self.wait_ready('DTM1', 15)
        progress('writing')
        logging.info('writing %d frame bytes', len(frame))
        self.bus.write(True, frame)
        # Allow BUSY assertion before polling; never invert or bypass BUSY.
        for stage, command, data, timeout in (
            ('power on', 0x04, b'', 60),
            ('refresh', 0x12, b'\x00', 120),
            ('power off', 0x02, b'\x00', 60),
        ):
            progress(stage)
            logging.info(stage)
            self.command(command, data)
            if stage == 'refresh':
                self.wait_refresh_cycle(timeout)
            else:
                self.sleep(0.01)
                self.wait_ready(stage, timeout)
            self.sleep(0.01)
        self.command(0x07, b'\xa5')
        progress('sleep')
        logging.info('deep sleep')

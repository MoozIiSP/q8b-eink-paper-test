"""4-wire SPI mode 0, MSB first, using libgpiod 2.x line requests."""
import math
import time
from contextlib import ExitStack


class GPIOBus:
    def __init__(self, pins, half_period_us=5):
        if set(pins) != {'mosi', 'clk', 'cs', 'dc', 'rst', 'busy'}:
            raise ValueError('all six GPIO signals are required')
        if len(set(pins.values())) != len(pins):
            raise ValueError('GPIO signals must use distinct chip/offset pairs')
        if not math.isfinite(half_period_us) or half_period_us < 1:
            raise ValueError('half-period must be finite and >= 1 microsecond')
        self.pins = pins
        self.half_period = half_period_us / 1_000_000
        self.stack = ExitStack()
        self.requests = {}

    def __enter__(self):
        import gpiod
        from gpiod.line import Direction, Value
        if not hasattr(gpiod, 'request_lines'):
            raise RuntimeError('libgpiod Python bindings 2.x required')
        self.values = (Value.INACTIVE, Value.ACTIVE)
        initial = dict(mosi=0, clk=0, cs=1, dc=1, rst=1)
        configs = {}
        for name, (chip, offset) in self.pins.items():
            configs.setdefault(chip, {})[offset] = gpiod.LineSettings(
                direction=Direction.INPUT if name == 'busy' else Direction.OUTPUT,
                output_value=self.values[initial.get(name, 0)],
            )
        try:
            for chip, config in configs.items():
                self.requests[chip] = self.stack.enter_context(gpiod.request_lines(
                    chip, consumer='e6-display', config=config))
        except BaseException:
            self.stack.close()
            raise
        return self

    def set(self, name, value):
        chip, offset = self.pins[name]
        self.requests[chip].set_value(offset, self.values[value])

    def setup_bit(self, value):
        # Explicit ordering: lower clock before changing data. A grouped ioctl
        # does not guarantee the order of electrical transitions across GPIO lines.
        self.set('clk', 0)
        self.set('mosi', value)

    def busy(self):
        chip, offset = self.pins['busy']
        return int(self.requests[chip].get_value(offset) == self.values[1])

    def reset(self, value):
        self.set('rst', value)

    def delay(self):
        # sleep() at each edge adds scheduler latency; spin for the minimum hold.
        deadline = time.perf_counter() + self.half_period
        while time.perf_counter() < deadline:
            pass

    def write(self, is_data, data):
        self.set('dc', int(is_data))
        # Match the reference's per-byte CS framing, including frame payload.
        for byte in data:
            self.set('cs', 0)
            try:
                for bit in range(7, -1, -1):
                    self.setup_bit((byte >> bit) & 1)
                    self.delay()
                    self.set('clk', 1)
                    self.delay()
                self.set('clk', 0)
                self.delay()
            finally:
                self.set('cs', 1)
            self.delay()

    def __exit__(self, exc_type, exc, tb):
        try:
            # No reset/power commands on failure: panel state may be busy.
            for name, value in (('cs', 1), ('clk', 0)):
                try:
                    self.set(name, value)
                except OSError:
                    pass
        finally:
            self.stack.close()

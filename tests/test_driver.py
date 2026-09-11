import unittest
from e6.gpio import GPIOBus
from e6.panel import FRAME_BYTES, Panel, color_bars, solid, validate_frame


class FakeBus:
    def __init__(self, busy=1):
        self.level = busy
        self.events = []
        self.refresh_samples = 0
        self.active_level = 0

    def busy(self):
        if self.refresh_samples:
            self.refresh_samples -= 1
            return self.active_level
        return self.level

    def reset(self, value):
        self.events.append(('reset', value))

    def write(self, data, payload):
        self.events.append(('data' if data else 'cmd', payload))
        if not data and payload == b'\x12':
            self.refresh_samples = 2


class FakeTime:
    def __init__(self):
        self.now = 0

    def sleep(self, seconds):
        self.now += seconds

    def clock(self):
        return self.now


class DriverTests(unittest.TestCase):
    def panel(self, bus):
        timer = FakeTime()
        return Panel(bus, sleep=timer.sleep, clock=timer.clock)

    def test_frame_validation(self):
        for size in (0, FRAME_BYTES - 1, FRAME_BYTES + 1):
            with self.assertRaises(ValueError):
                validate_frame(bytes(size))
        for value in (0x04, 0x40, 0x77, 0xff):
            with self.assertRaises(ValueError):
                validate_frame(bytes([value]) * FRAME_BYTES)
        validate_frame(color_bars())
        self.assertEqual(solid('green'), b'\x66' * FRAME_BYTES)

    def test_display_sequence_and_payload(self):
        bus = FakeBus()
        frame = color_bars()
        self.panel(bus).display(frame)
        self.assertEqual(bus.events, [
            ('reset', 0), ('reset', 1),
            ('cmd', b'\xe9'), ('data', b'\x01'),
            ('cmd', b'\x10'), ('data', frame),
            ('cmd', b'\x04'), ('cmd', b'\x12'), ('data', b'\x00'),
            ('cmd', b'\x02'), ('data', b'\x00'),
            ('cmd', b'\x07'), ('data', b'\xa5'),
        ])

    def test_invalid_frame_has_no_hardware_effect(self):
        bus = FakeBus()
        with self.assertRaises(ValueError):
            self.panel(bus).display(b'')
        self.assertEqual(bus.events, [])

    def test_busy_timeouts_stop_each_stage(self):
        for stage in ('reset', 'DTM1', 'power on', 'refresh', 'power off'):
            bus = FakeBus()
            panel = self.panel(bus)
            wait = panel.wait_ready
            def fail_at(current, timeout):
                if current == stage:
                    bus.level = 0
                wait(current, timeout)
            panel.wait_ready = fail_at
            with self.assertRaisesRegex(TimeoutError, stage):
                panel.display(solid('white'))
            commands = [v for k, v in bus.events if k == 'cmd']
            self.assertNotIn(b'\x07', commands)
            final = {'reset': None, 'DTM1': b'\x10', 'power on': b'\x04',
                     'refresh': b'\x12', 'power off': b'\x02'}[stage]
            self.assertEqual(commands[-1] if commands else None, final)

    def test_busy_high_configuration(self):
        panel = self.panel(FakeBus(busy=0))
        panel.busy_level = 1
        panel.bus.active_level = 1
        panel.display(solid('white'))

    def test_spi_rising_edges_msb_first_and_byte_cs(self):
        bus = GPIOBus(dict(zip(('mosi', 'clk', 'cs', 'dc', 'rst', 'busy'),
                              [('/dev/gpiochip0', n) for n in range(6)])))
        state = dict(clk=0, cs=1, mosi=0)
        bits, selects = [], []
        def set_line(name, value):
            if name == 'clk' and value == 1:
                self.assertEqual(state['cs'], 0)
                self.assertEqual(state['dc'], 1)
                bits.append(state['mosi'])
            if name == 'cs':
                selects.append(value)
            state[name] = value
        bus.setup_bit = lambda value: (set_line('clk', 0), set_line('mosi', value))
        bus.set = set_line
        bus.delay = lambda: None
        bus.write(True, b'\xa5\x12')
        self.assertEqual(bits, [int(c) for c in '1010010100010010'])
        self.assertEqual(selects, [0, 1, 0, 1])
        self.assertEqual(state['clk'], 0)

    def test_data_is_set_after_clock_low(self):
        bus = GPIOBus(dict(zip(('mosi', 'clk', 'cs', 'dc', 'rst', 'busy'),
                              [('/dev/gpiochip0', n) for n in range(6)])))
        from unittest.mock import Mock, call
        request = Mock()
        bus.requests = {'/dev/gpiochip0': request}
        bus.values = (0, 1)
        bus.setup_bit(1)
        self.assertEqual(request.set_value.call_args_list, [call(1, 0), call(0, 1)])
        request.set_values.assert_not_called()

    def test_idle_busy_must_not_report_refresh_success(self):
        bus = FakeBus()
        bus.busy = lambda: 1  # disconnected/stuck ready
        with self.assertRaisesRegex(TimeoutError, 'did not assert'):
            self.panel(bus).display(solid('white'))
        commands = [v for k, v in bus.events if k == 'cmd']
        self.assertEqual(commands[-1], b'\x12')
        self.assertNotIn(b'\x02', commands)
        self.assertNotIn(b'\x07', commands)

    def test_duplicate_lines_rejected(self):
        with self.assertRaises(ValueError):
            GPIOBus({s: ('/dev/gpiochip0', 1)
                     for s in ('mosi', 'clk', 'cs', 'dc', 'rst', 'busy')})


if __name__ == '__main__':
    unittest.main()

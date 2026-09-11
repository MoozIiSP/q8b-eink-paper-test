import io
import tempfile
import threading
import unittest
from pathlib import Path
from PIL import Image
from e6.imaging import convert, preview, RGB, CODES, pack, quantize, diagnostic
from e6.panel import FRAME_BYTES, solid, validate_frame
from e6.refresh import RefreshManager
from e6.web import create_app


def png(color='red', size=(720, 480)):
    stream = io.BytesIO()
    Image.new('RGB', size, color).save(stream, 'PNG')
    return stream.getvalue()


class ImagingTests(unittest.TestCase):
    def test_palette_roundtrip(self):
        for color, code in zip(RGB, CODES):
            frame, output = convert(png(color), 'none')
            self.assertEqual(frame, bytes([code * 17]) * FRAME_BYTES)
            self.assertEqual(Image.open(io.BytesIO(output)).getpixel((0, 0)), color)

    def test_transparency_and_fit(self):
        source = io.BytesIO()
        Image.new('RGBA', (20, 20), (0, 0, 0, 0)).save(source, 'PNG')
        frame, _ = convert(source.getvalue())
        self.assertEqual(frame, solid('white'))
        frame, _ = convert(png('red', (20, 20)), 'none', 'contain')
        self.assertEqual(frame[0], 0x11)
        frame, _ = convert(png('red', (20, 20)), 'none', 'cover')
        self.assertEqual(frame, solid('red'))

    def test_dithering_has_valid_codes_and_changes_midtones(self):
        a, _ = convert(png((120, 120, 120)), 'none')
        b, _ = convert(png((120, 120, 120)), 'floyd-steinberg')
        validate_frame(b)
        self.assertNotEqual(a, b)
        self.assertGreater(len(set(b)), 1)

    def test_landscape_scan_mapping_and_preview(self):
        codes = Image.new('L', (720, 480), 1)
        for point, value in [((0, 0), 3), ((719, 0), 2), ((0, 479), 5), ((719, 479), 6)]:
            codes.putpixel(point, value)
        frame = pack(codes)
        # CCW to native: top-right source maps to top-left native.
        self.assertEqual(frame[0] >> 4, 2)
        self.assertEqual(frame[239] & 15, 6)
        self.assertEqual(frame[-240] >> 4, 3)
        self.assertEqual(frame[-1] & 15, 5)
        image = Image.open(io.BytesIO(preview(frame)))
        self.assertEqual(image.size, (720, 480))
        self.assertEqual(image.getpixel((0, 0)), RGB[3])
        self.assertEqual(image.getpixel((719, 479)), RGB[5])
        self.assertEqual(Image.open(io.BytesIO(preview(frame, 'portrait'))).size, (480, 720))

    def test_additional_algorithms(self):
        image = Image.new('RGB', (48, 32), (120, 120, 120))
        for algorithm in ('atkinson', 'bayer'):
            result = quantize(image, algorithm, 1)
            self.assertTrue(set(result.tobytes()).issubset(CODES))
            self.assertGreater(len(set(result.tobytes())), 1)
            plain = quantize(image, algorithm, 0)
            self.assertEqual(len(set(plain.tobytes())), 1)
            for color, code in zip(RGB, CODES):
                pure = quantize(Image.new('RGB', (8, 8), color), algorithm, 1)
                self.assertEqual(set(pure.tobytes()), {code})

    def test_options_and_white_padding(self):
        for options in ({'gamma': 'nan'}, {'contrast': 9}, {'strength': -1}, {'enhance': 'bad'}):
            with self.assertRaises(ValueError):
                convert(png(), **options)
        for enhance in ('photo', 'soft'):
            frame, output = convert(png('red', (20, 20)), enhance=enhance, gamma=1.2)
            image = Image.open(io.BytesIO(output))
            self.assertEqual(image.size, (720, 480))
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
            validate_frame(frame)

    def test_diagnostic_exact_colors(self):
        for orientation, size in [('landscape', (720, 480)), ('portrait', (480, 720))]:
            frame, output = diagnostic(orientation)
            validate_frame(frame)
            image = Image.open(io.BytesIO(output))
            self.assertEqual(image.size, size)
            for i, rgb in enumerate(RGB):
                self.assertEqual(image.getpixel((i * size[0] // 6 + 10, 80)), rgb)

    def test_bad_image(self):
        with self.assertRaises(ValueError):
            convert(b'not an image')
        with self.assertRaises(ValueError):
            convert(png(), 'unknown')


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.json'
        self.now = 1000

    def manager(self, display):
        return RefreshManager(display, self.path, clock=lambda: self.now)

    def test_dedup_cooldown_restart_and_force(self):
        calls = []
        m = self.manager(lambda frame, progress: calls.append(frame))
        self.assertEqual(m.submit(solid('red')), 'started')
        m.thread.join(2)
        self.assertFalse(m.active)
        self.assertEqual(m.submit(solid('red')), 'unchanged')
        with self.assertRaises(ValueError):
            m.submit(solid('blue'))
        restarted = self.manager(lambda frame, progress: None)
        self.assertEqual(restarted.status()['wait_seconds'], 150)
        with self.assertRaises(ValueError):
            restarted.submit(solid('red'), force=True)
        self.now += 150
        self.assertEqual(restarted.submit(solid('red'), force=True), 'started')
        restarted.thread.join(2)

    def test_failure_invalidates_previous_frame(self):
        m = self.manager(lambda frame, progress: None)
        m.submit(solid('red')); m.thread.join(2)
        self.now += 150
        def fail(frame, progress):
            raise TimeoutError('refresh BUSY')
        m.display = fail
        m.submit(solid('blue')); m.thread.join(2)
        self.assertEqual(m.status()['stage'], 'failed')
        self.assertIsNone(m.status()['last_hash'])
        self.now += 150
        m.display = lambda frame, progress: None
        self.assertEqual(m.submit(solid('red')), 'started')
        m.thread.join(2)

    def test_serialization(self):
        gate = threading.Event()
        m = self.manager(lambda frame, progress: gate.wait(2))
        m.submit(solid('red'))
        try:
            with self.assertRaises(ValueError):
                m.submit(solid('white'))
        finally:
            gate.set(); m.thread.join(2)

    def test_interrupted_restart(self):
        self.path.write_text('{"last_hash": "old", "next_at": 0, "stage": "starting", "error": null}')
        m = self.manager(lambda frame, progress: None)
        self.assertIsNone(m.status()['last_hash'])
        self.assertEqual(m.status()['stage'], 'interrupted')
        self.assertEqual(m.status()['wait_seconds'], 150)


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.m = RefreshManager(lambda frame, progress: None, Path(self.temp.name) / 'state.json')
        self.app = create_app(self.m)
        self.app.testing = True
        self.client = self.app.test_client()

    def test_no_auth_and_status(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/api/status').status_code, 200)
        self.assertEqual(self.client.post('/api/refresh', json={}).status_code, 400)
        self.assertTrue(self.client.get('/api/status').json['simulate'])

    def test_upload_preview_refresh(self):
        response = self.client.post('/api/prepare', data={'image': (io.BytesIO(png()), 'test.png'),
                                    'algorithm': 'none', 'enhance': 'none'})
        self.assertEqual(response.status_code, 200)
        identifier = response.json['id']
        output = self.client.get('/api/preview/' + identifier)
        self.assertEqual(output.data, preview(solid('red')))
        response = self.client.post('/api/refresh', json={'id': identifier})
        self.assertEqual(response.json['result'], 'started')
        self.m.thread.join(2)
        self.assertEqual(self.client.post('/api/refresh', json={'id': identifier}).json['result'], 'unchanged')

    def test_stale_and_invalid(self):
        first = self.client.post('/api/prepare', data={'kind': 'bars'}).json['id']
        self.client.post('/api/prepare', data={'kind': 'white'})
        self.assertEqual(self.client.post('/api/refresh', json={'id': first}).status_code, 400)
        self.assertEqual(self.client.post('/api/prepare', data={'kind': 'bad'}).status_code, 400)
        self.assertEqual(self.client.post('/api/prepare', data={}).status_code, 400)
        self.assertEqual(self.client.post('/api/refresh', json=[]).status_code, 400)
        self.assertEqual(self.client.post('/api/prepare', data={'image': (io.BytesIO(b'bad'), 'a.png')}).status_code, 400)
        self.assertEqual(self.client.post('/api/prepare', data=b'x' * (10 * 1024 * 1024 + 1),
                                         content_type='multipart/form-data').status_code, 413)


if __name__ == '__main__':
    unittest.main()

"""Q8B local device management server. Simulation is the default."""
import argparse
import fcntl
import io
import secrets
import threading
import time
from pathlib import Path
from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException
from .imaging import convert, preview
from .panel import Panel, color_bars, solid
from .refresh import RefreshManager


def create_app(manager, simulate=True):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
    prepared = {}
    guard = threading.Lock()

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; frame-ancestors 'none'"
        return response

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error='上传不能超过 10 MiB' if error.code == 413 else error.description), error.code

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/status')
    def status():
        return jsonify(dict(manager.status(), simulate=simulate))

    @app.post('/api/prepare')
    def prepare():
        # Bound conversion concurrency and retained frames: one shared draft.
        if not guard.acquire(blocking=False):
            return jsonify(error='正在生成预览，请稍后再试'), 409
        try:
            kind = request.form.get('kind', 'image')
            if kind == 'image':
                upload = request.files.get('image')
                if upload is None:
                    raise ValueError('请选择图片')
                frame, png = convert(upload.read(), request.form.get('algorithm', 'floyd-steinberg'),
                                     request.form.get('fit', 'contain'))
            elif kind in ('white', 'bars'):
                frame = solid('white') if kind == 'white' else color_bars()
                png = preview(frame)
            else:
                raise ValueError('未知图像类型')
            identifier = secrets.token_urlsafe(18)
            prepared.clear()
            prepared.update(id=identifier, frame=frame, png=png)
            return jsonify(id=identifier, bytes=len(frame))
        finally:
            guard.release()

    @app.get('/api/preview/<identifier>')
    def get_preview(identifier):
        with guard:
            if prepared.get('id') != identifier:
                return jsonify(error='预览已过期，请重新生成'), 404
            png = prepared['png']
        return send_file(io.BytesIO(png), mimetype='image/png')

    @app.post('/api/refresh')
    def refresh():
        payload = request.get_json()
        if not isinstance(payload, dict) or type(payload.get('force', False)) is not bool:
            raise ValueError('无效请求')
        with guard:
            if prepared.get('id') != payload.get('id') or 'frame' not in prepared:
                raise ValueError('预览已过期，请重新生成')
            frame = prepared['frame']
        return jsonify(result=manager.submit(frame, force=payload.get('force', False)))

    return app


def main():
    parser = argparse.ArgumentParser(description='E6 Web manager (simulation by default)')
    parser.add_argument('--hardware', action='store_true', help='enable real Q8B GPIO access')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--chip', default='/dev/gpiochip4')
    parser.add_argument('--state-dir', type=Path, default=Path('var'))
    parser.add_argument('--busy-level', type=int, choices=(0, 1), default=0)
    for signal, offset in dict(mosi=88, clk=89, cs=90, dc=92, rst=110, busy=68).items():
        parser.add_argument('--' + signal, type=int, default=offset)
    args = parser.parse_args()
    pins = {s: (args.chip, getattr(args, s)) for s in ('mosi', 'clk', 'cs', 'dc', 'rst', 'busy')}
    args.state_dir.mkdir(parents=True, exist_ok=True)
    # One server per state directory; do not launch multiple WSGI worker processes.
    lock_file = (args.state_dir / 'web.lock').open('a')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('another E6 server is using this state directory')

    def display(frame, progress):
        if args.hardware:
            from .gpio import GPIOBus
            with GPIOBus(pins) as bus:
                Panel(bus, args.busy_level).display(frame, progress=progress)
        else:
            for stage in ('reset', 'writing', 'power on', 'refresh', 'power off', 'sleep'):
                progress(stage)
                time.sleep(0.3)

    state_file = args.state_dir / ('hardware.json' if args.hardware else 'simulation.json')
    manager = RefreshManager(display, state_file)
    from waitress import serve
    print(f'E6 manager: http://{args.host}:{args.port} ({"hardware" if args.hardware else "simulation"})', flush=True)
    serve(create_app(manager, not args.hardware), host=args.host, port=args.port, threads=4)


if __name__ == '__main__':
    main()

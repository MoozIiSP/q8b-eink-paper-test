"""Single active refresh, successful-frame deduplication and durable cooldown."""
import hashlib
import json
import math
import os
import threading
import time
from pathlib import Path
from .panel import validate_frame


class RefreshManager:
    def __init__(self, display, state_path, interval=150, clock=time.time):
        self.display = display
        self.path = Path(state_path)
        self.interval = interval
        self.clock = clock
        self.lock = threading.Lock()
        self.active = False
        self.thread = None
        self.state = dict(last_hash=None, next_at=0, stage='idle', error=None)
        if self.path.exists():
            saved = json.loads(self.path.read_text())
            self.state.update(saved)
            if self.state['stage'] not in ('done', 'idle'):
                self.state.update(last_hash=None, stage='interrupted', error='上次任务未完成，请检查面板')
                self.state['next_at'] = max(self.state['next_at'], self.clock() + interval)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        with temp.open('w') as stream:
            json.dump(self.state, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(self.path)

    def status(self):
        with self.lock:
            return dict(self.state, active=self.active,
                        wait_seconds=max(0, math.ceil(self.state['next_at'] - self.clock())))

    def submit(self, frame, force=False):
        validate_frame(frame)
        digest = hashlib.sha256(frame).hexdigest()
        with self.lock:
            if self.active:
                raise ValueError('已有刷新任务正在执行')
            if not force and digest == self.state['last_hash']:
                return 'unchanged'
            if self.clock() < self.state['next_at']:
                raise ValueError('刷新间隔未到，请等待倒计时结束')
            self.state.update(stage='starting', error=None, last_hash=None,
                              next_at=self.clock() + self.interval)
            self.save()  # Persist uncertainty before any hardware operation.
            self.active = True
            self.thread = threading.Thread(target=self.run, args=(bytes(frame), digest), daemon=True)
            self.thread.start()
            return 'started'

    def progress(self, stage):
        with self.lock:
            self.state['stage'] = stage

    def run(self, frame, digest):
        try:
            self.display(frame, self.progress)
            with self.lock:
                self.state.update(last_hash=digest, stage='done', error=None)
        except Exception as error:
            with self.lock:
                self.state.update(last_hash=None, stage='failed', error=str(error))
        finally:
            with self.lock:
                # Conservative: 150s from completion/failure, not just start.
                self.state['next_at'] = self.clock() + self.interval
                try:
                    self.save()
                except OSError as error:
                    self.state.update(last_hash=None, stage='failed', error=f'状态保存失败: {error}')
                self.active = False

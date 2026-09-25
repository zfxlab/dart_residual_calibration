"""Bounded ROS capture owned by the local workbench service."""

import atexit
import json
import os
import subprocess
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from .data import assign_segment


class Capture:
    def __init__(self, topic, duration, limit, *, preview=False, message_type=None):
        self.id = str(uuid.uuid4())
        self.topic = topic
        self.duration = duration
        self.limit = limit
        self.preview = preview
        self.samples = deque(maxlen=limit) if preview else []
        self.logs = deque(maxlen=30)
        self.lock = threading.Lock()
        self.started = time.monotonic()
        self.last_received = None
        self.stopped = False
        self.process = subprocess.Popen(
            [
                os.environ.get("DART_ROS_PYTHON", "/usr/bin/python3"),
                "-u",
                str(Path(__file__).with_name("worker.py")),
                "--topic",
                topic,
                "--duration",
                str(duration),
                "--limit",
                str(limit),
            ]
            + (["--preview"] if preview else [])
            + (["--message-type", message_type] if message_type else []),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.reader = threading.Thread(target=self._read, daemon=True)
        atexit.register(self.stop)
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                with self.lock:
                    try:
                        sample = json.loads(line)
                        if not isinstance(sample, dict) or "stamp_ns" not in sample:
                            raise ValueError("not a sample")
                        if self.preview or len(self.samples) < self.limit:
                            previous = self.samples[-1] if self.samples else None
                            sample["elapsed_s"] = time.monotonic() - self.started
                            self.samples.append(assign_segment(sample, previous))
                            self.last_received = time.monotonic()
                    except (ValueError, KeyError, TypeError):
                        self.logs.append(line.rstrip())
        finally:
            self.process.stdout.close()
            self.process.wait()
            atexit.unregister(self.stop)

    @property
    def running(self):
        return self.process.poll() is None or self.reader.is_alive()

    def snapshot(self):
        with self.lock:
            return list(self.samples), list(self.logs), self.last_received

    def stop(self):
        if self.process.poll() is None:
            self.stopped = True
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self.reader.join(timeout=2)
        atexit.unregister(self.stop)

"""Local data workbench: standalone web UI and numeric fitting API."""

import argparse
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd
from plotly.offline import get_plotlyjs

from .analysis.expressions import derive
from .analysis.fitting import describe_model, fit_data
from .capture.manager import Capture
from .capture.summary import summarize_capture

ROOT = Path(__file__).resolve().parents[1] / "frontend"
MAX_ROWS = 100000
MAX_BODY = 32 * 1024 * 1024




class Handler(BaseHTTPRequestHandler):
    capture = None
    capture_lock = threading.Lock()
    plotly = None

    def reply(self, content, status=200, mime="application/json; charset=utf-8"):
        raw = content if isinstance(content, bytes) else json.dumps(content, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/capture":
            with self.capture_lock:
                capture = type(self).capture
                if not capture:
                    return self.reply({"running": False, "samples": [], "logs": []})
                samples, logs, _ = capture.snapshot()
                return self.reply({"capture_id": capture.id, "running": capture.running, "samples": samples, "logs": logs, "topic": capture.topic})
        if path == "/plotly.js":
            if type(self).plotly is None:
                type(self).plotly = get_plotlyjs().encode()
            return self.reply(type(self).plotly, mime="text/javascript; charset=utf-8")
        assets = {"/": ("index.html", "text/html"), "/app.js": ("js/app.js", "text/javascript"),
                  "/features.js": ("js/features.js", "text/javascript"), "/project.js": ("js/project.js", "text/javascript"),
                  "/capture-summary.js": ("js/capture-summary.js", "text/javascript"),
                  "/style.css": ("css/style.css", "text/css"), "/features.css": ("css/features.css", "text/css")}
        if path in assets:
            name, mime = assets[path]
            return self.reply((ROOT / name).read_bytes(), mime=mime + "; charset=utf-8")
        self.reply({"error": "Not found"}, 404)

    def do_POST(self):
        # Mutations are local, same-origin JSON requests only.
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            return self.reply({"error": "拒绝跨站请求。"}, 403)
        if self.headers.get_content_type() != "application/json":
            return self.reply({"error": "需要 application/json。"}, 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise ValueError("请求为空或超过 32 MB。")
            payload = json.loads(self.rfile.read(length))
            if self.path == "/api/capture/summary":
                with self.capture_lock:
                    capture = type(self).capture
                    if not capture or capture.running:
                        raise ValueError("请先停止采集后再计算汇总。")
                    if payload.get("capture_id") != capture.id:
                        raise ValueError("采集已变化，请重新计算。")
                    samples, _, _ = capture.snapshot()
                    capture_id, topic = capture.id, capture.topic
                result = summarize_capture(samples, payload)
                return self.reply({**result, "capture_id": capture_id, "topic": topic})
            if self.path == "/api/fit":
                return self.reply(fit_data(payload))
            if self.path == "/api/derive":
                return self.reply(derive(payload))
            if self.path == "/api/model":
                return self.reply(describe_model(payload))
            if self.path == "/api/import":
                frame = pd.read_csv(io.StringIO(payload["csv"]), keep_default_na=True)
                if len(frame) > MAX_ROWS or not len(frame.columns):
                    raise ValueError("CSV 需要表头，最多支持 100000 行。")
                frame = frame.replace([np.inf, -np.inf], np.nan)
                return self.reply({"columns": list(frame.columns), "rows": json.loads(frame.to_json(orient="records"))})
            if self.path in ("/api/capture/start", "/api/capture/stop"):
                with self.capture_lock:
                    cls = type(self)
                    if self.path.endswith("stop"):
                        if cls.capture:
                            cls.capture.stop()
                    else:
                        if cls.capture and cls.capture.running:
                            raise ValueError("已有采集正在运行，请先停止。")
                        topic = str(payload["topic"])
                        duration, limit = float(payload["duration"]), int(payload["limit"])
                        if not topic.startswith("/") or any(c.isspace() for c in topic):
                            raise ValueError("请输入完整 ROS 话题路径。")
                        if not 1 <= duration <= 3600 or not 1 <= limit <= MAX_ROWS:
                            raise ValueError("时长范围 1–3600 秒，样本上限 1–100000。")
                        cls.capture = Capture(topic, duration, limit, message_type=str(payload.get("message_type", "dart_interfaces/msg/StereoTarget")))
                    return self.reply({"ok": True})
            self.reply({"error": "Not found"}, 404)
        except (ValueError, TypeError, KeyError, OSError, np.linalg.LinAlgError) as error:
            self.reply({"error": str(error)}, 400)


def main():
    parser = argparse.ArgumentParser(description="Data Workbench")
    parser.add_argument("--port", "--server.port", type=int, default=8501)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Data Workbench → http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if Handler.capture:
            Handler.capture.stop()


if __name__ == "__main__":
    main()

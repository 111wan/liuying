import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from api.douyin_mint import _read_cdp_version


def test_cdp_version_ignores_system_proxy(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/test"}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    try:
        result = _read_cdp_version(server.server_port)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

    assert result["webSocketDebuggerUrl"].endswith("/test")

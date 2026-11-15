"""Serve index.html and proxy its /api requests to agent.py on localhost:8001."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import ipaddress

ROOT = Path(__file__).resolve().parent
API = "http://127.0.0.1:8001"


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        request = Request(API + self.path, data=body, method=self.command,
                          headers={"Content-Type": self.headers.get("Content-Type", "application/json")})
        try:
            with urlopen(request, timeout=180) as response:
                self._send(response.status, response.headers.get("Content-Type", "application/json"), response.read())
        except HTTPError as exc:
            self._send(exc.code, exc.headers.get("Content-Type", "application/json"), exc.read())
        except (URLError, TimeoutError) as exc:
            message = ("{\"error\":\"Recruiter API is unavailable. Start it with: python agent.py --serve\"}").encode()
            self._send(502, "application/json; charset=utf-8", message)

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._proxy()
        if self.path not in ("/", "/index.html"):
            return self._send(404, "text/plain; charset=utf-8", b"Not found")
        page = ROOT / "index.html"
        if not page.exists():
            return self._send(404, "text/plain; charset=utf-8", b"index.html missing")
        return self._send(200, "text/html; charset=utf-8", page.read_bytes())

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self._proxy()
        return self._send(404, "application/json", b"{\"error\":\"Not found\"}")

    def log_message(self, *_args):
        return


def main():
    host, port = "127.0.0.1", 8000
    if not ipaddress.ip_address(host).is_loopback:
        raise RuntimeError("UI server must bind to loopback.")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Open Saral Recruiter at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

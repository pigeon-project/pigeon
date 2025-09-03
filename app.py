import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer


MESSAGE = {"message": "Hello, World!!!"}


class HelloHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server naming)
        if self.path == "/":
            body = json.dumps(MESSAGE).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404, "Not Found")

    def log_message(self, format: str, *args):  # type: ignore[override]
        # More concise logs suitable for containerized environments
        try:
            client = f"{self.client_address[0]}:{self.client_address[1]}"
        except Exception:
            client = "-"
        msg = f"{self.command} {self.path} {self.protocol_version} - {client} - " + format % args
        print(msg)


def run():
    port = int(os.environ.get("PORT", "8000"))
    host = "0.0.0.0"  # Listen on all interfaces for Docker
    with HTTPServer((host, port), HelloHandler) as httpd:
        print(f"Serving on http://{host}:{port}")
        httpd.serve_forever()


if __name__ == "__main__":
    run()

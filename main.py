import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HELLO_RESPONSE = {"message": "Hello, World"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003 - keep default signature
        # Keep server output quiet (useful for automated tests)
        pass

    def do_GET(self) -> None:  # noqa: N802 - http.server API uses camelcase
        if self.path == "/":
            body = json.dumps(HELLO_RESPONSE).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # Fallback 404 for any other path
        body = json.dumps({"error": "Not Found"}).encode("utf-8")
        self.send_response(404)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()


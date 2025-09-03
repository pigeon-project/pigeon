import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer


class HelloWorldHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            body = json.dumps({"message": "Hello, World"}).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404, "Not Found")

    # Silence default logging to stdout
    def log_message(self, format, *args):  # noqa: A003 - match signature
        return


def run():
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "8000"))
    server = HTTPServer((host, port), HelloWorldHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()


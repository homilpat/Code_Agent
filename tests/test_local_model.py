import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.patch.local_model import MAX_RESPONSE, LocalModelClient


def test_local_model_uses_bounded_loopback_http_without_following_redirects(monkeypatch):
    observed = {}

    class Response:
        status = 200

        def read(self, limit):
            assert limit == MAX_RESPONSE + 1
            return json.dumps({"choices": [{"message": {"content": '{"operations":[]}'}}]}).encode()

    class Connection:
        def __init__(self, host, port, timeout):
            observed.update(host=host, port=port, timeout=timeout)

        def request(self, method, path, body, headers):
            observed.update(method=method, path=path, payload=json.loads(body))

        def getresponse(self):
            return Response()

        def close(self):
            observed["closed"] = True

    monkeypatch.setattr("kh_agent.patch.local_model.http.client.HTTPConnection", Connection)
    answer = LocalModelClient("local/model", port=1234, timeout=15).generate(
        "Fix return value", "app.py", b"def app():\n    return 1\n"
    )
    assert answer == b'{"operations":[]}'
    assert (observed["host"], observed["port"], observed["path"]) == (
        "127.0.0.1",
        1234,
        "/v1/chat/completions",
    )
    assert observed["closed"]
    assert observed["payload"]["stream"] is False


def test_local_model_rejects_oversized_response_and_invalid_configuration(monkeypatch):
    class Response:
        status = 200

        def read(self, limit):
            return b"x" * limit

    class Connection:
        def __init__(self, host, port, timeout):
            pass

        def request(self, method, path, body, headers):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr("kh_agent.patch.local_model.http.client.HTTPConnection", Connection)
    with pytest.raises(DomainError) as large:
        LocalModelClient("local-model").generate("fix", "app.py", b"return 1\n")
    assert large.value.code == ErrorCode.INVALID_INPUT
    with pytest.raises(DomainError):
        LocalModelClient("model with spaces")


def test_local_model_speaks_to_a_real_loopback_http_server():
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            body = self.rfile.read(int(self.headers["Content-Length"]))
            seen["request"] = json.loads(body)
            response = json.dumps(
                {"choices": [{"message": {"content": '{"operations":[]}'}}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        answer = LocalModelClient("local", server.server_port, 5).generate(
            "fix", "app.py", b"VALUE = 1\n"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert answer == b'{"operations":[]}'
    assert seen["path"] == "/v1/chat/completions"
    assert seen["request"]["messages"][1]["content"].endswith("VALUE = 1\n")

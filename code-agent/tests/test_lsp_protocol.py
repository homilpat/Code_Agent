import io
import os
import threading

import pytest

from kh_agent.core.errors import DomainError
from kh_agent.sandbox.lsp import (
    WORKSPACE_READY,
    BoundedReader,
    LspSession,
    encode_message,
    parse_locations,
    read_message,
)

LIMIT = 1024 * 1024


def frame(data: bytes, max_body: int = LIMIT):
    return read_message(BoundedReader(io.BytesIO(data), LIMIT), max_body)


def pipes():
    """Client (stdin, stdout) and server (reader, writer) ends of two OS pipes."""
    server_in, client_out = os.pipe()
    client_in, server_out = os.pipe()
    client = (os.fdopen(client_out, "wb"), os.fdopen(client_in, "rb"))
    server = (BoundedReader(os.fdopen(server_in, "rb"), LIMIT), os.fdopen(server_out, "wb"))
    return client, server


def send(stream, *payloads):
    for payload in payloads:
        stream.write(encode_message(payload))
    stream.flush()


def serve(target):
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


def test_frames_round_trip_and_end_of_stream_is_clean():
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"text": "한글"}}
    assert frame(encode_message(payload)) == payload
    assert frame(b"") is None


@pytest.mark.parametrize(
    "data",
    [
        b'Content-Type: x\r\n\r\n{"jsonrpc":"2.0"}',
        b'Content-Length: 17\r\nContent-Length: 17\r\n\r\n{"jsonrpc":"2.0"}',
        b"Content-Length: -1\r\n\r\n",
        b'Content-Length: 17\n\n{"jsonrpc":"2.0"}',
        b"Content-Length: 40\r\n\r\n{}",
        b"Content-Length: 2\r\n\r\n[]",
        b"Content-Length: 2\r\n\r\n{}",
        b"Content-Length: 3\r\n\r\n{x}",
        b"X" * 2000 + b"\r\n\r\n",
        b"A: b\r\n" * 20 + b"\r\n",
        b"Content-Length: 2\r\n",
    ],
)
def test_malformed_or_truncated_frames_fail_closed(data):
    with pytest.raises(DomainError):
        frame(data)


def test_message_and_session_byte_limits_fail_closed():
    message = encode_message({"jsonrpc": "2.0", "method": "x", "params": {"v": "y" * 200}})
    with pytest.raises(DomainError):
        frame(message, max_body=100)
    with pytest.raises(DomainError):
        read_message(BoundedReader(io.BytesIO(message), 64), LIMIT)


def test_only_fixed_server_requests_are_answered_and_responses_match_ids():
    (stdin, stdout), (reader, writer) = pipes()
    session = LspSession(stdin, stdout)
    replies = []

    def server():
        request = read_message(reader, LIMIT)
        send(
            writer,
            {
                "jsonrpc": "2.0",
                "id": "s1",
                "method": "workspace/configuration",
                "params": {"items": [{"section": "python"}, {"section": "python.analysis"}]},
            },
            {"jsonrpc": "2.0", "id": "s2", "method": "workspace/applyEdit", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/publishDiagnostics",
                "params": {"uri": "file:///workspace/src/a.py", "diagnostics": []},
            },
        )
        replies.extend([read_message(reader, LIMIT), read_message(reader, LIMIT)])
        send(writer, {"jsonrpc": "2.0", "id": request["id"], "result": {"ok": True}})

    thread = serve(server)
    assert session.request("test/method", {}, 5) == {"ok": True}
    thread.join(5)
    by_id = {reply["id"]: reply for reply in replies}
    assert by_id["s1"]["result"] == [None, None]
    assert by_id["s2"]["error"]["code"] == -32601 and "result" not in by_id["s2"]
    assert session.wait_for_diagnostics("file:///workspace/src/a.py", 5) == []


def test_timeout_cancels_and_server_error_text_is_never_surfaced():
    (stdin, stdout), (reader, writer) = pipes()
    session = LspSession(stdin, stdout)
    seen = []

    def server():
        seen.append(read_message(reader, LIMIT))
        seen.append(read_message(reader, LIMIT))
        request = read_message(reader, LIMIT)
        error = {"code": -32603, "message": "SECRET_SOURCE_TEXT"}
        send(writer, {"jsonrpc": "2.0", "id": request["id"], "error": error})

    thread = serve(server)
    with pytest.raises(DomainError, match="timed out"):
        session.request("slow", {}, 0.2)
    with pytest.raises(DomainError) as rejected:
        session.request("bad", {}, 5)
    thread.join(5)
    assert seen[1] == {"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": 1}}
    assert "SECRET" not in rejected.value.message and "-32603" in rejected.value.message


def test_server_exit_fails_pending_requests_and_stops_the_server():
    (stdin, stdout), (reader, writer) = pipes()
    stopped = threading.Event()
    session = LspSession(stdin, stdout, on_failure=stopped.set)

    def server():
        read_message(reader, LIMIT)
        writer.close()

    serve(server)
    with pytest.raises(DomainError):
        session.request("x", {}, 5)
    assert stopped.is_set() and session.failure
    with pytest.raises(DomainError):
        session.notify("y", {})


def test_output_budget_stops_the_server():
    (stdin, stdout), (_, writer) = pipes()
    stopped = threading.Event()
    session = LspSession(stdin, stdout, max_total_bytes=256, on_failure=stopped.set)
    send(writer, {"jsonrpc": "2.0", "method": "window/logMessage", "params": {"m": "x" * 1000}})
    assert stopped.wait(5)
    assert session.failure == "Language server output budget exceeded"


def test_readiness_waits_for_the_workspace_log_and_fails_closed_without_it():
    (stdin, stdout), (_, writer) = pipes()
    session = LspSession(stdin, stdout)
    with pytest.raises(DomainError, match="readiness"):
        session.wait_for_log(WORKSPACE_READY, 0.2)
    for text in ("Loading configuration", "Found 3 source files"):
        send(writer, {"jsonrpc": "2.0", "method": "window/logMessage", "params": {"message": text}})
    assert session.wait_for_log(WORKSPACE_READY, 5) == "Found 3 source files"
    assert WORKSPACE_READY.search("No source files found.")
    assert not WORKSPACE_READY.search("Searching for source files")


def test_locations_outside_the_source_view_never_become_repository_paths():
    span = {"start": {"line": 1, "character": 2}, "end": {"line": 1, "character": 5}}
    result = [
        {"uri": "file:///workspace/src/pkg/core.py", "range": span},
        {"uri": "file:///usr/local/lib/node_modules/pyright/typeshed/os.pyi", "range": span},
        {"uri": "file:///workspace/src/../../etc/passwd", "range": span},
        {"uri": "file:///workspace/src/pkg/%2e%2e/%2e%2e/x.py", "range": span},
        {"uri": "file:///workspace/src/.git/config", "range": span},
        {"uri": "file:///workspace/srcx/a.py", "range": span},
        {"targetUri": "file:///workspace/src/pkg/main.py", "targetSelectionRange": span},
        {"uri": "file:///workspace/src/pkg/bad.py", "range": {"start": {"line": -1}}},
        "junk",
    ]
    locations = parse_locations(result)
    assert [item.path for item in locations] == [
        "pkg/core.py",
        None,
        None,
        None,
        None,
        None,
        "pkg/main.py",
    ]
    assert (locations[0].start_line, locations[0].end_character) == (1, 5)
    assert parse_locations(None) == ()

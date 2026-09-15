"""Minimal Language Server Protocol client for sandboxed semantic evidence (L1).

The principles follow Serena's solidlsp: Content-Length framing, id-keyed pending requests, a
reader thread that also answers server requests, and an ordered shutdown. They are rebuilt for
an untrusted server. Every frame and the whole session are byte-bounded, only a fixed set of
server requests is answered, server error text is never surfaced, and a location outside the
source view is never reported as a repository path. The server process runs only inside the
M06 sandbox (M02-LNG-011); this module never starts a process itself.
"""

import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import IO
from urllib.parse import quote, unquote

from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.patch.canonical import target_path

WORKSPACE_URI = "file:///workspace/src"
MAX_HEADER_LINE_BYTES = 1024
MAX_HEADER_LINES = 8
MAX_RESULTS = 10_000
MAX_DIAGNOSTIC_MESSAGE = 500
MAX_LOG_MESSAGES = 1000
MAX_LOG_TEXT = 300
METHOD_NOT_FOUND = -32601
# Pyright logs this once workspace enumeration ends. Earlier reference queries silently miss
# unopened files, so a client never queries before it (Serena waits for the same message).
WORKSPACE_READY = re.compile(r"^(Found \d+ source files?|No source files found)")
# Server requests answered with an empty result; every other server request is refused.
EMPTY_RESULT_REQUESTS = frozenset(
    {"client/registerCapability", "client/unregisterCapability", "window/workDoneProgress/create"}
)


def unavailable(message: str) -> DomainError:
    return DomainError(ErrorCode.CAPABILITY_NOT_AVAILABLE, message)


def encode_message(payload: dict) -> bytes:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


class BoundedReader:
    """Counts every byte read from the server and fails once the session budget is spent."""

    def __init__(self, stream: IO[bytes], budget: int) -> None:
        self.stream = stream
        self.remaining = budget

    def _take(self, data: bytes) -> bytes:
        self.remaining -= len(data)
        if self.remaining < 0:
            raise unavailable("Language server output budget exceeded")
        return data

    def readline(self, limit: int) -> bytes:
        return self._take(self.stream.readline(limit))

    def read_exactly(self, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = self._take(self.stream.read(size - len(chunks)))
            if not chunk:
                raise unavailable("Language server message truncated")
            chunks.extend(chunk)
        return bytes(chunks)


def read_message(reader: BoundedReader, max_body: int) -> dict | None:
    """Read one frame; None only at a clean end of stream before any header byte."""
    length = None
    for count in range(MAX_HEADER_LINES + 1):
        line = reader.readline(MAX_HEADER_LINE_BYTES + 1)
        if not line:
            if count == 0:
                return None
            raise unavailable("Language server header truncated")
        if len(line) > MAX_HEADER_LINE_BYTES or not line.endswith(b"\r\n"):
            raise unavailable("Malformed language server header")
        if line == b"\r\n":
            break
        name, separator, value = line[:-2].partition(b":")
        if not separator:
            raise unavailable("Malformed language server header")
        if name.strip().lower() == b"content-length":
            value = value.strip()
            if length is not None or not value.isdigit():
                raise unavailable("Invalid Content-Length")
            length = int(value)
    else:
        raise unavailable("Too many language server header lines")
    if length is None:
        raise unavailable("Missing Content-Length")
    if length > max_body:
        raise unavailable("Language server message exceeds limit")
    try:
        payload = json.loads(reader.read_exactly(length))
    except (ValueError, UnicodeDecodeError) as exc:
        raise unavailable("Language server sent invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        raise unavailable("Language server sent a non JSON-RPC message")
    return payload


@dataclass
class PendingRequest:
    done: threading.Event = field(default_factory=threading.Event)
    result: object = None
    error: str | None = None


class LspSession:
    """JSON-RPC over the server's stdio. `on_failure` must stop the server (container kill)."""

    def __init__(
        self,
        stdin: IO[bytes],
        stdout: IO[bytes],
        *,
        max_message_bytes: int = 8 * 1024 * 1024,
        max_total_bytes: int = 256 * 1024 * 1024,
        on_failure: Callable[[], object] | None = None,
    ) -> None:
        self._stdin = stdin
        self._max_message_bytes = max_message_bytes
        self._on_failure = on_failure
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._pending: dict[int, PendingRequest] = {}
        self._next_id = 1
        self._closing = False
        self.failure: str | None = None
        self.diagnostics: dict[str, list] = {}
        self.log_messages: list[str] = []
        self._diagnostics_changed = threading.Condition()
        self._reader = threading.Thread(
            target=self._read_loop, args=(BoundedReader(stdout, max_total_bytes),), daemon=True
        )
        self._reader.start()

    def _read_loop(self, reader: BoundedReader) -> None:
        try:
            while (message := read_message(reader, self._max_message_bytes)) is not None:
                self._dispatch(message)
            self._fail("Language server closed its output")
        except DomainError as exc:
            self._fail(exc.message)
        except (OSError, ValueError):
            self._fail("Language server stream failed")

    def _fail(self, reason: str) -> None:
        with self._lock:
            if self.failure is not None:
                return
            self.failure = reason
            pending, self._pending = self._pending, {}
        for waiter in pending.values():
            waiter.error = reason
            waiter.done.set()
        with self._diagnostics_changed:
            self._diagnostics_changed.notify_all()
        if self._on_failure is not None and not self._closing:
            self._on_failure()

    def _send(self, payload: dict) -> None:
        data = encode_message(payload)
        with self._write_lock:
            try:
                self._stdin.write(data)
                self._stdin.flush()
            except (OSError, ValueError) as exc:
                self._fail("Language server input closed")
                raise unavailable("Language server input closed") from exc

    def _dispatch(self, message: dict) -> None:
        method = message.get("method")
        params = message.get("params")
        if isinstance(method, str) and "id" in message:
            reply: dict = {"jsonrpc": "2.0", "id": message["id"]}
            if method in EMPTY_RESULT_REQUESTS:
                reply["result"] = None
            elif method == "workspace/configuration":
                items = params.get("items") if isinstance(params, dict) else None
                # Default settings for every section; repository-controlled config is absent.
                reply["result"] = [None] * min(len(items) if isinstance(items, list) else 0, 64)
            else:
                reply["error"] = {"code": METHOD_NOT_FOUND, "message": "Unsupported request"}
            self._send(reply)
        elif isinstance(method, str):
            if method == "textDocument/publishDiagnostics" and isinstance(params, dict):
                uri, items = params.get("uri"), params.get("diagnostics")
                if isinstance(uri, str) and isinstance(items, list):
                    with self._diagnostics_changed:
                        self.diagnostics[uri] = items[:MAX_RESULTS]
                        self._diagnostics_changed.notify_all()
            elif method == "window/logMessage" and isinstance(params, dict):
                text = params.get("message")
                if isinstance(text, str):
                    with self._diagnostics_changed:
                        if len(self.log_messages) < MAX_LOG_MESSAGES:
                            self.log_messages.append(text[:MAX_LOG_TEXT])
                        self._diagnostics_changed.notify_all()
        elif type(message.get("id")) is int:
            with self._lock:
                waiter = self._pending.pop(message["id"], None)
            if waiter is None:
                return
            error = message.get("error")
            if isinstance(error, dict):
                code = error.get("code")
                waiter.error = f"Language server rejected the request (code {code})"
            else:
                waiter.result = message.get("result")
            waiter.done.set()

    def notify(self, method: str, params: dict | None) -> None:
        if self.failure is not None:
            raise unavailable(self.failure)
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict | None, timeout: float) -> object:
        with self._lock:
            if self.failure is not None:
                raise unavailable(self.failure)
            request_id = self._next_id
            self._next_id += 1
            waiter = self._pending[request_id] = PendingRequest()
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        if not waiter.done.wait(timeout):
            with self._lock:
                self._pending.pop(request_id, None)
            if self.failure is None:
                self._send(
                    {"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": request_id}}
                )
            raise unavailable(f"Language server request timed out: {method}")
        if waiter.error is not None:
            raise unavailable(waiter.error)
        return waiter.result

    def forget_diagnostics(self, uri: str) -> None:
        with self._diagnostics_changed:
            self.diagnostics.pop(uri, None)

    def wait_for_diagnostics(self, uri: str, timeout: float) -> list:
        with self._diagnostics_changed:
            ready = self._diagnostics_changed.wait_for(
                lambda: uri in self.diagnostics or self.failure is not None, timeout
            )
            if self.failure is not None:
                raise unavailable(self.failure)
            if not ready:
                raise unavailable("Language server did not publish diagnostics")
            return self.diagnostics[uri]

    def wait_for_log(self, pattern: re.Pattern, timeout: float) -> str:
        """First recorded log message matching `pattern`; fails closed on timeout."""

        def matched() -> str | None:
            return next((text for text in self.log_messages if pattern.search(text)), None)

        with self._diagnostics_changed:
            self._diagnostics_changed.wait_for(
                lambda: matched() is not None or self.failure is not None, timeout
            )
            if self.failure is not None:
                raise unavailable(self.failure)
            found = matched()
            if found is None:
                raise unavailable("Language server did not report readiness")
            return found

    def close(self, timeout: float = 5) -> None:
        """Ordered shutdown; the sandbox removes the server regardless of the outcome."""
        self._closing = True
        try:
            if self.failure is None:
                self.request("shutdown", None, timeout)
                self.notify("exit", None)
        except DomainError:
            pass


def document_uri(path: str) -> str:
    target_path(path)
    parts = path.split("/")
    if not path or path.startswith("/") or any(part in ("", ".", "..") for part in parts):
        raise DomainError(ErrorCode.INVALID_INPUT, "Unsupported document path")
    return WORKSPACE_URI + "/" + quote(path)


def repository_path(uri: object) -> str | None:
    """Repository-relative path for a URI inside the source view, otherwise None."""
    prefix = WORKSPACE_URI + "/"
    if not isinstance(uri, str) or not uri.startswith(prefix):
        return None
    path = unquote(uri[len(prefix) :])
    try:
        document_uri(path)
    except (DomainError, UnicodeError):
        return None
    return path


@dataclass(frozen=True)
class Location:
    path: str | None  # None: outside the source view (bundled stubs, other roots)
    start_line: int
    start_character: int
    end_line: int
    end_character: int


@dataclass(frozen=True)
class Diagnostic:
    path: str
    line: int
    character: int
    severity: int | None
    code: str | None
    message: str


def _position(value: object) -> tuple[int, int] | None:
    if not isinstance(value, dict):
        return None
    line, character = value.get("line"), value.get("character")
    if type(line) is not int or type(character) is not int or line < 0 or character < 0:
        return None
    return line, character


def _range(value: object) -> tuple[int, int, int, int] | None:
    if not isinstance(value, dict):
        return None
    start, end = _position(value.get("start")), _position(value.get("end"))
    return (*start, *end) if start and end else None


def parse_locations(result: object) -> tuple[Location, ...]:
    """Location | Location[] | LocationLink[] | null; malformed entries are dropped."""
    items = result if isinstance(result, list) else [] if result is None else [result]
    locations = []
    for item in items[:MAX_RESULTS]:
        if not isinstance(item, dict):
            continue
        if "targetUri" in item:
            uri, span = item["targetUri"], _range(item.get("targetSelectionRange"))
        else:
            uri, span = item.get("uri"), _range(item.get("range"))
        if isinstance(uri, str) and span is not None:
            locations.append(Location(repository_path(uri), *span))
    return tuple(locations)


class PythonLanguageClient:
    """Definition, reference and diagnostic queries against a sandboxed Python server."""

    def __init__(self, session: LspSession, request_timeout: float = 60) -> None:
        self.session = session
        self.timeout = request_timeout
        self.session.request(
            "initialize",
            {
                "processId": None,
                "rootUri": WORKSPACE_URI,
                "workspaceFolders": [{"uri": WORKSPACE_URI, "name": "workspace"}],
                "capabilities": {
                    "textDocument": {
                        "synchronization": {"didSave": False},
                        "definition": {"linkSupport": True},
                        "references": {},
                        "publishDiagnostics": {"versionSupport": True},
                    },
                    "workspace": {"configuration": True, "workspaceFolders": True},
                },
            },
            request_timeout,
        )
        self.session.notify("initialized", {})
        self.workspace_status = self.session.wait_for_log(WORKSPACE_READY, request_timeout)

    def open(self, path: str, text: str) -> None:
        uri = document_uri(path)
        self.session.forget_diagnostics(uri)
        self.session.notify(
            "textDocument/didOpen",
            {"textDocument": {"uri": uri, "languageId": "python", "version": 1, "text": text}},
        )

    def _position_params(self, path: str, line: int, character: int) -> dict:
        if type(line) is not int or type(character) is not int or line < 0 or character < 0:
            raise DomainError(ErrorCode.INVALID_INPUT, "Invalid document position")
        return {
            "textDocument": {"uri": document_uri(path)},
            "position": {"line": line, "character": character},
        }

    def definition(self, path: str, line: int, character: int) -> tuple[Location, ...]:
        params = self._position_params(path, line, character)
        return parse_locations(
            self.session.request("textDocument/definition", params, self.timeout)
        )

    def references(
        self, path: str, line: int, character: int, include_declaration: bool = True
    ) -> tuple[Location, ...]:
        params = self._position_params(path, line, character)
        params["context"] = {"includeDeclaration": include_declaration}
        return parse_locations(
            self.session.request("textDocument/references", params, self.timeout)
        )

    def diagnostics(self, path: str) -> tuple[Diagnostic, ...]:
        """Diagnostics for a document opened with `open`."""
        items = self.session.wait_for_diagnostics(document_uri(path), self.timeout)
        result = []
        for item in items:
            start = _range(item.get("range")) if isinstance(item, dict) else None
            if start is None:
                continue
            severity, code, message = item.get("severity"), item.get("code"), item.get("message")
            result.append(
                Diagnostic(
                    path,
                    start[0],
                    start[1],
                    severity if type(severity) is int else None,
                    str(code)[:100] if isinstance(code, (str, int)) else None,
                    message[:MAX_DIAGNOSTIC_MESSAGE] if isinstance(message, str) else "",
                )
            )
        return tuple(result)

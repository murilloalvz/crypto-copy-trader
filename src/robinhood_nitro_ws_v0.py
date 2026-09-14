"""Minimal stdlib WebSocket transport for the Robinhood/Nitro sequencer feed.

The transport intentionally does not negotiate permessage-deflate. Nitro emits
JSON as WebSocket text frames when compression is not negotiated. This module
only handles transport and clocks; it does not claim EVM execution or economic
outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import os
import socket
import ssl
import time
from urllib.parse import urlsplit


WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
FEED_CLIENT_VERSION = 2
FEED_SERVER_VERSION = 2
ROBINHOOD_CHAIN_ID = 4663
DEFAULT_FEED_URL = "wss://feed.mainnet.chain.robinhood.com"

HEADER_CLIENT_VERSION = "arbitrum-feed-client-version"
HEADER_REQUESTED_SEQUENCE = "arbitrum-requested-sequence-number"
HEADER_SERVER_VERSION = "arbitrum-feed-server-version"
HEADER_CHAIN_ID = "arbitrum-chain-id"

OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


@dataclass(frozen=True)
class NitroHandshakeV0:
    feed_url: str
    host: str
    path: str
    requested_sequence_number: int
    feed_client_version: int
    feed_server_version: int
    chain_id: int


@dataclass(frozen=True)
class ServerFrameV0:
    fin: bool
    opcode: int
    payload: bytes


class WebSocketProtocolError(RuntimeError):
    pass


def _feed_target(feed_url: str) -> tuple[str, int, str]:
    parsed = urlsplit(feed_url)
    if parsed.scheme != "wss":
        raise ValueError("Nitro feed URL must use wss://")
    if not parsed.hostname:
        raise ValueError("Nitro feed URL has no hostname")
    port = parsed.port or 443
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return parsed.hostname, port, path


def make_websocket_key_v0(random_bytes: bytes | None = None) -> str:
    raw = os.urandom(16) if random_bytes is None else bytes(random_bytes)
    if len(raw) != 16:
        raise ValueError("WebSocket key entropy must be exactly 16 bytes")
    return base64.b64encode(raw).decode("ascii")


def build_handshake_request_v0(
    feed_url: str,
    *,
    requested_sequence_number: int,
    websocket_key: str,
) -> bytes:
    if requested_sequence_number < 0:
        raise ValueError("requested_sequence_number must be non-negative")
    host, port, path = _feed_target(feed_url)
    host_header = host if port == 443 else f"{host}:{port}"
    lines = [
        f"GET {path} HTTP/1.1",
        f"Host: {host_header}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Key: {websocket_key}",
        "Sec-WebSocket-Version: 13",
        f"Arbitrum-Feed-Client-Version: {FEED_CLIENT_VERSION}",
        f"Arbitrum-Requested-Sequence-Number: {requested_sequence_number}",
        "",
        "",
    ]
    return "\r\n".join(lines).encode("ascii")


def _parse_http_headers(raw: bytes) -> tuple[int, dict[str, str]]:
    try:
        text = raw.decode("iso-8859-1")
    except UnicodeDecodeError as exc:
        raise WebSocketProtocolError("invalid HTTP upgrade bytes") from exc
    lines = text.split("\r\n")
    if not lines or not lines[0].startswith("HTTP/"):
        raise WebSocketProtocolError("missing HTTP status line")
    parts = lines[0].split(" ", 2)
    if len(parts) < 2:
        raise WebSocketProtocolError("malformed HTTP status line")
    try:
        status = int(parts[1])
    except ValueError as exc:
        raise WebSocketProtocolError("malformed HTTP status code") from exc
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        if ":" not in line:
            raise WebSocketProtocolError("malformed HTTP header")
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    return status, headers


def validate_handshake_response_v0(
    raw_headers: bytes,
    *,
    websocket_key: str,
    feed_url: str,
    requested_sequence_number: int,
    expected_chain_id: int = ROBINHOOD_CHAIN_ID,
) -> NitroHandshakeV0:
    status, headers = _parse_http_headers(raw_headers)
    if status != 101:
        raise WebSocketProtocolError(f"WebSocket upgrade rejected with HTTP {status}")
    if headers.get("upgrade", "").lower() != "websocket":
        raise WebSocketProtocolError("upgrade response is not websocket")
    connection_tokens = {
        token.strip().lower() for token in headers.get("connection", "").split(",")
    }
    if "upgrade" not in connection_tokens:
        raise WebSocketProtocolError("upgrade response missing Connection: Upgrade")
    expected_accept = base64.b64encode(
        hashlib.sha1((websocket_key + WS_GUID).encode("ascii")).digest()
    ).decode("ascii")
    if headers.get("sec-websocket-accept") != expected_accept:
        raise WebSocketProtocolError("Sec-WebSocket-Accept mismatch")
    if "sec-websocket-extensions" in headers:
        raise WebSocketProtocolError("unexpected WebSocket extension negotiation")
    try:
        server_version = int(headers[HEADER_SERVER_VERSION], 0)
        chain_id = int(headers[HEADER_CHAIN_ID], 0)
    except KeyError as exc:
        raise WebSocketProtocolError(f"missing Nitro handshake header: {exc.args[0]}") from exc
    except ValueError as exc:
        raise WebSocketProtocolError("malformed Nitro handshake integer header") from exc
    if server_version != FEED_SERVER_VERSION:
        raise WebSocketProtocolError(
            f"unexpected feed server version: {server_version}"
        )
    if chain_id != expected_chain_id:
        raise WebSocketProtocolError(f"unexpected feed chain id: {chain_id}")
    host, _, path = _feed_target(feed_url)
    return NitroHandshakeV0(
        feed_url=feed_url,
        host=host,
        path=path,
        requested_sequence_number=requested_sequence_number,
        feed_client_version=FEED_CLIENT_VERSION,
        feed_server_version=server_version,
        chain_id=chain_id,
    )


def decode_server_frames_v0(buffer: bytes) -> tuple[tuple[ServerFrameV0, ...], bytes]:
    frames: list[ServerFrameV0] = []
    cursor = 0
    while cursor < len(buffer):
        frame, consumed = _decode_first_server_frame_v0(buffer[cursor:])
        if frame is None:
            break
        frames.append(frame)
        cursor += consumed
    return tuple(frames), buffer[cursor:]


def encode_client_control_frame_v0(
    opcode: int,
    payload: bytes = b"",
    *,
    mask_key: bytes | None = None,
) -> bytes:
    if opcode not in {OP_CLOSE, OP_PING, OP_PONG}:
        raise ValueError("client control frame opcode must be close/ping/pong")
    payload = bytes(payload)
    if len(payload) > 125:
        raise ValueError("control frame payload exceeds 125 bytes")
    key = os.urandom(4) if mask_key is None else bytes(mask_key)
    if len(key) != 4:
        raise ValueError("mask_key must be 4 bytes")
    masked_payload = bytes(value ^ key[index % 4] for index, value in enumerate(payload))
    return bytes([0x80 | opcode, 0x80 | len(payload)]) + key + masked_payload


class NitroSequencerFeedClientV0:
    """Blocking read-only Nitro feed client with no compression negotiation."""

    def __init__(
        self,
        feed_url: str = DEFAULT_FEED_URL,
        *,
        requested_sequence_number: int = 0,
        expected_chain_id: int = ROBINHOOD_CHAIN_ID,
        timeout_seconds: float = 10.0,
    ):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.feed_url = feed_url
        self.requested_sequence_number = requested_sequence_number
        self.expected_chain_id = expected_chain_id
        self.timeout_seconds = float(timeout_seconds)
        self.sock: socket.socket | ssl.SSLSocket | None = None
        self.handshake: NitroHandshakeV0 | None = None
        self._buffer = b""
        self._fragment_opcode: int | None = None
        self._fragment_payload = bytearray()

    def connect(self) -> NitroHandshakeV0:
        if self.sock is not None:
            raise RuntimeError("feed client already connected")
        host, port, _ = _feed_target(self.feed_url)
        raw_sock = socket.create_connection((host, port), timeout=self.timeout_seconds)
        context = ssl.create_default_context()
        wrapped = context.wrap_socket(raw_sock, server_hostname=host)
        wrapped.settimeout(self.timeout_seconds)
        websocket_key = make_websocket_key_v0()
        request = build_handshake_request_v0(
            self.feed_url,
            requested_sequence_number=self.requested_sequence_number,
            websocket_key=websocket_key,
        )
        wrapped.sendall(request)
        response = bytearray()
        while b"\r\n\r\n" not in response:
            chunk = wrapped.recv(4096)
            if not chunk:
                wrapped.close()
                raise WebSocketProtocolError("EOF during WebSocket upgrade")
            response.extend(chunk)
            if len(response) > 64 * 1024:
                wrapped.close()
                raise WebSocketProtocolError("oversized WebSocket upgrade response")
        split = response.index(b"\r\n\r\n") + 4
        raw_headers = bytes(response[:split])
        self._buffer = bytes(response[split:])
        try:
            handshake = validate_handshake_response_v0(
                raw_headers,
                websocket_key=websocket_key,
                feed_url=self.feed_url,
                requested_sequence_number=self.requested_sequence_number,
                expected_chain_id=self.expected_chain_id,
            )
        except Exception:
            wrapped.close()
            raise
        self.sock = wrapped
        self.handshake = handshake
        return handshake

    def close(self) -> None:
        sock = self.sock
        self.sock = None
        if sock is None:
            return
        try:
            sock.sendall(encode_client_control_frame_v0(OP_CLOSE))
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def _next_frame(self) -> ServerFrameV0:
        if self.sock is None:
            raise RuntimeError("feed client is not connected")
        while True:
            frame, consumed = _decode_first_server_frame_v0(self._buffer)
            if frame is not None:
                self._buffer = self._buffer[consumed:]
                return frame
            chunk = self.sock.recv(64 * 1024)
            if not chunk:
                raise EOFError("sequencer feed closed")
            self._buffer += chunk

    def read_text(self) -> tuple[str, int]:
        """Return one complete text message and its local receive-complete clock."""
        while True:
            frame = self._next_frame()
            observed_at_ns = time.time_ns()
            if frame.opcode == OP_PING:
                if self.sock is None:
                    raise RuntimeError("feed client disconnected during ping")
                self.sock.sendall(encode_client_control_frame_v0(OP_PONG, frame.payload))
                continue
            if frame.opcode == OP_PONG:
                continue
            if frame.opcode == OP_CLOSE:
                raise EOFError("sequencer feed sent close frame")
            if frame.opcode == OP_BINARY:
                raise WebSocketProtocolError("Nitro feed sent unexpected binary frame")
            if frame.opcode == OP_TEXT:
                if self._fragment_opcode is not None:
                    raise WebSocketProtocolError("new text frame during fragmented message")
                if frame.fin:
                    return frame.payload.decode("utf-8"), observed_at_ns
                self._fragment_opcode = OP_TEXT
                self._fragment_payload = bytearray(frame.payload)
                continue
            if frame.opcode == OP_CONTINUATION:
                if self._fragment_opcode != OP_TEXT:
                    raise WebSocketProtocolError("unexpected continuation frame")
                self._fragment_payload.extend(frame.payload)
                if frame.fin:
                    payload = bytes(self._fragment_payload)
                    self._fragment_opcode = None
                    self._fragment_payload.clear()
                    return payload.decode("utf-8"), observed_at_ns
                continue
            raise WebSocketProtocolError(f"unsupported WebSocket opcode: {frame.opcode}")


def _decode_first_server_frame_v0(buffer: bytes) -> tuple[ServerFrameV0 | None, int]:
    if len(buffer) < 2:
        return None, 0
    first = buffer[0]
    second = buffer[1]
    fin = bool(first & 0x80)
    rsv = first & 0x70
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if rsv:
        raise WebSocketProtocolError("unexpected RSV bits without negotiated extension")
    if masked:
        raise WebSocketProtocolError("server-to-client WebSocket frame must not be masked")
    header_len = 2
    if length == 126:
        if len(buffer) < 4:
            return None, 0
        length = int.from_bytes(buffer[2:4], "big")
        header_len = 4
    elif length == 127:
        if len(buffer) < 10:
            return None, 0
        length = int.from_bytes(buffer[2:10], "big")
        if length >> 63:
            raise WebSocketProtocolError("invalid 64-bit WebSocket payload length")
        header_len = 10
    end = header_len + length
    if len(buffer) < end:
        return None, 0
    if opcode >= 0x8:
        if not fin:
            raise WebSocketProtocolError("fragmented control frame")
        if length > 125:
            raise WebSocketProtocolError("oversized control frame")
    return ServerFrameV0(fin=fin, opcode=opcode, payload=buffer[header_len:end]), end

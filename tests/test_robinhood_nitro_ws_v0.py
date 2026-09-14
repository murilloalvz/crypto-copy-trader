import base64
import hashlib
import unittest

from src.robinhood_nitro_ws_v0 import (
    DEFAULT_FEED_URL,
    FEED_CLIENT_VERSION,
    FEED_SERVER_VERSION,
    OP_PONG,
    OP_TEXT,
    ROBINHOOD_CHAIN_ID,
    WS_GUID,
    WebSocketProtocolError,
    build_handshake_request_v0,
    decode_server_frames_v0,
    encode_client_control_frame_v0,
    make_websocket_key_v0,
    validate_handshake_response_v0,
)


def _server_frame(payload, *, opcode=OP_TEXT, fin=True):
    payload = bytes(payload)
    first = (0x80 if fin else 0) | opcode
    if len(payload) < 126:
        return bytes([first, len(payload)]) + payload
    if len(payload) <= 0xFFFF:
        return bytes([first, 126]) + len(payload).to_bytes(2, "big") + payload
    return bytes([first, 127]) + len(payload).to_bytes(8, "big") + payload


class RobinhoodNitroWsV0Tests(unittest.TestCase):
    def test_handshake_request_uses_nitro_v2_headers_without_compression(self):
        key = make_websocket_key_v0(b"0" * 16)
        request = build_handshake_request_v0(
            DEFAULT_FEED_URL,
            requested_sequence_number=123,
            websocket_key=key,
        ).decode("ascii")
        self.assertIn(f"Arbitrum-Feed-Client-Version: {FEED_CLIENT_VERSION}\r\n", request)
        self.assertIn("Arbitrum-Requested-Sequence-Number: 123\r\n", request)
        self.assertNotIn("Sec-WebSocket-Extensions", request)
        self.assertIn("Host: feed.mainnet.chain.robinhood.com\r\n", request)

    def test_handshake_validates_accept_server_version_and_chain(self):
        key = make_websocket_key_v0(b"1" * 16)
        accept = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode("ascii")).digest()
        ).decode("ascii")
        raw = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            f"Arbitrum-Feed-Server-Version: {FEED_SERVER_VERSION}\r\n"
            f"Arbitrum-Chain-Id: {ROBINHOOD_CHAIN_ID}\r\n"
            "\r\n"
        ).encode("ascii")
        handshake = validate_handshake_response_v0(
            raw,
            websocket_key=key,
            feed_url=DEFAULT_FEED_URL,
            requested_sequence_number=123,
        )
        self.assertEqual(handshake.chain_id, ROBINHOOD_CHAIN_ID)
        self.assertEqual(handshake.feed_server_version, FEED_SERVER_VERSION)
        self.assertEqual(handshake.requested_sequence_number, 123)

    def test_handshake_rejects_wrong_chain_and_compression(self):
        key = make_websocket_key_v0(b"2" * 16)
        accept = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode("ascii")).digest()
        ).decode("ascii")
        wrong_chain = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            "Arbitrum-Feed-Server-Version: 2\r\n"
            "Arbitrum-Chain-Id: 1\r\n\r\n"
        ).encode("ascii")
        with self.assertRaisesRegex(WebSocketProtocolError, "chain id"):
            validate_handshake_response_v0(
                wrong_chain,
                websocket_key=key,
                feed_url=DEFAULT_FEED_URL,
                requested_sequence_number=0,
            )

        compressed = wrong_chain.replace(
            b"Arbitrum-Chain-Id: 1\r\n",
            b"Arbitrum-Chain-Id: 4663\r\nSec-WebSocket-Extensions: permessage-deflate\r\n",
        )
        with self.assertRaisesRegex(WebSocketProtocolError, "extension"):
            validate_handshake_response_v0(
                compressed,
                websocket_key=key,
                feed_url=DEFAULT_FEED_URL,
                requested_sequence_number=0,
            )

    def test_decoder_preserves_partial_and_coalesced_frames(self):
        first = _server_frame(b'{"version":1}')
        second = _server_frame(b'{"version":1,"messages":[]}')
        frames, remainder = decode_server_frames_v0(first + second[:-3])
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].payload, b'{"version":1}')
        self.assertEqual(remainder, second[:-3])

        frames2, remainder2 = decode_server_frames_v0(remainder + second[-3:])
        self.assertEqual(len(frames2), 1)
        self.assertEqual(frames2[0].payload, b'{"version":1,"messages":[]}')
        self.assertEqual(remainder2, b"")

    def test_decoder_handles_extended_payload_lengths(self):
        payload_126 = b"a" * 126
        payload_long = b"b" * 70_000
        frames, remainder = decode_server_frames_v0(
            _server_frame(payload_126) + _server_frame(payload_long)
        )
        self.assertEqual([len(row.payload) for row in frames], [126, 70_000])
        self.assertEqual(remainder, b"")

    def test_client_pong_frame_is_masked(self):
        frame = encode_client_control_frame_v0(
            OP_PONG,
            b"abc",
            mask_key=b"\x01\x02\x03\x04",
        )
        self.assertEqual(frame[0], 0x80 | OP_PONG)
        self.assertTrue(frame[1] & 0x80)
        self.assertEqual(frame[2:6], b"\x01\x02\x03\x04")
        self.assertEqual(frame[6:], bytes([ord("a") ^ 1, ord("b") ^ 2, ord("c") ^ 3]))

    def test_server_masked_frame_is_rejected(self):
        with self.assertRaisesRegex(WebSocketProtocolError, "must not be masked"):
            decode_server_frames_v0(bytes([0x81, 0x80]))


if __name__ == "__main__":
    unittest.main()

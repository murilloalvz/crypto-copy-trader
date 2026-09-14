import base64
import json
import unittest

from src.robinhood_nitro_feed_v0 import (
    INTENT_ONLY,
    L1_MESSAGE_TYPE_L2_MESSAGE,
    L2_MESSAGE_KIND_BATCH,
    L2_MESSAGE_KIND_SIGNED_TX,
    classify_pons_intent_v0,
    extract_signed_tx_intents_v0,
    parse_broadcast_message_v0,
    parse_feed_intents_v0,
)


def _int_bytes(value):
    if value == 0:
        return b""
    size = (value.bit_length() + 7) // 8
    return value.to_bytes(size, "big")


def _rlp(item):
    if isinstance(item, int):
        item = _int_bytes(item)
    if isinstance(item, bytes):
        if len(item) == 1 and item[0] <= 0x7F:
            return item
        if len(item) <= 55:
            return bytes([0x80 + len(item)]) + item
        length = _int_bytes(len(item))
        return bytes([0xB7 + len(length)]) + length + item
    if isinstance(item, list):
        payload = b"".join(_rlp(value) for value in item)
        if len(payload) <= 55:
            return bytes([0xC0 + len(payload)]) + payload
        length = _int_bytes(len(payload))
        return bytes([0xF7 + len(length)]) + length + payload
    raise TypeError(type(item))


def _legacy_tx(*, to, value=0, data=b""):
    return _rlp([
        1,       # nonce
        2,       # gasPrice
        50_000,  # gasLimit
        to,
        value,
        data,
        27,
        1,
        1,
    ])


def _type2_tx(*, to, value=0, data=b""):
    return b"\x02" + _rlp([
        4663,    # chainId
        1,       # nonce
        2,       # maxPriorityFeePerGas
        3,       # maxFeePerGas
        50_000,  # gasLimit
        to,
        value,
        data,
        [],      # accessList
        0,
        1,
        1,
    ])


def _feed_payload(l2_messages, *, kind=L1_MESSAGE_TYPE_L2_MESSAGE):
    rows = []
    for index, l2_message in enumerate(l2_messages, start=1):
        rows.append({
            "sequenceNumber": 100 + index,
            "message": {
                "message": {
                    "header": {
                        "kind": kind,
                        "sender": "0x" + "11" * 20,
                        "blockNumber": 123,
                        "timestamp": 456,
                        "requestId": "0x" + "22" * 32,
                        "baseFeeL1": 7,
                    },
                    "l2Msg": base64.b64encode(l2_message).decode(),
                },
                "delayedMessagesRead": 9,
            },
            "blockHash": "0x" + "33" * 32,
            "signatureV2": None,
            "blockMetadata": base64.b64encode(b"\x00\x02").decode(),
        })
    return json.dumps({"version": 1, "messages": rows})


class RobinhoodNitroFeedV0Tests(unittest.TestCase):
    def test_official_nitro_serialization_shape_decodes_base64_fields(self):
        raw = json.dumps({
            "version": 1,
            "messages": [{
                "sequenceNumber": 12345,
                "message": {
                    "message": {
                        "header": {
                            "kind": 0,
                            "sender": "0x0000000000000000000000000000000000000000",
                            "blockNumber": 0,
                            "timestamp": 0,
                            "requestId": "0x" + "00" * 32,
                            "baseFeeL1": 0,
                        },
                        "l2Msg": "3q2+7w==",
                    },
                    "delayedMessagesRead": 3333,
                },
                "blockHash": "0xff" + "00" * 31,
                "signatureV2": None,
                "blockMetadata": "AAI=",
            }],
        })
        messages = parse_broadcast_message_v0(raw, observed_at_ns=99)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].sequence_number, 12345)
        self.assertEqual(messages[0].l2_message_raw, bytes.fromhex("deadbeef"))
        self.assertEqual(messages[0].block_metadata_raw, b"\x00\x02")
        self.assertEqual(messages[0].observed_at_ns, 99)
        self.assertEqual(extract_signed_tx_intents_v0(messages[0]), ())

    def test_legacy_signed_tx_extracts_target_value_selector_and_intent_scope(self):
        target = bytes.fromhex("44" * 20)
        calldata = bytes.fromhex("aabbccdd") + b"payload"
        tx = _legacy_tx(to=target, value=123, data=calldata)
        raw = _feed_payload([bytes([L2_MESSAGE_KIND_SIGNED_TX]) + tx])
        result = parse_feed_intents_v0(raw, observed_at_ns=1_000)
        self.assertEqual(result["signed_tx_intent_count"], 1)
        intent = result["intents"][0]
        self.assertEqual(intent["tx_envelope_type"], "legacy")
        self.assertIsNone(intent["tx_type_byte"])
        self.assertEqual(intent["to"], "0x" + "44" * 20)
        self.assertEqual(intent["value_raw"], 123)
        self.assertEqual(intent["calldata_selector"], "0xaabbccdd")
        self.assertEqual(intent["evidence_scope"], INTENT_ONLY)
        self.assertFalse(intent["execution_confirmed"])
        self.assertFalse(result["economic_outcomes_opened"])

    def test_eip1559_signed_tx_is_supported(self):
        target = bytes.fromhex("55" * 20)
        tx = _type2_tx(to=target, value=456, data=bytes.fromhex("01020304"))
        raw = _feed_payload([bytes([L2_MESSAGE_KIND_SIGNED_TX]) + tx])
        messages = parse_broadcast_message_v0(raw, observed_at_ns=2_000)
        intents = extract_signed_tx_intents_v0(messages[0])
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].tx_envelope_type, "eip1559")
        self.assertEqual(intents[0].tx_type_byte, 2)
        self.assertEqual(intents[0].value_raw, 456)
        self.assertEqual(intents[0].to, "0x" + "55" * 20)

    def test_nested_batch_uses_big_endian_u64_lengths_and_preserves_batch_path(self):
        tx_a = bytes([L2_MESSAGE_KIND_SIGNED_TX]) + _legacy_tx(
            to=bytes.fromhex("66" * 20), data=bytes.fromhex("11111111")
        )
        tx_b = bytes([L2_MESSAGE_KIND_SIGNED_TX]) + _type2_tx(
            to=bytes.fromhex("77" * 20), data=bytes.fromhex("22222222")
        )
        nested = (
            len(tx_a).to_bytes(8, "big") + tx_a
            + len(tx_b).to_bytes(8, "big") + tx_b
        )
        l2_message = bytes([L2_MESSAGE_KIND_BATCH]) + nested
        raw = _feed_payload([l2_message])
        message = parse_broadcast_message_v0(raw, observed_at_ns=3_000)[0]
        intents = extract_signed_tx_intents_v0(message)
        self.assertEqual(len(intents), 2)
        self.assertEqual(intents[0].batch_path, (0,))
        self.assertEqual(intents[1].batch_path, (1,))
        self.assertEqual(intents[0].calldata_selector, "0x11111111")
        self.assertEqual(intents[1].calldata_selector, "0x22222222")

    def test_pons_classification_is_target_and_selector_based_but_intent_only(self):
        factory = "0x" + "88" * 20
        curve = "0x" + "99" * 20
        buy_selector = "0x12345678"
        sell_selector = "0x90abcdef"
        txs = [
            bytes([L2_MESSAGE_KIND_SIGNED_TX])
            + _legacy_tx(to=bytes.fromhex("88" * 20), data=bytes.fromhex("deadbeef")),
            bytes([L2_MESSAGE_KIND_SIGNED_TX])
            + _legacy_tx(to=bytes.fromhex("99" * 20), data=bytes.fromhex("12345678")),
            bytes([L2_MESSAGE_KIND_SIGNED_TX])
            + _legacy_tx(to=bytes.fromhex("99" * 20), data=bytes.fromhex("90abcdef")),
        ]
        message_rows = parse_broadcast_message_v0(_feed_payload(txs), observed_at_ns=4_000)
        intents = [extract_signed_tx_intents_v0(row)[0] for row in message_rows]
        classified = [
            classify_pons_intent_v0(
                intent,
                factory_address=factory,
                known_curve_addresses=(curve,),
                buy_selector=buy_selector,
                sell_selector=sell_selector,
            )
            for intent in intents
        ]
        self.assertEqual(
            [row.intent_kind for row in classified],
            ["PONS_FACTORY_TARGET_INTENT", "PONS_CURVE_BUY_INTENT", "PONS_CURVE_SELL_INTENT"],
        )
        self.assertTrue(all(row.evidence_scope == INTENT_ONLY for row in classified))
        self.assertTrue(all(not row.execution_confirmed for row in classified))

    def test_confirmed_sequence_number_only_frame_has_no_messages(self):
        raw = json.dumps({
            "version": 1,
            "confirmedSequenceNumberMessage": {"sequenceNumber": 123},
        })
        self.assertEqual(parse_broadcast_message_v0(raw, observed_at_ns=5_000), ())

    def test_unsupported_feed_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported Nitro feed version"):
            parse_broadcast_message_v0(
                json.dumps({"version": 2}),
                observed_at_ns=6_000,
            )


if __name__ == "__main__":
    unittest.main()

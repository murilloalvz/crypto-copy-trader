from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from benchmarks.burst_selection_diagnostic_v1.run import (
    PRICE_IMPACT_CLOSENESS,
    _canonical_history_ids,
    validate_history_dirs,
)


class BurstSelectionDiagnosticV1Tests(unittest.TestCase):
    def test_price_impact_closeness_contract_is_explicit(self):
        self.assertEqual(
            PRICE_IMPACT_CLOSENESS,
            "entry_price_impact_closeness_to_zero",
        )

    def test_canonical_history_ids_reads_frozen_protocol_shape(self):
        protocol = {
            "mature_history_contract": {
                "frozen_history_run_ids": ["a", "b", "c", "d"]
            }
        }
        self.assertEqual(
            _canonical_history_ids(protocol),
            ["a", "b", "c", "d"],
        )

    def test_history_dirs_require_exact_frozen_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            protocol = root / "protocol.json"
            ids = ["a", "b", "c", "d"]
            protocol.write_text(
                '{"mature_history_contract":{"frozen_history_run_ids":'
                '["a","b","c","d"]}}',
                encoding="utf-8",
            )
            dirs = []
            for name in ids:
                path = root / name
                path.mkdir()
                dirs.append(path)
            resolved, expected = validate_history_dirs(
                dirs,
                protocol_path=protocol,
            )
            self.assertEqual(expected, ids)
            self.assertEqual(
                [path.name for path in resolved],
                ids,
            )

            with self.assertRaisesRegex(
                ValueError,
                "exactly match frozen order",
            ):
                validate_history_dirs(
                    list(reversed(dirs)),
                    protocol_path=protocol,
                )


if __name__ == "__main__":
    unittest.main()

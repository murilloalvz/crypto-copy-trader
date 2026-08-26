import unittest

from radar import format_report
from src.wave_radar import build_wave_radar_report
from tests.test_wave_radar import token


class WaveRadarCLITests(unittest.TestCase):
    def test_report_is_explicitly_read_only_and_explainable(self):
        report = build_wave_radar_report([token()])

        output = format_report(report, top_n=10, now_ms=1_800_000_600_000)

        self.assertIn("Wave Radar", output)
        self.assertIn("Tokens analisados: 1", output)
        self.assertIn("Aptos para paper signal: 1", output)
        self.assertIn("APTA PARA PAPER SIGNAL", output)
        self.assertIn("Wave Score inicial:", output)
        self.assertIn("Motivos:", output)
        self.assertIn("READ ONLY", output)
        self.assertIn("não prevê valorização futura", output)


if __name__ == "__main__":
    unittest.main()

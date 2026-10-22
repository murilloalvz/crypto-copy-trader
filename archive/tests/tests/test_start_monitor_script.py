import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "start-monitor.ps1"


class StartMonitorScriptTests(unittest.TestCase):
    def test_is_ascii_safe_for_windows_powershell_51(self):
        raw = SCRIPT_PATH.read_bytes()
        self.assertTrue(all(byte < 128 for byte in raw))

    def test_captures_native_python_output_in_session_log(self):
        script = SCRIPT_PATH.read_text(encoding="ascii")
        self.assertNotIn("Start-Transcript", script)
        self.assertIn("2>&1 | ForEach-Object", script)
        self.assertIn("Add-Content -Path $LogPath -Value $Line", script)
        self.assertIn("Set-Content -Path $LogPath", script)


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class WindowsReleaseSourceTests(TestCase):
    def test_build_and_verifier_require_gui_and_cli_artifacts(self) -> None:
        build = (ROOT / "scripts" / "build_windows.ps1").read_text(
            encoding="utf-8-sig"
        )
        package = (
            ROOT / "scripts" / "package_windows_release.ps1"
        ).read_text(encoding="utf-8-sig")
        verify = (
            ROOT / "scripts" / "verify_windows_release.ps1"
        ).read_text(encoding="utf-8-sig")

        self.assertIn("TradeHelperCLI.spec", build)
        self.assertIn("[switch]$SkipTests", build)
        self.assertIn("TradeHelperCLI.exe", package)
        self.assertIn("cli_executable_sha256", package)
        self.assertIn('"/TradeHelperCLI.exe"', verify)
        self.assertIn('"/config/personal_v1.json"', verify)
        self.assertIn('"/docs/strategy_replay.md"', verify)

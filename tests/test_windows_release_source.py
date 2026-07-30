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
        self.assertIn('"/RELEASE_NOTES.md"', verify)

        gui_spec = (ROOT / "TradeHelper.spec").read_text(encoding="utf-8")
        cli_spec = (ROOT / "TradeHelperCLI.spec").read_text(encoding="utf-8")
        self.assertIn("windows_version_info.txt", gui_spec)
        self.assertIn("windows_cli_version_info.txt", cli_spec)

    def test_packaged_daily_tasks_use_cli_and_local_app_data(self) -> None:
        register = (
            ROOT / "scripts" / "register_daily_task.ps1"
        ).read_text(encoding="utf-8-sig")
        pipeline = (
            ROOT / "scripts" / "run_daily_pipeline.ps1"
        ).read_text(encoding="utf-8-sig")
        package = (
            ROOT / "scripts" / "package_windows_release.ps1"
        ).read_text(encoding="utf-8-sig")
        verify = (
            ROOT / "scripts" / "verify_windows_release.ps1"
        ).read_text(encoding="utf-8-sig")

        self.assertIn("TradeHelperCLI.exe", register)
        self.assertIn("TradeHelperCLI.exe", pipeline)
        self.assertIn("TradeHelper\\account.db", pipeline)
        self.assertNotIn("-m trade_helper.cli", pipeline)
        self.assertIn("register_daily_task.ps1", package)
        self.assertIn('"/scripts/run_daily_pipeline.ps1"', verify)

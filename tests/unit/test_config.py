import tempfile
from pathlib import Path
from unittest import TestCase, mock

from localpilot.config import Settings


class SettingsTests(TestCase):
    def test_safe_defaults_are_offline_loopback_and_renamed(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch("localpilot.config.Path.home", return_value=Path("/unused-home")):
            settings = Settings.from_env()
        self.assertTrue(settings.offline)
        self.assertEqual(settings.ollama_url, "http://127.0.0.1:11434")
        self.assertEqual(settings.data_dir, Path("/unused-home/.jean-grey"))

    def test_invalid_context_is_rejected(self) -> None:
        with mock.patch.dict("os.environ", {"JEAN_GREY_CONTEXT_WINDOW": "1"}, clear=True):
            with self.assertRaisesRegex(ValueError, "CONTEXT_WINDOW"):
                Settings.from_env()

    def test_legacy_environment_is_compatible_and_new_name_wins(self) -> None:
        values = {"LOCALPILOT_MODEL": "legacy", "LOCALPILOT_DATA_DIR": "legacy-data",
                  "JEAN_GREY_MODEL": "current"}
        with mock.patch.dict("os.environ", values, clear=True): settings = Settings.from_env()
        self.assertEqual(settings.model, "current")
        self.assertEqual(settings.data_dir, Path("legacy-data"))

    def test_existing_legacy_directory_is_used_without_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); (home / ".localpilot").mkdir()
            with mock.patch.dict("os.environ", {}, clear=True), \
                 mock.patch("localpilot.config.Path.home", return_value=home):
                settings = Settings.from_env()
            self.assertEqual(settings.data_dir, home / ".localpilot")
            self.assertTrue((home / ".localpilot").exists())

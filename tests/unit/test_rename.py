import io
import tomllib
from pathlib import Path
from unittest import TestCase, mock

from localpilot.app.main import build_parser, run


class RenameTests(TestCase):
    def test_distribution_and_primary_entry_point_are_renamed(self):
        metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(metadata["project"]["name"], "jean-grey")
        self.assertEqual(metadata["project"]["scripts"]["jean-grey"], "localpilot.app.main:main")
        self.assertIn("localpilot", metadata["project"]["scripts"])

    def test_cli_branding_and_commands(self):
        self.assertEqual(build_parser().prog, "jean-grey")
        self.assertEqual(build_parser().parse_args(["voice"]).command, "voice")
        self.assertEqual(build_parser().parse_args(["chat"]).command, "chat")

    def test_voice_health_check_is_side_effect_free_and_reports_offline(self):
        with mock.patch.dict("os.environ", {"JEAN_GREY_OFFLINE": "true"}, clear=True), \
             mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            code = run(["voice", "--check"])
        self.assertIn(code, {0, 3})
        self.assertIn('"offline": true', output.getvalue())
        self.assertIn('"speech_to_text"', output.getvalue())

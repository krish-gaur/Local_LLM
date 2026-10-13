import io
import tempfile
from pathlib import Path
from unittest import TestCase, mock

from localpilot.app.main import run


class AgentCliTests(TestCase):
    def test_agent_demo_needs_no_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.dict("os.environ", {"LOCALPILOT_DATA_DIR": directory}, clear=True), \
             mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            code = run(["agent", "--prompt", "verified demo report"])
            self.assertEqual(code, 0)
            self.assertIn('"status": "COMPLETED"', output.getvalue())
            self.assertEqual((Path(directory) / "demo" / "report.txt").read_text(),
                             "verified demo report")

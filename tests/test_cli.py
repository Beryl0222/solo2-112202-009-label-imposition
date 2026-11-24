"""命令行入口的轻量测试。"""
import io
import contextlib
import unittest

import pack_check
from pack_audit.materials import DEFAULT_DATA


class CliTest(unittest.TestCase):
    def test_validate_default_output(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            pack_check.main(["--directory", str(DEFAULT_DATA), "validate"])
        self.assertIn("claims.tsv", stdout.getvalue())

    def test_batch_command_reports_executable_d1(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            pack_check.main(
                [
                    "batch",
                    "D1",
                    "--directory",
                    str(DEFAULT_DATA),
                    "--today",
                    "2026-11-24",
                ]
            )
        output = stdout.getvalue()
        self.assertIn("批号 D1", output)
        self.assertIn("可整单执行: 是", output)
        self.assertIn("I3(P4)×60", output)


if __name__ == "__main__":
    unittest.main()

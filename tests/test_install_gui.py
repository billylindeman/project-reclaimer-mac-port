"""install.sh in the launcher window's GUI mode: every failure must reach the window as an "error:" line.

Runs install.sh against a throwaway RECLAIMER_HOME with fake commands first on PATH (it fails early, so nothing is
installed or downloaded). Run: /usr/bin/python3 -I -m unittest discover -s tests
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class InstallGuiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bin = self.tmp / "bin"
        self.bin.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def fake(self, name, script):
        f = self.bin / name
        f.write_text("#!/bin/sh\n" + script + "\n")
        f.chmod(0o755)

    def run_install(self):
        env = dict(os.environ, RECLAIMER_GUI="1", RECLAIMER_HOME=str(self.tmp / "home"),
                   RECLAIMER_APPS_DIR=str(self.tmp / "apps"), PATH=f"{self.bin}:{os.environ['PATH']}",
                   RECLAIMER_MCC_FROM=str(self.tmp))  # (skips the free-space check; the test fails earlier anyway)
        p = subprocess.run(["/bin/bash", str(REPO / "install.sh")], env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=120)
        return p.returncode, [l for l in p.stdout.splitlines() if l.startswith("error: ")]

    def test_top_level_failure_reaches_the_window(self):
        self.fake("uname", "echo x86_64")
        rc, errors = self.run_install()
        self.assertNotEqual(rc, 0)
        self.assertEqual(errors, ["error: This needs an Apple Silicon Mac (M1 or newer)."])

    def test_download_failure_inside_a_helper_reaches_the_window(self):
        # fetch runs inside $(...): its error line used to be swallowed, leaving only "the install stopped"
        self.fake("curl", "exit 6")
        rc, errors = self.run_install()
        self.assertNotEqual(rc, 0)
        self.assertTrue(errors, "no error line")
        self.assertIn("internet connection", errors[0])

    def test_unexpected_failure_still_says_something(self):
        # a command failing without die (here: tar) must not end the install silently
        self.fake("tar", "exit 1")
        cache = self.tmp / "home" / "downloads"
        cache.mkdir(parents=True)
        # a cached Wine archive with the right checksum would be needed to reach tar; instead make curl "succeed"
        self.fake("curl", 'for a; do o=$a; done; while [ $# -gt 0 ]; do [ "$1" = -o ] && touch "$2"; shift; done')
        rc, errors = self.run_install()
        self.assertNotEqual(rc, 0)
        self.assertTrue(errors, "the install ended without an error line")


if __name__ == "__main__":
    unittest.main()

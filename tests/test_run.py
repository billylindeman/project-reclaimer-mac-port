"""scripts/run.sh starts the right Project Reclaimer: the newest, or the older release the player chose.

Uses a fake wine that records what it was asked to run. Run: /usr/bin/python3 -I -m unittest discover -s tests
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class RunTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        game = self.home / "game"
        game.mkdir()
        shutil.copy(REPO / "scripts" / "run.sh", game / "run.sh")
        for exe in ("project-reclaimer-v0.9.9.exe", "project-reclaimer-v0.9.13.exe",
                    "project-reclaimer-dedicated-v0.9.13.exe"):
            (game / exe).write_bytes(b"MZ")
        wine = self.home / "wine" / "Wine Staging.app" / "Contents" / "Resources" / "wine" / "bin" / "wine"
        wine.parent.mkdir(parents=True)
        wine.write_text('#!/bin/sh\necho "cwd=$(pwd) exe=$1 mode=$2"\n')
        wine.chmod(0o755)

    def tearDown(self):
        shutil.rmtree(self.home)

    def run_game(self):
        p = subprocess.run(["/bin/zsh", str(self.home / "game" / "run.sh")], capture_output=True, text=True,
                           env=dict(os.environ, RECLAIMER_HOME=str(self.home)), timeout=30)
        return p.stdout.strip()

    def test_newest_by_default(self):
        out = self.run_game()
        self.assertIn("exe=project-reclaimer-v0.9.13.exe mode=game-client", out)
        self.assertIn(f"cwd={self.home}/game", out)

    def test_chosen_older_version_starts_from_its_own_folder(self):
        versions = self.home / "game" / "versions"
        versions.mkdir()
        (versions / "project-reclaimer-v0.9.11.exe").write_bytes(b"MZ")
        (self.home / "game" / "chosen-version").write_text("0.9.11\n")
        out = self.run_game()
        self.assertIn("exe=project-reclaimer-v0.9.11.exe mode=game-client", out)
        self.assertIn(f"cwd={versions}", out)  # (its menu library sits next to it)

    def test_chosen_version_missing_falls_back_to_the_newest(self):
        (self.home / "game" / "chosen-version").write_text("0.9.11\n")
        self.assertIn("exe=project-reclaimer-v0.9.13.exe", self.run_game())


if __name__ == "__main__":
    unittest.main()

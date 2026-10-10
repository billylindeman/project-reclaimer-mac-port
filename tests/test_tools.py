"""Tests for scripts/tools.py (the launcher's Tools menu and auto-fixes), in throwaway homes.

Admin actions run with RECLAIMER_TOOLS_DRYRUN=1, which prints the command instead of asking for a password, so the
real network startup task is never touched. Run: /usr/bin/python3 -I -m unittest discover -s tests
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "scripts" / "tools.py"
WORKSHOP = Path("prefix-wine/drive_c/Program Files (x86)/Steam/steamapps/workshop")


class ToolsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "Games" / "ProjectReclaimer"
        for d in ("game", "logs", "tools", WORKSHOP / "content" / "976730"):
            (self.home / d).mkdir(parents=True)
        # the helper scripts sit next to tools.py in an install's game folder
        for f in ("workshop_helper.py", "presets.py", "reclaimer-loopback.sh", "local.projectreclaimer.loopback.plist"):
            shutil.copy(REPO / "scripts" / f, self.home / "game" / f)
        shutil.copy(TOOLS, self.home / "game" / "tools.py")
        self.apps = self.tmp / "Applications"
        (self.apps / "Project Reclaimer.app" / "Contents").mkdir(parents=True)
        self.desktop = self.tmp / "Desktop"
        self.desktop.mkdir()
        self.env = dict(os.environ, RECLAIMER_HOME=str(self.home), RECLAIMER_TOOLS_DRYRUN="1",
                        RECLAIMER_APPS_DIR=str(self.apps), RECLAIMER_DESKTOP=str(self.desktop),
                        RECLAIMER_GAME_PROCESS=r"project-reclaimer-v9\.9\.99\.exe game-client")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_tool(self, *args, **env):
        p = subprocess.run([sys.executable, "-I", str(self.home / "game" / "tools.py"), *args],
                           env=dict(self.env, **env), capture_output=True, text=True, timeout=60)
        return p.returncode, p.stdout.splitlines()

    def load(self):
        patcher = mock.patch.dict(os.environ, self.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location("tools", self.home / "game" / "tools.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def add_mod(self, wid, title, size):
        d = self.home / WORKSHOP / "content" / "976730" / wid
        d.mkdir()
        (d / "ModInfo.json").write_text(json.dumps({"Title": {"Neutral": title}}))
        (d / "data.bin").write_bytes(b"x" * size)
        (d / ".reclaimer-complete").write_text('{"timeupdated": 1, "manifest": "1"}')
        return d

    # ---- network -----------------------------------------------------------------------------------------------
    def test_net_check_needs_every_range(self):
        t = self.load()
        full = "\n".join(f"\tinet {a} netmask 0xffffffff" for a in t.EXPECTED_ALIASES)
        with mock.patch.object(t, "lo0", return_value="lo0: flags\n\tinet 127.0.0.1 netmask 0xff000000\n" + full):
            self.assertEqual(t.net_check(), "ok")
        with mock.patch.object(t, "lo0", return_value="lo0: flags\n\tinet 127.0.0.1 netmask 0xff000000\n"):
            self.assertEqual(t.net_check(), "missing")

    def test_expected_aliases_come_from_the_installed_loopback_script(self):
        t = self.load()
        for prefix in ("127.0.0.", "127.0.1.", "127.0.2.", "127.3.1."):
            self.assertTrue(any(a.startswith(prefix) for a in t.EXPECTED_ALIASES), prefix)

    def test_net_fix_reinstalls_and_restarts_the_startup_task_with_one_password_prompt(self):
        rc, out = self.run_tool("net-fix")
        self.assertEqual(rc, 0, out)
        admin = [l for l in out if l.startswith("dry-run admin: ")]
        self.assertEqual(len(admin), 1, out)
        cmd = admin[0]
        self.assertIn("/Library/LaunchDaemons/local.projectreclaimer.loopback.plist", cmd)
        self.assertIn("launchctl bootstrap system", cmd)
        self.assertIn("reclaimer-loopback.sh", cmd)
        self.assertEqual(out[-1], "ok")

    # ---- crash check -------------------------------------------------------------------------------------------
    def test_crash_check(self):
        log = self.home / "logs" / "client-wine.log"
        log.write_text("Menu loading screen finished.\n")
        self.assertEqual(self.run_tool("crash-check")[1][-1], "ok")
        log.write_text("...\nYour graphics card stopped responding, so the game had to close.\n")
        self.assertTrue(self.run_tool("crash-check")[1][-1].startswith("crash: The graphics card stopped"))
        log.write_text("thread 'main' panicked at src/thing.rs:1:2:\nboom\n")
        self.assertTrue(self.run_tool("crash-check")[1][-1].startswith("crash: Project Reclaimer hit an error"))

    # ---- mods --------------------------------------------------------------------------------------------------
    def test_mods_lists_titles_sizes_and_free_space(self):
        self.add_mod("111", "Warlock", 3000)
        self.add_mod("222", "Lockout", 1000)
        rc, out = self.run_tool("mods")
        data = json.loads(out[-1])
        self.assertGreater(data["free_bytes"], 0)
        self.assertEqual([(m["id"], m["title"]) for m in data["mods"]], [("111", "Warlock"), ("222", "Lockout")])
        self.assertGreaterEqual(data["mods"][0]["bytes"], 3000)

    def test_remove_mod_deletes_it_and_its_status(self):
        d = self.add_mod("111", "Warlock", 10)
        (self.home / "logs" / "mods").mkdir()
        (self.home / "logs" / "mods" / "111.json").write_text("{}")
        t = self.load()
        with mock.patch.object(t.helper(), "write_manifest") as manifest:
            self.assertEqual(t.remove_mod("111"), "ok")
        self.assertFalse(d.exists())
        self.assertFalse((self.home / "logs" / "mods" / "111.json").exists())
        self.assertTrue(manifest.called)  # the game must stop counting it as installed

    def test_remove_mod_refuses_while_the_game_runs_and_rejects_odd_ids(self):
        self.add_mod("111", "Warlock", 10)
        game = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)",
                                 "project-reclaimer-v9.9.99.exe game-client"])
        try:
            self.assertEqual(self.run_tool("remove-mod", "111")[1][-1], "error: Quit the game first.")
        finally:
            game.kill()
        self.assertTrue(self.run_tool("remove-mod", "../../etc")[1][-1].startswith("error: "))

    # ---- report ------------------------------------------------------------------------------------------------
    def test_report_zips_logs_without_the_steam_account(self):
        (self.home / "steam-account").write_text("SecretName\n")
        (self.home / "version").write_text("1.2.0\n")
        (self.home / "logs" / "launcher.log").write_text("launcher steam: done(\"Signed in as SecretName\")\n")
        (self.home / "logs" / "client-wine.log").write_text("Menu loading screen finished.\n")
        rc, out = self.run_tool("report")
        self.assertTrue(out[-1].startswith("ok "), out)
        path = Path(out[-1][3:])
        self.assertEqual(path.parent, self.desktop)
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            text = "".join(z.read(n).decode("utf-8", "replace") for n in names)
        self.assertIn("client-wine.log", " ".join(names))
        self.assertIn("summary.txt", names)
        self.assertIn("1.2.0", text)
        self.assertNotIn("SecretName", text)
        self.assertNotIn("steam-account", " ".join(names))

    # ---- graphics / steam --------------------------------------------------------------------------------------
    def test_forget_steam(self):
        (self.home / "steam-account").write_text("RealName_1\n")
        self.assertEqual(self.run_tool("forget-steam")[1][-1], "ok")
        self.assertFalse((self.home / "steam-account").exists())

    def test_reset_graphics_writes_the_tuned_settings(self):
        profile = self.home / "prefix-wine/drive_c/users/player/Documents/My Games/Project Reclaimer"
        profile.mkdir(parents=True)
        (profile / "settings.json").write_text(json.dumps({"version": 1, "graphics": {"frame_limit": 240},
                                                           "mouse_sensitivity": 3.0}))
        rc, out = self.run_tool("reset-graphics")
        self.assertEqual(out[-1], "ok", out)
        settings = json.loads((profile / "settings.json").read_text())
        self.assertEqual(settings["graphics"]["frame_limit"], 60)
        self.assertEqual(settings["mouse_sensitivity"], 3.0)  # only graphics change

    def test_repair_and_graphics_wait_for_the_game_to_quit(self):
        game = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)",
                                 "project-reclaimer-v9.9.99.exe game-client"])
        try:
            self.assertEqual(self.run_tool("repair")[1][-1], "error: Quit the game first.")
            self.assertEqual(self.run_tool("reset-graphics")[1][-1], "error: Quit the game first.")
        finally:
            game.kill()

    # ---- force quit / uninstall --------------------------------------------------------------------------------
    def test_force_quit_stops_the_game(self):
        game = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)",
                                 "project-reclaimer-v9.9.99.exe game-client"])
        try:
            rc, out = self.run_tool("force-quit")
            self.assertEqual(out[-1], "ok")
            game.wait(timeout=10)
        finally:
            if game.poll() is None:
                game.kill()
        self.assertIsNotNone(game.poll())

    def test_uninstall_removes_app_and_install_and_asks_once_for_the_network_task(self):
        rc, out = self.run_tool("uninstall")
        self.assertEqual(out[-1], "ok", out)
        self.assertFalse(self.home.exists())
        self.assertFalse((self.apps / "Project Reclaimer.app").exists())
        admin = [l for l in out if l.startswith("dry-run admin: ")]
        self.assertEqual(len(admin), 1)
        self.assertIn("launchctl bootout system/local.projectreclaimer.loopback", admin[0])

    def test_uninstall_removes_the_app_the_player_opened(self):
        moved = self.tmp / "Elsewhere" / "Project Reclaimer.app"
        moved.mkdir(parents=True)
        self.run_tool("uninstall", RECLAIMER_APP_PATH=str(moved))
        self.assertFalse(moved.exists())

    def test_uninstall_refuses_a_home_that_isnt_an_install(self):
        rc, out = self.run_tool("uninstall", RECLAIMER_HOME=str(self.tmp))
        self.assertTrue(out[-1].startswith("error: "))
        self.assertTrue(self.tmp.exists())


if __name__ == "__main__":
    unittest.main()

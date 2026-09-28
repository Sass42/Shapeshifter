"""The setup window, driven without showing it: discovery fills the fields, Install runs every step
(dry run) and says so. Dialogs are stubbed."""
import gc
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
tk = pytest.importorskip("tkinter")
import install  # noqa: E402
import setup_gui  # noqa: E402


@pytest.fixture(autouse=True)
def log_elsewhere(tmp_path, monkeypatch):
    """A run's setup.log goes to the test's folder, not beside the real Setup."""
    monkeypatch.setattr(setup_gui, "LOG_FILE", tmp_path / "setup.log")


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass
    install.WINDOWED = False
    gc.collect()                           # Tk objects must be freed on this thread, never a worker's


@pytest.fixture(autouse=True)
def tools_present(monkeypatch):
    """Every build tool is on the PC unless a test says otherwise (the window checks them first)."""
    monkeypatch.setattr(install, "missing_build_tools", lambda seed=None: [])


def settle(root, until, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        root.update()
        if until():
            return True
        time.sleep(0.02)
    return False


def fake_find(tmp_path):
    core = tmp_path / "core"
    (core / "src" / "server" / "game").mkdir(parents=True)
    (core / "modules").mkdir()
    (core / "CMakeLists.txt").write_text("")
    client = tmp_path / "wow"
    (client / "Data").mkdir(parents=True)
    (client / "Wow.exe").write_bytes(b"")

    def discover(ui, args, ask_missing=True):
        args.core, args.client, args.db = str(core), str(client), {}
        return None
    return core, client, discover


def test_the_window_shows_what_it_found_and_what_is_missing(root, tmp_path, monkeypatch):
    core, client, discover = fake_find(tmp_path)
    monkeypatch.setattr(install, "discover", discover)
    app = setup_gui.App(root)
    assert settle(root, lambda: not app.busy)
    assert app.vars["core"].get() == str(core) and app.vars["client"].get() == str(client)
    assert settle(root, lambda: "Not found:" in app.log.get("1.0", "end"))
    assert "Not found: Build folder, Server (worldserver), MySQL client" in app.log.get("1.0", "end")


def test_fields_that_can_stay_empty_say_so(root, tmp_path, monkeypatch):
    core, client, discover = fake_find(tmp_path)

    def preparing(ui, args, ask_missing=True):
        discover(ui, args, ask_missing)
        args.core, args.prepare_source, args.bots = None, True, True
        return None
    monkeypatch.setattr(install, "discover", preparing)
    app = setup_gui.App(root)
    assert settle(root, lambda: not app.busy)
    assert app.vars["core"].get() == setup_gui.PREPARED_NOTE and app.path("core") is None
    assert app.vars["build"].get() == setup_gui.PREPARED_NOTE and app.bots.get() is True
    app.clear_note("core")
    assert app.vars["core"].get() == ""


def test_install_runs_the_steps_and_reports(root, tmp_path, monkeypatch, capsys):
    core, client, discover = fake_find(tmp_path)
    monkeypatch.setattr(install, "discover", discover)
    monkeypatch.setattr(install, "BACKUPS", tmp_path / "backups")
    shown = {}
    monkeypatch.setattr(setup_gui.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(setup_gui.messagebox, "showinfo", lambda *a, **k: shown.setdefault("info", a))
    monkeypatch.setattr(setup_gui.messagebox, "showwarning", lambda *a, **k: shown.setdefault("warn", a))
    monkeypatch.setattr(install, "plan_steps", lambda uninstall, only=None: (("module", "addon"), install.STEP_FUNCS))
    app = setup_gui.App(root)
    assert settle(root, lambda: not app.busy)
    app.start(False)
    assert settle(root, lambda: shown)
    assert "info" in shown, shown
    log = app.log.get("1.0", "end")
    assert "copying module to" in log and "copying addon to" in log and "== Summary ==" in log
    assert (core / "modules" / "mod-shapeshifter").is_dir()


def test_a_step_question_becomes_a_dialog(root, monkeypatch):
    import queue
    app = setup_gui.App.__new__(setup_gui.App)
    app.root, app.calls = root, queue.Queue()

    def pump():
        while not app.calls.empty():
            app.calls.get()()
        root.after(20, pump)
    pump()
    ui = setup_gui.WindowUi(app, dry_run=True)
    monkeypatch.setattr(setup_gui.messagebox, "askokcancel", lambda *a, **k: False)
    monkeypatch.setattr(setup_gui.simpledialog, "askstring", lambda *a, **k: "2")
    answers = {}

    import threading

    def ask():
        answers["wait"] = ui.ask("   The game is running. Close it, then press Enter (or s to skip this step)")
        answers["pick"] = ui.ask("   Which one (number, or Enter to browse)")
    t = threading.Thread(target=ask)
    t.start()
    assert settle(root, lambda: len(answers) == 2)
    assert answers == {"wait": "s", "pick": "2"}                                 # Cancel skips; numbers typed


RELEASE = {"tag": "v9.0.0", "name": "Shapeshifter-9.0.0.zip", "size": 31000000,
           "url": "https://example.invalid/z.zip", "api": "https://example.invalid/assets/1"}


def test_check_for_updates_says_when_this_is_the_latest(root, tmp_path, monkeypatch):
    core, client, discover = fake_find(tmp_path)
    monkeypatch.setattr(install, "discover", discover)
    monkeypatch.setattr(install, "github_token", lambda: None)
    monkeypatch.setattr(install, "latest_release", lambda token: dict(RELEASE, tag="v" + install.VERSION))
    app = setup_gui.App(root)
    assert settle(root, lambda: not app.busy)
    app.check_update()
    assert settle(root, lambda: "you have the latest" in app.log.get("1.0", "end") and not app.busy)


def test_check_for_updates_downloads_and_hands_over(root, tmp_path, monkeypatch):
    core, client, discover = fake_find(tmp_path)
    monkeypatch.setattr(install, "discover", discover)
    monkeypatch.setattr(install, "github_token", lambda: None)
    monkeypatch.setattr(install, "latest_release", lambda token: RELEASE)
    new = tmp_path / "Shapeshifter-9.0.0"
    new.mkdir()
    (new / "Shapeshifter Setup.exe").write_bytes(b"")
    got, launched, closed = [], [], []
    monkeypatch.setattr(install, "download_release", lambda release, dest, token: got.append(release) or new)
    monkeypatch.setattr(install, "launch", lambda cmd, cwd: launched.append((cmd, cwd)))
    monkeypatch.setattr(setup_gui.messagebox, "askyesno", lambda *a, **kw: True)
    app = setup_gui.App(root)
    assert settle(root, lambda: not app.busy)
    monkeypatch.setattr(app, "quit_for_update", lambda: closed.append(True))
    app.check_update()
    assert settle(root, lambda: closed)
    assert got == [RELEASE]
    assert launched == [([str(new / "Shapeshifter Setup.exe")], str(new))]


def test_declining_an_update_downloads_nothing(root, tmp_path, monkeypatch):
    core, client, discover = fake_find(tmp_path)
    monkeypatch.setattr(install, "discover", discover)
    monkeypatch.setattr(install, "github_token", lambda: None)
    monkeypatch.setattr(install, "latest_release", lambda token: RELEASE)
    monkeypatch.setattr(install, "download_release", lambda *a: pytest.fail("downloaded after No"))
    monkeypatch.setattr(setup_gui.messagebox, "askyesno", lambda *a, **kw: False)
    app = setup_gui.App(root)
    assert settle(root, lambda: not app.busy)
    app.check_update()
    assert settle(root, lambda: not app.busy and "9.0.0" in app.log.get("1.0", "end"))



def test_missing_build_tools_come_first_in_their_own_window(root, tmp_path, monkeypatch):
    core, client, discover = fake_find(tmp_path)
    searched = []

    def preparing(ui, args, ask_missing=True):
        searched.append(True)
        discover(ui, args, ask_missing)
        args.core, args.prepare_source, args.server = None, True, str(tmp_path / "worldserver.exe")
        return None
    monkeypatch.setattr(install, "discover", preparing)
    have = set()
    tools = [("cmake", "CMake", "configures the build", "https://cmake.org/download/"),
             ("vs", "Visual Studio Build Tools (C++)", "the compiler", "https://visualstudio.microsoft.com/")]
    monkeypatch.setattr(install, "missing_build_tools", lambda seed=None: [t for t in tools if t[0] not in have])
    app = setup_gui.App(root)
    assert settle(root, lambda: app.tools_window is not None)
    window = app.tools_window
    assert [m[0] for m in window.missing] == ["cmake", "vs"] and all(v.get() for v in window.vars.values())
    assert str(window.continue_btn.cget("state")) == "disabled"
    assert not searched and str(app.install_btn.cget("state")) == "disabled"   # no server search yet
    window.check()                                          # still missing: nothing moves on
    assert settle(root, lambda: not window.busy)
    assert str(window.continue_btn.cget("state")) == "disabled" and not searched
    have.update({"cmake", "vs"})                            # the player installed them from the links
    window.check()
    assert settle(root, lambda: not window.busy and not window.missing)
    assert str(window.continue_btn.cget("state")) == "normal"
    window.done()
    assert settle(root, lambda: searched and not app.busy)  # only now: the search for the server
    assert app.tools_window is None and str(app.install_btn.cget("state")) == "normal"


def test_closing_the_tools_window_leaves_install_off(root, tmp_path, monkeypatch):
    core, client, discover = fake_find(tmp_path)

    def preparing(ui, args, ask_missing=True):
        discover(ui, args, ask_missing)
        args.core, args.prepare_source, args.server = None, True, str(tmp_path / "worldserver.exe")
        return None
    monkeypatch.setattr(install, "discover", preparing)
    tools = [("cmake", "CMake", "configures the build", "https://cmake.org/download/")]
    monkeypatch.setattr(install, "missing_build_tools", lambda seed=None: list(tools))
    app = setup_gui.App(root)
    assert settle(root, lambda: app.tools_window is not None)
    app.tools_window.close()                                # the player closes it: on to the main window
    assert settle(root, lambda: app.tools_window is not None and not app.busy)   # it comes back after the search
    assert str(app.install_btn.cget("state")) == "disabled"
    assert str(app.uninstall_btn.cget("state")) == "normal"

def test_every_line_of_a_run_is_saved_to_setup_log(tmp_path, monkeypatch):
    import queue
    log = tmp_path / "setup.log"
    monkeypatch.setattr(setup_gui, "LOG_FILE", log)
    lines = queue.Queue()
    writer = setup_gui.LogWriter(lines)
    writer.write("error C2039: 'Foo' is not a member\n")
    writer.write("build FAILED\n")
    writer.close()
    assert log.read_text(encoding="utf-8") == "error C2039: 'Foo' is not a member\nbuild FAILED\n"
    assert lines.get_nowait().startswith("error C2039")

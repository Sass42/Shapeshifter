"""Tests for install.py. Run from the repo root: python -m pytest tests -q"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install  # noqa: E402


def make_core(root):
    (root / "src" / "server" / "game").mkdir(parents=True)
    (root / "modules").mkdir()
    (root / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.16)\nproject(fakecore NONE)\n"
        "add_custom_target(worldserver COMMAND ${CMAKE_COMMAND} -E echo built)\n")
    return root


def make_client(root):
    (root / "Data").mkdir(parents=True)
    (root / "Wow.exe").write_bytes(b"")
    return root


@pytest.fixture
def backups(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "BACKUPS", tmp_path / "backups")
    return tmp_path / "backups"


# ---- helpers ------------------------------------------------------------------------------------

def test_core_and_client_detection(tmp_path):
    assert not install.is_core_root(tmp_path)
    assert install.is_core_root(make_core(tmp_path / "core"))
    assert not install.is_client_root(tmp_path)
    assert install.is_client_root(make_client(tmp_path / "wow"))
    (tmp_path / "bare" / "Data").mkdir(parents=True)
    assert not install.is_client_root(tmp_path / "bare")          # Data/ alone is not enough
    (tmp_path / "bare" / "Interface").mkdir()
    assert install.is_client_root(tmp_path / "bare")


def test_cmake_cache_is_read(tmp_path):
    assert install.read_cmake_cache(tmp_path) == {}
    (tmp_path / "CMakeCache.txt").write_text(
        "# comment\n//help text\nCMAKE_BUILD_TYPE:STRING=Release\n"
        "CMAKE_GENERATOR:INTERNAL=Unix Makefiles\nCMAKE_INSTALL_PREFIX:PATH=/opt/ac\n")
    cache = install.read_cmake_cache(tmp_path)
    assert cache["CMAKE_BUILD_TYPE"] == "Release"
    assert cache["CMAKE_INSTALL_PREFIX"] == "/opt/ac"
    assert not install.is_multi_config(cache)
    assert install.is_multi_config({"CMAKE_GENERATOR": "Visual Studio 17 2022"})
    assert install.is_multi_config({"CMAKE_CONFIGURATION_TYPES": "Debug;Release"})


def test_option_file_quotes_the_password():
    text = install.option_file_text("127.0.0.1", "3306", "acore", 'p"a\\ss word')
    assert text == '[client]\nhost="127.0.0.1"\nport=3306\nuser="acore"\npassword="p\\"a\\\\ss word"\n'


def test_patch_order():
    assert install.patch_order_ok(["core-name-override.patch", "core-weapon-override.patch", "core-form-speed.patch"])
    assert install.patch_order_ok(["core-name-override.patch"])
    assert not install.patch_order_ok(["core-name-override.patch", "core-form-speed.patch"])


def test_every_planned_patch_ships():
    for name, _, need, _ in install.PATCH_PLAN:
        assert (install.PATCHES / name).is_file()
        assert need is None or (install.PATCHES / need).is_file()


# ---- steps --------------------------------------------------------------------------------------

def test_addon_copy_backs_up_an_old_copy(tmp_path, backups):
    client = make_client(tmp_path / "wow")
    old = client / "Interface" / "AddOns" / "Shapeshifter"
    old.mkdir(parents=True)
    (old / "old.lua").write_text("old")
    code = install.main(["--step-by-step", "--only", "addon", "--client", str(client)], answers=["y"])
    assert code == 0
    assert (old / "Shapeshifter.toc").is_file() and not (old / "old.lua").exists()
    kept = list(backups.glob("*/Shapeshifter/old.lua"))
    assert len(kept) == 1
    # A second run finds it current and backs nothing up.
    assert install.main(["--step-by-step", "--only", "addon", "--client", str(client)], answers=["y"]) == 0
    assert len(list(backups.glob("*/Shapeshifter"))) == 1


def test_dry_run_changes_nothing(tmp_path, backups):
    client = make_client(tmp_path / "wow")
    core = make_core(tmp_path / "core")
    code = install.main(["--step-by-step", "--only", "module,addon", "--dry-run", "--core", str(core), "--client", str(client)],
                        answers=["y", "y"])
    assert code == 0
    assert not (client / "Interface").exists()
    assert not any((core / "modules").iterdir())
    assert not backups.exists()


def test_module_copy_and_skip(tmp_path, backups):
    core = make_core(tmp_path / "core")
    assert install.main(["--step-by-step", "--only", "module", "--core", str(core)], answers=["n"]) == 0   # skipped is fine
    assert not (core / "modules" / "mod-shapeshifter").exists()
    assert install.main(["--step-by-step", "--only", "module", "--core", str(core)], answers=["y"]) == 0
    assert install.same_tree(install.MODULE, core / "modules" / "mod-shapeshifter")


def test_quit_stops_and_fails(tmp_path, backups):
    core = make_core(tmp_path / "core")
    assert install.main(["--step-by-step", "--only", "module,addon", "--core", str(core)], answers=["q"]) == 1


def test_sql_uses_an_option_file_and_removes_it(tmp_path, monkeypatch):
    fake_mysql = tmp_path / "mysql.exe"
    fake_mysql.write_bytes(b"")
    seen = {}

    def fake_run(ui, cmd, cwd=None, stdin_bytes=None, check_only=False):
        option = Path(cmd[1].split("=", 1)[1])
        seen["cmd"] = cmd
        seen["option"] = option
        seen["text"] = option.read_text(encoding="utf-8")
        seen["stdin"] = stdin_bytes
        return 0

    monkeypatch.setattr(install, "run", fake_run)
    answers = ["y", "db.example", "3307", "gm", "chars", "secret"]
    assert install.main(["--step-by-step", "--only", "sql", "--mysql", str(fake_mysql)], answers=answers) == 0
    assert seen["cmd"][0] == str(fake_mysql) and seen["cmd"][2] == "chars"
    assert 'password="secret"' in seen["text"] and "port=3307" in seen["text"]
    assert not seen["option"].exists()
    assert b"CREATE TABLE IF NOT EXISTS `shapeshifter_active`" in seen["stdin"]
    assert all("secret" not in str(c) for c in seen["cmd"])


@pytest.mark.skipif(not shutil.which("cmake"), reason="cmake not installed")
def test_build_configures_and_builds_worldserver(tmp_path):
    core = make_core(tmp_path / "core")
    build = tmp_path / "build"
    subprocess.run(["cmake", "-S", str(core), "-B", str(build)], check=True, stdout=subprocess.DEVNULL)
    multi = install.is_multi_config(install.read_cmake_cache(build))
    answers = (["", "y"] if multi else ["y"])
    assert install.main(["--step-by-step", "--only", "build", "--core", str(core), "--build", str(build), "--jobs", "1"],
                        answers=answers) == 0


def test_build_skips_an_unconfigured_folder(tmp_path):
    core = make_core(tmp_path / "core")
    if not shutil.which("cmake"):
        pytest.skip("cmake not installed")
    assert install.main(["--step-by-step", "--only", "build", "--core", str(core)], answers=[""]) == 0


def test_each_marker_is_added_by_its_patch():
    for name, (rel, text) in install.PATCH_MARKERS.items():
        body = (install.PATCHES / name).read_text(encoding="utf-8")
        if text is None:
            assert "+++ b/" + rel in body and "new file mode" in body
        else:
            assert "\n+" + text + "\n" in body
            others = [n for n in install.PATCH_MARKERS if n != name]
            assert all("\n+" + text not in (install.PATCHES / n).read_text(encoding="utf-8") for n in others)


# ---- build load, server binary, class-grade data (2026-09-26) -------------------------------------

def test_build_command_caps_compilers_on_visual_studio():
    vs = install.build_command(Path("b"), "RelWithDebInfo", 4, {"CMAKE_GENERATOR": "Visual Studio 17 2022"})
    assert vs[-4:] == ["--parallel", "1", "--", "/p:CL_MPCount=4"]    # one project at a time, 4 compilers
    make = install.build_command(Path("b"), "Release", 4, {"CMAKE_GENERATOR": "Unix Makefiles"})
    assert make[-2:] == ["--parallel", "4"] and "--" not in make


def test_find_built_worldserver(tmp_path):
    assert install.find_built(tmp_path, "RelWithDebInfo") is None
    exe = tmp_path / "bin" / "RelWithDebInfo" / install.WORLDSERVER
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"new")
    assert install.find_built(tmp_path, "RelWithDebInfo") == exe
    flat = tmp_path / "flat" / "bin" / install.WORLDSERVER
    flat.parent.mkdir(parents=True)
    flat.write_bytes(b"new")
    assert install.find_built(tmp_path / "flat", "Release") == flat


def make_built(tmp_path):
    build = tmp_path / "build"
    exe = build / "bin" / "RelWithDebInfo" / install.WORLDSERVER
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"new binary")
    (exe.parent / "worldserver.pdb").write_bytes(b"new symbols")
    (build / "CMakeCache.txt").write_text("CMAKE_GENERATOR:INTERNAL=Visual Studio 17 2022\n")
    return build


def test_server_step_backs_up_and_replaces(tmp_path, backups):
    core = make_core(tmp_path / "core")
    build = make_built(tmp_path)
    live = tmp_path / "server" / install.WORLDSERVER
    live.parent.mkdir()
    live.write_bytes(b"old binary")
    args = ["--only", "server", "--core", str(core), "--build", str(build), "--server", str(live.parent)]
    assert install.main(["--step-by-step"] + args, answers=["", "y"]) == 0                  # configuration, then yes
    assert live.read_bytes() == b"new binary"
    assert (live.parent / "worldserver.pdb").read_bytes() == b"new symbols"
    assert list(backups.rglob(install.WORLDSERVER))[0].read_bytes() == b"old binary"


def test_server_step_waits_while_the_server_runs(tmp_path, backups, monkeypatch):
    core = make_core(tmp_path / "core")
    build = make_built(tmp_path)
    live = tmp_path / "server" / install.WORLDSERVER
    live.parent.mkdir()
    live.write_bytes(b"old binary")
    real = install.shutil.move
    calls = {"n": 0}

    def busy_once(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("in use")
        return real(src, dst)

    monkeypatch.setattr(install.shutil, "move", busy_once)
    args = ["--only", "server", "--core", str(core), "--build", str(build), "--server", str(live)]
    assert install.main(["--step-by-step"] + args, answers=["", "y", ""]) == 0              # Enter after stopping the server
    assert live.read_bytes() == b"new binary"


def test_server_step_dry_run_changes_nothing(tmp_path, backups):
    core = make_core(tmp_path / "core")
    build = make_built(tmp_path)
    live = tmp_path / "server" / install.WORLDSERVER
    live.parent.mkdir()
    live.write_bytes(b"old binary")
    args = ["--only", "server", "--dry-run", "--core", str(core), "--build", str(build), "--server", str(live)]
    assert install.main(["--step-by-step"] + args, answers=["", "y"]) == 0
    assert live.read_bytes() == b"old binary" and not backups.exists()


def test_classgrade_is_skipped_without_its_files(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "CLASSGRADE", tmp_path / "nothing")
    assert install.main(["--step-by-step", "--only", "classgrade"], answers=[]) == 0


def test_classgrade_applies_the_world_sql_and_copies_the_patch(tmp_path, backups, monkeypatch):
    kit = tmp_path / "classgrade"
    kit.mkdir()
    (kit / "shapeshift_class.sql").write_text("SELECT 1;")
    (kit / "patch-Y.MPQ").write_bytes(b"MPQ new")
    monkeypatch.setattr(install, "CLASSGRADE", kit)
    client = make_client(tmp_path / "wow")
    (client / "Data" / "patch-Y.MPQ").write_bytes(b"MPQ old")
    fake_mysql = tmp_path / "mysql.exe"
    fake_mysql.write_bytes(b"")
    seen = {}

    def fake_run(ui, cmd, cwd=None, stdin_bytes=None, check_only=False, low_priority=False):
        seen["cmd"], seen["stdin"] = cmd, stdin_bytes
        return 0

    monkeypatch.setattr(install, "run", fake_run)
    answers = ["y", "127.0.0.1", "3307", "root", "world", "pw"]
    assert install.main(["--step-by-step", "--only", "classgrade", "--mysql", str(fake_mysql), "--client", str(client)],
                        answers=answers) == 0
    assert seen["cmd"][2] == "world" and seen["stdin"] == b"SELECT 1;"
    assert (client / "Data" / "patch-Y.MPQ").read_bytes() == b"MPQ new"
    assert list(backups.rglob("patch-Y.MPQ"))[0].read_bytes() == b"MPQ old"


def test_one_database_login_serves_both_steps(tmp_path, backups, monkeypatch):
    kit = tmp_path / "classgrade"
    kit.mkdir()
    (kit / "shapeshift_class.sql").write_text("SELECT 1;")
    (kit / "patch-Y.MPQ").write_bytes(b"MPQ")
    monkeypatch.setattr(install, "CLASSGRADE", kit)
    client = make_client(tmp_path / "wow")
    fake_mysql = tmp_path / "mysql.exe"
    fake_mysql.write_bytes(b"")
    dbs = []
    monkeypatch.setattr(install, "run", lambda ui, cmd, **kw: dbs.append(cmd[2]) or 0)
    answers = ["y", "127.0.0.1", "3307", "root", "chars", "pw",       # sql: login and database
               "y", "world"]                                          # classgrade: only the database
    assert install.main(["--step-by-step", "--only", "sql,classgrade", "--mysql", str(fake_mysql), "--client", str(client)],
                        answers=answers) == 0
    assert dbs == ["chars", "world"]


# ---- uninstall (2026-09-26) ---------------------------------------------------------------------

CLASS_SQL = """CREATE TABLE IF NOT EXISTS `shapeshift_stance` (`gear_set` INT);
START TRANSACTION;
DELETE FROM `spell_dbc` WHERE `ID` BETWEEN 14000000 AND 14199999;
INSERT INTO `spell_dbc` VALUES (1);
DELETE FROM `item_template` WHERE `entry` BETWEEN 9300000 AND 9319999;
DELETE FROM `shapeshift_stance`;
INSERT INTO `shapeshift_stance` VALUES (1);
COMMIT;
"""


def test_the_class_grade_uninstall_sql_is_the_install_sqls_own_deletes():
    text = install.uninstall_classgrade_sql(CLASS_SQL)
    lines = text.strip().splitlines()
    assert lines[0] == "START TRANSACTION;" and "COMMIT;" in lines
    assert "DELETE FROM `spell_dbc` WHERE `ID` BETWEEN 14000000 AND 14199999;" in lines
    assert "DELETE FROM `item_template` WHERE `entry` BETWEEN 9300000 AND 9319999;" in lines
    assert "INSERT" not in text and lines[-1] == "DROP TABLE IF EXISTS `shapeshift_stance`;"


def test_uninstall_moves_the_addon_and_the_module_to_backups(tmp_path, backups):
    core = make_core(tmp_path / "core")
    client = make_client(tmp_path / "wow")
    shutil.copytree(install.MODULE, core / "modules" / "mod-shapeshifter")
    shutil.copytree(install.ADDON, client / "Interface" / "AddOns" / "Shapeshifter")
    args = ["--uninstall", "--only", "addon,module", "--core", str(core), "--client", str(client)]
    assert install.main(["--step-by-step"] + args, answers=["y", "y"]) == 0
    assert not (core / "modules" / "mod-shapeshifter").exists()
    assert not (client / "Interface" / "AddOns" / "Shapeshifter").exists()
    assert list(backups.rglob("mod-shapeshifter")) and list(backups.rglob("Shapeshifter"))


def test_uninstall_dry_run_changes_nothing(tmp_path, backups):
    core = make_core(tmp_path / "core")
    shutil.copytree(install.MODULE, core / "modules" / "mod-shapeshifter")
    assert install.main(["--step-by-step", "--uninstall", "--dry-run", "--only", "module", "--core", str(core)], answers=["y"]) == 0
    assert (core / "modules" / "mod-shapeshifter").exists() and not backups.exists()


def test_uninstall_reverses_only_applied_patches_newest_first(tmp_path, monkeypatch):
    core = make_core(tmp_path / "core")
    (core / "src" / "server" / "game" / "Cache").mkdir()
    (core / "src" / "server" / "game" / "Cache" / "NameOverride.h").write_text("//")
    player = core / "src" / "server" / "game" / "Entities" / "Player" / "Player.h"
    player.parent.mkdir(parents=True)
    player.write_text("#define COA_WEAPON_OVERRIDE 1\n")        # speed not applied
    calls = []
    monkeypatch.setattr(install.shutil, "which", lambda name: name)
    monkeypatch.setattr(install, "run_quiet", lambda cmd, cwd=None: (calls.append(("check", cmd)) or (0, "")))
    monkeypatch.setattr(install, "run", lambda ui, cmd, **kw: calls.append(("apply", cmd)) or 0)
    assert install.main(["--step-by-step", "--uninstall", "--only", "patches", "--core", str(core)], answers=["y"]) == 0
    reversed_ = [Path(c[1][-1]).name for c in calls if c[0] == "apply"]
    assert reversed_ == ["core-weapon-override.patch", "core-name-override.patch"]
    assert all("-R" in c[1] for c in calls)


def test_uninstall_drops_the_characters_table(tmp_path, monkeypatch):
    fake_mysql = tmp_path / "mysql.exe"
    fake_mysql.write_bytes(b"")
    seen = {}
    monkeypatch.setattr(install, "run", lambda ui, cmd, stdin_bytes=None, **kw: seen.update(db=cmd[2], sql=stdin_bytes) or 0)
    answers = ["y", "127.0.0.1", "3307", "root", "chars", "pw"]
    assert install.main(["--step-by-step", "--uninstall", "--only", "sql", "--mysql", str(fake_mysql)], answers=answers) == 0
    assert seen["db"] == "chars" and b"DROP TABLE IF EXISTS `shapeshift_active`" in seen["sql"]


def test_uninstall_classgrade_removes_the_rows_and_the_client_patch(tmp_path, backups, monkeypatch):
    kit = tmp_path / "classgrade"
    kit.mkdir()
    (kit / "shapeshift_class.sql").write_text(CLASS_SQL)
    (kit / "patch-Y.MPQ").write_bytes(b"MPQ")
    monkeypatch.setattr(install, "CLASSGRADE", kit)
    client = make_client(tmp_path / "wow")
    (client / "Data" / "patch-Y.MPQ").write_bytes(b"MPQ live")
    fake_mysql = tmp_path / "mysql.exe"
    fake_mysql.write_bytes(b"")
    seen = {}
    monkeypatch.setattr(install, "run", lambda ui, cmd, stdin_bytes=None, **kw: seen.update(db=cmd[2], sql=stdin_bytes) or 0)
    answers = ["y", "127.0.0.1", "3307", "root", "world", "pw"]
    args = ["--uninstall", "--only", "classgrade", "--mysql", str(fake_mysql), "--client", str(client)]
    assert install.main(["--step-by-step"] + args, answers=answers) == 0
    assert seen["db"] == "world" and b"DROP TABLE IF EXISTS `shapeshift_stance`" in seen["sql"]
    assert not (client / "Data" / "patch-Y.MPQ").exists()
    assert list(backups.rglob("patch-Y.MPQ"))[0].read_bytes() == b"MPQ live"


# ---- the automatic installer (0.15.0) -------------------------------------------------------------

CONF = """# worldserver.conf
LoginDatabaseInfo = "127.0.0.1;3307;acore;s3cret;acore_auth"
WorldDatabaseInfo = "127.0.0.1;3307;acore;s3cret;acore_world"
CharacterDatabaseInfo     = "127.0.0.1;3307;acore;s3;c;ret;acore_characters"
"""


def test_the_database_logins_come_from_worldserver_conf():
    db = install.parse_db_info(CONF)
    assert db["world"] == {"host": "127.0.0.1", "port": "3307", "user": "acore", "password": "s3cret",
                           "database": "acore_world"}
    assert db["characters"]["password"] == "s3;c;ret"                 # a ; inside the password survives
    assert db["characters"]["database"] == "acore_characters"


def make_repack(root):
    """A Conquest-of-Azeroth-style repack: Scripts/manage.py, a bots server with its configs."""
    (root / "Scripts").mkdir(parents=True)
    (root / "Scripts" / "manage.py").write_text("")
    (root / "CoA-Bots").mkdir()
    (root / "CoA-Bots" / "coa_bots.py").write_text("")
    exe = root / "CoA-Bots" / "Core" / install.WORLDSERVER
    (exe.parent / "configs").mkdir(parents=True)
    exe.write_bytes(b"old")
    (exe.parent / "configs" / "worldserver.conf").write_text(CONF)
    return exe


def test_a_repack_is_recognised_around_its_server(tmp_path):
    exe = make_repack(tmp_path / "Repack")
    repack = install.repack_of(exe)
    assert repack["root"] == tmp_path / "Repack"
    assert repack["bots"] == tmp_path / "Repack" / "CoA-Bots" / "coa_bots.py"      # the bots server's launcher
    assert install.find_conf(exe) == exe.parent / "configs" / "worldserver.conf"
    plain = tmp_path / "plain" / install.WORLDSERVER
    plain.parent.mkdir()
    plain.write_bytes(b"")
    assert install.repack_of(plain) is None


def test_saved_settings_move_to_the_new_name(tmp_path, backups):
    client = make_client(tmp_path / "wow")
    account = client / "WTF" / "Account" / "ME" / "SavedVariables"
    account.mkdir(parents=True)
    (account / "Shapeshift.lua").write_text('ShapeshiftDB = {\n\t["skins"] = {},\n}\n')
    char = client / "WTF" / "Account" / "ME" / "Realm" / "Hero" / "SavedVariables"
    char.mkdir(parents=True)
    (char / "Shapeshift.lua").write_text("ShapeshiftCharDB = {\n}\n")
    ui = install.Ui(False, [])
    assert install.migrate_saved_variables(ui, client, backups) == 2
    assert (account / "Shapeshifter.lua").read_text().startswith("ShapeshifterDB = {")
    assert (char / "Shapeshifter.lua").read_text().startswith("ShapeshifterCharDB = {")
    assert (account / "Shapeshift.lua").exists()                       # the old file stays
    assert install.migrate_saved_variables(ui, client, backups) == 0   # never twice


def test_the_old_addon_and_module_are_moved_aside(tmp_path, backups):
    core = make_core(tmp_path / "core")
    client = make_client(tmp_path / "wow")
    (core / "modules" / "mod-shapeshift").mkdir()
    (client / "Interface" / "AddOns" / "Shapeshift").mkdir(parents=True)
    args = ["--step-by-step", "--only", "module,addon", "--core", str(core), "--client", str(client)]
    assert install.main(args, answers=["y", "y"]) == 0
    assert not (core / "modules" / "mod-shapeshift").exists() and (core / "modules" / "mod-shapeshifter").is_dir()
    assert not (client / "Interface" / "AddOns" / "Shapeshift").exists()
    assert (client / "Interface" / "AddOns" / "Shapeshifter" / "Shapeshifter.toc").is_file()


def test_a_repack_server_is_stopped_and_started_through_its_scripts(tmp_path, monkeypatch):
    exe = make_repack(tmp_path / "Repack")
    state = {"up": True, "cmds": []}
    monkeypatch.setattr(install, "running_at", lambda path, names: [42] if state["up"] else [])

    def fake_run(ui, cmd, **kw):
        state["cmds"].append([Path(str(c)).name for c in cmd] + (["detached"] if kw.get("detached") else []))
        if cmd[-1] == "stop-all":
            state["up"] = False
        return 0

    monkeypatch.setattr(install, "run", fake_run)
    server = install.Server(install.Ui(False, []), exe)
    assert server.stop() is True and server.stopped_by_us
    server.ensure_database()
    assert server.start()
    # whatever keeps running after Setup closes (MySQL, auth, world) starts detached from Setup
    assert state["cmds"] == [[Path(sys.executable).name, "-B", "manage.py", "stop-all"],
                             [Path(sys.executable).name, "-B", "manage.py", "start-mysql", "detached"],
                             [Path(sys.executable).name, "-B", "coa_bots.py", "start-all", "detached"]]


def test_the_detached_launcher_logs_output_and_keeps_the_exit_code(tmp_path):
    text = install.launcher_text(["C:/Run Time/python.exe", "-B", "x.py", "start-all"], tmp_path / "out.log",
                                 tmp_path / "rc")
    lines = text.split("\r\n")
    assert lines[0] == "@echo off"
    assert lines[1] == '"C:/Run Time/python.exe" -B x.py start-all > "{}" 2>&1'.format(tmp_path / "out.log")
    assert lines[2] == '>"{}" echo %errorlevel%'.format(tmp_path / "rc.tmp")
    assert "100%%" in install.launcher_text(["echo", "100%"], tmp_path / "o", tmp_path / "r")   # % is literal


@pytest.mark.skipif(sys.platform != "win32", reason="the detached start is Windows only")
def test_a_detached_run_streams_the_output_and_returns_the_exit_code(tmp_path, monkeypatch, capsys):
    started = []

    def fake_start(cmd, cwd, show=False):          # runs the launcher in place of the WMI start
        started.append((cmd, show))
        subprocess.run(cmd, cwd=cwd)
        return 4242
    monkeypatch.setattr(install, "start_detached", fake_start)
    code = install.run(install.Ui(False, []), [sys.executable, "-c", "print('servers up'); raise SystemExit(3)"],
                       cwd=str(tmp_path), detached=True)
    assert code == 3
    assert "servers up" in capsys.readouterr().out
    assert started and started[0][1] is False


def test_a_detached_start_reads_the_pid_through_powershell_noise(monkeypatch):
    monkeypatch.setattr(install.os, "name", "nt")
    monkeypatch.setattr(install, "run_quiet", lambda cmd, cwd=None: (0, "26172\r\n#< CLIXML\r\n<Objs>progress</Objs>"))
    assert install.start_detached(["cmd", "/c", "x.cmd"], "C:/") == 26172
    monkeypatch.setattr(install, "run_quiet", lambda cmd, cwd=None: (1, "#< CLIXML\r\n<Objs>error</Objs>"))
    assert install.start_detached(["cmd", "/c", "x.cmd"], "C:/") is None


def test_a_detached_run_falls_back_to_a_plain_run_when_windows_refuses(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(install, "start_detached", lambda cmd, cwd, show=False: None)
    code = install.run(install.Ui(False, []), [sys.executable, "-c", "raise SystemExit(5)"], cwd=str(tmp_path),
                       detached=True)
    assert code == 5


def test_an_unknown_server_starts_detached_in_its_own_window(tmp_path, monkeypatch):
    exe = tmp_path / "srv" / install.WORLDSERVER
    exe.parent.mkdir()
    exe.write_bytes(b"")
    started = []
    monkeypatch.setattr(install, "start_detached", lambda cmd, cwd, show=False: started.append((cmd, cwd, show)) or 77)
    monkeypatch.setattr(install.subprocess, "Popen", lambda *a, **kw: pytest.fail("started as Setup's child"))
    assert install.Server(install.Ui(False, []), exe).start()
    assert started == [([str(exe)], str(exe.parent), True)]


def test_an_unknown_server_is_closed_after_one_warning(tmp_path, monkeypatch):
    exe = tmp_path / "srv" / install.WORLDSERVER
    exe.parent.mkdir()
    exe.write_bytes(b"")
    state = {"up": True, "killed": []}
    monkeypatch.setattr(install, "running_at", lambda path, names: [7] if state["up"] else [])
    monkeypatch.setattr(install, "run_quiet", lambda cmd, cwd=None: (state["killed"].append(cmd), state.update(up=False),
                                                                     (0, ""))[-1])
    server = install.Server(install.Ui(False, ["y"]), exe)          # "y": close it
    assert server.stop() is True and state["killed"]
    state["up"] = True
    assert install.Server(install.Ui(False, ["n"]), exe).stop() is None   # "n": left alone


def fake_discovery(monkeypatch, core, build, exe, client):
    def discover(ui, args):
        args.core, args.build, args.server, args.client = str(core), str(build), str(exe), str(client)
        args.db = {}
        return install.Server(ui, exe)
    monkeypatch.setattr(install, "discover", discover)


def test_the_automatic_run_asks_once_and_does_every_step(tmp_path, backups, monkeypatch):
    core = make_core(tmp_path / "core")
    build = make_built(tmp_path)
    exe = make_repack(tmp_path / "Repack")
    client = make_client(tmp_path / "wow")
    fake_discovery(monkeypatch, core, build, exe, client)
    state = {"up": True}
    monkeypatch.setattr(install, "running_at", lambda path, names: [42] if state["up"] else [])
    monkeypatch.setattr(install, "list_processes", lambda names: [])
    monkeypatch.setattr(install, "run", lambda ui, cmd, **kw: state.update(up=state["up"] and cmd[-1] != "stop-all") or 0)
    code = install.main(["--only", "module,server,addon,start"], answers=[""])      # one Enter: go ahead
    assert code == 0
    assert (core / "modules" / "mod-shapeshifter").is_dir()
    assert exe.read_bytes() == b"new binary"
    assert (client / "Interface" / "AddOns" / "Shapeshifter").is_dir()


def test_a_failed_step_still_starts_the_stopped_server(tmp_path, backups, monkeypatch):
    core = make_core(tmp_path / "core")
    build = make_built(tmp_path)
    exe = make_repack(tmp_path / "Repack")
    client = make_client(tmp_path / "wow")
    fake_discovery(monkeypatch, core, build, exe, client)
    calls = []
    monkeypatch.setattr(install, "running_at", lambda path, names: [] if "stop-all" in str(calls) else [42])
    monkeypatch.setattr(install, "run", lambda ui, cmd, **kw: calls.append(cmd[-1]) or 0)

    def broken(ui, args):
        return False
    monkeypatch.setitem(install.STEP_FUNCS, "sql", broken)
    code = install.main(["--only", "server,sql,start"], answers=[""])
    assert code == 1 and calls[-1] == "start-all"


def test_saying_no_up_front_changes_nothing(tmp_path, backups, monkeypatch):
    core = make_core(tmp_path / "core")
    client = make_client(tmp_path / "wow")
    fake_discovery(monkeypatch, core, tmp_path / "nobuild", tmp_path / "noexe", client)
    monkeypatch.setattr(install, "running_at", lambda path, names: [])
    assert install.main(["--only", "module"], answers=["n"]) == 1
    assert not (core / "modules" / "mod-shapeshifter").exists()


def test_the_build_behind_the_running_server_wins(tmp_path):
    ours, other = make_built(tmp_path / "ours"), make_built(tmp_path / "other")
    (other / "bin" / "RelWithDebInfo" / install.WORLDSERVER).write_bytes(b"another binary")
    live = tmp_path / "live" / install.WORLDSERVER
    live.parent.mkdir()
    live.write_bytes(b"new binary")                                   # what "ours" built
    assert install.server_build([other, ours], live) == ours
    assert install.pick_build(install.Ui(False, []), [other, ours], live) == ours
    assert install.pick_build(install.Ui(False, ["2"]), [other, ours], tmp_path / "nothing") == ours   # asked


def test_a_search_gives_up_after_its_time_budget(tmp_path):
    for i in range(30):
        (tmp_path / "d{}".format(i)).mkdir()
    slow = []

    def test(folder):
        slow.append(folder)
        install.time.sleep(0.02)
        return False
    install.scan([tmp_path], test, depth=2, budget=0.1)
    assert len(slow) < 31


# ---- preparing the repack's own source (0.16.0) ---------------------------------------------------

def make_repack_with_source(root, bots_rev="abc123"):
    exe = make_repack(root)
    import zipfile
    (root / "Source").mkdir()
    with zipfile.ZipFile(str(root / "Source" / "server-source.zip"), "w") as z:
        z.writestr("server-source/CMakeLists.txt", "cmake_minimum_required(VERSION 3.16)\nproject(x NONE)\n")
        z.writestr("server-source/src/server/game/Main.cpp", "")
        z.writestr("server-source/modules/.gitkeep", "")
    (root / "CoA-Bots" / "release.json").write_text('{"botsModuleRevision": "%s"}' % bots_rev)
    (root / "CoA-Bots" / "README.md").write_text(
        "Source of this build: the core at https://github.com/x/core (commit 1), the bots at "
        "https://github.com/Zyth45/mod-playerbots (branch `coa`), the dashboard at y.\n")
    return exe


def test_the_bots_source_is_read_from_coa_bots_own_files(tmp_path):
    exe = make_repack_with_source(tmp_path / "Repack")
    bots = install.bots_source(install.repack_of(exe)["root"])
    assert bots == {"url": "https://github.com/Zyth45/mod-playerbots", "branch": "coa", "revision": "abc123"}


def test_cmake_seed_flags_come_from_an_existing_build():
    cache = {"CMAKE_GENERATOR": "Visual Studio 17 2022", "CMAKE_GENERATOR_PLATFORM": "x64",
             "BOOST_ROOT": "C:/local/boost", "OPENSSL_ROOT_DIR": "C:/OpenSSL", "MYSQL_INCLUDE_DIR": "C:/mysql/inc",
             "MYSQL_LIBRARY": "C:/mysql/lib/libmysql.lib", "SCRIPTS": "static", "MODULES": "static",
             "CMAKE_HOME_DIRECTORY": "C:/old", "SOMETHING_ELSE": "x"}
    flags = install.seed_flags(cache)
    assert flags[:4] == ["-G", "Visual Studio 17 2022", "-A", "x64"]
    assert "-DBOOST_ROOT=C:/local/boost" in flags and "-DMODULES=static" in flags
    assert not any("CMAKE_HOME_DIRECTORY" in f or "SOMETHING_ELSE" in f for f in flags)
    assert install.seed_flags({}) == ["-DSCRIPTS=static", "-DMODULES=static", "-DTOOLS_BUILD=none"]


def test_preparing_unpacks_fetches_playerbots_and_configures(tmp_path, monkeypatch):
    exe = make_repack_with_source(tmp_path / "Repack")
    calls = []

    def fake_run(ui, cmd, cwd=None, **kw):
        calls.append([str(c) for c in cmd])
        if cmd[:2] == ["git", "clone"]:
            Path(str(cmd[-1])).mkdir(parents=True)
        return 0
    monkeypatch.setattr(install, "run", fake_run)
    monkeypatch.setattr(install.shutil, "which", lambda name: name)
    args = type("A", (), {"server": str(exe), "bots": True, "core": None, "build": None, "seed": {}, "prepare_source": True})()
    assert install.step_source(install.Ui(False, []), args) is True
    src = tmp_path / "Repack" / "Source" / "shapeshifter-source"
    assert (src / "src" / "server" / "game" / "Main.cpp").is_file()                 # unpacked, prefix stripped
    assert args.core == str(src) and args.build == str(tmp_path / "Repack" / "Source" / "shapeshifter-build")
    clone = [c for c in calls if c[:2] == ["git", "clone"]][0]
    assert "https://github.com/Zyth45/mod-playerbots" in clone and clone[-1].endswith("mod-playerbots")
    assert ["git", "checkout", "abc123"] in [c[:3] for c in calls]
    assert any(c[0] == "cmake" and "-S" in c for c in calls)
    calls.clear()
    assert install.step_source(install.Ui(False, []), args) is True                  # a second run reuses it
    assert not any(c[:2] == ["git", "clone"] for c in calls)


def test_without_the_bots_box_no_playerbots_is_fetched(tmp_path, monkeypatch):
    exe = make_repack_with_source(tmp_path / "Repack")
    calls = []
    monkeypatch.setattr(install, "run", lambda ui, cmd, cwd=None, **kw: calls.append([str(c) for c in cmd]) or 0)
    args = type("A", (), {"server": str(exe), "bots": False, "core": None, "build": None, "seed": {}, "prepare_source": True})()
    assert install.step_source(install.Ui(False, []), args) is True
    assert not any(c[:2] == ["git", "clone"] for c in calls)


def test_a_first_search_stops_at_the_first_find(tmp_path):
    for drive in ("c", "d"):
        for i in range(5):
            (tmp_path / drive / "f{}".format(i)).mkdir(parents=True)
    (tmp_path / "c" / "f3" / "hit").mkdir()
    (tmp_path / "d" / "f1" / "hit").mkdir()
    seen = []

    def test(folder):
        seen.append(folder)
        return folder.name == "hit"
    found = install.scan([tmp_path / "c", tmp_path / "d"], test, depth=2, first=True)
    assert found == [tmp_path / "c" / "f3" / "hit"]
    assert not any(tmp_path / "d" in f.parents or f == tmp_path / "d" for f in seen)    # D: never searched


# ---- build speed (2026-09-27): 75% of the CPU threads, server stopped first, Release for the repack's source

@pytest.mark.parametrize("threads, jobs", [(16, 12), (12, 9), (8, 6), (4, 3), (2, 1), (1, 1), (None, 1)])
def test_default_jobs_leave_a_quarter_of_the_cpu_free(monkeypatch, threads, jobs):
    monkeypatch.setattr(install.os, "cpu_count", lambda: threads)
    assert install.default_jobs() == jobs


def test_the_build_stops_a_running_server_first(tmp_path, monkeypatch):
    import argparse
    core = make_core(tmp_path / "core")
    build = make_built(tmp_path)
    exe = make_repack(tmp_path / "Repack")
    state = {"up": True, "cmds": []}
    monkeypatch.setattr(install, "running_at", lambda path, names: [42] if state["up"] else [])

    def fake_run(ui, cmd, **kw):
        state["cmds"].append([str(c) for c in cmd])
        if cmd[-1] == "stop-all":
            state["up"] = False
        return 0
    monkeypatch.setattr(install, "run", fake_run)
    ui = install.Ui(False, [])
    ui.auto = True
    args = argparse.Namespace(core=str(core), build=str(build), config="RelWithDebInfo", jobs=2,
                              prepare_source=False, server_ctl=install.Server(ui, exe))
    assert install.step_build(ui, args) is True
    assert args.server_ctl.stopped_by_us
    kinds = ["stop" if c[-1] == "stop-all" else c[0] for c in state["cmds"]]
    assert kinds == ["stop", "cmake", "cmake"]                  # stopped before configure and build


def test_the_prepared_source_builds_release(tmp_path, monkeypatch):
    exe = make_repack_with_source(tmp_path / "Repack")
    calls = []
    monkeypatch.setattr(install, "run", lambda ui, cmd, cwd=None, **kw: calls.append([str(c) for c in cmd]) or 0)
    args = type("A", (), {"server": str(exe), "bots": False, "core": None, "build": None, "seed": {}, "prepare_source": True})()
    assert install.step_source(install.Ui(False, []), args) is True
    configure = [c for c in calls if c[0] == "cmake"][0]
    assert "-DCMAKE_BUILD_TYPE=Release" in configure
    assert args.config == "Release"


# ---- the MySQL client DLL travels with the worldserver (2026-09-27, ACE00046 on the repack) --------

def make_mysql(root):
    (root / "lib").mkdir(parents=True)
    (root / "lib" / "libmysql.lib").write_bytes(b"import lib")
    (root / "lib" / "libmysql.dll").write_bytes(b"client 8.4.11")
    return root


def test_mysql_client_dll_is_found_next_to_the_import_library(tmp_path):
    mysql = make_mysql(tmp_path / "mysql")
    cache = {"MYSQL_LIBRARY": str(mysql / "lib" / "libmysql.lib")}
    assert install.mysql_client_dll(cache) == mysql / "lib" / "libmysql.dll"
    assert install.mysql_client_dll({}) is None
    assert install.mysql_client_dll({"MYSQL_LIBRARY": str(tmp_path / "nowhere" / "libmysql.lib")}) is None


def test_server_step_swaps_the_mysql_client_dll_too(tmp_path, backups):
    core = make_core(tmp_path / "core")
    build = make_built(tmp_path)
    mysql = make_mysql(tmp_path / "mysql")
    (build / "CMakeCache.txt").write_text("CMAKE_GENERATOR:INTERNAL=Visual Studio 17 2022\n"
                                          "MYSQL_LIBRARY:FILEPATH={}\n".format((mysql / "lib" / "libmysql.lib").as_posix()))
    live = tmp_path / "server" / install.WORLDSERVER
    live.parent.mkdir()
    live.write_bytes(b"old binary")
    (live.parent / "libmysql.dll").write_bytes(b"client 8.4.9")
    args = ["--only", "server", "--core", str(core), "--build", str(build), "--server", str(live.parent)]
    assert install.main(["--step-by-step"] + args, answers=["", "y"]) == 0
    assert (live.parent / "libmysql.dll").read_bytes() == b"client 8.4.11"
    assert list(backups.rglob("libmysql.dll"))[0].read_bytes() == b"client 8.4.9"


def test_server_step_leaves_a_matching_mysql_client_dll_alone(tmp_path, backups):
    core = make_core(tmp_path / "core")
    build = make_built(tmp_path)
    mysql = make_mysql(tmp_path / "mysql")
    (build / "CMakeCache.txt").write_text("CMAKE_GENERATOR:INTERNAL=Visual Studio 17 2022\n"
                                          "MYSQL_LIBRARY:FILEPATH={}\n".format((mysql / "lib" / "libmysql.lib").as_posix()))
    live = tmp_path / "server" / install.WORLDSERVER
    live.parent.mkdir()
    live.write_bytes(b"old binary")
    (live.parent / "libmysql.dll").write_bytes(b"client 8.4.11")
    args = ["--only", "server", "--core", str(core), "--build", str(build), "--server", str(live.parent)]
    assert install.main(["--step-by-step"] + args, answers=["", "y"]) == 0
    assert not list(backups.rglob("libmysql.dll"))                       # same bytes: nothing to replace


def test_server_step_retires_a_stale_pdb_when_the_build_has_none(tmp_path, backups):
    core = make_core(tmp_path / "core")
    build = make_built(tmp_path)
    (build / "bin" / "RelWithDebInfo" / "worldserver.pdb").unlink()                 # a Release build
    live = tmp_path / "server" / install.WORLDSERVER
    live.parent.mkdir()
    live.write_bytes(b"old binary")
    (live.parent / "worldserver.pdb").write_bytes(b"old symbols")
    args = ["--only", "server", "--core", str(core), "--build", str(build), "--server", str(live.parent)]
    assert install.main(["--step-by-step"] + args, answers=["", "y"]) == 0
    assert not (live.parent / "worldserver.pdb").exists()
    assert list(backups.rglob("worldserver.pdb"))[0].read_bytes() == b"old symbols"


def test_the_core_path_from_the_cmake_cache_uses_the_native_separator(tmp_path):
    import os
    core = make_core(tmp_path / "core")
    build = tmp_path / "build"
    build.mkdir()
    (build / "CMakeCache.txt").write_text("CMAKE_HOME_DIRECTORY:INTERNAL={}\n".format(core.as_posix()))
    assert install.core_of_build(build) == str(core)
    assert "/" not in install.core_of_build(build) or os.sep == "/"
    assert install.core_of_build(tmp_path / "none") is None


# ---- which server, partly applied patches, the repack's database (2026-09-27) ---------------------

def make_servers(tmp_path):
    """A CoA-Bots server, the same repack's own server, and an unrelated AzerothCore build."""
    bots = make_repack(tmp_path / "CoApack" / "CoA-Repack")
    base = tmp_path / "CoApack" / "CoA-Repack" / "Core" / install.WORLDSERVER
    other = tmp_path / "Build" / "bin" / install.WORLDSERVER
    for exe in (base, other):
        (exe.parent / "configs").mkdir(parents=True)
        exe.write_bytes(b"")
        (exe.parent / "configs" / "worldserver.conf").write_text(CONF)
    return bots, base, other


class NoQuestions(install.Ui):
    def ask(self, prompt, default=""):
        raise AssertionError("asked: " + prompt)


def test_servers_are_offered_coa_bots_first_then_the_repack_then_the_rest(tmp_path):
    bots, base, other = make_servers(tmp_path)
    assert install.rank_servers([], [other, base, bots]) == [bots, base, other]
    assert install.rank_servers([other], [bots, other]) == [bots, other]            # once each, running or not


def test_several_servers_are_asked_about_and_enter_takes_the_first(tmp_path):
    bots, base, other = make_servers(tmp_path)
    servers = [bots, base, other]
    assert install.pick_server(install.Ui(False, [""]), servers) == bots
    assert install.pick_server(install.Ui(False, ["3"]), servers) == other
    assert install.pick_server(install.Ui(False, ["9"]), servers) == bots             # not on the list
    assert install.pick_server(NoQuestions(False, []), [other]) == other             # one server: no question
    assert install.pick_server(NoQuestions(False, []), []) is None


def test_the_search_offers_the_coa_bots_server_before_a_nearer_one(tmp_path, monkeypatch):
    bots, base, other = make_servers(tmp_path)                    # the other build is found first (shallower)
    monkeypatch.setattr(install, "drive_roots", lambda: [tmp_path])
    monkeypatch.setattr(install, "list_processes", lambda names: [])
    monkeypatch.setattr(install.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    asked = []

    class Recorder(install.Ui):
        def ask(self, prompt, default=""):
            asked.append(prompt)
            return default
    args = argparse.Namespace(core=None, build=None, server=None, client=None, mysql=None, bots=None)
    install.discover(Recorder(False, []), args, ask_missing=False)
    assert args.server == str(bots)
    assert len(asked) == 1 and str(other) in asked[0] and "1. " + str(bots) in asked[0]


def git_core(tmp_path):
    """A core under git with two files and a patch changing both; marker in the first."""
    if not shutil.which("git"):
        pytest.skip("git not installed")
    core = make_core(tmp_path / "core")
    for name in ("a.txt", "b.txt"):
        (core / name).write_text("one\ntwo\nthree\n")
    subprocess.run(["git", "init", "-q"], cwd=core, check=True)
    subprocess.run(["git", "add", "-A"], cwd=core, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"], cwd=core, check=True)
    for name in ("a.txt", "b.txt"):
        (core / name).write_text("one\n#define MARK_{} 1\ntwo\nthree\n".format(name[0].upper()))
    patch = tmp_path / "patches" / "p.patch"
    patch.parent.mkdir()
    patch.write_bytes(subprocess.run(["git", "diff"], cwd=core, check=True, stdout=subprocess.PIPE).stdout)
    subprocess.run(["git", "checkout", "-q", "--", "."], cwd=core, check=True)
    return core, patch


def half_apply(monkeypatch, core, patch):
    monkeypatch.setattr(install, "PATCHES", patch.parent)
    monkeypatch.setattr(install, "PATCH_PLAN", (("p.patch", True, None, "test patch"),))
    monkeypatch.setattr(install, "PATCH_MARKERS", {"p.patch": ("a.txt", "#define MARK_A 1")})
    subprocess.run(["git", "apply", "--include=a.txt", str(patch)], cwd=core, check=True)   # stopped half way


def test_uninstall_reverses_a_half_applied_patch(tmp_path, monkeypatch):
    core, patch = git_core(tmp_path)
    half_apply(monkeypatch, core, patch)
    assert install.split_patch_files(core, patch) == (["a.txt"], ["b.txt"], [])
    assert install.main(["--step-by-step", "--uninstall", "--only", "patches", "--core", str(core)], answers=["y"]) == 0
    assert (core / "a.txt").read_text() == (core / "b.txt").read_text() == "one\ntwo\nthree\n"


def test_install_completes_a_half_applied_patch(tmp_path, monkeypatch):
    core, patch = git_core(tmp_path)
    half_apply(monkeypatch, core, patch)
    assert install.main(["--step-by-step", "--only", "patches", "--core", str(core)], answers=["y"]) == 0
    assert "#define MARK_B 1" in (core / "b.txt").read_text()
    assert subprocess.run(["git", "apply", "-R", "--check", str(patch)], cwd=core).returncode == 0   # whole now


def test_an_uninstall_starts_the_repacks_database_before_its_sql(tmp_path, monkeypatch):
    exe = make_repack(tmp_path / "Repack")
    cmds = []
    monkeypatch.setattr(install, "running_at", lambda path, names: [])
    monkeypatch.setattr(install, "run", lambda ui, cmd, **kw: cmds.append(Path(str(cmd[-1])).name) or 0)
    monkeypatch.setattr(install, "run_sql", lambda *a, **kw: cmds.append("sql") or 0)
    mysql = tmp_path / "mysql.exe"
    mysql.write_bytes(b"")
    ui = install.Ui(False, [])
    args = argparse.Namespace(db=install.parse_db_info(CONF), mysql=str(mysql), server_ctl=install.Server(ui, exe))
    assert install.undo_sql(ui, args) is True
    assert cmds == ["start-mysql", "sql"]


def test_each_root_is_searched_to_the_end_before_the_next(tmp_path):
    deep = tmp_path / "c" / "x" / "y" / "z"
    deep.mkdir(parents=True)
    (tmp_path / "d").mkdir()
    test = lambda folder: folder.name in ("z", "d")                  # noqa: E731
    assert install.scan([tmp_path / "c", tmp_path / "d"], test, depth=3) == [deep, tmp_path / "d"]


def test_the_coa_bots_box_follows_the_chosen_server(tmp_path, monkeypatch):
    bots, base, other = make_servers(tmp_path)
    monkeypatch.setattr(install, "drive_roots", lambda: [tmp_path])
    monkeypatch.setattr(install, "list_processes", lambda names: [])
    monkeypatch.setattr(install.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    for server, ticked in ((bots, True), (base, False)):
        args = argparse.Namespace(core=None, build=None, server=str(server), client=None, mysql=None, bots=None)
        install.discover(install.Ui(False, []), args, ask_missing=False)
        assert args.bots is ticked


# ---- update mode (2026-09-27): rebuild only when server code changed; fetch the latest release -----

def build_args(tmp_path, monkeypatch, server_bytes=b"new binary", stamped=True):
    """A built core (make_built) behind a repack server, with the build stamped for this code."""
    core = make_core(tmp_path / "core")
    build = make_built(tmp_path)
    exe = make_repack(tmp_path / "Repack")
    exe.write_bytes(server_bytes)
    if stamped:
        install.write_build_stamp(build)
    state = {"up": True, "cmds": []}
    monkeypatch.setattr(install, "running_at", lambda path, names: [42] if state["up"] else [])

    def fake_run(ui, cmd, **kw):
        state["cmds"].append([str(c) for c in cmd])
        if cmd[-1] == "stop-all":
            state["up"] = False
        return 0
    monkeypatch.setattr(install, "run", fake_run)
    ui = install.Ui(False, [])
    ui.auto = True
    args = argparse.Namespace(core=str(core), build=str(build), config="RelWithDebInfo", jobs=2,
                              prepare_source=False, server_ctl=install.Server(ui, exe))
    return ui, args, state, build


def test_server_code_hash_follows_the_module_and_the_patches(tmp_path, monkeypatch):
    module, patches = tmp_path / "module", tmp_path / "patches"
    shutil.copytree(str(install.MODULE), str(module))
    shutil.copytree(str(install.PATCHES), str(patches))
    monkeypatch.setattr(install, "MODULE", module)
    monkeypatch.setattr(install, "PATCHES", patches)
    first = install.server_code_hash()
    assert install.server_code_hash() == first
    (module / "src" / "Shapeshift.cpp").write_bytes((module / "src" / "Shapeshift.cpp").read_bytes() + b"\n")
    second = install.server_code_hash()
    assert second != first
    (patches / "core-name-override.patch").write_bytes(b"changed")
    assert install.server_code_hash() != second


def test_the_build_is_skipped_when_the_server_code_did_not_change(tmp_path, monkeypatch, capsys):
    ui, args, state, build = build_args(tmp_path, monkeypatch)
    assert install.step_build(ui, args) is True
    assert state["cmds"] == []                                  # no stop, no configure, no build
    assert not args.server_ctl.stopped_by_us
    assert "no rebuild needed" in capsys.readouterr().out


def test_changed_server_code_builds_and_stamps_the_build(tmp_path, monkeypatch):
    ui, args, state, build = build_args(tmp_path, monkeypatch, stamped=False)
    (build / install.BUILD_STAMP).write_text('{"code": "older"}')
    assert install.step_build(ui, args) is True
    assert [c[0] for c in state["cmds"] if c[-1] != "stop-all"] == ["cmake", "cmake"]
    assert install.build_is_current(build, "RelWithDebInfo", args.server_ctl.exe)


def test_a_server_running_another_binary_is_rebuilt(tmp_path, monkeypatch):
    ui, args, state, build = build_args(tmp_path, monkeypatch, server_bytes=b"some other build")
    assert install.step_build(ui, args) is True
    assert [c[0] for c in state["cmds"] if c[-1] != "stop-all"] == ["cmake", "cmake"]


def test_a_failed_build_leaves_no_stamp(tmp_path, monkeypatch):
    ui, args, state, build = build_args(tmp_path, monkeypatch, stamped=False)
    monkeypatch.setattr(install, "running_at", lambda path, names: [])
    monkeypatch.setattr(install, "run", lambda ui, cmd, **kw: 1 if "--build" in [str(c) for c in cmd] else 0)
    assert install.step_build(ui, args) is False
    assert not (build / install.BUILD_STAMP).exists()


@pytest.mark.parametrize("tag, newer", [("v1.0.2", True), ("1.1.0", True), ("v2.0.0", True), ("v1.0.1", False),
                                        ("v1.0.0", False), ("v0.9.9", False), ("nightly", False)])
def test_only_a_higher_version_counts_as_an_update(monkeypatch, tag, newer):
    monkeypatch.setattr(install, "VERSION", "1.0.1")
    assert install.is_newer(tag) is newer


RELEASE_JSON = (b'{"tag_name": "v1.0.2", "assets": [{"name": "Shapeshifter-1.0.2.zip", "size": 12,'
                b' "url": "https://api.github.com/repos/Sass42/Shapeshifter/releases/assets/7",'
                b' "browser_download_url": "https://github.com/Sass42/Shapeshifter/releases/download/v1.0.2/'
                b'Shapeshifter-1.0.2.zip"}]}')


def test_the_latest_release_is_read_from_github(monkeypatch):
    seen = []
    monkeypatch.setattr(install, "http_get", lambda url, token=None, accept=None: seen.append(url) or RELEASE_JSON)
    release = install.latest_release(token=None)
    assert seen == ["https://api.github.com/repos/Sass42/Shapeshifter/releases/latest"]
    assert release["tag"] == "v1.0.2" and release["name"] == "Shapeshifter-1.0.2.zip"
    assert release["api"].endswith("/assets/7")


def test_a_hidden_repository_is_reported_not_crashed(monkeypatch, capsys):
    import urllib.error

    def refuse(url, token=None, accept=None):
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
    monkeypatch.setattr(install, "http_get", refuse)
    assert install.latest_release(token=None) is None
    assert "private" in capsys.readouterr().out


def test_a_release_downloads_and_unpacks_beside_this_copy(tmp_path, monkeypatch):
    import io
    import zipfile
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, "w") as z:
        z.writestr("Shapeshifter-1.0.2/install.py", "VERSION = '1.0.2'\n")
    monkeypatch.setattr(install, "http_get", lambda url, token=None, accept=None: blob.getvalue())
    release = install.parse_release(RELEASE_JSON)
    folder = install.download_release(release, tmp_path, token=None)
    assert folder == tmp_path / "Shapeshifter-1.0.2"
    assert (folder / "install.py").read_text() == "VERSION = '1.0.2'\n"


def test_update_hands_over_to_the_new_version(tmp_path, monkeypatch):
    new = tmp_path / "Shapeshifter-1.0.2"
    (new).mkdir()
    (new / "install.py").write_text("")
    launched = []
    monkeypatch.setattr(install, "VERSION", "1.0.1")
    monkeypatch.setattr(install, "github_token", lambda: None)
    monkeypatch.setattr(install, "latest_release", lambda token: install.parse_release(RELEASE_JSON))
    monkeypatch.setattr(install, "download_release", lambda release, dest, token: new)
    monkeypatch.setattr(install, "launch", lambda cmd, cwd: launched.append((cmd, cwd)))
    assert install.main(["--update", "--dry-run"]) == 0
    assert launched == [([sys.executable, str(new / "install.py"), "--dry-run"], str(new))]


def test_update_does_nothing_when_this_is_the_latest(monkeypatch, capsys):
    monkeypatch.setattr(install, "VERSION", "1.0.2")
    monkeypatch.setattr(install, "github_token", lambda: None)
    monkeypatch.setattr(install, "latest_release", lambda token: install.parse_release(RELEASE_JSON))
    monkeypatch.setattr(install, "download_release", lambda *a: pytest.fail("downloaded the same version"))
    assert install.main(["--update"]) == 0
    assert "latest" in capsys.readouterr().out

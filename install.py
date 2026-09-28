#!/usr/bin/env python3
"""Shapeshifter installer: core patches, the server module, the worldserver build and swap, its
database table, the class-grade data (Conquest of Azeroth) and the addon, all in one go.

Run it with Python 3.8 or newer (standard library only). It finds your server, core source, build
folder, client and database login by itself (a folder browser opens for anything it cannot find),
asks once, then does everything: it stops a running server for the swap and starts it again after.
Nothing is overwritten without a backup in backups/<date>/, and --dry-run changes nothing.

    python install.py                 # find everything, confirm once, install
    python install.py --uninstall     # the same, undone
    python install.py --dry-run       # show what it would do
    python install.py --step-by-step  # ask before each step (and for each path)
    python install.py --only addon    # just some steps
"""

import argparse
import base64
import datetime
import filecmp
import getpass
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

VERSION = "1.1.1"
HERE = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
PATCHES = HERE / "patches"
MODULE = HERE / "module" / "mod-shapeshifter"
ADDON = HERE / "addon" / "Shapeshifter"
SQL = MODULE / "data" / "sql" / "db-characters" / "base" / "shapeshifter_active.sql"
BACKUPS = HERE / "backups"
CLASSGRADE = HERE / "classgrade"       # the Conquest of Azeroth class-grade data (in the release zip)
CLASSGRADE_FILES = ("shapeshift_class.sql", "patch-Y.MPQ")
BUILD_STAMP = "shapeshifter-build.json"   # in the build folder: the server code its last build compiled
RELEASES = "Sass42/Shapeshifter"          # the GitHub repository --update looks in
WORLDSERVER = "worldserver.exe" if os.name == "nt" else "worldserver"
GAME_EXES = ("Ascension.exe", "Wow.exe", "WoW.exe", "wow.exe")
STEPS = ("source", "patches", "module", "build", "server", "sql", "classgrade", "addon", "start")
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000   # Windows: the build yields to everything else on the PC
CREATE_NEW_CONSOLE = 0x00000010            # Windows: a restarted server gets its own console window
CREATE_NO_WINDOW = 0x08000000              # Windows: tools run by the setup window get no console of their own
WINDOWED = False                           # set by the setup window: tool output streams into its log
# The names before the rename to Shapeshifter (Shapeshift): moved aside on install so the old copy never runs beside the new.
OLD_ADDON, OLD_MODULE = "Shapeshift", "mod-shapeshift"
SAVED_RENAMES = (("Shapeshift.lua", "Shapeshifter.lua", "ShapeshiftDB", "ShapeshifterDB"),
                 ("Shapeshift.lua", "Shapeshifter.lua", "ShapeshiftCharDB", "ShapeshifterCharDB"))

# In order: form-speed's hunks sit next to weapon-override's, so it only applies after it.
# (name, required, prerequisite, what it does)
PATCH_PLAN = (
    ("core-name-override.patch", True, None,
     "Forms answer name queries with the creature's name. Required: the module will not build without it."),
    ("core-weapon-override.patch", False, None,
     "Forms swing their own weapons instead of yours. Optional."),
    ("core-form-speed.patch", False, "core-weapon-override.patch",
     "Forms run and fly at their own speed. Optional; needs the weapon patch."),
)

# What each patch leaves in the source: (file, text it holds, or None when the file itself is new).
# A reverse --check cannot tell, since a later patch stacked on an earlier one breaks it.
PATCH_MARKERS = {
    "core-name-override.patch": ("src/server/game/Cache/NameOverride.h", None),
    "core-weapon-override.patch": ("src/server/game/Entities/Player/Player.h", "#define COA_WEAPON_OVERRIDE 1"),
    "core-form-speed.patch": ("src/server/game/Entities/Player/Player.h", "#define COA_FORM_SPEED 1"),
}


class Quit(Exception):
    pass


# ---- small pure helpers (tested in tests/test_install.py) ---------------------------------------

def is_core_root(path):
    """An AzerothCore source tree: the game sources, the modules folder and the top CMakeLists."""
    p = Path(path)
    return (p / "src" / "server" / "game").is_dir() and (p / "modules").is_dir() and (p / "CMakeLists.txt").is_file()


def is_client_root(path):
    """A 3.3.5a client folder: it holds Data/ and a game executable or an Interface/ folder."""
    p = Path(path)
    if not (p / "Data").is_dir():
        return False
    exes = ("Wow.exe", "WoW.exe", "wow.exe", "Ascension.exe")
    return (p / "Interface").is_dir() or any((p / e).is_file() for e in exes)


def core_of_build(build_dir):
    """The source folder a build was configured from, spelled the native way (CMake writes C:/x)."""
    home = read_cmake_cache(build_dir).get("CMAKE_HOME_DIRECTORY")
    return str(Path(home)) if home else None


def read_cmake_cache(build_dir):
    """The CMakeCache.txt entries as {name: value}; empty when the folder was never configured."""
    cache = Path(build_dir) / "CMakeCache.txt"
    entries = {}
    if not cache.is_file():
        return entries
    for line in cache.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith(("#", "//")) or "=" not in line or ":" not in line.split("=", 1)[0]:
            continue
        key, value = line.split("=", 1)
        entries[key.split(":", 1)[0]] = value
    return entries


def is_multi_config(cache):
    """Visual Studio and Ninja Multi-Config builds pick Debug/Release at build time (--config)."""
    return bool(cache.get("CMAKE_CONFIGURATION_TYPES")) or "Visual Studio" in cache.get("CMAKE_GENERATOR", "") \
        or "Multi-Config" in cache.get("CMAKE_GENERATOR", "")


def option_file_text(host, port, user, password):
    """A mysql client option file, so the password never shows on a command line or in a process list."""
    def quoted(value):
        return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'
    return "[client]\nhost={}\nport={}\nuser={}\npassword={}\n".format(quoted(host), int(port), quoted(user),
                                                                      quoted(password))


def patch_order_ok(chosen):
    """Every chosen patch's prerequisite is chosen too."""
    names = set(chosen)
    return all(need is None or need in names for name, _, need, _ in PATCH_PLAN if name in names)


def patch_applied(core, name):
    """True when the patch's marker is already in the core source."""
    rel, text = PATCH_MARKERS[name]
    path = Path(core) / rel
    if text is None:
        return path.is_file()
    return path.is_file() and text in path.read_text(encoding="utf-8", errors="replace")


def patch_files(patch):
    """The source files a patch changes or adds (its +++ b/ lines)."""
    return [line[6:].strip() for line in Path(patch).read_text(encoding="utf-8", errors="replace").splitlines()
            if line.startswith("+++ b/")]


def split_patch_files(core, patch):
    """For a patch its marker says is in the core but git cannot reverse as a whole (a run that
    stopped half way leaves some files patched, others not): (files that have it, files that lack
    it, files that are neither), each file checked by git apply on its own."""
    have, lack, neither = [], [], []
    for rel in patch_files(patch):
        include = "--include=" + rel
        if run_quiet(["git", "apply", "-R", "--check", include, patch], cwd=core)[0] == 0:
            have.append(rel)
        elif run_quiet(["git", "apply", "--check", include, patch], cwd=core)[0] == 0:
            lack.append(rel)
        else:
            neither.append(rel)
    return have, lack, neither


def default_jobs():
    """Compilers at a time: three quarters of the CPU threads, so a quarter stays free and the PC
    never sits at 100% (12 of 16). The build also runs below normal priority, and the server is
    stopped before it starts. --jobs overrides."""
    return max(1, (os.cpu_count() or 2) * 3 // 4)


def build_command(build, config, jobs, cache):
    """The worldserver build. On Visual Studio, MSBuild runs one project at a time with `jobs`
    compilers (--parallel alone lets every project start its own compiler per core, which can take
    the whole machine); elsewhere `jobs` parallel jobs."""
    cmd = ["cmake", "--build", str(build), "--config", config, "--target", "worldserver"]
    if "Visual Studio" in cache.get("CMAKE_GENERATOR", ""):
        return cmd + ["--parallel", "1", "--", "/p:CL_MPCount={}".format(int(jobs))]
    return cmd + ["--parallel", str(int(jobs))]


def find_built(build, config):
    """The worldserver the build produced: bin/<config>/ (multi-config) or bin/, else None."""
    for candidate in (Path(build) / "bin" / config / WORLDSERVER, Path(build) / "bin" / WORLDSERVER):
        if candidate.is_file():
            return candidate
    return None


def mysql_mismatch(cache, target):
    """Why a worldserver built against the cache's MySQL cannot start in a CoA-Bots server, or None.
    CoA-Bots copies the repack's Core\\libmysql.dll over its own at every start unless the sizes match,
    and a worldserver behind a client DLL of another version stops at startup (ACE00046)."""
    repack = repack_of(target)
    dll = mysql_client_dll(cache) if cache else None
    if os.name != "nt" or not repack or not repack["bots"] or not dll:
        return None
    shipped = repack["root"] / "Core" / "libmysql.dll"
    if not shipped.is_file() or dll.stat().st_size == shipped.stat().st_size \
            or file_version(dll) == file_version(shipped):
        return None
    want = dll_version_text(shipped) or "?"
    return ("this worldserver was built against MySQL client {} but the repack ships {}. CoA-Bots puts the "
            "repack's libmysql.dll back at every start, and the server would stop at startup. Nothing was "
            "changed on your server: run Setup again and it rebuilds against MySQL {}.").format(
        dll_version_text(dll) or "?", want, want)


def mysql_client_dll(cache):
    """The libmysql.dll of the MySQL the build linked against (next to its import library), or None.
    The worldserver refuses to start behind a client DLL of another version (ACE00046), so the DLL
    travels with the binary."""
    library = cache.get("MYSQL_LIBRARY")
    if not library:
        return None
    dll = Path(library).parent / "libmysql.dll"
    return dll if dll.is_file() else None


def stamp():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")


def same_tree(a, b):
    """True when folder b holds exactly the files of folder a with the same bytes."""
    a, b = Path(a), Path(b)
    if not b.is_dir():
        return False
    fa = sorted(p.relative_to(a).as_posix() for p in a.rglob("*") if p.is_file())
    fb = sorted(p.relative_to(b).as_posix() for p in b.rglob("*") if p.is_file())
    if fa != fb:
        return False
    return all(filecmp.cmp(a / f, b / f, shallow=False) for f in fa)


# ---- console ------------------------------------------------------------------------------------

class Ui:
    def __init__(self, dry_run, assume_input=None):
        self.dry_run = dry_run
        self.answers = assume_input        # tests feed answers here instead of the keyboard
        self.notes = []                    # printed again at the end: rollback lines, reminders
        self.login = None                  # the MySQL login, asked once, kept in memory only
        self.auto = False                  # automatic mode: one confirmation up front, then no questions

    def ask(self, prompt, default=""):
        suffix = " [{}]".format(default) if default else ""
        if self.answers is not None:
            reply = self.answers.pop(0) if self.answers else ""
            print("{}{}: {}".format(prompt, suffix, reply))
        else:
            try:
                reply = input("{}{}: ".format(prompt, suffix))
            except EOFError:
                raise Quit()
        return reply.strip() or default

    def confirm(self, prompt):
        """Yes (Enter or y), no (n, the step is skipped) or quit (q). In the automatic mode every
        step was confirmed up front, so this answers yes by itself."""
        if self.auto:
            print(prompt + " yes")
            return True
        while True:
            reply = self.ask(prompt + " [Y/n/q]").lower()
            if reply in ("", "y", "yes"):
                return True
            if reply in ("n", "no", "s", "skip"):
                return False
            if reply in ("q", "quit"):
                raise Quit()

    def password(self, prompt):
        if self.answers is not None:
            return self.answers.pop(0) if self.answers else ""
        return getpass.getpass(prompt + ": ")

    def step(self, title, why):
        print("\n== {} ==".format(title))
        for line in why:
            print("   " + line)

    def note(self, text):
        self.notes.append(text)


# ---- finding the tools a build needs ---------------------------------------------------------------
# Setup only sees the PATH it was started with: git or CMake installed while it was open, or installed
# without adding itself to PATH (GitHub Desktop's git, the CMake inside Visual Studio), is not on it.
# So a tool is looked for on PATH, then on the PATH Windows has now, then where installers put it.

TOOL_DIRS = {
    "git": (r"%ProgramFiles%\Git\cmd", r"%ProgramW6432%\Git\cmd", r"%ProgramFiles(x86)%\Git\cmd",
            r"%LOCALAPPDATA%\Programs\Git\cmd", r"%USERPROFILE%\scoop\shims", r"%ProgramData%\chocolatey\bin"),
    "cmake": (r"%ProgramFiles%\CMake\bin", r"%ProgramW6432%\CMake\bin", r"%ProgramFiles(x86)%\CMake\bin",
              r"%LOCALAPPDATA%\Programs\CMake\bin", r"%USERPROFILE%\scoop\shims", r"%ProgramData%\chocolatey\bin"),
}
# Inside a Visual Studio installation (vswhere lists them).
VS_TOOL_DIRS = {
    "git": r"Common7\IDE\CommonExtensions\Microsoft\TeamFoundation\Team Explorer\Git\cmd",
    "cmake": r"Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin",
}
TOOLS = ("git", "cmake")          # run() and run_quiet() start these from where find_tool found them
_found_tools = {}


def registry_path():
    """Windows: the folders on PATH as the registry holds it now (the machine's, then the user's)."""
    if os.name != "nt":
        return []
    import winreg
    dirs = []
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                      (winreg.HKEY_CURRENT_USER, "Environment")):
        try:
            with winreg.OpenKey(hive, key) as handle:
                value = winreg.QueryValueEx(handle, "Path")[0]
        except OSError:
            continue
        dirs += [os.path.expandvars(d) for d in str(value).split(";") if d.strip()]
    return dirs


def visual_studios():
    """The Visual Studio (and Build Tools) installation folders, newest first, from vswhere."""
    if os.name != "nt":
        return []
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / \
        "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.is_file():
        return []
    try:
        code, out = run_quiet([vswhere, "-all", "-products", "*", "-sort", "-property", "installationPath"])
    except OSError:
        return []
    return [Path(line.strip()) for line in out.splitlines() if line.strip() and Path(line.strip()).is_dir()]


def tool_candidates(name):
    """Where find_tool looks after PATH, in order."""
    dirs = registry_path() + [os.path.expandvars(d) for d in TOOL_DIRS.get(name, ())]
    if name == "git":
        desktop = Path(os.path.expandvars(r"%LOCALAPPDATA%")) / "GitHubDesktop"
        dirs += [str(d / "resources" / "app" / "git" / "cmd") for d in sorted(desktop.glob("app-*"), reverse=True)]
    if name in VS_TOOL_DIRS:
        dirs += [str(vs / VS_TOOL_DIRS[name]) for vs in visual_studios()]
    return dirs


def find_tool(name):
    """The full path of git or cmake, or None when this PC does not have it."""
    found = shutil.which(name)
    if found:
        return found
    if os.name != "nt":
        return None
    if name not in _found_tools:
        _found_tools[name] = next((str(Path(d) / (name + ".exe")) for d in tool_candidates(name)
                                   if "%" not in d and (Path(d) / (name + ".exe")).is_file()), None)
    return _found_tools[name]


def tool_command(cmd):
    """cmd with git or cmake at its head replaced by the path find_tool found."""
    cmd = [str(c) for c in cmd]
    if cmd and cmd[0] in TOOLS:
        cmd[0] = find_tool(cmd[0]) or cmd[0]
    return cmd


def run(ui, cmd, cwd=None, stdin_bytes=None, check_only=False, low_priority=False, detached=False):
    """Runs a command, or on a dry run only shows it (check_only commands change nothing, so they run).
    low_priority: the command and everything it starts run below normal priority (the build).
    detached: what the command leaves running (a server) must not belong to Setup (run_detached).
    A program this PC does not have is said in words (exit code 127), never a bare WinError 2."""
    shown = " ".join('"{}"'.format(c) if " " in str(c) else str(c) for c in cmd)
    print("   $ " + shown)
    if ui.dry_run and not check_only:
        return 0
    try:
        return run_found(ui, tool_command(cmd), cwd, stdin_bytes, low_priority, detached)
    except FileNotFoundError:
        print("   {} is not installed on this PC (or Setup cannot find it).".format(Path(str(cmd[0])).name))
        return 127


def run_found(ui, cmd, cwd, stdin_bytes, low_priority, detached):
    if detached and os.name == "nt":
        code = run_detached(cmd, cwd)
        if code is not None:
            return code
    flags = 0
    if low_priority:
        if os.name == "nt":
            flags |= BELOW_NORMAL_PRIORITY_CLASS
        elif shutil.which("nice"):
            cmd = ["nice", "-n", "10"] + cmd
    if WINDOWED:
        if os.name == "nt":
            flags |= CREATE_NO_WINDOW
        proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
        if stdin_bytes is not None:
            proc.stdin.write(stdin_bytes)
            proc.stdin.close()
        for raw in proc.stdout:
            print("   " + raw.decode("utf-8", "replace").rstrip())
        return proc.wait()
    extra = {"creationflags": flags} if flags else {}
    result = subprocess.run(cmd, cwd=cwd, input=stdin_bytes, **extra)
    return result.returncode


def start_detached(cmd, cwd, show=False):
    """Windows: starts `cmd` through WMI (Win32_Process.Create), so it and everything it starts hang off
    Windows' WMI host instead of Setup: Task Manager lists them on their own and closing Setup never
    touches them. The window is hidden unless `show`. Returns the new pid, or None."""
    if os.name != "nt":
        return None

    def quote(text):
        return "'" + str(text).replace("'", "''") + "'"
    script = ("$ProgressPreference = 'SilentlyContinue'; "
              "$si = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{{ShowWindow=[uint16]{}}}; "
              "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{{CommandLine={}; "
              "CurrentDirectory={}; ProcessStartupInformation=$si}}; if ($r.ReturnValue -eq 0) {{ $r.ProcessId }}").format(
        1 if show else 0, quote(subprocess.list2cmdline([str(c) for c in cmd])), quote(cwd or os.getcwd()))
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        code, out = run_quiet(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded])
    except OSError:
        return None
    # The pid is a line of its own; stderr noise (progress records) must not hide a start that happened,
    # or the caller starts the server a second time.
    pids = [line.strip() for line in out.splitlines() if line.strip().isdigit()]
    return int(pids[0]) if pids else None


def launcher_text(cmd, log, rc):
    """The batch file run_detached starts: the command with its output in `log`, then its exit code
    written to `rc` in one move, so a reader never sees half of it."""
    def lit(text):
        return str(text).replace("%", "%%")
    tmp = Path(str(rc) + ".tmp")
    return "\r\n".join(["@echo off",
                         '{} > "{}" 2>&1'.format(lit(subprocess.list2cmdline([str(c) for c in cmd])), lit(log)),
                         '>"{}" echo %errorlevel%'.format(lit(tmp)),
                         'move /y "{}" "{}" > nul'.format(lit(tmp), lit(rc)), ""])


def run_detached(cmd, cwd, timeout=3600):
    """Runs `cmd` through a launcher that start_detached starts, so the servers it leaves running
    belong to Windows and not to Setup. Shows the output as the log grows and returns the exit code;
    None when the launcher could not be started (the caller then runs the command itself)."""
    work = Path(tempfile.mkdtemp(prefix="shapeshifter-run-"))
    log, rc = work / "out.log", work / "rc"
    launcher = work / "run.cmd"
    try:
        launcher.write_bytes(launcher_text(cmd, log, rc).encode("oem"))
    except (UnicodeEncodeError, LookupError):
        shutil.rmtree(str(work), ignore_errors=True)
        return None
    if start_detached(["cmd", "/c", str(launcher)], cwd) is None:
        shutil.rmtree(str(work), ignore_errors=True)
        return None
    pos, tail, code = 0, b"", None
    deadline = time.monotonic() + timeout
    while code is None:
        done = rc.is_file()
        if log.is_file():
            with log.open("rb") as handle:
                handle.seek(pos)
                chunk = handle.read()
            pos += len(chunk)
            *lines, tail = (tail + chunk).split(b"\n")
            for raw in lines:
                print("   " + raw.decode("utf-8", "replace").rstrip())
        if done:
            text = rc.read_text(errors="replace").strip()
            code = int(text) if text.lstrip("-").isdigit() else 1
        elif time.monotonic() > deadline:
            print("   still running after {} minutes; carrying on without it.".format(timeout // 60))
            code = 1
        else:
            time.sleep(0.25)
    if tail.strip():
        print("   " + tail.decode("utf-8", "replace").rstrip())
    shutil.rmtree(str(work), ignore_errors=True)
    return code


def mysql_login(ui, args, db_prompt, db_default):
    """(login, database): taken from the server's own worldserver.conf when it was found (automatic
    mode), else asked: the mysql client and login the first time only, kept in memory for the rest of
    the run (never saved), the database every time. (None, None) when skipped. A repack's MySQL
    only runs with its server, so its database is started first (install and uninstall alike)."""
    server = getattr(args, "server_ctl", None)
    if server:
        server.ensure_database()
    kind = "world" if "World" in db_prompt else "characters"
    conf = (getattr(args, "db", None) or {}).get(kind)
    mysql = args.mysql or shutil.which("mysql")
    if conf and mysql and Path(mysql).is_file():
        print("   using the {} login from the server's worldserver.conf ({}@{}:{}/{})".format(
            kind, conf["user"], conf["host"], conf["port"], conf["database"]))
        return dict(conf, mysql=mysql), conf["database"]
    first = ui.login is None
    if first:
        mysql = args.mysql or shutil.which("mysql")
        while not mysql or not Path(mysql).is_file():
            mysql = ui.ask("   Path to the mysql client (mysql.exe on Windows), or Enter to skip")
            if not mysql:
                return None, None
            mysql = shutil.which(mysql) or mysql
        login = {"mysql": mysql, "host": ui.ask("   MySQL host", "127.0.0.1"),
                 "port": ui.ask("   MySQL port", "3306"), "user": ui.ask("   MySQL user", "acore")}
    else:
        login = ui.login
    database = ui.ask(db_prompt, db_default)
    if first:
        login["password"] = ui.password("   Password for {}".format(login["user"]))
        ui.login = login
    return login, database


def run_sql(ui, login, database, sql_path=None, sql_bytes=None, label=None):
    """Feeds SQL (a file, or bytes) to the mysql client through a temporary option file (the password
    never shows on a command line or in a process list); returns the client's exit code."""
    if ui.dry_run:
        print("   $ \"{}\" --defaults-extra-file=<temporary file> {} < {}".format(
            login["mysql"], database, sql_path or label or "<sql>"))
        return 0
    handle, option_file = tempfile.mkstemp(suffix=".cnf", text=True)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            f.write(option_file_text(login["host"], login["port"], login["user"], login["password"]))
        return run(ui, [login["mysql"], "--defaults-extra-file=" + option_file, database],
                   stdin_bytes=sql_bytes if sql_bytes is not None else Path(sql_path).read_bytes())
    finally:
        os.remove(option_file)


def move_away(ui, target, backup_root, what):
    """Moves target (a file or folder) into backup_root. Something in use (a running server, an open
    client) cannot move on Windows: say so and wait for Enter, or s to skip. None when skipped."""
    backup = backup_root / target.name
    print("   moving {} to {}".format(what, backup))
    if ui.dry_run:
        return True
    while target.exists():
        try:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(backup))
        except PermissionError:
            reply = ui.ask("   {} is in use (still running?). Stop it, then press Enter, or s to skip".format(target))
            if reply.lower() in ("s", "skip"):
                return None
    ui.note("{} kept in {} (move it back to undo).".format(what[0].upper() + what[1:], backup))
    return True


def uninstall_classgrade_sql(install_sql):
    """The class-grade data's removal: the DELETEs shapeshift_class.sql begins with (each clears one of
    Shapeshifter's own id ranges), in one transaction, then its stance table dropped."""
    deletes = [line for line in install_sql.splitlines()
               if line.startswith("DELETE FROM") and "_stance`" not in line]
    return "\n".join(["START TRANSACTION;"] + deletes + ["COMMIT;", "DROP TABLE IF EXISTS `shapeshifter_stance`;",
                                                         "DROP TABLE IF EXISTS `shapeshift_stance`;"]) + "\n"


def replace_file(ui, source, target, backup_root, what):
    """Puts source at target, first moving the old target to backup_root. A file in use (a running
    server, an open client) cannot move on Windows: say so and wait for Enter, or s to skip."""
    if target.exists() and filecmp.cmp(source, target, shallow=False):
        print("   {} is already up to date at {}".format(what, target))
        return True
    if ui.dry_run:
        if target.exists():
            print("   backing up the old {} to {}".format(what, backup_root / target.name))
        print("   copying {} to {}".format(what, target))
        return True
    backup = backup_root / target.name
    while target.exists():
        try:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(backup))
            print("   backed up the old {} to {}".format(what, backup))
            ui.note("Old {} kept in {} (move it back to undo).".format(what, backup))
        except PermissionError:
            reply = ui.ask("   {} is in use (still running?). Stop it, then press Enter, or s to skip".format(target))
            if reply.lower() in ("s", "skip"):
                return None
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(source), str(target))
    print("   copied {} to {}".format(what, target))
    return True


def run_quiet(cmd, cwd=None):
    extra = {"creationflags": CREATE_NO_WINDOW} if WINDOWED and os.name == "nt" else {}
    try:
        result = subprocess.run(tool_command(cmd), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **extra)
    except FileNotFoundError:
        return 127, "{} is not installed on this PC.".format(Path(str(cmd[0])).name)
    return result.returncode, (result.stdout + result.stderr).decode("utf-8", "replace")


def copy_tree(ui, source, target, label, backup_root):
    """Copies a folder over target, first moving any different old copy into backup_root."""
    if same_tree(source, target):
        print("   {} is already up to date at {}".format(label, target))
        return True
    if target.exists():
        backup = backup_root / target.name
        print("   backing up the old {} to {}".format(label, backup))
        if not ui.dry_run:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(backup))
        ui.note("Old {} kept in {} (move it back to undo).".format(label, backup))
    print("   copying {} to {}".format(label, target))
    if not ui.dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(source), str(target))
    return True


# ---- paths --------------------------------------------------------------------------------------

def not_prepared_yet(ui, args):
    """A dry run whose source step only showed what it would prepare: that folder does not exist."""
    return ui.dry_run and getattr(args, "prepare_source", False) and not (args.core and Path(args.core).is_dir())


def need_core(ui, args):
    if not_prepared_yet(ui, args):
        return Path(args.core or "<the repack's prepared source>")
    while not args.core or not is_core_root(args.core):
        if args.core:
            print("   {} does not look like an AzerothCore source folder (src/server/game, modules/, "
                  "CMakeLists.txt).".format(args.core))
        args.core = ui.ask("AzerothCore source folder")
        if not args.core:
            raise Quit()
    return Path(args.core).resolve()


def need_client(ui, args):
    while not args.client or not is_client_root(args.client):
        if args.client:
            print("   {} does not look like a WoW 3.3.5a client folder (it has no Data/ next to the game)."
                  .format(args.client))
        args.client = ui.ask("WoW client folder (the one with Data/ in it)")
        if not args.client:
            raise Quit()
    return Path(args.client).resolve()


# ---- finding things by itself (automatic mode) ------------------------------------------------------

def parse_db_info(conf_text):
    """The database logins in a worldserver.conf: {"characters": {...}, "world": {...}} from its
    CharacterDatabaseInfo / WorldDatabaseInfo lines ("host;port;user;password;database")."""
    out = {}
    for line in conf_text.splitlines():
        line = line.strip()
        for key, name in (("CharacterDatabaseInfo", "characters"), ("WorldDatabaseInfo", "world")):
            if line.startswith(key) and "=" in line:
                value = line.split("=", 1)[1].strip().strip('"')
                parts = value.split(";")
                if len(parts) >= 5:
                    out[name] = {"host": parts[0], "port": parts[1], "user": parts[2],
                                 "password": ";".join(parts[3:-1]), "database": parts[-1]}
    return out


def find_conf(server_exe):
    """The worldserver.conf a server binary reads: configs/ next to it, beside it, or ../etc/."""
    exe = Path(server_exe)
    for candidate in (exe.parent / "configs" / "worldserver.conf", exe.parent / "worldserver.conf",
                      exe.parent / "etc" / "worldserver.conf", exe.parent.parent / "etc" / "worldserver.conf"):
        if candidate.is_file():
            return candidate
    return None


def repack_of(server_exe):
    """A known repack around a server binary, else None. Conquest of Azeroth (and the repacks built on
    the same kit) keep Scripts/manage.py, a bundled Python and a mysql client; its bots server has
    its own launcher (CoA-Bots/coa_bots.py)."""
    exe = Path(server_exe)
    for root in list(exe.parents)[:4]:
        manage = root / "Scripts" / "manage.py"
        if manage.is_file():
            python = root / "Runtime" / "python" / ("python.exe" if os.name == "nt" else "bin/python3")
            bots = root / "CoA-Bots" / "coa_bots.py"
            return {"root": root, "manage": manage, "python": python if python.is_file() else Path(sys.executable),
                    "bots": bots if bots.is_file() and "CoA-Bots" in exe.parts else None,
                    "mysql": root / "mysql" / "bin" / ("mysql.exe" if os.name == "nt" else "mysql")}
    return None


def list_processes(names):
    """[(pid, full path)] of running programs with one of these file names."""
    found = []
    if os.name == "nt":
        filt = " or ".join("Name='{}'".format(n) for n in names)
        script = ("Get-CimInstance Win32_Process -Filter \"{}\" | ForEach-Object {{ \"$($_.ProcessId)|"
                  "$($_.ExecutablePath)\" }}").format(filt)
        code, out = run_quiet(["powershell", "-NoProfile", "-Command", script])
        for line in out.splitlines():
            pid, _, path = line.strip().partition("|")
            if pid.isdigit() and path:
                found.append((int(pid), Path(path)))
        return found
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            path = Path(os.readlink(str(proc / "exe")))
        except OSError:
            continue
        if path.name in names:
            found.append((int(proc.name), path))
    return found


def running_at(path, names):
    """The pids of running programs whose binary is this file."""
    target = Path(path).resolve()
    return [pid for pid, exe in list_processes(names) if exe.resolve() == target]


SKIP = ("Windows", "$Recycle.Bin", "ProgramData", "AppData", "node_modules", ".git")


def scan(roots, test, depth=3, skip=SKIP, budget=15.0, first=False):
    """Folders under roots, breadth first to `depth` levels, for which test(folder) is true. Roots are
    searched one after another; first=True stops at the first find. Gives up after `budget` seconds,
    so one slow or huge disk cannot stall the installer (and the first roots, the system disk first,
    get the time before a big data disk can use it up)."""
    deadline = time.monotonic() + budget
    hits = []
    for root in roots:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        found = scan_one(Path(root), test, depth, skip, deadline)
        if first and found:
            return found[:1]
        hits += found
    return hits


def scan_one(root, test, depth, skip, deadline):
    """scan() for one root, breadth first, until the deadline."""
    hits, level = [], [root] if root.is_dir() else []
    for _ in range(depth + 1):
        following = []
        for folder in level:
            if time.monotonic() > deadline:
                return hits
            try:
                if test(folder):
                    hits.append(folder)
                    continue
                following += [c for c in folder.iterdir() if c.is_dir() and c.name not in skip]
            except (OSError, PermissionError):
                continue
        level = following
    return hits


def drive_roots():
    """The local fixed disks (removable, network and optical drives can take ages to answer)."""
    if os.name != "nt":
        return [Path.home(), Path("/opt"), Path("/srv")]
    import ctypes
    import string
    fixed = 3                                   # DRIVE_FIXED
    system = Path(os.environ.get("SystemDrive", "C:") + "\\")
    order = [system, Path("C:\\"), Path("D:\\")] + [Path("{}:\\".format(d)) for d in string.ascii_uppercase]
    roots = []
    for root in order:                          # the system drive, C: and D: first: most servers live there
        if root not in roots and ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(str(root))) == fixed:
            roots.append(root)
    return roots


def browse(ui, title, test):
    """A folder picked in a folder browser (tkinter), re-asked until test(folder) holds; None if
    cancelled or no desktop. Falls back to typing the path."""
    while True:
        folder = None
        if ui.answers is None:
            try:
                import tkinter
                from tkinter import filedialog
                root = tkinter.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                folder = filedialog.askdirectory(title=title) or None
                root.destroy()
            except Exception:
                folder = None
        if not folder:
            folder = ui.ask("   {} (a path, or Enter to skip)".format(title)) or None
        if not folder:
            return None
        if test(Path(folder)):
            return Path(folder)
        print("   {} is not it.".format(folder))


def migrate_saved_text(text, old_var, new_var):
    """The saved-variables file of the old addon name, rewritten for the new one."""
    return "\n".join((new_var + line[len(old_var):]) if line.startswith(old_var + " =") else line
                     for line in text.split("\n"))


def migrate_saved_variables(ui, client, backup_root):
    """Copies each account's and character's Shapeshift.lua to Shapeshifter.lua (favorites, chosen
    skins, flags), unless the new one exists. The old file stays where it is (the client ignores it)."""
    wtf = Path(client) / "WTF" / "Account"
    moved = 0
    for old_file, new_file, old_var, new_var in SAVED_RENAMES:
        for old in wtf.glob("**/SavedVariables/" + old_file):
            new = old.parent / new_file
            text = old.read_text(encoding="utf-8", errors="replace")
            if new.exists() or (old_var + " =") not in text:
                continue
            print("   carrying {} over to {}".format(old, new.name))
            if not ui.dry_run:
                new.write_text(migrate_saved_text(text, old_var, new_var), encoding="utf-8")
            moved += 1
    return moved


class Server:
    """The worldserver the player runs: is it up, stop it, start it (gracefully through a known
    repack's own scripts; an unknown server is closed after one warning)."""

    def __init__(self, ui, exe):
        self.ui, self.exe = ui, Path(exe)
        self.repack = repack_of(exe)
        self.stopped_by_us = False

    def running(self):
        return running_at(self.exe, (self.exe.name,))

    def stop(self):
        pids = self.running()
        if not pids:
            return True
        if self.repack:
            print("   stopping the server through the repack (graceful save and shutdown)")
            if self.ui.dry_run:
                self.stopped_by_us = True
                return True
            run(self.ui, [self.repack["python"], "-B", self.repack["manage"], "stop-all"], cwd=self.repack["root"])
        else:
            print("   {} is running (pid {}). Closing it now may lose what players did since its last".format(
                self.exe, ", ".join(str(p) for p in pids)))
            print("   save. It is started again after the install.")
            if not self.ui.confirm("   Close the server?"):
                return None
            if self.ui.dry_run:
                self.stopped_by_us = True
                return True
            for pid in pids:
                if os.name == "nt":
                    run_quiet(["taskkill", "/PID", str(pid), "/F"])
                else:
                    run_quiet(["kill", str(pid)])
        for _ in range(120):
            if not self.running():
                self.stopped_by_us = True
                print("   server stopped.")
                return True
            time.sleep(1)
        print("   the server did not stop within two minutes.")
        return False

    def ensure_database(self):
        """A repack's MySQL stops with its server: start just the database for the SQL steps."""
        if self.repack and not self.ui.dry_run:
            run(self.ui, [self.repack["python"], "-B", self.repack["manage"], "start-mysql"], cwd=self.repack["root"],
                detached=True)

    def start(self):
        print("   starting the server again")
        if self.ui.dry_run:
            return True
        if self.repack and self.repack["bots"]:
            cmd = [self.repack["python"], "-B", self.repack["bots"], "start-all"]
            return run(self.ui, cmd, cwd=self.repack["bots"].parent, detached=True) == 0
        if self.repack:
            return run(self.ui, [self.repack["python"], "-B", self.repack["manage"], "start-all"],
                       cwd=self.repack["root"], detached=True) == 0
        if start_detached([str(self.exe)], str(self.exe.parent), show=True) is None:
            flags = {"creationflags": CREATE_NEW_CONSOLE} if os.name == "nt" else {"start_new_session": True}
            subprocess.Popen([str(self.exe)], cwd=str(self.exe.parent), **flags)
        return True


def looks_like_build(folder):
    if not (Path(folder) / "CMakeCache.txt").is_file():
        return False
    home = read_cmake_cache(folder).get("CMAKE_HOME_DIRECTORY")
    return bool(home) and is_core_root(home)


def same_binary(a, b):
    a, b = Path(a), Path(b)
    return a.is_file() and b.is_file() and a.stat().st_size == b.stat().st_size and filecmp.cmp(a, b, shallow=False)


def server_build(candidates, server_exe):
    """The candidate build folder whose worldserver is byte-identical to the one the server runs."""
    if not server_exe:
        return None
    for build in candidates:
        for config in ("RelWithDebInfo", "Release", "Debug", "MinSizeRel"):
            built = find_built(build, config)
            if built and same_binary(built, server_exe):
                return Path(build)
    return None


def pick_build(ui, candidates, server_exe):
    """The build folder behind the running server: the one whose worldserver is byte-identical to it
    (a PC may hold several AzerothCore trees). Else the only candidate, else the player picks."""
    candidates = list(dict.fromkeys(Path(c) for c in candidates))
    if server_exe:
        for build in candidates:
            for config in ("RelWithDebInfo", "Release", "Debug", "MinSizeRel"):
                built = find_built(build, config)
                if built and same_binary(built, server_exe):
                    return build
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        return None
    listing = "".join("\n     {}. {} (source {})".format(i, build, read_cmake_cache(build).get("CMAKE_HOME_DIRECTORY"))
                      for i, build in enumerate(candidates, 1))
    reply = ui.ask("   None of these build folders built the server you run. After a repack update, use the"
                   " repack's new source, or the old core replaces the new server.{}\n   Which one (number, or"
                   " Enter to browse)".format(listing))
    return candidates[int(reply) - 1] if reply.isdigit() and 0 < int(reply) <= len(candidates) else None


def server_kind(exe):
    """0 for Conquest of Azeroth's CoA-Bots server, 1 for a repack's own server, 2 for any other."""
    repack = repack_of(exe)
    return 0 if repack and repack["bots"] else 1 if repack else 2


def rank_servers(running, found):
    """Every server once, in the order they are offered: the CoA-Bots server, then the repack's own,
    then the rest; a running one before a stopped one of the same kind."""
    servers, seen = [], set()
    for exe in list(running) + list(found):
        key = os.path.normcase(str(Path(exe).resolve()))
        if key not in seen:
            seen.add(key)
            servers.append(Path(exe))
    live = {os.path.normcase(str(Path(exe).resolve())) for exe in running}
    return sorted(servers, key=lambda exe: (server_kind(exe), os.path.normcase(str(exe.resolve())) not in live))


def pick_server(ui, servers, running=()):
    """The server Shapeshifter goes into: the only one, else the player picks from the list (Enter
    takes the first, the CoA-Bots server when there is one)."""
    if len(servers) < 2:
        return servers[0] if servers else None
    live = {os.path.normcase(str(Path(exe).resolve())) for exe in running}
    labels = ("CoA-Bots server", "Conquest of Azeroth server", "")
    listing = ""
    for i, exe in enumerate(servers, 1):
        tags = [t for t in (labels[server_kind(exe)],
                            "running" if os.path.normcase(str(exe.resolve())) in live else "") if t]
        listing += "\n     {}. {}{}".format(i, exe, " ({})".format(", ".join(tags)) if tags else "")
    try:
        reply = ui.ask("   This PC has {} servers. Which one gets Shapeshifter?{}\n   Its number".format(
            len(servers), listing), "1")
    except Quit:
        reply = "1"
    return servers[int(reply) - 1] if reply.isdigit() and 0 < int(reply) <= len(servers) else servers[0]


def discover(ui, args, ask_missing=True):
    """Fills in every path it can find: the worldserver (asked when the PC has several), the core and build
    folders, the client, the mysql client and the database logins. Returns the Server, if any.
    ask_missing=False: leave what it cannot find empty (the setup window has Browse buttons)."""
    print("\nSearching...")
    roots = drive_roots()
    if not args.server:
        running = [exe for _, exe in list_processes((WORLDSERVER,))]
        found = scan(roots, lambda f: (f / WORLDSERVER).is_file() and find_conf(f / WORLDSERVER) is not None, depth=4,
                     skip=SKIP + ("Program Files", "Program Files (x86)"))
        server = pick_server(ui, rank_servers(running, [f / WORLDSERVER for f in found]), running)
        args.server = str(server) if server else None
    repack = repack_of(args.server) if args.server else None
    if not args.build:
        near = [Path(args.core) / "build"] if args.core else []
        if repack:                              # what an earlier run prepared from the repack's source
            near.append(repack["root"] / "Source" / "shapeshifter-build")
        home = Path.home()
        hits = [p for p in near if looks_like_build(p)]
        places = [[home / "Desktop", home / "Documents", home / "source", home / "Projects"]] + [[r] for r in roots]
        fallback = bool(repack and (repack["root"] / "Source" / "server-source.zip").is_file())
        for place in places:                    # stop as soon as the running server's build turns up
            if server_build(hits, args.server) or (fallback and hits):
                break                           # (with the repack's own source to fall back on, any build
            hits += scan(place, looks_like_build, depth=2)      # found is enough: it only lends settings)
        build = server_build(hits, args.server)
        zip_path = repack["root"] / "Source" / "server-source.zip" if repack else None
        newest = max(hits, key=lambda h: (Path(h) / "CMakeCache.txt").stat().st_mtime) if hits else None
        args.seed = read_cmake_cache(newest) if newest else {}      # the build most recently configured here
        if not build and zip_path and zip_path.is_file():
            args.prepare_source = True           # step "source" unpacks, fetches and configures it
        else:
            build = build or pick_build(ui, hits, args.server)
        if build:
            args.build = str(build)
    if not getattr(args, "prepare_source", False):
        args.prepare_source = False
    if repack and getattr(args, "bots", None) is None:
        args.bots = bool(repack["bots"])        # the setup window's CoA-Bots box
    if args.build and not args.core:
        args.core = core_of_build(args.build)
    if not args.client:
        games = list_processes(GAME_EXES)
        if games:
            args.client = str(games[0][1].parent)
        else:
            where = [repack["root"].parent] if repack else []
            hits = scan(where + roots, is_client_root, depth=3, first=True)
            if hits:
                args.client = str(hits[0])
    if not args.mysql:
        if repack and repack["mysql"].is_file():
            args.mysql = str(repack["mysql"])
        elif shutil.which("mysql"):
            args.mysql = shutil.which("mysql")
        else:
            hits = scan([Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "MySQL"],
                        lambda f: (f / "bin" / ("mysql.exe" if os.name == "nt" else "mysql")).is_file(), depth=2)
            if hits:
                args.mysql = str(hits[0] / "bin" / ("mysql.exe" if os.name == "nt" else "mysql"))
    if not ask_missing:
        conf = find_conf(args.server) if args.server else None
        args.db = parse_db_info(conf.read_text(encoding="utf-8", errors="replace")) if conf else {}
        return Server(ui, args.server) if args.server and Path(args.server).is_file() else None
    # Anything still missing: a folder browser (the source is not missing when it is to be prepared).
    if not args.prepare_source and (not args.core or not is_core_root(args.core)):
        found = browse(ui, "Where is your AzerothCore source folder (it holds src/ and modules/)?", is_core_root)
        args.core = str(found) if found else None
    if not args.prepare_source and args.core and (not args.build or not read_cmake_cache(args.build)):
        found = browse(ui, "Where is its build folder (it holds CMakeCache.txt)?", lambda f: bool(read_cmake_cache(f)))
        args.build = str(found) if found else None
    if not args.server or not Path(args.server).is_file():
        found = browse(ui, "Where is the worldserver your server runs (its folder)?",
                       lambda f: (f / WORLDSERVER).is_file())
        args.server = str(found / WORLDSERVER) if found else None
    if not args.client or not is_client_root(args.client):
        found = browse(ui, "Where is your game client (the folder with Data/ in it)?", is_client_root)
        args.client = str(found) if found else None
    conf = find_conf(args.server) if args.server else None
    args.db = parse_db_info(conf.read_text(encoding="utf-8", errors="replace")) if conf else {}
    return Server(ui, args.server) if args.server else None


def show_found(args, server):
    if getattr(args, "prepare_source", False):
        prepared = "prepared from the repack's Source/server-source.zip{}".format(
            " + mod-playerbots (CoA-Bots server)" if getattr(args, "bots", False) else "")
        rows = (("Core source", prepared), ("Build folder", "a new one next to it"))
    else:
        rows = (("Core source", args.core), ("Build folder", args.build))
    rows = rows + (("Server", args.server),
            ("Game client", args.client), ("mysql client", args.mysql),
            ("Database login", "from {}".format(find_conf(args.server)) if args.db else None),
            ("Server control", ("the repack's own scripts" if server.repack else "close and restart it")
             if server else None))
    for label, value in rows:
        print("   {:16} {}".format(label, value or "NOT FOUND (that step is skipped)"))
    for line in build_readiness(args):
        print("   " + line)


# ---- preparing a repack's own source -----------------------------------------------------------------
# A repack update brings a new prebuilt server; Shapeshifter has to be compiled into that same core.
# The repack ships its core as Source/server-source.zip; the CoA-Bots add-on's server is that core plus
# mod-playerbots, whose repository and exact revision CoA-Bots records (README.md, release.json).
PLAYERBOTS_FALLBACK = {"url": "https://github.com/Zyth45/mod-playerbots", "branch": "coa"}
SEED_KEYS = ("BOOST_ROOT", "Boost_INCLUDE_DIR", "OPENSSL_ROOT_DIR", "OPENSSL_INCLUDE_DIR", "MYSQL_INCLUDE_DIR",
             "MYSQL_LIBRARY", "MYSQL_EXECUTABLE", "CMAKE_TOOLCHAIN_FILE", "SCRIPTS", "MODULES", "APPS_BUILD",
             "TOOLS_BUILD")


def bots_source(repack_root):
    """{url, branch, revision} of the mod-playerbots the CoA-Bots server was built from, or None."""
    import json
    import re
    bots = Path(repack_root) / "CoA-Bots"
    if not bots.is_dir():
        return None
    out = dict(PLAYERBOTS_FALLBACK, revision=None)
    readme = bots / "README.md"
    if readme.is_file():
        match = re.search(r"the bots at (https://github\.com/[\w.-]+/[\w.-]+) \(branch `([^`]+)`\)",
                          readme.read_text(encoding="utf-8", errors="replace"))
        if match:
            out["url"], out["branch"] = match.group(1), match.group(2)
    release = bots / "release.json"
    if release.is_file():
        try:
            out["revision"] = json.loads(release.read_text(encoding="utf-8")).get("botsModuleRevision")
        except ValueError:
            pass
    return out


# ---- the build tools (1.1.0) -------------------------------------------------------------------------
# Shapeshifter is compiled into the server, which needs Git, CMake, Visual Studio's C++ tools, Boost,
# OpenSSL and the MySQL client library. A player who downloaded a repack has none of them. Setup finds
# the ones this PC has, lists the rest (each with its download page) and, for the ones the player
# ticks, downloads and installs them: nothing is bundled with Shapeshifter.
BOOST_VERSION = "1.81.0"                   # the Boost the CoA repack's server builds with
MYSQL_VERSION = "8.4.9"                    # the MySQL client the CoA repack ships (a match avoids ACE00046)
LOCAL = Path(os.environ.get("SystemDrive", "C:") + "\\") / "local"   # where Boost and MySQL go (no admin needed)
ORIGINAL = "shapeshifter-original"     # beside the server: the repack's own worldserver, kept for uninstall
ORIGINAL_FILES = (WORLDSERVER, "libmysql.dll", "worldserver.pdb")
MYSQL_WANTED = None                        # the MySQL client version this run's build must use (aim_mysql)


def mysql_target():
    """The MySQL client version Setup installs: the repack's (aim_mysql), else MYSQL_VERSION."""
    return MYSQL_WANTED or MYSQL_VERSION


def mysql_header_version(include):
    """The client version ("8.4.9") a MySQL include folder declares (mysql_version.h), or None."""
    try:
        text = (Path(include) / "mysql_version.h").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r'#define\s+LIBMYSQL_VERSION\s+"([\d.]+)"', text)
    return match.group(1) if match else None


def dll_version_text(path):
    """"8.4.9" for a DLL whose file version is 8.4.9.0, or None."""
    version = file_version(path) if Path(path).is_file() else (0,)
    return ".".join(str(n) for n in version[:3]) if version[0] else None


def aim_mysql(args):
    """A server compiled from a repack's source must use the MySQL client the repack ships: CoA-Bots
    copies the repack's Core\\libmysql.dll over its own at every start (when the sizes differ), and a
    worldserver behind a client DLL of another version stops at startup (ACE00046). Sets and returns
    MYSQL_WANTED (None: any MySQL will do)."""
    global MYSQL_WANTED
    repack = repack_of(args.server) if getattr(args, "prepare_source", False) and getattr(args, "server", None) \
        else None
    MYSQL_WANTED = dll_version_text(repack["root"] / "Core" / "libmysql.dll") if repack else None
    return MYSQL_WANTED


def boost_root(seed=None):
    """A Boost with its compiled libraries: the seed build's, BOOST_ROOT, or one under C:\\local."""
    for candidate in ((seed or {}).get("BOOST_ROOT"), os.environ.get("BOOST_ROOT")):
        if candidate and (Path(candidate) / "boost" / "version.hpp").is_file():
            return Path(candidate)
    found = sorted(p for p in LOCAL.glob("boost_*") if (p / "boost" / "version.hpp").is_file())
    return found[-1] if found else None


def openssl_root(seed=None):
    """An OpenSSL with headers and import libraries (the full installer, not Light)."""
    programs = Path(os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles", r"C:\Program Files"))
    for candidate in ((seed or {}).get("OPENSSL_ROOT_DIR"), os.environ.get("OPENSSL_ROOT_DIR"),
                      programs / "OpenSSL-Win64", programs / "OpenSSL"):
        if candidate and (Path(candidate) / "include" / "openssl" / "ssl.h").is_file():
            return Path(candidate)
    return None


def mysql_dev(seed=None):
    """(include folder, libmysql.lib) of a MySQL with its client library, or None. With MYSQL_WANTED
    set (aim_mysql), only that exact client version counts."""
    def fits(include):
        return not MYSQL_WANTED or mysql_header_version(include) == MYSQL_WANTED
    seed = seed or {}
    if seed.get("MYSQL_INCLUDE_DIR") and Path(seed.get("MYSQL_LIBRARY", "")).is_file() \
            and fits(seed["MYSQL_INCLUDE_DIR"]):
        return Path(seed["MYSQL_INCLUDE_DIR"]), Path(seed["MYSQL_LIBRARY"])
    programs = Path(os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles", r"C:\Program Files"))
    for root in sorted(LOCAL.glob("mysql-*"), reverse=True) + sorted(programs.glob("MySQL/MySQL Server *"),
                                                                     reverse=True):
        if (root / "include" / "mysql.h").is_file() and (root / "lib" / "libmysql.lib").is_file() \
                and fits(root / "include"):
            return root / "include", root / "lib" / "libmysql.lib"
    return None


def has_cpp_compiler():
    return any((vs / "VC" / "Tools" / "MSVC").is_dir() for vs in visual_studios())


# key, name, what it is for, download page, how Setup installs it: ("winget", id, extra args) or
# ("download", url, kind) with kind "inno" (a silent installer into C:\local) or "zip" (unpacked there).
BUILD_TOOLS = (
    ("git", "Git", "applies the core patches, fetches mod-playerbots", "https://git-scm.com/download/win",
     ("winget", "Git.Git", [])),
    ("cmake", "CMake", "configures the build", "https://cmake.org/download/",
     ("winget", "Kitware.CMake", [])),
    ("vs", "Visual Studio Build Tools (C++)", "the compiler; about 3 to 6 GB",
     "https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022",
     ("winget", "Microsoft.VisualStudio.2022.BuildTools",
      ["--override", "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"])),
    ("boost", "Boost " + BOOST_VERSION, "C++ libraries the core uses; about 200 MB",
     "https://sourceforge.net/projects/boost/files/boost-binaries/" + BOOST_VERSION + "/",
     ("download", "https://downloads.sourceforge.net/project/boost/boost-binaries/{v}/boost_{u}-msvc-14.3-64.exe"
      .format(v=BOOST_VERSION, u=BOOST_VERSION.replace(".", "_")), "inno")),
    ("openssl", "OpenSSL (full, not Light)", "encryption for logins", "https://slproweb.com/products/Win32OpenSSL.html",
     ("winget", "ShiningLight.OpenSSL.Dev", [])),
    ("mysql", "MySQL {v} client library", "the database connection; about 280 MB, no service",
     "https://dev.mysql.com/downloads/mysql/",
     ("download", ("https://cdn.mysql.com/archives/mysql-{mm}/mysql-{v}-winx64.zip",
                   "https://cdn.mysql.com/Downloads/MySQL-{mm}/mysql-{v}-winx64.zip"), "zip")),
)


def tool_spec(key):
    """A BUILD_TOOLS entry with the MySQL version filled in (mysql_target)."""
    spec = next(t for t in BUILD_TOOLS if t[0] == key)
    if key != "mysql":
        return spec
    v = mysql_target()
    mm = ".".join(v.split(".")[:2])
    how = spec[4]
    return (key, spec[1].format(v=v), spec[2], spec[3],
            (how[0], tuple(u.format(v=v, mm=mm) for u in how[1]), how[2]))


def tool_present(key, seed=None):
    """True when this PC has the tool (a build already configured here proves the compiler and libraries)."""
    seed = seed or {}
    if key in ("git", "cmake"):
        return find_tool(key) is not None
    if os.name != "nt":
        return True
    if key == "vs":
        return bool(seed.get("CMAKE_GENERATOR")) or has_cpp_compiler()
    if key == "boost":
        return boost_root(seed) is not None
    if key == "openssl":
        return openssl_root(seed) is not None or bool(seed.get("OPENSSL_INCLUDE_DIR"))
    if key == "mysql":
        return mysql_dev(seed) is not None
    return True


def missing_build_tools(seed=None):
    """[(key, name, why, page)] of the build tools this PC lacks."""
    return [(key, name, why, page) for key, name, why, page, _ in (tool_spec(t[0]) for t in BUILD_TOOLS)
            if not tool_present(key, seed)]


def found_dev_flags(seed=None):
    """-D flags pointing CMake at the Boost, OpenSSL and MySQL found here (Setup's own installs live
    where CMake does not look by itself)."""
    flags = []
    boost, openssl, mysql = boost_root(seed), openssl_root(seed), mysql_dev(seed)
    if boost:
        flags.append("-DBOOST_ROOT=" + boost.as_posix())
    if openssl:
        flags.append("-DOPENSSL_ROOT_DIR=" + openssl.as_posix())
    if mysql:
        flags += ["-DMYSQL_INCLUDE_DIR=" + mysql[0].as_posix(), "-DMYSQL_LIBRARY=" + mysql[1].as_posix()]
    return flags


def has_winget():
    return os.name == "nt" and run_quiet(["winget", "--version"])[0] == 0


def download(url, target):
    """Downloads url to target, printing progress every 10%."""
    request = urllib.request.Request(url, headers={"User-Agent": "Shapeshifter-Setup/" + VERSION})
    with urllib.request.urlopen(request, timeout=120) as response, open(str(target), "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done, shown = 0, -1
        for block in iter(lambda: response.read(1 << 20), b""):
            out.write(block)
            done += len(block)
            if total and done * 10 // total != shown:
                shown = done * 10 // total
                print("   {:.0f} of {:.0f} MB".format(done / 1e6, total / 1e6))


def install_tool(ui, key):
    """Downloads and installs one build tool. True when it is there afterwards. Windows asks for
    administrator rights for the ones that install for every user."""
    _, name, _, page, how = tool_spec(key)
    print("\n   installing {}".format(name))
    if ui.dry_run:
        print("   (dry run) would install it")
        return True
    if how[0] == "winget":
        if not has_winget():
            print("   Windows' package manager (winget) is not on this PC: install {} from {}".format(name, page))
            return False
        run(ui, ["winget", "install", "--exact", "--id", how[1], "--silent", "--accept-package-agreements",
                 "--accept-source-agreements", "--disable-interactivity"] + how[2])
    else:
        urls, kind = (how[1] if isinstance(how[1], tuple) else (how[1],)), how[2]
        work = Path(tempfile.mkdtemp(prefix="shapeshifter-tool-"))
        try:
            file = work / urls[0].rsplit("/", 1)[-1]
            for i, url in enumerate(urls):      # a MySQL release is in the archive, or (while current) not yet
                print("   downloading {}".format(url))
                try:
                    download(url, file)
                    break
                except (urllib.error.URLError, OSError) as error:
                    if i + 1 == len(urls):
                        print("   the download failed ({}). Get it from {}".format(
                            getattr(error, "reason", error), page))
                        return False
            if kind == "zip":
                print("   unpacking into {}".format(LOCAL))
                LOCAL.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(str(file)) as archive:
                    archive.extractall(str(LOCAL))
            else:
                target = LOCAL / ("boost_" + BOOST_VERSION.replace(".", "_"))
                print("   running its installer into {} (Windows may ask for administrator rights; its progress window".format(target))
                print("   shows while it unpacks about 1.5 GB, which takes a few minutes)")
                run_elevated(file, ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/DIR=" + str(target)])
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    _found_tools.clear()                  # a new install may be on PATH now
    present = tool_present(key)
    print("   {} {}.".format(name, "is installed" if present else "is still missing; get it from " + page))
    return present


def run_elevated(exe, arguments):
    """Runs an installer that needs administrator rights (Windows shows its UAC prompt) and waits."""
    def quote(text):
        return "'" + str(text).replace("'", "''") + "'"
    script = "Start-Process -FilePath {} -ArgumentList {} -Verb RunAs -Wait".format(
        quote(exe), ",".join(quote(a) for a in arguments))
    return run_quiet(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])[0]


def repack_release(root):
    """The repack's release id (RELEASE.json releaseId, e.g. main-20260925-6557290fd), or None."""
    try:
        return json.loads((Path(root) / "RELEASE.json").read_text(encoding="utf-8-sig")).get("releaseId")
    except (OSError, ValueError, AttributeError):
        return None


def file_sha256(path):
    digest = hashlib.sha256()
    with open(str(path), "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stock_hashes(repack_root):
    """SHA-256s of the worldservers the repack and its CoA-Bots add-on ship (lower case)."""
    root, hashes = Path(repack_root), set()
    try:
        release = json.loads((root / "RELEASE.json").read_text(encoding="utf-8-sig"))
        hashes |= {b.get("SHA256", "").lower() for b in release.get("binaries", []) if b.get("Name") == WORLDSERVER}
    except (OSError, ValueError, AttributeError):
        pass
    try:
        bots = json.loads((root / "CoA-Bots" / "release.json").read_text(encoding="utf-8-sig"))
        hashes |= {h.lower() for key in ("originalWorldserverSha256", "patchedWorldserverSha256")
                   for h in bots.get(key, [])}
    except (OSError, ValueError, AttributeError):
        pass
    return hashes - {""}


def keep_original(ui, target):
    """Before the first Shapeshifter worldserver goes in: a copy of the repack's own (and its MySQL DLL
    and symbols) in shapeshifter-original/ beside it, so an uninstall puts it back without a compiler.
    Only a worldserver the repack itself shipped is kept (a repack update refreshes the copy)."""
    target = Path(target)
    repack = repack_of(target)
    if not repack or not target.is_file() or file_sha256(target) not in stock_hashes(repack["root"]):
        return
    keep = target.parent / ORIGINAL
    if same_binary(target, keep / WORLDSERVER):
        return
    print("   keeping the repack's own worldserver in {} (the uninstall puts it back)".format(keep))
    if ui.dry_run:
        return
    keep.mkdir(exist_ok=True)
    for name in ORIGINAL_FILES:
        if (target.parent / name).is_file():
            shutil.copy2(str(target.parent / name), str(keep / name))
        elif (keep / name).exists():
            (keep / name).unlink()


def restoring(args):
    """An uninstall on a PC with no build folder of its own (the server was compiled from the repack's
    source): the repack's own worldserver kept by the install goes back, no compile needed."""
    server = getattr(args, "server", None)
    return bool(server and getattr(args, "prepare_source", False)
                and (Path(server).parent / ORIGINAL / WORLDSERVER).is_file())


def build_seed(args):
    """The configured build that proves which tools this PC has: the chosen build folder, else the one
    most recently configured here."""
    cache = read_cmake_cache(args.build) if getattr(args, "build", None) else {}
    return cache or getattr(args, "seed", None) or {}


def required_tools_missing(args):
    """[(key, name, why, page)] of the build tools this run needs and this PC lacks. The install (and
    an uninstall that rebuilds) compiles the server; an uninstall that puts the repack's own server
    back does not."""
    if getattr(args, "uninstall", False) and restoring(args):
        return []
    if not getattr(args, "prepare_source", False) and not getattr(args, "build", None):
        return []
    aim_mysql(args)
    return missing_build_tools(build_seed(args))


def build_readiness(args):
    """Lines saying up front what this install is missing on this PC. Empty when it can go ahead."""
    if not getattr(args, "prepare_source", False) and not getattr(args, "build", None):
        if not getattr(args, "server", None) or getattr(args, "uninstall", False):
            return []
        return ["No AzerothCore source or build folder was found for this server. Shapeshifter is compiled",
                "into the server, so it needs the source your server was built from: Browse to it and its",
                "build folder (the one with CMakeCache.txt), or ask the repack's maker for the source."]
    missing = required_tools_missing(args)
    if not missing:
        return []
    lines = ["Shapeshifter is compiled into your server. Before it can install, this PC needs these build tools:"]
    lines += ["  - {} ({}): {}".format(name, why, page) for _, name, why, page in missing]
    return lines


def acquire_tools(ui, args):
    """Console: before anything is installed, the missing build tools are listed with their pages and,
    on yes, downloaded and installed. True when none is missing afterwards."""
    missing = required_tools_missing(args)
    if not missing:
        return True                       # (show_found listed them with their pages just above)
    if ui.ask("\nDownload and install the missing build tools now? [Y/n]").lower() in ("", "y", "yes"):
        for key, _, _, _ in missing:
            install_tool(ui, key)
    still = required_tools_missing(args)
    if still:
        print("\nShapeshifter cannot install until these are on this PC: {}.".format(
            ", ".join(name for _, name, _, _ in still)))
        print("Install them from the pages above (restart the PC after Visual Studio), then run Setup again.")
        return False
    return True


def seed_flags(cache):
    """CMake flags that let a fresh tree configure like a build already on this PC: the same generator
    and platform, and where Boost, OpenSSL and MySQL were found."""
    flags = []
    if cache.get("CMAKE_GENERATOR"):
        flags += ["-G", cache["CMAKE_GENERATOR"]]
    if cache.get("CMAKE_GENERATOR_PLATFORM"):
        flags += ["-A", cache["CMAKE_GENERATOR_PLATFORM"]]
    flags += ["-D{}={}".format(k, cache[k]) for k in SEED_KEYS if cache.get(k)]
    if not any(f.startswith("-DSCRIPTS=") for f in flags):
        flags += ["-DSCRIPTS=static", "-DMODULES=static", "-DTOOLS_BUILD=none"]
    return flags


def unpack_source(ui, zip_path, target):
    """Unpacks the repack's source zip into target (its top folder dropped), once per zip."""
    import json
    import zipfile
    stamp_file = target / ".shapeshifter-source.json"
    zstat = zip_path.stat()
    wanted = {"zip": str(zip_path), "size": zstat.st_size, "mtime": int(zstat.st_mtime)}
    if stamp_file.is_file():
        try:
            if json.loads(stamp_file.read_text(encoding="utf-8")) == wanted:
                print("   the repack's source is already unpacked at {}".format(target))
                return True
        except ValueError:
            pass
    print("   unpacking {} to {} (a few minutes)".format(zip_path, target))
    if ui.dry_run:
        return True
    if target.exists():
        move_away(ui, target, BACKUPS / stamp() / "old-source", "the previous unpacked source")
    with zipfile.ZipFile(str(zip_path)) as archive:
        for item in archive.infolist():
            parts = item.filename.split("/", 1)
            if len(parts) < 2 or not parts[1]:
                continue
            out = target / parts[1]
            if item.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as src, open(str(out), "wb") as dst:
                shutil.copyfileobj(src, dst)
    stamp_file.write_text(json.dumps(wanted), encoding="utf-8")
    return True


def ensure_build_tools(ui, args):
    """Installs the build tools this PC lacks that the player chose (args.install_tools: the window's
    checklist; asked here otherwise), then checks again. False, with nothing changed, when any is
    still missing."""
    aim_mysql(args)
    seed = build_seed(args)
    missing = missing_build_tools(seed)
    if not missing:
        return True
    print("   This PC is missing build tools:")
    for _, name, why, page in missing:
        print("     - {} ({}): {}".format(name, why, page))
    chosen = getattr(args, "install_tools", None)
    if chosen is None:
        chosen = [m[0] for m in missing] if ui.confirm("   Download and install them now?") else []
    for key, _, _, _ in missing:
        if key in chosen:
            install_tool(ui, key)
    still = [] if ui.dry_run else missing_build_tools(seed)
    if still:
        print("\n   Still missing: {}.".format(", ".join(name for _, name, _, _ in still)))
        print("   Nothing on your server was changed. Install them from the pages above (a PC restart may be")
        print("   needed after Visual Studio), then start Setup again.")
        return False
    return True


def step_source(ui, args):
    ui.step("0. The repack's own source", [
        "No build folder on this PC made the server you run (a fresh repack, or a repack update), so",
        "Shapeshifter is compiled into the repack's own core: the build tools this PC lacks are installed",
        "first (the ones you ticked), then its Source/server-source.zip is unpacked and configured as a",
        "Release build; for the CoA-Bots server, mod-playerbots is fetched at the revision CoA-Bots was",
        "built from.",
    ])
    if not getattr(args, "prepare_source", False):
        print("   not needed: {} built the server you run.".format(args.build))
        return True
    repack = repack_of(args.server) if args.server else None
    zip_path = repack["root"] / "Source" / "server-source.zip" if repack else None
    if not zip_path or not zip_path.is_file():
        print("   the server is not a repack that ships its source; pick your source and build folders instead.")
        return None
    if not ensure_build_tools(ui, args):
        return False
    source = zip_path.parent / "shapeshifter-source"
    build = zip_path.parent / "shapeshifter-build"
    if not unpack_source(ui, zip_path, source):
        return False
    if getattr(args, "bots", False):
        info = bots_source(repack["root"]) or dict(PLAYERBOTS_FALLBACK, revision=None)
        dest = source / "modules" / "mod-playerbots"
        if not dest.exists():
            print("   fetching mod-playerbots ({} branch {})".format(info["url"], info["branch"]))
            if run(ui, ["git", "clone", "-c", "core.longpaths=true", "--branch", info["branch"], info["url"],
                        dest]) != 0:
                print("   the download failed (internet connection?).")
                return False
        if info.get("revision") and run(ui, ["git", "checkout", info["revision"]], cwd=dest) != 0:
            print("   revision {} is not in that repository.".format(info["revision"]))
            return False
    print("   configuring {} (like the build already on this PC, Release)".format(build))
    seed = getattr(args, "seed", None) or {}
    flags = seed_flags(seed)
    if aim_mysql(args):                 # the repack's MySQL client, whichever one the seed build used
        print("   building against MySQL {}, the client the repack ships".format(MYSQL_WANTED))
        flags = [f for f in flags if not f.startswith(("-DMYSQL_INCLUDE_DIR=", "-DMYSQL_LIBRARY="))]
    flags += [f for f in found_dev_flags(seed) if not any(g.split("=")[0] == f.split("=")[0] for g in flags)]
    flags.append("-DCMAKE_BUILD_TYPE=Release")
    if run(ui, ["cmake", "-S", source, "-B", build] + flags) != 0:
        print("   CMake could not configure the repack's source. Building AzerothCore needs Visual Studio,")
        print("   CMake, Boost, OpenSSL and the MySQL libraries (see the AzerothCore install guide).")
        return False
    args.core, args.build = str(source), str(build)
    args.config = getattr(args, "config", None) or "Release"
    return True


# ---- the steps ----------------------------------------------------------------------------------

def step_patches(ui, args):
    ui.step("1. Core patches", [
        "mod-shapeshifter needs one small change to the core (name override) and can use two more",
        "(form weapons, form speed). They are applied with git apply, checked first with --check;",
        "a patch that is already in your source is left alone.",
    ])
    if not find_tool("git"):
        print("   Git is not installed on this PC (https://git-scm.com/download/win). Install it and start")
        print("   Setup again, or apply the files in patches/ by hand.")
        return False
    core = need_core(ui, args)
    if not_prepared_yet(ui, args):
        for name, _, _, _ in PATCH_PLAN:
            print("   (dry run) would apply {} to the prepared source".format(name))
        return True
    chosen = []
    unchecked = set()      # on a dry run: patches not really applied, so what stacks on them cannot be checked
    for name, required, need, what in PATCH_PLAN:
        patch = PATCHES / name
        print("\n   {}: {}".format(name, what))
        if need and need not in chosen:
            print("   skipped: it needs {}.".format(need))
            continue
        if patch_applied(core, name):
            lack = []
            if run_quiet(["git", "apply", "-R", "--check", patch], cwd=core)[0] != 0:
                lack = split_patch_files(core, patch)[1]
            if not lack:
                print("   already applied.")
                chosen.append(name)
                continue
            print("   only partly applied (a run that stopped half way?): adding it to {}".format(", ".join(lack)))
            if run(ui, ["git", "apply"] + ["--include=" + rel for rel in lack] + [patch], cwd=core) != 0:
                print("   git apply failed.")
                return False
            chosen.append(name)
            continue
        if not ui.confirm("   Apply {}?".format(name)):
            if required:
                print("   Not applied: the module will not build until it is.")
                return None
            continue
        if need in unchecked:
            print("   (dry run: it can only be checked once {} is really applied)".format(need))
            print("   $ git apply " + str(patch))
            chosen.append(name)
            unchecked.add(name)
            continue
        code, out = run_quiet(["git", "apply", "--check", patch], cwd=core)
        if code != 0:
            print("   it does not apply cleanly to this source (made against AzerothCore rev b3717c137710):")
            print("   " + out.strip().replace("\n", "\n   "))
            if required:
                print("   The module cannot build without it. Rebase the patch onto your core, then run this again.")
                return False
            continue
        if run(ui, ["git", "apply", patch], cwd=core) != 0:
            print("   git apply failed.")
            return False
        chosen.append(name)
        if ui.dry_run:
            unchecked.add(name)
        ui.note("Undo {}: cd \"{}\" && git apply -R \"{}\"".format(name, core, patch))
    return patch_order_ok(chosen)


def step_module(ui, args):
    ui.step("2. Server module", [
        "Copies module/mod-shapeshifter into your core's modules/ folder, where CMake picks it up.",
        "An older copy there (also one under the old name mod-shapeshift) goes to backups/ first.",
    ])
    core = need_core(ui, args)
    if not ui.confirm("   Copy the module?"):
        return None
    old = core / "modules" / OLD_MODULE
    if old.exists() and move_away(ui, old, BACKUPS / args.stamp / "old-name", "the old mod-shapeshift") is None:
        return False
    return copy_tree(ui, MODULE, core / "modules" / "mod-shapeshifter", "module", BACKUPS / args.stamp)


def server_code_hash():
    """What a worldserver build compiles from this copy: the module and the core patches (line
    endings ignored, so a checkout with other line endings is the same code)."""
    digest = hashlib.sha256()
    for root in (MODULE, PATCHES):
        root = Path(root)
        for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
            digest.update("{}/{}\0".format(root.name, path.relative_to(root).as_posix()).encode("utf-8"))
            digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def write_build_stamp(build):
    (Path(build) / BUILD_STAMP).write_text(json.dumps({"code": server_code_hash(), "version": VERSION}),
                                           encoding="utf-8")


def build_is_current(build, config, server_exe):
    """True when the last build compiled this copy's server code and the server runs what it made:
    an update that changes only the addon or data needs no rebuild."""
    try:
        stamp_data = json.loads((Path(build) / BUILD_STAMP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    built = find_built(build, config)
    if not built or not isinstance(stamp_data, dict) or stamp_data.get("code") != server_code_hash():
        return False
    return server_exe is None or same_binary(built, server_exe)


def step_build(ui, args):
    ui.step("3. Build the worldserver", [
        "Stops a running server first (a worldserver full of bots takes the CPU the compilers need),",
        "re-runs CMake's configure step (the name patch adds source files, the module is found at",
        "configure time), then builds the worldserver target. The Player.h patches mean most of",
        "the core recompiles: expect anything from ten minutes to an hour.",
    ])
    if puts_original_back(args):
        return True
    if not find_tool("cmake"):
        print("   CMake is not installed on this PC (https://cmake.org/download/). Install it and start")
        print("   Setup again, or build the core the way you normally do.")
        return False
    core = need_core(ui, args)
    if not_prepared_yet(ui, args):
        print("   (dry run) would configure and build the prepared source (below normal priority)")
        return True
    build = Path(args.build) if args.build else core / "build"
    cache = read_cmake_cache(build)
    while not cache:
        print("   {} has not been configured yet (no CMakeCache.txt). Configure and build your core once".format(build))
        print("   the usual way first (AzerothCore wiki: Core Installation), then point this at that folder.")
        answer = ui.ask("   Build folder, or Enter to skip the build")
        if not answer:
            print("   build skipped: re-run CMake configure and build worldserver yourself.")
            return None
        build = Path(answer)
        cache = read_cmake_cache(build)
    config = build_config(ui, args, build, cache)
    server = getattr(args, "server_ctl", None)
    server_exe = server.exe if server else (Path(args.server) if getattr(args, "server", None) else None)
    if server_exe and server_exe.is_dir():
        server_exe = server_exe / WORLDSERVER
    if build_is_current(build, config, server_exe):
        print("   the server code has not changed since the last build: no rebuild needed.")
        return True
    jobs = args.jobs or default_jobs()
    print("   build folder {}, configuration {}, {} compilers at a time, below normal priority".format(
        build, config, jobs))
    if not ui.confirm("   Configure and build now?"):
        print("   build skipped: re-run CMake configure and build worldserver yourself.")
        return None
    if server and server.running():
        print("   stopping the server first so the build gets the whole CPU (it is started again at the end)")
        stopped = server.stop()
        if not stopped:
            return stopped
    if run(ui, ["cmake", "-S", core, "-B", build]) != 0:
        print("   CMake configure failed; its output above says why.")
        return False
    if run(ui, build_command(build, config, jobs, cache), low_priority=True) != 0:
        print("   The build failed; its output above says why. The patches and module stay in place.")
        return False
    if not ui.dry_run:
        write_build_stamp(build)
    return True


def build_config(ui, args, build, cache):
    """The configuration to build (asked once for multi-config generators, then remembered)."""
    if getattr(args, "config", None):
        return args.config
    config = cache.get("CMAKE_BUILD_TYPE") or "RelWithDebInfo"
    if is_multi_config(cache) and not ui.auto:
        config = ui.ask("   Configuration to build", config)
    args.config = config
    return config


def step_server(ui, args):
    ui.step("4. Put the new worldserver in place", [
        "Copies the worldserver the build made over the one your server runs (its symbols and the",
        "MySQL client DLL it was built against too), after moving the old ones to this folder's",
        "backups/. The server has to be stopped for this; if it is still running, the step waits",
        "until you stop it.",
    ])
    if getattr(args, "uninstall", False) and restoring(args):
        return restore_original(ui, args)
    core = need_core(ui, args)
    build = Path(args.build) if args.build else core / "build"
    cache = read_cmake_cache(build)
    config = build_config(ui, args, build, cache) if cache else (args.config or "RelWithDebInfo")
    built = find_built(build, config)
    if not built:
        print("   no {} in {} (build it first, step 3).".format(WORLDSERVER, build / "bin"))
        return None if ui.dry_run else False
    target = Path(args.server) if args.server else None
    while not target or not (target.is_file() or (target / WORLDSERVER).is_file()):
        if target:
            print("   no {} at {}.".format(WORLDSERVER, target))
        answer = ui.ask("   The worldserver your server runs (the file or its folder), or Enter to skip")
        if not answer:
            ui.note("Copy {} over the worldserver your server runs (stop it first).".format(built))
            return None
        target = Path(answer)
    if target.is_dir():
        target = target / WORLDSERVER
    if target.resolve() == built.resolve():
        print("   your server runs the build's own worldserver: nothing to copy.")
        return True
    print("   new: {}\n   live: {}".format(built, target))
    repack = repack_of(target)
    if repack and (repack["root"] / "CoA-Bots" / "coa_bots.py").is_file() and \
            target.parent.resolve() == (repack["root"] / "Core").resolve():
        warning = ("CoA-Bots will not start while the repack's own server (Core\\worldserver.exe) is Shapeshifter's: "
                   "it checks that file is the repack's. Install into the CoA-Bots server instead (tick the "
                   "CoA-Bots box), or uninstall before starting CoA-Bots.")
        print("   Note: " + warning)
        ui.note(warning)
    mismatch = mysql_mismatch(cache, target)
    if mismatch:
        print("   Not installed: " + mismatch)
        ui.note("Not installed: " + mismatch)
        return False
    if not ui.confirm("   Replace the live worldserver?"):
        return None
    server = getattr(args, "server_ctl", None)
    if server and server.exe.resolve() == target.resolve():
        stopped = server.stop()
        if not stopped:
            return stopped
    backup_root = BACKUPS / args.stamp / "server"
    keep_original(ui, target)
    done = replace_file(ui, built, target, backup_root, "worldserver")
    symbols = built.with_suffix(".pdb")
    if done and symbols.is_file():
        replace_file(ui, symbols, target.with_suffix(".pdb"), backup_root, "worldserver symbols")
    elif done and target.with_suffix(".pdb").is_file():
        print("   the build has no symbols file; the old one would mislead crash reports")
        move_away(ui, target.with_suffix(".pdb"), backup_root, "the old worldserver symbols")
    dll = mysql_client_dll(cache) if cache else None
    if done and dll:
        replace_file(ui, dll, target.parent / dll.name, backup_root, "MySQL client library")
    if done:
        bring_runtime_dlls(ui, built, cache, target, backup_root)
    return done


# ---- the DLLs the new worldserver loads (1.1.0) --------------------------------------------------------
# A worldserver built here loads DLLs from the build PC: OpenSSL's (libcrypto-4-x64.dll after an
# OpenSSL 4 install), and the Visual C++ runtime of the compiler that built it. On the build PC they are
# found in System32 or on PATH, so the server starts there and nowhere else. Every one the server folder
# lacks, and a VC++ runtime DLL there older than the build's, goes beside it.
VC_RUNTIME = ("msvcp140", "vcruntime140", "concrt140", "vccorlib140")


def pe_imports(path):
    """The DLL names a Windows executable or DLL imports (its import directory), [] if unreadable."""
    import struct
    try:
        data = Path(path).read_bytes()
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        sections = struct.unpack_from("<H", data, pe + 6)[0]
        optional_size = struct.unpack_from("<H", data, pe + 20)[0]
        optional = pe + 24
        directory = optional + (112 if struct.unpack_from("<H", data, optional)[0] == 0x20B else 96)
        rva = struct.unpack_from("<I", data, directory + 8)[0]
        table = [struct.unpack_from("<8sIIII", data, optional + optional_size + 40 * i) for i in range(sections)]

        def offset(address):
            for _, vsize, vaddr, rawsize, rawptr in table:
                if vaddr <= address < vaddr + max(vsize, rawsize):
                    return address - vaddr + rawptr
            raise ValueError(address)
        names, pos = [], offset(rva) if rva else None
        while pos is not None:
            name_rva = struct.unpack_from("<I", data, pos + 12)[0]
            if not name_rva:
                break
            start = offset(name_rva)
            names.append(data[start:data.index(b"\0", start)].decode("ascii", "replace"))
            pos += 20
        return names
    except (OSError, ValueError, struct.error, IndexError):
        return []


def file_version(path):
    """A Windows file's version as a tuple (0,) when it has none."""
    if os.name != "nt":
        return (0,)
    import ctypes
    from ctypes import wintypes
    version = ctypes.windll.version
    size = version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return (0,)
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
        return (0,)
    info, length = ctypes.c_void_p(), wintypes.UINT()
    if not version.VerQueryValueW(buffer, "\\", ctypes.byref(info), ctypes.byref(length)):
        return (0,)
    words = ctypes.cast(info, ctypes.POINTER(wintypes.DWORD * 4))[0]
    return (words[2] >> 16, words[2] & 0xFFFF, words[3] >> 16, words[3] & 0xFFFF)


def file_company(path):
    """A Windows file's CompanyName ('' when it has none)."""
    if os.name != "nt":
        return ""
    import ctypes
    from ctypes import wintypes
    version = ctypes.windll.version
    size = version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return ""
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
        return ""
    info, length = ctypes.c_void_p(), wintypes.UINT()
    if not version.VerQueryValueW(buffer, "\\VarFileInfo\\Translation", ctypes.byref(info), ctypes.byref(length)) \
            or length.value < 4:
        return ""
    lang = ctypes.cast(info, ctypes.POINTER(wintypes.WORD * 2))[0]
    key = "\\StringFileInfo\\{:04x}{:04x}\\CompanyName".format(lang[0], lang[1])
    if not version.VerQueryValueW(buffer, key, ctypes.byref(info), ctypes.byref(length)) or not length.value:
        return ""
    return ctypes.wstring_at(info, length.value - 1)


def is_windows_dll(path):
    """Part of Windows itself (Microsoft's, in System32, not the VC++ runtime): every PC has it. OpenSSL
    and others put copies in System32 too, so the folder alone does not tell."""
    return Path(path).is_file() and not path.name.lower().startswith(VC_RUNTIME) and \
        file_company(path).startswith("Microsoft")


def dll_folders(built, cache):
    """Where the build PC keeps the DLLs its worldserver loads: next to it, the libraries it was built
    against, PATH, then System32 (where the VC++ runtime is)."""
    folders = [Path(built).parent]
    for key in ("OPENSSL_ROOT_DIR", "OPENSSL_INCLUDE_DIR"):
        if cache.get(key):
            root = Path(cache[key]).parent if key.endswith("INCLUDE_DIR") else Path(cache[key])
            folders += [root / "bin", root]
    openssl = openssl_root(cache)
    if openssl:
        folders += [openssl / "bin", openssl]
    if cache.get("MYSQL_LIBRARY"):
        folders.append(Path(cache["MYSQL_LIBRARY"]).parent)
    folders += [Path(d) for d in os.environ.get("PATH", "").split(os.pathsep) + registry_path() if d]
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    return folders + [system]


def runtime_dlls(built, cache, server_dir):
    """[source path] of the DLLs to put beside the server: the ones it (or those DLLs) loads that the
    server folder lacks, and VC++ runtime DLLs newer than the server folder's. Windows' own are skipped."""
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    folders = dll_folders(built, cache)
    wanted, queue, seen = [], list(pe_imports(built)), set()
    while queue:
        name = queue.pop(0)
        low = name.lower()
        if low in seen or low.startswith(("api-ms-", "ext-ms-")) or low == "libmysql.dll":
            continue
        seen.add(low)
        runtime = low.startswith(VC_RUNTIME)
        if not runtime and is_windows_dll(system / name):
            continue
        source = next((f / name for f in folders if (f / name).is_file()), None)
        if runtime:                                   # the newest one the build PC has
            source = max((f / name for f in folders if (f / name).is_file()), key=file_version, default=None)
        if source is None:
            continue
        here = Path(server_dir) / name
        if here.is_file() and (not runtime or file_version(here) >= file_version(source)):
            continue
        wanted.append(source)
        queue += pe_imports(source)
    return wanted


def bring_runtime_dlls(ui, built, cache, target, backup_root):
    """Puts the DLLs runtime_dlls names beside the server. For the CoA-Bots server, a VC++ runtime DLL
    also goes into the repack's own Core folder: CoA-Bots copies that folder's DLLs over its own at every
    start (a newer runtime runs the repack's server too)."""
    if os.name != "nt":
        return
    repack = repack_of(target)
    for source in runtime_dlls(built, cache, target.parent):
        folders = [target.parent]
        if source.name.lower().startswith(VC_RUNTIME) and repack and repack["bots"] and \
                (repack["root"] / "Core").resolve() != target.parent.resolve():
            folders.append(repack["root"] / "Core")
        for folder in folders:
            backup = backup_root if folder == target.parent else backup_root / "repack-Core"
            replace_file(ui, source, folder / source.name, backup, "runtime library " + source.name)


def puts_original_back(args):
    """True (the step says why it has nothing to do) when an uninstall puts the repack's own worldserver
    back instead of compiling: no source, patches, module or build to undo on this PC."""
    if getattr(args, "uninstall", False) and restoring(args):
        print("   not needed: the repack's own worldserver goes back instead (the server step).")
        return True
    return False


def restore_original(ui, args):
    """Uninstall without a compiler: the repack's own worldserver, MySQL DLL and symbols, kept in
    shapeshifter-original/ by the install, go back in place (what they replace goes to backups/)."""
    target = Path(args.server)
    keep = target.parent / ORIGINAL
    print("   putting back the repack's own worldserver from {}".format(keep))
    if not ui.confirm("   Put it back?"):
        return None
    server = getattr(args, "server_ctl", None)
    if server and server.exe.resolve() == target.resolve():
        stopped = server.stop()
        if not stopped:
            return stopped
    backup_root = BACKUPS / args.stamp / "server"
    done = True
    for name in ORIGINAL_FILES:
        if (keep / name).is_file():
            done = replace_file(ui, keep / name, target.parent / name, backup_root, name) and done
        elif (target.parent / name).is_file():
            done = move_away(ui, target.parent / name, backup_root, name) and done
    return done


def step_start(ui, args):
    ui.step("8. Start the server", ["Starts the server again if the install stopped it."])
    server = getattr(args, "server_ctl", None)
    if not server or not server.stopped_by_us:
        print("   nothing to do (the install did not stop it).")
        return True
    return server.start()


def wait_for_game_closed(ui, args):
    """The client patch cannot be replaced while the game runs: wait until it is closed."""
    while not ui.dry_run and list_processes(GAME_EXES):
        reply = ui.ask("   The game is running. Close it, then press Enter (or s to skip this step)")
        if reply.lower() in ("s", "skip"):
            return False
    return True


def step_sql(ui, args):
    ui.step("5. Characters database", [
        "Creates one small table (shapeshift_active) in the characters database. It lets a login",
        "after a crash strip auras a form left behind. CREATE TABLE IF NOT EXISTS: safe to re-run.",
        "If your worldserver applies module SQL itself (database updates on), you can skip this.",
        "The login is asked once for this run, kept in memory only, and never saved. MySQL has to be",
        "running (on some repacks it only runs with the server: start just the database).",
    ])
    if not ui.confirm("   Create the table now?"):
        return None
    login, database = mysql_login(ui, args, "   Characters database", "acore_characters")
    if not login:
        print("   skipped. By hand: mysql -u <user> -p <characters database> < \"{}\"".format(SQL))
        return None
    if run_sql(ui, login, database, SQL) != 0:
        print("   mysql reported an error (above).")
        return False
    print("   table created (or already there).")
    return True


def step_classgrade(ui, args):
    ui.step("6. Class-grade forms (Conquest of Azeroth, optional)", [
        "Player-grade copies of every form's spells, its gear and talents: world data for the server",
        "(shapeshift_class.sql into the world database) and a client patch (patch-Y.MPQ into the",
        "client's Data folder). Both are built from one client's own files, so they fit that client",
        "only. Stop the worldserver and close the game first. Without them forms use each creature's",
        "own spells.",
    ])
    missing = [name for name in CLASSGRADE_FILES if not (CLASSGRADE / name).is_file()]
    if missing:
        print("   this copy has no classgrade/ folder (it comes in the release zip); skipped.")
        return None
    if not ui.confirm("   Install the class-grade data?"):
        return None
    login, database = mysql_login(ui, args, "   World database", "acore_world")
    if not login:
        print("   skipped. By hand: mysql -u <user> -p <world database> < \"{}\"".format(
            CLASSGRADE / "shapeshift_class.sql"))
        return None
    print("   applying the world data (a few minutes; it replaces only Shapeshifter's own rows)")
    if run_sql(ui, login, database, CLASSGRADE / "shapeshift_class.sql") != 0:
        print("   mysql reported an error (above); nothing was committed.")
        return False
    client = need_client(ui, args)
    if not wait_for_game_closed(ui, args):
        return None
    return replace_file(ui, CLASSGRADE / "patch-Y.MPQ", client / "Data" / "patch-Y.MPQ",
                        BACKUPS / args.stamp / "client", "client patch")


def step_addon(ui, args):
    ui.step("7. Addon", [
        "Copies addon/Shapeshifter into the client's Interface/AddOns folder. An older copy (also the",
        "old Shapeshift addon) goes to backups/ first, and its saved settings (favorites, chosen skins)",
        "are carried over to the new name.",
    ])
    client = need_client(ui, args)
    if not ui.confirm("   Copy the addon?"):
        return None
    old = client / "Interface" / "AddOns" / OLD_ADDON
    if old.exists() and move_away(ui, old, BACKUPS / args.stamp / "old-name", "the old Shapeshift addon") is None:
        return False
    migrate_saved_variables(ui, client, BACKUPS / args.stamp)
    return copy_tree(ui, ADDON, client / "Interface" / "AddOns" / "Shapeshifter", "addon", BACKUPS / args.stamp)


STEP_FUNCS = {"source": step_source, "patches": step_patches, "module": step_module, "build": step_build, "server": step_server,
              "sql": step_sql, "classgrade": step_classgrade, "addon": step_addon, "start": step_start}


# ---- uninstall: the same steps, undone, in reverse --------------------------------------------------

UNINSTALL_STEPS = ("addon", "classgrade", "sql", "module", "patches", "build", "server", "start")


def undo_addon(ui, args):
    ui.step("1. Addon", ["Moves Interface/AddOns/Shapeshifter (and an old Shapeshift) out of the client, into backups/."])
    client = need_client(ui, args)
    targets = [t for t in (client / "Interface" / "AddOns" / "Shapeshifter", client / "Interface" / "AddOns" / OLD_ADDON)
               if t.exists()]
    if not targets:
        print("   not installed.")
        return True
    if not ui.confirm("   Remove the addon?"):
        return None
    for target in targets:
        if move_away(ui, target, BACKUPS / args.stamp / "client", "the {} addon".format(target.name)) is None:
            return None
    return True


def undo_classgrade(ui, args):
    ui.step("2. Class-grade forms", [
        "Deletes Shapeshifter's own rows from the world database (its id ranges only, the DELETEs its",
        "install SQL begins with), drops its stance table, and moves patch-Y.MPQ out of the client's",
        "Data folder. Stop the worldserver and close the game first; MySQL must be running.",
    ])
    install_sql = CLASSGRADE / "shapeshift_class.sql"
    if not install_sql.is_file():
        print("   needs {} (the class-grade download) to know its id ranges; skipped.".format(install_sql))
        return None
    if not ui.confirm("   Remove the class-grade data?"):
        return None
    login, database = mysql_login(ui, args, "   World database", "acore_world")
    if not login:
        return None
    sql = uninstall_classgrade_sql(install_sql.read_text(encoding="utf-8", errors="replace"))
    if run_sql(ui, login, database, sql_bytes=sql.encode("utf-8"), label="<class-grade removal>") != 0:
        print("   mysql reported an error (above); nothing was committed.")
        return False
    client = need_client(ui, args)
    patch = client / "Data" / "patch-Y.MPQ"
    if patch.exists() and not wait_for_game_closed(ui, args):
        return None
    if not patch.exists():
        print("   no patch-Y.MPQ in the client.")
        return True
    return move_away(ui, patch, BACKUPS / args.stamp / "client", "the client patch")


def undo_sql(ui, args):
    ui.step("3. Characters database", [
        "Drops the shapeshifter_active table (it only holds forms worn at the moment).",
    ])
    if not ui.confirm("   Drop the table?"):
        return None
    login, database = mysql_login(ui, args, "   Characters database", "acore_characters")
    if not login:
        return None
    if run_sql(ui, login, database,
               sql_bytes=b"DROP TABLE IF EXISTS `shapeshifter_active`;\nDROP TABLE IF EXISTS `shapeshift_active`;\n",
               label="<drop shapeshifter_active>") != 0:
        print("   mysql reported an error (above).")
        return False
    return True


def undo_module(ui, args):
    ui.step("4. Server module", ["Moves modules/mod-shapeshifter (and an old mod-shapeshift) out of your core, into backups/."])
    if puts_original_back(args):
        return True
    core = need_core(ui, args)
    targets = [t for t in (core / "modules" / "mod-shapeshifter", core / "modules" / OLD_MODULE) if t.exists()]
    if not targets:
        print("   not installed.")
        return True
    if not ui.confirm("   Remove the module?"):
        return None
    for target in targets:
        if move_away(ui, target, BACKUPS / args.stamp, "the {} module".format(target.name)) is None:
            return None
    return True


def undo_patches(ui, args):
    ui.step("5. Core patches", [
        "Reverses the Shapeshifter patches your core has (git apply -R), newest first, each checked",
        "first. Patches that are not in your source are left alone.",
    ])
    if puts_original_back(args):
        return True
    if not find_tool("git"):
        print("   git is not on PATH. Reverse the files in patches/ by hand (git apply -R).")
        return False
    core = need_core(ui, args)
    applied = [name for name, _, _, _ in reversed(PATCH_PLAN) if patch_applied(core, name)]
    if not applied:
        print("   none applied.")
        return True
    print("   applied: " + ", ".join(applied))
    if not ui.confirm("   Reverse them?"):
        return None
    for i, name in enumerate(applied):
        patch = PATCHES / name
        if ui.dry_run and i > 0:
            print("   (dry run: it can only be checked once the patch above is really reversed)")
            print("   $ git apply -R " + str(patch))
            continue
        cmd = ["git", "apply", "-R", patch]
        code, out = run_quiet(["git", "apply", "-R", "--check", patch], cwd=core)
        if code != 0:
            have, _, neither = split_patch_files(core, patch)
            if neither or not have:
                print("   {} does not reverse cleanly:\n   {}".format(name, out.strip().replace("\n", "\n   ")))
                return False
            print("   {} is only partly applied (a run that stopped half way?): reversing it in {}".format(
                name, ", ".join(have)))
            cmd = ["git", "apply", "-R"] + ["--include=" + rel for rel in have] + [patch]
        if run(ui, cmd, cwd=core) != 0:
            print("   git apply -R failed.")
            return False
        ui.note("Re-apply {}: cd \"{}\" && git apply \"{}\"".format(name, core, patch))
    return True


UNDO_FUNCS = {"addon": undo_addon, "classgrade": undo_classgrade, "sql": undo_sql, "module": undo_module,
              "patches": undo_patches, "build": step_build, "server": step_server, "start": step_start}


def is_newer(tag):
    """True when a release tag (v1.2.3) is a higher version than this copy."""
    def parts(text):
        bits = text.strip().lstrip("vV").split(".")
        return tuple(int(b) for b in bits) if all(b.isdigit() for b in bits) else None
    theirs, ours = parts(tag), parts(VERSION)
    return bool(theirs and ours and theirs > ours)


class DropAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub sends a download on to a signed storage address, which refuses a second credential."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlparse(newurl).netloc != urllib.parse.urlparse(req.full_url).netloc:
            new.remove_header("Authorization")
        return new


def http_get(url, token=None, accept=None):
    headers = {"User-Agent": "Shapeshifter-Setup/" + VERSION, "Accept": accept or "application/vnd.github+json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    opener = urllib.request.build_opener(DropAuthOnRedirect)
    with opener.open(urllib.request.Request(url, headers=headers), timeout=120) as response:
        return response.read()


def github_token():
    """A GitHub login for a private repository: GH_TOKEN or GITHUB_TOKEN, else the GitHub CLI's.
    Kept in memory for this run only."""
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(name):
            return os.environ[name]
    if shutil.which("gh"):
        code, out = run_quiet(["gh", "auth", "token"])
        token = out.strip().splitlines()[0] if code == 0 and out.strip() else ""
        return token or None
    return None


def parse_release(raw):
    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.startswith("Shapeshifter-") and name.endswith(".zip"):
            return {"tag": data.get("tag_name", ""), "name": name, "size": asset.get("size", 0),
                    "url": asset.get("browser_download_url"), "api": asset.get("url")}
    return None


def latest_release(token):
    """The newest release on GitHub and its zip, or None (said why)."""
    url = "https://api.github.com/repos/{}/releases/latest".format(RELEASES)
    try:
        raw = http_get(url, token)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            print("   GitHub shows no release: the repository may be private (sign in with `gh auth login`,")
            print("   or set GH_TOKEN), or nothing is released yet.")
        else:
            print("   GitHub answered {} {}.".format(error.code, error.reason))
        return None
    except (urllib.error.URLError, OSError) as error:
        print("   could not reach GitHub ({}).".format(getattr(error, "reason", error)))
        return None
    release = parse_release(raw)
    if not release:
        print("   the newest release has no Shapeshifter zip.")
    return release


def download_release(release, dest, token):
    """Downloads the release zip and unpacks it into dest (its own Shapeshifter-<version> folder)."""
    data = http_get(release["api"], token, accept="application/octet-stream") if token else http_get(release["url"])
    dest = Path(dest).resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.namelist():
            if not (dest / member).resolve().is_relative_to(dest):
                raise zipfile.BadZipFile("{} would unpack outside {}".format(member, dest))
        archive.extractall(str(dest))
    return dest / release["name"][:-len(".zip")]


def launch(cmd, cwd):
    subprocess.Popen(cmd, cwd=cwd)


def run_update(argv):
    """--update: fetch the newest release beside this copy and hand over to its Setup, which installs
    what changed (it rebuilds the worldserver only when the server code did)."""
    print("Shapeshifter {}: looking for a newer release on GitHub".format(VERSION))
    token = github_token()
    release = latest_release(token)
    if not release:
        return 1
    if not is_newer(release["tag"]):
        print("   you have the latest ({}).".format(VERSION))
        return 0
    print("   {} is out: downloading {} ({:.1f} MB)".format(release["tag"], release["name"], release["size"] / 1e6))
    try:
        folder = download_release(release, HERE.parent, token)
    except (urllib.error.URLError, OSError, zipfile.BadZipFile) as error:
        print("   the download failed ({}).".format(getattr(error, "reason", error)))
        return 1
    rest = [a for a in argv if a != "--update"]
    setup = folder / "Shapeshifter Setup.exe"
    if getattr(sys, "frozen", False) and setup.is_file():
        cmd = [str(setup)] + rest
    else:
        cmd = [sys.executable, str(folder / "install.py")] + rest
    print("   unpacked to {}; starting it".format(folder))
    launch(cmd, str(folder))
    return 0


def plan_steps(uninstall, only=None):
    """(steps, functions) for an install or an uninstall, optionally only some steps."""
    all_steps, funcs = (UNINSTALL_STEPS, UNDO_FUNCS) if uninstall else (STEPS, STEP_FUNCS)
    if not only:
        return all_steps, funcs
    wanted = [x.strip() for x in only.split(",") if x.strip()]
    unknown = [x for x in wanted if x not in all_steps]
    if unknown:
        raise ValueError("unknown step(s): {} (choose from {})".format(", ".join(unknown), ", ".join(all_steps)))
    return tuple(x for x in all_steps if x in wanted), funcs


def execute(ui, args, steps, funcs, results=None):
    """Runs the steps (the paths in args already found), then starts a server the run stopped, even
    when a step failed, and prints the summary. Returns 0 when every step ran and none failed."""
    results = {} if results is None else results
    try:
        for name in steps:
            results[name] = funcs[name](ui, args)
            if results[name] is False and name in ("patches", "module", "build", "server"):
                print("\nStopped: the server steps after this one depend on it.")
                break
    except Quit:
        print("\nStopped at your request.")
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        server = getattr(args, "server_ctl", None)
        if server and server.stopped_by_us and "start" not in results:
            print("\nThe install stopped your server; starting it again.")
            results["start"] = server.start()
    print("\n== Summary ==")
    for name in steps:
        state = {True: "done", False: "FAILED", None: "skipped"}[results[name]] if name in results else "not run"
        print("   {:10} {}".format(name, state))
    for line in ui.notes:
        print("   - " + line)
    failed = any(results.get(n) is False for n in steps) or any(n not in results for n in steps) or not steps
    if not failed and getattr(args, "uninstall", False):
        print("\nShapeshifter is removed. Everything taken out is in {} (installing again puts it back).".format(
            BACKUPS / args.stamp))
    elif not failed:
        print("\nDone. Log in on a GM account and type /ss (or click the minimap button).")
    return 1 if failed else 0


def main(argv=None, answers=None):
    parser = argparse.ArgumentParser(description="Install Shapeshifter {}: finds everything, asks once, "
                                                 "does it all.".format(VERSION))
    parser.add_argument("--uninstall", action="store_true", help="undo everything (same steps, reversed)")
    parser.add_argument("--update", action="store_true",
                        help="download the newest release from GitHub and run its Setup (it rebuilds only if needed)")
    parser.add_argument("--dry-run", action="store_true", help="show every step, change nothing")
    parser.add_argument("--step-by-step", action="store_true",
                        help="ask before each step and for each path instead of finding them")
    parser.add_argument("--core", help="AzerothCore source folder (found by itself if left out)")
    parser.add_argument("--build", help="its CMake build folder (found by itself if left out)")
    parser.add_argument("--server", help="the worldserver your server runs, file or folder (found by itself)")
    parser.add_argument("--client", help="the game client folder (found by itself)")
    parser.add_argument("--mysql", help="the mysql client (found by itself)")
    parser.add_argument("--bots", dest="bots", action="store_true", default=None,
                        help="the server is the CoA-Bots one (fetch mod-playerbots when preparing the repack's source)")
    parser.add_argument("--no-bots", dest="bots", action="store_false", help="the repack's base server")
    parser.add_argument("--config", help="build configuration (default: from the build folder)")
    parser.add_argument("--jobs", type=int, help="compilers at a time (default: three quarters of the CPU threads)")
    parser.add_argument("--only", help="comma-separated steps to run: " + ",".join(STEPS))
    args = parser.parse_args(argv)
    if args.update:
        return run_update(list(sys.argv[1:] if argv is None else argv))
    args.stamp = stamp()
    try:
        steps, funcs = plan_steps(args.uninstall, args.only)
    except ValueError as error:
        parser.error(str(error))
    if sys.version_info < (3, 8):
        print("Python 3.8 or newer is needed.")
        return 2
    if args.server and Path(args.server).is_dir():
        args.server = str(Path(args.server) / WORLDSERVER)

    ui = Ui(args.dry_run, answers)
    print("Shapeshifter {} {}{}".format(VERSION, "uninstall" if args.uninstall else "setup",
                                        " (dry run: nothing will be changed)" if args.dry_run else ""))
    results = {}
    try:
        if not args.step_by_step:
            args.server_ctl = discover(ui, args)
            show_found(args, args.server_ctl)
            if not args.dry_run and not acquire_tools(ui, args):
                return 1
            print("\nIt will {}: {}.".format("remove" if args.uninstall else "install", ", ".join(steps)))
            if args.server_ctl and args.server_ctl.running():
                print("Your server is running: it is stopped before the build and started again at the end.")
            print("Back up your server, its databases and your client first; replaced files go to backups/.")
            answer = ui.ask("Go ahead? [Y/n]").lower()
            if answer not in ("", "y", "yes"):
                raise Quit()
            ui.auto = True
        return execute(ui, args, steps, funcs, results)
    except Quit:
        print("\nStopped at your request.")
        return execute(ui, args, (), funcs, results)



if __name__ == "__main__":
    code = main()
    if os.name == "nt" and len(sys.argv) == 1 and sys.stdin and sys.stdin.isatty():
        input("\nPress Enter to close.")          # double-clicked: keep the window open to read the summary
    sys.exit(code)

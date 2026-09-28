"""Build the one release zip: Shapeshifter-<version>.zip with everything in it (the committed files at
HEAD, "Shapeshifter Setup.exe" and classgrade/ from the class-grade build). Maintainers only.

    python -m PyInstaller --noconfirm --onefile --windowed --name "Shapeshifter Setup" \
        --distpath build_exe/dist --workpath build_exe/work --specpath build_exe setup_gui.py
    python tools/make_release.py --classgrade C:/CoA-Build/shapeshift/class [--out dist] [--worktree]

--worktree: the files as they are on disk (tracked and new, .gitignore respected) instead of HEAD, for a
test build before a commit.
"""
import argparse
import io
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
DEV_DIRS = ("/tools/", "/data/", "/docs/")   # generators, their source data and design docs: not for players
sys.path.insert(0, str(HERE))
import install  # noqa: E402

README = """Class-grade data for Shapeshifter {v}: player-grade spells, gear and talents for every form.
Built from the Conquest of Azeroth client's own files for this version; it fits that client only.
install.py installs it (world data into the world database, patch-Y.MPQ into the client's Data folder).
"""


def worktree_zip(name):
    """The files as they are on disk (tracked and untracked, .gitignore respected, deleted ones and
    maintainer folders left out) zipped like git archive would."""
    listed = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=str(HERE),
                            stdout=subprocess.PIPE, check=True).stdout.decode("utf-8").split("\0")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out:
        for rel in sorted(set(r for r in listed if r)):
            if ("/" + rel).startswith(DEV_DIRS) or not (HERE / rel).is_file():
                continue
            out.write(str(HERE / rel), "{}/{}".format(name, rel))
    return buffer.getvalue()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--classgrade", required=True, help="folder with shapeshift_class.sql and patch-Y.MPQ")
    parser.add_argument("--out", default=str(HERE / "dist"))
    parser.add_argument("--worktree", action="store_true", help="package the working tree, not HEAD (test builds)")
    args = parser.parse_args(argv)
    kit = Path(args.classgrade)
    setup_exe = HERE / "build_exe" / "dist" / "Shapeshifter Setup.exe"
    if not setup_exe.is_file():
        parser.error("build {} first (PyInstaller line in this file's docstring)".format(setup_exe))
    missing = [n for n in install.CLASSGRADE_FILES if not (kit / n).is_file()]
    if missing:
        parser.error("{} has no {}".format(kit, ", ".join(missing)))
    if not args.worktree and subprocess.run(["git", "diff", "--quiet", "HEAD"], cwd=str(HERE)).returncode != 0:
        parser.error("uncommitted changes: the zip is built from HEAD, commit first (or --worktree for a test)")
    name = "Shapeshifter-{}".format(install.VERSION)
    if args.worktree:
        archive = worktree_zip(name)
    else:
        archive = subprocess.run(["git", "archive", "--format=zip", "--prefix={}/".format(name), "HEAD"],
                                 cwd=str(HERE), stdout=subprocess.PIPE, check=True).stdout
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / (name + ".zip")
    with zipfile.ZipFile(io.BytesIO(archive)) as src, \
            zipfile.ZipFile(str(target), "w", zipfile.ZIP_DEFLATED, compresslevel=6) as dst:
        for item in src.infolist():
            if not item.filename.startswith(tuple(name + d for d in DEV_DIRS)):   # maintainer files stay out
                dst.writestr(item, src.read(item))
        dst.write(str(setup_exe), "{}/Shapeshifter Setup.exe".format(name))
        for file_name in install.CLASSGRADE_FILES:
            dst.write(str(kit / file_name), "{}/classgrade/{}".format(name, file_name))
        dst.writestr("{}/classgrade/README.txt".format(name), README.format(v=install.VERSION))
    print("wrote {} ({:.1f} MB)".format(target, target.stat().st_size / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())

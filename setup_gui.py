"""Shapeshifter Setup: the installer's window. Built into "Shapeshifter Setup.exe" (Python bundled), it
sits next to addon/, module/, patches/ and classgrade/ in the release zip and runs install.py's steps.

It finds everything when it opens (the same search as install.py), shows it with Browse buttons,
and Install / Uninstall run every step with a live log. Questions a step has to ask (close the game,
close an unknown server, pick a build folder) come up as dialogs.
"""
import argparse
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

import install

TITLE = "Shapeshifter Setup {}".format(install.VERSION)


class LogWriter:
    """sys.stdout for the worker thread: every print goes to the window's log."""

    def __init__(self, lines):
        self.lines = lines

    def write(self, text):
        if text:
            self.lines.put(text)

    def flush(self):
        pass


class WindowUi(install.Ui):
    """install.Ui whose questions are dialogs, asked on the window's own thread."""

    def __init__(self, app, dry_run):
        super().__init__(dry_run, None)
        self.app = app

    def _on_main(self, fn):
        box, done = {}, threading.Event()

        def call():
            box["value"] = fn()
            done.set()
        self.app.calls.put(call)
        done.wait()
        return box["value"]

    def ask(self, prompt, default=""):
        text = prompt.strip()
        if "Enter" in text and "number" not in text:
            # "press Enter when done" questions: OK carries on, Cancel skips
            ok = self._on_main(lambda: messagebox.askokcancel(TITLE, text.replace("press Enter", "click OK")))
            return "" if ok else "s"
        reply = self._on_main(lambda: simpledialog.askstring(TITLE, text, initialvalue=default, parent=self.app.root))
        if reply is None:
            raise install.Quit()
        return reply.strip() or default

    def confirm(self, prompt):
        if self.auto:
            print(prompt + " yes")
            return True
        return self._on_main(lambda: messagebox.askyesno(TITLE, prompt.strip()))

    def password(self, prompt):
        reply = self._on_main(lambda: simpledialog.askstring(TITLE, prompt.strip(), show="*", parent=self.app.root))
        if reply is None:
            raise install.Quit()
        return reply


PREPARED_NOTE = "(leave empty: Setup takes care of it)"

FIELDS = (("core", "AzerothCore source", "dir"), ("build", "Build folder", "dir"),
          ("server", "Server (worldserver)", "exe"), ("client", "Game client", "dir"),
          ("mysql", "MySQL client", "file"))


class ToolsWindow:
    """The build tools this PC lacks, in a window of its own: a box to tick (Setup downloads and installs
    it) and the download page of each, with Check again for ones installed by hand. Continue turns on
    only when none is missing; closing it goes on to the main window, where Install stays off."""

    INTRO = ("Shapeshifter is compiled into your server, and this PC is missing tools for that. Tick the ones "
             "Setup should download and install for you, or install them yourself from their links and click "
             "Check again. Setup looks for your server once they are all here.")

    def __init__(self, app, missing, compute, then):
        self.app, self.compute, self.then = app, compute, then
        self.missing, self.vars, self.busy = [], {}, False
        top = self.top = tk.Toplevel(app.root)
        top.title("{}: build tools".format(TITLE))
        top.transient(app.root)
        top.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(top, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Build tools needed first", font=("Segoe UI", 13, "bold")).grid(row=0, column=0,
                                                                                              sticky="w")
        ttk.Label(frame, text=self.INTRO, wraplength=720, justify="left").grid(row=1, column=0, sticky="w",
                                                                              pady=(4, 8))
        self.rows = ttk.Frame(frame)
        self.rows.grid(row=2, column=0, sticky="we")
        actions = ttk.Frame(frame)
        actions.grid(row=3, column=0, sticky="we", pady=8)
        self.install_btn = ttk.Button(actions, text="Install ticked tools", command=self.install)
        self.install_btn.pack(side="left")
        self.check_btn = ttk.Button(actions, text="Check again", command=self.check)
        self.check_btn.pack(side="left", padx=6)
        self.continue_btn = ttk.Button(actions, text="Continue", command=self.done)
        self.continue_btn.pack(side="right")
        self.status = ttk.Label(frame, text="")
        self.status.grid(row=4, column=0, sticky="w")
        self.log = scrolledtext.ScrolledText(frame, height=10, width=100, font=("Consolas", 9), state="disabled")
        self.log.grid(row=5, column=0, sticky="nsew", pady=(6, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(5, weight=1)
        self.render(missing)
        top.grab_set()

    def render(self, missing):
        ticked = {key: var.get() for key, var in self.vars.items()}
        self.missing, self.vars = list(missing), {}
        for child in self.rows.winfo_children():
            child.destroy()
        for row, (key, name, why, page) in enumerate(self.missing):
            var = tk.BooleanVar(value=ticked.get(key, True))
            self.vars[key] = var
            ttk.Checkbutton(self.rows, text=name, variable=var).grid(row=row, column=0, sticky="w")
            ttk.Label(self.rows, text=why, foreground="#555555").grid(row=row, column=1, sticky="w", padx=8)
            link = tk.Label(self.rows, text=page, fg="#0645ad", cursor="hand2")
            link.grid(row=row, column=2, sticky="w")
            link.bind("<Button-1>", lambda e, url=page: webbrowser.open(url))
        self.status.configure(text="All build tools are on this PC. Click Continue." if not self.missing else
                              "Continue turns on once all of these are on this PC.")
        self.set_busy(self.busy)

    def set_busy(self, busy):
        self.busy = busy
        for button in (self.install_btn, self.check_btn):
            button.configure(state="disabled" if busy or not self.missing else "normal")
        self.continue_btn.configure(state="disabled" if busy or self.missing else "normal")

    def write(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def check(self):
        self.set_busy(True)

        def work():
            install._found_tools.clear()
            missing = self.compute()
            print("\n" + ("All build tools are here." if not missing else
                          "Still missing: {}.".format(", ".join(m[1] for m in missing))))

            def show():
                self.set_busy(False)
                self.render(missing)
            self.app.calls.put(show)
        self.app.in_thread(work)

    def install(self):
        keys = [key for key, var in self.vars.items() if var.get()]
        if not keys:
            messagebox.showinfo(TITLE, "Tick the tools Setup should install, or install them from their links "
                                       "and click Check again.", parent=self.top)
            return
        names = [m[1] for m in self.missing if m[0] in keys]
        if not messagebox.askyesno(TITLE, "Download and install {}?\n\nThis can take a while (Visual Studio is the "
                                          "biggest, several GB). Windows asks for administrator rights for some of "
                                          "them. Nothing on your server changes.".format(", ".join(names)),
                                   parent=self.top):
            return
        self.set_busy(True)

        def work():
            ui = WindowUi(self.app, dry_run=False)
            ui.auto = True
            for key in keys:
                install.install_tool(ui, key)
            self.app.calls.put(self.check)
        self.app.in_thread(work)

    def close(self):
        if self.busy and not messagebox.askyesno(TITLE, "A tool is still being installed. Close anyway?",
                                                 parent=self.top):
            return
        self.done()

    def done(self):
        try:
            self.top.grab_release()
            self.top.destroy()
        except tk.TclError:
            pass
        self.app.tools_closed(self, self.then)

class App:
    def __init__(self, root):
        self.root = root
        root.title(TITLE)
        root.minsize(760, 560)
        self.lines = queue.Queue()
        self.calls = queue.Queue()         # work for the window's thread, queued by the worker (Tk is not thread-safe)
        self.busy = False
        self.vars = {}
        self.db = {}

        top = ttk.Frame(root, padding=12)
        top.pack(fill="both", expand=True)
        ttk.Label(top, text="Shapeshifter {}".format(install.VERSION), font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(top, text="Become iconic bosses and creatures on your AzerothCore server (GM only).").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 10))
        self.entries = {}
        for i, (key, label, kind) in enumerate(FIELDS, start=2):
            ttk.Label(top, text=label).grid(row=i, column=0, sticky="w", pady=2)
            var = tk.StringVar()
            self.vars[key] = var
            entry = tk.Entry(top, textvariable=var, width=78)
            entry.grid(row=i, column=1, sticky="we", padx=6)
            entry.bind("<FocusIn>", lambda e, k=key: self.clear_note(k))
            self.entries[key] = entry
            ttk.Button(top, text="Browse...", command=lambda k=key, kd=kind: self.browse(k, kd)).grid(row=i, column=2)
        self.tools_missing = []            # build tools this PC lacks: Install stays off while any is
        self.tools_window = None
        buttons = ttk.Frame(top)
        buttons.grid(row=9, column=0, columnspan=3, sticky="we", pady=4)
        self.install_btn = ttk.Button(buttons, text="Install", command=lambda: self.start(False))
        self.install_btn.pack(side="left")
        self.uninstall_btn = ttk.Button(buttons, text="Uninstall", command=lambda: self.start(True))
        self.uninstall_btn.pack(side="left", padx=6)
        self.update_btn = ttk.Button(buttons, text="Check for updates", command=self.check_update)
        self.update_btn.pack(side="left")
        self.bots = tk.BooleanVar(value=False)
        ttk.Checkbutton(buttons, text="Install for CoA-Bots Server", variable=self.bots).pack(side="left", padx=12)
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        self.progress = ttk.Progressbar(top, mode="indeterminate")
        self.progress.grid(row=10, column=0, columnspan=3, sticky="we", pady=(8, 6))
        self.log = scrolledtext.ScrolledText(top, height=12, font=("Consolas", 9), state="disabled")
        self.log.grid(row=11, column=0, columnspan=3, sticky="nsew")
        top.columnconfigure(1, weight=1)
        top.rowconfigure(11, weight=1)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.set_busy(True)
        self.pump()
        self.in_thread(self.first_check)

    # ---- plumbing --------------------------------------------------------------------------------
    def pump(self):
        try:
            while True:
                text = self.lines.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", text)
                self.log.see("end")
                self.log.configure(state="disabled")
                if self.tools_window:
                    self.tools_window.write(text)
        except queue.Empty:
            pass
        try:
            while True:
                self.calls.get_nowait()()
        except queue.Empty:
            pass
        self.root.after(100, self.pump)

    def in_thread(self, fn):
        def work():
            sys.stdout = sys.stderr = LogWriter(self.lines)
            try:
                fn()
            except Exception as error:                     # never die silently: show it in the log
                print("\nError: {}".format(error))
                self.calls.put(lambda: self.finished(1, "failed"))
        threading.Thread(target=work, daemon=True).start()

    def set_busy(self, busy):
        self.busy = busy
        for button in (self.install_btn, self.uninstall_btn, self.update_btn):
            button.configure(state="disabled" if busy else "normal")
        if self.tools_missing:
            self.install_btn.configure(state="disabled")
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def browse(self, key, kind):
        if kind == "dir":
            path = filedialog.askdirectory(title=dict((k, l) for k, l, _ in FIELDS)[key])
        else:
            name = install.WORLDSERVER if kind == "exe" else ("mysql.exe" if sys.platform == "win32" else "mysql")
            path = filedialog.askopenfilename(title="Find " + name, filetypes=[(name, name), ("All files", "*.*")])
        if path:
            self.clear_note(key)
            self.vars[key].set(str(Path(path)))
            if key == "server":
                self.read_login()

    def show_note(self, key):
        entry = self.entries[key]
        self.vars[key].set(PREPARED_NOTE)
        entry.configure(fg="#888888")

    def clear_note(self, key):
        if self.vars[key].get() == PREPARED_NOTE:
            self.vars[key].set("")
        self.entries[key].configure(fg="black")

    def path(self, key):
        value = self.vars[key].get()
        return None if not value or value == PREPARED_NOTE else value

    def read_login(self):
        conf = install.find_conf(self.path("server")) if self.path("server") else None
        self.db = install.parse_db_info(conf.read_text(encoding="utf-8", errors="replace")) if conf else {}

    # ---- finding ---------------------------------------------------------------------------------
    def find(self):
        args = argparse.Namespace(core=None, build=None, server=None, client=None, mysql=None, bots=None)
        ui = WindowUi(self, dry_run=True)
        server = install.discover(ui, args, ask_missing=False)
        self.db = args.db
        self.found = args

        def show():
            for key in ("core", "build", "server", "client", "mysql"):
                self.vars[key].set(getattr(args, key) or "")
            self.bots.set(bool(getattr(args, "bots", False)))
            if getattr(args, "prepare_source", False):
                for key in ("core", "build"):
                    if not self.vars[key].get():
                        self.show_note(key)
            notes = []
            if server and server.running():
                notes.append("Server found running. It will be restarted during the install.")
            elif server:
                notes.append("Server found.")
            if not self.db:
                notes.append("Database login not found. You will be asked for it.")
            snapshot = self.run_args()
            self.tools_missing = install.required_tools_missing(snapshot)
            if self.tools_missing:
                notes.append("This PC is still missing build tools: {}. Install stays off until they are here."
                             .format(", ".join(m[1] for m in self.tools_missing)))
                self.open_tools(self.tools_missing, lambda: install.required_tools_missing(snapshot))
            else:
                notes.extend(install.build_readiness(args))
            optional = ("core", "build") if getattr(args, "prepare_source", False) else ()
            missing = [label for key, label, _ in FIELDS if not self.path(key) and key not in optional]
            if missing:
                notes.append("Not found: {}. Use Browse.".format(", ".join(missing)))
            elif not self.tools_missing:
                notes.append("Everything needed was found. Click Install.")
            self.lines.put("\n" + "\n".join(notes) + "\n")
            self.set_busy(False)
        self.calls.put(show)

    # ---- build tools -----------------------------------------------------------------------------
    def first_check(self):
        """Before anything else: the build tools. Missing ones come up in a window of their own, and the
        search for your server (and the question which one) waits until they are all here."""
        print("Checking this PC for the build tools a server build needs...")
        missing = install.missing_build_tools({})
        print("   " + ("all there." if not missing else "missing: {}.".format(", ".join(m[1] for m in missing))))

        def next_step():
            if missing:
                self.open_tools(missing, lambda: install.missing_build_tools({}), then=lambda: self.in_thread(self.find))
            else:
                self.in_thread(self.find)
        self.calls.put(next_step)

    def open_tools(self, missing, compute, then=None):
        if self.tools_window:
            self.tools_window.render(missing)
            return
        self.tools_window = ToolsWindow(self, missing, compute, then)

    def tools_closed(self, window, then):
        self.tools_window = None
        self.closed_tools = window         # a tool install still running holds it: never freed on its thread
        self.tools_missing = window.missing
        self.set_busy(self.busy)
        if then:
            then()
    def run_args(self, uninstall=False):
        """The paths and choices on screen, as install.py's arguments."""
        paths = {k: self.path(k) for k in ("core", "build", "server", "client", "mysql")}
        found = getattr(self, "found", None)
        return argparse.Namespace(uninstall=uninstall, dry_run=False, step_by_step=False, config=None,
                                  jobs=None, only=None, stamp=install.stamp(), db=self.db, bots=self.bots.get(),
                                  seed=getattr(found, "seed", {}) if found else {}, install_tools=[],
                                  prepare_source=not (paths["core"] and paths["build"]), **paths)

    # ---- running ---------------------------------------------------------------------------------
    def start(self, uninstall):
        what = "Uninstall" if uninstall else "Install"
        if not uninstall and install.required_tools_missing(self.run_args()):
            messagebox.showwarning(TITLE, "Get the build tools listed in the window first (Install ticked tools, "
                                          "or their links and Check again).")
            return
        message = ("{} Shapeshifter now?\n\nIt will stop the server if it is running, patch it and rebuild it if its "
                   "code changed (ten minutes to an hour), put the new one in place and start it again. Replaced files go to "
                   "the backups folder next to this program.").format(what)
        if not messagebox.askyesno(TITLE, message):
            return
        self.read_login() if not self.db else None
        args = self.run_args(uninstall)
        self.set_busy(True)

        def work():
            ui = WindowUi(self, dry_run=args.dry_run)
            ui.auto = True
            args.server_ctl = install.Server(ui, args.server) if args.server and Path(args.server).is_file() else None
            steps, funcs = install.plan_steps(uninstall)
            print("\n{} Shapeshifter {}{}\n".format(what, install.VERSION, " (dry run)" if args.dry_run else ""))
            code = install.execute(ui, args, steps, funcs)
            self.calls.put(lambda: self.finished(code, what.lower()))
        self.in_thread(work)

    # ---- updates ---------------------------------------------------------------------------------
    def check_update(self):
        """Asks GitHub for a newer release; on Yes it unpacks next to this copy and its Setup takes
        over (its Install then rebuilds the server only if the server code changed)."""
        self.set_busy(True)

        def work():
            print("\nLooking for a newer Shapeshifter on GitHub...")
            token = install.github_token()
            release = install.latest_release(token)
            if release and install.is_newer(release["tag"]):
                print("   Shapeshifter {} is out.".format(release["tag"].lstrip("vV")))
                self.calls.put(lambda: self.offer_update(release, token))
                return
            if release:
                print("   you have the latest ({}).".format(install.VERSION))
            self.calls.put(lambda: self.set_busy(False))
        self.in_thread(work)

    def offer_update(self, release, token):
        question = ("Shapeshifter {} is out. Download it ({:.0f} MB) and switch to its Setup?\n\nIt unpacks next "
                    "to this copy; nothing changes on your server until you click Install there.").format(
                        release["tag"].lstrip("vV"), release["size"] / 1e6)
        if not messagebox.askyesno(TITLE, question):
            self.set_busy(False)
            return

        def work():
            print("   downloading {}...".format(release["name"]))
            try:
                folder = install.download_release(release, install.HERE.parent, token)
            except (OSError, install.zipfile.BadZipFile) as error:
                print("   the download failed ({}).".format(getattr(error, "reason", error)))
                self.calls.put(lambda: self.set_busy(False))
                return
            setup = folder / "Shapeshifter Setup.exe"
            cmd = [str(setup)] if setup.is_file() else [sys.executable, str(folder / "setup_gui.py")]
            print("   unpacked to {}; starting its Setup.".format(folder))
            install.launch(cmd, str(folder))
            self.calls.put(self.quit_for_update)
        self.in_thread(work)

    def quit_for_update(self):
        self.root.destroy()

    def finished(self, code, what):
        self.set_busy(False)
        if code == 0:
            done = "Shapeshifter is removed." if what == "uninstall" else \
                "Shapeshifter is installed. Log in on a GM account and type /ss."
            messagebox.showinfo(TITLE, done)
        else:
            messagebox.showwarning(TITLE, "The {} did not finish. The log shows which step and why.".format(what))

    def close(self):
        if self.busy and not messagebox.askyesno(TITLE, "It is still working. Close anyway?"):
            return
        self.root.destroy()


def selftest(out_path):
    """`Shapeshifter Setup.exe --selftest <file>`: the search and the bundle check, written to a file
    (the windowed program has no console). For maintainers checking a built exe."""
    import json
    args = argparse.Namespace(core=None, build=None, server=None, client=None, mysql=None, bots=None)
    server = install.discover(install.Ui(True, []), args, ask_missing=False)
    report = {k: getattr(args, k) for k in ("core", "build", "server", "client", "mysql")}
    report.update(here=str(install.HERE), addon=install.ADDON.is_dir(), module=install.MODULE.is_dir(),
                  patches=install.PATCHES.is_dir(), classgrade=all((install.CLASSGRADE / n).is_file()
                                                                   for n in install.CLASSGRADE_FILES),
                  db_login=sorted(args.db), repack=bool(server and server.repack),
                  server_running=bool(server and server.running()), frozen=bool(getattr(sys, "frozen", False)),
                  prepare_source=bool(getattr(args, "prepare_source", False)), bots=bool(getattr(args, "bots", False)),
                  missing_build_tools=[m[1] for m in install.required_tools_missing(args)],
                  seed_generator=(getattr(args, "seed", None) or {}).get("CMAKE_GENERATOR"))
    Path(out_path).write_text(json.dumps(report, indent=1), encoding="utf-8")


def main():
    install.WINDOWED = True
    if len(sys.argv) == 3 and sys.argv[1] == "--selftest":
        sys.stdout = sys.stderr = open(str(Path(sys.argv[2]).with_suffix(".log")), "w", encoding="utf-8")
        selftest(sys.argv[2])
        return
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

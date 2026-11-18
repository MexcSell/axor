"""The Study Lab's shell and runners: Python inside Pyodide, in the browser (lab-worker.js loads this file).

- Lab.line(text): a line typed in the terminal. Three modes: sh (a small shell: pipes, redirects, && || ;, quotes,
  $VARS, ~ and globs, with built-in coreutils, python, pip, pytest, make and sqlite3), python (the interactive console)
  and sqlite (the sqlite3 shell). Answers {code, prompt, mode} and, for a few commands, a page action (open a file in the
  editor, download a file).
- Lab.run(path, stdin): a Python file, as `python path` runs it, with packages loaded from its imports.
- Lab.check(folder, tests): a lab task's or a project ticket's checks, every test_* function in `tests`, run in its folder.
- Lab.snapshot(folder) and Lab.changes(folder, base): a project's files as git would track them, and what changed since
  a snapshot as unified diffs (the ticket's "pull request").
- Lab.sql(db, query) and Lab.schema(db): the SQL playground. Lab.sample(path) writes its sample database.
- Files for the editor: files, read, write, remove, rename, all kept inside ~.
Output goes to the page through emit(stream, text), buffered so a tight print loop doesn't flood it, and capped.
Figures left open by matplotlib are sent as PNG images when a run ends.
"""
import base64, builtins, code, contextlib, fnmatch, glob, io, json, os, random, re, shutil, sqlite3, sys, time, traceback
from datetime import datetime, timedelta

try:
    import pyodide_js  # the JS side of Pyodide: loads packages
    from pyodide.code import find_imports
except ImportError:  # plain CPython (tests)
    pyodide_js = find_imports = None

MAX_OUT = 1_000_000   # characters a command may print
MAX_ROWS = 500        # rows the SQL playground returns per statement
MAX_FILE = 2_000_000  # bytes the editor opens
SKIP = {"__pycache__", ".pytest_cache", ".ipynb_checkpoints"}
UNSUPPORTED = {
    "git": "git isn't installed: the lab is Python in your browser, not a Linux machine. Practise git on your own computer.",
    "curl": "There's no network here: code in the lab can't reach the internet. Use the Prompts tab to call models.",
    "wget": "There's no network here: code in the lab can't reach the internet.",
    "ssh": "There's no network here.", "apt": "There's no package manager for system software here: pip installs Python packages.",
    "apt-get": "There's no package manager for system software here: pip installs Python packages.",
    "sudo": "There's no root here, and nothing needs it: ~ is yours.", "docker": "Docker doesn't run in the browser.",
    "npm": "Only Python runs in the lab.", "node": "Only Python runs in the lab.", "bash": "This is the lab's own shell: type commands here directly.",
    "sh": "This is the lab's own shell: type commands here directly.", "vim": None, "vi": None, "nano": None, "code": None,
}
README = """# Your lab

Python {py} runs here, in your browser (Pyodide): nothing you run reaches the server, and files in ~ are kept in this browser.

- **Terminal**: type `help`. Try `python hello.py`, `sqlite3 sample.db`, `pip install rich`, `pytest`.
- **Python**: open a file, edit it, press Run (Ctrl+Enter). matplotlib figures show under the output.
- **SQL**: sample.db is made-up data of an LLM app: its users, 3,000 model calls and two eval runs.
- **Tasks**: Get a task writes a hands-on exercise into ~/tasks, with checks that run here.
- **Projects**: onboarding repos in ~/projects. Read ONBOARDING.md, run `make test`, pick up tickets, ship 0.1.0.

There's no network: requests, curl and git don't work. `reset` in the terminal empties ~.
"""
HELLO = '''"""Your first lab program: a tiny eval of a mocked model call."""
import json
import statistics


def fake_model(prompt: str) -> str:
    """Stands in for an LLM call (there's no network in the lab)."""
    return json.dumps({"label": "billing" if "charge" in prompt else "other", "confidence": 0.9})


cases = [("I was charged twice", "billing"), ("How do I reset my password?", "account")]
scores = []
for text, want in cases:
    got = json.loads(fake_model(text))["label"]
    scores.append(got == want)
    print(f"{text!r:35} -> {got:8} {'✓' if got == want else '✗ expected ' + want}")

print(f"accuracy: {statistics.mean(scores):.0%}")
'''
NO_INPUT = "input() has nothing to read here: pipe text in (echo 42 | python app.py) or fill the Input box under the editor."

class ShellError(Exception): pass

class Out(io.TextIOBase):
    """Text for the page: buffered, sent at 4 KB or after 50 ms, and cut at MAX_OUT per command."""
    def __init__(self, lab, stream): self.lab, self.stream, self.buf, self.size, self.t = lab, stream, [], 0, time.monotonic()
    def writable(self): return True
    def isatty(self): return True
    def write(self, s):
        s = str(s)
        if self.lab.sent >= MAX_OUT: return len(s)
        self.lab.sent += len(s)
        if self.lab.sent >= MAX_OUT: s += "\n… output cut: that's more than the terminal keeps\n"
        if not self.buf: self.t = time.monotonic()  # 50 ms from the first unsent text
        self.buf.append(s); self.size += len(s)
        if self.size > 4096 or time.monotonic() - self.t > 0.05: self.flush()
        return len(s)
    def flush(self):
        if self.buf: self.lab.emit(self.stream, "".join(self.buf))
        self.buf, self.size, self.t = [], 0, time.monotonic()

class Stdin(io.StringIO):
    """What input() reads; an empty one explains how to give a program input."""
    def readline(self, *a):
        line = super().readline(*a)
        if not line: raise EOFError(NO_INPUT)
        return line

def _human(n):
    for u in ("", "K", "M", "G"):
        if n < 1024: return f"{n:.0f}{u}" if u == "" or n >= 10 else f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.0f}T"

BLUE, GREEN, RED, DIM, BOLD, RESET = "\x1b[1;34m", "\x1b[32m", "\x1b[31m", "\x1b[2m", "\x1b[1m", "\x1b[0m"

class Lab:
    def __init__(self, emit, home, user="learner"):
        self.emit, self.home, self.user = emit, home, user
        self.mode, self.console, self.db, self.sqlbuf, self.sent, self.prev = "sh", None, None, "", 0, home
        self.env = {"HOME": home, "USER": user, "PATH": "/usr/bin", "PWD": home, "SHELL": "lab", "LANG": "C.UTF-8"}
        self.out, self.err = Out(self, "out"), Out(self, "err")
        os.makedirs(home, exist_ok=True); os.chdir(home)
        os.environ.update(HOME=home, MPLBACKEND="Agg", COLUMNS="100")
        sys.dont_write_bytecode = True  # an edit of the same size within a second would run the old bytecode
        import warnings
        warnings.filterwarnings("ignore", message=".*non-interactive.*")  # plt.show() under Agg: the figure is sent after the run
        self.code = 0
        if not os.listdir(home):  # a new ~: something to start from
            with open(os.path.join(home, "README.md"), "w", encoding="utf-8") as f: f.write(README.format(py=sys.version.split()[0]))
            self.example(); self.sample()

    def example(self):
        """hello.py, the example program (written again if it was deleted)."""
        p = os.path.join(self.home, "hello.py")
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8") as f: f.write(HELLO)
        return {"path": "hello.py"}

    # ---------- paths ----------
    def inside(self, path):
        """A path from the page, resolved inside ~ (anything else is refused)."""
        path = str(path or "")
        mine = os.path.isabs(path) and (path == self.home or path.startswith(self.home + "/"))
        p = os.path.realpath(path if mine else os.path.join(self.home, path.lstrip("/")))
        if p != self.home and not p.startswith(self.home + "/"): raise ShellError("That path is outside your lab folder.")
        return p
    def rel(self, p): return os.path.relpath(p, self.home)
    def tilde(self, p):
        p = os.path.abspath(p)
        return "~" + p[len(self.home):] if p == self.home or p.startswith(self.home + "/") else p
    def prompt(self):
        if self.mode == "python": return "... " if self.console and self.console.buffer else ">>> "
        if self.mode == "sqlite": return "   ...> " if self.sqlbuf else "sqlite> "
        return f"{self.user}@lab:{self.tilde(os.getcwd())}$ "
    def state(self, code=0, **kw):
        self.out.flush(); self.err.flush()
        return {"code": code, "prompt": self.prompt(), "mode": self.mode, "cwd": self.tilde(os.getcwd()), **kw}

    # ---------- a line in the terminal ----------
    async def line(self, text, cols=100):
        self.sent, self.action = 0, None
        os.environ["COLUMNS"] = str(max(40, min(int(cols or 100), 300)))
        try: os.getcwd()
        except FileNotFoundError: os.chdir(self.home)  # the folder it was in was removed
        try:
            if self.mode == "python": code = await self.py_line(text)
            elif self.mode == "sqlite": code = self.sql_line(text)
            else:
                items = self.parse(text)
                code = await self.run_list(items) if items else self.code
        except ShellError as e:
            self.err.write(f"{e}\n"); code = 2
        except BaseException:  # a bug in the shell itself: say so rather than freeze
            self.err.write(traceback.format_exc()); code = 1
        self.code = code
        self.figures()
        return self.state(code, action=self.action)

    # ---------- parsing: words, quotes, $VARS, ~, globs and operators ----------
    OPS = ("2>&1", "2>>", "2>", "&&", "||", ">>", "|", ";", ">", "<", "&")
    def parse(self, text):
        toks, cur, have, glob_, i, n = [], [], False, False, 0, len(text)
        def word():
            nonlocal cur, have, glob_
            if have: toks.append(("w", cur, glob_))
            cur, have, glob_ = [], False, False
        def var(i):  # $NAME, ${NAME} and $?, expanded when the command runs (export X=1; echo $X)
            if text.startswith("${", i):
                j = text.find("}", i)
                if j < 0: raise ShellError("Missing } in ${…}.")
                return ("$", text[i + 2:j]), j + 1
            if text.startswith("$?", i): return ("$", "?"), i + 2
            m = re.match(r"\$([A-Za-z_][A-Za-z0-9_]*)", text[i:])
            return (("$", m.group(1)), i + len(m.group(0))) if m else ("$", i + 1)
        while i < n:
            c = text[i]
            if c in " \t": word(); i += 1; continue
            if c == "#" and not have: break
            op = next((o for o in self.OPS if text.startswith(o, i) and (not o.startswith("2") or not have)), None)
            if op: word(); toks.append(("op", op, False)); i += len(op); continue
            if c == "'":
                j = text.find("'", i + 1)
                if j < 0: raise ShellError("There's an unclosed ' quote.")
                cur.append(text[i + 1:j]); have = True; i = j + 1; continue
            if c == '"':
                i += 1; have = True
                while i < n and text[i] != '"':
                    if text[i] == "\\" and i + 1 < n and text[i + 1] in '"\\$`': cur.append(text[i + 1]); i += 2
                    elif text[i] == "$": v, i = var(i); cur.append(v)
                    else: cur.append(text[i]); i += 1
                if i >= n: raise ShellError('There\'s an unclosed " quote.')
                i += 1; continue
            if c == "\\" and i + 1 < n: cur.append(text[i + 1]); have = True; i += 2; continue
            if c == "$": v, i = var(i); cur.append(v); have = True; continue
            if c == "~" and not have and (i + 1 == n or text[i + 1] in "/ \t"): cur.append(self.home); have = True; i += 1; continue
            if c in "*?[": glob_ = True
            cur.append(c); have = True; i += 1
        word()
        # [(connector, [command]...)] where a command is {"argv": [(parts, glob)], "redir": [(op, parts)]}
        items, pipe, cmd, conn = [], [], {"argv": [], "redir": []}, None
        def end_cmd():
            nonlocal cmd
            if not cmd["argv"] and not cmd["redir"]: raise ShellError("Syntax error: a command is missing around | ; && or ||.")
            pipe.append(cmd); cmd = {"argv": [], "redir": []}
        k = 0
        while k < len(toks):
            kind, v, g = toks[k]
            if kind == "w": cmd["argv"].append((v, g))
            elif v == "&": raise ShellError("Background jobs (&) don't run here: commands run one at a time.")
            elif v in (">", ">>", "<", "2>", "2>>"):
                if k + 1 >= len(toks) or toks[k + 1][0] != "w": raise ShellError(f"Syntax error: {v} needs a file name after it.")
                cmd["redir"].append((v, toks[k + 1][1])); k += 1
            elif v == "2>&1": cmd["redir"].append((v, []))
            elif v == "|": end_cmd()
            else:  # ; && ||
                end_cmd(); items.append((conn, pipe)); pipe, conn = [], v
            k += 1
        if cmd["argv"] or cmd["redir"]: end_cmd()
        elif pipe or (toks and toks[-1][1] == "|"): raise ShellError("Syntax error: the line ends with |.")
        if pipe: items.append((conn, pipe))
        return items

    async def run_list(self, items):
        code = 0
        for conn, pipe in items:
            if (conn == "&&" and code != 0) or (conn == "||" and code == 0): continue
            code = await self.pipeline(pipe)
            self.code = code
            if self.mode != "sh": break  # python or sqlite took over the terminal
        return code

    async def pipeline(self, pipe):
        data, code = None, 0
        for i, c in enumerate(pipe):
            last = i == len(pipe) - 1
            out, err, files = (self.out if last else io.StringIO()), self.err, []
            for op, target in c["redir"]:
                target = self.text(target)
                if op == "<":
                    p = self.path(target)
                    if not os.path.isfile(p): raise ShellError(f"{target}: No such file")
                    data = open(p, encoding="utf-8", errors="replace").read()
                elif op == "2>&1": err = out
                else:
                    buf = io.StringIO(); files.append((self.path(target), "a" if op.endswith(">>") else "w", buf))
                    if op.startswith("2"): err = buf
                    else: out = buf
            argv = self.expand(c["argv"])
            try:
                code = await self.command(argv, data, out, err)
            finally:
                for p, mode, buf in files:
                    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
                    with open(p, mode, encoding="utf-8") as f: f.write(buf.getvalue())
            data = out.getvalue() if isinstance(out, io.StringIO) and not last else None
            if self.mode != "sh": break
        return code

    def text(self, parts):
        return "".join(x if isinstance(x, str) else str(self.code) if x[1] == "?" else self.env.get(x[1], "") for x in parts)

    def expand(self, words):
        out = []
        for parts, g in words:
            w = self.text(parts)
            hits = sorted(glob.glob(w)) if g else []
            out += hits or [w]
        return out

    def path(self, p): return os.path.abspath(os.path.expanduser(p) if p.startswith("~") else p)

    async def command(self, argv, data, out, err):
        if not argv: return 0
        while argv and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", argv[0]):  # NAME=value
            k, v = argv.pop(0).split("=", 1); self.env[k] = v
        if not argv: return 0
        name, args = argv[0], argv[1:]
        if name == "ll": args = ["-l", *args]
        name = {"python3": "python", "pip3": "pip", "ll": "ls", "dir": "ls", "py": "python"}.get(name, name)
        fn = getattr(self, "c_" + name.replace("-", "_"), None) if re.fullmatch(r"[a-z0-9_-]+", name) else None
        if name in UNSUPPORTED and name not in ("vim", "vi", "nano", "code"):
            err.write(f"{name}: {UNSUPPORTED[name]}\n"); return 127
        if name in ("vim", "vi", "nano", "code"): fn = self.c_edit
        if not fn:
            err.write(f"{name}: command not found. Type help for what runs here.\n"); return 127
        try:
            r = fn(args, data, out, err)
            if hasattr(r, "__await__"): r = await r
            return r or 0
        except ShellError as e:
            err.write(f"{name}: {e}\n"); return 1
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError, FileExistsError, PermissionError, OSError) as e:
            err.write(f"{name}: {e.filename + ': ' if getattr(e, 'filename', None) else ''}{e.strerror or e}\n"); return 1

    @staticmethod
    def opts(args, flags, values=()):
        """-abc style switches (and -n 5 style values) before the operands."""
        on, vals, rest, i = set(), {}, [], 0
        while i < len(args):
            a = args[i]
            if a == "--": rest += args[i + 1:]; break
            if a.startswith("-") and len(a) > 1 and not re.fullmatch(r"-\d+", a):
                for j, ch in enumerate(a[1:]):
                    if ch in values:
                        v = a[j + 2:] or (args[i + 1] if i + 1 < len(args) else None)
                        if v is None: raise ShellError(f"-{ch} needs a value")
                        if not a[j + 2:]: i += 1
                        vals[ch] = v; break
                    if ch not in flags: raise ShellError(f"unknown option -{ch}")
                    on.add(ch)
            else: rest.append(a)
            i += 1
        return on, vals, rest

    def texts(self, files, data, name):
        """(label, text) for each operand, or stdin when there are none."""
        if not files:
            if data is None: raise ShellError("give a file name (or pipe text in)")
            return [("-", data)]
        out = []
        for f in files:
            p = self.path(f)
            if os.path.isdir(p): raise ShellError(f"{f}: Is a directory")
            if not os.path.exists(p): raise ShellError(f"{f}: No such file")
            out.append((f, open(p, encoding="utf-8", errors="replace").read()))
        return out

    # ---------- built-in commands ----------
    def c_help(self, args, data, out, err):
        out.write(f"""{BOLD}The lab's shell{RESET}: Python 3.{sys.version_info.minor} in your browser (Pyodide). Nothing you run reaches the server.
Files in ~ are kept in this browser; download what you want to keep elsewhere.

{BOLD}Files{RESET}      ls [-la]  cd  pwd  tree  cat  head  tail  wc  mkdir [-p]  touch  cp [-r]  mv  rm [-r]  rmdir
{BOLD}Text{RESET}       echo  grep [-inrvcl]  find [-name -type]  sort [-rnu]  uniq [-c]  cut  tr  sed s/a/b/g
{BOLD}Python{RESET}     python [file.py | -c code | -m module]   python (no file: the interactive console)
           pip install|list|uninstall  pytest   (numpy, pandas, scikit-learn, matplotlib… load on import)
{BOLD}Build{RESET}      make [target…] [-n] [-C dir]   (a project's Makefile: make help lists its targets)
{BOLD}SQL{RESET}        sqlite3 [file.db] ["SELECT …"]   (no query: the sqlite3 shell, .tables .schema .quit)
{BOLD}Shell{RESET}      a | b   a > file   a >> file   a < file   a && b   a || b   a ; b   $VAR  export  env  which  history  clear
{BOLD}Lab{RESET}        edit file (opens it in the Python tab)   download file   reset (empties ~)

{DIM}No network or subprocesses: requests, curl and git don't work here. Ctrl+C stops a running program, ↑ ↓ history, Tab completes.{RESET}
""")

    def c_pwd(self, args, data, out, err): out.write(os.getcwd() + "\n")

    def c_cd(self, args, data, out, err):
        t = args[0] if args else self.home
        if t == "-": t = self.prev
        p = self.path(t)
        if not os.path.isdir(p): raise ShellError(f"{t}: No such directory")
        self.prev = os.getcwd(); os.chdir(p); self.env["PWD"] = p

    def c_ls(self, args, data, out, err):
        on, _, rest = self.opts(args, "alh1RtrS")
        targets, code = rest or ["."], 0
        cols = int(os.environ.get("COLUMNS", 100))
        for k, t in enumerate(targets):
            p = self.path(t)
            if not os.path.exists(p): err.write(f"ls: {t}: No such file or directory\n"); code = 1; continue
            if os.path.isdir(p):
                names = [x for x in os.listdir(p) if "a" in on or not x.startswith(".")]
                if "a" in on: names += [".", ".."]
            else: names, p = [os.path.basename(p)], os.path.dirname(p) or "."
            key = (lambda x: -os.stat(os.path.join(p, x)).st_mtime) if "t" in on else (lambda x: -os.stat(os.path.join(p, x)).st_size) if "S" in on else str.lower
            names.sort(key=key, reverse="r" in on)
            if len(targets) > 1: out.write(("\n" if k else "") + f"{t}:\n")
            paint = lambda x: f"{BLUE}{x}{RESET}" if os.path.isdir(os.path.join(p, x)) else f"{GREEN}{x}{RESET}" if x.endswith((".py", ".sh")) else x
            if "l" in on:
                for x in names:
                    st = os.stat(os.path.join(p, x)); d = os.path.isdir(os.path.join(p, x))
                    size = _human(st.st_size) if "h" in on else str(st.st_size)
                    out.write(f"{'drwxr-xr-x' if d else '-rw-r--r--'}  {self.user}  {size:>8}  {datetime.fromtimestamp(st.st_mtime):%b %d %H:%M}  {paint(x)}\n")
            elif "1" in on or out is not self.out:
                for x in names: out.write(x + "\n")
            elif names:
                w = max(len(x) for x in names) + 2; per = max(1, cols // w); rows = -(-len(names) // per)
                for r in range(rows):
                    row = [names[c * rows + r] for c in range(per) if c * rows + r < len(names)]
                    out.write("".join(paint(x) + " " * (w - len(x)) for x in row).rstrip() + "\n")
        return code

    def c_tree(self, args, data, out, err):
        root = self.path(args[0] if args else "."); dirs = files = 0
        out.write(f"{BLUE}{args[0] if args else '.'}{RESET}\n")
        def walk(d, pre):
            nonlocal dirs, files
            xs = sorted((x for x in os.listdir(d) if not x.startswith(".") and x not in SKIP), key=str.lower)
            for i, x in enumerate(xs):
                p, last = os.path.join(d, x), i == len(xs) - 1
                out.write(f"{pre}{'└── ' if last else '├── '}{BLUE + x + RESET if os.path.isdir(p) else x}\n")
                if os.path.isdir(p): dirs += 1; walk(p, pre + ("    " if last else "│   "))
                else: files += 1
        walk(root, "")
        out.write(f"\n{dirs} director{'y' if dirs == 1 else 'ies'}, {files} file{'' if files == 1 else 's'}\n")

    def c_cat(self, args, data, out, err):
        on, _, rest = self.opts(args, "n")
        for _, t in self.texts(rest, data, "cat"):
            if "n" in on: t = "".join(f"{i + 1:6}\t{l}" for i, l in enumerate(t.splitlines(True)))
            out.write(t)

    def _headtail(self, args, data, out, tail):
        args = [f"-n{a[1:]}" if re.fullmatch(r"-\d+", a) else a for a in args]
        _, vals, rest = self.opts(args, "", "n")
        n = int(vals.get("n", 10))
        many = len(rest) > 1
        for i, (f, t) in enumerate(self.texts(rest, data, "head")):
            if many: out.write(("\n" if i else "") + f"==> {f} <==\n")
            lines = t.splitlines(True)
            out.write("".join(lines[-n:] if tail and n else lines[:n]))
    def c_head(self, args, data, out, err): self._headtail(args, data, out, False)
    def c_tail(self, args, data, out, err): self._headtail(args, data, out, True)

    def c_wc(self, args, data, out, err):
        on, _, rest = self.opts(args, "lwc")
        on = on or {"l", "w", "c"}
        tot = [0, 0, 0]
        texts = self.texts(rest, data, "wc")
        for f, t in texts:
            v = [t.count("\n"), len(t.split()), len(t.encode())]
            tot = [a + b for a, b in zip(tot, v)]
            out.write("".join(f"{x:>8}" for x, k in zip(v, "lwc") if k in on) + (f" {f}" if f != "-" else "") + "\n")
        if len(texts) > 1: out.write("".join(f"{x:>8}" for x, k in zip(tot, "lwc") if k in on) + " total\n")

    def c_echo(self, args, data, out, err):
        nl = True
        if args and args[0] == "-n": nl, args = False, args[1:]
        if args and args[0] == "-e": args = [a.encode().decode("unicode_escape") for a in args[1:]]
        out.write(" ".join(args) + ("\n" if nl else ""))

    def c_grep(self, args, data, out, err):
        on, vals, rest = self.opts(args, "inrvclEFwHho", "e")
        pat = vals.get("e")
        if pat is None:
            if not rest: raise ShellError("usage: grep [-inrvcl] PATTERN [FILE…]")
            pat, rest = rest[0], rest[1:]
        pat = re.escape(pat) if "F" in on else pat.replace(r"\|", "|").replace(r"\(", "(").replace(r"\)", ")") if "E" not in on else pat
        if "w" in on: pat = rf"\b(?:{pat})\b"
        try: rx = re.compile(pat, re.I if "i" in on else 0)
        except re.error as e: raise ShellError(f"bad pattern: {e}")
        if "r" in on:
            files = []
            for t in rest or ["."]:
                p = self.path(t)
                if os.path.isdir(p):
                    for d, ds, fs in os.walk(p):
                        ds[:] = sorted(x for x in ds if not x.startswith(".") and x not in SKIP)
                        files += [os.path.relpath(os.path.join(d, f)) for f in sorted(fs)]
                else: files.append(t)
            rest = files
        many, found = (len(rest) > 1 or "r" in on) and "h" not in on or "H" in on, False
        for f, t in self.texts(rest, data, "grep"):
            if "\0" in t[:1024]: continue  # binary
            n = 0
            for i, line in enumerate(t.splitlines()):
                m = rx.search(line)
                if bool(m) == ("v" in on): continue
                n += 1; found = True
                if "l" in on: break
                if "c" in on: continue
                shown = rx.sub(lambda x: f"{RED}{BOLD}{x.group(0)}{RESET}", line) if out is self.out and "v" not in on else line
                if "o" in on: shown = "\n".join(x.group(0) for x in rx.finditer(line))
                out.write((f"{f}:" if many else "") + (f"{i + 1}:" if "n" in on else "") + shown + "\n")
            if "l" in on and n: out.write(f + "\n")
            if "c" in on: out.write((f"{f}:" if many else "") + f"{n}\n")
        return 0 if found else 1

    def c_find(self, args, data, out, err):
        roots = []
        while args and not args[0].startswith("-"): roots.append(args.pop(0))
        name = typ = None; iname = False
        while args:
            a = args.pop(0)
            if a in ("-name", "-iname") and args: name, iname = args.pop(0), a == "-iname"
            elif a == "-type" and args: typ = args.pop(0)
            else: raise ShellError(f"unknown option {a} (this find knows -name, -iname and -type)")
        for r in roots or ["."]:
            p = self.path(r)
            if not os.path.exists(p): raise ShellError(f"{r}: No such file or directory")
            for d, ds, fs in os.walk(p):
                ds.sort(); fs.sort()
                for x, isdir in [(d, True)] + [(os.path.join(d, f), False) for f in fs]:
                    if typ and (typ == "d") != isdir: continue
                    base = os.path.basename(x)
                    if name and not fnmatch.fnmatch(base.lower() if iname else base, name.lower() if iname else name): continue
                    out.write((r.rstrip("/") + x[len(p):] if x != p else r) + "\n")

    def c_sort(self, args, data, out, err):
        on, _, rest = self.opts(args, "rnuf")
        lines = [l for _, t in self.texts(rest, data, "sort") for l in t.splitlines()]
        num = lambda l: (float(m.group()) if (m := re.match(r"\s*-?\d+(\.\d+)?", l)) else 0.0)
        key = num if "n" in on else (str.lower if "f" in on else None)
        lines.sort(key=key, reverse="r" in on)
        if "u" in on: lines = list(dict.fromkeys(lines))
        out.write("".join(l + "\n" for l in lines))

    def c_uniq(self, args, data, out, err):
        on, _, rest = self.opts(args, "cd")
        prev, n, rows = None, 0, []
        for l in [l for _, t in self.texts(rest, data, "uniq") for l in t.splitlines()] + [None]:
            if l == prev: n += 1; continue
            if prev is not None and ("d" not in on or n > 1): rows.append(f"{n:>7} {prev}" if "c" in on else prev)
            prev, n = l, 1
        out.write("".join(r + "\n" for r in rows))

    def c_cut(self, args, data, out, err):
        _, vals, rest = self.opts(args, "", "dfc")
        def picks(spec, n):
            got = []
            for part in spec.split(","):
                a, _, b = part.partition("-")
                lo = int(a) if a else 1; hi = (int(b) if b else n) if "-" in part else lo
                got += range(lo, hi + 1)
            return got
        for _, t in self.texts(rest, data, "cut"):
            for l in t.splitlines():
                if "c" in vals: out.write("".join(l[i - 1] for i in picks(vals["c"], len(l)) if i <= len(l)) + "\n")
                else:
                    d = vals.get("d", "\t"); fs = l.split(d)
                    out.write(d.join(fs[i - 1] for i in picks(vals.get("f", "1"), len(fs)) if i <= len(fs)) + "\n")

    def c_tr(self, args, data, out, err):
        on, _, rest = self.opts(args, "d")
        if data is None: raise ShellError("tr reads piped text: echo hello | tr a-z A-Z")
        rng = lambda s: re.sub(r"(.)-(.)", lambda m: "".join(chr(c) for c in range(ord(m.group(1)), ord(m.group(2)) + 1)), s.encode().decode("unicode_escape"))
        if "d" in on: out.write(data.translate({ord(c): None for c in rng(rest[0])})); return
        if len(rest) < 2: raise ShellError("usage: tr SET1 SET2")
        a, b = rng(rest[0]), rng(rest[1]); b = b + b[-1:] * (len(a) - len(b))
        out.write(data.translate(str.maketrans(a, b[:len(a)])))

    def c_sed(self, args, data, out, err):
        on, _, rest = self.opts(args, "iE")
        if not rest: raise ShellError("this sed knows s/old/new/[g] (and -i to edit files in place)")
        m = re.fullmatch(r"s(.)(.*?)(?<!\\)\1(.*?)(?<!\\)\1([gi]*)", rest[0])
        if not m: raise ShellError("this sed knows s/old/new/[g] only")
        rx = re.compile(m.group(2), re.I if "i" in m.group(4) else 0)
        rep = re.sub(r"\\(\d)", r"\\g<\1>", m.group(3)).replace("&", r"\g<0>")
        sub = lambda t: "\n".join(rx.sub(rep, l, count=0 if "g" in m.group(4) else 1) for l in t.split("\n"))
        if "i" in on:
            for f in rest[1:]:
                p = self.path(f); t = open(p, encoding="utf-8").read(); open(p, "w", encoding="utf-8").write(sub(t))
            return
        for _, t in self.texts(rest[1:], data, "sed"): out.write(sub(t))

    def c_mkdir(self, args, data, out, err):
        on, _, rest = self.opts(args, "p")
        if not rest: raise ShellError("missing directory name")
        for d in rest:
            p = self.path(d)
            if "p" in on: os.makedirs(p, exist_ok=True)
            elif os.path.exists(p): raise ShellError(f"{d}: File exists")
            else: os.mkdir(p)

    def c_touch(self, args, data, out, err):
        if not args: raise ShellError("missing file name")
        for f in args:
            p = self.path(f)
            if os.path.exists(p): os.utime(p)
            else: open(p, "a").close()

    def c_rm(self, args, data, out, err):
        on, _, rest = self.opts(args, "rfRv")
        if not rest and "f" not in on: raise ShellError("missing file name")
        code = 0
        for f in rest:
            p = self.path(f)
            if os.path.realpath(p) in (self.home, "/"): raise ShellError(f"refusing to remove {f}: use reset to empty ~")
            if not os.path.lexists(p):
                if "f" not in on: err.write(f"rm: {f}: No such file or directory\n"); code = 1
                continue
            if os.path.isdir(p) and not os.path.islink(p):
                if not on & {"r", "R"}: err.write(f"rm: {f}: is a directory (use rm -r)\n"); code = 1; continue
                shutil.rmtree(p)
            else: os.remove(p)
            if "v" in on: out.write(f"removed {f}\n")
        return code

    def c_rmdir(self, args, data, out, err):
        for d in args: os.rmdir(self.path(d))

    def c_cp(self, args, data, out, err):
        on, _, rest = self.opts(args, "rRf")
        if len(rest) < 2: raise ShellError("usage: cp [-r] SOURCE… DEST")
        *srcs, dst = rest; dp = self.path(dst)
        if len(srcs) > 1 and not os.path.isdir(dp): raise ShellError(f"{dst}: is not a directory")
        for s in srcs:
            sp = self.path(s); t = os.path.join(dp, os.path.basename(sp)) if os.path.isdir(dp) else dp
            if os.path.isdir(sp):
                if not on & {"r", "R"}: raise ShellError(f"{s} is a directory (use cp -r)")
                shutil.copytree(sp, t, dirs_exist_ok=True)
            else: shutil.copy2(sp, t)

    def c_mv(self, args, data, out, err):
        _, _, rest = self.opts(args, "fv")
        if len(rest) < 2: raise ShellError("usage: mv SOURCE… DEST")
        *srcs, dst = rest; dp = self.path(dst)
        if len(srcs) > 1 and not os.path.isdir(dp): raise ShellError(f"{dst}: is not a directory")
        for s in srcs: shutil.move(self.path(s), dp)

    def c_env(self, args, data, out, err): out.write("".join(f"{k}={v}\n" for k, v in sorted(self.env.items())))
    def c_export(self, args, data, out, err):
        for a in args:
            if "=" in a: k, v = a.split("=", 1); self.env[k] = v
    def c_unset(self, args, data, out, err):
        for a in args: self.env.pop(a, None)
    def c_whoami(self, args, data, out, err): out.write(self.user + "\n")
    def c_date(self, args, data, out, err): out.write(datetime.now().strftime("%a %b %d %H:%M:%S %Y") + "\n")
    def c_true(self, args, data, out, err): return 0
    def c_false(self, args, data, out, err): return 1
    def c_which(self, args, data, out, err):
        code = 0
        for a in args:
            if hasattr(self, "c_" + a) or a in ("python3", "pip3"): out.write(f"{a}: lab built-in\n")
            else: err.write(f"{a} not found\n"); code = 1
        return code

    def c_edit(self, args, data, out, err):
        if not args: raise ShellError("usage: edit FILE (opens it in the Python tab)")
        p = self.path(args[0])
        if os.path.isdir(p): raise ShellError(f"{args[0]} is a directory")
        if not os.path.exists(p): os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").close()
        self.action = {"open": self.rel(self.inside(p))}
        out.write(f"{DIM}Opened {self.tilde(p)} in the Python tab.{RESET}\n")

    def c_download(self, args, data, out, err):
        if not args: raise ShellError("usage: download FILE")
        p = self.inside(self.path(args[0]))
        if not os.path.isfile(p): raise ShellError(f"{args[0]}: No such file")
        self.action = {"download": self.rel(p)}

    def c_reset(self, args, data, out, err):
        self.action = {"reset": True}
        out.write(f"{DIM}Confirm in the dialog to empty ~.{RESET}\n")

    def c_history(self, args, data, out, err): self.action = {"history": True}
    def c_clear(self, args, data, out, err): self.action = {"clear": True}
    def c_exit(self, args, data, out, err): out.write(f"{DIM}This terminal stays open: it's the lab. Leave the tab whenever you like.{RESET}\n")

    # ---------- python ----------
    def purge(self):
        """Forget modules imported from the learner's files, so edits are picked up on the next run."""
        for k, m in list(sys.modules.items()):
            f = getattr(m, "__file__", None) or ""
            if f.startswith((self.home + "/", "/tmp/lab")): del sys.modules[k]

    async def load_imports(self, src, folder=None):
        """Load the Pyodide packages a program imports (numpy, pandas…) before it runs."""
        if not pyodide_js: return
        srcs = [src]
        if folder:  # local modules the program imports may need packages too
            for f in sorted(glob.glob(os.path.join(folder, "*.py")))[:40]:
                try: srcs.append(open(f, encoding="utf-8").read())
                except OSError: pass
        import importlib.util
        names, here = set(), [folder or os.getcwd(), os.getcwd()]
        for s in srcs:
            try: names |= {n.split(".")[0] for n in find_imports(s)}
            except SyntaxError: pass
        local = lambda n: any(os.path.exists(os.path.join(d, n + ".py")) or os.path.isdir(os.path.join(d, n)) for d in here)
        missing = sorted(n for n in names if n not in sys.modules and n not in sys.stdlib_module_names and not local(n) and importlib.util.find_spec(n) is None)
        if missing:  # the loader writes "Loading numpy" itself
            try: await pyodide_js.loadPackagesFromImports("\n".join(f"import {n}" for n in missing))
            except Exception: pass  # an unknown package: the import error says so

    async def c_python(self, args, data, out, err):
        if not args:
            self.mode = "python"
            self.console = code.InteractiveConsole({"__name__": "__console__", "__builtins__": builtins})
            out.write(f"Python {sys.version.split()[0]} (Pyodide) in your browser. exit() or Ctrl+D leaves.\n")
            return 0
        if args[0] in ("-V", "--version"): out.write(f"Python {sys.version.split()[0]}\n"); return 0
        if args[0] == "-c":
            if len(args) < 2: raise ShellError("-c needs code: python -c \"print(1 + 1)\"")
            return await self.exec_src(args[1], "<string>", ["-c", *args[2:]], data, out, err)
        if args[0] == "-m":
            if len(args) < 2: raise ShellError("-m needs a module name")
            mod, rest = args[1], args[2:]
            if mod == "pip": return await self.c_pip(rest, data, out, err)
            if mod == "pytest": return await self.c_pytest(rest, data, out, err)
            return await self.exec_module(mod, rest, data, out, err)
        p = self.path(args[0])
        if not os.path.isfile(p): raise ShellError(f"can't open file '{args[0]}': No such file")
        src = open(p, encoding="utf-8", errors="replace").read()
        return await self.exec_src(src, p, [args[0], *args[1:]], data, out, err)

    async def exec_src(self, src, path, argv, data, out, err):
        folder = os.path.dirname(path) if path.startswith("/") else os.getcwd()
        await self.load_imports(src, folder)
        try: compiled = compile(src, path, "exec")
        except SyntaxError:
            traceback.print_exception(*sys.exc_info()[:2], None, file=err); return 1
        g = {"__name__": "__main__", "__file__": path, "__builtins__": builtins}
        return self.guarded(lambda: exec(compiled, g), argv, folder, data, out, err, path)

    async def exec_module(self, mod, rest, data, out, err):
        import runpy
        await self.load_imports(f"import {mod}")
        return self.guarded(lambda: runpy.run_module(mod, run_name="__main__", alter_sys=True), [mod, *rest], os.getcwd(), data, out, err, None)

    def guarded(self, run, argv, folder, data, out, err, path):
        """Runs a program with its argv, stdin and output, and prints its traceback without the lab's own frames."""
        self.purge()
        saved = sys.argv, sys.stdin, list(sys.path), os.getcwd()
        sys.argv, sys.stdin = argv, Stdin(data or "")
        sys.path.insert(0, folder)
        code = 0
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try: run()
                except SystemExit as e:
                    if e.code not in (None, 0):
                        if not isinstance(e.code, int): print(e.code, file=sys.stderr)
                        code = e.code if isinstance(e.code, int) else 1
                except BaseException as e:
                    te = traceback.TracebackException(type(e), e, e.__traceback__)
                    te.stack = traceback.StackSummary.from_list([f for f in te.stack if f.filename != __file__ and not f.filename.endswith("runpy.py")])
                    print("".join(te.format()), end="", file=sys.stderr)
                    code = 1
                finally:
                    sys.stdout.flush()
        finally:
            sys.argv, sys.stdin = saved[0], saved[1]
            sys.path[:] = saved[2]
            if os.path.isdir(saved[3]) and os.getcwd() != saved[3]: os.chdir(saved[3])
        return code

    async def py_line(self, text):
        if text == "\x03": self.console.resetbuffer(); return 0  # Ctrl+C: drop the half-typed statement
        if text.strip() in ("exit()", "quit()", "exit", "quit", "\x04"):
            self.mode, self.console = "sh", None; return 0
        await self.load_imports(text)
        with contextlib.redirect_stdout(self.out), contextlib.redirect_stderr(self.err):
            try: self.console.push(text)
            except SystemExit: self.mode, self.console = "sh", None
        return 0

    async def c_pip(self, args, data, out, err):
        if not pyodide_js: raise ShellError("pip needs the browser's Python")
        await pyodide_js.loadPackage("micropip")
        import micropip
        sub, rest = (args[0] if args else "help"), args[1:]
        if sub == "install":
            names, i = [], 0
            while i < len(rest):
                a = rest[i]
                if a in ("-r", "--requirement") and i + 1 < len(rest):
                    p = self.path(rest[i + 1]); i += 1
                    names += [l.split("#")[0].strip() for l in open(p, encoding="utf-8") if l.split("#")[0].strip() and not l.startswith("-")]
                elif a.endswith(".whl") and os.path.isfile(self.path(a)): names.append("emfs:" + self.path(a))  # a wheel you built
                elif not a.startswith("-"): names.append(a)
                i += 1
            if not names: raise ShellError("usage: pip install PACKAGE… (or -r requirements.txt)")
            before = {k: v.version for k, v in micropip.list().items()}
            out.write(f"Installing {', '.join(names)}…\n"); out.flush()
            try: await micropip.install(names)
            except Exception as e:
                msg = str(e).split("\n")[0]
                err.write(f"pip: {msg}\n{DIM}The lab installs packages built for Pyodide and pure-Python wheels from PyPI; packages with compiled code Pyodide doesn't ship can't be installed.{RESET}\n")
                return 1
            new = sorted(f"{k}-{v.version}" for k, v in micropip.list().items() if before.get(k) != v.version)
            out.write(f"Successfully installed {' '.join(new)}\n" if new else "Requirement already satisfied.\n")
            return 0
        if sub in ("list", "freeze"):
            for k, v in sorted(micropip.list().items()): out.write(f"{k}=={v.version}\n" if sub == "freeze" else f"{k:<32}{v.version}\n")
            return 0
        if sub == "uninstall":
            names = [a for a in rest if not a.startswith("-")]
            micropip.uninstall(names); out.write(f"Uninstalled {' '.join(names)}\n"); return 0
        if sub == "show":
            have = micropip.list()
            for n in rest:
                v = have.get(n)
                out.write(f"Name: {n}\nVersion: {v.version}\nSource: {v.source}\n" if v else f"WARNING: Package not found: {n}\n")
            return 0
        out.write("usage: pip install PACKAGE… | pip install -r requirements.txt | pip list | pip freeze | pip show NAME | pip uninstall NAME\n")
        return 0 if sub == "help" else 1

    async def c_pytest(self, args, data, out, err):
        if pyodide_js: await pyodide_js.loadPackage("pytest")
        import pytest
        self.purge()
        for k in [k for k in sys.modules if k.startswith("test_") or k == "conftest"]: del sys.modules[k]
        saved = list(sys.path); sys.path.insert(0, os.getcwd())
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = int(pytest.main(["-p", "no:cacheprovider", "--color=yes", "--capture=sys", *args]))
        finally:
            sys.path[:] = saved
        return code

    # ---------- make: a project's Makefile ----------
    def makefile(self):
        """The Makefile here: its variables and its rules, {target: {deps, recipe: [(line, text)], help}} in order.
        Recipe lines may start with spaces as well as a tab: the lab's editor indents with spaces."""
        name = next((x for x in ("GNUmakefile", "makefile", "Makefile") if os.path.isfile(x)), None)
        if not name: raise ShellError("*** No targets specified and no makefile found.  Stop.")
        vars_, rules, cur = {}, {}, []
        for n, raw in enumerate(open(name, encoding="utf-8", errors="replace").read().replace("\\\n", " ").split("\n"), 1):
            if raw[:1] in ("\t", " ") and cur:
                if raw.strip() and not raw.strip().startswith("#"):
                    for t in cur: rules[t]["recipe"].append((n, raw.strip()))
                continue
            line = raw.split("#", 1)[0].rstrip()
            if not line.strip(): continue
            m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*(\?=|:=|::=|\+=|=)\s*(.*)$", line)
            if m:
                k, op, v = m.groups()
                if op != "?=" or k not in vars_: vars_[k] = f"{vars_.get(k, '')} {v}".strip() if op == "+=" else v
                cur = []; continue
            m = re.match(r"([^:=]+?)\s*::?\s*(.*)$", line)
            if not m: raise ShellError(f"{name}:{n}: *** missing separator.  Stop.")
            cur = [t for t in self.mexpand(m.group(1), vars_).split() if not t.startswith(".")]  # .PHONY and friends
            for t in cur:
                r = rules.setdefault(t, {"deps": [], "recipe": [], "help": ""})
                r["deps"] += self.mexpand(m.group(2), vars_).split()
                r["help"] = r["help"] or (raw.split("##", 1)[1].strip() if "##" in raw else "")
        return name, vars_, rules

    def mexpand(self, text, vars_, target="", depth=0):
        """$(NAME), ${NAME}, $@ and $$ in a Makefile line; variables can use variables."""
        def sub(m):
            x = m.group(0)
            if x == "$$": return "$"
            if x == "$@": return target
            k = m.group(1) or m.group(2)
            return self.mexpand(vars_[k], vars_, target, depth + 1) if k in vars_ and depth < 10 else self.env.get(k, "")
        return re.sub(r"\$\$|\$@|\$\(([A-Za-z_][A-Za-z0-9_]*)\)|\$\{([A-Za-z_][A-Za-z0-9_]*)\}", sub, text)

    async def c_make(self, args, data, out, err):
        """make [-n] [-s] [-C dir] [target…]: runs the Makefile's recipes, prerequisites first, each line in this shell.
        Every target runs when asked for (there are no timestamps); help lists the targets if the Makefile has no rule."""
        on, vals, goals = self.opts(args, "ns", "C")
        was = os.getcwd()
        try:
            if "C" in vals: os.chdir(self.path(vals["C"]))
            name, vars_, rules = self.makefile()
            if not goals: goals = [next(iter(rules), "")]
            if goals == ["help"] and not rules.get("help", {}).get("recipe"):
                for t, r in rules.items(): out.write(f"{t:<14}{r['help']}\n")
                return 0
            done = set()
            async def build(t, chain):
                if t in done: return 0
                if t in chain: err.write(f"make: Circular {chain[-1]} <- {t} dependency dropped.\n"); return 0
                if t not in rules:
                    if os.path.exists(t): return 0  # a file it depends on
                    err.write(f"make: *** No rule to make target '{t}'{f', needed by {chain[-1]!r}' if chain else ''}.  Stop.\n"); return 2
                for d in rules[t]["deps"]:
                    if (code := await build(d, chain + [t])): return code
                for n, line in rules[t]["recipe"]:
                    cmd, quiet, keep = self.mexpand(line, vars_, t), False, False
                    while cmd[:1] in ("@", "-", "+"):
                        quiet |= cmd[0] == "@"; keep |= cmd[0] == "-"; cmd = cmd[1:].lstrip()
                    if (not quiet or "n" in on) and "s" not in on: out.write(f"{cmd}\n")
                    if "n" in on: continue
                    code = await self.recipe(cmd, out, err)
                    if code and not keep: err.write(f"make: *** [{name}:{n}: {t}] Error {code}\n"); return 2
                    if code: err.write(f"make: [{name}:{n}: {t}] Error {code} (ignored)\n")
                done.add(t)
                return 0
            for g in goals:
                if (code := await build(g, [])): return code
            return 0
        finally:
            if os.path.isdir(was): os.chdir(was)

    async def recipe(self, cmd, out, err):
        """One recipe line, run as if in its own shell: a cd, or a python console it opens, doesn't outlast the line."""
        was, saved = os.getcwd(), (self.out, self.err)
        self.out, self.err = out, err  # the last command of a pipeline writes to self.out
        try:
            items = self.parse(cmd)
            return await self.run_list(items) if items else 0
        except ShellError as e:
            err.write(f"{e}\n"); return 2
        finally:
            self.out, self.err = saved
            if self.mode != "sh": self.mode, self.console, self.db, self.sqlbuf = "sh", None, None, ""
            if os.path.isdir(was): os.chdir(was)

    def figures(self):
        """matplotlib figures left open by a run, sent to the page as PNG images."""
        plt = sys.modules.get("matplotlib.pyplot")
        if not plt: return
        try:
            for n in plt.get_fignums()[:6]:
                buf = io.BytesIO(); plt.figure(n).savefig(buf, format="png", dpi=96, bbox_inches="tight")
                self.emit("img", base64.b64encode(buf.getvalue()).decode())
        finally:
            plt.close("all")

    # ---------- sqlite ----------
    def c_sqlite3(self, args, data, out, err):
        db = self.path(args[0]) if args else ":memory:"
        sql = " ".join(args[1:]) if len(args) > 1 else data
        if sql:
            con = sqlite3.connect(db)
            try: return self.sql_script(con, sql, out, err)
            finally: con.close()
        self.mode, self.db, self.sqlbuf = "sqlite", sqlite3.connect(db), ""
        self.sqlmode, self.headers = "box", True
        out.write(f"SQLite {sqlite3.sqlite_version} · {self.tilde(db) if db != ':memory:' else 'an in-memory database'}\n"
                  f"{DIM}End statements with ; · .tables .schema [table] .headers on|off .mode box|csv|list .quit{RESET}\n")

    def sql_line(self, text):
        if text == "\x03": self.sqlbuf = ""; return 0
        t = text.strip()
        if not self.sqlbuf and t.startswith("."):
            cmd, *rest = t.split()
            if cmd in (".quit", ".exit", ".q"): self.db.close(); self.mode, self.db = "sh", None; return 0
            if cmd == ".tables":
                names = [r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name")]
                self.out.write("  ".join(names) + "\n" if names else ""); return 0
            if cmd == ".schema":
                q = "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL" + (" AND tbl_name=?" if rest else "") + " ORDER BY name"
                for (s,) in self.db.execute(q, rest[:1]): self.out.write(s + ";\n")
                return 0
            if cmd == ".headers" and rest: self.headers = rest[0] == "on"; return 0
            if cmd == ".mode" and rest and rest[0] in ("box", "csv", "list", "column", "table"): self.sqlmode = rest[0]; return 0
            if cmd == ".help": self.out.write(".tables  .schema [TABLE]  .headers on|off  .mode box|csv|list  .quit\n"); return 0
            self.err.write(f"Unknown command {cmd}: try .help\n"); return 1
        self.sqlbuf += text + "\n"
        if not sqlite3.complete_statement(self.sqlbuf): return 0
        sql, self.sqlbuf = self.sqlbuf, ""
        return self.sql_script(self.db, sql, self.out, self.err, self.sqlmode, self.headers)

    @staticmethod
    def statements(sql):
        """The statements in a script, split where sqlite3 says one is complete (semicolons in strings are safe)."""
        out, cur = [], ""
        for part in sql.split(";"):
            cur += part + ";"
            if sqlite3.complete_statement(cur):
                if cur.strip(" \n\t;"): out.append(cur.strip())
                cur = ""
        if cur.strip(" \n\t;"): out.append(cur.strip().rstrip(";"))
        return out

    def sql_script(self, con, sql, out, err, mode="box", headers=True):
        for st in self.statements(sql):
            try:
                cur = con.execute(st)
                if cur.description:
                    cols = [d[0] for d in cur.description]; rows = cur.fetchmany(1001)
                    self.table(cols, rows[:1000], out, mode, headers)
                    if len(rows) > 1000: out.write(f"{DIM}… more rows not shown{RESET}\n")
                con.commit()
            except sqlite3.Error as e:
                err.write(f"Error: {e}\n"); return 1
        return 0

    @staticmethod
    def cell(v):
        if v is None: return "NULL"
        if isinstance(v, bytes): return f"<blob {len(v)} bytes>"
        if isinstance(v, float): return f"{v:.6g}" if abs(v) < 1e15 else str(v)
        return str(v)

    def table(self, cols, rows, out, mode="box", headers=True):
        cells = [[self.cell(v).replace("\n", " ") for v in r] for r in rows]
        if mode == "csv":
            import csv
            w = csv.writer(out, lineterminator="\n")
            if headers: w.writerow(cols)
            w.writerows(cells); return
        if mode == "list":
            if headers: out.write("|".join(cols) + "\n")
            for r in cells: out.write("|".join(r) + "\n")
            return
        ws = [min(60, max([len(c)] + [len(r[i]) for r in cells])) for i, c in enumerate(cols)]
        fit = lambda s, w: s if len(s) <= w else s[:w - 1] + "…"
        right = [bool(rows) and all(isinstance(r[i], (int, float)) or r[i] is None for r in rows) for i in range(len(cols))]
        fmt = lambda r: "│ " + " │ ".join(fit(v, w).rjust(w) if right[i] else fit(v, w).ljust(w) for i, (v, w) in enumerate(zip(r, ws))) + " │\n"
        out.write("┌─" + "─┬─".join("─" * w for w in ws) + "─┐\n")
        if headers: out.write(BOLD + fmt(cols)[:-1] + RESET + "\n" + "├─" + "─┼─".join("─" * w for w in ws) + "─┤\n")
        for r in cells: out.write(fmt(r))
        out.write("└─" + "─┴─".join("─" * w for w in ws) + "─┘\n")
        out.write(f"{DIM}{len(rows)} row{'' if len(rows) == 1 else 's'}{RESET}\n")

    # ---------- the SQL playground ----------
    def sql(self, db, query):
        p = self.inside(db)
        con = sqlite3.connect(p); t = time.perf_counter(); results = []
        try:
            for st in self.statements(query)[:20]:
                try:
                    cur = con.execute(st)
                    if cur.description:
                        rows = cur.fetchmany(MAX_ROWS + 1)
                        results.append({"sql": st, "columns": [d[0] for d in cur.description],
                                        "rows": [[v if v is None or isinstance(v, (int, float, str)) else self.cell(v) for v in r] for r in rows[:MAX_ROWS]],
                                        "more": len(rows) > MAX_ROWS})
                    else: results.append({"sql": st, "changes": con.total_changes})
                    con.commit()
                except sqlite3.Error as e:
                    results.append({"sql": st, "error": str(e)}); break
        finally: con.close()
        return {"results": results, "ms": round((time.perf_counter() - t) * 1000, 1)}

    def schema(self, db):
        p = self.inside(db)
        if not os.path.exists(p): return {"tables": []}
        con = sqlite3.connect(p)
        try:
            out = []
            for name, kind in con.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY type, name"):
                q = name.replace('"', '""')
                cols = [{"name": r[1], "type": r[2] or "", "pk": bool(r[5])} for r in con.execute(f'PRAGMA table_info("{q}")')]
                n = con.execute(f'SELECT COUNT(*) FROM "{q}"').fetchone()[0]
                out.append({"name": name, "kind": kind, "columns": cols, "rows": n})
            return {"tables": out}
        finally: con.close()

    def databases(self):
        found = []
        for d, ds, fs in os.walk(self.home):
            ds[:] = sorted(x for x in ds if not x.startswith(".") and x not in SKIP)
            found += [self.rel(os.path.join(d, f)) for f in sorted(fs) if f.endswith((".db", ".sqlite", ".sqlite3"))]
        return found[:100]

    def sample(self, path="sample.db", reset=False):
        """The SQL playground's sample data: an LLM app's users, model calls and eval runs (made up, the same every time)."""
        p = self.inside(path)
        if os.path.exists(p) and not reset:
            con = sqlite3.connect(p)
            try: tables = con.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
            finally: con.close()
            if tables: return {"path": self.rel(p)}  # an empty file (sqlite3 sample.db before the SQL tab) is filled in
        if os.path.exists(p): os.remove(p)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        r, con = random.Random(7), sqlite3.connect(p)
        con.executescript("""
            CREATE TABLE models (id TEXT PRIMARY KEY, provider TEXT, input_per_mtok REAL, output_per_mtok REAL, context_tokens INTEGER);
            CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, team TEXT, plan TEXT, signed_up TEXT);
            CREATE TABLE calls (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), model TEXT REFERENCES models(id), feature TEXT,
                                prompt_tokens INTEGER, completion_tokens INTEGER, cached_tokens INTEGER, latency_ms INTEGER, status TEXT, created_at TEXT);
            CREATE TABLE evals (id INTEGER PRIMARY KEY, run TEXT, model TEXT REFERENCES models(id), question_id INTEGER, category TEXT, score REAL, passed INTEGER);""")
        models = [("atlas-large", "Atlas", 4.0, 20.0, 1_000_000), ("atlas-small", "Atlas", 0.5, 2.5, 200_000), ("nova-pro", "Nova", 2.5, 10.0, 400_000),
                  ("nova-mini", "Nova", 0.15, 0.6, 128_000), ("local-8b", "self-hosted", 0.0, 0.0, 32_000)]
        con.executemany("INSERT INTO models VALUES (?,?,?,?,?)", models)
        first = ["Ada", "Ben", "Chen", "Dara", "Eli", "Fatima", "Gus", "Hana", "Ivan", "Jo", "Kemal", "Lena", "Mo", "Nia", "Omar", "Priya", "Quinn", "Rosa", "Sam", "Tariq", "Uma", "Vik", "Wen", "Xavi", "Yara", "Zoe"]
        teams, plans, start = ["support", "search", "sales", "research", "platform"], ["free", "pro", "team"], datetime(2026, 9, 1)
        users = [(i + 1, f"{first[i % 26]} {chr(65 + i // 26)}.", r.choice(teams), r.choices(plans, [5, 3, 2])[0], (start - timedelta(days=r.randint(5, 400))).date().isoformat()) for i in range(40)]
        con.executemany("INSERT INTO users VALUES (?,?,?,?,?)", users)
        feats = {"support": "ticket_triage", "search": "rag_answer", "sales": "email_draft", "research": "summarize", "platform": "agent_task"}
        speed = {"atlas-large": 2400, "atlas-small": 700, "nova-pro": 1600, "nova-mini": 450, "local-8b": 900}
        calls = []
        for i in range(3000):
            u = r.choice(users); m = r.choices([x[0] for x in models], [3, 5, 2, 6, 2])[0]
            pt = int(r.lognormvariate(7, 0.8)); ct = int(r.lognormvariate(5.3, 0.7)); cached = int(pt * r.choice([0, 0, 0.5, 0.8]))
            lat = int(speed[m] * r.lognormvariate(0, 0.35) + ct * 6)
            status = r.choices(["ok", "error", "timeout", "refused"], [92, 4, 3, 1])[0]
            when = start + timedelta(days=r.randint(0, 29), seconds=r.randint(0, 86399))
            calls.append((i + 1, u[0], m, feats[u[2]], pt, ct if status == "ok" else 0, cached, lat if status != "timeout" else 30000, status, when.strftime("%Y-%m-%d %H:%M:%S")))
        con.executemany("INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?)", calls)
        evals, k, skill = [], 0, {"atlas-large": 0.86, "atlas-small": 0.72, "nova-pro": 0.8, "nova-mini": 0.64, "local-8b": 0.55}
        for run in ("2026-09-07", "2026-09-21"):
            for m in skill:
                for q in range(1, 41):
                    k += 1; s = max(0.0, min(1.0, r.gauss(skill[m] + (0.03 if run.endswith("21") else 0), 0.15)))
                    evals.append((k, run, m, q, ["retrieval", "reasoning", "format", "safety"][q % 4], round(s, 2), int(s >= 0.7)))
        con.executemany("INSERT INTO evals VALUES (?,?,?,?,?,?,?)", evals)
        con.commit(); con.close()
        return {"path": self.rel(p)}

    # ---------- files for the editor ----------
    def files(self):
        out = []
        for d, ds, fs in os.walk(self.home):
            ds[:] = sorted((x for x in ds if not x.startswith(".") and x not in SKIP), key=str.lower)
            rel = self.rel(d)
            if rel != ".": out.append({"path": rel, "dir": True})
            for f in sorted(fs, key=str.lower):
                if f.startswith("."): continue
                st = os.stat(os.path.join(d, f))
                out.append({"path": os.path.join(rel, f) if rel != "." else f, "size": st.st_size, "mtime": st.st_mtime})
            if len(out) > 600: break
        return out[:600]

    def read(self, path):
        p = self.inside(path)
        if not os.path.isfile(p): raise ShellError(f"{path} isn't there any more.")
        size = os.path.getsize(p)
        ext = os.path.splitext(p)[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp") and size <= MAX_FILE:
            return {"path": self.rel(p), "image": base64.b64encode(open(p, "rb").read()).decode(), "type": ext[1:].replace("jpg", "jpeg"), "size": size}
        if size > MAX_FILE: return {"path": self.rel(p), "binary": True, "size": size}
        raw = open(p, "rb").read()
        if b"\0" in raw[:4096]: return {"path": self.rel(p), "binary": True, "size": size}
        return {"path": self.rel(p), "text": raw.decode("utf-8", "replace"), "size": size}

    def write(self, path, text):
        p = self.inside(path)
        if os.path.isdir(p): raise ShellError(f"{path} is a folder")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f: f.write(text)
        return {"path": self.rel(p)}

    def write_b64(self, path, data):
        p = self.inside(path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f: f.write(base64.b64decode(data))
        return {"path": self.rel(p)}

    def bytes_b64(self, path):
        p = self.inside(path)
        if not os.path.isfile(p): raise ShellError(f"{path} isn't there any more.")
        return base64.b64encode(open(p, "rb").read()).decode()

    def mkdir(self, path): os.makedirs(self.inside(path), exist_ok=True); return {"path": self.rel(self.inside(path))}

    def remove(self, path):
        p = self.inside(path)
        if p == self.home: raise ShellError("That's your whole lab folder: use Reset to empty it.")
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        return {}

    def rename(self, a, b):
        pa, pb = self.inside(a), self.inside(b)
        if os.path.exists(pb): raise ShellError(f"{b} already exists.")
        os.makedirs(os.path.dirname(pb), exist_ok=True); shutil.move(pa, pb)
        return {"path": self.rel(pb)}

    def reset(self):
        for x in os.listdir(self.home):
            p = os.path.join(self.home, x)
            shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)
        os.chdir(self.home); self.mode, self.console, self.db, self.sqlbuf = "sh", None, None, ""
        return self.state()

    def complete(self, text):
        """Tab: what can finish the last word (commands first, then paths)."""
        if self.mode != "sh": return {"words": []}
        word = re.split(r"[\s|;&<>]", text)[-1]
        before = text[:len(text) - len(word)].strip()
        if not before or before.endswith(("|", ";", "&&", "||")):
            names = sorted({k[2:] for k in dir(self) if k.startswith("c_")} | {"python3", "pip3"})
            return {"words": [n for n in names if n.startswith(word)]}
        base = os.path.expanduser(word) if word.startswith("~") else word
        d, part = os.path.split(base)
        try: xs = os.listdir(d or ".")
        except OSError: return {"words": []}
        hits = sorted(x for x in xs if x.startswith(part) and (part.startswith(".") or not x.startswith(".")))
        pre = word[:len(word) - len(part)]
        return {"words": [pre + x + ("/" if os.path.isdir(os.path.join(d or ".", x)) else "") for x in hits]}

    # ---------- lab tasks ----------
    def seed(self, folder, files, setup_db=True):
        """A task's starting files in ~/<folder> (files already there are kept unless reset), and data.db built from setup.sql."""
        root = self.inside(folder)
        os.makedirs(root, exist_ok=True)
        for f in files:
            p = os.path.realpath(os.path.join(root, f["path"]))
            if not p.startswith(root + "/"): continue
            if os.path.exists(p) and not f.get("force"): continue
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh: fh.write(f["content"])
        setup = os.path.join(root, "setup.sql")
        if setup_db and os.path.exists(setup):
            db = os.path.join(root, "data.db")
            if os.path.exists(db): os.remove(db)
            con = sqlite3.connect(db)
            try: con.executescript(open(setup, encoding="utf-8").read()); con.commit()
            except sqlite3.Error as e: return {"path": self.rel(root), "warning": f"setup.sql didn't run: {e}"}
            finally: con.close()
        return {"path": self.rel(root)}

    async def check(self, folder, tests):
        """Runs every test_* function of a task's checks in its folder; each result says what passed or why not."""
        root = self.inside(folder)
        if not os.path.isdir(root): raise ShellError("The task's folder is gone: start the task again.")
        await self.load_imports(tests, root)
        self.purge()
        saved = list(sys.path), os.getcwd(), sys.stdin
        sys.path.insert(0, root); os.chdir(root); sys.stdin = Stdin("")
        results = []
        try:
            ns = {"__name__": "lab_checks", "__builtins__": builtins}
            try: exec(compile(tests, "<checks>", "exec"), ns)
            except BaseException as e:
                return {"error": "The checks couldn't load: " + "".join(traceback.format_exception_only(type(e), e)).strip(), "results": []}
            for name, fn in [(k, v) for k, v in ns.items() if k.startswith("test") and callable(v)][:20]:
                cap = io.StringIO()
                t = time.perf_counter()
                with contextlib.redirect_stdout(cap), contextlib.redirect_stderr(cap):
                    try: fn(); ok, msg = True, ""
                    except AssertionError as e:
                        line = next((f.line for f in reversed(traceback.extract_tb(e.__traceback__)) if f.filename == "<checks>"), None)
                        ok, msg = False, str(e) or (line and f"Failed: {line}") or "An assertion failed."
                    except BaseException as e:
                        ok, msg = False, "".join(traceback.format_exception_only(type(e), e)).strip()
                    finally: os.chdir(root)
                doc = (fn.__doc__ or "").strip().split("\n")[0]
                results.append({"name": name, "doc": doc, "ok": ok, "message": msg[:1500], "output": cap.getvalue()[-1500:],
                                "ms": round((time.perf_counter() - t) * 1000)})
            return {"results": results}
        finally:
            sys.path[:] = saved[0]; sys.stdin = saved[2]
            os.chdir(saved[1] if os.path.isdir(saved[1]) else self.home)

    async def verify(self, files, solution, commands, tests):
        """The task checked against the tutor's own solution, in a scratch folder: do the checks pass there?"""
        scratch = os.path.join(self.home, ".verify")
        shutil.rmtree(scratch, ignore_errors=True)
        kept = os.getcwd(), dict(self.env), self.code, self.prev  # the learner's shell is left as it was
        try:
            self.seed(".verify", files)
            for f in solution: self.seed(".verify", [{**f, "force": True}], setup_db=False)
            if commands:
                was, self.out, self.err = (self.out, self.err), io.StringIO(), io.StringIO()  # the solution's output isn't shown
                os.chdir(scratch)
                try:
                    for c in commands[:20]:
                        items = self.parse(c)
                        if items: await self.run_list(items)
                        if self.mode != "sh": self.mode, self.console, self.db = "sh", None, None
                finally:
                    self.out, self.err = was
            r = await self.check(".verify", tests)
            return {"passed": sum(x["ok"] for x in r["results"]), "total": len(r["results"]), "error": r.get("error")}
        except Exception as e:
            return {"passed": 0, "total": 0, "error": str(e)}
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
            os.chdir(kept[0] if os.path.isdir(kept[0]) else self.home); self.env, self.code, self.prev = kept[1], kept[2], kept[3]

    # ---------- projects: what changed since a ticket started ----------
    def tracked(self, root):
        """{path: text} of the files under root that git would track: not .gitignore'd, not in dot folders or caches,
        not binary, not over 200 KB."""
        ignore = []
        if os.path.isfile(os.path.join(root, ".gitignore")):
            ignore = [l.strip() for l in open(os.path.join(root, ".gitignore"), encoding="utf-8", errors="replace") if l.strip() and not l.startswith("#")]
        def ignored(rel, folder):
            for pat in ignore:
                if pat.endswith("/") and not folder: continue
                pat = pat.strip("/")
                if fnmatch.fnmatch(rel.rsplit("/", 1)[-1], pat) or fnmatch.fnmatch(rel, pat): return True
            return False
        out = {}
        for d, ds, fs in os.walk(root):
            rd = os.path.relpath(d, root)
            ds[:] = sorted(x for x in ds if not x.startswith(".") and x not in SKIP and not ignored(os.path.normpath(os.path.join(rd, x)), True))
            for f in sorted(fs):
                rel, p = os.path.normpath(os.path.join(rd, f)), os.path.join(d, f)
                if ignored(rel, False) or os.path.getsize(p) > 200_000: continue
                raw = open(p, "rb").read()
                if b"\0" in raw[:4096]: continue
                out[rel] = raw.decode("utf-8", "replace")
                if len(out) >= 400: return out
        return out

    def snapshot(self, folder):
        return {"files": self.tracked(self.inside(folder))}

    def changes(self, folder, base):
        """What differs from `base` (a snapshot's files): a unified diff per file, added and deleted files included."""
        import difflib
        now = self.tracked(self.inside(folder))
        out = []
        for path in sorted(set(base) | set(now)):
            a, b = base.get(path), now.get(path)
            if a == b: continue
            lines = [l if l.endswith("\n") else l + "\n" for l in difflib.unified_diff(
                (a or "").splitlines(True), (b or "").splitlines(True), "/dev/null" if a is None else f"a/{path}", "/dev/null" if b is None else f"b/{path}")]
            out.append({"path": path, "status": "added" if a is None else "deleted" if b is None else "modified",
                        "add": sum(l[0] == "+" and not l.startswith("+++") for l in lines),
                        "del": sum(l[0] == "-" and not l.startswith("---") for l in lines), "diff": "".join(lines)[:80_000]})
        return {"files": out}

    async def run(self, path, stdin=""):
        """▶ in the editor: `python path` in the file's folder, with what's in the Input box as stdin."""
        p = self.inside(path)
        self.sent, self.action, was = 0, None, os.getcwd()
        os.chdir(os.path.dirname(p))
        try: code = await self.command(["python", p], stdin or "", self.out, self.err)
        finally: os.chdir(was if os.path.isdir(was) else self.home)
        self.figures()
        return self.state(code)

LAB = None
CALLS = {"line", "complete", "run", "check", "verify", "seed", "sql", "schema", "databases", "sample", "example", "files", "read", "write",
         "write_b64", "bytes_b64", "mkdir", "remove", "rename", "reset", "state", "snapshot", "changes"}

def start(emit, home, user):
    global LAB
    LAB = Lab(emit, home, user)
    return json.dumps(LAB.state())

async def call(name, args):
    """One request from the page: a Lab method and its arguments as JSON; the answer as JSON ({"error": …} when refused)."""
    if name not in CALLS: return json.dumps({"error": f"Unknown request {name}."})
    try:
        r = getattr(LAB, name)(**json.loads(args))
        if hasattr(r, "__await__"): r = await r
    except ShellError as e:
        LAB.out.flush(); LAB.err.flush()
        return json.dumps({"error": str(e)})
    return json.dumps(r)

#!/usr/bin/env python3
"""Packs earlier work on a competition into one bundle for Mining HQ's "Import existing work" (Competition teams → a team →
Import). Run it on the machine where the work is; it only reads.

    python3 tools/mining-import.py /home/thomas/bit --out bit-import.json

What goes in:
- Text files the work is made of (code, scripts, plans, notes, eval logs, task lists), up to 300 kB each. The ones the import page
  ticks to start with: files git tracks, plans, eval logs and task lists, but not downloaded data (folders named data or *-data). Left out, and listed in
  the bundle with the reason: anything that looks like a secret (.env files, keys), binaries, caches and virtualenvs, nested git
  repositories (vendored or downloaded code) and bulk data (a folder with more than 20 MB of text, such as model weights,
  benchmark mirrors or other people's agents).
- The folder's git history (the root repository's commits).
- Claude Code conversations held in that folder (~/.claude/projects/<folder>/*.jsonl), cut down to what was asked and answered
  (no tool calls or outputs), and Claude Code's memory notes for it.

Secrets are taken out before anything is written: API keys and tokens by their shape, private keys, values assigned to names like
password or api_key, and every value found in the .env files left out. The bundle says how many it took out; read it before you
upload it if the work ever touched a wallet's mnemonic, which has no shape to look for.
"""
import argparse, datetime, json, os, re, subprocess, sys, time

FORMAT = "axor-mining-import/1"
FILE_BYTES = 300_000            # Mining HQ's per-file limit (mining_work.FILE_BYTES)
BULK_BYTES = 20_000_000         # a folder with more text than this is data, not work
SESSION_CHARS = 40_000          # what's kept of one conversation
TEXT_EXT = {".py", ".md", ".txt", ".sh", ".json", ".jsonl", ".toml", ".yaml", ".yml", ".cfg", ".ini", ".csv", ".tsv", ".sql", ".log",
            ".js", ".ts", ".go", ".rs", ".rb", ".java", ".c", ".h", ".cpp", ".hpp", ".php", ".ex", ".lua", ".pl", ".r", ".ipynb",
            ".dockerfile", ".env.example", ".gitignore", ".patch", ".diff", ".html", ".css"}
TEXT_NAMES = {"Dockerfile", "Makefile", "README", "LICENSE", ".gitignore", "CLAUDE.md", "requirements.txt"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", ".ruff_cache", ".pytest_cache", ".mypy_cache", ".tox",
             "cache", ".cache", "site-packages", "dist", "build", ".idea", ".vscode", ".ipynb_checkpoints"}
RUN_DIRS = {"runs", "results", "outputs", "wandb", "mlruns", "checkpoints"}  # what runs leave behind: the logs' tables say how they went
SECRET_NAME = re.compile(r"(^|/)(\.env(\.[^/]*)?|[^/]*\.(pem|key|p12|pfx|apikey|keystore)|id_(rsa|ed25519|ecdsa)[^/]*|[^/]*(credential|secret|api[_-]?keys?)[^/]*"
                         r"|coldkey[^/]*|hotkey[^/]*|\.netrc|\.pgpass)$", re.I)
SECRET_OK = re.compile(r"\.example$|\.sample$|\.template$", re.I)
# keep in sync with backend/app/mining_import.py (the server takes them out again)
SECRETS = [re.compile(p) for p in (
    r"sk-ant-[A-Za-z0-9_-]{20,}", r"sk-or-v1-[A-Za-z0-9]{20,}", r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}", r"gh[pousr]_[A-Za-z0-9]{30,}",
    r"github_pat_[A-Za-z0-9_]{30,}", r"glpat-[A-Za-z0-9_-]{20,}", r"xox[abprs]-[A-Za-z0-9-]{10,}", r"AKIA[0-9A-Z]{16}", r"AIza[0-9A-Za-z_-]{35}",
    r"hf_[A-Za-z0-9]{30,}", r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{24,}", r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")]
SECRET_VAR = re.compile(r"(?i)key|token|secret|pass|mnemonic|seed|private|auth|credential")
ASSIGNED = re.compile(r"(?i)\b([A-Za-z0-9_]*(?:api[_-]?key|token|secret|passw(?:or)?d|private[_-]?key|mnemonic|seed[_-]?phrase)[A-Za-z0-9_]*)"
                      r"(\s*[=:]\s*[\"']?)([A-Za-z0-9_+/=.-]{16,})(?![A-Za-z0-9_(\[])")


class Redactor:
    def __init__(self):
        self.values, self.n = set(), 0

    def learn(self, path):
        """Remembers the values in a secrets file left out, so they're taken out wherever else they turn up."""
        try: text = open(path, encoding="utf-8", errors="replace").read(200_000)
        except OSError: return
        for line in text.splitlines():
            m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*[=:]\s*[\"']?([^\"'#\s]+)", line)
            if m and SECRET_VAR.search(m.group(1)) and len(m.group(2)) >= 8 and "://" not in m.group(2): self.values.add(m.group(2))

    def __call__(self, text):
        if not text: return text
        def sub(m):
            self.n += 1
            return "[redacted]"
        for v in sorted(self.values, key=len, reverse=True):
            if v in text: self.n += text.count(v); text = text.replace(v, "[redacted]")
        for p in SECRETS: text = p.sub(sub, text)
        def keep_name(m):
            v = m.group(3)
            if v == "[redacted]" or not (re.search(r"\d", v) and re.search(r"[A-Za-z]", v)) or "." in v.strip("."): return m.group(0)
            self.n += 1
            return m.group(1) + m.group(2) + "[redacted]"
        return ASSIGNED.sub(keep_name, text)


def is_text(path, head):
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    if b"\x00" in head: return False
    if ext in TEXT_EXT or name in TEXT_NAMES or (not ext and head[:2] == b"#!"): return True
    try: head.decode("utf-8"); return not ext  # extensionless text files only
    except UnicodeDecodeError: return False


def group(rel):
    p = rel.lower()
    if re.search(r"(^|/)(plan|roadmap|todo|ideas|notes?|design)[^/]*\.md$", p): return "plan"
    if p.endswith(".log") or "/eval" in f"/{p}" or "/sets/" in p or "result" in p: return "eval"
    if p.endswith((".md", ".txt")): return "docs"
    if p.endswith((".json", ".jsonl", ".csv", ".tsv")): return "data"
    return "code"


def tracked(root):
    try: out = subprocess.run(["git", "-C", root, "ls-files", "-z"], capture_output=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError): return set()
    return {p.decode("utf-8", "replace") for p in out.split(b"\0") if p}


def walk(root, red):
    """The work's text files, and what was left out with why."""
    files, skipped, ins = [], [], tracked(root)
    direct = {}  # text bytes right in each folder, to spot bulk data
    plan = []
    for d, dirs, names in os.walk(root, topdown=True):
        rel_d = os.path.relpath(d, root)
        keep = []
        for x in sorted(dirs):
            full = os.path.join(d, x)
            rel = os.path.normpath(os.path.join(rel_d, x))
            if x in SKIP_DIRS or x.endswith("-venv") or x.endswith(".egg-info"): skipped.append({"path": rel + "/", "why": "cache or environment"})
            elif x in RUN_DIRS: skipped.append({"path": rel + "/", "why": "run output", "bytes": du(full)})
            elif os.path.islink(full): skipped.append({"path": rel + "/", "why": "link"})
            elif os.path.exists(os.path.join(full, ".git")): skipped.append({"path": rel + "/", "why": "a git repository of its own (vendored or downloaded)", "bytes": du(full)})
            else: keep.append(x)
        dirs[:] = keep
        for n in sorted(names):
            full, rel = os.path.join(d, n), os.path.normpath(os.path.join(rel_d, n))
            if os.path.islink(full): continue
            if SECRET_NAME.search(rel) and not SECRET_OK.search(rel):
                red.learn(full); skipped.append({"path": rel, "why": "looks like a secret"}); continue
            try: size = os.path.getsize(full)
            except OSError: continue
            try:
                with open(full, "rb") as f: head = f.read(4096)
            except OSError: continue
            if not is_text(full, head):
                if size > 1_000_000: skipped.append({"path": rel, "why": "binary", "bytes": size})
                continue
            if size > FILE_BYTES: skipped.append({"path": rel, "why": f"over {FILE_BYTES // 1000} kB", "bytes": size}); continue
            plan.append((rel, full, size))
            direct[rel_d] = direct.get(rel_d, 0) + size
    sizes, under, bulk = {}, {}, []  # deepest folders first: a bulk folder doesn't count toward its parent
    for d in sorted({p for x in direct for p in _parents(x)}, key=lambda d: -(0 if d == "." else d.count(os.sep) + 1)):
        sizes[d] = direct.get(d, 0) + under.get(d, 0)
        if d != "." and sizes[d] > BULK_BYTES: bulk.append(d)
        elif d != ".": under[_parent(d)] = under.get(_parent(d), 0) + sizes[d]
    for p in bulk: skipped.append({"path": p + "/", "why": "bulk data (more than 20 MB of text)", "bytes": sizes[p]})
    for rel, full, size in plan:
        if any(rel.startswith(p + os.sep) for p in bulk): continue
        try: text = open(full, encoding="utf-8", errors="replace").read()
        except OSError: continue
        posix = rel.replace(os.sep, "/")
        g, own = group(posix), posix in ins
        downloaded = any(x == "data" or x.endswith("-data") or x in ("vendor", "third_party", "external") for x in posix.split("/")[:-1])
        files.append({"path": posix, "content": red(text), "bytes": size, "group": g, "tracked": own, "mtime": os.path.getmtime(full),
                      "pick": (own or g in ("plan", "eval")) and not downloaded})  # what the import page ticks to start with
    return files, skipped


def _parent(d): return os.path.dirname(d) or "."

def _parents(d):
    out = [d]
    while d != ".": d = _parent(d); out.append(d)
    return out


def du(path):
    total = 0
    for d, _, names in os.walk(path):
        for n in names:
            try: total += os.lstat(os.path.join(d, n)).st_size
            except OSError: pass
    return total


def commits(root, red):
    fmt = "%x1e%H%x1f%at%x1f%an%x1f%s"  # --shortstat's lines follow each record
    try: out = subprocess.run(["git", "-C", root, "log", f"--format={fmt}", "--shortstat", "-n", "2000"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError): return [], ""
    rows = []
    for chunk in out.split("\x1e"):
        chunk = chunk.strip()
        if not chunk: continue
        head, _, stat = chunk.partition("\n")
        parts = head.split("\x1f")
        if len(parts) < 4: continue
        rows.append({"hash": parts[0][:12], "ts": int(parts[1]), "author": parts[2], "subject": red(parts[3]), "stat": stat.strip()})
    try: remote = subprocess.run(["git", "-C", root, "remote", "get-url", "origin"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError): remote = ""
    remote = re.sub(r"//[^@/]+@", "//", remote)  # no credentials in the URL
    return rows, remote


def _text(content):
    if isinstance(content, str): return content
    if isinstance(content, list): return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _clean(text):
    text = re.sub(r"<(system-reminder|command-[a-z-]+|local-command-[a-z-]+|ide_[a-z_]+)>[\s\S]*?</\1>", "", text)
    return text.strip()


def sessions(folder, red):
    """Claude Code's conversations for the folder, cut down to what was asked and answered."""
    out = []
    for f in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not f.endswith(".jsonl"): continue
        turns, t0, t1 = [], None, None
        try: lines = open(os.path.join(folder, f), encoding="utf-8", errors="replace")
        except OSError: continue
        with lines:
            for line in lines:
                try: d = json.loads(line)
                except ValueError: continue
                if d.get("isSidechain") or d.get("isMeta"): continue
                ts = d.get("timestamp")
                if d.get("type") not in ("user", "assistant"): continue
                text = _clean(_text((d.get("message") or {}).get("content")))
                if not text or text.startswith(("This session is being continued", "Caveat:", "[Request interrupted")): continue
                t0, t1 = t0 or ts, ts or t1
                turns.append((d["type"], ts, text))
        asks = [t for t in turns if t[0] == "user"]
        if not asks: continue
        body = [f"{'**User**' if who == 'user' else '**Claude**'} ({(ts or '')[:16].replace('T', ' ')}): {txt[:2500 if who == 'user' else 1500]}" for who, ts, txt in turns]
        text = "\n\n".join(body)
        if len(text) > SESSION_CHARS:  # the user's words all stay; Claude's answers go from the middle first
            drop = sorted((i for i, t in enumerate(turns) if t[0] != "user"), key=lambda i: abs(i - len(turns) / 2))
            gone, size = set(), len(text)
            for i in drop:
                if size <= SESSION_CHARS: break
                gone.add(i); size -= len(body[i]) + 2
            kept = []
            for i, b in enumerate(body):
                if i not in gone: kept.append(b)
                elif not kept or kept[-1] != "…": kept.append("…")
            text = "\n\n".join(kept)[:SESSION_CHARS]
        out.append({"id": f[:-6], "started": _epoch(t0), "ended": _epoch(t1), "asks": len(asks), "first": red(asks[0][2][:300]),
                    "text": red(text), "chars": len(text)})
    return sorted(out, key=lambda s: s["started"] or 0)


def memory(folder, red):
    out = []
    for f in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not f.endswith(".md") or f == "MEMORY.md": continue
        p = os.path.join(folder, f)
        text = open(p, encoding="utf-8", errors="replace").read()
        m = re.search(r"^description:\s*\"?(.*?)\"?\s*$", text, re.M)
        name = re.search(r"^name:\s*(.*)$", text, re.M)
        body = re.sub(r"\A---[\s\S]*?\n---\n", "", text).strip()
        title = (m.group(1) if m else (name.group(1) if name else f[:-3])).strip().replace('\\"', '"')
        out.append({"title": title[:200], "body": red(body),
                    "ts": os.path.getmtime(p), "kind": "memory", "source": f"Claude Code memory: {f}"})
    return out


def _epoch(ts):
    if not ts: return None
    try: return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError: return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", help="the folder the work is in")
    ap.add_argument("--out", default="mining-import.json", help="where to write the bundle (default: mining-import.json)")
    ap.add_argument("--claude", default=os.path.expanduser("~/.claude"), help="Claude Code's folder (default: ~/.claude)")
    ap.add_argument("--no-sessions", action="store_true", help="leave the Claude Code conversations out")
    a = ap.parse_args()
    root = os.path.abspath(a.folder)
    if not os.path.isdir(root): sys.exit(f"{root} isn't a folder.")
    red = Redactor()
    print(f"Reading {root}…", file=sys.stderr)
    files, skipped = walk(root, red)  # first: it learns the .env values the rest is cleaned of
    log, remote = commits(root, red)
    proj = os.path.join(a.claude, "projects", re.sub(r"[^A-Za-z0-9]", "-", root))
    convs = [] if a.no_sessions else sessions(proj, red)
    notes = memory(os.path.join(proj, "memory"), red)
    bundle = {"format": FORMAT, "made": time.time(), "source": root, "name": os.path.basename(root), "remote": remote,
              "files": files, "notes": notes, "sessions": convs, "commits": log, "skipped": skipped, "redacted": red.n}
    with open(a.out, "w", encoding="utf-8") as f: json.dump(bundle, f, ensure_ascii=False)
    size = os.path.getsize(a.out)
    print(f"{len(files)} files ({sum(x['bytes'] for x in files) / 1e6:.1f} MB), {len(log)} commits, {len(convs)} conversations, "
          f"{len(notes)} memory notes; {len(skipped)} things left out; {red.n} secrets taken out.\n"
          f"Wrote {a.out} ({size / 1e6:.1f} MB). Upload it in Competition teams → your team → Import.", file=sys.stderr)


if __name__ == "__main__":
    main()

"""The wallet's btcli terminal: the real btcli (the bittensor SDK's), run read-only for each user.

- Every user gets a sandbox home (DATA_DIR/btcli/u<id>) holding public-key-only copies of their tracked wallets
  (coldkeypub.txt and hotkeys/<name>pub.txt), so `btcli wallet balance -w main` works as on their own machine and
  btcli has no key to sign with. What btcli caches there (runtime metadata, subnet names) persists between commands.
- Read-only commands run as a subprocess: an argument list (never a shell), on the app's network, with a clean
  environment (none of the app's secrets), flags that point at files, other endpoints or signers refused, a
  timeout and an output cap, one command at a time per user. Without -w the selected wallet is used.
- Commands that sign (stake add, remove, move, unstake-all, wallet transfer) aren't run: the page opens the matching
  transaction sheet, filled in from the command, and the browser wallet signs. With --dry-run, these and a few
  other transaction commands do run here: a plan needs only the public key. Anything else that signs or writes
  files is refused, with the command to copy for the user's own machine.
- Output keeps btcli's colours (ANSI SGR); the spinner's cursor moves are applied so only the final text remains.
"""
import json, logging, os, re, shlex, shutil, subprocess, threading, time
from pathlib import Path

from .wallet import NAME, NETWORKS, SECRET_HINT, looks_secret, pubkey, valid_ss58

log = logging.getLogger("wallet.term")
TIMEOUT = 45          # seconds a command may run
MAX_OUT = 256_000     # characters of output kept
MAX_LINE = 500
RATE = 30             # commands per minute per user
ALIASES = {"w": "wallet", "wallets": "wallet", "st": "stake", "s": "subnets", "subnet": "subnets", "sn": "subnets", "q": "query"}
# read-only commands, run as they are (query and explain: every subcommand)
READ = {"wallet": {"list", "balance", "overview", "registrations", "history", "inspect", "get-identity", "show", "swap-check", "verify"},
        "stake": {"list", "show", "auto"},
        "subnets": {"list", "show", "hyperparameters", "price", "conviction", "metagraph", "burn-cost", "create-cost"},
        "root": {"list"}, "query": "*", "explain": "*"}
# commands that sign and have a sheet in the wallet: op and how btcli's flags fill it
SIGN = {("stake", "add"): "stake", ("stake", "remove"): "unstake", ("stake", "move"): "move", ("stake", "unstake-all"): "unstake_all",
        ("wallet", "transfer"): "send"}
# transaction commands that can be previewed here with --dry-run
DRY = set(SIGN) | {("subnets", "register"), ("stake", "swap"), ("stake", "move-swap"), ("stake", "transfer"), ("root", "register")}
# where the selected wallet is added when the command names none
WALLETED = {("wallet", c) for c in ("balance", "overview", "registrations", "history", "inspect", "show")} | {("stake", c) for c in ("list", "show", "auto")} | DRY
# flags that read files, reach other endpoints, sign, prompt or change the network
DENY = {"--wallet-path", "--wallet-password-file", "--macos-password", "--keychain-password", "--signer", "--signer-address", "--ledger",
        "--ledger-account", "--ledger-index", "--extension-source", "--extension-browser", "--extension-bridge", "--proxy-for",
        "--force-proxy-type", "--signatory", "--fallback-endpoints", "--archive-endpoints", "--retry-forever", "--yes", "-y", "--mev-shield",
        "--no-mev-shield", "--config", "--subtensor.chain_endpoint", "--subtensor.network", "--output", "--out", "--file", "--path"}
NET_FLAGS = {"--network", "-n"}
HOTKEY_FLAGS = {"--hotkey", "--origin-hotkey", "--dest-hotkey", "--include-hotkeys", "--hotkey-ss58"}
# what Tab completes: groups, then their commands, then common flags
COMPLETE = {g: sorted(c) if c != "*" else [] for g, c in READ.items()}
for g, c in SIGN: COMPLETE.setdefault(g, []).append(c)
for g, c in DRY: COMPLETE.setdefault(g, []).append(c)
COMPLETE = {g: sorted(set(c)) for g, c in COMPLETE.items()}
FLAGS = ["--wallet", "--hotkey", "--netuid", "--amount-tao", "--amount-alpha", "--all", "--dry-run", "--json", "--coldkey", "--dest",
         "--origin-hotkey", "--origin-netuid", "--dest-hotkey", "--dest-netuid", "--rate-tolerance", "--network", "--help"]
HELP = [
    ["The real btcli, read-only: your tracked wallets are here as public keys only, so -w NAME works and nothing can sign."],
    {"head": ["Try", "Shows"], "rows": [
        ["btcli wallet list", "Your tracked wallets"],
        ["btcli wallet balance", "Free, staked and total (the selected wallet, or -w NAME)"],
        ["btcli stake list", "Every stake position"],
        ["btcli subnets list", "All subnets: price, emission, flow, burn"],
        ["btcli subnets show 19", "One subnet: owner, registration, neurons"],
        ["btcli query delegate-take --hotkey 5…", "Any chain read (btcli query --help lists them)"],
        ["btcli stake add --netuid 19 --hotkey 5… --amount-tao 1", "Opens the Stake sheet: your browser wallet signs"],
        ["… --dry-run", "Previews a transaction here"],
        ["clear · ↑ ↓ history · Tab completes", ""]]},
    [{"s": "Stake add/remove/move/unstake-all and wallet transfer open the wallet's sheet. Other commands that sign or write files run on your own machine.", "c": "faint"}]]

class TermError(Exception):
    def __init__(self, msg, status="error", copy=None): super().__init__(msg); self.status, self.copy = status, copy

def T(text, c): return {"s": text, "c": c}

def screen(raw):
    """btcli's output with its terminal moves applied: carriage returns, erased lines and cursor-up (the spinner) are
    replayed into final lines; colour codes (SGR) and links (OSC 8) are kept, every other control sequence is dropped."""
    lines, cur, cr = [""], 0, False
    for tok in re.findall(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[A-Za-z]|\x1b[^\[\]]|\r|\n|[^\x1b\r\n]+", raw):
        if tok == "\n": cur += 1; cr = False; lines += [""] * (cur + 1 - len(lines)); continue
        if tok == "\r": cr = True; continue
        if tok.startswith("\x1b["):
            cmd, arg = tok[-1], tok[2:-1]
            if cmd == "m": lines[cur] += tok
            elif cmd == "K" and arg in ("", "2"): lines[cur] = ""
            elif cmd == "A": cur = max(0, cur - int(arg or 1))
            continue
        if tok.startswith("\x1b]8;"): lines[cur] += tok; continue  # a link: ESC ] 8 ; params ; URL ST
        if tok.startswith("\x1b"): continue
        if cr: lines[cur] = ""; cr = False
        lines[cur] += tok
    plain = lambda l: re.sub(r"\x1b\[[0-9;]*m|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", l)
    while lines and not plain(lines[-1]).strip(): lines.pop()
    while lines and not plain(lines[0]).strip(): lines.pop(0)
    return "\n".join(lines)

class Btcli:
    def __init__(self, wallets, data_dir):
        self.w, self.root = wallets, Path(data_dir) / "btcli"
        self.exe = shutil.which("btcli")
        self.hits, self.locks, self.slots = {}, {}, threading.Semaphore(3)

    # ---------- the sandbox ----------
    def home(self, me):
        """The user's sandbox home, with their tracked wallets as public keys only (re-synced before every command)."""
        home = self.root / f"u{int(me['id'])}"
        wdir = home / ".bittensor" / "wallets"
        wdir.mkdir(parents=True, exist_ok=True)
        rows = [r for r in self.w._rows(me) if NAME.fullmatch(r["name"]) and not r["name"].startswith(".")]
        keep = {r["name"] for r in rows}
        for d in wdir.iterdir():
            if d.is_dir() and d.name not in keep and (d / ".scout").exists(): shutil.rmtree(d, ignore_errors=True)
        pub = lambda a: json.dumps({"ss58Address": a, "accountId": "0x" + pubkey(a).hex(), "publicKey": "0x" + pubkey(a).hex(), "cryptoType": 1})
        for r in rows:
            d = wdir / r["name"]; (d / "hotkeys").mkdir(parents=True, exist_ok=True)
            (d / ".scout").write_text("written by AXoR: public keys only\n")
            (d / "coldkeypub.txt").write_text(pub(r["coldkey"]))
            names = set()
            for h in r["hotkeys"]:
                if not NAME.fullmatch(h["name"]) or h["name"].startswith("."): continue
                names.add(h["name"] + "pub.txt")
                (d / "hotkeys" / (h["name"] + "pub.txt")).write_text(pub(h["ss58"]))
            for f in (d / "hotkeys").iterdir():
                if f.name not in names: f.unlink(missing_ok=True)  # only *pub.txt files are ever written here
        return home

    # ---------- a command ----------
    def run(self, me, line, wid=None, cols=110):
        line = (line or "").strip()
        if len(line) > MAX_LINE: return {"status": "error", "lines": [[f"Commands are limited to {MAX_LINE} characters."]]}
        now = time.time()
        hits = [t for t in self.hits.get(me["id"], []) if now - t < 60]
        if len(hits) >= RATE: return {"status": "error", "lines": [["That's a lot of commands. Wait a minute and try again."]]}
        self.hits[me["id"]] = hits + [now]
        try:
            if looks_secret(line): raise TermError(SECRET_HINT, "refused")
            return self._run(me, line, wid, max(40, min(int(cols or 110), 220)))
        except TermError as e:
            return {"status": e.status, "lines": [[str(e)]], "copy": e.copy}

    def _words(self, line):
        if re.search(r"[;|&`<>]|\$\(|\$\{", line):
            raise TermError("One btcli command at a time: there's no shell here, so ; | && $( ) and redirects don't run.", "refused")
        try: words = shlex.split(line)
        except ValueError: raise TermError("Couldn't read that command (an unclosed quote?).")
        return words

    def _run(self, me, line, wid, cols):
        words = self._words(line)
        if not words: return {"status": "ok", "lines": []}
        if words[0] in ("help", "?") or words == ["btcli"]: return {"status": "ok", "lines": HELP}
        if words[0] != "btcli":
            raise TermError(f"Only btcli runs here. Run “{words[0]}” in your own terminal.", "refused", line)
        args = words[1:]
        if args and args[0] in ALIASES: args[0] = ALIASES[args[0]]
        group = args[0] if args else ""
        cmd = args[1] if len(args) > 1 and not args[1].startswith("-") else ""
        flags = self._flags(args[2:] if cmd else args[1:])
        if group.startswith("-"): group, cmd, flags = "", "", self._flags(args)  # btcli --help
        helping = "--help" in flags or "-h" in flags
        op = (group, cmd)
        rows = self.w._rows(me)
        wname = flags.get("--wallet") or flags.get("-w")
        def wallet():
            w = next((r for r in rows if r["name"] == wname), None) if wname else next((r for r in rows if r["id"] == wid), rows[0] if rows else None)
            if wname and not w:
                raise TermError(f"No tracked wallet is named “{wname}”." + (f" Yours: {', '.join(r['name'] for r in rows)}." if rows else " Add one first (public addresses only)."))
            return w
        dry = "--dry-run" in flags
        if op in SIGN and not dry and not helping:
            w = wallet()
            if not w: raise TermError("Add a wallet first: Add an address, or connect a browser wallet.")
            return self._sheet(SIGN[op], flags, w, line)
        if helping: allowed = not group or group in COMPLETE  # btcli's own help for anything it knows
        else: allowed = (group in READ and (READ[group] == "*" or cmd in READ[group])) or (op in DRY and dry)
        if not allowed:
            known = group in COMPLETE or group in ("config", "addr", "proxy", "multisig", "evm", "tx", "call", "hparams", "conviction", "misc", "tools")
            raise TermError((f"“btcli {group} {cmd}”".replace("  ", " ") + (" signs a transaction or writes files, so it doesn't run here. Add --dry-run to preview it if it's a transaction, or run it on your own machine."
                             if known else " isn't a btcli command this terminal knows. Type help for what runs here.")), "refused", line)
        for k, v in flags.items():
            if k in DENY: raise TermError(f"{k} doesn't run here (it reads files, reaches other endpoints, signs or skips confirmations).", "refused", line)
            if k in NET_FLAGS and v not in NETWORKS: raise TermError(f"This terminal reads {' or '.join(NETWORKS)} only.", "refused", line)
        for a in args:
            if a.startswith(("/", "~", "./")) or ".." in a or "://" in a or "\\" in a:
                raise TermError(f"“{a}” looks like a file path or URL: those don't run here.", "refused", line)
        w = wallet()
        argv = self._hotkeys(list(args), w)
        if op in WALLETED and w and not wname and not any(k in flags for k in ("--coldkey", "--all", "-a", "--ss58")):
            argv += ["--wallet", w["name"]]
        if not any(k in flags for k in NET_FLAGS) and group != "explain":
            argv += ["--network", self.w.chain.network]
        return self._exec(me, argv, cols)

    @staticmethod
    def _hotkeys(argv, w):
        """btcli resolves a hotkey *name* from its private keyfile, which the sandbox never has: pass the address instead."""
        if not w: return argv
        names = {h["name"]: h["ss58"] for h in w["hotkeys"]}
        for i, a in enumerate(argv):
            k, eq, v = a.partition("=")
            if eq and k in HOTKEY_FLAGS: argv[i] = f"{k}={names.get(v.split('/')[-1], v)}"
            elif a in HOTKEY_FLAGS and i + 1 < len(argv): argv[i + 1] = names.get(argv[i + 1].split("/")[-1], argv[i + 1])
        return argv

    @staticmethod
    def _flags(rest):
        """--flag value, --flag=value and bare switches, as a dict (switches map to True)."""
        out, i = {}, 0
        while i < len(rest):
            a = rest[i]
            if a.startswith("-"):
                if "=" in a and a.startswith("--"): k, v = a.split("=", 1); out[k] = v
                elif i + 1 < len(rest) and not rest[i + 1].startswith("-"): out[a] = rest[i + 1]; i += 1
                else: out[a] = True
            i += 1
        return out

    def _exec(self, me, argv, cols):
        if not self.exe: raise TermError("btcli isn't installed on this server.")
        lock = self.locks.setdefault(me["id"], threading.Lock())
        if not lock.acquire(blocking=False): raise TermError("Your previous command is still running.")
        try:
            if not self.slots.acquire(timeout=20): raise TermError("The terminal is busy. Try again in a moment.")
            try:
                home = self.home(me)
                env = {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "COLUMNS": str(cols), "LINES": "60",
                       "FORCE_COLOR": "1", "TERM": "xterm-256color", "COLORTERM": "truecolor", "LANG": "C.UTF-8", "PYTHONUNBUFFERED": "1"}
                t = time.time()
                try:
                    p = subprocess.run([self.exe, *argv], cwd=home, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=TIMEOUT)
                    out, code = (p.stdout + p.stderr).decode("utf-8", "replace"), p.returncode
                except subprocess.TimeoutExpired:
                    out, code = f"\nStopped after {TIMEOUT} seconds.", -1
                text = screen(out).replace(str(home), "~")  # btcli's own paths, without the server's layout
                cut = len(text) > MAX_OUT
                return {"status": "ok" if code == 0 else "error", "ansi": text[:MAX_OUT] + ("\n… output cut" if cut else ""),
                        "code": code, "took": round(time.time() - t, 2), "argv": ["btcli", *argv]}
            finally:
                self.slots.release()
        finally:
            lock.release()

    # ---------- commands that sign: the wallet's sheet ----------
    def _sheet(self, op, f, w, line):
        """The transaction sheet's fields from btcli's flags (hotkeys by address, or by a tracked hotkey's name)."""
        def hk(*keys):
            v = next((f[k] for k in keys if isinstance(f.get(k), str)), None)
            if v is None: return None
            name = v.split("/", 1)[-1]
            h = next((h for h in w["hotkeys"] if h["name"] in (v, name)), None)
            if h: return h["ss58"]
            if valid_ss58(v): return v
            raise TermError(f"“{v}” isn't one of {w['name']}'s hotkeys or an SS58 address. Use the validator's hotkey address.")
        def num(*keys, kind=float):
            v = next((f[k] for k in keys if isinstance(f.get(k), str)), None)
            if v is None: return None
            try: return kind(v)
            except ValueError: raise TermError(f"{keys[0]} must be a number.")
        tol = num("--rate-tolerance")
        preset = {"all": f.get("--all") is True}
        if op == "stake": preset.update(netuid=num("--netuid", kind=int), hotkey=hk("--hotkey", "--include-hotkeys", "-H", "--wallet-hotkey"), amount=num("--amount-tao", "--amount"))
        elif op == "unstake": preset.update(netuid=num("--netuid", kind=int), hotkey=hk("--hotkey", "-H", "--wallet-hotkey"), amount=num("--amount-alpha", "--amount"))
        elif op == "move": preset.update(netuid=num("--origin-netuid", "--netuid", kind=int), hotkey=hk("--origin-hotkey", "--hotkey"),
                                         dest_netuid=num("--dest-netuid", kind=int), dest_hotkey=hk("--dest-hotkey"), amount=num("--amount-alpha", "--amount"))
        elif op == "unstake_all": preset.update(hotkey=hk("--hotkey", "-H", "--wallet-hotkey"))
        else: preset.update(dest=f.get("--dest") if isinstance(f.get("--dest"), str) else None, amount=num("--amount-tao", "--amount"))
        if tol is not None: preset["slippage"] = round(min(max(tol * 100, 0.1), 20), 2)
        preset = {k: v for k, v in preset.items() if v not in (None, False)}
        return {"status": "sign", "action": {"op": op, "wallet_id": w["id"], "preset": preset},
                "lines": [[T("→ ", "faint"), T(f"Opening {op.replace('_', ' ')} for {w['name']}", "b"), T(": review it, then your browser wallet signs.", "faint")]]}

    def complete(self, words):
        """Tab: what can follow the words typed so far."""
        if not words or words[0] != "btcli": return ["btcli"]
        if len(words) == 1: return sorted(COMPLETE)
        if len(words) == 2: return COMPLETE.get(ALIASES.get(words[1], words[1]), []) or FLAGS
        return FLAGS

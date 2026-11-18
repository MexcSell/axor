"""The VM Docker runner (D-013; docs/architecture/stabilization/D013_VM_RUNNER_DESIGN.md; G5-4 V4.2; Owner decision D-8 of
2026-11-13 with D8-a…h as recommended): Docker work for agents, in one throwaway KVM virtual machine per job.

- A job is validated here before any VM exists (validate): its kind, its files, every image it would pull. Pulls are by digest
  only (`name@sha256:…`): a tag alone is refused, in `images`, in every Dockerfile `FROM` and `COPY --from`, and in a Compose
  file. Compose services may not be privileged, share the VM's namespaces or mount paths outside the job's folder. A job that
  names a secret, or a push, isn't started: it needs a person's approval (design §5), and that path isn't built yet.
- One pod per job in the runner's own namespace (axor-runner, k8s/runner/58-runner.yaml; default-deny egress): QEMU with
  /dev/kvm and nothing else from the host, no privileges, no API token. The VM boots from the read-only base disk in the pod
  image (k8s/runner/build-base.sh), runs the fixed runner script (k8s/runner/job.py), powers off, and the pod hands the result
  to AXoR's endpoint for that one run (the sandbox proxy's port, a token of the run's own). Pod and ConfigMaps are deleted.
- Network: `none` (the VM reaches nothing), `registry` (pulls through the egress proxy, which is opened for this run with the
  registry hosts only, egress_proxy.py: hosts) or `build` (Owner decision D1 of 2026-11-13: the same, plus the package
  indexes the Owner approved, reachable only by the Dockerfile's build steps: a second proxy run with its own token is opened
  for registry hosts and exactly those index hosts, and only `docker build` is given it). Never direct internet, never
  another pod, never a host that isn't on a list; every host reached and every refusal is in the job's result.
- What comes back (design §4): status and exit; the log; every image pulled or built with its digest; peak memory and CPU per
  container and for the VM, disk, bytes in and out, duration, retries; container health; the environment (base disk sha256,
  runner script sha256, Docker and Compose versions, kernel, VM size, times); the inputs' hashes; what the VM and a container
  could reach; and the artifact files the job named. A benchmark's score is read from the artifact the job names
  (`score_file`), never from what an agent says (Q-4), and is reported apart from the exit code (Q-5).

Nothing here creates the namespace, the image or the RoleBinding: without them ready() answers no, agents aren't offered the
docker_job tool, and the `docker` readiness probe doesn't pass.
"""
import hashlib, json, logging, os, re, secrets, threading, time

import yaml

from .kube import KubeError
from . import sandbox as _sandbox
from .sandbox import EGRESS_PROXY, INPUT_BYTES, NO_PROXY, PROXY_URL, SECRET_PATH, chunks, pack

log = logging.getLogger("runner")
NS = os.getenv("RUNNER_NAMESPACE", "axor-runner")
IMAGE = os.getenv("RUNNER_IMAGE", "")                    # QEMU + supervise.py + the base disk (k8s/runner/Dockerfile)
PULL = os.getenv("RUNNER_IMAGE_PULL", "Never")
BASE_SHA = os.getenv("RUNNER_BASE_SHA256", "").lower()   # the base disk this server expects: a job on another one isn't evidence
AT_ONCE = max(1, min(2, int(os.getenv("RUNNER_MAX_JOBS", "2"))))  # D8-e: two KVM devices
SERVICE = "vm-docker"                                    # mw_sbx.services of a runner job (D8-b: no table of its own)
KINDS = ("build", "run", "bench")
TREE_MAX = 2000                                          # files a job's kept result lists one by one (inputs.tree)
SLOT_STEP = 2                                            # seconds between looks at a waiting job's cancelled test
MAX_TIMEOUT, MAX_BUILD, MAX_MEM, MAX_CPUS = 3600, 1800, 8192, 4
INPUT_CHUNKS = 4
REGISTRY_HOSTS = tuple(h.strip().lower() for h in os.getenv(
    "RUNNER_REGISTRY_HOSTS", "docker.io,docker.com,ghcr.io,pkg-containers.githubusercontent.com").split(",") if h.strip())  # D8-c
PIN = re.compile(r"^[a-z0-9]+(?:[._/:-][a-z0-9]+)*@sha256:[0-9a-f]{64}$")
REL = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._/@+-]{0,200}$")
SECRET_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,60}$")
JOB_FILE = ".axor-job/job.json"
RESULT_PATH = "/rlm/job/result"  # the sandbox proxy hands every /rlm/… request to the run's own hook: the runner's result uses that hook
VERIFY_DAYS = 7
MARK = re.compile(r"^@@AXOR-RESULT sha256:([0-9a-f]{64}) (\S+)$", re.M)


class RunnerError(Exception):
    """A job can't be taken or didn't run; the message is safe to show an agent."""


# ---------- validation: before any VM exists ----------
def _rel(path, what):
    p = (path or "").strip().replace("\\", "/")
    while p.startswith("./"): p = p[2:]
    if not p or p.startswith("/") or ".." in p.split("/") or not REL.match(p): raise RunnerError(f"{what} must be a path inside the job's files: {path!r}")
    return p


def _pinned(ref, where):
    if not PIN.match(ref or ""): raise RunnerError(f"{where}: {ref!r} isn't pinned. Name every image by digest (name@sha256:<64 hex>); a tag alone is refused.")
    return ref


def dockerfile_images(text, where="Dockerfile"):
    """The images a Dockerfile pulls: every FROM, COPY --from and RUN --mount from that isn't an earlier stage or scratch.
    Each must be pinned by digest. A FROM built from an argument, or an unpinned syntax directive, is refused."""
    lines, cur = [], ""
    for raw in (text or "").splitlines():
        s = raw.strip()
        m = re.match(r"^#\s*syntax\s*=\s*(\S+)", s, re.I)
        if m and not lines and not cur: _pinned(m[1], f"{where} (syntax directive)")
        if not s or s.startswith("#"): continue
        cur += s[:-1] + " " if s.endswith("\\") else s
        if not s.endswith("\\"): lines.append(cur); cur = ""
    if cur: lines.append(cur)
    stages, pulls, froms = set(), [], 0
    for i, ln in enumerate(lines):
        op, _, rest = ln.partition(" ")
        op, toks = op.upper(), rest.split()
        if op == "FROM":
            froms += 1
            args = [t for t in toks if not t.startswith("--")]
            if not args: raise RunnerError(f"{where}: a FROM names no image.")
            img = args[0]
            if "$" in img: raise RunnerError(f"{where}: FROM {img} takes its image from a build argument; write the pinned image itself.")
            if img.lower() != "scratch" and img not in stages: pulls.append(_pinned(img, f"{where} FROM"))
            if len(args) >= 3 and args[1].upper() == "AS": stages.add(args[2])
            stages.add(str(froms - 1))
        elif op in ("COPY", "ADD", "RUN"):
            for src in re.findall(r"--from=(\S+)", rest) + re.findall(r"--mount=\S*?from=([^,\s]+)", rest):
                if src not in stages and not src.isdigit(): pulls.append(_pinned(src, f"{where} {op} --from"))
    if not froms: raise RunnerError(f"{where} has no FROM.")
    return pulls


def compose_images(text, files, base=""):
    """The images a Compose file pulls, after checking that no service can reach past its container into the VM's own parts."""
    try: doc = yaml.safe_load(text or "") or {}
    except yaml.YAMLError as e: raise RunnerError(f"The Compose file isn't valid YAML: {str(e)[:160]}")
    if not isinstance(doc, dict) or not isinstance(doc.get("services"), dict) or not doc["services"]: raise RunnerError("The Compose file has no services.")
    if "include" in doc: raise RunnerError("The Compose file may not include other files.")
    pulls = []
    for name, s in doc["services"].items():
        if not isinstance(s, dict): raise RunnerError(f"Compose service {name} isn't a mapping.")
        for k in ("privileged", "devices", "cap_add", "extends", "device_cgroup_rules", "security_opt", "sysctls", "volumes_from"):
            if s.get(k): raise RunnerError(f"Compose service {name} may not set {k}.")
        for k in ("network_mode", "pid", "ipc", "userns_mode", "cgroup", "uts"):
            if str(s.get(k) or "").lower() == "host" or str(s.get(k) or "").startswith("container:"): raise RunnerError(f"Compose service {name} may not share the VM's {k}.")
        for v in s.get("volumes") or []:
            src = (v.get("source") if isinstance(v, dict) else str(v).split(":")[0]) or ""
            if isinstance(v, dict) and v.get("type") not in (None, "volume", "bind", "tmpfs"): raise RunnerError(f"Compose service {name}: volume type {v.get('type')} isn't allowed.")
            if src.startswith(("/", "~")) or ".." in src.split("/") or "docker.sock" in src:
                raise RunnerError(f"Compose service {name} may mount only folders of the job (./…) and named volumes, not {src!r}.")
        b = s.get("build")
        if b:
            ctx = (b if isinstance(b, str) else (b or {}).get("context") or ".")
            df = "Dockerfile" if isinstance(b, str) else (b or {}).get("dockerfile") or "Dockerfile"
            path = "/".join(x for x in (base, "" if ctx in (".", "./") else _rel(ctx, f"Compose service {name}'s build context"), df) if x)
            if path not in files: raise RunnerError(f"Compose service {name} builds from {path}, which isn't among the job's files.")
            pulls += dockerfile_images(files[path], path)
        elif s.get("image"): pulls.append(_pinned(str(s["image"]), f"Compose service {name}"))
        else: raise RunnerError(f"Compose service {name} has neither an image nor a build.")
    return pulls


HOSTNAME = re.compile(r"^(?=.{4,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")


def package_hosts(value):
    """The package-index hosts the Owner approved for builds (D1), from their stored form (a JSON list): lower-case host names,
    exact hosts only (no wildcard, no port, no path), at most 12. Anything else in the list is dropped."""
    try: v = json.loads(value) if isinstance(value, str) else list(value or [])
    except (ValueError, TypeError): return []
    return sorted({h for h in (str(x).strip().lower().rstrip(".") for x in v if isinstance(x, str)) if HOSTNAME.match(h) and re.search(r"\.[a-z]{2,}$", h)})[:12]  # a name, never an address


def workspace_roots(spec):
    """(roots, snapshot) a job asks of its mission's workspace (D-032c step 1): the folders or files it names there, and the
    snapshot it wants (None: the newest). ([], None) for a job that asks nothing, which is every job before this field existed.
    A root is a path inside the workspace, never the whole of it: the job says which part is the candidate."""
    spec = spec or {}
    roots = list(dict.fromkeys(_rel(str(p), "workspace_paths").rstrip("/") for p in spec.get("workspace_paths") or [] if str(p or "").strip()))
    if len(roots) > 12: raise RunnerError("A job names at most 12 workspace_paths.")
    snap = spec.get("workspace_snapshot")
    if snap in (None, "", 0): return sorted(roots), None
    if isinstance(snap, bool) or not isinstance(snap, int) or snap < 0: raise RunnerError("workspace_snapshot is a snapshot's number (0 or nothing for the newest).")
    if not roots: raise RunnerError("workspace_snapshot names a snapshot of the mission's workspace, so the job also names workspace_paths.")
    return sorted(roots), snap


def under(path, roots): return any(path == r or path.startswith(r + "/") for r in roots)


def validate(spec, files, packages=()):
    """(job, held) for what an agent asked: the job as the VM will get it, and the reasons it needs a person's approval first
    (held: it isn't started). Raises RunnerError for anything a job may not ask. Pure: it reads the spec and the files only.
    packages: the package-index hosts the Owner approved for builds on this server (package_hosts()); network `build` needs them."""
    spec = spec or {}
    kind = (spec.get("kind") or "").strip().lower()
    held = []
    if kind == "push": held.append("it pushes an image to a registry")
    elif kind not in KINDS: raise RunnerError(f"kind must be one of {', '.join(KINDS)} (push needs a person's approval).")
    network = (spec.get("network") or "none").strip().lower()
    if network not in ("none", "registry", "build"):
        raise RunnerError("network is none, registry (pulls by digest through the egress proxy) or build (the same, plus the approved package indexes while the Dockerfile builds).")
    job = {"v": 1, "kind": kind, "network": network}
    if network == "build":
        if not (spec.get("dockerfile") or "").strip(): raise RunnerError("network: build is for a job that builds a Dockerfile: the package indexes are reachable only by its build steps.")
        hosts = package_hosts(list(packages or ()))
        if not hosts: raise RunnerError("No package index is approved for builds on this server, so network: build isn't available. The Owner names the hosts.")
        job["package_hosts"] = hosts  # in the job, so the job's hash says which indexes its build could reach
    pulls = [_pinned(str(i).strip(), "images") for i in spec.get("images") or []]
    if len(pulls) > 12: raise RunnerError("A job pulls at most 12 images.")
    job["images"] = list(dict.fromkeys(pulls))
    if (spec.get("dockerfile") or "").strip():
        job["dockerfile"] = _rel(spec["dockerfile"], "dockerfile")
        if job["dockerfile"] not in files: raise RunnerError(f"There's no {job['dockerfile']} among the job's files.")
        job["context"] = _rel(spec["context"], "context") if (spec.get("context") or "").strip() not in ("", ".", "./") else "."
        pulls += dockerfile_images(files[job["dockerfile"]], job["dockerfile"])
    if (spec.get("compose") or "").strip():
        job["compose"] = _rel(spec["compose"], "compose")
        if job["compose"] not in files: raise RunnerError(f"There's no {job['compose']} among the job's files.")
        pulls += compose_images(files[job["compose"]], files, job["compose"].rpartition("/")[0])
    cmd = (spec.get("command") or "").strip()
    if len(cmd) > 4000: raise RunnerError("The command is over 4,000 characters: put it in a script among the files.")
    if cmd: job["command"] = cmd
    if kind == "build" and not (job.get("dockerfile") or job.get("compose")): raise RunnerError("A build job names a dockerfile or a compose file.")
    if kind in ("run", "bench") and not (cmd or job.get("compose")): raise RunnerError(f"A {kind} job gives a command (or a compose file to bring up).")
    if pulls and network == "none": raise RunnerError("This job pulls images, so it needs network: registry. With network: none only FROM scratch builds work.")
    job["timeout_s"] = max(30, min(int(spec.get("timeout_s") or 600), MAX_TIMEOUT))
    job["build_timeout_s"] = MAX_BUILD
    job["memory_mb"] = max(1024, min(int(spec.get("memory_mb") or 4096), MAX_MEM))
    job["cpus"] = max(1, min(int(spec.get("cpus") or 2), MAX_CPUS))
    arts = [_rel(p, "an artifact") for p in spec.get("artifacts") or []]
    if (spec.get("score_file") or "").strip():
        if kind != "bench": raise RunnerError("Only a bench job names a score_file.")
        job["score_file"] = _rel(spec["score_file"], "score_file"); arts.append(job["score_file"])
    job["artifacts"] = list(dict.fromkeys(arts))
    if len(job["artifacts"]) > 20: raise RunnerError("A job returns at most 20 artifact files.")
    names = [str(s).strip() for s in spec.get("secrets") or [] if str(s).strip()]
    for n in names:
        if not SECRET_NAME.match(n): raise RunnerError(f"A secret is named like BEX_CHALLENGE_API_KEY, never given by value: {n[:40]!r}")
    if names: held.append(f"it names the secret{'s' if len(names) > 1 else ''} {', '.join(names)}"); job["secrets"] = names
    src = spec.get("source") or {}
    if isinstance(src, dict) and (src.get("repo") or src.get("commit")):
        if not re.fullmatch(r"[0-9a-f]{7,64}", str(src.get("commit") or "")): raise RunnerError("source.commit is a git commit hash.")
        job["source"] = {"repo": str(src.get("repo") or "")[:300], "commit": str(src["commit"]).lower(), "basis": "declared by the submitter, not checked by the runner"}
    roots, snap = workspace_roots(spec)
    if roots: job["workspace_paths"] = roots       # only when asked: a job that asks nothing of the workspace keeps the hash it always had
    if snap is not None: job["workspace_snapshot"] = snap
    if network in ("registry", "build"):
        job["check_hosts"] = sorted({_registry_host(p) for p in dict.fromkeys(pulls)})[:6] or ["registry-1.docker.io"]
        g = (spec.get("check_git") or "").strip()
        if g:
            if not re.fullmatch(r"https://[A-Za-z0-9.-]+/[A-Za-z0-9._/-]{1,200}", g): raise RunnerError("check_git is an https:// repository URL.")
            job["check_git"] = g
    return job, held


def _registry_host(ref):
    """The registry an image reference pulls from: its first path component when that is a host (it has a dot or a port, and
    something follows it); otherwise Docker Hub. `python:3.12-slim@sha256:…` is Docker Hub: the colon there is a tag."""
    name = ref.split("@")[0]
    first = name.split("/")[0]
    return first.split(":")[0] if "/" in name and ("." in first or ":" in first or first == "localhost") and first != "docker.io" else "registry-1.docker.io"


def job_sha(job):
    """The job's own hash: the job as validated, without the run's id (the same job run twice has the same hash)."""
    return hashlib.sha256(json.dumps({k: v for k, v in job.items() if k not in ("id", "proxy", "build_proxy")}, sort_keys=True).encode()).hexdigest()


def inputs(job, files, workspace=None):
    """What went in, by hash: the job as validated and every file sent, so the same job can be run again and compared. `tree` is
    the per-file list files_sha256 is made from (D-034: a release's frozen measuring job is recognized by the hash of its harness
    files, which is a subset of this list); left out above TREE_MAX files, and such a job can't be a measuring job.
    workspace: where the files under the job's workspace_paths came from (the mission, the snapshot, the roots), as AXoR read them."""
    shas = {p: hashlib.sha256(t.encode()).hexdigest() for p, t in sorted(files.items())}
    tree = "".join(f"{h}  {p}\n" for p, h in shas.items())
    return {"job_sha256": job_sha(job), "files": len(files), "files_sha256": hashlib.sha256(tree.encode()).hexdigest(),
            **({"tree": shas} if len(shas) <= TREE_MAX else {}), **({"source": job["source"]} if job.get("source") else {}),
            **({"workspace": workspace} if workspace else {})}


# ---------- D-034: the measuring job a release freezes (which job gave a score, not only that some job did) ----------
def measure_sha(job):
    """A job's hash as a measuring job: the spec without the run's id, the proxy tokens, the declared source and the workspace
    snapshot it named (the source and the snapshot say which candidate, and differ per candidate; everything else, the Owner's
    package hosts and the workspace roots included, configures the measurement)."""
    return hashlib.sha256(json.dumps({k: v for k, v in (job or {}).items() if k not in ("id", "proxy", "build_proxy", "source", "secrets", "workspace_snapshot")},
                                     sort_keys=True).encode()).hexdigest()


def harness_sha(tree, root):
    """The hash of a job's harness: every file sent into it that is not under the candidate root. The root is the release's, never
    the job's, so a job can't shrink its own harness."""
    root = (root or "").strip().strip("/") + "/"
    return hashlib.sha256("".join(f"{h}  {p}\n" for p, h in sorted((tree or {}).items()) if not p.startswith(root)).encode()).hexdigest()


def candidate_sha(tree, root):
    """D-034a: the hash of a job's candidate: every file sent into it that IS under the candidate root (harness_sha's complement,
    the same per-file lines). A release keeps it from its reference run, so the release says which candidate it measures."""
    root = (root or "").strip().strip("/") + "/"
    return hashlib.sha256("".join(f"{h}  {p}\n" for p, h in sorted((tree or {}).items()) if p.startswith(root)).encode()).hexdigest()


def measure_of(doc, root):
    """What a job's kept result (stored()) says about it as a measuring job, for the release's candidate root; None when the result
    holds no file list (a job from before D-034, or one with more than TREE_MAX files) or names no score file."""
    job, tree = (doc or {}).get("job") or {}, ((doc or {}).get("inputs") or {}).get("tree")
    if not isinstance(tree, dict) or not job.get("score_file") or not (root or "").strip().strip("/"): return None
    pulled = sorted({d for i in doc.get("images") or [] if i.get("how") == "pulled" for d in (i.get("digests") or [i.get("id")]) if d})
    return {"job_sha256": measure_sha(job), "harness_sha256": harness_sha(tree, root), "images": pulled, "score_file": job["score_file"],
            "candidate_root": root.strip().strip("/"), "candidate_sha256": candidate_sha(tree, root)}


# The parts that configure the measurement. The candidate (candidate_sha256, D-034a) is deliberately not one of them: two releases
# of one trial measure with the same job and different candidates (evolution.measured compares these keys only).
MEASURE_WHAT = {"job_sha256": "the job (its command, images, limits or network)", "harness_sha256": "the harness files", "images": "the images it pulled",
                "score_file": "the score file"}


def differs(doc, measure):
    """Why a job's kept result is not the release's frozen measuring job: the first part that differs, in words; "" when it is."""
    got = measure_of(doc, (measure or {}).get("candidate_root"))
    if got is None: return "its result holds no file list or no score file, so it can't be compared with the release's measuring job"
    k = next((k for k in MEASURE_WHAT if got.get(k) != measure.get(k)), None)
    if not k:
        # D-034a: it is the measuring job; is it measuring the candidate this release froze? A release frozen before D-034a kept
        # no candidate hash and can't say: for it any candidate under the root counts, as before.
        if measure.get("candidate_sha256") and got["candidate_sha256"] != measure["candidate_sha256"]:
            return (f"it measured another candidate than the one this release froze (the files under {measure.get('candidate_root')}/ differ): "
                    "freeze a new release to measure it")
        return ""
    why = f"its job isn't this release's measuring job: {MEASURE_WHAT[k]} differ{'s' if k == 'score_file' else ''}"
    if k == "images":  # name them: a candidate with another base image is another thing being measured, and needs a release of its own
        new, gone = sorted(set(got["images"]) - set(measure.get("images") or [])), sorted(set(measure.get("images") or []) - set(got["images"]))
        short = lambda ds: ", ".join(d[:19] + "…" for d in ds[:3])
        why += " (" + "; ".join(x for x in (f"it pulled {short(new)}, which the frozen job doesn't name" if new else "",
                                            f"it didn't pull {short(gone)}" if gone else "") if x) + ": freeze a new release to measure it)"
    return why


def summary(job):
    """One line for the run's record (mw_sbx.command)."""
    parts = [f"docker_job {job['kind']}"] + [f"{k}={job[k]}" for k in ("dockerfile", "compose") if job.get(k)]
    if job.get("images"): parts.append(f"images={len(job['images'])}")
    return " ".join(parts) + (f": {job['command']}" if job.get("command") else "")


def read_score(text):
    """The score a benchmark wrote to its score_file: a JSON object with a numeric "score" (and, if it gives them, integer
    "solved" and "tasks"). (score dict, "") or (None, why). The exit code plays no part (Q-5)."""
    try: d = json.loads(text or "")
    except ValueError: return None, "the score file isn't JSON"
    if not isinstance(d, dict) or isinstance(d.get("score"), bool) or not isinstance(d.get("score"), (int, float)): return None, 'the score file has no numeric "score"'
    out = {"score": float(d["score"])}
    for k in ("solved", "tasks"):
        if isinstance(d.get(k), int) and not isinstance(d.get(k), bool) and d[k] >= 0: out[k] = d[k]
    return out, ""


# ---------- the stored result of a job: what later readers (benchmarks, missions, probes) trust ----------
def document(result, job):
    """The job's result as kept in the team's files (runs/sbx-<id>/result.json): everything but the log and the artifact texts."""
    return {"v": 1, "job": {k: v for k, v in job.items() if k != "secrets"}, **{k: result.get(k) for k in
            ("status", "exit", "error", "seconds", "pod", "images", "stats", "health", "environment", "inputs", "net", "artifacts", "score", "score_error")}}


def stored(db, wid, sid):
    """The kept result of runner job `sid` of team `wid`, or None: only for a job that finished cleanly (done, exit 0), and only
    when the file in the team's files is still the one the run's own record names by sha256 (an edited file isn't evidence)."""
    s = db.q("SELECT id, status, exit_code, finished, output, services FROM mw_sbx WHERE id=? AND comp_id=?", (sid, wid), one=True)
    if not s or s["services"] != SERVICE or s["status"] != "done" or s["exit_code"] != 0 or not s["finished"]: return None
    m = MARK.search(s["output"] or "")
    if not m: return None
    f = db.q("SELECT content FROM mw_files WHERE comp_id=? AND path=?", (wid, m[2]), one=True)
    if not f or hashlib.sha256((f["content"] or "").encode()).hexdigest() != m[1]: return None
    try: d = json.loads(f["content"])
    except ValueError: return None
    return {**d, "sbx": s["id"], "finished": s["finished"], "result_sha256": m[1]} if isinstance(d, dict) else None


def release_measure(db, release_id):
    """The frozen measuring job of a release (D-034), by the release's id; None when it has none, or on a server from before."""
    if not release_id: return None
    try: r = db.q("SELECT measure FROM mw_release WHERE id=?", (release_id,), one=True)
    except Exception: return None  # noqa: BLE001 - no release table, or no such column yet
    try: m = json.loads((r or {}).get("measure") or "null")
    except ValueError: m = None
    return m if isinstance(m, dict) and m.get("job_sha256") and m.get("harness_sha256") else None


def backed(db, wid, ref, score, measure=None):
    """True when `ref` is `job:<id>` of this team, that job's kept result is intact (stored) and it still says this score. The one
    rule for "a job's own output gave the score": a row that only names a job, or whose filed number differs from the job's,
    isn't measured (missions._ev_bench and the trial reader apply the same rule to their own rows).
    measure (D-034): the frozen measuring job of the row's release, when it has one. Then the job must also be that job: a score
    another job gave (the team's mock validator, say) isn't this release's measurement. None: as before D-034."""
    m = re.fullmatch(r"job:(\d+)", ref or "")
    if not m or score is None: return False
    try: d = stored(db, wid, int(m[1]))
    except Exception: return False  # noqa: BLE001 - a server without the run or file tables holds no kept result
    sc = (d or {}).get("score")
    sc = sc.get("score") if isinstance(sc, dict) else None
    if not (isinstance(sc, (int, float)) and not isinstance(sc, bool) and abs(sc - score) < 1e-9): return False
    return not (measure and differs(d, measure))


# ---------- running ----------
def proxy_run(token, wall, exact=None):
    """What a job's run at the egress proxy is opened with: the registry hosts (for the build's run also exactly the approved
    package hosts), and https only. Https-only has no switch: a job's pulls and its build's installs speak https on port 443
    and nothing else, so a plain http:// request is refused at the proxy whatever host it names (the AEF's package policy,
    applied to VM jobs)."""
    return {"token": token, "up_mb": 50 if exact is None else 20, "down_mb": 8000, "ttl_s": wall + 900, "hosts": list(REGISTRY_HOSTS),
            **({"hosts_exact": list(exact)} if exact is not None else {}), "https_only": True}


def https_confirmed(opened, what):
    """Did the proxy say it enforces https-only for the run it just opened? True only when its answer says so. Anything else
    means the job isn't started: an answer that says no, and an answer that doesn't say (a proxy from before it could say, or
    something else answering in its place). Never a run with less than was asked, and never one nobody confirmed."""
    v = opened.get("https_only") if isinstance(opened, dict) else None
    if v is True: return True
    if v is None: raise RunnerError(f"The egress proxy didn't say it enforces https-only for the job's {what} (a proxy from before it could?), so the job isn't started.")
    raise RunnerError(f"The egress proxy opened the job's {what} without https-only, so the job isn't started.")


class Runner:
    def __init__(self, kube, proxy, egress):
        """kube: AXoR's cluster client. proxy, egress: the sandbox's own (its result port and the egress proxy's control side)."""
        self.kube, self.proxy, self.egress = kube, proxy, egress
        self.slots = threading.BoundedSemaphore(AT_ONCE)
        self._ready, self._checked = (False, "Not checked yet."), 0.0
        if self.configured()[0]: threading.Thread(target=self._sweep, daemon=True, name="runner-sweep").start()

    def configured(self):
        """(True, "") when this server is set up to try (a switch, a cluster, an image, the result port), else (False, why)."""
        if os.getenv("RUNNER", "1") == "0": return False, "The VM runner is switched off on this server (RUNNER=0)."
        if not self.kube or not getattr(self.kube, "enabled", False): return False, "The VM runner runs on Kubernetes, and this AXoR isn't on a cluster."
        if not IMAGE: return False, "No VM runner image is set (RUNNER_IMAGE): the runner isn't installed on this server."
        if not getattr(self.proxy, "server", None): return False, "AXoR's result port for runs isn't listening."
        return True, ""

    def quota(self):
        """KVM devices the runner's namespace may use; raises KubeError when it can't be read."""
        q = self.kube.get(f"/api/v1/namespaces/{NS}/resourcequotas/runner") or {}
        v = ((q.get("spec") or {}).get("hard") or {}).get("requests.axor.dev/kvm")
        return int(v) if str(v or "").isdigit() else 0

    def ready(self):
        """(True, "") when a job can start, else (False, why). The namespace and its KVM quota are asked at most once a minute."""
        ok, why = self.configured()
        if not ok: return ok, why
        if time.time() - self._checked > 60:
            try:
                self.kube.call("GET", f"/api/v1/namespaces/{NS}/pods", {"limit": 1}, timeout=10)
                self._ready = (True, "") if self.quota() > 0 else (False, f"The {NS} namespace allows no KVM device.")
            except KubeError as e:
                self._ready = (False, f"The {NS} namespace isn't set up for AXoR (k8s/runner/58-runner.yaml, the Owner's step)." if e.status in (403, 404)
                               else f"Kubernetes didn't answer: {e}")
            self._checked = time.time()
        return self._ready

    @staticmethod
    def endpoints():
        """Where a job's pod reaches AXoR's run port and the egress proxy: the sandbox's own answer (sandbox.endpoints, the one
        place both kinds of pod take them from). With SANDBOX_BY_ADDRESS=1 both come back as addresses resolved in AXoR, so the
        pod needs no DNS: that, with the runner's network policy without its DNS rule (k8s/runner/58-runner-no-dns.candidate.yaml),
        closes DNS as a way out of a job's VM. A name that can't be resolved means the job isn't started. On a tree without
        sandbox.endpoints the configured names are used, as before."""
        fn = getattr(_sandbox, "endpoints", None)
        if fn is None: return {"proxy_url": PROXY_URL, "egress_proxy": EGRESS_PROXY, "no_proxy": NO_PROXY, "by_address": False}
        try: return fn()
        except _sandbox.SandboxError as e: raise RunnerError(f"The job wasn't started: {e}")

    def _sweep(self):
        for kind in ("pods", "configmaps"):
            try:
                for o in self.kube.items(f"/api/v1/namespaces/{NS}/{kind}", {"labelSelector": "app=axor-runner"}):
                    self.kube.delete(f"/api/v1/namespaces/{NS}/{kind}/{o['metadata']['name']}", {"gracePeriodSeconds": 0} if kind == "pods" else None)
            except KubeError as e: log.info("runner: couldn't sweep %s: %s", kind, e)

    def run(self, job, files, label="", cancelled=lambda: False, started=lambda pod: None, workspace=None):
        """Runs a validated job in a fresh VM; blocks until it ends. Returns the result (see the module's header). Raises
        RunnerError when the job couldn't start at all."""
        ok, why = self.ready()
        if not ok: raise RunnerError(why)
        if job.get("secrets") or job.get("kind") not in KINDS: raise RunnerError("This job needs a person's approval and isn't started.")
        roots = job.get("workspace_paths") or []
        if roots and not (isinstance(workspace, dict) and workspace.get("snapshot")):  # the caller read the workspace (mining_work._docker_job); nothing here can
            raise RunnerError("This job names workspace_paths, and no workspace was read for it: it isn't started.")
        net = job["network"] != "none"
        withheld = sorted(p for p in files if SECRET_PATH.search(p)) if net else []
        files = {p: t for p, t in files.items() if p not in withheld and not p.startswith(".axor-job/")}
        send = {**files, JOB_FILE: json.dumps(job)}
        cap = INPUT_BYTES * INPUT_CHUNKS - 8192
        total = sum(len(t.encode()) + len(p) + 16 for p, t in send.items())
        omitted = []
        if total > cap or any(len(t.encode()) > INPUT_BYTES - 1024 for t in send.values()):
            named = " ".join(str(job.get(k) or "") for k in ("dockerfile", "compose", "command")) + " " + JOB_FILE
            got = pack(send, named, cap - 16384, INPUT_BYTES - 1024)
            if got is None or JOB_FILE not in got[0]: raise RunnerError(f"The job's files come to {total // 1000} kB; a job takes at most {cap // 1000} kB. Narrow it with paths.")
            send, omitted = got
        lost = [p for p, _ in omitted if under(p, roots)]
        if lost:  # never part of a candidate: a candidate measured without one of its files is another candidate
            raise RunnerError(f"The job's files don't fit, and {len(lost)} of the files left out would be from the workspace ({', '.join(lost[:5])}{' and more' if len(lost) > 5 else ''}). "
                              "Name fewer or smaller workspace_paths, or narrow the team's files with paths.")
        # The record is of what is sent, after the files that didn't fit were left out (they are named in the result's `omitted`):
        # a file the VM never got must not count toward the job's file list, or toward the harness a release froze (D-034).
        rec = inputs(job, {p: t for p, t in send.items() if p != JOB_FILE}, workspace if roots else None)
        manifest, data = {}, {}
        for i, (path, text) in enumerate(sorted(send.items())): manifest[f"f{i}"], data[f"f{i}"] = path, text
        data["manifest.json"] = json.dumps(manifest)
        parts = chunks(data)
        if len(parts) > INPUT_CHUNKS: raise RunnerError("The job's files don't fit the runner's input. Narrow it with paths.")
        # A job cancelled while it waits for a VM (a person's stop, or an emergency stop of its mission through the caller's
        # cancelled test) is never started: no proxy run, no ConfigMap and no pod is made for it. It waits in short steps to notice.
        never = lambda: finish(job, {}, "cancelled", None, "Stopped before it started: nothing was created for it.", "", None, rec, 0.0, None, withheld, [p for p, _ in omitted])
        waited = time.time()
        while not self.slots.acquire(timeout=SLOT_STEP):
            if cancelled(): return never()
            if time.time() - waited > 600: raise RunnerError(f"The VM runner is busy ({AT_ONCE} jobs at once): try again in a few minutes.")
        if cancelled():
            self.slots.release()
            return never()
        name = f"job-{int(time.time())}-{secrets.token_hex(3)}"
        maps = [name] + [f"{name}-{i}" for i in range(1, len(parts))]
        got, t0 = {}, time.time()

        def hook(method, sub, body):
            if method != "POST" or sub != RESULT_PATH: return 404, {"error": {"message": "No such endpoint.", "code": 404}}
            if got: return 409, {"error": {"message": "This job already reported.", "code": 409}}
            got.update(body); return 200, {"ok": True}

        token = self.proxy.open(0.0, hook)  # a cap of 0: a job has no inference budget, only the result endpoint
        net_token, egress, status, code, err, out = (secrets.token_urlsafe(24) if net else None), None, "error", None, "", ""
        build_token, build_egress = (secrets.token_urlsafe(24) if job["network"] == "build" else None), None
        wall = job["timeout_s"] + (job["build_timeout_s"] if job.get("dockerfile") or job.get("compose") else 0) + 300
        https = {}  # per proxy run opened for this job: did the proxy say it enforces https-only
        try:
            ep = self.endpoints()  # before anything is created: a job whose pod can't be told where AXoR is isn't started
            if net_token:
                try: opened = self.egress._call("POST", "/runs", proxy_run(net_token, wall))
                except (OSError, ValueError) as e: raise RunnerError(f"The egress proxy didn't take the job ({getattr(e, 'reason', e)}), so it can't pull.")
                https["registry"] = https_confirmed(opened, "run")
            if build_token:  # D1: its own run, for registry hosts and exactly the approved package indexes; only `docker build` gets this token
                try: opened = self.egress._call("POST", "/runs", proxy_run(build_token, wall, job["package_hosts"]))
                except (OSError, ValueError) as e: raise RunnerError(f"The egress proxy didn't take the job's build ({getattr(e, 'reason', e)}), so it can't reach the package indexes.")
                https["build"] = https_confirmed(opened, "build run")
            for cm, part in zip(maps, parts):
                self.kube.call("POST", f"/api/v1/namespaces/{NS}/configmaps",
                               body={"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": cm, "labels": {"app": "axor-runner"}}, "data": part})
            self.kube.call("POST", f"/api/v1/namespaces/{NS}/pods", body=self._pod(name, job, token, net_token, maps, label, wall, build_token, ep))
            started(name)
            status, code, err = self._wait(name, wall, cancelled, got)
            try: out = self.kube.logs(NS, name, "vm", tail=200, timestamps=False)
            except KubeError as e: out = f"(couldn't read the pod's log: {e})"
        except KubeError as e: err = f"Kubernetes refused the job: {e}"
        except RunnerError as e: err = str(e)
        finally:
            for kind, n in [("pods", name)] + [("configmaps", cm) for cm in maps]:
                try: self.kube.delete(f"/api/v1/namespaces/{NS}/{kind}/{n}", {"gracePeriodSeconds": 0} if kind == "pods" else None)
                except KubeError as e: log.warning("runner: couldn't delete %s %s: %s", kind, n, e)
            self.proxy.close(token)
            if net_token: egress = self.egress.close(net_token)
            if build_token: build_egress = {**(self.egress.close(build_token) or {}), "package_hosts": list(job["package_hosts"]), "opened": t0, "closed": time.time()}
            self.slots.release()
        return finish(job, got, status, code, err, out, name, rec, round(time.time() - t0, 1), egress, withheld, [p for p, _ in omitted], build_egress, https)

    def _wait(self, name, wall, cancelled, got):
        """(status, exit, error) of the pod, once its VM container ended, the time is up or the job is cancelled."""
        deadline = time.time() + wall + 120
        while True:
            time.sleep(2)
            if cancelled(): return "cancelled", None, "Stopped before it finished."
            try: p = self.kube.get(f"/api/v1/namespaces/{NS}/pods/{name}")
            except KubeError as e: return "error", None, f"Lost track of the job: {e}"
            if not p: return "error", None, "The job's pod disappeared."
            st = p.get("status") or {}
            for cs in st.get("containerStatuses") or []:
                w = (cs.get("state") or {}).get("waiting") or {}
                if w.get("reason") in ("ErrImagePull", "ImagePullBackOff", "InvalidImageName", "CreateContainerConfigError", "CreateContainerError", "ErrImageNeverPull"):
                    return "error", None, f"The runner pod couldn't start: {w.get('reason')}: {(w.get('message') or '')[:300]}"
            vm = next((cs for cs in st.get("containerStatuses") or [] if cs["name"] == "vm"), None)
            done = (vm or {}).get("state", {}).get("terminated")
            if done: return ("done" if done.get("exitCode") == 0 else "failed"), done.get("exitCode"), ""
            if st.get("phase") in ("Succeeded", "Failed"): return "failed", None, st.get("message") or st.get("reason") or "The pod ended."
            if time.time() > deadline: return "timeout", None, "The job took too long (or never started) and was stopped."

    def _pod(self, name, job, token, net_token, maps, label, wall, build_token=None, ep=None):
        ep = ep or self.endpoints()
        env = {"AXOR_RESULT_URL": f"{ep['proxy_url']}/t/{token}{RESULT_PATH}", "AXOR_TIMEOUT": str(wall - 240), "AXOR_NETWORK": job["network"],
               "VM_CPUS": str(job["cpus"]), "VM_MEM_MB": str(job["memory_mb"]), "NO_PROXY": ep["no_proxy"], "no_proxy": ep["no_proxy"]}
        labels = {"app": "axor-runner"}
        if net_token:  # the label opens the way to the egress proxy (58-runner.yaml); the token is what the proxy lets through, for registry hosts only
            labels["axor.dev/internet"] = "on"
            env["AXOR_PROXY"] = f"http://{net_token}:x@{ep['egress_proxy']}"
            if build_token: env["AXOR_BUILD_PROXY"] = f"http://{build_token}:x@{ep['egress_proxy']}"
        vm = {"name": "vm", "image": IMAGE, "imagePullPolicy": PULL, "workingDir": "/work",
              "env": [{"name": k, "value": v} for k, v in env.items()],
              "securityContext": {"privileged": False, "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}},
              "resources": {"requests": {"cpu": "1", "memory": f"{job['memory_mb'] + 512}Mi", "axor.dev/kvm": "1"},
                            "limits": {"cpu": str(job["cpus"] + 1), "memory": f"{job['memory_mb'] + 1024}Mi", "ephemeral-storage": "30Gi", "axor.dev/kvm": "1"}},
              "volumeMounts": [{"name": "input", "mountPath": "/input", "readOnly": True}, {"name": "work", "mountPath": "/work"}]}
        return {"apiVersion": "v1", "kind": "Pod",
                "metadata": {"name": name, "labels": labels, "annotations": {"axor.dev/run": (label or "")[:200]}},
                "spec": {"restartPolicy": "Never", "activeDeadlineSeconds": wall + 300, "automountServiceAccountToken": False, "enableServiceLinks": False,
                         "terminationGracePeriodSeconds": 5, "securityContext": {"seccompProfile": {"type": "RuntimeDefault"}},
                         "containers": [vm],
                         "volumes": [{"name": "input", "projected": {"sources": [{"configMap": {"name": cm}} for cm in maps]}},
                                     {"name": "work", "emptyDir": {"sizeLimit": "28Gi"}}]}}


def finish(job, got, status, code, err, pod_log, pod, rec, seconds, egress=None, withheld=(), omitted=(), build_egress=None, https=None):
    """The job's result from what the pod handed over (got: {"supervisor", "result", "files"}) and how the pod itself ended.
    The VM's own status and exit win when it reported; without a report the job is an error or a timeout, never done."""
    sup, res = got.get("supervisor") or {}, got.get("result")
    if status == "cancelled": res = None
    if res:
        status, code, err = res.get("status") or "error", res.get("exit"), res.get("error") or ""
        if status == "done" and code != 0: status = "failed"
    else:
        if status in ("done", "failed"): status = "timeout" if "time limit" in (sup.get("error") or "") else "error"
        err = err or sup.get("error") or "The VM ended without a result."
        code = None
    res = res or {}
    env = {**(res.get("environment") or {}), "base_disk_sha256": (sup.get("base") or {}).get("sha256"), "vm": sup.get("vm"), "pod_image": IMAGE}
    if status == "done" and (sup.get("inputs") or {}).get("job_sha256") != rec["job_sha256"]:
        status, err = "error", "The VM ran another job than the one AXoR validated (the job hashes differ)."
    if status == "done" and BASE_SHA and env.get("base_disk_sha256") != BASE_SHA:
        status, err = "error", f"The job ran on a base disk ({str(env.get('base_disk_sha256'))[:12]}) other than the one this server expects ({BASE_SHA[:12]})."
    files, arts = {}, {}
    for path, fact in (res.get("files") or {}).items():
        f = (got.get("files") or {}).get(path) or {}
        arts[path] = dict(fact)
        if "text" in f and "sha256" in fact:
            if hashlib.sha256(f["text"].encode()).hexdigest() == fact["sha256"]: files[path] = f["text"]
            else: arts[path]["error"] = "the file handed over isn't the one the VM hashed"
        elif "b64" in f: arts[path]["kept"] = False; arts[path]["note"] = "not text: recorded by sha256 only"
    out = {"status": status, "exit": code, "error": err, "seconds": seconds, "pod": pod, "services": [SERVICE], "cost": 0.0, "calls": 0,
           "output": (res.get("output") or "") if res else (sup.get("serial_tail") or pod_log or ""),
           "images": res.get("images") or [], "stats": res.get("stats") or {}, "health": res.get("health") or [], "environment": env,
           "inputs": rec,
           # https_only: asked for every proxy run of a job; confirmed only when the proxy said so for each run that was opened.
           # A job that never got as far as opening a run (stopped before it started) asked the proxy for nothing: no such line
           "net": ({**(res.get("net") or {}), "egress": egress, **({"build_egress": build_egress} if job["network"] == "build" else {}), "withheld": list(withheld),
                    **({"https_only": {"asked": True, "runs": dict(https),
                                       # confirmed: the proxy said so when it opened each run, and no run's closing record says otherwise
                                       # for every run this job's network needs (a building job has two), not only those it got to open
                                       "confirmed": all(https.get(k) is True for k in (("registry", "build") if job["network"] == "build" else ("registry",))) and
                                       all(r.get("https_only") is True for r in (egress, build_egress) if isinstance(r, dict) and "https_only" in r)}}
                       if https is not None else {})}
                   if job["network"] != "none" else None),
           "artifacts": arts, "files": files, **({"omitted": list(omitted)} if omitted else {})}
    c = (out["net"] or {}).get("container")
    if isinstance(c, dict) and c.get("ok") is False:
        # the VM's container probe (job.py, in the base disk) falls back to plain http for a client that can't tunnel https through
        # a proxy (busybox wget). Plain http is refused on an https-only run, so for such an image "not reached" says nothing
        # about https. Said here, with the record, until the probe itself changes with the next base disk.
        out["net"]["container"] = {**c, "note": "This run is https-only. The probe's last resort is plain http (for a client that can't tunnel https through "
                                                "a proxy, like busybox wget), which this run refuses: not reached this way doesn't mean https is closed."}
    if job.get("score_file"):  # read whenever the file came back, whatever the exit code (Q-5); only a clean job's score is evidence (stored())
        if job["score_file"] not in files: out["score"], out["score_error"] = None, f"the job returned no {job['score_file']}"
        else: out["score"], out["score_error"] = read_score(files[job["score_file"]])
    return out

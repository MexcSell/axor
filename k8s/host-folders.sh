#!/usr/bin/env bash
# The host folders My Knowledge's linked folders can reach (AXoR Host files, k8s/host/42-hostfiles.yaml). Each one is a
# read-only mount at /roots/<name> in the hostfiles pod; inside one, the page links any folder by its path.
#
#   k8s/host-folders.sh list                     the folders in the manifest, and what the running pod mounts
#   k8s/host-folders.sh add /opt/data [name]     reach another folder (read only)
#   k8s/host-folders.sh remove <name|path>       stop reaching it (its links stop syncing; what they read stays in My Knowledge)
#   ... --deploy                                 then run ./k8s/redeploy.sh (a production deploy)
#
# It edits the manifest's three entries for a folder (HOSTFILES_LABELS, a volumeMount, a volume) and checks the path first:
# it exists and is a real folder (no symbolic link), isn't / or a system folder (/etc, /root, /var/lib, …), and the pod's
# user (nobody, group 1000) can enter it; a folder already inside a mounted one needs no mount of its own.
set -euo pipefail
cd "$(dirname "$0")/.."
MANIFEST=${HOSTFILES_MANIFEST:-k8s/host/42-hostfiles.yaml}
deploy=0 args=()
for a in "$@"; do [[ $a == --deploy ]] && deploy=1 || args+=("$a"); done
cmd=${args[0]:-list}
[[ -f $MANIFEST ]] || { echo "No $MANIFEST" >&2; exit 2; }

set +e
python3 -I - "$MANIFEST" "$cmd" "${args[@]:1}" <<'PY'
import json, os, re, stat, sys

path, cmd, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
UID, GID = 65534, 1000            # the hostfiles pod's user and group (runAsUser / runAsGroup in the manifest)
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
SYSTEM = ("/etc", "/root", "/proc", "/sys", "/dev", "/boot", "/run", "/var/lib", "/var/run", "/var/log", "/usr", "/bin", "/sbin",
          "/lib", "/lib32", "/lib64", "/libx32", "/snap", "/srv/k3s", "/opt/containerd", "/tmp")
text = open(path).read()
lines = text.split("\n")

def die(msg, code=1): print(msg, file=sys.stderr); sys.exit(code)

li = next((i for i, l in enumerate(lines) if "name: HOSTFILES_LABELS" in l), None)
if li is None: die(f"{path}: no HOSTFILES_LABELS line")
m = re.search(r"value: '(.*)' \}", lines[li])
labels = json.loads(m.group(1)) if m else die(f"{path}: can't read HOSTFILES_LABELS")
mounts = {mm.group(1): i for i, l in enumerate(lines) if (mm := re.match(r"\s*- \{ name: ([a-z0-9-]+), mountPath: /roots/\1, readOnly: true \}", l))}
vols = {mm.group(1): (i, mm.group(2)) for i, l in enumerate(lines) if (mm := re.match(r"\s*- \{ name: ([a-z0-9-]+), hostPath: \{ path: ([^,]+), type: Directory \} \}", l))}

def inside(p, root): return p == root or p.startswith(root.rstrip("/") + "/")

def can_enter(p):
    """nobody (group 1000) reaches p: every folder on the way lets it through (x), and p itself lets it list (r+x)."""
    cur, parts = "/", [x for x in p.split("/") if x]
    for i, part in enumerate(parts):
        cur = os.path.join(cur, part)
        st = os.stat(cur)
        need = (stat.S_IROTH | stat.S_IXOTH) if i == len(parts) - 1 else stat.S_IXOTH
        gneed = (stat.S_IRGRP | stat.S_IXGRP) if i == len(parts) - 1 else stat.S_IXGRP
        if st.st_uid == UID: continue
        if st.st_gid == GID and st.st_mode & gneed == gneed: continue
        if st.st_mode & need == need: continue
        return cur
    return None

if cmd == "list":
    print(f"Host folders in {path} (read only, at /roots/<name> in the hostfiles pod):")
    for n in sorted(set(labels) | set(mounts) | set(vols)):
        ok = n in labels and n in mounts and n in vols
        host = vols.get(n, (None, labels.get(n)))[1]
        print(f"  {n:<16} {host or '?':<40} {'' if ok else '(incomplete: ' + ', '.join(x for x, s in (('label', labels), ('mount', mounts), ('volume', vols)) if n not in s) + ' missing)'}")
    sys.exit(0)

def save(new):
    open(path, "w").write("\n".join(new))

if cmd == "add":
    if not rest: die("add needs a path: k8s/host-folders.sh add /opt/data [name]", 2)
    want = rest[0]
    if not want.startswith("/"): die("A full path, like /opt/data.")
    if os.path.islink(want.rstrip("/") or "/"): die(f"{want} is a symbolic link: give the folder it points to.")
    p = os.path.realpath(want)
    if p == "/" or any(inside(p, s) or (inside(s, p) and os.path.exists(s)) for s in SYSTEM):  # nor a folder holding one
        die(f"{p}: not / or a system folder ({', '.join(SYSTEM[:8])}, …): they hold the server's own secrets.")
    if not os.path.isdir(p): die(f"{p} isn't a folder on this server.")
    for n, h in labels.items():
        if inside(p, h): print(f"{p} is inside {h} ({n}) already: the page reaches it by its path. Nothing to change."); sys.exit(3)
    name = rest[1] if len(rest) > 1 else re.sub(r"[^a-z0-9-]+", "-", os.path.basename(p).lower()).strip("-")[:40] or "folder"
    if not NAME.fullmatch(name): die(f"{name!r}: a name of lowercase letters, digits and dashes.")
    base, i = name, 2
    while name in labels or name in mounts or name in vols: name, i = f"{base[:37]}-{i}", i + 1
    blocked = can_enter(p)
    if blocked: die(f"The hostfiles pod's user (nobody, group {GID}) can't enter {blocked}: give it read access (e.g. chmod o+rx, or group {GID}) first.")
    wider = [n for n, h in labels.items() if inside(h, p)]
    labels[name] = p
    new = list(lines)
    new[li] = re.sub(r"value: '.*' \}", "value: '" + json.dumps(labels) + "' }", new[li])
    mi = max(mounts.values()) if mounts else next(i for i, l in enumerate(new) if l.strip() == "volumeMounts:")
    vi = max(v[0] for v in vols.values()) if vols else next(i for i, l in enumerate(new) if l.strip() == "volumes:")
    ind_m = re.match(r"\s*", new[mi]).group(0) + ("" if mounts else "  ")   # as the last mount, or under "volumeMounts:"
    ind_v = re.match(r"\s*", new[vi]).group(0) + ("" if vols else "  ")
    new.insert(vi + 1, f"{ind_v}- {{ name: {name}, hostPath: {{ path: {p}, type: Directory }} }}")
    new.insert(mi + 1, f"{ind_m}- {{ name: {name}, mountPath: /roots/{name}, readOnly: true }}")
    save(new)
    print(f"Added {name}: {p} (read only at /roots/{name}).")
    if wider: print(f"It holds {', '.join(wider)}: their links keep working; new paths inside them still go to the narrower one.")
    sys.exit(0)

if cmd == "remove":
    if not rest: die("remove needs a name or a path: k8s/host-folders.sh remove data", 2)
    key = rest[0].rstrip("/") or "/"
    name = key if key in labels or key in mounts or key in vols else next((n for n, h in labels.items() if h.rstrip("/") == key), None)
    if not name: die(f"No host folder {key!r}. k8s/host-folders.sh list shows them.")
    new = [l for i, l in enumerate(lines) if i != mounts.get(name) and i != vols.get(name, (None,))[0]]
    labels.pop(name, None)
    j = next(i for i, l in enumerate(new) if "name: HOSTFILES_LABELS" in l)
    new[j] = re.sub(r"value: '.*' \}", "value: '" + json.dumps(labels) + "' }", new[j])
    save(new)
    print(f"Removed {name}. Links on it stop syncing at the next deploy; what they read stays in My Knowledge until you unlink them.")
    sys.exit(0)

die(f"Unknown command {cmd!r}: list, add <path> [name], remove <name|path> (add --deploy to redeploy).", 2)
PY
rc=$?
set -e
(( rc == 3 )) && exit 0          # nothing to change
(( rc != 0 )) && exit $rc
[[ $cmd == list ]] && command -v kubectl >/dev/null && {
  live=$(kubectl -n axor-host get deploy hostfiles -o jsonpath='{range .spec.template.spec.volumes[*]}{.name}={.hostPath.path}{"  "}{end}' 2>/dev/null || true)
  echo "Running pod mounts: ${live:-unknown (no hostfiles deployment?)}"
}
if [[ $cmd != list ]]; then
  if (( deploy )); then echo "== redeploying"; exec ./k8s/redeploy.sh
  else echo "Not live yet: run ./k8s/redeploy.sh (or add --deploy)."; fi
fi
exit $rc

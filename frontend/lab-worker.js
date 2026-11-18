/* The Study Lab's runtime: Python (Pyodide, CPython compiled to WebAssembly) in a worker, so nothing a learner runs
   reaches the server and a runaway loop never freezes the page (Ctrl+C ends the worker; the page starts a new one).
   - The page sends {id, op, args} and gets {id, done, result | error}; output streams as {id, stream, text} (out, err,
     info) and figures as {id, stream: "img", text: base64 PNG}. Requests run one at a time.
   - This file has its own CSP (main.py): it loads Pyodide from one pinned path and pip packages from PyPI, and can reach
     nothing else, not even AXoR's API, so code typed in the lab can't act as the signed-in user.
   - ~ is /home/u<id>, kept in IndexedDB (per user and browser) and saved after every request.
   - The shell, the runners, the checks and SQL are Python: lab_shell.py, which the page sends with the first request. */
let py = null, lab = null, cur = 0, queue = Promise.resolve();
const post = m => postMessage(m);
const emit = (stream, text) => post({ id: cur, stream, text });
const sync = (load = false) => new Promise((ok, no) => py.FS.syncfs(load, e => e ? no(e) : ok()));

async function init({ index, shell, home, user }) {
  emit("info", "Loading Python…\n");
  importScripts(index + "pyodide.js");
  // Python's own output goes through lab_shell.py; what reaches these is the package loader's notes ("Loading numpy")
  const note = t => { if (!/already loaded from/.test(t)) emit("info", t + "\n"); };
  py = await loadPyodide({ indexURL: index, stdout: note, stderr: note });
  py.FS.mkdirTree(home);
  py.FS.mount(py.FS.filesystems.IDBFS, {}, home);
  await sync(true);
  await py.loadPackage("sqlite3");  // unvendored from Pyodide's standard library; the shell and SQL playground need it
  py.FS.mkdirTree("/lab");
  py.FS.writeFile("/lab/lab_shell.py", shell);
  py.runPython("import sys; sys.path.insert(0, '/lab')");
  lab = py.pyimport("lab_shell");
  return { ...JSON.parse(lab.start(emit, home, user)), python: py.runPython("import sys; sys.version.split()[0]"), pyodide: py.version,
           sqlite: py.runPython("import sqlite3; sqlite3.sqlite_version") };
}

async function handle(m) {
  cur = m.id;
  try {
    if (m.op === "init") return post({ id: m.id, done: true, result: await init(m) });
    if (!lab) throw new Error("Python isn't loaded yet.");
    const r = JSON.parse(await lab.call(m.op, JSON.stringify(m.args || {})));
    await sync();
    post({ id: m.id, done: true, result: r, error: r && typeof r === "object" && !Array.isArray(r) ? r.error : undefined });
  } catch (e) {
    post({ id: m.id, done: true, error: String(e?.message || e) });
  }
}
onmessage = ({ data }) => { queue = queue.then(() => handle(data)); };

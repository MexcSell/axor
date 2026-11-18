"""What every Lab project repo shares: the wheel builder, pyproject.toml, .gitignore, the changelog and the release ticket.

A file that tickets change is written once, as a template with «markers» on lines of their own, and block(ticket, stub,
solution) for each marker: the repo at any point is the template with the solved tickets' solutions and the others'
stubs (render), so a ticket's reference solution can't drift from the code it starts from.
"""
import re

VERSION, DEV = "0.1.0", "0.1.0.dev0"


def tabs(text):
    """Makefile recipes: lines indented with four spaces get the tab make wants."""
    return re.sub(r"^    ", "\t", text, flags=re.M)


def block(ticket, stub, solution):
    return ticket, stub.strip("\n") + "\n", solution.strip("\n") + "\n"


def render(file, done):
    """A file's text with the tickets in `done` solved: a plain string, or (template, {marker: block(…)})."""
    if isinstance(file, str): return file
    template, blocks = file
    def fill(m):
        ticket, stub, solution = blocks[m.group(1)]
        return solution if ticket in done else stub
    text = re.sub(r"^«([\w-]+)»\n", fill, template, flags=re.M)
    assert "«" not in text, f"an unfilled marker in {text[:60]!r}"
    return text


def pyproject(name, description):
    return f'''[project]
name = "{name}"
version = "{DEV}"
description = "{description}"
readme = "README.md"
requires-python = ">=3.11"
dependencies = []

[project.scripts]
{name} = "{name}.cli:main"

[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
packages = ["{name}"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
'''


def gitignore(*extra):
    return "\n".join(["__pycache__/", ".pytest_cache/", "dist/", "*.whl", *extra]) + "\n"


def changelog(name, first):
    return f"""# Changelog

Notable changes to {name}, newest first: each release lists what it ships, one line per change.

## Unreleased

- {first}
"""


def makefile(name, extra, clean):
    """The targets every project has (help, test, build, install, clean) around the project's own (extra); clean
    removes dist and the paths in `clean`."""
    return tabs(f"""# {name}'s dev loop: `make` lists the targets. Run them from the repo's root.
.PHONY: help test {" ".join(re.findall(r"^([a-z-]+):", extra, re.M))} build install clean

help:  ## list the targets (the default)
    @grep '^[a-z-]*:.*## ' Makefile

test:  ## run the whole test suite
    pytest -q

{extra.strip()}

build:  ## build dist/{name}-<version>-py3-none-any.whl
    python scripts/build_wheel.py

install: build  ## install the wheel into this Python
    pip install dist/*.whl

clean:  ## remove what builds and runs leave behind
    rm -rf dist {clean}
""")


BUILD_WHEEL = r'''"""Builds dist/<name>-<version>-py3-none-any.whl from pyproject.toml: a small stand-in for `python -m build`.

The lab's Python can't start subprocesses, so this does by hand what a build backend does for a pure-Python package:
check that pyproject.toml and the package agree on the version, compile every module (a syntax error fails the build),
then zip the package with the metadata pip reads (METADATA, WHEEL, entry points and RECORD).
On your own machine `python -m build` builds the same project with setuptools.
"""
import base64
import hashlib
import pathlib
import re
import sys
import tomllib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent


def digest(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def main() -> int:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    name, version = project["name"], project["version"]
    pkg = ROOT / name.replace("-", "_")
    found = re.search(r"^__version__\s*=\s*[\"']([^\"']+)[\"']", (pkg / "__init__.py").read_text(encoding="utf-8"), re.M)
    if not found or found.group(1) != version:
        said = found.group(1) if found else "no __version__"
        print(f"build failed: pyproject.toml says {version}, {pkg.name}/__init__.py says {said}", file=sys.stderr)
        return 1
    files = {}
    for path in sorted(pkg.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        source = path.read_bytes()
        try:
            compile(source, str(path.relative_to(ROOT)), "exec")
        except SyntaxError as e:
            print(f"build failed: {e.filename}:{e.lineno}: {e.msg}", file=sys.stderr)
            return 1
        files[path.relative_to(ROOT).as_posix()] = source
    info = f"{pkg.name}-{version}.dist-info"
    metadata = ["Metadata-Version: 2.1", f"Name: {name}", f"Version: {version}",
                f"Summary: {project.get('description', '')}", f"Requires-Python: {project.get('requires-python', '>=3')}"]
    files[f"{info}/METADATA"] = ("\n".join(metadata) + "\n").encode()
    files[f"{info}/WHEEL"] = b"Wheel-Version: 1.0\nGenerator: build_wheel.py\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    if project.get("scripts"):
        entry = "".join(f"{k} = {v}\n" for k, v in project["scripts"].items())
        files[f"{info}/entry_points.txt"] = f"[console_scripts]\n{entry}".encode()
    record = [f"{p},sha256={digest(b)},{len(b)}" for p, b in files.items()] + [f"{info}/RECORD,,"]
    files[f"{info}/RECORD"] = ("\n".join(record) + "\n").encode()
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    for old in dist.glob(f"{pkg.name}-*.whl"):  # dist/ holds the latest build only
        old.unlink()
    wheel = dist / f"{pkg.name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as z:
        for path, data in files.items():
            z.writestr(path, data)
    modules = sum(p.endswith(".py") for p in files)
    print(f"Successfully built {wheel.relative_to(ROOT)} ({modules} modules, {wheel.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

RELEASE_TESTS = r'''"""__ID__: the 0.1.0 release: versions bumped, the changelog written, and the wheel built from the code as it is."""
import importlib
import pathlib
import re
import sys
import tomllib
import zipfile

PKG = "__PKG__"
VERSION = "0.1.0"
WHEEL = pathlib.Path("dist", f"{PKG}-{VERSION}-py3-none-any.whl")


def test_version_bumped():
    """pyproject.toml and the package both say 0.1.0"""
    project = tomllib.loads(pathlib.Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == VERSION, f"pyproject.toml says version {project['version']!r}, not {VERSION!r}"
    init = pathlib.Path(PKG, "__init__.py").read_text(encoding="utf-8")
    found = re.search(r"^__version__\s*=\s*[\"']([^\"']+)[\"']", init, re.M)
    assert found and found.group(1) == VERSION, f"{PKG}/__init__.py says __version__ = {found and found.group(1)!r}, not {VERSION!r}"


def test_changelog():
    """CHANGELOG.md has a 0.1.0 section with a line per change"""
    text = pathlib.Path("CHANGELOG.md").read_text(encoding="utf-8")
    section = re.search(r"^## \[?0\.1\.0\]?[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert section, "CHANGELOG.md has no '## 0.1.0' heading: rename '## Unreleased'"
    bullets = [line for line in section.group(1).splitlines() if line.lstrip().startswith(("- ", "* "))]
    assert len(bullets) >= __BULLETS__, f"the 0.1.0 section lists {len(bullets)} change(s): add a bullet per ticket (at least __BULLETS__)"


def test_wheel_built():
    """make build left dist/__PKG__-0.1.0-py3-none-any.whl, with the right name and version inside"""
    assert WHEEL.exists(), f"there's no {WHEEL}: bump the versions, then run make build"
    with zipfile.ZipFile(WHEEL) as z:
        metadata = z.read(f"{PKG}-{VERSION}.dist-info/METADATA").decode()
    assert f"Name: {PKG}\n" in metadata and f"Version: {VERSION}\n" in metadata, "the wheel's METADATA doesn't say __PKG__ 0.1.0"


def test_wheel_is_current():
    """Every module in the wheel is the code in the repo now (no stale build)"""
    assert WHEEL.exists(), "build the wheel first: make build"
    with zipfile.ZipFile(WHEEL) as z:
        built = {name: z.read(name) for name in z.namelist() if name.endswith(".py")}
    here = {p.as_posix(): p.read_bytes() for p in pathlib.Path(PKG).rglob("*.py") if "__pycache__" not in p.parts}
    missing = sorted(set(here) - set(built))
    stale = sorted(p for p in here if p in built and built[p] != here[p])
    assert not missing, f"not in the wheel: {', '.join(missing)}. Run make build again"
    assert not stale, f"changed since the build: {', '.join(stale)}. Run make build again"


def test_wheel_imports():
    """The wheel imports on its own and reports version 0.1.0"""
    assert WHEEL.exists(), "build the wheel first: make build"
    path = str(WHEEL.resolve())
    saved = {name: sys.modules.pop(name) for name in list(sys.modules) if name == PKG or name.startswith(PKG + ".")}
    sys.path.insert(0, path)
    try:
        module = importlib.import_module(PKG)
        assert path in (module.__file__ or ""), "the package didn't import from the wheel"
        assert module.__version__ == VERSION, f"the wheel's {PKG}.__version__ is {module.__version__!r}"
    finally:
        sys.path.remove(path)
        for name in [n for n in sys.modules if n == PKG or n.startswith(PKG + ".")]:
            del sys.modules[name]
        sys.modules.update(saved)
'''

RELEASE_BODY = """**Labels** `release` · **Needs** every ticket above

Time to ship **__NAME__ 0.1.0**. Cut the release the way the team always does:

1. **Bump the version** from `0.1.0.dev0` to `0.1.0` in `pyproject.toml` *and* in `__PKG__/__init__.py`. `make build` refuses to build while they disagree.
2. **Write the changelog.** In `CHANGELOG.md`, rename `## Unreleased` to `## 0.1.0` and list what this release ships: one bullet per ticket, at least __BULLETS__.
3. **Build** in the terminal, from the repo's root: `make build` writes `dist/__PKG__-0.1.0-py3-none-any.whl`.
4. **Try the artifact** (optional): `make install` installs the wheel into the lab's Python. Then `cd ~ && python -c "import __PKG__; print(__PKG__.__version__, __PKG__.__file__)"` imports the installed copy, not the repo's.

CI checks the versions, the changelog, and that the wheel holds every module **as it is now**: change code after building and you'll need to build again.
"""


def release(project, final, number):
    """The last ticket of every project: cut 0.1.0 (version bump, changelog, wheel), its checks and its solution."""
    pkg, tickets = project["package"], project["tickets"]
    rid = f"{tickets[0]['id'].split('-')[0]}-{number}"
    fill = lambda text: (text.replace("__ID__", rid).replace("__PKG__", pkg).replace("__NAME__", project["name"])
                         .replace("__BULLETS__", str(len(tickets))))
    init = f"{pkg}/__init__.py"
    notes = "".join(f"- {t['title']} ({t['id']})\n" for t in tickets)
    solution = {"pyproject.toml": final["pyproject.toml"].replace(f'version = "{DEV}"', f'version = "{VERSION}"'),
                init: final[init].replace(f'__version__ = "{DEV}"', f'__version__ = "{VERSION}"'),
                "CHANGELOG.md": final["CHANGELOG.md"].replace("## Unreleased\n\n", f"## {VERSION}\n\n{notes}", 1)}
    assert all(solution[p] != final[p] for p in solution), f"{pkg}: the release didn't change every file it should"
    return {"id": rid, "kind": "release", "title": f"Cut the {project['name']} 0.1.0 release", "estimate": 15, "topic": "found.python",
            "touch": ["pyproject.toml", init, "CHANGELOG.md"], "test_path": "tests/test_release.py", "tests": fill(RELEASE_TESTS),
            "body": fill(RELEASE_BODY), "solution": solution, "commands": ["make build"],
            "hints": ["Two files hold the version: search for `0.1.0.dev0` with `grep -rn dev0 .`",
                      "`make build` prints `Successfully built dist/…`; if it says the versions disagree, one file still says dev0.",
                      "Changed code after building? `make build` again: CI compares the wheel with the repo."]}

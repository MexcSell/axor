"""Developer page (administrators): file explorer + editor, terminals on the server and a Claude Code / Codex panel.

Ported from Agent Company's Developer page (/home/luca/Agent_Company/docs/developer.md, rebuild spec
docs/requirements/WORKSPACE.md there, WS-R-nn). Names differ from the source, since AXoR already has a Workspace page:
view id `developer`, front end frontend/dvp-*.js + dvp.css, API /api/dev/*, modules dev_files / dev_terminal / dev_claude.

It is the administrator's own tool, not an agent (WS-R-01): shells run as the server's user with no command filter and
Claude Code runs with every tool allowed in the opened folder. So:
- every route needs an admin session; everything that changes something (files, opened folders, uploads, terminals,
  stopping other processes' Claude sessions, deleting history) also needs sudo: a fresh password or authenticator code,
  AXoR's rule for consoles and admin changes, as on Machines. Stopping this page's own runs and closing its own terminals
  don't (stopping something never needs a password), and neither does the Claude panel's composer (its prompts and
  pasted/attached files): the owner asked on 2026-11-11 that typing there never brings up the password box;
- WebSockets check the session cookie and that the page is same-origin (browsers apply no CORS to WebSockets);
- everything that changes something is in the audit log (Audit log, action `dev.*`).
Shells and Claude runs live in this process's memory: AXoR runs one web replica with one worker.
"""
import asyncio, json, os, re, uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.websockets import WebSocketDisconnect

from . import dev_claude, dev_files, dev_terminal

MAX_UPLOAD = 50 * 1024 * 1024  # explorer uploads
MAX_ATTACH = 10 * 1024 * 1024  # Claude panel attachments
ATTACH_TYPES = ("image/", "text/", "application/json", "application/pdf", "application/x-yaml")
_UPLOAD_ID = re.compile(r"^[0-9a-f]{32}$")


class PathBody(BaseModel):
    path: str = Field(min_length=1, max_length=4096)

class PathsBody(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=1000)

class WriteBody(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    text: str = Field(max_length=dev_files.MAX_TEXT * 2)

class CreateBody(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    folder: bool = False

class MoveBody(BaseModel):
    src: str = Field(min_length=1, max_length=4096)
    dest: str = Field(min_length=1, max_length=4096)
    keep_source: bool = False  # copy instead of moving

class CompressBody(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=1000)
    name: str = Field(default="", max_length=255)

class TerminalBody(BaseModel):
    cwd: str = Field(default="", max_length=4096)
    cols: int = Field(default=120, ge=2, le=1000)
    rows: int = Field(default=32, ge=2, le=500)

class ClaudeBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=100_000)
    cwd: str = Field(default="", max_length=4096)
    session_id: str = Field(default="", max_length=64)
    model: str = Field(default="", max_length=80)
    effort: str = Field(default="", max_length=16)
    title: str = Field(default="", max_length=200)
    attachments: list[str] = Field(default_factory=list, max_length=10)
    provider: str = Field(default="claude", pattern=r"^(claude|codex|copilot)$")
    router_model: str = Field(default="", max_length=80)


def _uploads_dir() -> Path:
    d = dev_files.data_dir() / "developer" / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _upload(uid: str) -> dict:
    if not _UPLOAD_ID.fullmatch(uid or ""):
        raise HTTPException(404, "No such attachment.")
    hit = next(iter(_uploads_dir().glob(f"{uid}-*")), None)
    if hit is None:
        raise HTTPException(404, "No such attachment.")
    return {"id": uid, "name": hit.name[len(uid) + 1:], "path": str(hit)}


async def _body(req: Request, limit: int, what: str) -> bytes:
    """The request body (the file's raw bytes: AXoR takes no multipart forms), refused past `limit`."""
    data = bytearray()
    async for chunk in req.stream():
        data += chunk
        if len(data) > limit:
            raise HTTPException(413, what)
    return bytes(data)


def build(db, helpers, ip):
    r = APIRouter(prefix="/api/dev")
    admin, sudo = helpers["admin"], helpers["sudo"]

    def audit(u, action, target="", req=None, detail=None):
        db.log("dev." + action, u["username"], str(target)[:256], ip(req) if req is not None else "",
               json.dumps(detail, default=str)[:1000] if detail else "")

    def call(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except HTTPException:
            raise
        except KeyError as e:
            raise HTTPException(404, str(e).strip("'\""))
        except PermissionError as e:
            raise HTTPException(403, str(e) or "Permission denied.")
        except (ValueError, OSError) as e:  # FileError is a ValueError
            raise HTTPException(400, str(e))
        except RuntimeError as e:  # an agent CLI missing
            raise HTTPException(503, str(e))

    # --- file manager ---
    @r.get("/files/roots")
    def roots(req: Request):
        admin(req)
        return dev_files.roots()

    @r.post("/files/roots")
    def root_add(b: PathBody, req: Request):
        u = sudo(req)
        out = call(dev_files.add_root, b.path)
        audit(u, "folder_open", out["path"], req)
        return out

    @r.delete("/files/roots")
    def root_remove(path: str, req: Request):
        u = sudo(req)
        call(dev_files.remove_root, path)
        audit(u, "folder_close", path, req)
        return {"ok": True}

    @r.get("/files/list")
    def listing(path: str, req: Request):
        admin(req)
        return call(dev_files.listing, path)

    @r.get("/files/git-status")
    def git_status(path: str, req: Request):
        admin(req)
        return call(dev_files.git_status, path)

    @r.get("/files/read")
    def read(path: str, req: Request):
        admin(req)
        return call(dev_files.read, path)

    @r.get("/files/raw")
    def raw(path: str, req: Request, download: bool = False):
        u = admin(req)
        p = call(dev_files.resolve, path)
        if p.is_dir():
            raise HTTPException(400, "That is a folder; download it as a zip.")
        if download:
            audit(u, "file_download", p, req)
        return FileResponse(p, filename=p.name if download else None,
                            content_disposition_type="attachment" if download else "inline",
                            headers={"Cache-Control": "no-store",
                                     "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"})

    @r.get("/files/archive")
    def archive(req: Request, paths: list[str] = Query(...)):
        u = admin(req)
        tmp, name = call(dev_files.download_archive, paths)
        audit(u, "file_download", ", ".join(paths), req, {"zip": name})
        return FileResponse(tmp, filename=name, media_type="application/zip",
                            background=BackgroundTask(tmp.unlink, missing_ok=True))

    @r.post("/files/compress")
    def compress(b: CompressBody, req: Request):
        u = sudo(req)
        out = call(dev_files.compress, b.paths, b.name)
        audit(u, "file_compress", out["path"], req, {"from": b.paths[:20]})
        return out

    @r.post("/files/extract")
    def extract(b: PathBody, req: Request):
        u = sudo(req)
        out = call(dev_files.extract, b.path)
        audit(u, "file_extract", b.path, req, out)
        return out

    @r.put("/files/write")
    def write(b: WriteBody, req: Request):
        u = sudo(req)
        out = call(dev_files.write, b.path, b.text)
        audit(u, "file_write", out["path"], req, {"size": out["size"]})
        return out

    @r.post("/files/create")
    def create(b: CreateBody, req: Request):
        u = sudo(req)
        out = call(dev_files.create, b.path, b.folder)
        audit(u, "file_create", out["path"], req)
        return out

    @r.post("/files/move")
    def move(b: MoveBody, req: Request):
        u = sudo(req)
        out = call(dev_files.move, b.src, b.dest, b.keep_source)
        audit(u, "file_copy" if b.keep_source else "file_move", b.src, req, {"to": out["path"]})
        return out

    @r.post("/files/delete")
    def delete(b: PathsBody, req: Request):
        u = sudo(req)
        done = call(dev_files.delete, b.paths)
        audit(u, "file_delete", ", ".join(done), req)
        return {"deleted": done}

    @r.post("/files/upload")
    async def upload(folder: str, name: str, req: Request):
        """The file's bytes as the body; `name` its file name."""
        u = sudo(req)
        data = await _body(req, MAX_UPLOAD, "Files may be at most 50 MB.")
        out = await run_in_threadpool(call, dev_files.upload, folder, name or "file", data)
        await run_in_threadpool(audit, u, "file_upload", out["path"], req, {"size": out["size"]})
        return out

    @r.get("/files/folders")
    def folders(req: Request, path: str = ""):
        admin(req)
        return call(dev_files.folders, path)

    # --- terminals: the administrator's own shells on the server (not an agent) ---
    @r.get("/terminal/sessions")
    def terminals(req: Request):
        admin(req)
        return dev_terminal.list_sessions()

    @r.post("/terminal/sessions")
    async def terminal_open(b: TerminalBody, req: Request):
        u = sudo(req)
        try:
            s = dev_terminal.create(b.cwd, u["username"], b.cols, b.rows)  # on the event loop: it registers a reader
        except (ValueError, OSError) as e:
            raise HTTPException(400, str(e))
        await run_in_threadpool(audit, u, "terminal_open", s.cwd, req, {"id": s.id})
        return s.to_dict()

    @r.delete("/terminal/sessions/{sid}")
    async def terminal_close(sid: str, req: Request):
        u = admin(req)
        if sid not in dev_terminal.SESSIONS:
            raise HTTPException(404, "No such terminal.")
        dev_terminal.close(sid)
        await run_in_threadpool(audit, u, "terminal_close", sid, req)
        return {"ok": True}

    @r.websocket("/terminal/sessions/{sid}/ws")
    async def terminal_ws(ws: WebSocket, sid: str):
        """WS-R-38. Close codes: 4403 not an admin or not same-origin, 4404 no such shell (the page opens a new one)."""
        await ws.accept()  # before refusing, so the browser sees the close code (refused earlier it sees only 1006)
        origin, host = ws.headers.get("origin", ""), ws.headers.get("x-forwarded-host") or ws.headers.get("host", "")
        try:
            ok = bool(origin) and origin.split("://", 1)[-1] == host and bool(admin(ws))
        except HTTPException:
            ok = False
        if not ok:
            return await ws.close(code=4403)
        sess = dev_terminal.SESSIONS.get(sid)
        if sess is None:
            return await ws.close(code=4404)
        q = sess.attach()
        # The replay, taken in the same step as attaching so no output is in both. A browser that reconnects says how
        # much it has (`after`) and gets only the rest while the buffer still reaches back that far.
        start = sess.total - len(sess.buffer)
        try:
            after = int(ws.query_params.get("after", ""))
        except ValueError:
            after = -1
        begin = after if start <= after <= sess.total else start
        replay = bytes(sess.buffer[begin - start:])

        async def outgoing():
            await ws.send_text(json.dumps({"t": "at", "from": begin}))
            if replay:
                await ws.send_bytes(replay)
            if not sess.alive:
                return await ws.send_text(json.dumps({"t": "exit", "code": sess.exit_code}))
            while True:
                data = await q.get()
                if data is None:
                    return await ws.send_text(json.dumps({"t": "exit", "code": sess.exit_code}))
                while not q.empty():  # coalesce bursts into one frame
                    more = q.get_nowait()
                    if more is None:
                        q.put_nowait(None)
                        break
                    data += more
                await ws.send_bytes(data)

        async def incoming():
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    return
                if msg.get("bytes"):
                    sess.write(msg["bytes"])
                elif msg.get("text"):
                    try:
                        m = json.loads(msg["text"])
                    except ValueError:
                        continue
                    if m.get("t") == "in":
                        sess.write(str(m.get("data", "")).encode())
                    elif m.get("t") == "resize":
                        try:
                            sess.resize(int(m.get("cols") or 80), int(m.get("rows") or 24))
                        except (TypeError, ValueError):
                            pass

        async def still_admin():  # signing out (or losing admin) ends the connection too
            while True:
                await asyncio.sleep(30)
                try:
                    await run_in_threadpool(admin, ws)
                except HTTPException:
                    return

        tasks = [asyncio.create_task(f()) for f in (outgoing, incoming, still_admin)]
        try:
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
        finally:
            sess.detach(q)
            for t in tasks:
                if t.done() and not t.cancelled():
                    t.exception()  # retrieved, so asyncio does not log it
            try:
                await ws.close()
            except (RuntimeError, WebSocketDisconnect):
                pass

    # --- Claude Code panel ---
    @r.get("/claude")
    def claude_info(req: Request):
        admin(req)
        dev_claude.warm_usage()
        return dev_claude.available()

    @r.get("/claude-usage")
    def claude_usage(req: Request, model: str = ""):
        admin(req)
        home = call(dev_claude.model_home, model)
        return dev_claude.claude_usage(home) | {"plan": dev_claude.claude_limits(home), "account": dev_claude._account(home),
                                                "home": "own" if home else "host"}

    @r.get("/claude-activity")
    def claude_activity(req: Request, cwd: str = "", model: str = ""):
        admin(req)
        return dev_claude.host_activity(cwd, call(dev_claude.model_home, model))

    @r.post("/claude")
    def claude_start(b: ClaudeBody, req: Request):
        u = admin(req)  # no sudo: see the module docstring
        images = [_upload(a) for a in b.attachments]
        run = call(dev_claude.start, b.prompt, b.cwd, u["username"], b.session_id, b.model, images, b.title, b.provider,
                   "", b.effort, b.router_model)
        audit(u, "claude", run.cwd, req, {"run": run.id, "prompt": b.prompt[:200], "provider": b.provider,
                                          "model": run.model or "default", "resume": b.session_id or None})
        return run.to_dict()

    @r.get("/claude-sessions")
    def claude_sessions(req: Request):
        admin(req)
        return dev_claude.sessions()

    @r.get("/claude-sessions/{session_id}")
    def claude_session(session_id: str, req: Request, after: int = 0):
        admin(req)
        return call(dev_claude.session_status, session_id, max(0, after))

    @r.post("/claude-sessions/{session_id}/stop")
    def claude_session_stop(session_id: str, req: Request):
        u = sudo(req)
        out = call(dev_claude.stop_session, session_id)
        audit(u, "claude_session_stop", session_id, req, out)
        return out

    @r.get("/claude-history")
    def claude_history(req: Request, q: str = "", limit: int = 200):
        admin(req)
        return dev_claude.history(q[:200], max(1, min(limit, 1000)))

    @r.delete("/claude-history/{session_id}")
    def claude_history_delete(session_id: str, req: Request):
        u = sudo(req)
        out = call(dev_claude.delete_session, session_id)
        audit(u, "claude_session_delete", session_id, req, {"files": len(out["deleted"])})
        return out

    @r.get("/claude/{run_id}")
    def claude_events(run_id: str, req: Request, after: int = 0):
        admin(req)
        return call(dev_claude.get, run_id).to_dict(max(0, after))

    @r.post("/claude/{run_id}/stop")
    def claude_stop(run_id: str, req: Request):
        u = admin(req)
        run = call(dev_claude.stop, run_id)
        audit(u, "claude_stop", run.cwd, req, {"run": run_id})
        return {"status": run.status}

    # --- attachments for the Claude panel (admins: only this page uses them) ---
    @r.post("/uploads")
    async def attach(name: str, req: Request):
        """The file's bytes as the body, its type as Content-Type; `name` its file name."""
        admin(req)  # no sudo: see the module docstring
        ctype = (req.headers.get("content-type") or "").split(";")[0].strip().lower()
        if not ctype.startswith(ATTACH_TYPES):
            raise HTTPException(400, "Attach images, text, JSON, YAML or PDF files.")
        data = await _body(req, MAX_ATTACH, "Attachments may be at most 10 MB.")
        uid = uuid.uuid4().hex
        safe = re.sub(r"[^\w.\- ]", "_", Path(name or "file").name)[:120] or "file"
        (_uploads_dir() / f"{uid}-{safe}").write_bytes(data)
        return {"id": uid, "name": safe, "content_type": ctype, "size": len(data)}

    @r.get("/uploads/{uid}")
    def attachment(uid: str, req: Request):
        admin(req)
        a = _upload(uid)
        return FileResponse(a["path"], headers={"Content-Security-Policy": "default-src 'none'", "Cache-Control": "no-store"})

    return r

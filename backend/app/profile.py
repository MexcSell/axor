"""My profile: an AI engineer's profile, made into a resume, a full CV and a personal website.

- Each user keeps one profile (ProfileIn): basics (name, headline, photo, contact, availability, summary), links,
  skill groups, experience, projects, education, publications, certifications and languages, plus the look of the
  site and documents (theme, accent colour, resume template) and whether email and phone are public.
- Resume and CV (profile_pages.py) are pages laid out for A4; the browser's print dialog saves them as PDF. The resume
  keeps featured projects and leaves out publications, certifications and languages; the CV has everything.
- The website is a portfolio styled like a product site: a header with mega menus, a hero, projects, experience,
  skills, background and a contact band.
- Publishing: a published profile is public at /u/<slug>, with /u/<slug>/resume and /u/<slug>/cv, like a share link
  (no sign-in; disabled accounts' pages are gone). Public pages, the site zip and Netlify show email and phone only if
  the user allows it; previews and downloads in the app always include them.
- Netlify: with the user's personal access token (encrypted with SecretBox) the site deploys as a zip (index.html,
  resume/, cv/ and a _headers file with the pages' CSP). The first deploy creates the Netlify site, and a deploy
  recreates it if it was deleted there. The same zip downloads for Netlify Drop or any static host.
  NETLIFY_API_URL points the calls elsewhere (tests/fake_netlify_api.py).
- AI review: the agents' model rewrites the headline, summary and experience bullets, for a pasted job description if
  one is given, and lists missing keywords and tips. It's told not to invent facts; the page applies only what's picked.
"""
import json, os, re, sqlite3, time, urllib.error, urllib.request
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field, StringConstraints

from . import profile_pages as pages
from .llm import LLMError
from .secretbox import SecretBox, mask

NETLIFY = os.getenv("NETLIFY_API_URL", "https://api.netlify.com/api/v1").rstrip("/")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")
SITE_NAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
TOKEN = re.compile(r"^[A-Za-z0-9_\-]{20,200}$")
MAX_JOB = 8000  # characters of a pasted job description

def Text(n): return Annotated[str, StringConstraints(strip_whitespace=True, max_length=n)]

class Link(BaseModel):
    label: Text(40) = ""
    url: Text(300) = ""

class SkillGroup(BaseModel):
    name: Text(60) = ""
    items: list[Text(60)] = Field(default_factory=list, max_length=40)

class Job(BaseModel):
    title: Text(100) = ""
    company: Text(100) = ""
    location: Text(80) = ""
    start: Text(20) = ""  # YYYY-MM from the month picker, or free text
    end: Text(20) = ""    # empty: present
    bullets: list[Text(400)] = Field(default_factory=list, max_length=12)
    tech: list[Text(40)] = Field(default_factory=list, max_length=20)

class Project(BaseModel):
    name: Text(100) = ""
    url: Text(300) = ""
    repo: Text(300) = ""
    description: Text(600) = ""
    tech: list[Text(40)] = Field(default_factory=list, max_length=20)
    featured: bool = False

class School(BaseModel):
    school: Text(120) = ""
    degree: Text(120) = ""
    start: Text(20) = ""
    end: Text(20) = ""
    detail: Text(300) = ""

class Pub(BaseModel):
    title: Text(240) = ""
    venue: Text(120) = ""
    year: Text(10) = ""
    url: Text(300) = ""

class Cert(BaseModel):
    name: Text(160) = ""
    issuer: Text(120) = ""
    year: Text(10) = ""
    url: Text(300) = ""

class ProfileIn(BaseModel):
    name: Text(80) = ""
    headline: Text(140) = ""
    photo: Text(500) = ""
    location: Text(80) = ""
    email: Text(120) = ""
    phone: Text(40) = ""
    availability: Text(120) = ""
    summary: Text(1500) = ""
    links: list[Link] = Field(default_factory=list, max_length=10)
    skills: list[SkillGroup] = Field(default_factory=list, max_length=12)
    experience: list[Job] = Field(default_factory=list, max_length=20)
    projects: list[Project] = Field(default_factory=list, max_length=24)
    education: list[School] = Field(default_factory=list, max_length=10)
    publications: list[Pub] = Field(default_factory=list, max_length=40)
    certifications: list[Cert] = Field(default_factory=list, max_length=20)
    languages: list[Text(60)] = Field(default_factory=list, max_length=10)
    theme: Text(20) = "midnight"
    accent: Text(7) = ""
    template: Text(20) = "modern"
    public_contact: bool = False

class PublishIn(BaseModel):
    published: bool
    slug: str = Field("", max_length=40)

class TokenIn(BaseModel):
    token: str = Field(max_length=200)

class DeployIn(BaseModel):
    name: str = Field("", max_length=63)  # the Netlify subdomain for a new site; empty for a random one

class AiIn(BaseModel):
    job: str = Field("", max_length=MAX_JOB)
    model: str | None = None

AI_SYSTEM = (
    "You are a resume editor for AI and machine-learning engineers. You improve wording, never facts: keep every employer, "
    "title, date, number and technology as given, and never add achievements, metrics, tools or responsibilities that the "
    "profile doesn't state. Bullets start with a strong verb, say what was built and what it changed, and stay under 30 "
    "words; keep each role's bullets to the same number or fewer. The headline is under 12 words; the summary is 2 to 4 "
    "sentences in the first person without 'I' at the start of every sentence. Write in the profile's language. When a "
    "job description is given, match its wording and priorities where the profile supports them, and list the job's "
    "important keywords the profile doesn't show yet. Tips are short, specific next steps (e.g. a metric worth adding).")
AI_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["headline", "summary", "experience", "keywords", "tips"],
             "properties": {
                 "headline": {"type": "string"},
                 "summary": {"type": "string"},
                 "experience": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["index", "bullets"],
                                                           "properties": {"index": {"type": "integer"}, "bullets": {"type": "array", "items": {"type": "string"}}}}},
                 "keywords": {"type": "array", "items": {"type": "string"}},
                 "tips": {"type": "array", "items": {"type": "string"}}}}

class NetlifyError(Exception):
    def __init__(self, msg, status=502):
        super().__init__(msg); self.status = status

def netlify(token, method, path, body=None, zipped=None):
    """One Netlify API call: JSON in and out, or a zip upload."""
    data, ctype = (zipped, "application/zip") if zipped is not None else (json.dumps(body).encode() if body is not None else None, "application/json")
    req = urllib.request.Request(NETLIFY + path, data=data, method=method,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": ctype, "User-Agent": "AXoR"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try: detail = str(json.load(e).get("message") or "")
        except Exception: detail = ""
        raise NetlifyError(detail[:300], e.code)
    except (urllib.error.URLError, OSError, ValueError):
        raise NetlifyError("Couldn't reach Netlify from the server. Try again.", 0)

def _netlify_http(e: NetlifyError):
    if e.status in (401, 403):
        return HTTPException(400, "Netlify rejected the token. Create a new personal access token and connect again.")
    if not e.status: return HTTPException(502, str(e))
    return HTTPException(502, f"Netlify error ({e.status}){': ' + str(e) if str(e) else ''}. Try again.")

def _html(text, status=200, frame=False):
    """A profile page with its own CSP: the app frames its previews (same origin); public pages can't be framed."""
    return HTMLResponse(text, status_code=status, headers={
        "Content-Security-Policy": pages.CSP + ("; frame-ancestors 'self'" if frame else "; frame-ancestors 'none'"),
        "X-Frame-Options": "SAMEORIGIN" if frame else "DENY", "Cache-Control": "no-cache"})

def _gone():
    return _html("""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Profile not found</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;font:16px/1.5 system-ui,sans-serif;background:#0e1e25;color:#eef4f5}
main{text-align:center;padding:24px}h1{font-size:22px;margin:0 0 6px}p{margin:0;color:#9fb4bb}</style></head>
<body><main><h1>This profile isn't published.</h1><p>The link may be old, or its owner took the page down.</p></main></body></html>""", 404)

class Profiles:
    def __init__(self, db, data_dir, hub=None, ready=None):
        self.db, self.box, self.hub, self.ready = db, SecretBox(db, data_dir), hub, ready
        db.q("""CREATE TABLE IF NOT EXISTS profiles (user_id INTEGER PRIMARY KEY, data TEXT, updated REAL,
                slug TEXT UNIQUE, published REAL, netlify TEXT)""")

    def _row(self, me):
        return self.db.q("SELECT * FROM profiles WHERE user_id=?", (me["id"],), one=True) or {}

    def get(self, me):
        r = self._row(me)
        data = json.loads(r["data"]) if r.get("data") else {"email": me.get("email") or ""}
        return ProfileIn.model_validate(data).model_dump()

    def _ensure(self, me):
        self.db.q("INSERT OR IGNORE INTO profiles (user_id, data, updated) VALUES (?,?,?)",
                  (me["id"], json.dumps(self.get(me)), time.time()))

    def _suggest(self, me):
        base = re.sub(r"[^a-z0-9]+", "-", me["username"].lower()).strip("-")[:36] or "profile"
        if len(base) < 3: base += "-ai"
        slug, n = base, 2
        while self.db.q("SELECT 1 FROM profiles WHERE slug=? AND user_id<>?", (slug, me["id"]), one=True):
            slug, n = f"{base}-{n}", n + 1
        return slug

    def view(self, me):
        r = self._row(me)
        return {"profile": self.get(me), "updated": r.get("updated"), "slug": r.get("slug") or self._suggest(me),
                "published": bool(r.get("published")),
                "netlify": {"token": mask(self.box.get(f"netlify_token:{me['id']}")), "site": json.loads(r.get("netlify") or "null")},
                "themes": {k: {"label": t["label"], "bg": t["bg"], "text": t["text"], "accent": t["accent"]} for k, t in pages.THEMES.items()},
                "templates": pages.TEMPLATES, "ai": bool(self.hub)}

    def save(self, me, p: ProfileIn):
        d = p.model_dump()
        if d["theme"] not in pages.THEMES: d["theme"] = "midnight"
        if d["template"] not in pages.TEMPLATES: d["template"] = "modern"
        if d["accent"] and not pages.HEX.match(d["accent"]): d["accent"] = ""
        now = time.time()
        self.db.q("INSERT INTO profiles (user_id, data, updated) VALUES (?,?,?) "
                  "ON CONFLICT(user_id) DO UPDATE SET data=excluded.data, updated=excluded.updated", (me["id"], json.dumps(d), now))
        return {"updated": now}

    def publish(self, me, b: PublishIn, ip=""):
        self._ensure(me)
        if not b.published:
            self.db.q("UPDATE profiles SET published=NULL WHERE user_id=?", (me["id"],))  # the address stays reserved
            self.db.log("profile.unpublish", me["username"], self._row(me).get("slug") or "", ip)
            return self.view(me)
        slug = b.slug.strip().lower()
        if not SLUG.match(slug):
            raise HTTPException(400, "Use 3–40 characters: a–z, 0–9 and hyphens, starting and ending with a letter or digit.")
        if not self.get(me)["name"]: raise HTTPException(400, "Add your name before publishing.")
        try:
            self.db.q("UPDATE profiles SET slug=?, published=? WHERE user_id=?", (slug, time.time(), me["id"]))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "That address is taken. Try another.")
        self.db.log("profile.publish", me["username"], slug, ip)
        return self.view(me)

    def public(self, slug):
        """The published profile at `slug`, or None (unknown, unpublished, or the account is disabled)."""
        if not SLUG.match(slug or ""): return None
        r = self.db.q("SELECT p.data, p.published, u.disabled FROM profiles p JOIN users u ON u.id=p.user_id WHERE p.slug=?", (slug,), one=True)
        if not r or not r["published"] or r["disabled"]: return None
        return ProfileIn.model_validate(json.loads(r["data"] or "{}")).model_dump()

    # ---------- Netlify ----------
    def connect(self, me, token, ip=""):
        token = token.strip()
        if not TOKEN.match(token): raise HTTPException(400, "Paste a Netlify personal access token.")
        try: account = netlify(token, "GET", "/user")
        except NetlifyError as e: raise _netlify_http(e)
        self.box.set(f"netlify_token:{me['id']}", token)
        self.db.log("profile.netlify.connect", me["username"], account.get("email") or account.get("full_name") or "", ip)
        return self.view(me)

    def disconnect(self, me, ip=""):
        self.box.delete(f"netlify_token:{me['id']}")
        self.db.q("UPDATE profiles SET netlify=NULL WHERE user_id=?", (me["id"],))  # the site itself stays on Netlify
        self.db.log("profile.netlify.disconnect", me["username"], "", ip)
        return self.view(me)

    def deploy(self, me, b: DeployIn, ip=""):
        token = self.box.get(f"netlify_token:{me['id']}")
        if not token: raise HTTPException(400, "Connect Netlify first.")
        p = self.get(me)
        if not p["name"]: raise HTTPException(400, "Add your name before deploying.")
        name = b.name.strip().lower()
        if name and not SITE_NAME.match(name): raise HTTPException(400, "Site names use a–z, 0–9 and hyphens.")
        zipped = pages.site_zip(p)
        site = json.loads(self._row(me).get("netlify") or "null")

        def create():
            try: s = netlify(token, "POST", "/sites", {"name": name} if name else {})
            except NetlifyError as e:
                if e.status == 422: raise HTTPException(409, f"Netlify didn't accept that site name{': ' + str(e) if str(e) else ''}. Pick another, or leave it empty.")
                raise
            return {"id": s["id"], "name": s.get("name"), "url": s.get("ssl_url") or s.get("url"), "admin_url": s.get("admin_url")}
        try:
            if not site: site = create()
            try: d = netlify(token, "POST", f"/sites/{site['id']}/deploys", zipped=zipped)
            except NetlifyError as e:
                if e.status != 404: raise
                site = create()  # deleted on Netlify since the last deploy
                d = netlify(token, "POST", f"/sites/{site['id']}/deploys", zipped=zipped)
        except NetlifyError as e:
            raise _netlify_http(e)
        site.update(deployed=time.time(), deploy_id=d.get("id"), state=d.get("state"),
                    deploy_url=d.get("deploy_ssl_url") or d.get("deploy_url"))
        self._ensure(me)
        self.db.q("UPDATE profiles SET netlify=? WHERE user_id=?", (json.dumps(site), me["id"]))
        self.db.log("profile.netlify.deploy", me["username"], site.get("url") or "", ip)
        return self.view(me)

    # ---------- AI review ----------
    def ai(self, me, a: AiIn):
        if not self.hub: raise HTTPException(404, "AI review needs agents, which aren't available on this server.")
        self.hub.gate(me)
        p = self.get(me)
        if not (p["summary"] or p["headline"] or p["experience"]): raise HTTPException(400, "Add a headline, a summary or some experience first.")
        if self.ready: self.ready(a.model)
        prof = {"name": p["name"], "headline": p["headline"], "summary": p["summary"], "skills": p["skills"],
                "experience": [{"index": i, **{k: j[k] for k in ("title", "company", "start", "end", "bullets", "tech")}} for i, j in enumerate(p["experience"])],
                "projects": [{k: x[k] for k in ("name", "description", "tech")} for x in p["projects"]]}
        job = a.job.strip()
        prompt = ("Profile:\n" + json.dumps(prof, ensure_ascii=False)
                  + (f"\n\nJob description:\n{job}" if job else "\n\nNo job description: improve it for AI engineer roles in general."))
        used = [0]
        try:
            out = self.hub.llm.structured(a.model, AI_SYSTEM, prompt, AI_SCHEMA, "profile_review", on_usage=lambda n: used.__setitem__(0, used[0] + n))
        except LLMError as e:
            raise HTTPException(502, str(e))
        finally:
            self.hub.log_usage(me, "profile", used[0], None, self.hub.model_of(a.model))
        if not isinstance(out, dict): raise HTTPException(502, "The model's answer was incomplete. Try again or pick another model.")
        strs = lambda xs, n, size: [str(x).strip()[:size] for x in (xs if isinstance(xs, list) else []) if str(x).strip()][:n]
        exp = [{"index": x["index"], "bullets": strs(x.get("bullets"), 12, 400)} for x in out.get("experience") or []
               if isinstance(x, dict) and isinstance(x.get("index"), int) and 0 <= x["index"] < len(p["experience"])]
        self.db.log("profile.ai", me["username"], "", "", "tailored" if job else "general")
        return {"headline": str(out.get("headline") or "").strip()[:140], "summary": str(out.get("summary") or "").strip()[:1500],
                "experience": [x for x in exp if x["bullets"]], "keywords": strs(out.get("keywords"), 20, 60), "tips": strs(out.get("tips"), 8, 300)}

def build(db, require, ip, data_dir, hub=None, ready=None):
    r = APIRouter(prefix="/api/profile")
    public = APIRouter()
    prof = Profiles(db, data_dir, hub, ready)
    r.state = {"profiles": prof, "public": public}

    @r.get("")
    def view(req: Request):
        return prof.view(require(req))

    @r.put("")
    def save(p: ProfileIn, req: Request):
        return prof.save(require(req), p)

    @r.put("/publish")
    def publish(b: PublishIn, req: Request):
        return prof.publish(require(req), b, ip(req))

    @r.get("/preview/{doc}", include_in_schema=False)
    def preview(doc: str, req: Request, bar: int = 0):
        """The pages as the app frames them: the site as visitors see it, the resume and CV with contact details."""
        p = prof.get(require(req))
        base = "/api/profile/preview"
        if doc == "site": return _html(pages.site(p, {"home": f"{base}/site", "resume": f"{base}/resume?bar=1", "cv": f"{base}/cv?bar=1"}), frame=True)
        if doc in ("resume", "cv"): return _html(pages.resume(p, doc, bar=bool(bar), back=f"{base}/site" if bar else ""), frame=True)
        raise HTTPException(404, "No such page.")

    @r.get("/download/{doc}", include_in_schema=False)
    def download(doc: str, req: Request):
        if doc not in ("resume", "cv"): raise HTTPException(404, "No such document.")
        p = prof.get(require(req))
        stem = re.sub(r"[^a-z0-9]+", "-", (p["name"] or "profile").lower()).strip("-") or "profile"
        return Response(pages.resume(p, doc), media_type="text/html; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{stem}-{doc}.html"'})

    @r.get("/site.zip", include_in_schema=False)
    def site_zip(req: Request):
        p = prof.get(require(req))
        stem = re.sub(r"[^a-z0-9]+", "-", (p["name"] or "profile").lower()).strip("-") or "profile"
        return Response(pages.site_zip(p), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{stem}-site.zip"'})

    @r.put("/netlify/token")
    def netlify_connect(b: TokenIn, req: Request):
        return prof.connect(require(req), b.token, ip(req))

    @r.delete("/netlify/token")
    def netlify_disconnect(req: Request):
        return prof.disconnect(require(req), ip(req))

    @r.post("/netlify/deploy")
    def netlify_deploy(b: DeployIn, req: Request):
        return prof.deploy(require(req), b, ip(req))

    @r.post("/ai")
    def ai(a: AiIn, req: Request):
        return prof.ai(require(req), a)

    # ---------- public pages: /u/<slug> ----------
    @public.get("/u/{slug}", include_in_schema=False)
    def public_site(slug: str):
        p = prof.public(slug)
        if not p: return _gone()
        return _html(pages.site(p, {"home": f"/u/{slug}", "resume": f"/u/{slug}/resume", "cv": f"/u/{slug}/cv"}))

    @public.get("/u/{slug}/{doc}", include_in_schema=False)
    def public_doc(slug: str, doc: str):
        p = prof.public(slug)
        if not p or doc not in ("resume", "cv"): return _gone()
        return _html(pages.resume(p, doc, public=True, back=f"/u/{slug}"))

    return r

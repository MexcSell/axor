"""HTML for My profile (profile.py): the resume and the CV in two print templates, the portfolio website, and the
static site as a zip for Netlify or any other host.

Every page is self-contained (inline CSS, no web fonts, no scripts from elsewhere), so it looks the same at
/u/<slug>, on Netlify and as a downloaded file. The only script is the print button's (PRINT_JS), which CSP allows
by its hash. The website's header has mega menus in pure CSS: they open on hover and on keyboard focus, and fold
into one menu (a <details>) on phones.
"""
import base64, hashlib, html, io, re, zipfile
from datetime import date

e = html.escape
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
EMAIL = re.compile(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']+$")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
PRINT_JS = 'document.addEventListener("click",e=>{if(e.target.closest("[data-print]"))print()})'
PRINT_HASH = "'sha256-" + base64.b64encode(hashlib.sha256(PRINT_JS.encode()).digest()).decode() + "'"
# public pages and the Netlify site: inline styles, https images (the photo), and only the print button's script
CSP = f"default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; script-src {PRINT_HASH}; base-uri 'none'; form-action 'none'"

THEMES = {
    "midnight": {"label": "Midnight", "bg": "#0e1e25", "panel": "#13252d", "panel2": "#1b2f38", "line": "#29414b",
                 "text": "#eef4f5", "muted": "#9fb4bb", "accent": "#32e6e2", "shadow": "0 24px 60px rgb(0 0 0 / .45)"},
    "daylight": {"label": "Daylight", "bg": "#ffffff", "panel": "#f6f7f9", "panel2": "#eef1f4", "line": "#e1e5ea",
                 "text": "#0f1720", "muted": "#55626f", "accent": "#2563eb", "shadow": "0 24px 60px rgb(15 23 32 / .14)"},
    "aurora": {"label": "Aurora", "bg": "#100d22", "panel": "#18142e", "panel2": "#221c40", "line": "#312a57",
               "text": "#f2eeff", "muted": "#aca5cf", "accent": "#a78bfa", "shadow": "0 24px 60px rgb(0 0 0 / .5)"},
}
TEMPLATES = {"modern": {"label": "Modern", "hint": "Two columns, accent headings"},
             "classic": {"label": "Classic", "hint": "One column, plain: best for applicant tracking systems"}}

# ---------- colour ----------
def _rgb(h): return [int(h[i:i + 2], 16) for i in (1, 3, 5)]

def _lum(h):
    c = [x / 255 for x in _rgb(h)]
    c = [x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4 for x in c]
    return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]

def _contrast(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + .05) / (lo + .05)

def on_color(h):
    """Text colour for a button filled with `h`."""
    return "#0b1117" if _contrast(h, "#0b1117") >= _contrast(h, "#ffffff") else "#ffffff"

def readable(h, bg):
    """`h`, darkened (light background) or lightened (dark one) until it reads as text on `bg` (4.5:1)."""
    r, lighten = _rgb(h), _lum(bg) < .5
    c = h
    for _ in range(40):
        c = "#%02x%02x%02x" % tuple(r)
        if _contrast(c, bg) >= 4.5: break
        r = [min(255, round(x + (255 - x) * .12)) for x in r] if lighten else [round(x * .88) for x in r]
    return c

# ---------- text ----------
def when(s):
    m = re.fullmatch(r"(\d{4})-(\d{2})", s or "")
    return f"{MONTHS[int(m[2]) - 1]} {m[1]}" if m and 1 <= int(m[2]) <= 12 else (s or "")

def span(a, b):
    a, b = when(a), when(b)
    return f"{a} – {b or 'Present'}" if a else b

def href(url):
    """An http(s) or mailto link, or "" for anything else (javascript:, data:…). Bare domains get https://."""
    u = (url or "").strip()
    if u.lower().startswith("mailto:"): return u if EMAIL.match(u[7:]) else ""
    if re.match(r"^https?://[^\s<>\"']+$", u, re.I): return u
    if re.match(r"^[\w-]+(\.[\w-]+)+(/[^\s<>\"']*)?$", u): return "https://" + u
    return ""

def host(url):
    return re.sub(r"^(https?://)?(www\.)?", "", (url or "").strip(), flags=re.I).rstrip("/")

def initials(name):
    return "".join(w[0] for w in (name or "").split()[:2]).upper() or "•"

def years(p):
    """Whole years since the earliest dated role."""
    starts = [m for j in p["experience"] if (m := re.fullmatch(r"(\d{4})-(\d{2})", j["start"] or ""))]
    if not starts: return 0
    y, mo = min((int(m[1]), int(m[2])) for m in starts)
    t = date.today()
    return max(0, (t.year - y) - (t.month < mo))

def sentences(text, n):
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return " ".join(parts[:n])

def _photo(p):
    return p["photo"] if re.match(r"^https://[^\s<>\"']+$", p["photo"] or "") else ""

def _ul(items):
    return f"<ul>{''.join(f'<li>{e(b)}</li>' for b in items)}</ul>" if items else ""

def _link(url, text, cls=""):
    h = href(url)
    c = f' class="{cls}"' if cls else ""
    return f'<a{c} href="{e(h)}" target="_blank" rel="noopener noreferrer">{e(text)}</a>' if h else e(text)

def favicon(text, bg, fg):
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="{bg}"/>'
           f'<text x="32" y="42" font-family="system-ui,sans-serif" font-size="28" font-weight="800" text-anchor="middle" fill="{fg}">{e(text)}</text></svg>')
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()

def _filled(p):
    """The profile without blank entries (rows added in the editor and not filled in yet)."""
    keep = {"links": ("url",), "skills": ("items",), "experience": ("title", "company"), "projects": ("name",),
            "education": ("school", "degree"), "publications": ("title",), "certifications": ("name",)}
    return {**p, **{k: [x for x in p[k] if any(x[f] for f in fs)] for k, fs in keep.items()}}

def contacts(p, public):
    """(text, link) pairs for the resume's contact line: location, email and phone (unless hidden), then links."""
    show = not public or p["public_contact"]
    out = [(p["location"], "")] if p["location"] else []
    if show and EMAIL.match(p["email"] or ""): out.append((p["email"], "mailto:" + p["email"]))
    if show and p["phone"]: out.append((p["phone"], "tel:" + re.sub(r"[^+\d]", "", p["phone"])))
    out += [(host(l["url"]), href(l["url"])) for l in p["links"] if href(l["url"])]
    return out

# ---------- resume and CV ----------
RESUME_CSS = """
*{box-sizing:border-box}
html{background:#e8e8e4}
body{margin:0;color:#171a1f;font:10pt/1.45 -apple-system,"Segoe UI",Inter,Roboto,"Helvetica Neue",Arial,sans-serif;-webkit-print-color-adjust:exact;print-color-adjust:exact}
a{color:inherit;text-decoration:none}
.bar{position:sticky;top:0;z-index:2;display:flex;align-items:center;gap:12px;padding:10px 16px;background:#16181c;color:#f3f3f1;font:13px/1.3 system-ui,sans-serif}
.bar span{flex:1;text-align:center;opacity:.8}
.bar a,.bar button{padding:7px 12px;border-radius:8px;border:1px solid #3a3d44;background:none;color:inherit;font:inherit;font-weight:600;cursor:pointer}
.bar button{background:var(--a);border-color:var(--a);color:#fff}
.page{width:210mm;min-height:297mm;margin:24px auto;background:#fff;padding:15mm 16mm;box-shadow:0 2px 28px rgb(0 0 0/.13)}
h1{margin:0;font-size:23pt;line-height:1.1;letter-spacing:-.02em}
.role{margin:4px 0 0;font-size:11.5pt;font-weight:600;color:var(--a)}
h2{margin:15px 0 7px;font-size:9pt;letter-spacing:.13em;text-transform:uppercase;color:var(--a)}
p{margin:0}
.item{margin:0 0 9px;break-inside:avoid}
.ih{display:flex;justify-content:space-between;align-items:baseline;gap:12px}
.ih b{font-size:10.5pt}
.org{color:#454b55}
.when{flex:none;color:#646b76;font-size:9pt;font-variant-numeric:tabular-nums}
.meta{color:#646b76;font-size:9pt}
ul{margin:3px 0 0;padding-left:15px}
li{margin:1.5px 0}
.tech{margin-top:3px;color:#646b76;font-size:9pt}
@page{size:A4;margin:12mm 0}
@page:first{margin-top:0}
@media print{html{background:#fff}.bar{display:none}.page{margin:0 auto;padding-top:12mm;padding-bottom:0;min-height:0;box-shadow:none}}
@media (max-width:840px){html{background:#fff}.page{width:auto;min-height:0;margin:0;padding:24px 18px;box-shadow:none}.ih{flex-wrap:wrap}}
/* modern: header band, main column and a tinted sidebar */
.modern header{display:flex;justify-content:space-between;gap:20px;padding-bottom:12px;border-bottom:2.5px solid var(--a)}
.modern .cols{display:grid;grid-template-columns:1fr 58mm;gap:8mm;margin-top:4px}
.modern aside{padding:2px 0 0}
.modern aside h2:first-child,.modern .main h2:first-child{margin-top:12px}
.modern aside .c{display:grid;gap:3px;font-size:9pt;overflow-wrap:anywhere}
.modern aside .ih{display:block}
.modern aside .when{display:block}
.modern .grp{margin:0 0 7px}
.modern .grp b{display:block;font-size:9.5pt}
.modern .grp span{color:#454b55;font-size:9pt}
.modern h2{border-bottom:1px solid #e3e6ea;padding-bottom:3px}
@media (max-width:840px){.modern .cols{grid-template-columns:1fr}.modern header{flex-direction:column}}
/* classic: centred header, one column, plain rules */
.classic{font-family:Georgia,"Times New Roman",serif;font-size:10.5pt}
.classic header{text-align:center;padding-bottom:9px;border-bottom:1px solid #171a1f}
.classic h1{font-size:22pt;letter-spacing:.01em}
.classic .role{color:#30353d;font-weight:400;font-style:italic}
.classic .c{margin-top:6px;font-size:9.5pt;color:#30353d}
.classic .c span+span::before{content:" · "}
.classic h2{color:#171a1f;border-bottom:1px solid #b9bec5;padding-bottom:2px;letter-spacing:.1em}
.classic .grp{margin:0 0 2px}
"""

def resume(p, doc="resume", public=False, bar=True, back=""):
    """The resume (doc "resume") or the full CV ("cv") as a print-ready page. `public` hides the contact details the
    user didn't make public; `bar` adds the screen-only toolbar with the print button; `back` links the website."""
    p = _filled(p)
    tpl = p["template"] if p["template"] in TEMPLATES else "modern"
    theme = THEMES.get(p["theme"]) or THEMES["midnight"]
    accent = readable(p["accent"] if HEX.match(p["accent"] or "") else theme["accent"], "#ffffff")
    full = doc == "cv"
    title = "CV" if full else "Resume"
    projects = p["projects"] if full else ([x for x in p["projects"] if x["featured"]] or p["projects"])[:4]

    def job(j):
        org = " · ".join(x for x in (j["company"], j["location"]) if x)
        return (f'<div class="item"><div class="ih"><b>{e(j["title"])}{f"<span class=org>, {e(org)}</span>" if org else ""}</b>'
                f'<span class="when">{e(span(j["start"], j["end"]))}</span></div>{_ul(j["bullets"])}'
                f'{f"<div class=tech>{e(", ".join(j["tech"]))}</div>" if j["tech"] and full else ""}</div>')

    def project(x):
        url = x["url"] or x["repo"]
        return (f'<div class="item"><div class="ih"><b>{e(x["name"])}</b>{f"<span class=when>{e(host(url))}</span>" if href(url) else ""}</div>'
                f'{f"<p>{e(x["description"])}</p>" if x["description"] else ""}{f"<div class=tech>{e(", ".join(x["tech"]))}</div>" if x["tech"] else ""}</div>')

    def school(s):
        return (f'<div class="item"><div class="ih"><b>{e(s["degree"] or s["school"])}</b><span class="when">{e(span(s["start"], s["end"]))}</span></div>'
                f'{f"<div class=org>{e(s["school"])}</div>" if s["degree"] and s["school"] else ""}{f"<div class=meta>{e(s["detail"])}</div>" if s["detail"] else ""}</div>')

    def pub(x):
        return f'<div class="item"><b>{_link(x["url"], x["title"])}</b><div class="meta">{e(", ".join(v for v in (x["venue"], x["year"]) if v))}</div></div>'

    def cert(x):
        return f'<div class="item"><b>{_link(x["url"], x["name"])}</b><div class="meta">{e(", ".join(v for v in (x["issuer"], x["year"]) if v))}</div></div>'

    sec = lambda name, body: f"<h2>{name}</h2>{body}" if body else ""
    contact = contacts(p, public)
    groups = [g for g in p["skills"] if g["items"]]
    summary = sec("Profile" if tpl == "modern" else "Summary", f"<p>{e(p['summary'])}</p>" if p["summary"] else "")
    exp = sec("Experience", "".join(map(job, p["experience"])))
    proj = sec("Projects" if full else "Selected projects", "".join(map(project, projects)))
    edu = sec("Education", "".join(map(school, p["education"])))
    pubs = sec("Publications &amp; talks", "".join(map(pub, p["publications"]))) if full else ""
    certs = sec("Certifications", "".join(map(cert, p["certifications"]))) if full else ""
    langs = sec("Languages", f"<p>{e(', '.join(p['languages']))}</p>" if p["languages"] else "") if full else ""
    head = f'<h1>{e(p["name"] or "Your name")}</h1>{f"<p class=role>{e(p["headline"])}</p>" if p["headline"] else ""}'
    if tpl == "modern":
        skills = sec("Skills", "".join(f'<div class="grp"><b>{e(g["name"])}</b><span>{e(", ".join(g["items"]))}</span></div>' for g in groups))
        cl = "".join(f'<a href="{e(u)}">{e(t)}</a>' if u else f"<span>{e(t)}</span>" for t, u in contact)
        page = (f'<main class="page modern"><header><div>{head}</div></header><div class="cols">'
                f'<div class="main">{summary}{exp}{proj}{pubs}</div>'
                f'<aside>{sec("Contact", f"<div class=c>{cl}</div>" if cl else "")}{skills}{edu}{certs}{langs}</aside></div></main>')
    else:
        skills = sec("Skills", "".join(f'<p class="grp"><b>{e(g["name"])}:</b> {e(", ".join(g["items"]))}</p>' for g in groups))
        cl = "".join(f'<span><a href="{e(u)}">{e(t)}</a></span>' if u else f"<span>{e(t)}</span>" for t, u in contact)
        page = (f'<main class="page classic"><header>{head}{f"<p class=c>{cl}</p>" if cl else ""}</header>'
                f'{summary}{skills}{exp}{proj}{edu}{pubs}{certs}{langs}</main>')
    toolbar = (f'<div class="bar">{f"<a href={chr(34)}{e(back)}{chr(34)}>← Website</a>" if back else "<i></i>"}'
               f'<span>{e(p["name"])} · {title}</span><button type="button" data-print>Download PDF</button></div>'
               f"<script>{PRINT_JS}</script>") if bar else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{e(p["name"] or "Profile")} – {title}</title><meta name="description" content="{e(p["headline"])}">'
            f'<style>:root{{--a:{accent}}}{RESUME_CSS}</style></head><body>{toolbar}{page}</body></html>')

# ---------- the website ----------
SITE_CSS = """
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:84px}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.6 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit}
img{max-width:100%}
.wrap{max-width:1180px;margin:0 auto;padding:0 24px}
.eyebrow{margin:0 0 14px;font:500 12px/1.4 ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.ul{font-weight:600;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:4px}
.ul:hover{color:var(--acc-t)}
:focus-visible{outline:2px solid var(--acc);outline-offset:3px;border-radius:6px}
/* header and mega menus */
.nav{position:sticky;top:0;z-index:10;background:color-mix(in srgb,var(--bg) 86%,transparent);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
.nav-in{display:flex;align-items:center;gap:26px;height:68px}
.logo{display:flex;align-items:center;gap:10px;font-weight:800;font-size:18px;letter-spacing:-.015em;text-decoration:none;white-space:nowrap}
.mono{display:grid;place-items:center;width:34px;height:34px;border-radius:9px;background:var(--acc);color:var(--on);font-size:13px;font-weight:800;letter-spacing:0}
.menu{display:flex;align-items:center;gap:2px;flex:1}
.mm{position:relative}
.mm::after{content:"";position:absolute;left:0;right:0;top:100%;height:16px}
.mm-btn,.menu-link{display:inline-flex;align-items:center;gap:6px;padding:8px 12px;border:0;border-radius:8px;background:none;color:var(--text);font:inherit;font-size:15px;font-weight:600;text-decoration:none;cursor:pointer}
.mm-btn svg{width:13px;height:13px;transition:transform .2s}
.mm:hover .mm-btn,.mm:focus-within .mm-btn,.menu-link:hover{color:var(--acc-t)}
.mm:hover .mm-btn svg,.mm:focus-within .mm-btn svg{transform:rotate(180deg)}
.mm-panel{position:absolute;top:calc(100% + 12px);left:-12px;display:grid;grid-template-columns:290px auto;width:max-content;max-width:min(820px,calc(100vw - 48px));background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);overflow:hidden;opacity:0;visibility:hidden;transform:translateY(-6px);transition:opacity .16s,transform .16s,visibility .16s}
.mm:hover .mm-panel,.mm:focus-within .mm-panel{opacity:1;visibility:visible;transform:none}
.mm-l{padding:26px 28px;background:var(--panel2)}
.mm-r{padding:26px 30px;border-left:1px solid var(--line);min-width:300px}
.mm-lede{margin:0 0 22px;font-size:15px;line-height:1.6}
.mm-grid{display:grid;grid-template-columns:repeat(2,minmax(140px,auto));gap:14px 44px}
.mm-grid.one{grid-template-columns:minmax(220px,auto)}
.mm-grid a{font-size:15px}
.mm-item{display:grid;gap:1px;text-decoration:none}
.mm-item b{font-weight:600;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:4px}
.mm-item:hover b{color:var(--acc-t)}
.mm-item small{color:var(--muted);font-size:13px}
.nav-cta{display:flex;align-items:center;gap:10px}
.burger{display:none;position:relative;margin-left:auto}
.burger summary{display:grid;place-items:center;width:42px;height:42px;border:1px solid var(--line);border-radius:10px;cursor:pointer;list-style:none}
.burger summary::-webkit-details-marker{display:none}
.burger summary svg{width:20px;height:20px}
.burger-panel{position:absolute;right:0;top:calc(100% + 10px);width:min(320px,calc(100vw - 32px));max-height:calc(100vh - 100px);overflow:auto;display:grid;gap:2px;padding:12px;background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow)}
.burger-panel a{padding:9px 12px;border-radius:8px;font-weight:600;text-decoration:none}
.burger-panel a:hover{background:var(--panel2)}
.burger-panel .eyebrow{margin:12px 12px 4px}
/* buttons */
.btn{display:inline-flex;align-items:center;gap:8px;padding:12px 20px;border:1px solid var(--line);border-radius:10px;font-size:15px;font-weight:700;text-decoration:none;white-space:nowrap;transition:filter .15s,border-color .15s}
.btn.solid{background:var(--acc);border-color:var(--acc);color:var(--on)}
.btn.solid:hover{filter:brightness(1.08)}
.btn.ghost:hover{border-color:var(--text)}
.btn.sm{padding:9px 16px;font-size:14px}
.btn svg{width:16px;height:16px}
/* hero */
.hero{position:relative;overflow:hidden;border-bottom:1px solid var(--line)}
.hero::before{content:"";position:absolute;inset:0;background:radial-gradient(55% 65% at 85% 15%,color-mix(in srgb,var(--acc) 16%,transparent),transparent 70%);pointer-events:none}
.hero-in{position:relative;display:grid;grid-template-columns:1.15fr .85fr;gap:56px;align-items:center;padding-top:88px;padding-bottom:96px}
.kicker{display:inline-flex;align-items:center;gap:10px;margin:0 0 24px;padding:6px 14px;border:1px solid var(--line);border-radius:999px;color:var(--muted);font-size:14px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--acc);box-shadow:0 0 0 4px color-mix(in srgb,var(--acc) 24%,transparent)}
h1{margin:0 0 24px;font-size:clamp(40px,6.2vw,78px);line-height:1.02;letter-spacing:-.035em;font-weight:800}
h1.long{font-size:clamp(34px,4.3vw,58px);line-height:1.06}
.lede{max-width:38em;margin:0 0 34px;color:var(--muted);font-size:19px}
.ctas{display:flex;flex-wrap:wrap;gap:12px}
.art{color:var(--text)}
.art svg{display:block;width:100%;height:auto}
.photo{position:relative;margin:0;padding:18px;border:1.5px dashed var(--line);border-radius:28px}
.photo img{display:block;width:100%;aspect-ratio:1;object-fit:cover;border-radius:18px;border:1px solid var(--line)}
.photo::after{content:"";position:absolute;right:-12px;bottom:-12px;width:56px;height:56px;border-radius:14px;background:var(--acc);opacity:.9;z-index:-1}
/* strips and sections */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));border-bottom:1px solid var(--line)}
.stat{padding:32px 24px;border-right:1px solid var(--line)}
.stat:last-child{border-right:0}
.stat b{display:block;font-size:42px;line-height:1.1;letter-spacing:-.03em;color:var(--acc-t)}
.stat span{color:var(--muted)}
.logos{display:flex;flex-wrap:wrap;align-items:center;gap:16px 44px;padding-top:30px;padding-bottom:30px;border-bottom:1px solid var(--line)}
.logos .eyebrow{margin:0}
.logos span{color:var(--muted);font-size:19px;font-weight:800;letter-spacing:-.01em}
.s{padding:96px 0;border-bottom:1px solid var(--line)}
h2{margin:0 0 40px;font-size:clamp(30px,3.6vw,46px);line-height:1.1;letter-spacing:-.03em}
h3{margin:0;font-size:20px;letter-spacing:-.01em;line-height:1.3}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:18px}
.card{display:flex;flex-direction:column;gap:12px;padding:26px;background:var(--panel);border:1px solid var(--line);border-radius:16px;transition:border-color .2s,transform .2s}
.card:hover{border-color:color-mix(in srgb,var(--acc) 70%,var(--line));transform:translateY(-2px)}
.card p{margin:0;color:var(--muted)}
.badge{align-self:flex-start;padding:5px 8px;border-radius:6px;background:color-mix(in srgb,var(--acc) 16%,transparent);color:var(--acc-t);font:600 11px/1 ui-monospace,Menlo,monospace;letter-spacing:.08em;text-transform:uppercase}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chips span{padding:3px 10px;border:1px solid var(--line);border-radius:999px;color:var(--muted);font-size:13px}
.card-links{display:flex;gap:20px;margin-top:auto;padding-top:6px}
.timeline{margin:0;padding:0;list-style:none}
.timeline>li{display:grid;grid-template-columns:210px 1fr;gap:32px;padding:30px 0;border-top:1px solid var(--line)}
.tl-when{padding-top:3px;color:var(--muted);font:500 13px/1.6 ui-monospace,Menlo,monospace}
.timeline h3 span{color:var(--muted);font-weight:500}
.timeline .where{margin:2px 0 0;color:var(--muted);font-size:14px}
.timeline ul{margin:12px 0 14px;padding-left:18px}
.timeline li li{margin:5px 0}
.skill-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:18px}
.skill{padding:24px;background:var(--panel);border:1px solid var(--line);border-radius:16px}
.skill h3{margin-bottom:14px;font-size:17px}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px 48px}
.entry{padding:16px 0;border-top:1px solid var(--line)}
.entry b{display:block}
.entry span{color:var(--muted);font-size:14px}
.band{background:var(--panel2);border-bottom:1px solid var(--line)}
.band-in{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:28px;padding-top:84px;padding-bottom:84px}
.band h2{margin-bottom:12px}
.band p{margin:0;color:var(--muted);font-size:18px}
footer{padding:30px 0;color:var(--muted);font-size:14px}
footer .wrap{display:flex;flex-wrap:wrap;justify-content:space-between;gap:12px 24px}
footer nav{display:flex;flex-wrap:wrap;gap:8px 20px}
footer a{text-decoration:none}
footer a:hover{color:var(--text)}
@media (max-width:980px){.menu,.nav-cta .ghost{display:none}.burger{display:block}.nav-cta{margin-left:auto}.burger{margin-left:0}
  .hero-in{grid-template-columns:1fr;gap:40px;padding-top:56px;padding-bottom:64px}.art{max-width:460px}}
@media (max-width:640px){.wrap{padding:0 16px}.nav-in{gap:12px}.nav-cta{display:none}.burger{margin-left:auto}.s{padding:64px 0}.lede{font-size:17px}
  .timeline>li{grid-template-columns:1fr;gap:6px}.stat{border-right:0;border-bottom:1px solid var(--line)}.band-in{padding-top:56px;padding-bottom:56px}}
@media (prefers-reduced-motion:reduce){*{transition:none!important}html{scroll-behavior:auto}}
"""

CHEV = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>'
BURGER = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>'
ARROW = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>'
# hand-drawn style line art for the hero when there's no photo: a metrics chart, a locked box, a deploy arrow and a model graph
ART = """<svg viewBox="0 0 520 440" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
<g opacity=".35" stroke-width="1.6" stroke-dasharray="5 9"><path d="M8 52h504"/><path d="M8 300h504"/><path d="M58 8v424"/><path d="M372 8v424"/></g>
<rect x="88" y="82" width="250" height="186" rx="12"/><path d="M112 232l44-34 40 16 44-52 40 22 34-38"/>
<g fill="var(--bg)"><circle cx="112" cy="232" r="6"/><circle cx="156" cy="198" r="6"/><circle cx="196" cy="214" r="6"/><circle cx="240" cy="162" r="6"/><circle cx="280" cy="184" r="6"/><circle cx="314" cy="146" r="6"/></g>
<path d="M112 108h56M112 124h32" opacity=".6"/>
<rect x="402" y="74" width="74" height="74" rx="14"/><circle cx="439" cy="104" r="9"/><path d="M439 113v16"/><path d="M439 148v52h-70"/>
<path d="M214 420v-96M190 346l24-24 24 24"/>
<g stroke="var(--acc)"><circle cx="420" cy="336" r="10"/><circle cx="476" cy="292" r="10"/><circle cx="476" cy="384" r="10"/><circle cx="364" cy="384" r="10"/>
<path d="M429 330l38-31M429 342l38 36M411 343l-38 34M466 384h-92"/></g>
<rect x="88" y="330" width="62" height="62" rx="10"/><path d="M104 350h30M104 362h22M104 374h30" opacity=".7"/>
</svg>"""

def site(p, paths):
    """The portfolio website. `paths` has the "home", "resume" and "cv" URLs, which differ between AXoR (/u/<slug>/…),
    the static zip (/resume/…) and the in-app preview."""
    p = _filled(p)
    t = THEMES.get(p["theme"]) or THEMES["midnight"]
    acc = p["accent"] if HEX.match(p["accent"] or "") else t["accent"]
    name = p["name"] or "Your name"
    headline = p["headline"] or "AI engineer"
    email = p["email"] if p["public_contact"] and EMAIL.match(p["email"] or "") else ""
    links = [(l["label"] or host(l["url"]), href(l["url"])) for l in p["links"] if href(l["url"])]
    skills = [s for g in p["skills"] for s in g["items"]]
    jobs = p["experience"]
    projects = sorted(enumerate(p["projects"]), key=lambda x: not x[1]["featured"])
    featured = any(x["featured"] for x in p["projects"])
    first_name = name.split()[0]
    reach = f"mailto:{email}" if email else (links[0][1] if links else "#contact")

    def panel(left_eyebrow, left, right_eyebrow, right, one=False):
        r = f'<div class="mm-r"><p class="eyebrow">{right_eyebrow}</p><div class="mm-grid{" one" if one else ""}">{right}</div></div>' if right else ""
        return f'<div class="mm-panel"><div class="mm-l"><p class="eyebrow">{left_eyebrow}</p>{left}</div>{r}</div>'

    teaser = sentences(p["summary"], 1)
    menus = [("About", panel(
        "The portfolio", f'<p class="mm-lede"><b>{e(name)}, {e(headline)}.</b> {e(teaser)}</p><a class="ul" href="#about">Explore my work</a>',
        "Key skills", "".join(f'<a class="ul" href="#skills">{e(s)}</a>' for s in skills[:8])))]
    if jobs or projects:
        roles = "".join(f'<a class="mm-item" href="#exp-{i}"><b>{e(j["title"] or j["company"])}</b><small>{e(" · ".join(x for x in (j["company"], span(j["start"], j["end"])) if x))}</small></a>'
                        for i, j in enumerate(jobs[:4]))
        menus.append(("Work", panel(
            "Experience" if jobs else "Work",
            (f'<div class="mm-grid one" style="margin-bottom:22px">{roles}</div>' if roles else f'<p class="mm-lede">{len(projects)} projects, from prototypes to production.</p>')
            + f'<a class="ul" href="#{"experience" if jobs else "projects"}">{"See the full timeline" if jobs else "See all projects"}</a>',
            "Featured projects" if featured else "Projects", "".join(f'<a class="ul" href="#proj-{i}">{e(x["name"])}</a>' for i, x in projects[:6]))))
    docs = (f'<a class="mm-item" href="{e(paths["resume"])}"><b>Resume</b><small>One or two pages, ready to print</small></a>'
            f'<a class="mm-item" href="{e(paths["cv"])}"><b>Curriculum vitae</b><small>Everything, with publications</small></a>')
    elsewhere = "".join(f'<a class="ul" href="{e(u)}" target="_blank" rel="noopener noreferrer">{e(l)}</a>' for l, u in links[:8])
    if p["publications"]: elsewhere = '<a class="ul" href="#background">Publications</a>' + elsewhere
    menus.append(("Resources", panel("Documents", f'<div class="mm-grid one">{docs}</div>', "Elsewhere", elsewhere)))
    nav = "".join(f'<div class="mm"><button type="button" class="mm-btn" aria-haspopup="true">{label}{CHEV}</button>{body}</div>' for label, body in menus)

    burger_links = [("#about", "About"), *([("#projects", "Projects")] if projects else []), *([("#experience", "Experience")] if jobs else []),
                    *([("#skills", "Skills")] if skills else []), ("#contact", "Contact")]
    burger = (f'<details class="burger"><summary aria-label="Menu">{BURGER}</summary><nav class="burger-panel" aria-label="Menu">'
              + "".join(f'<a href="{h}">{l}</a>' for h, l in burger_links)
              + f'<p class="eyebrow">Documents</p><a href="{e(paths["resume"])}">Resume</a><a href="{e(paths["cv"])}">CV</a>'
              + (f'<p class="eyebrow">Elsewhere</p>' + "".join(f'<a href="{e(u)}" target="_blank" rel="noopener noreferrer">{e(l)}</a>' for l, u in links) if links else "")
              + "</nav></details>")
    header = (f'<header class="nav"><div class="wrap nav-in"><a class="logo" href="#top"><span class="mono">{e(initials(name))}</span>{e(name)}</a>'
              f'<nav class="menu" aria-label="Main">{nav}<a class="menu-link" href="#contact">Contact</a></nav>'
              f'<div class="nav-cta"><a class="btn sm ghost" href="{e(paths["resume"])}">Resume</a><a class="btn sm solid" href="{e(reach)}">Get in touch</a></div>{burger}</div></header>')

    photo = _photo(p)
    art = f'<figure class="photo"><img src="{e(photo)}" alt="{e(name)}" referrerpolicy="no-referrer"></figure>' if photo else ART
    kicker = p["availability"] or p["location"]
    hero = (f'<section class="hero" id="about"><div class="wrap hero-in"><div>'
            f'{f"<p class=kicker><span class=dot></span>{e(kicker)}</p>" if kicker else ""}'
            f'<h1{" class=long" if len(headline) > 34 else ""}>{e(headline)}</h1><p class="lede">{e(p["summary"] or f"Hi, I’m {first_name}.")}</p>'
            f'<div class="ctas"><a class="btn solid" href="#{"projects" if projects else "contact"}">See my work {ARROW}</a>'
            f'<a class="btn ghost" href="{e(paths["cv"])}">Download CV</a></div></div><div class="art">{art}</div></div></section>')

    y = years(p)
    stats = [(f"{y}+", "years of experience")] if y else []
    if projects: stats.append((str(len(projects)), "projects shipped"))
    if skills: stats.append((str(len(skills)), "skills and tools"))
    if p["publications"]: stats.append((str(len(p["publications"])), "papers and talks"))
    stats_html = f'<div class="stats wrap">{"".join(f"<div class=stat><b>{v}</b><span>{l}</span></div>" for v, l in stats)}</div>' if len(stats) >= 2 else ""
    companies = list(dict.fromkeys(j["company"] for j in jobs if j["company"]))
    logos = f'<div class="logos wrap"><p class="eyebrow">Previously at</p>{"".join(f"<span>{e(c)}</span>" for c in companies[:6])}</div>' if companies else ""

    def card(i, x):
        ls = "".join(f'<a class="ul" href="{e(href(u))}" target="_blank" rel="noopener noreferrer">{l} ↗</a>' for u, l in ((x["url"], "Live"), (x["repo"], "Code")) if href(u))
        return (f'<article class="card" id="proj-{i}">{"<span class=badge>Featured</span>" if x["featured"] else ""}<h3>{e(x["name"])}</h3>'
                f'{f"<p>{e(x["description"])}</p>" if x["description"] else ""}'
                f'{f"<div class=chips>{"".join(f"<span>{e(s)}</span>" for s in x["tech"])}</div>" if x["tech"] else ""}'
                f'{f"<div class=card-links>{ls}</div>" if ls else ""}</article>')

    def role(i, j):
        return (f'<li id="exp-{i}"><div class="tl-when">{e(span(j["start"], j["end"]))}</div><div>'
                f'<h3>{e(j["title"])}{f" <span>· {e(j["company"])}</span>" if j["company"] else ""}</h3>'
                f'{f"<p class=where>{e(j["location"])}</p>" if j["location"] else ""}{_ul(j["bullets"])}'
                f'{f"<div class=chips>{"".join(f"<span>{e(s)}</span>" for s in j["tech"])}</div>" if j["tech"] else ""}</div></li>')

    def section(id_, eyebrow, title, body):
        return f'<section class="s" id="{id_}"><div class="wrap"><p class="eyebrow">{eyebrow}</p><h2>{title}</h2>{body}</div></section>' if body else ""

    work = section("projects", "Selected work", "Projects", f'<div class="cards">{"".join(card(i, x) for i, x in projects)}</div>' if projects else "")
    career = section("experience", "Career", "Experience", f'<ol class="timeline">{"".join(role(i, j) for i, j in enumerate(jobs))}</ol>' if jobs else "")
    groups = [g for g in p["skills"] if g["items"]]
    skill_html = section("skills", "Toolbox", "Skills", '<div class="skill-grid">' + "".join(
        f'<div class="skill"><h3>{e(g["name"] or "Skills")}</h3><div class="chips">{"".join(f"<span>{e(s)}</span>" for s in g["items"])}</div></div>' for g in groups) + "</div>" if groups else "")
    col = lambda title, entries: f'<div><p class="eyebrow">{title}</p>{"".join(entries)}</div>' if entries else ""
    background = "".join([
        col("Education", [f'<div class="entry"><b>{e(s["degree"] or s["school"])}</b><span>{e(" · ".join(x for x in (s["school"] if s["degree"] else "", span(s["start"], s["end"]), s["detail"]) if x))}</span></div>' for s in p["education"]]),
        col("Publications &amp; talks", [f'<div class="entry"><b>{_link(x["url"], x["title"], "ul")}</b><span>{e(", ".join(v for v in (x["venue"], x["year"]) if v))}</span></div>' for x in p["publications"]]),
        col("Certifications", [f'<div class="entry"><b>{_link(x["url"], x["name"], "ul")}</b><span>{e(", ".join(v for v in (x["issuer"], x["year"]) if v))}</span></div>' for x in p["certifications"]]),
        col("Languages", [f'<div class="entry"><b>{e(l)}</b></div>' for l in p["languages"]])])
    bg_html = section("background", "Background", "Education &amp; writing", f'<div class="cols">{background}</div>' if background else "")
    contact_btns = (f'<a class="btn solid" href="mailto:{e(email)}">Email me {ARROW}</a>' if email else "") + "".join(
        f'<a class="btn ghost" href="{e(u)}" target="_blank" rel="noopener noreferrer">{e(l)}</a>' for l, u in links[:3])
    band = (f'<section class="band" id="contact"><div class="wrap band-in"><div><p class="eyebrow">Contact</p><h2>Let’s build something intelligent.</h2>'
            f'<p>{e(p["availability"] or "Open to interesting AI work.")}</p></div><div class="ctas">{contact_btns}'
            f'<a class="btn ghost" href="{e(paths["resume"])}">Resume</a></div></div></section>')
    footer = (f'<footer><div class="wrap"><span>© {date.today().year} {e(name)}</span><nav aria-label="Footer">'
              + "".join(f'<a href="{e(u)}" target="_blank" rel="noopener noreferrer">{e(l)}</a>' for l, u in links)
              + f'<a href="{e(paths["cv"])}">CV</a></nav><span>Made with AXoR</span></div></footer>')
    root = (f':root{{color-scheme:{"light" if _lum(t["bg"]) > .5 else "dark"};--bg:{t["bg"]};--panel:{t["panel"]};--panel2:{t["panel2"]};--line:{t["line"]};'
            f'--text:{t["text"]};--muted:{t["muted"]};--acc:{acc};--acc-t:{readable(acc, t["bg"])};--on:{on_color(acc)};--shadow:{t["shadow"]}}}')
    desc = e(teaser or headline)
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{e(name)} · {e(headline)}</title><meta name="description" content="{desc}">'
            f'<meta property="og:type" content="profile"><meta property="og:title" content="{e(name)} · {e(headline)}"><meta property="og:description" content="{desc}">'
            f'{f"<meta property=og:image content={chr(34)}{e(photo)}{chr(34)}>" if photo else ""}'
            f'<link rel="icon" href="{favicon(initials(name), acc, on_color(acc))}"><meta name="theme-color" content="{t["bg"]}">'
            f'<style>{root}{SITE_CSS}</style></head><body id="top">{header}<main>{hero}{stats_html}{logos}{work}{career}{skill_html}{bg_html}{band}</main>{footer}</body></html>')

def site_zip(p):
    """The website as a static site for Netlify (a zip deploy or Netlify Drop) or any other host."""
    paths = {"home": "/", "resume": "/resume/", "cv": "/cv/"}
    files = {"index.html": site(p, paths),
             "resume/index.html": resume(p, "resume", public=True, back="/"),
             "cv/index.html": resume(p, "cv", public=True, back="/"),
             "_headers": f"/*\n  Content-Security-Policy: {CSP}; frame-ancestors 'none'\n  X-Content-Type-Options: nosniff\n"
                         "  Referrer-Policy: strict-origin-when-cross-origin\n"}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items(): z.writestr(name, text)
    return buf.getvalue()

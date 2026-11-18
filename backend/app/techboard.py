"""Tech Daily: one edition a day of new technology (AI, software, Android, devices, IoT and security), told like ads.

The builder runs once a day, after TECH_DAILY_HOUR (UTC), and at start-up when the last edition is over a day old:
- it reads the tech press's public feeds (RSS and Atom), Hacker News's top stories of the last day and new GitHub
  repositories gaining stars. Everything is fetched by the server; viewers' browsers only load the images.
- each story gets a category (its feed's, or by keywords for general feeds, Hacker News and GitHub) and a score for
  freshness, the source, and Hacker News points or GitHub stars. Duplicates (same link, or nearly the same title) and
  stories run in the last week's editions are dropped, and each category keeps its best few, at most three per outlet.
- stories without an image or a summary get the article's og:image and og:description.
- the agents' default model (TECH_MODEL, or "off") writes the ad copy from the story's own title and summary only:
  a headline, a tagline, a short pitch, why it matters, tags, and how big the news is, which orders the category.
  One more call writes the edition's cover line and picks the spotlight. Without a model the stories keep their own words.
Editions are kept TECH_KEEP_DAYS. Admins can rebuild today's edition from the page (audited as tech.rebuild).
Pages are fetched only from public addresses, redirects included, and only a few hundred KB of each is read.
"""
import concurrent.futures, contextlib, html, http.client, ipaddress, json, logging, math, os, re, socket, threading, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from fastapi import APIRouter, HTTPException, Request

log = logging.getLogger("tech")
ENABLED = os.getenv("TECH_DAILY", "1") == "1"
HOUR = int(os.getenv("TECH_DAILY_HOUR", "6"))
KEEP_DAYS = int(os.getenv("TECH_KEEP_DAYS", "60"))
MODEL = os.getenv("TECH_MODEL", "auto")  # an agents model id ("anthropic:claude-haiku-5-5"), "auto" for the default, or "off"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
PER_CATEGORY, CANDIDATES, PER_SOURCE = 6, 10, 3
SOURCE_CAP = {"GitHub": 1}  # per category, where it differs from PER_SOURCE
WINDOW_H, WIDE_H = 36, 96  # how old a story may be, and how old when its category is short of stories
REPEAT_DAYS = 7            # a link that ran in the last week's editions doesn't run again
UA = "Mozilla/5.0 (compatible; AXoR Tech Daily/1.0)"
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# id: (label, the section's line, icon)
CATEGORIES = {
    "ai": ("AI", "Intelligence, shipped daily.", "sparkle"),
    "software": ("Software", "Code that moves everything.", "code"),
    "android": ("Android", "Pocket-sized breakthroughs.", "phone"),
    "devices": ("Devices", "Hardware worth holding.", "devices"),
    "iot": ("IoT", "Everything, connected.", "radio"),
    "security": ("Security", "Trust, verified.", "shield"),
}
# (outlet, feed, category, weight, mixed: sorted by keywords, the category being the fallback)
FEEDS = [
    ("The Verge", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "ai", 1.0, False),
    ("MIT Technology Review", "https://www.technologyreview.com/topic/artificial-intelligence/feed", "ai", 1.0, False),
    ("OpenAI", "https://openai.com/news/rss.xml", "ai", 1.0, False),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml", "ai", 1.0, False),
    ("Google", "https://blog.google/innovation-and-ai/technology/ai/rss/", "ai", 0.9, False),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml", "ai", 0.9, False),
    ("TechCrunch", "https://techcrunch.com/feed/", "software", 1.0, True),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/technology-lab", "software", 1.0, True),
    ("The Register", "https://www.theregister.com/headlines.atom", "software", 0.9, True),
    ("The New Stack", "https://thenewstack.io/feed/", "software", 0.9, False),
    ("GitHub Blog", "https://github.blog/feed/", "software", 0.9, False),
    ("Android Authority", "https://www.androidauthority.com/feed/", "android", 1.0, True),
    ("Android Developers", "https://developer.android.com/static/blog/atom.xml", "android", 1.0, False),
    ("9to5Google", "https://9to5google.com/feed/", "android", 1.0, True),
    ("Engadget", "https://www.engadget.com/rss.xml", "devices", 1.0, True),
    ("The Verge", "https://www.theverge.com/rss/tech/index.xml", "devices", 1.0, True),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/gadgets", "devices", 1.0, False),
    ("GSMArena", "https://www.gsmarena.com/rss-news-reviews.php3", "devices", 0.9, True),
    ("CNX Software", "https://www.cnx-software.com/feed/", "iot", 1.0, True),
    ("Hackster.io", "https://www.hackster.io/news.atom", "iot", 1.0, False),
    ("Raspberry Pi", "https://www.raspberrypi.com/news/feed/", "iot", 0.9, False),
    ("BleepingComputer", "https://www.bleepingcomputer.com/feed/", "security", 1.0, False),
    ("Krebs on Security", "https://krebsonsecurity.com/feed/", "security", 0.9, False),
]
# for mixed feeds, Hacker News and GitHub: hits in the title count twice. Ties go to the earlier category, and a
# Hacker News story that matches none isn't about technology.
RULES = {k: re.compile(v, re.I) for k, v in {
    "security": r"vulnerabilit|exploit|ransomware|malware|data breach|breached|zero-day|0-day|\bcve-\d|phishing|\bhackers?\b|\bhacked\b|backdoor|privacy|"
                r"cyber|infosec|spyware|botnet|\bddos\b|infostealer|supply[- ]chain attack",
    "android": r"\bandroid\b|\bpixel \d|\bpixel (phone|watch|tablet|buds)|\bgalaxy [sza]\d|\bone ui\b|\bwear ?os\b|google play|play store|jetpack|\bkotlin\b",
    "iot": r"\biot\b|internet of things|raspberry pi|arduino|\besp32|\besp8266|microcontroller|\bembedded\b|smart home|home assistant|zigbee|"
           r"lorawan|\blora\b|risc-v|single[- ]board|\bsbc\b|\bmcu\b|\bmatter\b (device|standard|smart)",
    "ai": r"\bai\b|artificial intelligence|\bllms?\b|\bgpt-?\d|chatgpt|\bclaude\b|\bgemini\b|openai|anthropic|deepmind|machine learning|neural|"
          r"diffusion model|transformer|copilot|mistral|\bllama\b|hugging ?face|inference|agentic|\bai agents?\b|chatbot|deepseek|\bqwen",
    "devices": r"iphone|\bipad|macbook|\bmac\b|laptop|tablet|smartwatch|headphones|earbuds|\bcamera\b|\btvs?\b|\bmonitor\b|\bgpus?\b|\bcpus?\b|"
               r"\bchips?\b|processor|snapdragon|apple silicon|console|playstation|xbox|nintendo|\bvr\b|headset|wearable|kindle|e-reader|"
               r"smartphone|\bphones?\b|\bssd\b|\brouter\b",
    "software": r"software|open[- ]source|\breleased?\b|programming|developers?|\bapis?\b|framework|\blibrary\b|database|\blinux\b|\bwindows\b|"
                r"macos|\bios\b|browser|chrome|firefox|compiler|\brust\b|python|javascript|typescript|golang|\bjava\b|kubernetes|docker|"
                r"\bcloud\b|github|\bgit\b|\bsdk\b|\bapps?\b|startup|saas|devops|terminal|\beditor\b|\bcli\b|\bcode\b|\bwasm\b|webassembly",
}.items()}

COPY_SYSTEM = """You are the copywriter of Tech Daily, a board that introduces new technology the way a great product ad does: \
confident, concrete and short. Each story comes with its source, its title and the outlet's own summary (sometimes empty). For every story write:
- headline: at most 7 words, punchy, ad style (for example "Your laptop, now a lab."). It must stay true to the story: no invented \
facts, numbers, prices, dates or names; no clickbait, no questions, and not the outlet's name.
- tagline: one sentence of at most 18 words saying what is new.
- pitch: two or three plain sentences: what it is, who made it, what it does. Use only facts from the title and summary; with no \
summary, write one sentence from the title and don't guess.
- why: up to two short points on why it matters to developers or users; empty when the story doesn't say enough.
- tags: one to three short topic tags, such as "LLM", "Pixel" or "RISC-V".
- importance: 1 to 10, how significant and widely interesting the news is. Launches, releases and real breakthroughs score higher \
than opinion, funding, lawsuits and rumours.
- same_as: when two stories report the same news, give the weaker one the id of the better one; otherwise -1.
Return every story you were given, with its id, in English."""
COPY_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["stories"], "properties": {"stories": {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["id", "headline", "tagline", "pitch", "why", "tags", "importance", "same_as"],
    "properties": {"id": {"type": "integer"}, "headline": {"type": "string"}, "tagline": {"type": "string"}, "pitch": {"type": "string"},
                   "why": {"type": "array", "items": {"type": "string"}}, "tags": {"type": "array", "items": {"type": "string"}},
                   "importance": {"type": "integer"}, "same_as": {"type": "integer"}}}}}}
COVER_SYSTEM = """You edit Tech Daily, a daily board of new technology written like product ads. From today's headlines, write the \
edition's cover line: at most 9 words, ad style, about the day's biggest themes, true to the stories (no invented facts). Then pick \
the spotlight: the id of the most significant launch or release of the day, preferring one marked [picture] when two are close."""
COVER_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["cover", "spotlight"],
                "properties": {"cover": {"type": "string"}, "spotlight": {"type": "integer"}}}

# ---------- fetching ----------
# G5-2.2 Milestone 3 (web security review): every connection goes to an address checked in the same lookup (no second lookup a
# DNS rebinding answer could change), IPv6 forms that carry an internal IPv4 address are refused, only http and https are opened
# (no ftp, file or data handler, no proxy from the environment), at most 5 redirects are followed, each checked the same way, and
# a fetch run under deadline() is cut at its total time even when the server sends a byte at a time.
_NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))
_dl = threading.local()
# Milestone 4: the ports a fetch may connect to (every saved source, link and story in production is https on 443, 11-12);
# AXOR_WEB_PORTS=443 allows https only
PORTS = {int(p) for p in os.getenv("AXOR_WEB_PORTS", "80,443").split(",") if p.strip().isdigit()}
DNS_LIMIT = 8   # seconds a lookup may take when no deadline() is running
_dns = concurrent.futures.ThreadPoolExecutor(8, thread_name_prefix="web-dns")


class NotPublic(OSError):
    """A host that resolves to an address AXoR may not connect to (loopback, private, link-local, metadata, ...)."""


def _global_ip(a):
    """An address AXoR may connect to: globally reachable, not multicast, and no internal IPv4 address inside an IPv6 form
    (IPv4-mapped, IPv4-compatible, NAT64, 6to4, Teredo)."""
    try: ip = ipaddress.ip_address(str(a).split("%")[0])
    except ValueError: return False
    if ip.version == 6:
        inner = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if inner is None and (any(ip in n for n in _NAT64) or int(ip) >> 32 == 0): inner = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if inner is not None and not inner.is_global: return False
    return ip.is_global and not ip.is_multicast


def _resolve(host, port):
    """[(family, sockaddr)] of `host`, every one public, or NotPublic. One lookup: the connection uses exactly these."""
    if port not in PORTS: raise NotPublic(f"port {port} isn't allowed (AXOR_WEB_PORTS: {', '.join(map(str, sorted(PORTS)))})")
    at = getattr(_dl, "at", None)
    wait = max(0.05, at - time.time()) if at else DNS_LIMIT
    f = _dns.submit(socket.getaddrinfo, host, port, 0, 0, socket.IPPROTO_TCP)  # inside the deadline: a slow resolver can't hold the fetch
    try: infos = f.result(timeout=wait)
    except UnicodeError as e: raise NotPublic(f"{host}: {e}") from None   # (a name that doesn't resolve raises socket.gaierror: OSError)
    except concurrent.futures.TimeoutError:
        raise TimeoutError(f"the name {host} didn't resolve in time") from None
    out, seen = [], set()
    for fam, _t, _p, _c, sa in infos:
        if sa[0] not in seen: seen.add(sa[0]); out.append((fam, sa))
    bad = [sa[0] for _f, sa in out if not _global_ip(sa[0])]
    if not out or bad: raise NotPublic(f"{host} resolves to a non-public address{': ' + bad[0] if bad else ''}")
    return out


def check_url(url):
    """None when `url` is http(s) and its host resolves only to public addresses. Raises NotPublic when it isn't (not http(s), no
    host, or a non-public address: a FAIL for the live-data check), and OSError when the name can't be resolved (UNKNOWN: AXoR
    can't tell). An early answer only: the connection checks again, on the addresses it connects to (_pinned_socket)."""
    try: p = urllib.parse.urlparse(url or "")
    except ValueError as e: raise NotPublic(f"not a valid address: {e}") from None
    if p.scheme not in ("http", "https") or not p.hostname: raise NotPublic("not an http(s) address")
    try: port = p.port or (443 if p.scheme == "https" else 80)
    except ValueError as e: raise NotPublic(f"not a valid port: {e}") from None
    _resolve(p.hostname, port)


def _public_url(url):
    """http(s) URL whose host resolves only to public addresses (so a feed can't point the server at internal hosts)."""
    try: check_url(url)
    except (OSError, ValueError): return False
    return True


class _Watch:
    """The deadline's watchdog on one connection: at the deadline the socket it holds is shut, so a read blocked on a server that
    drips bytes returns. It holds the socket in use: the raw one while connecting and in the TLS handshake, then the TLS socket
    (wrapping detaches the raw one, and shutting a detached socket does nothing)."""
    def __init__(self, sock):
        self.sock = sock
        at = getattr(_dl, "at", None)
        if at:
            t = threading.Timer(max(0.0, at - time.time()), self.fire); t.daemon = True; t.start()

    def fire(self):
        try: self.sock.shutdown(socket.SHUT_RDWR)
        except OSError: pass


def _pinned_socket(host, port, timeout, source=None):
    """A connection to `host`, made to the addresses one checked lookup returned (never a second lookup)."""
    err = None
    for _fam, sa in _resolve(host, port):
        at = getattr(_dl, "at", None)
        t = min(timeout, max(0.05, at - time.time())) if at and timeout else timeout
        try: return socket.create_connection((sa[0], port), t, source)
        except OSError as e: err = e
    raise err or NotPublic(f"{host}: no address to connect to")


class _PinnedHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = _pinned_socket(self.host, self.port, self.timeout, self.source_address)
        _Watch(self.sock)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def connect(self):
        sock = _pinned_socket(self.host, self.port, self.timeout, self.source_address)
        w = _Watch(sock)                                                   # the handshake, too, ends by the deadline
        self.sock = w.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req): return self.do_open(_PinnedHTTP, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req): return self.do_open(_PinnedHTTPS, req, context=self._context)


class _Redirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).scheme not in ("http", "https"): raise urllib.error.URLError(NotPublic(f"redirect to another protocol: {newurl[:80]}"))
        if urllib.parse.urlparse(req.full_url).scheme == "https" and urllib.parse.urlparse(newurl).scheme == "http":  # no downgrade
            raise urllib.error.URLError(NotPublic(f"redirect from https to plain http: {newurl[:80]}"))
        try: check_url(newurl)
        except NotPublic as e: raise urllib.error.URLError(NotPublic(f"redirect to a non-public address: {newurl[:120]} ({e})")) from None
        except OSError as e: raise urllib.error.URLError(e) from None   # the redirect's host didn't resolve: a network failure (UNKNOWN)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_opener(context=None):
    """http and https only (no ftp, file or data handler), no proxy from the environment, pinned connections, checked redirects.
    context: the TLS context (tests trust their own certificate with it); None: the system's trust store."""
    o = urllib.request.OpenerDirector()
    for h in (urllib.request.ProxyHandler({}), urllib.request.UnknownHandler(), _PinnedHTTPHandler(), _PinnedHTTPSHandler(context=context),
              urllib.request.HTTPDefaultErrorHandler(), _Redirects(), urllib.request.HTTPErrorProcessor()):
        o.add_handler(h)
    return o


_opener = _build_opener()


@contextlib.contextmanager
def deadline(seconds):
    """Fetches on this thread inside the block end by `seconds` from now, all of it: connecting, redirects, headers and body."""
    prev = getattr(_dl, "at", None)
    _dl.at = time.time() + seconds
    try: yield _dl.at
    finally: _dl.at = prev


def read_until(r, limit, at=None):
    """At most `limit` bytes of a response, read in pieces; past `at` (a deadline()) it raises TimeoutError instead of returning
    what a dripping server sent so far."""
    buf = bytearray()
    read = getattr(r, "read1", None) or r.read
    while len(buf) < limit:
        if at and time.time() >= at: raise TimeoutError("the page took longer than its time limit in total")
        chunk = read(min(65536, limit - len(buf)))
        if not chunk: break
        buf += chunk
    if at and time.time() >= at: raise TimeoutError("the page took longer than its time limit in total")
    return bytes(buf)

def loadable(url):
    """Whether a browser on another site can show this picture: it answers as an image (not SVG) and its
    Cross-Origin-Resource-Policy doesn't forbid it. Reads the first 2 KB only."""
    if not _public_url(url): return False
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/avif,image/webp,image/*", "Range": "bytes=0-2047"})
    try:
        with deadline(8) as at, _opener.open(req, timeout=8) as r:
            kind, corp = (r.headers.get("Content-Type") or "").lower(), (r.headers.get("Cross-Origin-Resource-Policy") or "").lower()
            read_until(r, 2048, at)
            return r.status in (200, 206) and kind.startswith("image/") and "svg" not in kind and corp not in ("same-origin", "same-site")
    except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException):
        return False

def fetch(url, limit=3_000_000, timeout=12, accept="*/*", headers=None):
    """At most `limit` bytes of a public URL, read within `timeout` seconds in total (the lookup, connecting, TLS, headers, body)."""
    with deadline(timeout) as at:
        if not _public_url(url): raise ValueError(f"not a public address: {url}")
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, **(headers or {})})
        with _opener.open(req, timeout=timeout) as r:
            return read_until(r, limit, at)

# ---------- parsing ----------
NS = {"atom": "http://www.w3.org/2005/Atom", "media": "http://search.yahoo.com/mrss/",
      "content": "http://purl.org/rss/1.0/modules/content/", "dc": "http://purl.org/dc/elements/1.1/"}
IMG = re.compile(r"<img\b[^>]*?\bsrc=[\"'](https://[^\"']+)[\"']", re.I)
# tracking pixels, avatars and emoji, and GitHub's generated repository cards (a picture of text: the category's art reads better)
NOT_PHOTO = re.compile(r"feedburner|feedsportal|pixel|1x1|gravatar|emoji|/smilies/|\.gif(\?|$)|\.svg(\?|$)|doubleclick|stats\.|opengraph\.githubassets\.com", re.I)

def _q(ns, tag): return f"{{{NS[ns]}}}{tag}"

def _text(el):
    return "".join(el.itertext()).strip() if el is not None else ""

def plain(s, n=600):
    """Readable text from a feed's HTML summary: no tags, no "The post … appeared first on …", at most n characters."""
    s = re.sub(r"(?is)<(script|style|figure|figcaption|table)\b.*?</\1>", " ", s or "")
    s = re.sub(r"\s+([.,;:!?)])", r"\1", " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split()))  # no space left before punctuation
    s = re.sub(r"\s*The post .{0,300}? appeared first on .{0,120}$", "", s)
    s = re.sub(r"\s*(\[(…|\.\.\.)\]|(Continue|Keep) reading.*|Read (more|the full (story|article)).*)$", "", s, flags=re.I)
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0].rstrip(",;:") + "…"

def _date(s):
    s = (s or "").strip()
    if not s: return None
    try: return parsedate_to_datetime(s).timestamp()
    except (TypeError, ValueError, IndexError): pass
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError: return None

def _photo(url):
    url = html.unescape((url or "").strip())
    return url if url.startswith("https://") and len(url) < 1000 and not NOT_PHOTO.search(url) else None

def _media(el):
    """The entry's own image: media:content / media:thumbnail, an image enclosure, or the first <img> in its HTML."""
    for m in [*el.iter(_q("media", "content")), *el.iter(_q("media", "thumbnail"))]:
        kind = (m.get("medium") or m.get("type") or "image").lower()
        if ("image" in kind or kind == "image") and _photo(m.get("url")): return _photo(m.get("url"))
    for e in [*el.findall("enclosure"), *el.findall(_q("atom", "link"))]:
        if (e.get("type") or "").startswith("image/") and (e.tag == "enclosure" or e.get("rel") == "enclosure"):
            if _photo(e.get("url") or e.get("href")): return _photo(e.get("url") or e.get("href"))
    for part in (el.find(_q("content", "encoded")), el.find("description"), el.find(_q("atom", "content")), el.find(_q("atom", "summary"))):
        for m in IMG.finditer(_text(part)):
            if _photo(m.group(1)): return _photo(m.group(1))
    return None

def parse_feed(data):
    """[{title, url, summary, image, ts}] from RSS 2.0 or Atom bytes (entries without a link, title or date are skipped)."""
    if re.search(rb"<!ENTITY", data[:20000]): raise ValueError("feeds don't declare entities")  # no entity expansion tricks
    root, out = ET.fromstring(data), []
    for it in root.iter("item"):
        guid = it.find("guid")
        url = _text(it.find("link")) or (_text(guid) if guid is not None and guid.get("isPermaLink", "true") != "false" else "")
        out.append({"title": plain(_text(it.find("title")), 300), "url": url,
                    "summary": plain(_text(it.find("description")) or _text(it.find(_q("content", "encoded")))),
                    "image": _media(it), "ts": _date(_text(it.find("pubDate")) or _text(it.find(_q("dc", "date"))))})
    for e in root.iter(_q("atom", "entry")):
        links = e.findall(_q("atom", "link"))
        url = next((l.get("href") for l in links if l.get("rel") in (None, "alternate")), "")
        out.append({"title": plain(_text(e.find(_q("atom", "title"))), 300), "url": url,
                    "summary": plain(_text(e.find(_q("atom", "summary"))) or _text(e.find(_q("atom", "content")))),
                    "image": _media(e), "ts": _date(_text(e.find(_q("atom", "published"))) or _text(e.find(_q("atom", "updated"))))})
    return [s for s in out if s["title"] and s["url"].startswith(("https://", "http://")) and s["ts"]]

META = re.compile(r"<meta\b[^>]*>", re.I)

def page_meta(data):
    """og:image / twitter:image and og:description / description of an article page's <head>."""
    found = {}
    for tag in META.findall(data.decode("utf-8", "replace")):
        attrs = {k.lower(): html.unescape(v) for k, _, v in re.findall(r"""([\w:-]+)\s*=\s*(["'])(.*?)\2""", tag, re.S)}
        key, val = (attrs.get("property") or attrs.get("name") or "").lower(), attrs.get("content", "")
        if key in ("og:image", "og:image:secure_url", "twitter:image", "twitter:image:src", "og:description", "description", "twitter:description"):
            found.setdefault(key, val)
    image = next((found[k] for k in ("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src") if k in found), None)
    desc = next((found[k] for k in ("og:description", "twitter:description", "description") if k in found), "")
    return image, plain(desc, 500)

def canon(url):
    """A link without tracking parameters, fragment, www. or trailing slash, for spotting the same story twice."""
    p = urllib.parse.urlparse(url.strip())
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if not k.lower().startswith(("utm_", "ref", "source", "fbclid", "gclid", "cmp"))]
    host = (p.hostname or "").lower().removeprefix("www.")
    return urllib.parse.urlunparse(("https", host, p.path.rstrip("/") or "/", "", urllib.parse.urlencode(q), ""))

STOP = set("a an and the of to in on for with by from at is are be as it its this that new how why what your you our we can now will vs".split())

def _words(title):
    return set(re.findall(r"[a-z0-9]+", title.lower())) - STOP

def classify(title, summary, fallback, mixed):
    if not mixed: return fallback
    best, top = None, 0
    for cat, rx in RULES.items():
        n = 2 * len(rx.findall(title)) + len(rx.findall(summary))
        if n > top: best, top = cat, n
    return best or fallback

def score(s, now):
    """Freshness (halving every 18 hours) times the source's weight, plus Hacker News points and GitHub stars."""
    fresh = 0.6 if s["kind"] == "github" else 0.5 ** (max(0.0, now - s["ts"]) / 3600 / 18)
    boost = 0.6 * min(1.0, math.log10(s["points"]) / 3.3) if s.get("points", 0) > 1 else 0.0
    boost += 0.3 * min(1.0, math.log10(s["stars"]) / 4) if s.get("stars", 0) > 1 else 0.0
    return s["weight"] * fresh + boost

def _clip(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0].rstrip(",;:") + "…"

def _day(ts=None):
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).strftime("%Y-%m-%d")

# ---------- the board ----------
class TechBoard:
    def __init__(self, db, hub=None):
        self.db, self.hub = db, hub
        self.lock = threading.Lock()
        self.status = {"building": False, "step": "", "error": None, "started": None}
        self.after_build = None  # fn(day), once an edition is saved: the day's brief (tech_analysis.py)
        db.q("""CREATE TABLE IF NOT EXISTS tech_editions (day TEXT PRIMARY KEY, ts REAL, cover TEXT, spotlight INTEGER, model TEXT,
                tokens INTEGER, sources INTEGER, stories INTEGER)""")
        db.q("""CREATE TABLE IF NOT EXISTS tech_stories (id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, category TEXT, rank INTEGER,
                source TEXT, url TEXT, title TEXT, summary TEXT, image TEXT, ts REAL, headline TEXT, tagline TEXT, pitch TEXT, why TEXT,
                tags TEXT, importance INTEGER, points INTEGER, stars INTEGER, UNIQUE(day, url))""")
        db.q("CREATE INDEX IF NOT EXISTS tech_stories_day ON tech_stories (day, category, rank)")

    def start(self):
        if ENABLED: threading.Thread(target=self._loop, daemon=True, name="tech-daily").start()

    def _loop(self):
        time.sleep(45)  # let start-up (and the first chain read) settle
        while True:
            try:
                if self.due(): self.build()
            except Exception:
                log.exception("tech daily build failed")
            time.sleep(600)

    def due(self, now=None):
        now = now or time.time()
        last = self.db.q("SELECT day, ts FROM tech_editions ORDER BY day DESC LIMIT 1", one=True)
        if not last: return True
        if last["day"] == _day(now): return False
        return datetime.fromtimestamp(now, timezone.utc).hour >= HOUR or now - last["ts"] > 30 * 3600

    def next_build(self, now=None):
        """When the next edition is due (UTC timestamp)."""
        now = now or time.time()
        d = datetime.fromtimestamp(now, timezone.utc)
        at = d.replace(hour=HOUR, minute=0, second=0, microsecond=0)
        last = self.db.q("SELECT day FROM tech_editions ORDER BY day DESC LIMIT 1", one=True)
        if at <= d and last and last["day"] == _day(now): at += timedelta(days=1)
        return max(at.timestamp(), now)

    def model(self):
        """The model that writes the copy (provider:model), or None."""
        if MODEL == "off" or not self.hub: return None
        return self.hub.model_of(MODEL)

    # ----- collect -----
    def _step(self, text):
        self.status["step"] = text

    def _feed(self, src):
        name, url, cat, weight, mixed = src
        out = []
        for s in parse_feed(fetch(url, accept="application/rss+xml, application/atom+xml, application/xml, text/xml")):
            c = classify(s["title"], s["summary"], cat, mixed)
            out.append({**s, "source": name, "category": c, "weight": weight, "kind": "feed"})
        return out

    def _hacker_news(self, now):
        q = urllib.parse.urlencode({"tags": "story", "numericFilters": f"points>100,created_at_i>{int(now - 86400)}", "hitsPerPage": 100})
        hits = json.loads(fetch("https://hn.algolia.com/api/v1/search?" + q, accept="application/json")).get("hits", [])
        out = []
        for h in hits:
            title, url = plain(h.get("title") or "", 300), h.get("url") or ""
            cat = classify(title, "", None, True)
            if not url.startswith(("https://", "http://")) or not cat: continue  # Ask HN, and stories that aren't about technology
            out.append({"title": title, "url": url, "summary": "", "image": None, "ts": float(h.get("created_at_i") or now),
                        "source": "Hacker News", "category": cat, "weight": 0.9, "kind": "hn", "points": int(h.get("points") or 0)})
        return out

    def _github(self, now):
        since = _day(now - 7 * 86400)
        q = urllib.parse.urlencode({"q": f"created:>{since} stars:>150", "sort": "stars", "order": "desc", "per_page": 30})
        headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        repos = json.loads(fetch("https://api.github.com/search/repositories?" + q, accept="application/vnd.github+json", headers=headers)).get("items", [])
        out = []
        for r in repos:
            if r.get("fork") or r.get("archived") or not r.get("description"): continue
            about = " ".join([r["description"], " ".join(r.get("topics") or []), r.get("language") or ""])
            out.append({"title": f"{r['full_name']}: {plain(r['description'], 160)}", "url": r["html_url"], "summary": plain(r["description"], 500),
                        "image": None, "ts": _date(r.get("created_at")) or now,  # the page's og:image, if the owner made one
                        "source": "GitHub", "category": classify(r["full_name"] + " " + r["description"], about, "software", True),
                        "weight": 0.85, "kind": "github", "stars": int(r.get("stargazers_count") or 0)})
        return out

    def collect(self, now=None):
        """Every source's stories (a source that fails is skipped) and how many sources answered."""
        now = now or time.time()
        jobs = [(f"{s[0]}", lambda s=s: self._feed(s)) for s in FEEDS] + [("Hacker News", lambda: self._hacker_news(now)), ("GitHub", lambda: self._github(now))]
        stories, ok = [], 0
        with ThreadPoolExecutor(8) as pool:
            for (name, _), fut in zip(jobs, [pool.submit(fn) for _, fn in jobs]):
                try: got = fut.result(); stories += got; ok += 1
                except Exception as e: log.info("tech source %s skipped: %s", name, e)
        return stories, ok

    def select(self, stories, now=None):
        """Up to CANDIDATES fresh stories per category, best first: duplicates and recent repeats out, PER_SOURCE per outlet."""
        now = now or time.time()
        since = _day(now - REPEAT_DAYS * 86400)
        ran = {canon(r["url"]) for r in self.db.q("SELECT url FROM tech_stories WHERE day>=? AND day<?", (since, _day(now)))}
        points = {}
        for s in stories:
            if s.get("points"): points[canon(s["url"])] = max(points.get(canon(s["url"]), 0), s["points"])
        for s in stories:
            s["points"] = max(s.get("points", 0), points.get(canon(s["url"]), 0))  # a feed story that's also on Hacker News
            s["score"] = score(s, now)
        pool, seen, titles = [], set(), []
        for s in sorted(stories, key=lambda s: -s["score"]):
            key, words = canon(s["url"]), _words(s["title"])
            age = (now - s["ts"]) / 3600
            if key in seen or key in ran or (s["kind"] != "github" and (age > WIDE_H or age < -6)): continue
            if any(len(words & w) >= 3 and len(words & w) / min(len(words), len(w)) >= 0.6 for w in titles): continue  # the same news elsewhere
            seen.add(key); titles.append(words); pool.append(s)
        picked = {c: [] for c in CATEGORIES}
        for wide in (False, True):  # fresh stories first; older ones only top up a category that's short
            per = Counter((c, s["source"]) for c, ss in picked.items() for s in ss)
            for s in pool:
                c, age = s["category"], (now - s["ts"]) / 3600
                if c not in picked or s in picked[c] or len(picked[c]) >= (CANDIDATES if not wide else PER_CATEGORY): continue
                if not wide and s["kind"] != "github" and age > WINDOW_H: continue
                if per[(c, s["source"])] >= SOURCE_CAP.get(s["source"], PER_SOURCE): continue
                picked[c].append(s); per[(c, s["source"])] += 1
        return picked

    def _enrich(self, stories, need):
        """The article's og:image and og:description for stories missing `need` ("image" or "summary")."""
        todo = [s for s in stories if not s.get(need) and not s.get(f"_{need}_tried")]
        def one(s):
            s[f"_{need}_tried"] = True
            try:
                image, desc = page_meta(fetch(s["url"], limit=400_000, timeout=8, accept="text/html"))
                if not s.get("image") and image:
                    image = urllib.parse.urljoin(s["url"], image)
                    s["image"] = _photo(image)
                if not s.get("summary") and desc: s["summary"] = desc
            except Exception as e:
                log.debug("tech page %s: %s", s["url"], e)
        with ThreadPoolExecutor(8) as pool: list(pool.map(one, todo))

    def _pictures(self, stories):
        """Keeps only pictures a viewer's browser can load: the feed's, else the article's, else none (the category's art)."""
        def check(s):
            if s.get("image") and s.get("_checked") != s["image"]:
                s["_checked"] = s["image"] if loadable(s["image"]) else None
                if not s["_checked"]: s["image"] = None
        with ThreadPoolExecutor(8) as pool: list(pool.map(check, stories))
        self._enrich(stories, "image")
        with ThreadPoolExecutor(8) as pool: list(pool.map(check, stories))

    # ----- write -----
    def _copy(self, model, cat, stories, used):
        lines = [f"Category: {CATEGORIES[cat][0]}\n"]
        for i, s in enumerate(stories):
            lines.append(f"[id {i}] source: {s['source']}\ntitle: {s['title']}\nsummary: {s['summary'] or '(none)'}\n")
        out = self.hub.llm.structured(model, COPY_SYSTEM, "\n".join(lines), COPY_SCHEMA, "tech_copy", on_usage=lambda n: used.__setitem__(0, used[0] + n))
        for c in (out or {}).get("stories", []):
            i = c.get("id")
            if not isinstance(i, int) or not 0 <= i < len(stories): continue
            s = stories[i]
            if c.get("headline"): s["headline"] = _clip(c["headline"], 80)
            if c.get("tagline"): s["tagline"] = _clip(c["tagline"], 200)
            if c.get("pitch"): s["pitch"] = _clip(c["pitch"], 600)
            s["why"] = [_clip(w, 180) for w in (c.get("why") or []) if str(w).strip()][:2]
            s["tags"] = [_clip(t, 24) for t in (c.get("tags") or []) if str(t).strip()][:3]
            s["importance"] = max(1, min(10, int(c.get("importance") or 5)))
            if isinstance(c.get("same_as"), int) and c["same_as"] != i and 0 <= c["same_as"] < len(stories): s["dupe"] = True

    def build(self, day=None):
        """Builds (or rebuilds) the edition of `day` (today, UTC). Returns False if a build is already running."""
        if not self.lock.acquire(blocking=False): return False
        now = time.time()
        day = day or _day(now)
        self.status.update(building=True, error=None, started=now)
        try:
            self._step("Reading the sources")
            stories, sources = self.collect(now)
            if not stories: raise RuntimeError("No source answered. Check that the server can reach the internet.")
            picked = self.select(stories, now)
            candidates = [s for ss in picked.values() for s in ss]
            self._step("Reading the articles")
            self._enrich(candidates, "summary")
            for s in candidates:
                s.update(headline=_clip(s["title"], 90), tagline=_clip(s["summary"].split(". ")[0], 180) if s["summary"] else "",
                         pitch=_clip(s["summary"], 420), why=[], tags=[], importance=0)
            model, used, cover, spot = self.model(), [0], "", None
            if model:
                self._step("Writing the copy")
                def write(c):
                    try: self._copy(model, c, picked[c], used)
                    except Exception as e: log.warning("tech copy for %s failed: %s", c, e)
                with ThreadPoolExecutor(3) as pool: list(pool.map(write, [c for c in picked if picked[c]]))
            final = {}
            for c, ss in picked.items():
                final[c] = sorted((s for s in ss if not s.get("dupe")), key=lambda s: (-s["importance"], -s["score"]))[:PER_CATEGORY]
            chosen = [s for ss in final.values() for s in ss]
            self._step("Finding the pictures")
            self._pictures(chosen)
            if model and chosen:
                self._step("Writing the cover")
                try:
                    lines = "\n".join(f"[id {i}] {CATEGORIES[s['category']][0]}: {s['headline']} ({s['title']}){' [picture]' if s.get('image') else ''}"
                                      for i, s in enumerate(chosen))
                    out = self.hub.llm.structured(model, COVER_SYSTEM, lines, COVER_SCHEMA, "tech_cover", on_usage=lambda n: used.__setitem__(0, used[0] + n))
                    cover = _clip((out or {}).get("cover"), 90)
                    i = (out or {}).get("spotlight")
                    spot = chosen[i] if isinstance(i, int) and 0 <= i < len(chosen) else None
                except Exception as e:
                    log.warning("tech cover failed: %s", e)
            spot = spot or max(chosen, key=lambda s: (s["importance"] + (1 if s.get("image") else 0), s["score"]), default=None)
            self._save(day, now, final, spot, cover, model if used[0] else None, used[0], sources)
            if self.after_build and model and chosen:
                self._step("Writing the brief")
                self.after_build(day)
            self._step("")
            log.info("tech daily %s: %d stories from %d sources%s", day, len(chosen), sources, f", copy by {model}" if used[0] else "")
            return True
        except Exception as e:
            self.status["error"] = str(e)[:300]
            raise
        finally:
            self.status.update(building=False, step="")
            self.lock.release()

    def _save(self, day, now, final, spot, cover, model, tokens, sources):
        rows = [(day, c, rank, s["source"], s["url"], s["title"], s["summary"], s.get("image"), s["ts"], s["headline"], s["tagline"], s["pitch"],
                 json.dumps(s["why"]), json.dumps(s["tags"]), s["importance"], s.get("points") or 0, s.get("stars") or 0)
                for c, ss in final.items() for rank, s in enumerate(ss)]
        db = self.db
        with db.lock:  # one transaction: readers see the old edition or the new one, never half of it
            db.db.execute("DELETE FROM tech_stories WHERE day=?", (day,))
            db.db.executemany("""INSERT OR IGNORE INTO tech_stories (day, category, rank, source, url, title, summary, image, ts, headline, tagline,
                                 pitch, why, tags, importance, points, stars) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
            spot_id = None
            if spot:
                r = db.db.execute("SELECT id FROM tech_stories WHERE day=? AND url=?", (day, spot["url"])).fetchone()
                spot_id = r[0] if r else None
            db.db.execute("INSERT OR REPLACE INTO tech_editions (day, ts, cover, spotlight, model, tokens, sources, stories) VALUES (?,?,?,?,?,?,?,?)",
                          (day, now, cover, spot_id, model, tokens, sources, len(rows)))
            old = _day(now - KEEP_DAYS * 86400)
            db.db.execute("DELETE FROM tech_stories WHERE day<?", (old,))
            db.db.execute("DELETE FROM tech_editions WHERE day<?", (old,))
            db.db.commit()

    def rebuild(self):
        """Starts rebuilding today's edition in the background; False if one is already being built."""
        if self.status["building"]: return False
        threading.Thread(target=lambda: self._quiet(self.build), daemon=True, name="tech-rebuild").start()
        return True

    @staticmethod
    def _quiet(fn):
        try: fn()
        except Exception: log.exception("tech daily rebuild failed")

    # ----- read -----
    def state(self, admin=False):
        s = self.status
        return {"enabled": ENABLED, "building": s["building"], "step": s["step"], "started": s["started"], "next": self.next_build(),
                "error": s["error"] if admin else (s["error"] and "The last build failed."), "ai": bool(self.model())}

    def latest(self):
        r = self.db.q("SELECT day, ts, stories FROM tech_editions ORDER BY day DESC LIMIT 1", one=True)
        return r or {"day": None, "ts": None, "stories": 0}

    def edition(self, day=None, admin=False):
        days = self.db.q("SELECT day, ts, stories FROM tech_editions ORDER BY day DESC LIMIT 30")
        if day and not DAY.match(day): raise HTTPException(400, "Pick a day as YYYY-MM-DD.")
        if day and day not in {d["day"] for d in days}:
            if not self.db.q("SELECT 1 FROM tech_editions WHERE day=?", (day,), one=True): raise HTTPException(404, "There's no edition for that day.")
        day = day or (days[0]["day"] if days else None)
        ed = self.db.q("SELECT * FROM tech_editions WHERE day=?", (day,), one=True) if day else None
        stories = []
        for r in self.db.q("SELECT * FROM tech_stories WHERE day=? ORDER BY rank", (day,)) if day else []:
            r["why"], r["tags"] = json.loads(r["why"] or "[]"), json.loads(r["tags"] or "[]")
            r["site"] = (urllib.parse.urlparse(r["url"]).hostname or "").removeprefix("www.")
            stories.append(r)
        if ed and not admin: ed.pop("tokens", None)
        return {"edition": ed, "stories": stories, "days": days, "state": self.state(admin), "admin": admin,
                "categories": [{"id": k, "label": v[0], "line": v[1], "icon": v[2]} for k, v in CATEGORIES.items()]}

def build(db, user, admin, ip, hub=None):
    """`user(req)`: the signed-in user (None when sign-in is off); `admin(req)`: the same, for admins only."""
    r = APIRouter(prefix="/api/tech")
    board = TechBoard(db, hub)
    r.state = {"board": board}
    is_admin = lambda me: bool(me and me.get("role") == "admin")

    @r.get("")
    def edition(req: Request, day: str | None = None):
        return board.edition(day, is_admin(user(req)))

    @r.get("/latest")
    def latest(req: Request):
        user(req)
        return board.latest()

    @r.get("/status")
    def status(req: Request):
        return board.state(is_admin(user(req)))

    @r.post("/rebuild")
    def rebuild(req: Request):
        me = admin(req)
        if not ENABLED: raise HTTPException(409, "Tech Daily is turned off on this server (TECH_DAILY=0).")
        if board.rebuild(): db.log("tech.rebuild", me["username"], _day(), ip(req))
        return board.state(True)

    return r

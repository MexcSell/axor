"""tech_analysis.py (Technology Research → Analyze and the research brief): article text without page furniture; an
analysis read from the article, kept by link so a rebuild of the edition keeps it, written once however often it's asked,
charged to the asker and capped per day; an unreadable page means an analysis from the summary that can't claim high
confidence; no model means a 503, not a call; the brief maps its themes back to the stories (dropping ids it made up),
goes stale when the edition is rebuilt, and is written again by the daily build; the week's brief takes each story once."""
import json, os, tempfile, time, unittest

from fastapi import HTTPException

from app import tech_analysis, techboard
from app.auth import AuthDB

ADMIN = {"id": 1, "username": "leo", "role": "admin"}
ANA = {"id": 2, "username": "ana", "role": "member"}
PAGE = ("<html><head><script>var x = 1;</script></head><body><nav><p>Home · News · Reviews · Deals and more links here</p></nav>"
        "<article><h1>Acme ships an on-device model runtime</h1>"
        + "".join(f"<p>Paragraph {i} explains how the runtime compiles models ahead of time for phone NPUs, with details.</p>" for i in range(30))
        + "<aside><p>Related: ten other stories you might like to read today</p></aside><p>Advertisement for something else entirely</p></article>"
        "<footer><p>Copyright notice and the outlet's address, repeated</p></footer></body></html>").encode()
ANALYSIS = {"summary": "Acme released a runtime.", "what": "A runtime.", "how": "Ahead-of-time compiling.", "points": ["a", "b", "c", "d", "e", "f"],
            "audience": "App developers.", "uses": ["x"], "limits": ["y"], "maturity": "available", "verdict": "try",
            "verdict_why": "Worth a test.", "background": "", "confidence": "high"}


class LLM:
    def __init__(self): self.calls = []
    def structured(self, model, system, prompt, schema, name, on_usage=None, effort="low"):
        self.calls.append((name, prompt))
        if on_usage: on_usage(1200)
        if name == "tech_analysis": return dict(ANALYSIS)
        ids = [int(x) for x in __import__("re").findall(r"^\[id (\d+)\]", prompt, __import__("re").M)]
        return {"headline": "A week of runtimes", "summary": "Runtimes moved on-device.", "watch": ["w"], "takeaways": ["t1", "t2"],
                "themes": [{"title": "On-device AI", "summary": "s", "stories": [ids[-1], 0, 0, 99]}, {"title": "", "summary": "dropped", "stories": [0]}]}


class Hub:
    def __init__(self, model="anthropic:claude-haiku-5-5"):
        self.llm, self.model, self.usage, self.gated = LLM(), model, [], []
    def model_of(self, choice): return self.model
    def gate(self, me): self.gated.append(me["id"]); return me
    def log_usage(self, me, source, tokens, agent_id=None, model=None): self.usage.append((me["id"], source, tokens))


def story(url, cat="ai", headline="Acme ships a runtime", importance=8):
    return {"source": "The Verge", "url": url, "title": headline + " (title)", "summary": "Acme's new runtime.", "image": None, "ts": time.time(),
            "headline": headline, "tagline": "", "pitch": "Acme released it.", "why": [], "tags": [], "importance": importance, "category": cat}


class TechAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.hub = Hub()
        self.board = techboard.TechBoard(self.db, self.hub)
        self.an = tech_analysis.TechAnalyst(self.db, self.board, self.hub)
        self.fetch, self.pages = techboard.fetch, {}
        techboard.fetch = lambda url, **kw: self.pages[url] if url in self.pages else (_ for _ in ()).throw(OSError("unreachable"))
        self.limits = (tech_analysis.DAILY, tech_analysis.PER_USER)
        self.day = techboard._day()
        self.save(self.day, [story("https://ex.com/a?utm_source=x"), story("https://ex.com/b", "security", "Patch now", 6)])

    def tearDown(self):
        techboard.fetch = self.fetch
        tech_analysis.DAILY, tech_analysis.PER_USER = self.limits
        self.dir.cleanup()

    def save(self, day, stories, ts=None):
        final = {c: [s for s in stories if s["category"] == c] for c in techboard.CATEGORIES}
        self.board._save(day, ts or time.time(), final, stories[0], "Cover.", "m", 10, 3)

    def sid(self, url, day=None):
        return self.db.q("SELECT id FROM tech_stories WHERE day=? AND url=?", (day or self.day, url), one=True)["id"]

    def test_article_text_keeps_the_article_only(self):
        text = tech_analysis.article_text(PAGE)
        self.assertIn("Paragraph 0 explains", text)
        self.assertNotIn("var x", text)
        self.assertNotIn("Related:", text)
        self.assertNotIn("Copyright", text)
        self.assertNotIn("Advertisement", text)
        self.assertNotIn("Home · News", text)
        self.assertLessEqual(len(tech_analysis.article_text(PAGE, 300)), 302)
        # <article> tags that are only related-story teasers: the page's own paragraphs win
        teasers = ("<body>" + "".join(f"<article><h3>Teaser number {i} about another story</h3></article>" for i in range(6))
                   + "<div class='post'>" + "".join(f"<p>The Fold 8 doubles its storage at the same price, sentence {i}.</p>" for i in range(30)) + "</div></body>")
        self.assertIn("doubles its storage", tech_analysis.article_text(teasers))

    def test_analysis_from_the_article_is_kept_by_link_and_written_once(self):
        self.pages["https://ex.com/a?utm_source=x"] = PAGE
        a = self.sid("https://ex.com/a?utm_source=x")
        out = self.an.analyze(a, ANA)["analysis"]
        self.assertEqual((out["based_on"], out["verdict"], out["maturity"], out["confidence"]), ("article", "try", "available", "high"))
        self.assertEqual(len(out["points"]), 5)
        prompt = self.hub.llm.calls[0][1]
        self.assertIn("<article>", prompt)
        self.assertIn("Paragraph 3", prompt)
        self.assertEqual(self.hub.usage, [(2, "tech", 1200)])
        self.assertEqual(self.hub.gated, [2])
        self.an.analyze(a, ANA)  # kept: no second call
        self.assertEqual(len(self.hub.llm.calls), 1)
        # a rebuild gives the story a new id and drops the tracking parameter: the analysis is still there
        self.save(self.day, [story("https://ex.com/a"), story("https://ex.com/b", "security", "Patch now", 6)])
        b = self.sid("https://ex.com/a")
        self.assertNotEqual(a, b)
        self.assertEqual(self.an.get(b)["analysis"]["summary"], "Acme released a runtime.")
        self.assertEqual(self.an.analyzed(self.day), [b])
        with self.assertRaises(HTTPException) as e: self.an.get(a)
        self.assertEqual(e.exception.status_code, 404)

    def test_unreadable_article_means_summary_and_no_high_confidence(self):
        out = self.an.analyze(self.sid("https://ex.com/b"), ANA)["analysis"]
        self.assertEqual((out["based_on"], out["confidence"]), ("summary", "low"))
        self.assertNotIn("<article>", self.hub.llm.calls[0][1])
        self.assertIn("couldn't be read", self.hub.llm.calls[0][1])

    def test_daily_caps_and_force(self):
        tech_analysis.PER_USER = 1
        self.an.analyze(self.sid("https://ex.com/a?utm_source=x"), ANA)
        with self.assertRaises(HTTPException) as e: self.an.analyze(self.sid("https://ex.com/b"), ANA)
        self.assertEqual(e.exception.status_code, 429)
        self.an.analyze(self.sid("https://ex.com/b"), ADMIN)  # admins aren't held to the per-user cap
        tech_analysis.DAILY = 2
        self.save(self.day, [story("https://ex.com/a"), story("https://ex.com/b", "security"), story("https://ex.com/c", "iot")])
        with self.assertRaises(HTTPException) as e: self.an.analyze(self.sid("https://ex.com/c"), ADMIN)
        self.assertEqual(e.exception.status_code, 429)
        n = len(self.hub.llm.calls)
        self.an.analyze(self.sid("https://ex.com/b"), ADMIN, force=True)  # writing one again isn't a new analysis
        self.assertEqual(len(self.hub.llm.calls), n + 1)

    def test_no_model_means_503_and_no_call(self):
        self.hub.model = None
        with self.assertRaises(HTTPException) as e: self.an.analyze(self.sid("https://ex.com/b"), ANA)
        self.assertEqual(e.exception.status_code, 503)
        with self.assertRaises(HTTPException) as e: self.an.write_brief("day", self.day, ANA)
        self.assertEqual(e.exception.status_code, 503)
        self.assertFalse(self.hub.llm.calls)
        self.assertFalse(self.an.get(self.sid("https://ex.com/b"))["ai"])
        self.an.after_build(self.day)  # the daily build just goes without
        self.assertIsNone(self.an.brief("day", self.day)["brief"])

    def test_brief_maps_themes_to_stories_and_goes_stale(self):
        self.assertIs(self.board.after_build.__func__, tech_analysis.TechAnalyst.after_build)
        out = self.an.write_brief("day", self.day, ANA)["brief"]
        self.assertEqual(out["headline"], "A week of runtimes")
        self.assertEqual(len(out["themes"]), 1)  # the untitled theme is dropped
        refs = out["themes"][0]["stories"]
        self.assertEqual([r["url"] for r in refs], ["https://ex.com/b", "https://ex.com/a?utm_source=x"])  # 99 dropped, 0 once
        self.assertEqual(refs[1]["id"], self.sid("https://ex.com/a?utm_source=x"))
        self.assertFalse(out["stale"])
        self.assertEqual(self.hub.usage[-1], (2, "tech", 1200))
        n = len(self.hub.llm.calls)
        self.an.write_brief("day", self.day, ANA)  # kept
        self.assertEqual(len(self.hub.llm.calls), n)
        self.db.q("UPDATE tech_briefs SET ts=ts-60")  # written a minute before the rebuild
        self.save(self.day, [story("https://ex.com/a"), story("https://ex.com/b", "security")])
        out = self.an.brief("day", self.day)["brief"]
        self.assertTrue(out["stale"])
        self.assertEqual(out["themes"][0]["stories"][0]["id"], self.sid("https://ex.com/b"))
        self.an.after_build(self.day)  # what the daily build calls: written again, not charged to anyone
        self.assertEqual(len(self.hub.llm.calls), n + 1)
        self.assertFalse(self.an.brief("day", self.day)["brief"]["stale"])

    def test_week_brief_takes_each_story_once(self):
        old = techboard._day(time.time() - 2 * 86400)
        self.save(old, [story("https://ex.com/a"), story("https://ex.com/old", "devices", "Old one", 9)])
        self.an.write_brief("week", self.day, ADMIN)
        prompt = self.hub.llm.calls[-1][1]
        self.assertEqual(prompt.count("[id "), 3)  # a, b and old: a ran on both days
        self.assertIn("the seven days up to", prompt)
        with self.assertRaises(HTTPException) as e: self.an.write_brief("month", self.day, ADMIN)
        self.assertEqual(e.exception.status_code, 400)

    def test_build_writes_the_brief_after_saving(self):
        seen = []
        self.board.after_build = seen.append
        self.board.collect = lambda now: ([{**story("https://ex.com/z"), "kind": "feed", "weight": 1.0}], 1)
        self.board._enrich = self.board._pictures = lambda *a: None
        self.board.build()
        self.assertEqual(seen, [self.day])


if __name__ == "__main__":
    unittest.main()

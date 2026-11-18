"""Study: two learning tracks, AI Engineer and English C1+, taught by a study team of tutor agents.

- Tracks are paths of modules and topics (TRACKS). Each user ticks topics off and sets a level and a goal per track.
- Streak: a day counts once the user ticks a topic or chats with a study agent that day, by the page's local date
  (accepted within a day of UTC, otherwise UTC is used).
- Practice drills are exercises in the page, written by the model for the learner (practice.py): lessons, quizzes graded as
  you go, flashcards with spaced repetition (a deck per track), pronunciation and dictation scored in the browser, writing
  corrections, coding exercises and reviews, plans and projects, and voice sessions with a tutor ending in a feedback report.
  Finished drills are kept as recent practice and count towards the streak.
- The Lab (AI Engineer track; frontend/lab.js) is a practice environment in the browser: a terminal, a Python editor and a
  SQL playground on Pyodide (PYODIDE, loaded in a worker whose CSP main.py sets), so nothing the learner runs reaches the
  server, plus a prompt playground that calls the connected models here (lab_prompt). The lab drill sets hands-on tasks
  in it whose checks run in the browser, and its Projects are onboarding repos (lab_projects) worked ticket by ticket,
  with CI in the browser too. Neither needs agents: tasks are written by a model, projects aren't.
- The study team is the agent hub's Study templates (agent_hub.STUDY); "Create study team" makes or reuses them. Chats are
  kept per agent and track, and the open track (and topic, if one is picked) is passed to the agent as context.
- Study agents get two tools from here: study_progress (the learner's tracks) and mark_topic (tick or untick a topic on the
  learner's own path). They can't reach subnet data.
"""
import json, time
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import lab_projects, practice
from .agent_hub import STUDY
from .agents import _schema
from .llm import LLMError

MAX_GOAL = 200
MAX_CARDS = 1000  # per track
RECENT = 8        # finished drills listed per track
STREAK_WINDOW = 400  # days of activity read back to count a streak
# the Lab's Python: Pyodide from one pinned path (main.py allows only this path in the lab worker's CSP)
PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.29.5/full/"
LAB_SYSTEM, LAB_TEXT, LAB_TURNS = 20_000, 40_000, 24  # prompt playground: characters of system prompt and of turns, turns

# (module id, title, [(topic id, title)]); a topic's id on the path is "<module>.<topic>"
TRACKS = [
    {"id": "ai", "title": "AI Engineer", "icon": "chip", "color": "violet",
     "blurb": "From how LLMs work to shipping RAG, agents and evals in production, with a portfolio and interviews at the end.",
     "levels": [["new", "New to AI and coding"], ["dev", "Software engineer"], ["ml", "Data or ML practitioner"], ["pro", "Working AI engineer"]],
     "modules": [
         ("found", "Foundations", [
             ("python", "Python for AI: typing, async, packaging and virtual environments"),
             ("math", "The math you need: vectors, matrices, probability and gradients"),
             ("ml", "ML basics: train, validation and test sets, overfitting, losses and metrics"),
             ("nn", "Neural networks, backpropagation and PyTorch basics")]),
         ("llm", "How LLMs work", [
             ("tokens", "Tokenization and context windows"),
             ("attention", "Transformers and attention"),
             ("training", "Pretraining, instruction tuning and RLHF"),
             ("sampling", "Sampling: temperature, top-p, stop sequences and determinism"),
             ("models", "Choosing a model: quality, latency, cost and context length")]),
         ("api", "Building with LLM APIs", [
             ("prompting", "Prompt engineering: system prompts, examples and step-by-step reasoning"),
             ("structured", "Structured output and JSON schemas"),
             ("reliability", "Streaming, retries, timeouts and rate limits"),
             ("cost", "Token budgets, prompt caching and cost control")]),
         ("rag", "Retrieval (RAG)", [
             ("embeddings", "Embeddings and similarity search"),
             ("chunking", "Chunking and indexing documents"),
             ("hybrid", "Vector databases and hybrid search (BM25 plus vectors)"),
             ("rerank", "Reranking and query rewriting"),
             ("measure", "Measuring retrieval: recall@k, MRR and faithfulness")]),
         ("agents", "Agents and tool use", [
             ("loop", "Tool calling and the agent loop"),
             ("memory", "Planning, memory and long multi-step tasks"),
             ("multi", "Multi-agent patterns and hand-offs"),
             ("mcp", "MCP: Model Context Protocol servers and clients"),
             ("safety", "Agent safety: permissions, prompt injection and sandboxing")]),
         ("evals", "Evaluation", [
             ("datasets", "Building eval sets from real usage"),
             ("judge", "LLM-as-judge, rubrics and human review"),
             ("regress", "Regression tests and CI for prompts and agents"),
             ("online", "Online metrics, A/B tests and user feedback")]),
         ("tune", "Fine-tuning and open models", [
             ("when", "When to prompt, retrieve or fine-tune"),
             ("lora", "LoRA, QLoRA and parameter-efficient tuning"),
             ("prefs", "Preference tuning (DPO) and synthetic data"),
             ("serving", "Serving open models: vLLM, quantization and GPU sizing")]),
         ("prod", "Production", [
             ("latency", "Latency, throughput and cost budgets"),
             ("observe", "Observability: tracing, logging and token accounting"),
             ("guard", "Guardrails, privacy (PII) and abuse prevention"),
             ("design", "System design: a support assistant, a RAG search, an agent platform")]),
         ("career", "Portfolio and interviews", [
             ("project", "Ship an end-to-end AI app with evals and a write-up"),
             ("oss", "Contribute to an open-source AI project"),
             ("interview", "AI engineer interviews: coding, LLM system design, behavioural")]),
     ]},
    {"id": "english", "title": "English C1+", "icon": "globe", "color": "teal",
     "blurb": "Advanced English for work and life: fluent speaking, natural pronunciation, precise grammar and vocabulary, at C1 and beyond.",
     "levels": [["b2", "B2 · Upper intermediate"], ["c1", "C1 · Advanced"], ["c2", "C2 · Proficient"]],
     "modules": [
         ("speak", "Speaking fluency", [
             ("long-turn", "Speak for two minutes on any topic without long pauses"),
             ("fillers", "Natural fillers, hedges and thinking time (I'd say…, to some extent…)"),
             ("stories", "Telling stories and anecdotes"),
             ("abstract", "Discussing abstract ideas, opinions and hypotheticals")]),
         ("pron", "Pronunciation and intonation", [
             ("stress", "Word stress and sentence stress"),
             ("connected", "Connected speech: linking, weak forms and elision"),
             ("intonation", "Intonation for questions, lists, contrast and emphasis"),
             ("sounds", "The sounds that are hardest from your first language")]),
         ("grammar", "Advanced grammar", [
             ("conditionals", "Mixed conditionals and alternatives to if (provided that, unless, were it not for)"),
             ("inversion", "Inversion for emphasis (Not only…, Rarely have I…)"),
             ("cleft", "Cleft sentences (What I need is…, It was she who…)"),
             ("modals", "Past modals of deduction and speculation (must have, can't have, might have)"),
             ("participles", "Participle clauses and reduced relative clauses"),
             ("articles", "Articles and countability with C1 precision")]),
         ("vocab", "Vocabulary", [
             ("collocations", "Collocations (heavy rain, make a decision, bitterly disappointed)"),
             ("phrasal", "Phrasal verbs in context"),
             ("idioms", "Idioms and fixed expressions"),
             ("academic", "Academic and technical vocabulary"),
             ("nuance", "Near-synonyms, connotation and word families")]),
         ("register", "Register and tone", [
             ("formality", "Formal and informal English, and switching between them"),
             ("diplomacy", "Softening, hedging and disagreeing diplomatically"),
             ("cohesion", "Cohesion: linking words, reference and signposting")]),
         ("writing", "Writing", [
             ("email", "Professional emails and messages"),
             ("docs", "Reports, design docs and summaries"),
             ("essay", "Essays and arguments (C1 Advanced, IELTS Task 2)"),
             ("edit", "Editing for clarity and concision")]),
         ("listen", "Listening", [
             ("fast", "Fast speech and different accents (US, UK, Australian, non-native)"),
             ("talks", "Talks and podcasts: taking notes and summarising"),
             ("implied", "Implied meaning, humour and sarcasm")]),
         ("work", "English at work", [
             ("meetings", "Meetings: interrupting, agreeing and disagreeing politely"),
             ("present", "Presentations and technical talks"),
             ("interview", "Job interviews in English (STAR answers)"),
             ("smalltalk", "Small talk, networking and negotiation")]),
         ("exam", "Exams (optional)", [
             ("format", "C1 Advanced and C2 Proficiency: format and scoring"),
             ("ielts", "IELTS Academic band 7.5+ strategies"),
             ("timed", "Timed practice and self-assessment against the CEFR descriptors")]),
     ]},
]
# the fast track: the path re-ordered into steps that get you working at a high level soonest (build first, theory when it
# pays off). topics: the step's core; extra: what the full path adds (the fast track skips it unless your level needs it);
# hours: a focused learner's estimate for the core; drill: the checkpoint that proves the step; build: what you make or do.
S = lambda id, title, outcome, hours, topics, drill, build, extra=(): {"id": id, "title": title, "outcome": outcome, "hours": hours,
                                                                      "topics": list(topics), "extra": list(extra), "drill": drill, "build": build}
ROADMAP = {
    "ai": [
        S("first-call", "Ship your first LLM feature", "Call a model from code, control its output and get JSON back.", 6,
          ["api.prompting", "llm.tokens", "llm.sampling", "api.structured"], "quiz",
          "A command-line tool that turns a messy email into a JSON ticket (schema, retries on bad JSON).", ["found.python"]),
        S("models", "Know your models", "Pick the right model for a job and explain why, with cost numbers.", 6,
          ["llm.models", "llm.attention", "llm.training", "api.cost"], "quiz",
          "A one-page model choice for three use cases: quality, latency and monthly cost.", ["found.math", "found.ml", "found.nn"]),
        S("prod-calls", "Production-grade calls", "Make model calls that are fast, observable and don't fall over.", 6,
          ["api.reliability", "prod.latency", "prod.observe"], "code",
          "Add streaming, timeouts, retries with backoff and token logging to your tool."),
        S("rag", "RAG that works", "Answer questions over your own documents with sources.", 10,
          ["rag.embeddings", "rag.chunking", "rag.hybrid", "rag.rerank"], "code",
          "Q&A over a real document set (your notes, a product's docs) with citations."),
        S("evals", "Measure everything", "Prove quality with numbers and catch regressions before users do.", 8,
          ["rag.measure", "evals.datasets", "evals.judge", "evals.regress"], "quiz",
          "A 50-question eval set, an LLM judge with a rubric and a CI check for your RAG app."),
        S("agents", "Agents and tools", "Build an agent that plans, calls tools and stays safe.", 10,
          ["agents.loop", "agents.memory", "agents.mcp", "agents.safety"], "code",
          "An agent with three tools, one of them from an MCP server, and an approval step for risky actions.", ["agents.multi"]),
        S("ship", "Ship it safely", "Design and run an LLM system in production like a senior engineer.", 6,
          ["prod.guard", "evals.online", "prod.design"], "design",
          "A system design write-up for one of your apps: architecture, guardrails, metrics and costs."),
        S("open", "Open models when they pay off", "Know when to fine-tune or self-host, and how.", 6,
          ["tune.when", "tune.serving"], "quiz",
          "Serve an open model with vLLM (or a hosted endpoint) and compare it with your API model on your evals.", ["tune.lora", "tune.prefs"]),
        S("hired", "Get hired", "A portfolio that shows it, and interviews you pass.", 12,
          ["career.project", "career.interview"], "design",
          "Publish your best project with a README, an eval report and a demo; do three mock interviews.", ["career.oss"]),
    ],
    "english": [
        S("fluency", "Unlock fluency", "Talk for two minutes on anything without long pauses.", 6,
          ["speak.long-turn", "speak.fillers", "register.cohesion"], "talk",
          "Record a two-minute answer to a work question every day this week."),
        S("sound", "Sound natural", "Stress, linking and intonation that native speakers follow easily.", 6,
          ["pron.stress", "pron.connected", "pron.intonation"], "pron",
          "Shadow one minute of a talk you like every day, then record it.", ["pron.sounds"]),
        S("grammar", "Precision grammar", "The structures that mark C1: conditionals, modals, clefts and inversion.", 8,
          ["grammar.conditionals", "grammar.modals", "grammar.cleft", "grammar.inversion"], "grammar",
          "Rewrite one of your own emails using three of these structures.", ["grammar.participles", "grammar.articles"]),
        S("words", "Words that make you C1", "Collocations, phrasal verbs and the precise word every time.", 8,
          ["vocab.collocations", "vocab.phrasal", "vocab.nuance"], "vocab",
          "Add ten cards a day from what you read and review the due ones.", ["vocab.idioms", "vocab.academic"]),
        S("tone", "Tone and diplomacy", "Disagree, push back and persuade without sounding rude.", 6,
          ["register.formality", "register.diplomacy", "work.meetings"], "debate",
          "Lead one meeting (or a mock one) and disagree politely at least twice."),
        S("write", "Write like a pro", "Clear, concise emails and documents at C1+.", 8,
          ["writing.email", "writing.docs", "writing.edit"], "write",
          "Write a one-page design doc or report and have it corrected.", ["writing.essay"]),
        S("listen", "Understand everyone", "Follow fast speech, accents and what's implied.", 6,
          ["listen.fast", "listen.talks", "listen.implied"], "listen",
          "Summarise a podcast episode in five sentences, out loud and in writing."),
        S("room", "Own the room", "Stories, opinions and talks that hold attention.", 8,
          ["speak.stories", "speak.abstract", "work.present", "work.smalltalk"], "talk",
          "Give a five-minute talk on your work and take questions."),
        S("interview", "Interview-ready", "Pass a job interview in English with STAR answers.", 6,
          ["work.interview"], "interview",
          "Three mock interviews with Hugo, scored, until you get a strong yes.", ["exam.format", "exam.ielts", "exam.timed"]),
    ],
}
# levels that need part of the full path on the fast track too
LEVEL_CORE = {"ai": {"new": ["found.python", "found.ml"]}, "english": {"b2": ["grammar.articles", "pron.sounds"]}}
PACES = (3, 5, 8, 12, 20, 30)  # hours a week the learner can put in
DEFAULT_PACE = 8

BY_ID = {t["id"]: t for t in TRACKS}
TOPICS = {t["id"]: {f"{m}.{k}": (title, mt) for m, mt, ts in t["modules"] for k, title in ts} for t in TRACKS}

# who teaches a module when the learner picks one of its topics (template ids); "*" for the rest of the track
TUTOR = {"ai": {"career": "study-mentor", "*": "study-tutor"},
         "english": {"speak": "study-conversation", "listen": "study-conversation", "work": "study-conversation", "pron": "study-vocab",
                     "vocab": "study-vocab", "*": "study-writing"}}

# practice drills, each an exercise in the page (frontend/practice.js) run in one of these modes:
# lesson (a short lesson, then check questions), quiz (questions graded as you go), cards (flashcards with spaced repetition),
# pron (read sentences aloud, scored word by word), dictation (listen and type), writing (write, then see corrections),
# code (an exercise or your own code, then a review), plan and project (saved to notes), and dialogue (a voice session with
# the tutor, then a feedback report). agent: the tutor's template id; prompt: what a dialogue opens with ({topic} filled in).
D = lambda id, title, icon, agent, mode, blurb, prompt="": {"id": id, "title": title, "icon": icon, "agent": agent, "mode": mode, "blurb": blurb, "prompt": prompt}
DRILLS = {
    "ai": [
        D("explain", "Teach me a topic", "bulb", "study-tutor", "lesson", "A short lesson on {topic}, then three questions to check you've got it."),
        D("quiz", "Quiz me", "target", "study-tutor", "quiz", "Six questions on {topic}: choices, open answers and spot-the-gap, graded as you go."),
        D("cards", "Concept flashcards", "book", "study-tutor", "cards", "Flashcards for the key terms of {topic}, reviewed with spaced repetition."),
        D("code", "Coding practice", "code", "study-tutor", "code", "Get an exercise on {topic} or paste your own code, run it, then get a senior engineer's line-by-line review."),
        D("lab", "Hands-on lab", "terminal", "study-tutor", "lab", "A task on {topic} in the Lab's terminal, Python editor or SQL playground, checked by tests that run in your browser."),
        D("plan", "Plan my week", "calendar", "study-mentor", "plan", "A seven-day plan from your next topics, with a build task. Save it to your notes."),
        D("project", "Project idea", "zap", "study-mentor", "project", "A one-or-two-weekend portfolio project that practises {topic}, with milestones."),
        D("design", "System design interview", "trophy", "study-interview", "dialogue", "A spoken LLM system design interview with Hugo, scored with a rubric at the end.",
          "Give me an LLM system design interview question{about} and interview me like a senior AI engineer would: one question at a time. Keep each turn short."),
    ],
    "english": [
        D("talk", "Conversation", "chat", "study-conversation", "dialogue", "A spoken conversation with Clara, hands-free, then feedback on fluency, accuracy and range.",
          "Let's have a conversation in English{about}. You pick the topic, keep it natural and ask me follow-up questions. Keep your turns short so I do most of the talking."),
        D("debate", "Debate", "users", "study-conversation", "dialogue", "Argue a point out loud against Clara, then see how precise and persuasive your English was.",
          "Let's debate{about}. Pick a friendly but controversial topic, tell me which side I'm on, take the other side and push me to argue precisely. Keep your turns short."),
        D("write", "Correct my writing", "edit", "study-writing", "writing", "Write to a task (or paste your own text) and see every correction with the reason."),
        D("grammar", "Grammar workout", "book", "study-writing", "quiz", "Eight sentences to transform and complete on {topic}, checked as you go."),
        D("vocab", "Vocabulary cards", "book", "study-vocab", "cards", "C1+ words and phrases with pronunciation, reviewed with spaced repetition."),
        D("pron", "Pronunciation drill", "speaker", "study-vocab", "pron", "Hear a sentence, say it into the microphone, and see which words came through."),
        D("listen", "Dictation", "speaker", "study-conversation", "dictation", "Listen to natural speech sentence by sentence and type what you hear."),
        D("interview", "Job interview", "trophy", "study-interview", "dialogue", "A spoken interview for an AI engineer role with Hugo, scored on content and English.",
          "Interview me in English for an AI engineer role{about}, behavioural questions first, one at a time. Keep your turns short; save the scoring for the end."),
    ],
}

TOOLS = [
    {"name": "study_progress", "strict": True,
     "description": "The learner's Study tab: for each track (ai = AI Engineer, english = English C1+) their level, goal, topics ticked "
                    "per module ([x] done, [ ] not yet, with topic ids like rag.embeddings) and the next topics, plus their streak "
                    "(days in a row with study) and active days in the last 14.",
     "input_schema": _schema({})},
    {"name": "mark_topic", "strict": True,
     "description": "Tick a topic as done (done: true) or untick it (done: false) on the learner's own path. Only tick topics they've "
                    "shown they know. track: ai or english; topic: an id from study_progress such as rag.embeddings.",
     "input_schema": _schema({"track": {"type": "string", "enum": [t["id"] for t in TRACKS]}, "topic": {"type": "string"},
                              "done": {"type": "boolean"}})},
]

def _today(day=None):
    """The user's local date if the page sent a plausible one, otherwise today in UTC."""
    utc = datetime.now(timezone.utc).date()
    try: d = date.fromisoformat(day) if day else utc
    except ValueError: d = utc
    return d if abs((d - utc).days) <= 1 else utc

def _find(track, topic):
    """(topic title, module title); LookupError with a hint if either is unknown."""
    if track not in TOPICS: raise LookupError(f"Unknown track {track!r}: use ai or english.")
    if topic not in TOPICS[track]: raise LookupError(f"Unknown topic {topic!r} on the {track} track. Call study_progress for topic ids.")
    return TOPICS[track][topic]

class TopicIn(BaseModel):
    track: str
    topic: str
    done: bool = True
    today: str | None = None

class ProfileIn(BaseModel):
    track: str
    level: str = ""
    goal: str = ""
    pace: int | None = None  # hours a week; None keeps what's saved

class StepIn(BaseModel):
    track: str
    step: str
    done: bool = True
    today: str | None = None

class MaterialIn(BaseModel):
    kind: str  # file (Scout Drive) or source (owner/name:path on the Source hub)
    id: str

class StudyChatIn(BaseModel):
    agent_id: int
    track: str
    topic: str | None = None
    message: str
    model: str | None = None
    effort: str = "medium"
    today: str | None = None
    attachments: list[MaterialIn] = []

class PracticeIn(BaseModel):
    track: str
    drill: str
    kind: str
    topic: str | None = None
    agent_id: int | None = None  # report: the tutor the voice session was with
    text: str = ""               # the learner's text, code or answer
    task: str = ""               # the writing task or coding exercise the text answers
    question: str = ""           # grade: the question and its reference answers
    answers: list[str] = []
    model: str | None = None
    step: str | None = None      # a roadmap step: the drill covers the whole step (testing out)
    material: list[MaterialIn] = []  # Drive files or Source code the drill is built from
    lab: str | None = None       # lab_task: the environment, terminal, python or sql

class LabTurn(BaseModel):
    role: str  # user or assistant
    text: str

class LabPromptIn(BaseModel):
    system: str = ""
    turns: list[LabTurn]
    json_schema: str = ""  # a JSON schema the answer must match; empty for text
    model: str | None = None
    effort: str = "low"

class DoneIn(BaseModel):
    track: str
    drill: str
    topic: str | None = None
    score: float | None = None
    total: float | None = None
    today: str | None = None

class CardIn(BaseModel):
    front: str
    ipa: str = ""
    back: str = ""
    example: str = ""
    extra: str = ""

class CardsIn(BaseModel):
    track: str
    cards: list[CardIn]
    today: str | None = None

class ReviewIn(BaseModel):
    grade: str
    today: str | None = None

def _questions(items):
    """Questions the page can run: a prompt, and for multiple choice at least two options and a valid answer index."""
    out = []
    for q in items or []:
        if not isinstance(q, dict) or not str(q.get("prompt") or "").strip() or q.get("type") not in ("choice", "gap", "transform", "short"): continue
        if q["type"] == "choice":
            q["options"] = [str(o) for o in q.get("options") or []][:6]
            if len(q["options"]) < 2 or not isinstance(q.get("correct"), int) or not 0 <= q["correct"] < len(q["options"]): continue
        out.append(q)
    return out[:10]

class Study:
    def __init__(self, db, hub=None):
        self.db, self.hub, self.tools = db, hub, TOOLS
        db.q("CREATE TABLE IF NOT EXISTS study_topics (user_id INTEGER, track TEXT, topic TEXT, done REAL, PRIMARY KEY (user_id, track, topic))")
        db.q("""CREATE TABLE IF NOT EXISTS study_profile (
                  user_id INTEGER, track TEXT, level TEXT, goal TEXT, updated REAL, PRIMARY KEY (user_id, track))""")
        if "pace" not in {c["name"] for c in db.q("PRAGMA table_info(study_profile)")}: db.q("ALTER TABLE study_profile ADD COLUMN pace INTEGER")
        db.q("CREATE TABLE IF NOT EXISTS study_days (user_id INTEGER, day TEXT, actions INTEGER, PRIMARY KEY (user_id, day))")
        db.q("""CREATE TABLE IF NOT EXISTS study_chats (
                  user_id INTEGER, agent_id INTEGER, track TEXT, conversation_id TEXT, PRIMARY KEY (user_id, agent_id, track))""")
        db.q("""CREATE TABLE IF NOT EXISTS study_cards (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, track TEXT, front TEXT, ipa TEXT, back TEXT, example TEXT, extra TEXT,
                  ease REAL DEFAULT 2.5, interval INTEGER DEFAULT 0, reps INTEGER DEFAULT 0, due TEXT, created REAL, reviewed REAL)""")
        db.q("CREATE INDEX IF NOT EXISTS study_cards_due ON study_cards (user_id, track, due)")
        db.q("""CREATE TABLE IF NOT EXISTS study_sessions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, track TEXT, drill TEXT, topic TEXT, score REAL, total REAL, created REAL)""")

    @staticmethod
    def _track(track):
        if track not in BY_ID: raise HTTPException(400, "Unknown track.")
        return BY_ID[track]

    # ---------- progress ----------
    def _done(self, me):
        out = {t["id"]: {} for t in TRACKS}
        for r in self.db.q("SELECT track, topic, done FROM study_topics WHERE user_id=?", (me["id"],)):
            if r["topic"] in TOPICS.get(r["track"], {}): out[r["track"]][r["topic"]] = r["done"]  # topics dropped from the path don't count
        return out

    def _profiles(self, me):
        return {r["track"]: r for r in self.db.q("SELECT track, level, goal, pace FROM study_profile WHERE user_id=?", (me["id"],))}

    def touch(self, me, day=None):
        """Counts today towards the streak."""
        d = _today(day).isoformat()
        self.db.q("INSERT OR IGNORE INTO study_days VALUES (?,?,0)", (me["id"], d))
        self.db.q("UPDATE study_days SET actions=actions+1 WHERE user_id=? AND day=?", (me["id"], d))

    def activity(self, me, day=None):
        today = _today(day)
        rows = {r["day"]: r["actions"] for r in self.db.q("SELECT day, actions FROM study_days WHERE user_id=? AND day>=?",
                                                          (me["id"], (today - timedelta(days=STREAK_WINDOW)).isoformat()))}
        d, streak = today if today.isoformat() in rows else today - timedelta(days=1), 0  # not yet today: yesterday's streak still stands
        while d.isoformat() in rows: streak += 1; d -= timedelta(days=1)
        days = [(today - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
        return {"streak": streak, "today": today.isoformat() in rows, "days": [{"day": x, "n": rows.get(x, 0)} for x in days],
                "active_14": sum(1 for x in days if x in rows)}

    def _summary(self, t, done, prof):
        levels = dict(t["levels"])
        tutor = TUTOR[t["id"]]
        mods = [{"id": m, "title": mt, "tutor": tutor.get(m, tutor["*"]),
                 "topics": [{"id": f"{m}.{k}", "title": title, "done": f"{m}.{k}" in done} for k, title in ts]}
                for m, mt, ts in t["modules"]]
        for m in mods: m["done"], m["total"] = sum(x["done"] for x in m["topics"]), len(m["topics"])
        road = self._roadmap(t, done, prof.get("level") or "")
        # next up: the fast track's next topic, then anything left on the full path
        nxt = next((x for st in road for x in st["topics"] if not x["done"]), None) \
            or next(({**x, "module": m["title"]} for m in mods for x in m["topics"] if not x["done"]), None)
        return {"id": t["id"], "title": t["title"], "icon": t["icon"], "color": t["color"], "blurb": t["blurb"], "levels": t["levels"],
                "level": prof.get("level") or "", "level_label": levels.get(prof.get("level") or ""), "goal": prof.get("goal") or "",
                "pace": prof.get("pace") or DEFAULT_PACE, "paces": PACES,
                "modules": mods, "done": sum(m["done"] for m in mods), "total": sum(m["total"] for m in mods), "next": nxt,
                "drills": [{**d, "topic": self._default_topic(t, d, mods, nxt)} for d in DRILLS[t["id"]]],
                "roadmap": road}

    @staticmethod
    def _roadmap(t, done, level):
        """The fast track with the learner's progress: per step its core and extra topics (ticked or not), and its status on the
        fast track: done (core ticked), current (the first step that isn't), next, or later."""
        promoted, out, seen = set(LEVEL_CORE[t["id"]].get(level, [])), [], False
        for i, st in enumerate(ROADMAP[t["id"]]):
            core = st["topics"] + [x for x in st["extra"] if x in promoted]
            extra = [x for x in st["extra"] if x not in promoted]
            row = lambda x: {"id": x, "title": TOPICS[t["id"]][x][0], "module": TOPICS[t["id"]][x][1], "done": x in done}
            s = {**{k: st[k] for k in ("id", "title", "outcome", "hours", "drill", "build")}, "n": i + 1,
                 "topics": [row(x) for x in core], "extra": [row(x) for x in extra]}
            s["done"], s["total"] = sum(x["done"] for x in s["topics"]), len(s["topics"])
            s["status"] = "done" if s["done"] == s["total"] else "later" if seen else "current"
            if s["status"] == "current": seen = True
            out.append(s)
        cur = next((i for i, s in enumerate(out) if s["status"] == "current"), None)
        if cur is not None and cur + 1 < len(out) and out[cur + 1]["status"] == "later": out[cur + 1]["status"] = "next"
        return out

    @staticmethod
    def _default_topic(t, d, mods, nxt):
        """What a drill is about when the learner hasn't picked a topic: the next one on the AI path, or the next one in the
        English module the drill trains; None for open drills (conversations, interviews, the weekly plan)."""
        if d["mode"] == "dialogue" or d["id"] == "plan": return None
        if t["id"] == "ai": return nxt and {"id": nxt["id"], "title": nxt["title"]}
        mod = {"grammar": "grammar", "vocab": "vocab", "pron": "pron", "listen": "listen", "write": "writing"}.get(d["id"])
        m = next((m for m in mods if m["id"] == mod), None)
        if not m: return None
        x = next((x for x in m["topics"] if not x["done"]), m["topics"][0])
        return {"id": x["id"], "title": x["title"]}

    def tracks(self, me):
        done, profs = self._done(me), self._profiles(me)
        return [self._summary(t, done[t["id"]], profs.get(t["id"], {})) for t in TRACKS]

    def view(self, me, day=None):
        tracks = self.tracks(me)
        for t in tracks: t["deck"], t["recent"] = self._deck_counts(me, t["id"], day), self._recent(me, t["id"])
        return {"tracks": tracks, "activity": self.activity(me, day), "agents": self._agents(me), "agents_enabled": self.agents_on(me),
                "team": [{k: t[k] for k in ("id", "name", "role", "track", "icon", "color", "description")} for t in STUDY],
                "lab": {"runtime": PYODIDE, "home": f"/home/u{int(me['id'])}"}}  # the Lab's Pyodide, and ~ (its files are kept per user)

    def set_topic(self, me, track, topic, done, day=None, count=True):
        try: _find(track, topic)
        except LookupError as e: raise HTTPException(400, str(e))
        if done:
            self.db.q("INSERT OR IGNORE INTO study_topics VALUES (?,?,?,?)", (me["id"], track, topic, time.time()))
            if count: self.touch(me, day)
        else:
            self.db.q("DELETE FROM study_topics WHERE user_id=? AND track=? AND topic=?", (me["id"], track, topic))

    def set_profile(self, me, p: ProfileIn):
        t = self._track(p.track)
        if p.level and p.level not in dict(t["levels"]): raise HTTPException(400, "Unknown level.")
        goal = " ".join(p.goal.split())[:MAX_GOAL]
        if p.pace is not None and p.pace not in PACES: raise HTTPException(400, "Pick a pace from the list.")
        pace = p.pace if p.pace is not None else (self._profiles(me).get(t["id"]) or {}).get("pace")
        self.db.q("INSERT OR REPLACE INTO study_profile (user_id, track, level, goal, updated, pace) VALUES (?,?,?,?,?,?)",
                  (me["id"], t["id"], p.level, goal, time.time(), pace))

    def set_step(self, me, p: StepIn):
        """Ticks (or unticks) every core topic of a roadmap step: testing out of it, or finishing it in one go."""
        t = self._track(p.track)
        s = next((x for x in self.tracks(me) if x["id"] == t["id"]), None)
        st = next((x for x in s["roadmap"] if x["id"] == p.step), None)
        if not st: raise HTTPException(400, "Unknown step.")
        for x in st["topics"]: self.set_topic(me, t["id"], x["id"], p.done, p.today, count=False)
        if p.done: self.touch(me, p.today)

    # ---------- the study agents' tools ----------
    def progress(self, me):
        """study_progress: every track as compact checklists the model can read at a glance."""
        act = self.activity(me)
        out = []
        for s in self.tracks(me):
            out.append({"track": s["id"], "title": s["title"], "level": s["level_label"] or "not set", "goal": s["goal"] or "not set",
                        "done": f"{s['done']}/{s['total']}",
                        "modules": [{"module": m["title"], "done": f"{m['done']}/{m['total']}",
                                     "topics": [f"[{'x' if x['done'] else ' '}] {x['id']}: {x['title']}" for x in m["topics"]]} for m in s["modules"]],
                        "next_topics": [f"{x['id']}: {x['title']}" for m in s["modules"] for x in m["topics"] if not x["done"]][:3]})
        return {"streak_days": act["streak"], "studied_today": act["today"], "active_days_last_14": act["active_14"], "tracks": out}

    def tool(self, me, name, args):
        if name == "study_progress": return self.progress(me)
        if name == "mark_topic":
            track, topic, done = args.get("track"), (args.get("topic") or "").strip(), args.get("done", True) is not False
            title, module = _find(track, topic)
            self.set_topic(me, track, topic, done, count=False)  # the chat itself already counts the day
            s = next(x for x in self.tracks(me) if x["id"] == track)
            return {"ok": True, "topic": topic, "title": title, "module": module, "done": done, "track_progress": f"{s['done']}/{s['total']}"}
        raise KeyError(name)

    # ---------- the study team and its chats ----------
    def agents_on(self, me):
        if not self.hub: return False
        try: self.hub.gate(me); return True
        except HTTPException: return False

    def _gate(self, me):
        if not self.hub: raise HTTPException(404, "Agents aren't available on this server.")
        self.hub.gate(me)

    def _agents(self, me):
        """Study agents the user can use: the team in template order, then any others; each with the track it teaches."""
        if not self.agents_on(me): return []
        lists, tracks = self.hub.list(me), {(t["name"], t["role"]): (i, t) for i, t in enumerate(STUDY)}
        seen, out = set(), []
        for a in lists["mine"] + lists["shared"] + lists["from_directory"]:
            if a["kind"] != "study" or a["id"] in seen: continue
            seen.add(a["id"])
            i, t = tracks.get((a["name"], a["role"]), (len(STUDY), {}))
            out.append({**a, "track": t.get("track", "both"), "template": t.get("id"), "order": i})
        return sorted(out, key=lambda a: (a["order"], a["id"]))

    def add_team(self, me, day=None):
        self._gate(me)
        ids, made = self.hub.create_study_team(me)
        return {**self.view(me, day), "team_result": {"created": made, "total": len(ids)}}

    def _conv(self, me, aid, track):
        r = self.db.q("SELECT conversation_id FROM study_chats WHERE user_id=? AND agent_id=? AND track=?", (me["id"], aid, track), one=True)
        return r and r["conversation_id"]

    def chat_view(self, me, aid, track):
        self._gate(me); self._track(track)
        cid = self._conv(me, aid, track)
        if not cid: return {"id": None, "items": []}
        try: return self.hub.view(me, aid, cid)
        except HTTPException:  # the conversation went away with its agent
            self.db.q("DELETE FROM study_chats WHERE user_id=? AND agent_id=? AND track=?", (me["id"], aid, track))
            return {"id": None, "items": []}

    def _context(self, me, t, topic=None):
        s = next(x for x in self.tracks(me) if x["id"] == t["id"])
        text = (f"This chat is open in the Study tab on the {t['title']} track. The learner's level: "
                f"{s['level_label'] or 'not set yet (ask, and suggest they set it at the top of the track)'}. Their goal: "
                f"{s['goal'] or 'not set yet'}. Progress on this track: {s['done']} of {s['total']} topics ticked"
                + (f"; next on the path: {s['next']['title']} ({s['next']['id']})." if s["next"] else "; the whole path is ticked.")
                + self._fast(s))
        if topic:
            title, module = TOPICS[t["id"]][topic]
            done = any(x["id"] == topic and x["done"] for m in s["modules"] for x in m["topics"])
            text += (f" They picked this topic to work on now: \"{title}\" (module {module}, id {topic}), "
                     f"{'already ticked as done, so review or go deeper' if done else 'not ticked yet'}.")
        return text

    @staticmethod
    def _fast(s):
        """Where the learner is on the fast track and how much time they have, for tutors and drills."""
        cur = next((x for x in s["roadmap"] if x["status"] == "current"), None)
        text = f" They follow the fast track (the path re-ordered into {len(s['roadmap'])} steps to reach a high level quickly) at about {s['pace']} hours a week"
        if not cur: return text + ", and every step is done: push them to expert level with harder work."
        left = [x["title"] for x in cur["topics"] if not x["done"]]
        return (text + f". Current step {cur['n']}: {cur['title']} ({cur['outcome']}); topics left in it: {'; '.join(left)}. "
                f"Its build task: {cur['build']} Keep them moving: short explanations, then make them do something.")

    def chat(self, me, c: StudyChatIn):
        self._gate(me)
        t = self._track(c.track)
        a = self.hub._usable(c.agent_id, me)
        if a["kind"] != "study":
            raise HTTPException(400, f"{a['name']} isn't a study agent. Create the study team, or turn on Study agent in the agent's editor.")
        if c.topic:
            try: _find(t["id"], c.topic)
            except LookupError as e: raise HTTPException(400, str(e))
        out = self.hub.chat(me, c.agent_id, self._conv(me, c.agent_id, t["id"]), c.message, c.model, c.effort,
                            context=self._context(me, t, c.topic), attachments=c.attachments)
        if out.get("id"):
            self.db.q("INSERT OR REPLACE INTO study_chats VALUES (?,?,?,?)", (me["id"], c.agent_id, t["id"], out["id"]))
        if not out.get("error"): self.touch(me, c.today)
        return out

    def new_chat(self, me, aid, track):
        self._gate(me); self._track(track)
        self.db.q("DELETE FROM study_chats WHERE user_id=? AND agent_id=? AND track=?", (me["id"], aid, track))
        return {"id": None, "items": []}

    # ---------- practice ----------
    def _drill(self, track, drill):
        d = next((x for x in DRILLS[track] if x["id"] == drill), None)
        if not d: raise HTTPException(400, "Unknown drill.")
        return d

    def _tutor(self, me, template):
        return next((a for a in self._agents(me) if a["template"] == template), None)

    def _learner(self, me, s, topic, tutor):
        """What the model knows about the learner for one drill: track, level, goal, progress, the topic, and what the drill's
        tutor remembers about them."""
        nxt = [x["title"] for m in s["modules"] for x in m["topics"] if not x["done"]][:3]
        lines = [f"Track: {s['title']}. Level: {s['level_label'] or 'not set'}. Goal: {s['goal'] or 'not set'}.",
                 f"Progress: {s['done']} of {s['total']} topics ticked. Next topics: {'; '.join(nxt) or 'none, the path is done'}." + self._fast(s)]
        if topic: lines.append(f"Topic for this practice: {topic[0]} (module {topic[1]}).")
        if tutor:
            mem = self.db.q("SELECT text FROM agent_memory WHERE agent_id=? AND user_id=? ORDER BY created DESC LIMIT 30", (tutor["id"], me["id"]))
            if mem: lines.append(f"What their tutor {tutor['name']} remembers about them:\n" + "\n".join(f"- {m['text']}" for m in mem))
        return "\n".join(lines)

    def practice(self, me, p: PracticeIn):
        """Asks the model for one piece of a drill: the exercise itself, a grade for a free answer, a correction, a review,
        or the report at the end of a voice session."""
        self._gate(me)
        t = self._track(p.track)
        d = self._drill(t["id"], p.drill)
        if p.kind not in practice.KINDS[d["mode"]]: raise HTTPException(400, "That drill doesn't do that.")
        s = next(x for x in self.tracks(me) if x["id"] == t["id"])
        if p.step:  # the whole roadmap step: its core topics as one topic
            st = next((x for x in s["roadmap"] if x["id"] == p.step), None)
            if not st: raise HTTPException(400, "Unknown step.")
            tid, topic = None, (f"{st['title']}, covering: " + "; ".join(x["title"] for x in st["topics"]), f"fast track step {st['n']}")
        else:
            tid = p.topic or (self._default_topic(t, d, s["modules"], s["next"]) or {}).get("id")
            try: topic = _find(t["id"], tid) if tid else None
            except LookupError as e: raise HTTPException(400, str(e))
        material, _ = self.hub.material(me, p.material) if p.material else ([], [])
        text = p.text.strip()
        limit = practice.LIMITS.get("grade" if p.kind == "grade" else d["mode"], 0)
        if p.kind in ("writing", "code", "grade"):
            if not text: raise HTTPException(400, "Write something first." if p.kind != "code" else "Paste or write some code first.")
            if len(text) > limit: raise HTTPException(400, f"That's too long: keep it under {limit:,} characters.")
        tutor = self._tutor(me, d["agent"])
        data = {"text": text, "task": p.task.strip()[:3000], "question": p.question.strip()[:2000], "answers": [a[:500] for a in p.answers[:8]], "step": bool(p.step)}
        if p.kind == "grade" and not data["question"]: raise HTTPException(400, "Missing the question.")
        if p.kind == "lab_task":
            if p.lab not in practice.LABS: raise HTTPException(400, "Pick the terminal, Python or SQL for the task.")
            data["lab"] = p.lab
        if p.kind == "cards":
            fronts = [r["front"] for r in self.db.q("SELECT front FROM study_cards WHERE user_id=? AND track=? ORDER BY id DESC LIMIT 150", (me["id"], t["id"]))]
            data["avoid"] = "; ".join(fronts)
        if p.kind == "report":
            a = self.hub._usable(p.agent_id, me) if p.agent_id else None
            cid = a and self._conv(me, a["id"], t["id"])
            if not cid: raise HTTPException(400, "Start the session and say something first.")
            _, messages = self.hub._load(a["id"], cid, me)
            data.update(transcript=practice.transcript(messages), drill=d["title"], tutor=a["name"], interview=d["id"] in ("design", "interview"))
            if "Learner:" not in data["transcript"]: raise HTTPException(400, "Say something first: the report is about what you said.")
            tutor = a
        used = [0]
        ask = practice.prompt(p.kind, t["id"], d["id"], self._learner(me, s, topic, tutor), topic and topic[0], data) + practice.material(p.kind, material)
        try:
            out = self.hub.llm.structured(p.model, practice.SYSTEM, ask, practice.SCHEMAS[p.kind], p.kind, on_usage=lambda n: used.__setitem__(0, used[0] + n))
        except LLMError as e:
            raise HTTPException(502, str(e))
        finally:
            self.hub.log_usage(me, "practice", used[0], tutor and tutor["id"], self.hub.model_of(p.model))
        if not isinstance(out, dict): raise HTTPException(502, "The model's answer was incomplete. Try again or pick another model.")
        if p.kind == "lesson": out["check"] = _questions(out.get("check"))
        if p.kind == "quiz":
            out["items"] = _questions(out.get("items"))
            if not out["items"]: raise HTTPException(502, "The model didn't write usable questions. Try again or pick another model.")
        if p.kind == "lab_task": out = self._lab_task(out, p.lab)
        if tutor: self.db.q("UPDATE custom_agents SET tokens=tokens+?, last_activity=? WHERE id=?", (used[0], time.time(), tutor["id"]))
        return {"kind": p.kind, "data": out, "tokens": used[0], "topic": tid, "tutor": tutor and tutor["name"]}

    @staticmethod
    def _lab_task(out, lab):
        """A lab task the page can set up: files with safe paths, checks, and a file to open first."""
        out.update(env=lab, files=practice.lab_files(out.get("files")), solution=practice.lab_files(out.get("solution")),
                   commands=[str(c).strip()[:500] for c in out.get("commands") or [] if str(c).strip()][:20],
                   hints=[str(h) for h in out.get("hints") or []][:4], tests=str(out.get("tests") or "")[:20000])
        paths = [f["path"] for f in out["files"]]
        if not paths or not out["tests"].strip() or (lab == "sql" and "setup.sql" not in paths):
            raise HTTPException(502, "The model didn't write a usable task. Try again or pick another model.")
        if out.get("main") not in paths: out["main"] = next((x for x in paths if x.endswith((".py", ".sql"))), paths[0])
        return out

    # ---------- the Lab's prompt playground ----------
    def lab_prompt(self, me, p: LabPromptIn):
        """One model call with the learner's system prompt and turns, answered as text or as JSON matching their schema."""
        self._gate(me)
        turns = [(t.role, t.text.strip()) for t in p.turns if t.text.strip()]
        if any(r not in ("user", "assistant") for r, _ in turns): raise HTTPException(400, "Turns are from the user or the assistant.")
        if not turns or turns[0][0] != "user" or turns[-1][0] != "user": raise HTTPException(400, "Start and end with a user message.")
        if len(turns) > LAB_TURNS: raise HTTPException(400, f"Keep it to {LAB_TURNS} turns.")
        if len(p.system) > LAB_SYSTEM or sum(len(t) for _, t in turns) > LAB_TEXT:
            raise HTTPException(400, f"That's too long: up to {LAB_SYSTEM:,} characters of system prompt and {LAB_TEXT:,} of turns.")
        msgs = []  # turns from the same side in a row are joined: the APIs expect them to alternate
        for r, t in turns:
            if msgs and msgs[-1]["role"] == r: msgs[-1]["content"] += "\n\n" + t
            else: msgs.append({"role": r, "content": t})
        schema = None
        if p.json_schema.strip():
            try: schema = json.loads(p.json_schema)
            except ValueError as e: raise HTTPException(400, f"The JSON schema isn't valid JSON: {e}")
            if not isinstance(schema, dict) or schema.get("type") != "object":
                raise HTTPException(400, 'The schema must describe an object: {"type": "object", "properties": {…}}.')
        system = p.system.strip() or "You are a helpful assistant."  # providers need a non-empty system prompt
        used, model, t0 = [0], self.hub.model_of(p.model), time.time()
        try:
            if schema:
                data = self.hub.llm.structured(p.model, system, None, schema, "playground", on_usage=lambda n: used.__setitem__(0, used[0] + n),
                                               effort=p.effort, messages=msgs)
                text, stop = json.dumps(data, indent=2, ensure_ascii=False), "end_turn"
            else:
                call, model = self.hub.llm.completer(p.model, p.effort)
                blocks, stop, used[0] = call(system, [], msgs)
                text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except LLMError as e:
            raise HTTPException(502, str(e))
        finally:
            self.hub.log_usage(me, "lab", used[0], None, model)
        return {"text": text, "stop": stop, "tokens": used[0], "model": model, "seconds": round(time.time() - t0, 2), "json": bool(schema)}

    def done(self, me, p: DoneIn):
        """A finished drill: listed as recent practice, and it counts towards the streak."""
        t = self._track(p.track)
        self._drill(t["id"], p.drill)
        if p.topic:
            try: _find(t["id"], p.topic)
            except LookupError as e: raise HTTPException(400, str(e))
        score = total = None
        if p.total and p.total > 0 and p.score is not None: total, score = round(p.total, 1), round(max(0, min(p.score, p.total)), 1)
        self.db.q("INSERT INTO study_sessions (user_id, track, drill, topic, score, total, created) VALUES (?,?,?,?,?,?,?)",
                  (me["id"], t["id"], p.drill, p.topic, score, total, time.time()))
        self.touch(me, p.today)
        return {"recent": self._recent(me, t["id"]), "activity": self.activity(me, p.today)}

    def _recent(self, me, track):
        titles = {d["id"]: d["title"] for d in DRILLS[track]}
        return [{"drill": r["drill"], "title": titles.get(r["drill"], r["drill"]), "topic": TOPICS[track].get(r["topic"], ("",))[0] if r["topic"] else "",
                 "score": r["score"], "total": r["total"], "created": r["created"]}
                for r in self.db.q("SELECT * FROM study_sessions WHERE user_id=? AND track=? ORDER BY id DESC LIMIT ?", (me["id"], track, RECENT))]

    # ---------- flashcards: a deck per track, reviewed with spaced repetition ----------
    _CARD = "id, front, ipa, back, example, extra, ease, interval, reps, due"

    def _deck_counts(self, me, track, day=None):
        r = self.db.q("SELECT COUNT(*) total, SUM(due<=?) due FROM study_cards WHERE user_id=? AND track=?", (_today(day).isoformat(), me["id"], track), one=True)
        return {"total": r["total"] or 0, "due": r["due"] or 0}

    def deck(self, me, track, day=None):
        self._track(track)
        due = self.db.q(f"SELECT {self._CARD} FROM study_cards WHERE user_id=? AND track=? AND due<=? ORDER BY due, id LIMIT 50",
                        (me["id"], track, _today(day).isoformat()))
        cards = self.db.q(f"SELECT {self._CARD} FROM study_cards WHERE user_id=? AND track=? ORDER BY id DESC LIMIT 300", (me["id"], track))
        return {**self._deck_counts(me, track, day), "queue": due, "cards": cards}

    def add_cards(self, me, c: CardsIn):
        t = self._track(c.track)
        have = {r["front"].lower() for r in self.db.q("SELECT front FROM study_cards WHERE user_id=? AND track=?", (me["id"], t["id"]))}
        added = 0
        for x in c.cards[:20]:
            front = " ".join(x.front.split())[:120]
            if not front or front.lower() in have: continue
            if len(have) >= MAX_CARDS: raise HTTPException(400, f"A deck holds up to {MAX_CARDS:,} cards. Delete some first.")
            self.db.q("INSERT INTO study_cards (user_id, track, front, ipa, back, example, extra, due, created) VALUES (?,?,?,?,?,?,?,?,?)",
                      (me["id"], t["id"], front, x.ipa.strip()[:80], x.back.strip()[:500], x.example.strip()[:500], x.extra.strip()[:500],
                       _today(c.today).isoformat(), time.time()))
            have.add(front.lower()); added += 1
        return {"added": added, **self.deck(me, t["id"], c.today)}

    def _card(self, me, cid):
        r = self.db.q("SELECT * FROM study_cards WHERE id=? AND user_id=?", (cid, me["id"]), one=True)
        if not r: raise HTTPException(404, "Card not found.")
        return r

    def review(self, me, cid, r: ReviewIn):
        card = self._card(me, cid)
        if r.grade not in practice.GRADES: raise HTTPException(400, "Grade a card again, hard, good or easy.")
        ease, iv, reps, due = practice.schedule(card, r.grade, _today(r.today))
        self.db.q("UPDATE study_cards SET ease=?, interval=?, reps=?, due=?, reviewed=? WHERE id=?", (ease, iv, reps, due, time.time(), cid))
        self.touch(me, r.today)
        return {"id": cid, "interval": iv, "due": due, **self._deck_counts(me, card["track"], r.today)}

    def delete_card(self, me, cid):
        card = self._card(me, cid)
        self.db.q("DELETE FROM study_cards WHERE id=?", (cid,))
        return self._deck_counts(me, card["track"])

def build(db, require, hub=None, ready=None):
    r = APIRouter(prefix="/api/study")
    st = Study(db, hub)
    r.state = {"study": st}

    @r.get("")
    def view(req: Request, today: str | None = None):
        return st.view(require(req), today)

    @r.put("/topics")
    def topic(t: TopicIn, req: Request):
        me = require(req)
        st.set_topic(me, t.track, t.topic, t.done, t.today)
        return st.view(me, t.today)

    @r.put("/profile")
    def profile(p: ProfileIn, req: Request, today: str | None = None):
        me = require(req)
        st.set_profile(me, p)
        return st.view(me, today)

    @r.post("/team")
    def team(req: Request, today: str | None = None):
        return st.add_team(require(req), today)

    @r.get("/chat")
    def chat_view(agent_id: int, track: str, req: Request):
        return st.chat_view(require(req), agent_id, track)

    @r.put("/step")
    def step(b: StepIn, req: Request):
        me = require(req)
        st.set_step(me, b)
        return st.view(me, b.today)

    @r.post("/chat")
    def chat(c: StudyChatIn, req: Request):
        me = require(req)
        if ready: ready(c.model)
        return st.chat(me, c)

    @r.delete("/chat")
    def new_chat(agent_id: int, track: str, req: Request):
        return st.new_chat(require(req), agent_id, track)

    @r.post("/practice")
    def practice_(p: PracticeIn, req: Request):
        me = require(req)
        st._gate(me)
        if ready: ready(p.model)
        return st.practice(me, p)

    @r.post("/lab/prompt")
    def lab_prompt(p: LabPromptIn, req: Request):
        me = require(req)
        st._gate(me)
        if ready: ready(p.model)
        return st.lab_prompt(me, p)

    @r.get("/lab/projects")
    def lab_project_list(req: Request):
        require(req)
        return {"projects": lab_projects.catalog()}

    @r.get("/lab/projects/{pid}")
    def lab_project(pid: str, req: Request):
        require(req)
        p = lab_projects.get(pid)
        if not p: raise HTTPException(404, "That project doesn't exist.")
        return p

    @r.post("/practice/done")
    def practice_done(p: DoneIn, req: Request):
        return st.done(require(req), p)

    @r.get("/cards")
    def cards(track: str, req: Request, today: str | None = None):
        return st.deck(require(req), track, today)

    @r.post("/cards")
    def add_cards(c: CardsIn, req: Request):
        return st.add_cards(require(req), c)

    @r.put("/cards/{cid}")
    def review(cid: int, r: ReviewIn, req: Request):
        return st.review(require(req), cid, r)

    @r.delete("/cards/{cid}")
    def delete_card(cid: int, req: Request):
        return st.delete_card(require(req), cid)

    return r

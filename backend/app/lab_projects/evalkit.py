"""evalkit: an evaluation harness for language models, modeled on EleutherAI's lm-evaluation-harness."""
import json

from ._common import BUILD_WHEEL, block, changelog, gitignore, makefile, pyproject

ONBOARDING = r"""# Welcome to evalkit 👋

**evalkit** is how we decide whether a model or prompt change is better or worse *before* it ships. It's a small evaluation harness modeled on EleutherAI's open-source [lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness), the tool behind many public LLM leaderboards:

- a **task** is a dataset, a prompt template and the metrics to score with;
- the **runner** builds the prompts (with few-shot examples if asked), sends them to the model in one batch, and scores the answers;
- the **regression gate** compares a candidate's scores with the baseline's and fails CI when something got worse.

## Codebase tour

| Path | What's there |
|---|---|
| `evalkit/metrics.py` | answer normalization, `exact_match`, `f1`, and the `METRICS` registry |
| `evalkit/tasks.py` | `Task`, and `load_task()` for the JSON files in `tasks/` |
| `evalkit/models.py` | `LookupModel`: a stand-in for an LLM (the lab has no network) |
| `evalkit/runner.py` | few-shot sampling, prompt building and `evaluate()` |
| `evalkit/compare.py` | the regression gate |
| `evalkit/cli.py` | `python -m evalkit run …` and `python -m evalkit compare …` |
| `tasks/` | `capitals.json` and `arithmetic.json` |
| `models/` | `v1.json` and `v2.json`: the answers two versions of "the model" give |
| `tests/` | `test_smoke.py` now, one file per ticket as you pick them up |

## Your dev loop

```sh
cd ~/projects/evalkit
make                               # lists the targets
make test                          # the whole suite
pytest tests/test_metrics.py -q    # one file, while you work on it
make eval                          # score models v1 and v2 on every task, into results/
make gate                          # the regression gate: v2 against v1
make build                         # dist/evalkit-<version>-py3-none-any.whl
```

Edit in the Lab's **Python** tab (or type `edit evalkit/metrics.py` in the terminal). **Run CI** on a ticket runs its acceptance tests plus everything already merged.

## How we work

- **Every number has a test.** A metric that's slightly off silently changes every decision made with it, so metrics get exact, hand-computed test cases.
- **Runs are deterministic.** Few-shot examples are sampled with a seed: the same command gives the same scores, today and next month.
- **The gate is the contract.** A change that drops a score by more than the allowed noise doesn't merge until someone explains it.
- **One ticket, one pull request**, and CI must be green. Don't edit acceptance tests to pass them: CI runs its own copy.

## Your first week

{tickets}

Welcome aboard!
"""

README = r"""# evalkit

A small harness for evaluating language models on short-answer tasks, modeled on EleutherAI's [lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness). Python 3.11+, no dependencies.

```sh
python -m evalkit run tasks/*.json --model models/v1.json --fewshot 2 -o results/v1.json
python -m evalkit run tasks/*.json --model models/v2.json --fewshot 2 -o results/v2.json
python -m evalkit compare results/v1.json results/v2.json --max-drop 0.02   # exits 1 on a regression
```

New to the codebase? Start with [ONBOARDING.md](ONBOARDING.md).
"""

INIT = r'''"""evalkit: a small harness for evaluating language models on short-answer tasks, modeled on EleutherAI's
lm-evaluation-harness."""
from .metrics import METRICS, exact_match, f1, normalize_answer
from .models import LookupModel
from .tasks import Task, load_task

__version__ = "0.1.0.dev0"
__all__ = ["METRICS", "LookupModel", "Task", "exact_match", "f1", "load_task", "normalize_answer"]
'''

METRICS = (r'''"""Metrics for short answers, SQuAD-style: normalize both strings, then compare them.

METRICS maps a name (as tasks list them) to a function (prediction, gold) -> a score between 0 and 1.
"""
import re
import string
from collections import Counter

_PUNCTUATION = set(string.punctuation)


def normalize_answer(text: str) -> str:
    """Lowercases, removes punctuation and the articles a, an and the, and squeezes whitespace.
    normalize_answer("The  Eiffel Tower!") == "eiffel tower"."""
    text = text.lower()
    text = "".join(ch for ch in text if ch not in _PUNCTUATION)
«articles»
    return " ".join(text.split())


def exact_match(prediction: str, gold: str) -> float:
    """1.0 when the normalized answers are the same, else 0.0."""
    return float(normalize_answer(prediction) == normalize_answer(gold))


def f1(prediction: str, gold: str) -> float:
    """Token-level F1 between the normalized answers: partial credit for the words they share (EK-2)."""
«f1»


METRICS = {"exact_match": exact_match, "f1": f1}
''', {
    "articles": block("EK-1", r'''
    text = re.sub(r"(a|an|the)", " ", text)
''', r'''
    text = re.sub(r"\b(a|an|the)\b", " ", text)
'''),
    "f1": block("EK-2", r'''
    raise NotImplementedError("EK-2: token-level F1")
''', r'''
    pred, ref = normalize_answer(prediction).split(), normalize_answer(gold).split()
    if not pred or not ref:
        return float(pred == ref)
    shared = sum((Counter(pred) & Counter(ref)).values())
    if shared == 0:
        return 0.0
    precision, recall = shared / len(pred), shared / len(ref)
    return 2 * precision * recall / (precision + recall)
'''),
})

TASKS = r'''"""Tasks: a dataset of docs (questions with their answers), a prompt template, and the metrics to score with."""
import json
from dataclasses import dataclass, field


@dataclass
class Task:
    name: str
    docs: list[dict]
    prompt: str                    # a str.format template over a doc's fields: "Q: What is the capital of {country}?\nA:"
    target: str = "answer"         # the doc field that holds the gold answer
    metrics: list[str] = field(default_factory=lambda: ["exact_match"])
    description: str = ""

    def render(self, doc: dict) -> str:
        return self.prompt.format(**doc)

    def gold(self, doc: dict) -> str:
        return str(doc[self.target])


def load_task(path: str) -> Task:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return Task(d["name"], d["docs"], d["prompt"], d.get("target", "answer"), d.get("metrics", ["exact_match"]), d.get("description", ""))
'''

MODELS = r'''"""Models. A real one calls an API; the lab has no network, so LookupModel answers from a table, like a test fixture."""


class LookupModel:
    """Answers the last question of each prompt from a table of {question fragment: answer}, then keeps talking, as a
    model does without a stop sequence: the harness has to cut the answer at the first newline.

    It reads only the prompt's last block (after the last blank line), so few-shot examples don't confuse it.
    calls counts generate() calls: a harness should send all its prompts in one batch.
    """

    def __init__(self, answers: dict[str, str], default: str = "I don't know"):
        self.answers = answers
        self.default = default
        self.calls = 0

    def generate(self, prompts: list[str]) -> list[str]:
        self.calls += 1
        outputs = []
        for prompt in prompts:
            question = prompt.rsplit("\n\n", 1)[-1]
            answer = next((a for key, a in self.answers.items() if key in question), self.default)
            outputs.append(f" {answer}\nQ: And what else would you like to know?")
        return outputs
'''

RUNNER = (r'''"""The runner: few-shot prompts, one batched call to the model, and the scores (EK-3)."""
import random

from .metrics import METRICS


def fewshot_docs(task, index: int, k: int, seed: int = 1234) -> list[dict]:
    """k example docs for doc `index`, never the doc itself, sampled with random.Random(seed + index) (EK-3)."""
«fewshot»


def build_prompt(task, doc: dict, examples: list[dict]) -> str:
    """The examples, each as its prompt, a space, its answer and a blank line; then the doc's prompt (EK-3)."""
«prompt»


def evaluate(model, task, num_fewshot: int = 0, limit: int | None = None, seed: int = 1234) -> dict:
    """Scores the model on the task's first `limit` docs (all of them by default): EK-3 says what it returns."""
«evaluate»
''', {
    "fewshot": block("EK-3", r'''
    raise NotImplementedError("EK-3: sample few-shot examples")
''', r'''
    if k == 0:
        return []
    others = [i for i in range(len(task.docs)) if i != index]
    return [task.docs[i] for i in random.Random(seed + index).sample(others, k)]
'''),
    "prompt": block("EK-3", r'''
    raise NotImplementedError("EK-3: build the prompt")
''', r'''
    shots = "".join(f"{task.render(ex)} {task.gold(ex)}\n\n" for ex in examples)
    return shots + task.render(doc)
'''),
    "evaluate": block("EK-3", r'''
    raise NotImplementedError("EK-3: the evaluation loop")
''', r'''
    docs = task.docs if limit is None else task.docs[:limit]
    if not docs:
        raise ValueError("no docs to evaluate")
    prompts = [build_prompt(task, doc, fewshot_docs(task, i, num_fewshot, seed)) for i, doc in enumerate(docs)]
    outputs = model.generate(prompts)  # one batch
    samples, totals = [], dict.fromkeys(task.metrics, 0.0)
    for doc, prompt, output in zip(docs, prompts, outputs):
        prediction = output.split("\n", 1)[0].strip()
        scores = {name: METRICS[name](prediction, task.gold(doc)) for name in task.metrics}
        for name, score in scores.items():
            totals[name] += score
        samples.append({"prompt": prompt, "prediction": prediction, "gold": task.gold(doc), "scores": scores})
    return {"task": task.name, "n": len(docs), "num_fewshot": num_fewshot,
            "metrics": {name: total / len(docs) for name, total in totals.items()}, "samples": samples}
'''),
})

COMPARE = (r'''"""The regression gate CI runs on every model or prompt change: compare a candidate's scores with the baseline's (EK-4).

Score files are {task: {metric: score}}, as `python -m evalkit run … -o FILE` writes them.
"""

TOLERANCE = 1e-9  # float slack: 0.78 - 0.80 is -0.020000000000000018


def compare(baseline: dict, candidate: dict, max_drop: float = 0.02) -> list[dict]:
    """One row per task and metric of the baseline, sorted: {task, metric, base, cand, delta, ok} (EK-4)."""
«compare»
''', {"compare": block("EK-4", r'''
    raise NotImplementedError("EK-4: the regression gate")
''', r'''
    rows = []
    for task in sorted(baseline):
        for metric in sorted(baseline[task]):
            base = baseline[task][metric]
            cand = candidate.get(task, {}).get(metric)
            delta = None if cand is None else cand - base
            rows.append({"task": task, "metric": metric, "base": base, "cand": cand, "delta": delta,
                         "ok": delta is not None and delta >= -max_drop - TOLERANCE})
    return rows
''')})

CLI = r'''"""python -m evalkit: run tasks against a model, or compare two score files (the regression gate)."""
import argparse
import json
import pathlib

from .compare import compare
from .models import LookupModel
from .runner import evaluate
from .tasks import load_task


def read_json(path: str):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evalkit")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="score a model on tasks")
    run.add_argument("tasks", nargs="+", help="task JSON files")
    run.add_argument("--model", required=True, help="a LookupModel's answers (JSON)")
    run.add_argument("--fewshot", type=int, default=0)
    run.add_argument("--limit", type=int)
    run.add_argument("-o", "--output", help="write {task: {metric: score}} here")
    gate = sub.add_parser("compare", help="the regression gate: a candidate's scores against the baseline's")
    gate.add_argument("baseline")
    gate.add_argument("candidate")
    gate.add_argument("--max-drop", type=float, default=0.02)
    args = parser.parse_args(argv)
    if args.command == "run":
        model, scores = LookupModel(read_json(args.model)), {}
        for path in args.tasks:
            task = load_task(path)
            result = evaluate(model, task, num_fewshot=args.fewshot, limit=args.limit)
            scores[task.name] = result["metrics"]
            print(f"{task.name:<12} n={result['n']:<3} " + "  ".join(f"{m} {v:.3f}" for m, v in result["metrics"].items()))
        if args.output:
            out = pathlib.Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(scores, indent=2) + "\n", encoding="utf-8")
            print(f"wrote {out}")
        return 0
    rows = compare(read_json(args.baseline), read_json(args.candidate), args.max_drop)
    for row in rows:
        cand = "missing" if row["cand"] is None else f"{row['cand']:.3f}"
        delta = "" if row["delta"] is None else f"({row['delta']:+.3f})"
        print(f"{'ok  ' if row['ok'] else 'FAIL'}  {row['task']:<12} {row['metric']:<12} {row['base']:.3f} -> {cand} {delta}")
    bad = sum(not row["ok"] for row in rows)
    print(f"regression gate: {'FAILED' if bad else 'passed'}, {bad} of {len(rows)} scores regressed")
    return 1 if bad else 0
'''

MAIN = r'''from .cli import main

raise SystemExit(main())
'''

COUNTRIES = [("France", "Paris"), ("Japan", "Tokyo"), ("Peru", "Lima"), ("Kenya", "Nairobi"), ("Canada", "Ottawa"),
             ("Australia", "Canberra"), ("Brazil", "Brasília"), ("Egypt", "Cairo"), ("Norway", "Oslo"), ("Vietnam", "Hanoi"),
             ("Mexico", "Mexico City"), ("Greece", "Athens")]
SUMS = [(7, 5), (12, 30), (9, 9), (48, 27), (100, 250), (63, 19), (8, 15), (71, 71), (35, 66), (14, 89)]
CAPITALS = {"name": "capitals", "description": "The capital city of a country.", "prompt": "Q: What is the capital of {country}?\nA:",
            "target": "answer", "metrics": ["exact_match", "f1"], "docs": [{"country": c, "answer": a} for c, a in COUNTRIES]}
ARITHMETIC = {"name": "arithmetic", "description": "Adding two whole numbers.", "prompt": "Q: What is {a} + {b}?\nA:",
              "target": "answer", "metrics": ["exact_match"], "docs": [{"a": a, "b": b, "answer": str(a + b)} for a, b in SUMS]}
WRONG = {"v1": {"Australia": "Sydney", "Brazil": "Rio de Janeiro", "Canada": "Toronto", "Mexico": "Mexico"},
         "v2": {"Brazil": "Brasilia", "Mexico": "Ciudad de México"}}
OFF = {"v1": {(48, 27): 65}, "v2": {(48, 27): 65, (63, 19): 72, (35, 66): 91, (14, 89): 93}}


def answers(version):
    """A model version's answers: mostly right, with the mistakes in WRONG and OFF (v2 knows capitals better and sums worse)."""
    caps = {f"capital of {c}?": WRONG[version].get(c, a) for c, a in COUNTRIES}
    sums = {f"What is {a} + {b}?": str(OFF[version].get((a, b), a + b)) for a, b in SUMS}
    return json.dumps(caps | sums, indent=2, ensure_ascii=False) + "\n"


SMOKE = r'''"""Smoke tests: the package imports, and what already works keeps working."""
import evalkit
from evalkit import LookupModel, load_task


def test_version():
    """The package imports and has a version"""
    assert evalkit.__version__


def test_tasks_load():
    """The bundled tasks load, with their docs and metrics"""
    task = load_task("tasks/capitals.json")
    assert task.name == "capitals" and len(task.docs) >= 10 and "exact_match" in task.metrics
    assert task.render(task.docs[0]) == "Q: What is the capital of France?\nA:"


def test_lookup_model():
    """LookupModel answers the last question, then rambles on"""
    out = LookupModel({"France": "Paris"}).generate(["Q: What is the capital of France?\nA:"])
    assert out[0].startswith(" Paris\n")
'''

T_METRICS = r'''"""EK-1: normalize_answer removes the articles a, an and the as words, never inside words."""
from evalkit import exact_match, normalize_answer


def test_articles_removed():
    """Whole-word articles go, wherever they are"""
    assert normalize_answer("The Eiffel Tower") == "eiffel tower"
    got = normalize_answer("an apple a day")
    assert got == "apple day", f"got {got!r}"


def test_words_containing_articles_survive():
    """'Theory', 'Athens' and 'banana' keep their letters"""
    got = normalize_answer("Theory of Athens and a banana")
    assert got == "theory of athens and banana", f"got {got!r}: only whole-word articles should go"


def test_punctuation_and_spaces():
    """Punctuation goes and whitespace is squeezed"""
    got = normalize_answer("  Paris,   France! ")
    assert got == "paris france", f"got {got!r}"


def test_exact_match():
    """exact_match compares normalized answers"""
    assert exact_match("The Athens.", "athens") == 1.0
    assert exact_match("Athens", "Thens") == 0.0, "Athens and Thens are different answers"
'''

T_F1 = r'''"""EK-2: token-level F1 gives partial credit for overlapping answers."""
import math

from evalkit import METRICS, f1


def test_identical_answers():
    """The same answer after normalizing scores 1.0"""
    assert f1("The Eiffel Tower", "eiffel tower!") == 1.0


def test_partial_overlap():
    """1 shared word of 2 predicted and 3 gold: P = 1/2, R = 1/3, F1 = 0.4"""
    got = f1("Eiffel Paris", "Tower in Eiffel")
    assert math.isclose(got, 0.4), f"got {got}"


def test_repeated_words():
    """A word counts as often as it appears in both answers"""
    got = f1("New new York", "New York")
    assert math.isclose(got, 0.8), f"shared: new once, york once; P = 2/3, R = 1, so F1 = 0.8; got {got}"


def test_no_overlap_and_empty_answers():
    """No shared word scores 0.0; both empty scores 1.0; one empty scores 0.0"""
    assert f1("Paris", "London") == 0.0
    assert f1("", "the") == 1.0, "both answers normalize to nothing: that's a match"
    assert f1("Paris", "") == 0.0


def test_registered():
    """f1 is in METRICS next to exact_match"""
    assert METRICS["f1"] is f1 and "exact_match" in METRICS
'''

T_RUNNER = r'''"""EK-3: few-shot prompts and the evaluation loop."""
import math
import random

from evalkit import LookupModel, Task
from evalkit.runner import build_prompt, evaluate, fewshot_docs

DOCS = [{"country": c, "answer": a} for c, a in [("France", "Paris"), ("Japan", "Tokyo"), ("Peru", "Lima"), ("Kenya", "Nairobi")]]
TASK = Task("capitals", DOCS, "Q: What is the capital of {country}?\nA:", metrics=["exact_match", "f1"])


def test_zero_shot_prompt():
    """With no examples the prompt is the doc's own"""
    assert build_prompt(TASK, DOCS[0], []) == "Q: What is the capital of France?\nA:"


def test_fewshot_prompt():
    """Examples come first: their prompt, a space, the answer and a blank line"""
    got = build_prompt(TASK, DOCS[0], [DOCS[1], DOCS[2]])
    want = ("Q: What is the capital of Japan?\nA: Tokyo\n\n"
            "Q: What is the capital of Peru?\nA: Lima\n\n"
            "Q: What is the capital of France?\nA:")
    assert got == want, f"got:\n{got}"


def test_fewshot_docs_exclude_the_doc():
    """Examples never include the doc being asked about"""
    for i in range(len(DOCS)):
        examples = fewshot_docs(TASK, i, 3, seed=1)
        assert DOCS[i] not in examples and len(examples) == 3, f"doc {i} got {examples}"
    assert fewshot_docs(TASK, 0, 0) == []


def test_fewshot_docs_are_seeded():
    """Sampling is random.Random(seed + index).sample over the other docs' positions"""
    want = [DOCS[j] for j in random.Random(9 + 1).sample([0, 2, 3], 2)]
    assert fewshot_docs(TASK, 1, 2, seed=9) == want, f"got {fewshot_docs(TASK, 1, 2, seed=9)}, expected {want}"


def test_evaluate():
    """One generate() call for all docs, answers cut at the first newline, each metric averaged"""
    model = LookupModel({"France": "Paris", "Japan": "Tokyo", "Peru": "Lima city", "Kenya": "Mombasa"})
    r = evaluate(model, TASK)
    assert model.calls == 1, f"the model was called {model.calls} times: send every prompt in one generate() call"
    got = [s["prediction"] for s in r["samples"]]
    assert got == ["Paris", "Tokyo", "Lima city", "Mombasa"], f"predictions: {got}"
    assert r["task"] == "capitals" and r["n"] == 4
    assert math.isclose(r["metrics"]["exact_match"], 0.5), f"exact_match = {r['metrics']['exact_match']}"
    assert math.isclose(r["metrics"]["f1"], (1 + 1 + 2 / 3 + 0) / 4), f"f1 = {r['metrics']['f1']}"


def test_evaluate_limit_and_fewshot():
    """limit takes the first docs; num_fewshot puts examples in every prompt"""
    model = LookupModel({"France": "Paris", "Japan": "Tokyo"})
    r = evaluate(model, TASK, num_fewshot=2, limit=2, seed=3)
    assert r["n"] == 2 and len(r["samples"]) == 2 and r["num_fewshot"] == 2
    assert all(s["prompt"].count("Q: ") == 3 for s in r["samples"]), "2 examples and the question make 3 Q: lines"
    assert r["metrics"]["exact_match"] == 1.0
'''

T_COMPARE = r'''"""EK-4: the regression gate compares a candidate's scores with the baseline's."""
import json
import os
import tempfile

from evalkit.cli import main
from evalkit.compare import compare

BASE = {"capitals": {"exact_match": 0.80, "f1": 0.85}, "arithmetic": {"exact_match": 0.60}}


def write(folder, name, scores):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(scores, f)
    return path


def test_a_row_per_baseline_score():
    """One row per task and metric of the baseline, sorted"""
    rows = compare(BASE, BASE)
    got = [(r["task"], r["metric"]) for r in rows]
    assert got == [("arithmetic", "exact_match"), ("capitals", "exact_match"), ("capitals", "f1")], f"got {got}"
    assert all(r["ok"] and r["delta"] == 0 for r in rows)


def test_small_drop_ok_big_drop_flagged():
    """A drop up to max_drop is noise; more is a regression"""
    cand = {"capitals": {"exact_match": 0.79, "f1": 0.80}, "arithmetic": {"exact_match": 0.65}}
    rows = {(r["task"], r["metric"]): r for r in compare(BASE, cand, max_drop=0.02)}
    assert rows["capitals", "exact_match"]["ok"], "a 0.01 drop is within max_drop = 0.02"
    assert not rows["capitals", "f1"]["ok"], "a 0.05 drop is a regression"
    up = rows["arithmetic", "exact_match"]
    assert up["ok"] and abs(up["delta"] - 0.05) < 1e-9 and up["base"] == 0.60 and up["cand"] == 0.65, f"got {up}"


def test_exactly_max_drop_is_ok():
    """Dropping exactly max_drop isn't a regression, whatever float rounding says"""
    rows = compare({"t": {"m": 0.80}}, {"t": {"m": 0.78}}, max_drop=0.02)
    assert rows[0]["ok"], f"0.80 to 0.78 is exactly the allowed drop, got {rows[0]}"


def test_missing_scores_fail():
    """A task or metric the candidate didn't report fails the gate"""
    rows = compare(BASE, {"capitals": {"exact_match": 0.9}})
    bad = [(r["task"], r["metric"]) for r in rows if not r["ok"]]
    assert bad == [("arithmetic", "exact_match"), ("capitals", "f1")], f"got {bad}"
    assert all(r["cand"] is None and r["delta"] is None for r in rows if not r["ok"])


def test_cli_exit_code():
    """python -m evalkit compare exits 1 on a regression and 0 otherwise"""
    folder = tempfile.mkdtemp()
    base = write(folder, "base.json", BASE)
    worse = write(folder, "worse.json", {**BASE, "capitals": {"exact_match": 0.5, "f1": 0.85}})
    assert main(["compare", base, base]) == 0
    assert main(["compare", base, worse]) == 1
'''

PROJECT = {
    "id": "evalkit", "name": "evalkit", "package": "evalkit", "like": "EleutherAI's lm-evaluation-harness", "org": "EleutherAI",
    "title": "An LLM evaluation harness",
    "blurb": "Join the team that decides whether a model change ships: fix answer normalization, add token-level F1, build "
             "the few-shot runner and the regression gate CI runs, then ship 0.1.0.",
    "level": "Intermediate", "hours": 3, "skills": ["Metrics", "Few-shot prompts", "Regression gates", "Determinism", "Packaging"],
    "topics": ["evals.datasets", "evals.regress", "found.python"],
    "smoke": SMOKE,
    "files": {
        "README.md": README, "ONBOARDING.md": ONBOARDING, "CHANGELOG.md": changelog("evalkit", "Project scaffolding: tasks, the lookup model and the CLI."),
        "pyproject.toml": pyproject("evalkit", "A small evaluation harness for language models"),
        ".gitignore": gitignore("results/"),
        "Makefile": makefile("evalkit", """
eval:  ## score models v1 and v2 on every task, into results/
    python -m evalkit run tasks/arithmetic.json tasks/capitals.json --model models/v1.json --fewshot 2 -o results/v1.json
    python -m evalkit run tasks/arithmetic.json tasks/capitals.json --model models/v2.json --fewshot 2 -o results/v2.json

gate: eval  ## the regression gate: fails when v2 scores worse than v1
    python -m evalkit compare results/v1.json results/v2.json
""", "results"),
        "evalkit/__init__.py": INIT, "evalkit/__main__.py": MAIN, "evalkit/cli.py": CLI, "evalkit/metrics.py": METRICS,
        "evalkit/tasks.py": TASKS, "evalkit/models.py": MODELS, "evalkit/runner.py": RUNNER, "evalkit/compare.py": COMPARE,
        "tasks/capitals.json": json.dumps(CAPITALS, indent=2, ensure_ascii=False), "tasks/arithmetic.json": json.dumps(ARITHMETIC, indent=2),
        "models/v1.json": answers("v1"), "models/v2.json": answers("v2"),
        "scripts/build_wheel.py": BUILD_WHEEL,
    },
    "tickets": [
        {"id": "EK-1", "kind": "good first issue", "title": "normalize_answer eats letters inside words", "estimate": 15, "topic": "evals.regress",
         "touch": ["evalkit/metrics.py"], "test_path": "tests/test_metrics.py", "tests": T_METRICS,
         "body": r"""**Reported by** the research team · **Labels** `bug` `good first issue` `metrics`

> Our exact-match scores on capitals look too good. "Athens" and "Thens" both count as right?!

`normalize_answer` should do what the official SQuAD evaluation script does: lowercase, remove punctuation, remove the **articles** "a", "an" and "the", and squeeze whitespace. But it removes those letters *anywhere*: "Athens" becomes "thens", "Paris" becomes "p ris", "theory" becomes "ory".

Fix it so only whole-word articles go: `normalize_answer("Theory of Athens and a banana")` should be `"theory of athens and banana"`.

**Where:** `normalize_answer` in `evalkit/metrics.py`. **Done when** `tests/test_metrics.py` passes (`pytest tests/test_metrics.py -q`) and **Run CI** is green.
""",
         "hints": ["Try `re.sub(r\"(a|an|the)\", \"_\", \"banana\")` in the Python console: the pattern matches inside words.",
                   "`\\b` matches at a word boundary: `r\"\\b(a|an|the)\\b\"`."]},
        {"id": "EK-2", "kind": "feature", "title": "Token-level F1 metric", "estimate": 30, "topic": "evals.regress",
         "touch": ["evalkit/metrics.py"], "test_path": "tests/test_f1.py", "tests": T_F1,
         "body": r"""**Labels** `feature` `metrics` · **Needs** EK-1

Exact match is all or nothing: "Lima city" for "Lima" scores 0. Implement **token-level F1**, the SQuAD metric that gives partial credit, in `evalkit/metrics.py`:

1. normalize both answers and split them into words;
2. count the words they share as a multiset: a word counts as many times as it appears in **both** (`Counter(pred) & Counter(gold)`);
3. precision = shared ÷ predicted words, recall = shared ÷ gold words, F1 = 2·P·R ÷ (P + R); no shared word scores 0;
4. if either answer has no words left after normalizing, F1 is 1.0 when both are empty and 0.0 otherwise.

`f1("Eiffel Paris", "Tower in Eiffel")`: 1 shared word, P = 1/2, R = 1/3, so F1 = **0.4**.

`f1` is registered in `METRICS` already, so tasks can ask for it by name. **Done when** `tests/test_f1.py` passes and CI is green.
""",
         "hints": ["`sum((Counter(a) & Counter(b)).values())` is the number of shared words.",
                   "Handle the empty answers first, before you divide by anything."]},
        {"id": "EK-3", "kind": "feature", "title": "Few-shot runner", "estimate": 45, "topic": "evals.datasets",
         "touch": ["evalkit/runner.py"], "test_path": "tests/test_runner.py", "tests": T_RUNNER,
         "body": r"""**Labels** `feature` · **Needs** EK-2

The runner in `evalkit/runner.py` is stubbed. Implement it the way lm-evaluation-harness runs few-shot evaluations:

- `fewshot_docs(task, index, k, seed=1234)`: `k` example docs for doc `index`, never the doc itself. Sample with `random.Random(seed + index).sample(…, k)` over the **positions** of the other docs (in order), and map them back to docs. `k = 0` gives `[]`.
- `build_prompt(task, doc, examples)`: each example as `task.render(example) + " " + task.gold(example) + "\n\n"`, then `task.render(doc)`.
- `evaluate(model, task, num_fewshot=0, limit=None, seed=1234)`:
  - take the first `limit` docs (all of them when `None`); few-shot examples come from **all** the task's docs;
  - call `model.generate(prompts)` **once**, with every prompt: models are much faster in batches;
  - a model keeps talking after its answer, so the prediction is its output **up to the first newline**, stripped;
  - score each prediction with every metric in `task.metrics`: `METRICS[name](prediction, gold)`;
  - return `{"task": task.name, "n": …, "num_fewshot": …, "metrics": {name: mean score}, "samples": [{"prompt", "prediction", "gold", "scores"}]}`.

Then `make eval` scores both model versions on every task and writes `results/v1.json` and `results/v2.json`.

**Done when** `tests/test_runner.py` passes and CI is green.
""",
         "hints": ["`others = [i for i in range(len(task.docs)) if i != index]`, then `random.Random(seed + index).sample(others, k)`.",
                   "`output.split(\"\\n\", 1)[0].strip()` is the prediction.",
                   "Add up each metric over the samples, then divide by the number of docs."]},
        {"id": "EK-4", "kind": "feature", "title": "Regression gate for CI", "estimate": 35, "topic": "evals.regress",
         "touch": ["evalkit/compare.py"], "test_path": "tests/test_compare.py", "tests": T_COMPARE,
         "body": r"""**Labels** `feature` `ci` · **Needs** EK-3

`make gate` should fail the build when a candidate model scores worse than the baseline, but `compare()` is a stub. Implement it in `evalkit/compare.py`.

`compare(baseline, candidate, max_drop=0.02)` takes two score files' contents, `{task: {metric: score}}`, and returns one row per task and metric **of the baseline**, sorted by task and then metric:

```python
{"task": "capitals", "metric": "f1", "base": 0.85, "cand": 0.80, "delta": -0.05, "ok": False}
```

- `delta` is `cand − base`; `ok` says whether the drop is at most `max_drop` (an improvement is always ok). A drop of exactly `max_drop` is ok, even though `0.78 − 0.80` is `-0.020000000000000018` in floating point: allow for that (`TOLERANCE`).
- A task or metric the candidate didn't report isn't ok, and its `cand` and `delta` are `None`.

`python -m evalkit compare BASE CAND` (written already, in `cli.py`) prints the rows and exits 1 when a row isn't ok: that's what turns CI red. Then try `make gate`: v2 knows more capitals but adds worse than v1, so the gate should **fail**.

**Done when** `tests/test_compare.py` passes and CI is green.
""",
         "hints": ["Loop `for task in sorted(baseline)` and `for metric in sorted(baseline[task])`.",
                   "`candidate.get(task, {}).get(metric)` is `None` when the candidate didn't report it.",
                   "`delta >= -max_drop - TOLERANCE` absorbs the float rounding."]},
    ],
}

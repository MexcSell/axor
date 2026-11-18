"""minitok: a byte-pair-encoding tokenizer library, modeled on Hugging Face tokenizers."""
from ._common import BUILD_WHEEL, block, changelog, gitignore, makefile, pyproject

ONBOARDING = r"""# Welcome to minitok 👋

You're joining the team behind **minitok**, a small byte-pair-encoding (BPE) tokenizer library. Its design follows Hugging Face's open-source [tokenizers](https://github.com/huggingface/tokenizers): text goes through a **pipeline** of a normalizer, a pre-tokenizer and a model, and a trained tokenizer is saved to one `tokenizer.json` that any user can load.

This doc gets you from zero to your first merged ticket. Give it half an hour on day one.

## What minitok does

```text
"Crème brûlée!"  -- normalizer -->     "crème brûlée!"
                 -- pre-tokenizer -->  ["crème", "brûlée", "!"]
                 -- BPE model -->      ["cr", "ème</w>", "br", "û", "lée</w>", "!</w>"]  -->  ids [37, 52, 18, 9, 61, 4]
```

BPE learns its vocabulary from a corpus: it starts from single characters and keeps **merging the most frequent pair** of neighbouring symbols into a new token. The merges, in the order they were learned, are the model. GPT-2, RoBERTa and many open models use this algorithm.

## Codebase tour

| Path | What's there |
|---|---|
| `minitok/normalizers.py` | `Normalizer`: Unicode NFKC, lowercasing, accent stripping |
| `minitok/pre_tokenizers.py` | `Whitespace`: splits text into words and punctuation, with offsets |
| `minitok/models.py` | `BPE`: training (learning merges) and tokenizing a word |
| `minitok/tokenizer.py` | `Tokenizer`: the pipeline, `encode` and `decode`, saving and loading `tokenizer.json` |
| `minitok/cli.py` | `python -m minitok train …` and `python -m minitok encode …` |
| `tests/` | pytest suites: `test_smoke.py` now, one file per ticket as you pick them up |
| `scripts/build_wheel.py` | builds the wheel (`make build`) |
| `data/corpus.txt` | a small corpus for the demo |

## Your dev loop

```sh
cd ~/projects/minitok
make                                  # lists the targets
make test                             # the whole suite (pytest -q)
pytest tests/test_normalizers.py -q   # one file, while you work on it
make demo                             # train on data/corpus.txt, then encode a sentence
make build                            # dist/minitok-<version>-py3-none-any.whl
```

Edit in the Lab's **Python** tab (or type `edit minitok/models.py` in the terminal). **Run CI** on a ticket runs its acceptance tests plus everything already merged, as CI does on a pull request.

## How we work

- **One ticket, one pull request.** Change what the ticket asks for; open a follow-up for anything else you spot.
- **Tests come with the ticket.** Each ticket adds its acceptance tests to `tests/`, failing. You're done when CI is green, not when the code looks right. Don't edit those tests to make them pass: CI runs its own copy.
- **Don't break main.** CI also runs the tests of every ticket already merged.
- **Readable beats clever.** Type hints on public functions, a docstring that says what and why, names instead of comments.
- **Ask early.** Stuck for 20 minutes? Ask your tutor (**Ask** on the ticket) and say what you tried.

## Your first week

{tickets}

Welcome aboard!
"""

README = r"""# minitok

A small byte-pair-encoding (BPE) tokenizer library for Python 3.11+, modeled on Hugging Face's [tokenizers](https://github.com/huggingface/tokenizers).

```python
from minitok import Tokenizer

tok = Tokenizer().train_from_files(["data/corpus.txt"], vocab_size=300)
enc = tok.encode("Tokenizers split text into subwords.")
print(enc.tokens, enc.ids, enc.offsets)
print(tok.decode(enc.ids))
tok.save("tokenizer.json")
tok = Tokenizer.from_file("tokenizer.json")
```

From the command line:

```sh
python -m minitok train data/corpus.txt --vocab-size 300 -o tokenizer.json
python -m minitok encode tokenizer.json "Tokenizers split text into subwords."
```

New to the codebase? Start with [ONBOARDING.md](ONBOARDING.md).
"""

CORPUS = r"""Tokenizers turn text into tokens, and tokens into the numbers a model reads.
A tokenizer that splits text into whole words needs a huge vocabulary, and still meets words it has never seen.
A tokenizer that splits text into single characters never meets an unknown word, but its sequences get very long.
Subword tokenizers sit in between: frequent words become single tokens, and rare words are split into pieces.
Byte pair encoding learns the pieces from a corpus. It starts from characters and merges the most frequent pair.
The newest merges join longer and longer pieces, until the vocabulary is as large as we asked for.
The lowest frequency pair that still gets merged sets how rare a piece can be.
Lower vocabulary sizes give longer sequences; larger vocabulary sizes give shorter sequences and bigger models.
Models read token ids, so the tokenizer must stay the same between training and serving.
Save the tokenizer next to the model, and load the same file wherever the model runs.
The tokenizer splits text the same way every time: the same text always gives the same tokens.
Offsets map every token back to the text, so a token can be highlighted where it came from.
Special tokens mark the start and the end of a sequence, and unknown characters become an unknown token.
Normalization comes first: unicode forms are folded, text is lowercased, and accents can be stripped.
Pre-tokenization comes next: text is split into words and punctuation, each with its offsets.
The model comes last: each word is split into the subword tokens the merges allow.
"""

INIT = r'''"""minitok: a small byte-pair-encoding (BPE) tokenizer library, modeled on Hugging Face tokenizers.

Text goes through a pipeline: a Normalizer cleans it up, a pre-tokenizer splits it into words, and the BPE model splits
words into the subword tokens it learned. Tokenizer ties them together and saves them to one tokenizer.json.
"""
from .models import BPE
from .normalizers import Normalizer
from .pre_tokenizers import Whitespace
from .tokenizer import Encoding, Tokenizer

__version__ = "0.1.0.dev0"
__all__ = ["BPE", "Encoding", "Normalizer", "Tokenizer", "Whitespace"]
'''

NORMALIZERS = (r'''"""Normalizers: clean text up before it's split into words, the first step of the pipeline."""
import unicodedata


class Normalizer:
    """Unicode NFKC (full-width letters, ligatures and the like folded to plain ones), then optional lowercasing,
    then optional accent stripping."""

    def __init__(self, lowercase: bool = True, strip_accents: bool = False):
        self.lowercase = lowercase
        self.strip_accents = strip_accents

    def normalize(self, text: str) -> str:
        text = unicodedata.normalize("NFKC", text)
        if self.lowercase:
            text = text.lower()
        if self.strip_accents:
«accents»
        return text

    def to_dict(self) -> dict:
        return {"type": "Normalizer", "lowercase": self.lowercase, "strip_accents": self.strip_accents}

    @classmethod
    def from_dict(cls, d: dict) -> "Normalizer":
        return cls(lowercase=d.get("lowercase", True), strip_accents=d.get("strip_accents", False))
''', {"accents": block("MT-1", r'''
            text = text.encode("ascii", "ignore").decode("ascii")
''', r'''
            # NFD splits "é" into "e" and a combining accent: drop only the combining marks, then recompose
            text = "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))
            text = unicodedata.normalize("NFC", text)
''')})

PRE_TOKENIZERS = r'''"""Pre-tokenizers: split normalized text into words, each with its (start, end) offsets."""
import re

_WORDS = re.compile(r"\w+|[^\w\s]")


class Whitespace:
    """Words are runs of letters, digits and _; any other character that isn't a space is a word of its own, like
    Hugging Face's Whitespace pre-tokenizer. split("Hi, you!") == [("Hi", (0, 2)), (",", (2, 3)), ("you", (4, 7)), ("!", (7, 8))]
    """

    def split(self, text: str) -> list[tuple[str, tuple[int, int]]]:
        return [(m.group(), m.span()) for m in _WORDS.finditer(text)]

    def to_dict(self) -> dict:
        return {"type": "Whitespace"}
'''

MODELS = (r'''"""The BPE model: learns merges from word counts, then splits words into the subword tokens it knows.

A word starts as its characters, the last one marked with END ("</w>"), so the same letters at the end of a word and
inside one are different tokens ("st</w>" in "fastest", "st" in "stop"). Training merges the most frequent pair of
neighbouring symbols, again and again, until the vocabulary is full; the merges, in order, are the model.
"""
from collections import Counter

END = "</w>"


def split_word(word: str) -> list[str]:
    """A word's starting symbols: its characters, the last one marked with END. split_word("low") == ["l", "o", "w</w>"]"""
    return [*word[:-1], word[-1] + END] if word else []


def merge(symbols: list[str], pair: tuple[str, str]) -> list[str]:
    """symbols with every occurrence of pair, from left to right, joined into one symbol.
    merge(["l", "o", "w</w>"], ("l", "o")) == ["lo", "w</w>"]"""
    out, i = [], 0
    while i < len(symbols):
        if i + 1 < len(symbols) and (symbols[i], symbols[i + 1]) == pair:
            out.append(symbols[i] + symbols[i + 1])
            i += 2
        else:
            out.append(symbols[i])
            i += 1
    return out


class BPE:
    def __init__(self, vocab: dict[str, int], merges: list[tuple[str, str]], unk_token: str = "[UNK]"):
        self.vocab = dict(vocab)                   # token -> id
        self.merges = [tuple(m) for m in merges]   # in the order they were learned
        self.ranks = {m: i for i, m in enumerate(self.merges)}
        self.unk_token = unk_token

    @classmethod
    def train(cls, word_counts: dict[str, int], vocab_size: int, min_frequency: int = 2,
              special_tokens: list[str] = (), unk_token: str = "[UNK]") -> "BPE":
        """Learns merges from word counts until the vocabulary holds vocab_size tokens (MT-2).

        The vocabulary starts with the special tokens, then every starting symbol (sorted); each merge adds its joined
        symbol. The pair merged next is the most frequent one (each word's pairs count as often as the word), ties
        going to the smallest pair in sorted order. Training stops early when no pair occurs min_frequency times.
        """
«train»

    def tokenize(self, word: str) -> list[str]:
        """Splits one word into tokens (MT-3): start from split_word(word) and keep merging the neighbouring pair with
        the lowest rank (learned earliest) until no pair can merge. Symbols not in the vocabulary become unk_token."""
«tokenize»

    def to_dict(self) -> dict:
        """The model as tokenizer.json stores it (MT-4)."""
«to_dict»

    @classmethod
    def from_dict(cls, d: dict) -> "BPE":
        """The model back from what to_dict() returned (MT-4)."""
«from_dict»
''', {
    "train": block("MT-2", r'''
        raise NotImplementedError("MT-2: learn the merges")
''', r'''
        vocab: dict[str, int] = {}
        for token in special_tokens:
            vocab.setdefault(token, len(vocab))
        words = {w: split_word(w) for w in word_counts if w}
        for symbol in sorted({s for symbols in words.values() for s in symbols}):
            vocab.setdefault(symbol, len(vocab))
        merges = []
        while len(vocab) < vocab_size:
            pairs = Counter()
            for w, symbols in words.items():
                for pair in zip(symbols, symbols[1:]):
                    pairs[pair] += word_counts[w]
            if not pairs:
                break
            best = min(pairs, key=lambda p: (-pairs[p], p))  # most frequent, then smallest
            if pairs[best] < min_frequency:
                break
            merges.append(best)
            vocab.setdefault(best[0] + best[1], len(vocab))
            words = {w: merge(symbols, best) for w, symbols in words.items()}
        return cls(vocab, merges, unk_token)
'''),
    "tokenize": block("MT-3", r'''
        raise NotImplementedError("MT-3: apply the merges")
''', r'''
        symbols = split_word(word)
        while len(symbols) > 1:
            pair = min(zip(symbols, symbols[1:]), key=lambda p: self.ranks.get(p, len(self.ranks)))
            if pair not in self.ranks:
                break
            symbols = merge(symbols, pair)
        return [s if s in self.vocab else self.unk_token for s in symbols]
'''),
    "to_dict": block("MT-4", r'''
        raise NotImplementedError("MT-4: save the model")
''', r'''
        return {"type": "BPE", "unk_token": self.unk_token, "end_of_word_suffix": END,
                "vocab": self.vocab, "merges": [f"{a} {b}" for a, b in self.merges]}
'''),
    "from_dict": block("MT-4", r'''
        raise NotImplementedError("MT-4: load the model")
''', r'''
        if d.get("type") != "BPE":
            raise ValueError(f"not a BPE model: {d.get('type')!r}")
        return cls(d["vocab"], [tuple(m.split(" ")) for m in d["merges"]], d.get("unk_token", "[UNK]"))
'''),
})

TOKENIZER = (r'''"""Tokenizer: the pipeline (normalizer, then pre-tokenizer, then BPE model), encode and decode, tokenizer.json."""
import json
from collections import Counter
from dataclasses import dataclass, field

from .models import BPE, END
from .normalizers import Normalizer
from .pre_tokenizers import Whitespace

UNK, CLS, SEP = "[UNK]", "[CLS]", "[SEP]"
SPECIAL = [UNK, CLS, SEP]  # always ids 0, 1 and 2
FORMAT = "minitok/1"       # tokenizer.json's "version"


@dataclass
class Encoding:
    """What encode() returns: the ids for the model, the tokens they stand for, and each token's (start, end) in the
    normalized text ((0, 0) for special tokens)."""
    ids: list[int] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)
    offsets: list[tuple[int, int]] = field(default_factory=list)


class Tokenizer:
    def __init__(self, model: BPE | None = None, normalizer: Normalizer | None = None, pre_tokenizer: Whitespace | None = None):
        self.model = model
        self.normalizer = normalizer or Normalizer()
        self.pre_tokenizer = pre_tokenizer or Whitespace()

    def normalize(self, text: str) -> str:
        return self.normalizer.normalize(text)

    def train(self, texts, vocab_size: int = 200, min_frequency: int = 2) -> "Tokenizer":
        """Learns the BPE model from an iterable of texts (a file's lines, say) and returns self."""
        counts = Counter()
        for text in texts:
            counts.update(word for word, _ in self.pre_tokenizer.split(self.normalize(text)))
        self.model = BPE.train(counts, vocab_size, min_frequency, special_tokens=SPECIAL, unk_token=UNK)
        return self

    def train_from_files(self, paths: list[str], **kw) -> "Tokenizer":
        def lines():
            for path in paths:
                with open(path, encoding="utf-8") as f:
                    yield from f
        return self.train(lines(), **kw)

    def get_vocab_size(self) -> int:
        return len(self._model().vocab)

    def token_to_id(self, token: str) -> int | None:
        return self._model().vocab.get(token)

    def id_to_token(self, id: int) -> str | None:
        return next((t for t, i in self._model().vocab.items() if i == id), None)

    def encode(self, text: str, add_special_tokens: bool = True) -> Encoding:
        """Normalizes text, splits it into words and each word into tokens (MT-3). With add_special_tokens, the
        encoding starts with [CLS] and ends with [SEP]."""
«encode»

    def decode(self, ids: list[int], skip_special_tokens: bool = True) -> str:
        """Joins the tokens back into words (a token ending in </w> ends a word), separated by single spaces (MT-3).
        Special tokens are left out, or kept as words of their own with skip_special_tokens=False."""
«decode»

    def to_dict(self) -> dict:
        """Everything needed to rebuild this tokenizer (MT-4): the format is in the ticket."""
«to_dict»

    def save(self, path: str) -> None:
        """Writes to_dict() to path as UTF-8 JSON, non-ASCII characters as they are (MT-4)."""
«save»

    @classmethod
    def from_dict(cls, d: dict) -> "Tokenizer":
«from_dict»

    @classmethod
    def from_file(cls, path: str) -> "Tokenizer":
«from_file»

    def _model(self) -> BPE:
        if self.model is None:
            raise ValueError("this tokenizer has no model yet: train it or load one")
        return self.model
''', {
    "encode": block("MT-3", r'''
        raise NotImplementedError("MT-3: encode text")
''', r'''
        model, enc = self._model(), Encoding()

        def add(token, span):
            enc.tokens.append(token)
            enc.ids.append(model.vocab[token])
            enc.offsets.append(span)

        if add_special_tokens:
            add(CLS, (0, 0))
        for word, (start, _) in self.pre_tokenizer.split(self.normalize(text)):
            for token in model.tokenize(word):
                size = 1 if token == model.unk_token else len(token.removesuffix(END))
                add(token, (start, start + size))
                start += size
        if add_special_tokens:
            add(SEP, (0, 0))
        return enc
'''),
    "decode": block("MT-3", r'''
        raise NotImplementedError("MT-3: decode ids")
''', r'''
        words, word = [], ""
        for i in ids:
            token = self.id_to_token(i)
            if token is None:
                raise ValueError(f"unknown token id {i}")
            if token in SPECIAL:
                if not skip_special_tokens:
                    words.append(token)
                continue
            word += token.removesuffix(END)
            if token.endswith(END):
                words.append(word)
                word = ""
        if word:
            words.append(word)
        return " ".join(words)
'''),
    "to_dict": block("MT-4", r'''
        raise NotImplementedError("MT-4: describe the tokenizer")
''', r'''
        model = self._model()
        return {"version": FORMAT,
                "special_tokens": [{"id": model.vocab[t], "content": t} for t in SPECIAL],
                "normalizer": self.normalizer.to_dict(),
                "pre_tokenizer": self.pre_tokenizer.to_dict(),
                "model": model.to_dict()}
'''),
    "save": block("MT-4", r'''
        raise NotImplementedError("MT-4: write tokenizer.json")
''', r'''
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
'''),
    "from_dict": block("MT-4", r'''
        raise NotImplementedError("MT-4: rebuild a tokenizer")
''', r'''
        if d.get("version") != FORMAT:
            raise ValueError(f"unsupported tokenizer.json version {d.get('version')!r}: expected {FORMAT!r}")
        return cls(BPE.from_dict(d["model"]), Normalizer.from_dict(d["normalizer"]), Whitespace())
'''),
    "from_file": block("MT-4", r'''
        raise NotImplementedError("MT-4: read tokenizer.json")
''', r'''
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
'''),
})

CLI = r'''"""python -m minitok: train a tokenizer on text files, or encode text with a saved one."""
import argparse

from .tokenizer import Tokenizer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="minitok", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train", help="learn a BPE tokenizer from text files")
    train.add_argument("files", nargs="+")
    train.add_argument("--vocab-size", type=int, default=200)
    train.add_argument("--min-frequency", type=int, default=2)
    train.add_argument("-o", "--output", default="tokenizer.json")
    encode = sub.add_parser("encode", help="encode text with a saved tokenizer")
    encode.add_argument("tokenizer")
    encode.add_argument("text")
    args = parser.parse_args(argv)
    if args.command == "train":
        tok = Tokenizer().train_from_files(args.files, vocab_size=args.vocab_size, min_frequency=args.min_frequency)
        tok.save(args.output)
        print(f"trained {tok.get_vocab_size()} tokens ({len(tok.model.merges)} merges) -> {args.output}")
    else:
        enc = Tokenizer.from_file(args.tokenizer).encode(args.text)
        for token, i, (start, end) in zip(enc.tokens, enc.ids, enc.offsets):
            print(f"{i:>5}  {token:<16} {start}-{end}")
    return 0
'''

MAIN = r'''from .cli import main

raise SystemExit(main())
'''

SMOKE = r'''"""Smoke tests: the package imports, and what already works keeps working."""
import minitok
from minitok import Whitespace
from minitok.models import merge, split_word


def test_version():
    """The package imports and has a version"""
    assert minitok.__version__


def test_whitespace_offsets():
    """Whitespace splits words and punctuation, with their offsets"""
    assert Whitespace().split("Hi, you!") == [("Hi", (0, 2)), (",", (2, 3)), ("you", (4, 7)), ("!", (7, 8))]


def test_word_helpers():
    """split_word marks the end of the word; merge joins a pair wherever it occurs"""
    assert split_word("low") == ["l", "o", "w</w>"]
    assert merge(["a", "b", "a", "b</w>"], ("a", "b")) == ["ab", "a", "b</w>"]
'''

T_NORMALIZERS = r'''"""MT-1: strip_accents takes the accents off and leaves every letter, in every script."""
from minitok import Normalizer


def test_strips_accents():
    """Accents come off Latin letters"""
    got = Normalizer(strip_accents=True).normalize("Crème Brûlée")
    assert got == "creme brulee", f"got {got!r}"


def test_keeps_other_scripts():
    """Japanese and Russian survive accent stripping"""
    got = Normalizer(strip_accents=True).normalize("Crème brûlée in 東京 и Москва")
    assert got == "creme brulee in 東京 и москва", f"got {got!r}: only the accents should go"


def test_keeps_symbols():
    """Emoji and currency signs aren't accents"""
    got = Normalizer(lowercase=False, strip_accents=True).normalize("Café ☕ costs €3")
    assert got == "Cafe ☕ costs €3", f"got {got!r}"


def test_nfkc_comes_first():
    """Full-width letters and ligatures are folded before accents are stripped"""
    got = Normalizer(strip_accents=True).normalize("ＡＢＣ ﬁancé")
    assert got == "abc fiance", f"got {got!r}"


def test_accents_kept_by_default():
    """Without strip_accents, accents stay"""
    assert Normalizer().normalize("Crème") == "crème"
'''

T_TRAIN = r'''"""MT-2: BPE training learns merges in the right order and fills the vocabulary."""
from minitok import BPE

WORDS = {"low": 5, "lower": 2, "newest": 6, "widest": 3}


def test_first_merges():
    """The most frequent pair merges first; ties go to the smallest pair"""
    merges = BPE.train(WORDS, vocab_size=30).merges
    want = [("e", "s"), ("es", "t</w>"), ("l", "o"), ("e", "w"), ("ew", "est</w>"), ("n", "ewest</w>")]
    assert merges[:6] == want, f"got {merges[:6]}"


def test_vocab_layout():
    """Special tokens first, then the sorted starting symbols, then a token per merge"""
    bpe = BPE.train(WORDS, vocab_size=30, special_tokens=["[UNK]", "[CLS]"])
    tokens = sorted(bpe.vocab, key=bpe.vocab.get)
    assert tokens[:2] == ["[UNK]", "[CLS]"], f"got {tokens[:2]}"
    alphabet = ["d", "e", "i", "l", "n", "o", "r</w>", "s", "t</w>", "w", "w</w>"]
    assert tokens[2:13] == alphabet, f"got {tokens[2:13]}"
    assert tokens[13] == "es", f"the first merge's token comes right after the alphabet, got {tokens[13]!r}"
    assert sorted(bpe.vocab.values()) == list(range(len(bpe.vocab))), "ids are 0, 1, 2… with no gaps"


def test_vocab_size_respected():
    """Training stops when the vocabulary holds vocab_size tokens"""
    for size in (12, 15, 20):
        got = len(BPE.train(WORDS, vocab_size=size).vocab)
        assert got == size, f"vocab_size={size} gave {got} tokens"


def test_min_frequency():
    """Pairs seen fewer than min_frequency times aren't merged"""
    merges = BPE.train(WORDS, vocab_size=100, min_frequency=4).merges
    assert len(merges) == 7 and merges[-1] == ("lo", "w</w>"), f"got {merges}"


def test_deterministic():
    """The same counts give the same model, whatever order the words come in"""
    a = BPE.train(WORDS, vocab_size=24)
    b = BPE.train(dict(reversed(list(WORDS.items()))), vocab_size=24)
    assert a.merges == b.merges and a.vocab == b.vocab
'''

T_ENCODE = r'''"""MT-3: tokenize words with the learned merges; encode and decode text."""
from minitok import Tokenizer

CORPUS = ["low low low low low", "lower lower", "newest newest newest newest newest newest", "widest widest widest"]


def trained():
    return Tokenizer().train(CORPUS, vocab_size=24)


def test_tokenize_known_words():
    """Words that were merged whole come out as one token"""
    bpe = trained().model
    assert bpe.tokenize("newest") == ["newest</w>"], f"got {bpe.tokenize('newest')}"
    assert bpe.tokenize("widest") == ["widest</w>"], f"got {bpe.tokenize('widest')}"


def test_tokenize_applies_merges_by_rank():
    """A new word is split by applying merges, earliest learned first"""
    bpe = trained().model
    assert bpe.tokenize("lowest") == ["lo", "w", "est</w>"], f"got {bpe.tokenize('lowest')}"
    assert bpe.tokenize("slow") == ["s", "low</w>"], f"got {bpe.tokenize('slow')}"


def test_unknown_characters():
    """Characters the model never saw become [UNK]"""
    bpe = trained().model
    assert bpe.tokenize("lowz") == ["lo", "w", "[UNK]"], f"got {bpe.tokenize('lowz')}"


def test_encode():
    """encode() gives tokens in [CLS] … [SEP], their ids, and offsets into the normalized text"""
    tok = trained()
    enc = tok.encode("Lowest newest!")
    assert enc.tokens == ["[CLS]", "lo", "w", "est</w>", "newest</w>", "[UNK]", "[SEP]"], f"got {enc.tokens}"
    assert enc.offsets == [(0, 0), (0, 2), (2, 3), (3, 6), (7, 13), (13, 14), (0, 0)], f"got {enc.offsets}"
    assert enc.ids == [tok.token_to_id(t) for t in enc.tokens], "ids don't match the tokens"
    assert enc.ids[0] == 1 and enc.ids[-1] == 2, "[CLS] is id 1 and [SEP] is id 2"


def test_encode_without_special_tokens():
    """add_special_tokens=False leaves [CLS] and [SEP] out"""
    assert trained().encode("low", add_special_tokens=False).tokens == ["low</w>"]


def test_decode():
    """decode(encode(text).ids) gives the normalized words back, separated by single spaces"""
    tok = trained()
    for text in ("lowest newest", "Widest  LOW", "slow wider"):
        got = tok.decode(tok.encode(text).ids)
        assert got == " ".join(text.lower().split()), f"{text!r} came back as {got!r}"
    got = tok.decode(tok.encode("low").ids, skip_special_tokens=False)
    assert got == "[CLS] low [SEP]", f"with skip_special_tokens=False: got {got!r}"
'''

T_SERIAL = r'''"""MT-4: save a trained tokenizer to tokenizer.json and load it back."""
import json
import os
import tempfile

from minitok import Normalizer, Tokenizer

CORPUS = ["low low low low low", "lower lower", "newest newest newest newest newest newest", "widest widest widest"]


def saved(tok):
    """Saves tok to a fresh tokenizer.json; returns its path and the parsed JSON."""
    path = os.path.join(tempfile.mkdtemp(), "tokenizer.json")
    tok.save(path)
    with open(path, encoding="utf-8") as f:
        return path, json.load(f)


def test_format():
    """tokenizer.json has the version, special tokens, normalizer, pre-tokenizer and model"""
    _, d = saved(Tokenizer().train(CORPUS, vocab_size=24))
    assert d.get("version") == "minitok/1", f"version is {d.get('version')!r}"
    assert d["special_tokens"] == [{"id": 0, "content": "[UNK]"}, {"id": 1, "content": "[CLS]"}, {"id": 2, "content": "[SEP]"}]
    assert d["normalizer"] == {"type": "Normalizer", "lowercase": True, "strip_accents": False}
    assert d["pre_tokenizer"] == {"type": "Whitespace"}
    assert d["model"]["type"] == "BPE" and d["model"]["unk_token"] == "[UNK]"


def test_merges_as_strings_in_order():
    """Merges are stored as "a b" strings, in the order they were learned"""
    tok = Tokenizer().train(CORPUS, vocab_size=24)
    _, d = saved(tok)
    assert d["model"]["merges"][:3] == ["e s", "es t</w>", "l o"], f"got {d['model']['merges'][:3]}"
    assert len(d["model"]["merges"]) == len(tok.model.merges)


def test_round_trip():
    """A loaded tokenizer encodes exactly like the one that was saved, settings included"""
    tok = Tokenizer(normalizer=Normalizer(strip_accents=True)).train(CORPUS, vocab_size=24)
    path, _ = saved(tok)
    back = Tokenizer.from_file(path)
    for text in ("lowest newést", "WIDER slow", "?!"):
        a, b = tok.encode(text), back.encode(text)
        assert (a.ids, a.tokens, a.offsets) == (b.ids, b.tokens, b.offsets), f"{text!r} encodes differently after loading"
    assert back.normalizer.strip_accents is True, "the normalizer's settings are saved too"


def test_utf8_not_escaped():
    """Non-ASCII tokens are written as they are, not as \\u escapes"""
    path, _ = saved(Tokenizer().train(["café café café", "thé thé"], vocab_size=20))
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert "é" in text and "\\u00e9" not in text, "write with ensure_ascii=False"


def test_unknown_version_rejected():
    """Loading a file of another version raises ValueError"""
    path, d = saved(Tokenizer().train(CORPUS, vocab_size=24))
    d["version"] = "minitok/9"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f)
    try:
        Tokenizer.from_file(path)
    except ValueError:
        return
    raise AssertionError("from_file should refuse version minitok/9 with ValueError")
'''

PROJECT = {
    "id": "minitok", "name": "minitok", "package": "minitok", "like": "Hugging Face tokenizers", "org": "Hugging Face",
    "title": "A BPE tokenizer library",
    "blurb": "Join the team behind a byte-pair-encoding tokenizer: fix a Unicode bug, implement BPE training, encoding and "
             "decoding with offsets, save tokenizers to tokenizer.json, and ship 0.1.0.",
    "level": "Intermediate", "hours": 4, "skills": ["BPE", "Unicode", "Offsets", "JSON formats", "Packaging"],
    "topics": ["llm.tokens", "found.python"],
    "smoke": SMOKE,
    "files": {
        "README.md": README, "ONBOARDING.md": ONBOARDING, "CHANGELOG.md": changelog("minitok", "Project scaffolding: the pipeline, the Whitespace pre-tokenizer and the CLI."),
        "pyproject.toml": pyproject("minitok", "A small BPE tokenizer library, modeled on Hugging Face tokenizers"),
        ".gitignore": gitignore("tokenizer.json"),
        "Makefile": makefile("minitok", """
demo:  ## train on data/corpus.txt, then encode a sentence with the saved tokenizer
    python -m minitok train data/corpus.txt --vocab-size 300 -o tokenizer.json
    python -m minitok encode tokenizer.json "The newest tokenizers split text into subwords."
""", "tokenizer.json"),
        "minitok/__init__.py": INIT, "minitok/__main__.py": MAIN, "minitok/cli.py": CLI,
        "minitok/normalizers.py": NORMALIZERS, "minitok/pre_tokenizers.py": PRE_TOKENIZERS,
        "minitok/models.py": MODELS, "minitok/tokenizer.py": TOKENIZER,
        "scripts/build_wheel.py": BUILD_WHEEL, "data/corpus.txt": CORPUS,
    },
    "tickets": [
        {"id": "MT-1", "kind": "good first issue", "title": "strip_accents deletes non-Latin text", "estimate": 15, "topic": "llm.tokens",
         "touch": ["minitok/normalizers.py"], "test_path": "tests/test_normalizers.py", "tests": T_NORMALIZERS,
         "body": r"""**Reported by** a user on the forum · **Labels** `bug` `good first issue`

> I turned on `strip_accents=True` to fold "café" into "cafe", and my Japanese and Russian text disappeared.

```python
>>> Normalizer(strip_accents=True).normalize("Crème brûlée in 東京 и Москва")
'creme brulee in  '
```

Accent stripping should take the **accents** off and leave every letter, in every script, where it is: that line should give `'creme brulee in 東京 и москва'`.

**Where:** `Normalizer.normalize` in `minitok/normalizers.py`.

**Done when** the tests in `tests/test_normalizers.py` pass (`pytest tests/test_normalizers.py -q`) and **Run CI** is green.

**A pointer:** in Unicode, "é" can be one character or two: "e" followed by a *combining* acute accent. `unicodedata.normalize("NFD", text)` gives you the two-character form, and `unicodedata.combining(ch)` says whether a character is a combining mark.
""",
         "hints": ["The bug is the `encode(\"ascii\", \"ignore\")` line: it throws away every character outside ASCII, letters included.",
                   "Decompose with NFD, keep the characters where `unicodedata.combining(c)` is 0, then recompose with NFC."]},
        {"id": "MT-2", "kind": "feature", "title": "Train BPE merges", "estimate": 45, "topic": "llm.tokens",
         "touch": ["minitok/models.py"], "test_path": "tests/test_bpe_train.py", "tests": T_TRAIN,
         "body": r"""**Labels** `feature` · **Blocks** MT-3 and MT-4

`BPE.train` is a stub. Implement byte-pair-encoding training (Sennrich et al., 2016), the algorithm behind GPT-2's and Hugging Face's BPE tokenizers:

1. **Start** each word as `split_word(word)`: its characters, the last one marked with `</w>`. The vocabulary is the `special_tokens` first (ids 0, 1, …), then every starting symbol in **sorted** order.
2. **Count** every pair of neighbouring symbols across all words, each word weighted by its count.
3. **Merge** the most frequent pair everywhere it occurs (`merge()` is written already), append it to `merges`, and add the joined symbol to the vocabulary with the next id. **Ties** go to the smallest pair in sorted order, so training is deterministic.
4. **Repeat** until the vocabulary holds `vocab_size` tokens, no pairs are left, or the best pair occurs fewer than `min_frequency` times.

For `{"low": 5, "lower": 2, "newest": 6, "widest": 3}` the first merges are `("e", "s")` (9 times: it ties with `("s", "t</w>")` and wins on order), then `("es", "t</w>")`, then `("l", "o")`.

**Where:** `BPE.train` in `minitok/models.py`. **Done when** `tests/test_bpe_train.py` passes and CI is green.
""",
         "hints": ["A `collections.Counter` keyed by `(a, b)` tuples counts the pairs: `for pair in zip(symbols, symbols[1:])`.",
                   "`min(pairs, key=lambda p: (-pairs[p], p))` picks the most frequent pair and breaks ties by sorted order in one go.",
                   "After each merge, rebuild every word with `merge(symbols, best)` before counting again."]},
        {"id": "MT-3", "kind": "feature", "title": "Encode and decode text", "estimate": 45, "topic": "llm.tokens",
         "touch": ["minitok/models.py", "minitok/tokenizer.py"], "test_path": "tests/test_encode.py", "tests": T_ENCODE,
         "body": r"""**Labels** `feature` · **Needs** MT-2

We can learn merges now, but not use them. Implement:

- **`BPE.tokenize(word)`** in `minitok/models.py`: start from `split_word(word)`. While some neighbouring pair has been learned, merge the pair with the **lowest rank** (`self.ranks`: learned earliest) everywhere it occurs. Symbols that aren't in the vocabulary become `unk_token`.
- **`Tokenizer.encode(text, add_special_tokens=True)`** in `minitok/tokenizer.py`: normalize, pre-tokenize, tokenize each word, and fill an `Encoding` with `tokens`, `ids` and `offsets`. Offsets are `(start, end)` in the **normalized** text: a token spans as many characters as it has letters (without `</w>`), `[UNK]` spans one, and `[CLS]` and `[SEP]` (added first and last) get `(0, 0)`.
- **`Tokenizer.decode(ids, skip_special_tokens=True)`**: join tokens into words (a token ending in `</w>` ends a word) and the words with single spaces. Special tokens are skipped, or kept as words of their own with `skip_special_tokens=False`.

With the tests' corpus:

```python
>>> tok.encode("Lowest newest!").tokens
['[CLS]', 'lo', 'w', 'est</w>', 'newest</w>', '[UNK]', '[SEP]']
>>> tok.decode(tok.encode("Lowest newest").ids)
'lowest newest'
```

**Done when** `tests/test_encode.py` passes and CI is green.
""",
         "hints": ["In `tokenize`, `min(zip(symbols, symbols[1:]), key=lambda p: self.ranks.get(p, len(self.ranks)))` finds the earliest-learned pair; stop when it isn't in `self.ranks`.",
                   "In `encode`, keep a running `start` per word: each token adds `len(token.removesuffix(\"</w>\"))` characters (1 for `[UNK]`).",
                   "In `decode`, build the current word token by token and close it when a token ends with `</w>`."]},
        {"id": "MT-4", "kind": "feature", "title": "Save and load tokenizer.json", "estimate": 40, "topic": "llm.tokens",
         "touch": ["minitok/models.py", "minitok/tokenizer.py"], "test_path": "tests/test_serialization.py", "tests": T_SERIAL,
         "body": r"""**Labels** `feature` · **Needs** MT-3

Users can't keep a trained tokenizer. Implement saving and loading, in a `tokenizer.json` modeled on Hugging Face's:

```json
{
  "version": "minitok/1",
  "special_tokens": [{"id": 0, "content": "[UNK]"}, {"id": 1, "content": "[CLS]"}, {"id": 2, "content": "[SEP]"}],
  "normalizer": {"type": "Normalizer", "lowercase": true, "strip_accents": false},
  "pre_tokenizer": {"type": "Whitespace"},
  "model": {"type": "BPE", "unk_token": "[UNK]", "end_of_word_suffix": "</w>",
            "vocab": {"[UNK]": 0, "[CLS]": 1, "…": 2}, "merges": ["e s", "es t</w>", "l o"]}
}
```

- `BPE.to_dict` and `BPE.from_dict`: merges as `"a b"` strings, in order. `from_dict` refuses a `type` other than `"BPE"` with `ValueError`.
- `Tokenizer.to_dict`, `Tokenizer.save(path)` (UTF-8, `ensure_ascii=False` so "é" stays readable, `indent=2`), `Tokenizer.from_dict` and `Tokenizer.from_file(path)`. Loading another `version` raises `ValueError`.

A loaded tokenizer must encode **exactly** like the saved one. Then try the whole thing: `make demo` trains on `data/corpus.txt`, saves `tokenizer.json`, and encodes a sentence with the file it saved.

**Done when** `tests/test_serialization.py` passes and CI is green.
""",
         "hints": ["`Normalizer.to_dict()` and `Whitespace.to_dict()` exist already: `Tokenizer.to_dict` mostly assembles the parts.",
                   "`json.dump(d, f, ensure_ascii=False, indent=2)` with the file opened as `open(path, \"w\", encoding=\"utf-8\")`.",
                   "`\"es t</w>\".split(\" \")` gives the pair back as a list: make it a tuple."]},
    ],
}

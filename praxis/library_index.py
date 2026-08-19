#!/usr/bin/env python3
"""What the library already teaches — the corpus a JD requirement is matched against.

`praxis/jd_extract.py` ends with a structured list of what a posting asks for. The gap
analysis has to decide, for each of those requirements, whether Praxis can already teach
it — and the only honest answer comes from the library that actually shipped. This module
is that side of the diff: **one entry per notebook the product can build today**, read
live out of `curriculum.DOMAINS` every time it is asked for.

Live is the whole point. `docs/explanation/gap-analysis.md` is a *generated* index of the
same material, and a hand-copied list beside it would be wrong the first time a topic is
added to `curriculum.py`. So:

  - every seed domain contributes its enumerated topics, `recommended` ones included —
    a recommended neighbour is already scaffolded (gap-analysis.md §2), so re-tutorialing
    it is exactly the redundancy this funnel exists to avoid, and it counts as library;
  - a `filesystem` domain enumerates no topics, so its notebooks are discovered on disk
    the way `launcher/app.py` discovers them (gap-analysis.md §3, the legacy library);
  - `Domain.dir` is the `rel` everywhere else in the product, so an entry's `rel` is
    already what `/render/<rel>` and `/api/library` use.

The other half is matching. A posting says "K8s", the library says "Kubernetes"; a posting
says "Answer Set Programming", the library says "Answer Set Programming (ASP / clingo)".
Both sides therefore go through **one** normalizer — `match_key()` — in the same lenient
spirit as the rest of the JD funnel: case- and punctuation-insensitive, stopwords dropped,
plurals folded, and a small alias table for the short forms a posting actually writes.
Because the *same* function canonicalizes the topic title and the requirement, a rule that
mangles a word (plural stripping does) mangles it identically on both sides and the match
still lands.

Exact keys alone would be brittle, so an entry also carries its identity `tokens` and the
index carries an IDF weight per token: `related()` ranks the topics that share the rarest
words with a phrase, which is the raw material for "partially covered" one band up. What
counts as covered, partial or missing is *not* decided here — this module only says what
exists and how near it is.

CLI:
    python -m praxis.library_index                 the corpus: domains, topics, counts
    python -m praxis.library_index "kubernetes"    what the library has for a phrase
"""

from __future__ import annotations

import math
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import curriculum  # noqa: E402  (module, not `from ... import DOMAINS`: read live)

#: Words that carry no identity on either side of the match.
STOPWORDS = frozenset(
    "a an and are as at by for from in into its of on or the to via with your".split()
)

#: What a posting writes for something the library titles differently. Applied to the
#: raw token before anything else, so a form listed here is never plural-stripped into
#: a collision (VITS -> "vit" must not become "vision transformer").
TOKEN_ALIASES = {
    "k8s": "kubernetes", "k8": "kubernetes", "kubectl": "kubernetes",
    "iac": "infrastructure as code",
    "aws": "amazon web services", "gcp": "google cloud",
    "js": "javascript", "golang": "go", "postgres": "postgresql",
    "hf": "hugging face", "huggingface": "hugging face",
    "sklearn": "scikit learn", "scikitlearn": "scikit learn",
    "ml": "machine learning", "nlp": "natural language processing",
    "rl": "reinforcement learning", "rlhf": "rlhf",
    "llm": "large language model", "llms": "large language model",
    "rag": "retrieval augmented generation",
    "cot": "chain of thought",
    "asr": "speech recognition", "stt": "speech to text", "tts": "text to speech",
    "moe": "mixture of experts",
    "mcp": "model context protocol",
    "a2a": "agent to agent", "adk": "agent development kit",
    "asp": "answer set programming", "owl": "web ontology language",
    "smt": "satisfiability modulo theories",
    "ipynb": "jupyter", "notebooks": "notebook", "apis": "api",
}

#: Where a title hides a second name for the same thing: "Quantization: GPTQ / AWQ",
#: "Answer Set Programming (ASP / clingo)", "Weights & Biases".
_PARENTHETICAL = re.compile(r"\(([^)]*)\)")
_SEPARATORS = re.compile(r"[/,;:&]|\s-\s|—")
_WORD = re.compile(r"[a-z0-9]+")

MIN_KEY_CHARS = 2      # shorter than this names nothing a posting could mean
RELATED_LIMIT = 8


# --- one normalizer, used on both sides --------------------------------------


def _singular(token: str) -> str:
    """Fold an unremarkable plural. Applied to topic titles and requirements alike, so a
    word it mangles is mangled the same on both sides and still matches itself.

    The length bar is what keeps it honest: a short name is a name, not a plural, and
    stripping one costs a real distinction — "VITS" (a TTS model) would become the "ViT"
    of Vision Transformer. Anything that short is spelled out in TOKEN_ALIASES instead.
    """
    if len(token) > 4 and token.endswith("s") and token[-2:] not in ("ss", "us", "is"):
        return token[:-1]
    return token


def canonical_tokens(text: object) -> list[str]:
    """The identity words of a phrase, in order: lower-cased, aliased, de-stopworded."""
    tokens: list[str] = []
    for raw in _WORD.findall(str(text or "").lower()):
        expanded = TOKEN_ALIASES.get(raw)
        # The alias is expanded first and folded second — never re-aliased, so a plural
        # that strips onto another short form ("VITS" -> "vit") can't take its meaning.
        pieces = expanded.split() if expanded else [raw]
        tokens += [_singular(p) for p in pieces if p not in STOPWORDS]
    return tokens


def match_key(text: object) -> str:
    """The exact-match form of a phrase. `"K8s!"` and `"Kubernetes"` are one key."""
    return " ".join(canonical_tokens(text))


def match_tokens(text: object) -> frozenset[str]:
    """The identity words as a set, for overlap. Bare numbers name nothing."""
    return frozenset(t for t in canonical_tokens(text) if not t.isdigit())


def title_keys(title: str, slug: str = "") -> tuple[str, ...]:
    """Every key a topic answers to: its title, its slug, and the names inside it.

    "Answer Set Programming (ASP / clingo)" is one notebook that a posting may call any
    of three things, so the parenthetical and the separated pieces each become a key.
    """
    inside = _PARENTHETICAL.findall(title)
    outside = _PARENTHETICAL.sub(" ", title)
    candidates = [title, outside, slug.replace("-", " "), *inside]
    for phrase in [outside, *inside]:
        candidates += _SEPARATORS.split(phrase)

    keys: list[str] = []
    for candidate in candidates:
        key = match_key(candidate)
        if len(key) >= MIN_KEY_CHARS and not key.isdigit() and key not in keys:
            keys.append(key)
    return tuple(keys)


# --- the corpus --------------------------------------------------------------


@dataclass(frozen=True)
class LibraryTopic:
    """One notebook the product can already build, as the gap analysis sees it."""

    slug: str
    title: str
    rel: str            # the same string /render/<rel> and /api/library use
    domain: str         # Domain.dir
    domain_title: str
    recommended: bool = False
    runnable: bool = True
    note: str = ""
    keys: tuple[str, ...] = ()
    tokens: frozenset[str] = frozenset()

    def evidence(self) -> dict:
        """This topic as a citation — what band 77 attaches to a classification."""
        return {
            "slug": self.slug,
            "title": self.title,
            "rel": self.rel,
            "domain": self.domain,
            "domainTitle": self.domain_title,
            "recommended": self.recommended,
        }


@dataclass(frozen=True)
class LibraryIndex:
    """The shipped library, indexed for matching. Built by `build_index()`, never by hand."""

    domains: tuple = ()
    topics: tuple[LibraryTopic, ...] = ()
    by_key: dict[str, tuple[LibraryTopic, ...]] = field(default_factory=dict)
    by_token: dict[str, tuple[LibraryTopic, ...]] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.topics)

    def idf(self, token: str) -> float:
        """How much sharing this word says. "ai" says almost nothing; "clingo" says a lot."""
        return math.log(1 + len(self.topics) / (1 + len(self.by_token.get(token, ()))))

    def lookup(self, text: object) -> tuple[LibraryTopic, ...]:
        """The topics whose name *is* this phrase, normalization aside. Possibly none."""
        return self.by_key.get(match_key(text), ())

    def related(self, text: object, limit: int = RELATED_LIMIT) -> list[tuple[LibraryTopic, float]]:
        """Topics sharing words with `text`, best first, scored 0..1 by how much of the
        phrase's meaning they account for. An adjacency, not a match — band 76's
        classifier decides where the line between partial and missing falls."""
        wanted = match_tokens(text)
        total = sum(self.idf(token) for token in wanted)
        if not wanted or total <= 0:
            return []
        scored: list[tuple[LibraryTopic, float]] = []
        for topic in {id(t): t for token in wanted
                      for t in self.by_token.get(token, ())}.values():
            shared = wanted & topic.tokens
            if shared:
                scored.append((topic, sum(self.idf(t) for t in shared) / total))
        scored.sort(key=lambda pair: (-pair[1], pair[0].title))
        return scored[:limit]


def _manifest_topics(domain) -> list[LibraryTopic]:
    return [
        LibraryTopic(
            slug=topic.slug,
            title=topic.title,
            rel=f"{domain.dir}/{topic.slug}.ipynb",
            domain=domain.dir,
            domain_title=domain.title,
            recommended=topic.recommended,
            runnable=topic.runnable,
            note=topic.note,
            keys=title_keys(topic.title, topic.slug),
            tokens=match_tokens(f"{topic.title} {topic.slug.replace('-', ' ')}"),
        )
        for topic in domain.topics
    ]


def _filesystem_topics(domain) -> list[LibraryTopic]:
    """A domain that enumerates nothing — its notebooks are the manifest (curriculum.py's
    `source="filesystem"`, the legacy library of gap-analysis.md §3). Discovered the same
    way `launcher/app.py` discovers them, so the two can't disagree about what is there."""
    base = curriculum.domain_path(domain)
    titles = {t.slug: t for t in domain.topics}
    topics = []
    for path in sorted(base.rglob("*.ipynb")):
        topic = titles.get(path.stem)
        title = topic.title if topic else path.stem.replace("-", " ").title()
        group = path.parent.name if path.parent != base else ""
        topics.append(LibraryTopic(
            slug=path.stem,
            title=title,
            rel=f"{domain.dir}/{path.relative_to(base).as_posix()}",
            domain=domain.dir,
            domain_title=domain.title,
            recommended=bool(topic and topic.recommended),
            runnable=topic.runnable if topic else True,
            note=topic.note if topic else group.replace("-", " "),
            keys=title_keys(title, path.stem),
            tokens=match_tokens(f"{title} {path.stem.replace('-', ' ')} "
                                f"{group.replace('-', ' ')}"),
        ))
    return topics


def build_index() -> LibraryIndex:
    """The shipped library, read out of `curriculum.DOMAINS` right now.

    Nothing here is cached at module scope and nothing is copied: adding a topic to
    `curriculum.py` adds it to the corpus, which is the only way this can't drift from
    the library the launcher lists and the constructor fills.
    """
    domains = tuple(curriculum.DOMAINS)
    topics: list[LibraryTopic] = []
    for domain in domains:
        topics += (_filesystem_topics(domain) if domain.source == "filesystem"
                   else _manifest_topics(domain))

    by_key: dict[str, list[LibraryTopic]] = {}
    by_token: dict[str, list[LibraryTopic]] = {}
    for topic in topics:
        for key in topic.keys:
            by_key.setdefault(key, []).append(topic)
        for token in topic.tokens:
            by_token.setdefault(token, []).append(topic)
    return LibraryIndex(
        domains=domains,
        topics=tuple(topics),
        by_key={k: tuple(v) for k, v in by_key.items()},
        by_token={k: tuple(v) for k, v in by_token.items()},
    )


_CACHED: LibraryIndex | None = None


def library_index(*, refresh: bool = False) -> LibraryIndex:
    """`build_index()` once per process, for a caller matching a whole requirement list.

    A caller that has changed the curriculum (or a test that has) passes `refresh=True`;
    `build_index()` itself is always live.
    """
    global _CACHED
    if refresh or _CACHED is None:
        _CACHED = build_index()
    return _CACHED


def _main(argv: list[str]) -> int:  # pragma: no cover - a convenience CLI
    index = build_index()
    if not argv:
        print(f"{len(index.domains)} domains, {len(index)} topics "
              f"({sum(1 for t in index.topics if t.recommended)} recommended)\n")
        for domain in index.domains:
            n = sum(1 for t in index.topics if t.domain == domain.dir)
            print(f"  {domain.dir:<40} {n:>4}  {domain.title}")
        return 0

    query = " ".join(argv)
    print(f"{query!r} -> {match_key(query)!r}\n")
    for topic in index.lookup(query):
        print(f"  = {topic.title}  ({topic.rel})")
    for topic, score in index.related(query):
        print(f"  ~ {score:.2f}  {topic.title}  ({topic.rel})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))

#!/usr/bin/env python3
"""The Praxis curriculum model — the seed library plus user-defined subjects.

A **curriculum** is a subject broken into modules, each module a list of topics, each
topic exactly one notebook. Two kinds share that one shape:

  seed       the 11 hand-written study domains enumerated below — Praxis ships them as
             the example library and as worked examples of a finished tutorial.
  generated  a user-defined subject: free text -> praxis/curriculum_gen.py asks the LLM
             for the same structure -> persisted as JSON under
             notebooks/subjects/<slug>/curriculum.json and read back with load_subject().

Because both resolve to the same `Domain`/`Topic` objects, everything downstream —
scaffold_notebooks.py, launcher/app.py, nbstatus.py, the gate — works on a generated
subject exactly as it works on a seed domain.

Drives:
  - scaffold_notebooks.py   (creates blank notebook scaffolds + reorgs the legacy 64)
  - launcher/app.py         (sidebar navigation + completion status)
  - ralph/generate_tasklists.py (one ralphy task per notebook below the rubric bar)
  - CURRICULUM.md / docs/gap-analysis.md (generated human indices)

Domains 1-10 are the seed study curriculum (explicit topic lists below).
Domain 11 (DevOps/MLOps & Infra) is the relocated legacy library; its topics are
discovered from the filesystem (source="filesystem"), not enumerated here.

Each Topic carries:
  slug         kebab-case file stem -> notebooks/<domain.dir>/<slug>.ipynb
  title        human-readable notebook title
  runnable     True  -> notebook must contain executed, runnable Python cells
               False -> Python can't drive it (engines/SaaS/IDEs/other-language);
                        notebook is conceptual + CLI/snippets with a clear note
  recommended  True  -> NOT in the user's original list; a suggested addition
  note         short qualifier (e.g. "needs API key", "R kernel", "Unity asset")
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from praxis import storage  # noqa: E402  (needs the line above when run as a script)


@dataclass(frozen=True)
class Topic:
    slug: str
    title: str
    runnable: bool = True
    recommended: bool = False
    note: str = ""


@dataclass(frozen=True)
class Domain:
    """A titled group of topics — a seed domain, or one module of a user subject."""

    dir: str  # notebooks/<dir>/
    title: str
    blurb: str
    topics: tuple[Topic, ...] = ()
    # "manifest"   topics are enumerated below; every one of them has a notebook
    # "filesystem" topics are discovered by scanning notebooks/<dir> (the legacy library)
    # "subject"    a generated subject's module: topics are enumerated, but only the
    #              ones already scaffolded exist on disk
    source: str = "manifest"


def T(slug, title, runnable=True, recommended=False, note=""):
    return Topic(slug, title, runnable, recommended, note)


DOMAINS: list[Domain] = [
    Domain(
        "01-symbolic-ai-logic",
        "Symbolic AI & Logic",
        "Logic programming, knowledge representation, reasoning, and the semantic web.",
        (
            T("swi-prolog", "SWI-Prolog", note="needs swipl"),
            T("datalog", "Datalog"),
            T("answer-set-programming", "Answer Set Programming (ASP / clingo)", note="needs clingo"),
            T("clips", "CLIPS Expert System", note="needs clips"),
            T("pyke", "Pyke (Python Knowledge Engine)"),
            T("knowledge-graphs", "Knowledge Graphs"),
            T("owl", "OWL (Web Ontology Language)", note="owlready2"),
            T("sparql", "SPARQL"),
            # recommended additions
            T("rdflib", "RDF & Turtle with rdflib", recommended=True),
            T("z3-smt", "Z3 / SMT Solving", recommended=True),
            T("minikanren", "miniKanren (relational programming)", recommended=True),
            T("problog", "ProbLog (probabilistic logic)", recommended=True),
            T("minizinc", "MiniZinc (constraint programming)", recommended=True, note="needs minizinc"),
            T("description-logic-reasoners", "Description-Logic Reasoners (HermiT/Pellet)", recommended=True, runnable=False),
            T("rete-algorithm", "The Rete Algorithm", recommended=True),
        ),
    ),
    Domain(
        "02-ai-ml-tooling",
        "AI/ML Tooling",
        "Core frameworks and experiment/lifecycle tooling for building ML.",
        (
            T("pytorch", "PyTorch"),
            T("keras", "Keras"),
            T("tensorflow", "TensorFlow"),
            T("mlflow", "MLflow"),
            T("jupyter", "Jupyter"),
            T("huggingface", "Hugging Face (Transformers/Datasets/Hub)"),
            T("scikit-learn", "scikit-learn", recommended=True),
            T("jax-flax", "JAX & Flax", recommended=True),
            T("pytorch-lightning", "PyTorch Lightning", recommended=True),
            T("onnx-runtime", "ONNX & ONNX Runtime", recommended=True),
            T("weights-and-biases", "Weights & Biases", recommended=True, note="needs API key"),
            T("dvc", "DVC (Data Version Control)", recommended=True),
            T("optuna", "Optuna (hyperparameter optimization)", recommended=True),
            T("gradio", "Gradio", recommended=True),
        ),
    ),
    Domain(
        "03-llm-inference-training-optimization",
        "LLM Inference, Training & Optimization",
        "Training LLMs from scratch, RAG, embeddings, prompting, and efficiency.",
        (
            T("open-r1", "Open-R1"),
            T("mingpt", "minGPT"),
            T("megatron-lm", "Megatron-LM"),
            T("finetune-transformer-lm", "finetune-transformer-lm (GPT)"),
            T("dspy", "DSPy"),
            T("rag", "Retrieval-Augmented Generation (RAG)"),
            T("faiss", "FAISS"),
            T("chromadb", "ChromaDB"),
            T("pinecone", "Pinecone", note="needs API key"),
            T("vector-embeddings", "Vector Embeddings"),
            T("semantic-search", "Semantic Search"),
            T("prompt-engineering", "Prompt Engineering"),
            T("few-shot-learning", "Few-Shot Learning"),
            T("chain-of-thought", "Chain-of-Thought Prompting"),
            T("lora-controlnet", "LoRA & ControlNet"),
            T("vllm", "vLLM (inference)", recommended=True, note="cross-ref domain 11"),
            T("gguf-llama-cpp", "GGUF & llama.cpp quantized inference", recommended=True),
            T("quantization-gptq-awq", "Quantization: GPTQ / AWQ / bitsandbytes", recommended=True),
            T("flash-attention", "Flash Attention", recommended=True),
            T("speculative-decoding", "Speculative Decoding", recommended=True),
            T("kv-cache", "KV-Cache & Paged Attention", recommended=True),
            T("qlora", "QLoRA", recommended=True),
            T("trl-rlhf-dpo", "TRL: RLHF / PPO / DPO", recommended=True),
            T("unsloth", "Unsloth (fast finetuning)", recommended=True),
            T("graphrag", "GraphRAG", recommended=True),
            T("llamaindex", "LlamaIndex", recommended=True),
            T("rerankers", "Rerankers (cross-encoders)", recommended=True),
            T("vector-db-comparison", "Vector DBs: Weaviate / Qdrant / Milvus / pgvector", recommended=True),
        ),
    ),
    Domain(
        "04-agentic-ai",
        "Agentic AI",
        "Agent frameworks, protocols, orchestration, and reasoning loops.",
        (
            T("model-context-protocol", "Model Context Protocol (MCP)"),
            T("agent-to-agent", "Agent-to-Agent (A2A)"),
            T("agent-development-kit", "Agent Development Kit (ADK)"),
            T("langchain", "LangChain"),
            T("langgraph", "LangGraph"),
            T("crewai", "CrewAI"),
            T("autogen", "AutoGen"),
            T("babyagi", "BabyAGI"),
            T("semantic-kernel", "Semantic Kernel"),
            T("react", "ReAct (Reasoning + Acting)"),
            T("llamaindex-agents", "LlamaIndex Agents", recommended=True),
            T("openai-agents-sdk", "OpenAI Agents SDK / Swarm", recommended=True, note="needs API key"),
            T("haystack", "Haystack", recommended=True),
            T("pydanticai", "PydanticAI", recommended=True),
            T("smolagents", "smolagents", recommended=True),
            T("letta-memgpt", "Letta / MemGPT (agent memory)", recommended=True),
        ),
    ),
    Domain(
        "05-speech-audio",
        "Speech & Audio",
        "STT, TTS, voice, phonetics, and audio processing.",
        (
            T("ffmpeg", "ffmpeg", note="CLI"),
            T("whisper-stt", "Whisper STT"),
            T("coqui-tts", "Coqui TTS"),
            T("piper-tts", "Piper TTS"),
            T("elevenlabs", "ElevenLabs", note="needs API key"),
            T("google-cloud-tts", "Google Cloud TTS", note="needs API key"),
            T("espeak-ng", "espeak-ng", note="CLI"),
            T("azure-speech", "Azure Speech Services", note="needs API key"),
            T("amazon-polly", "Amazon Polly", note="needs AWS creds"),
            T("wav2vec", "Wav2Vec 2.0"),
            T("deepspeech", "DeepSpeech"),
            T("tacotron", "Tacotron 2"),
            T("vits", "VITS"),
            T("phoneme-analysis", "Phoneme Analysis"),
            T("nvidia-nemo", "NVIDIA NeMo", recommended=True),
            T("speechbrain", "SpeechBrain", recommended=True),
            T("faster-whisper-whisperx", "faster-whisper / WhisperX", recommended=True),
            T("pyannote-diarization", "pyannote (speaker diarization)", recommended=True),
            T("bark", "Bark (generative TTS)", recommended=True),
            T("styletts2", "StyleTTS 2", recommended=True),
            T("librosa-torchaudio", "librosa & torchaudio", recommended=True),
            T("demucs", "Demucs (source separation)", recommended=True),
        ),
    ),
    Domain(
        "07-proprietary-coding-ai",
        "Proprietary Models & Coding AI",
        "Hosted model APIs and AI coding assistants/IDEs.",
        (
            T("google-gemini", "Google Gemini", note="needs API key"),
            T("google-vertex", "Google Vertex AI", note="needs GCP creds"),
            T("grok", "Grok", note="needs API key"),
            T("llama", "LLaMA", note="HF weights"),
            T("mistral", "Mistral", note="HF weights / API"),
            T("anthropic-claude-api", "Anthropic Claude API", recommended=True, note="needs API key"),
            T("perplexity", "Perplexity API", recommended=True, note="needs API key"),
            T("deepseek", "DeepSeek", recommended=True, note="API / HF weights"),
            T("qwen", "Qwen", recommended=True, note="API / HF weights"),
        ),
    ),
    Domain(
        "08-architectures",
        "Architectures",
        "Neural-network building blocks, implemented from scratch in PyTorch.",
        (
            T("rnn", "Recurrent Neural Networks (RNN)"),
            T("cnn", "Convolutional Neural Networks (CNN)"),
            T("lstm", "Long Short-Term Memory (LSTM)"),
            T("gan", "Generative Adversarial Networks (GAN)"),
            T("bert", "BERT"),
            T("transformer", "Transformer"),
            T("t5", "T5"),
            T("attention-mechanisms", "Attention Mechanisms"),
            T("encoder-decoder", "Encoder-Decoder Models"),
            T("vae", "Variational Autoencoders (VAE)"),
            T("resnet", "ResNet"),
            T("u-net", "U-Net"),
            T("gnn", "Graph Neural Networks (GNN)"),
            T("diffusion-models", "Diffusion Models"),
            T("mixture-of-experts", "Mixture of Experts (MoE)", recommended=True),
            T("mamba-ssm", "Mamba / State-Space Models", recommended=True),
            T("vision-transformer", "Vision Transformer (ViT)", recommended=True),
            T("clip", "CLIP", recommended=True),
            T("diffusion-transformer", "Diffusion Transformer (DiT)", recommended=True),
            T("flow-matching", "Flow Matching", recommended=True),
            T("normalizing-flows", "Normalizing Flows", recommended=True),
            T("autoencoders", "Autoencoders (vanilla/denoising)", recommended=True),
        ),
    ),
    Domain(
        "09-procedural-generation",
        "Procedural Generation",
        "Algorithms for generating content: noise, grammars, automata, and PCG.",
        (
            T("tracery", "Tracery"),
            T("perlin-noise", "Perlin Noise"),
            T("wave-function-collapse", "Wave Function Collapse"),
            T("l-systems", "L-Systems"),
            T("markov-chains", "Markov Chains"),
            T("context-free-grammars", "Context-Free Grammars"),
            T("cellular-automata", "Cellular Automata"),
            T("noise-simplex-worley", "Noise Functions (Simplex, Worley)"),
            T("pcg-algorithms", "PCG Algorithms (overview)"),
            T("rule-based-generation", "Rule-Based Generation"),
            T("poisson-disk-sampling", "Poisson-Disk Sampling", recommended=True),
            T("voronoi-delaunay", "Voronoi / Delaunay", recommended=True),
            T("diamond-square", "Diamond-Square (heightmaps)", recommended=True),
            T("bsp-dungeon-generation", "BSP Dungeon Generation", recommended=True),
            T("drunkards-walk", "Drunkard's Walk", recommended=True),
            T("gan-diffusion-pcg", "GAN/Diffusion for PCG", recommended=True),
        ),
    ),
    Domain(
        "10-data-analysis-research",
        "Data Analysis & Research",
        "Statistical analysis, qualitative tools, and research workflows.",
        (
            T("r-language", "R", runnable=False, note="R kernel / rpy2"),
            T("lme4", "lme4 (mixed models)", runnable=False, note="R"),
            T("montreal-forced-aligner", "Montreal Forced Aligner", note="conda CLI"),
            T("numpy-pandas-scipy", "Python: NumPy, Pandas, SciPy"),
            T("matplotlib", "Matplotlib"),
            T("ggplot2", "ggplot2", runnable=False, note="R"),
            T("statistical-modeling", "Statistical Modeling"),
            T("mixed-effects-models", "Mixed-Effects Models"),
            T("polars", "Polars", recommended=True),
            T("duckdb", "DuckDB", recommended=True),
            T("statsmodels", "statsmodels", recommended=True),
            T("pymc", "PyMC (Bayesian)", recommended=True),
            T("seaborn", "seaborn", recommended=True),
            T("plotly", "Plotly", recommended=True),
            T("quarto", "Quarto", recommended=True, runnable=False, note="CLI/publishing"),
        ),
    ),
    Domain(
        "11-devops-mlops-infra",
        "DevOps/MLOps & Infra",
        "The legacy library: self-hosting AI/ML on Kubernetes/AWS — serving, "
        "distributed training, GPU components, orchestration, storage, networking. "
        "Topics are discovered from the filesystem (relocated from the original repo root).",
        topics=(),
        source="filesystem",
    ),
]

ROOT = Path(__file__).resolve().parent
NOTEBOOKS_DIR = ROOT / "notebooks"


def domain_by_dir(d: str) -> Domain | None:
    return next((dom for dom in DOMAINS if dom.dir == d), None)


def domain_path(domain: Domain) -> Path:
    """Where a domain's notebooks live.

    `Domain.dir` is always relative to the notebooks root, so `/render/<rel>` and the
    library's paths are the same string everywhere. A generated subject resolves
    against `subjects_dir()` instead, so relocating that (tests) moves its curriculum
    and its notebooks together.
    """
    if domain.source == "subject":
        return subjects_dir().parent / domain.dir
    return NOTEBOOKS_DIR / domain.dir


def topic_path(domain: Domain, topic: Topic) -> Path:
    return domain_path(domain) / f"{topic.slug}.ipynb"


def all_manifest_topics() -> list[tuple[Domain, Topic]]:
    return [(d, t) for d in DOMAINS for t in d.topics]


# ---------------------------------------------------------------------------
# User-defined subjects
#
# Same shape as the seed manifest above, but data-driven: a Subject is generated
# per user goal (praxis/curriculum_gen.py) and stored as JSON. Its modules ARE
# Domains, so the scaffolder, the launcher and the gate need no special case.
# ---------------------------------------------------------------------------

Module = Domain  # a subject's modules are Domains: a titled group of topics

# notebooks/subjects/<slug>/curriculum.json + notebooks/subjects/<slug>/<NN-module>/*.ipynb
SUBJECTS_ROOT = "subjects"
CURRICULUM_FILE = "curriculum.json"

SLUG_MAX = 60


class CurriculumError(ValueError):
    """A curriculum payload could not be read as a subject."""


def subjects_dir() -> Path:
    """Where generated subjects live — the active storage backend decides.

    A user's subjects are their data, not part of the shipped library, so they sit under
    `praxis.storage`'s root (the app-data directory by default) rather than beside the
    seed notebooks. `PRAXIS_SUBJECTS_DIR` still relocates just this leaf, which is how
    the tests keep out of a developer's real storage.
    """
    return storage.subjects_dir()


def slugify(text: str, fallback: str = "") -> str:
    """Kebab-case a title into something safe as a directory or file stem."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:SLUG_MAX]
    return slug.strip("-") or fallback


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _unique(slug: str, used: set[str]) -> str:
    """Two topics that slugify the same would overwrite one notebook — suffix instead."""
    candidate, n = slug, 2
    while candidate in used:
        candidate, n = f"{slug}-{n}", n + 1
    used.add(candidate)
    return candidate


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Subject:
    """One user-defined subject: the goal, and the curriculum generated for it."""

    slug: str
    title: str
    goal: str = ""          # the free text the user typed
    blurb: str = ""         # a one-line description of the curriculum
    modules: tuple[Domain, ...] = ()
    created: str = ""       # ISO-8601 UTC
    model: str = ""         # provenance: which model wrote this curriculum
    source: str = "generated"  # "generated" | "seed"

    @property
    def n_topics(self) -> int:
        return sum(len(m.topics) for m in self.modules)

    @property
    def dir(self) -> Path:
        return subjects_dir() / self.slug

    @property
    def path(self) -> Path:
        return self.dir / CURRICULUM_FILE

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "title": self.title,
            "goal": self.goal,
            "blurb": self.blurb,
            "created": self.created,
            "model": self.model,
            "source": self.source,
            "n_topics": self.n_topics,
            "modules": [
                {
                    "dir": m.dir,
                    "title": m.title,
                    "blurb": m.blurb,
                    "topics": [
                        {
                            "slug": t.slug,
                            "title": t.title,
                            "runnable": t.runnable,
                            "recommended": t.recommended,
                            "note": t.note,
                        }
                        for t in m.topics
                    ],
                }
                for m in self.modules
            ],
        }


def _topic_from_dict(raw: object, used: set[str]) -> Topic:
    if not isinstance(raw, dict):
        raise CurriculumError(f"a topic must be an object, got {type(raw).__name__}")
    title = _text(raw.get("title"))
    if not title:
        raise CurriculumError("a topic is missing its title")
    slug = slugify(raw.get("slug") or title)
    if not slug:
        raise CurriculumError(f"topic {title!r} has no usable slug")
    return Topic(
        slug=_unique(slug, used),
        title=title,
        runnable=bool(raw.get("runnable", True)),
        recommended=bool(raw.get("recommended", False)),
        note=_text(raw.get("note")),
    )


def _module_dir(subject_slug: str, raw: dict, index: int, title: str) -> str:
    """Keep a stored dir (renaming a subject must not orphan its notebooks)."""
    stored = _text(raw.get("dir"))
    prefix = f"{SUBJECTS_ROOT}/{subject_slug}/"
    if stored:
        if not stored.startswith(prefix) or ".." in stored.split("/"):
            raise CurriculumError(f"module dir {stored!r} escapes {prefix}")
        return stored
    slug = slugify(raw.get("slug") or title, fallback=f"module-{index}")
    return f"{prefix}{index:02d}-{slug}"


def _module_from_dict(raw: object, index: int, subject_slug: str) -> Domain:
    if not isinstance(raw, dict):
        raise CurriculumError(f"a module must be an object, got {type(raw).__name__}")
    title = _text(raw.get("title")) or f"Module {index}"
    topics_raw = raw.get("topics")
    if not isinstance(topics_raw, list) or not topics_raw:
        raise CurriculumError(f"module {title!r} has no topics")
    used: set[str] = set()
    return Domain(
        dir=_module_dir(subject_slug, raw, index, title),
        title=title,
        blurb=_text(raw.get("blurb")),
        topics=tuple(_topic_from_dict(t, used) for t in topics_raw),
        source="subject",
    )


def subject_from_dict(
    raw: object, *, slug: str = "", goal: str = "", model: str = ""
) -> Subject:
    """Normalize a curriculum payload — freshly generated or read back from disk.

    Lenient about what the model returns (slugs, dirs, flags and blurbs are all
    derived when absent) and strict about what would break the scaffolder: every
    subject needs a slug, a title, and at least one module holding titled topics.
    """
    if not isinstance(raw, dict):
        raise CurriculumError(f"a curriculum must be an object, got {type(raw).__name__}")
    title = _text(raw.get("title")) or _text(raw.get("subject"))
    goal = goal or _text(raw.get("goal"))
    if not title:
        title = goal[:80] or ""
    if not title:
        raise CurriculumError("curriculum is missing its title")
    subject_slug = slugify(slug or raw.get("slug") or title)
    if not subject_slug:
        raise CurriculumError(f"subject {title!r} has no usable slug")

    modules_raw = raw.get("modules")
    if not isinstance(modules_raw, list) or not modules_raw:
        raise CurriculumError(f"curriculum {title!r} has no modules")
    modules = tuple(
        _module_from_dict(m, i, subject_slug) for i, m in enumerate(modules_raw, start=1)
    )
    dirs = [m.dir for m in modules]
    if len(set(dirs)) != len(dirs):
        raise CurriculumError(f"curriculum {title!r} has two modules in the same directory")

    return Subject(
        slug=subject_slug,
        title=title,
        goal=goal,
        blurb=_text(raw.get("blurb")) or _text(raw.get("description")),
        modules=modules,
        created=_text(raw.get("created")) or _now(),
        model=model or _text(raw.get("model")),
        source=_text(raw.get("source")) or "generated",
    )


def save_subject(subject: Subject) -> Path:
    """Persist a subject's curriculum. Returns the file written."""
    path = subject.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(subject.to_dict(), indent=2) + "\n")
    return path


def load_subject(slug: str) -> Subject:
    path = subjects_dir() / slugify(slug) / CURRICULUM_FILE
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise CurriculumError(f"no subject {slug!r} at {path}") from exc
    except (OSError, ValueError) as exc:
        raise CurriculumError(f"could not read {path}: {exc}") from exc
    return subject_from_dict(raw, slug=slug)


def all_subjects() -> list[Subject]:
    """Every persisted subject, newest first. Unreadable ones are skipped, not fatal."""
    root = subjects_dir()
    if not root.is_dir():
        return []
    found = []
    for entry in sorted(root.iterdir()):
        if not (entry / CURRICULUM_FILE).is_file():
            continue
        try:
            found.append(load_subject(entry.name))
        except CurriculumError:
            continue  # user data: a broken file must not take down the library
    return sorted(found, key=lambda s: (s.created, s.slug), reverse=True)


def seed_subject() -> Subject:
    """The built-in domains, presented as one subject alongside generated ones."""
    return Subject(
        slug="seed",
        title="Praxis seed library",
        goal="The hand-written study curriculum Praxis ships with.",
        blurb="Eleven domains of AI/ML tooling, kept as examples of a finished tutorial.",
        modules=tuple(DOMAINS),
        source="seed",
    )


def all_curricula() -> list[Subject]:
    """The seed curriculum plus every user-defined subject."""
    return [seed_subject(), *all_subjects()]


if __name__ == "__main__":
    listed = sum(1 for d in DOMAINS for t in d.topics if not t.recommended)
    rec = sum(1 for d in DOMAINS for t in d.topics if t.recommended)
    print(f"{len(DOMAINS)} domains; {listed} listed + {rec} recommended = "
          f"{listed + rec} manifest topics (domains 1-10).")
    for d in DOMAINS:
        if d.source == "manifest":
            print(f"  {d.dir:42} {len(d.topics):3} topics")
        else:
            print(f"  {d.dir:42}  (filesystem)")
    subjects = all_subjects()
    print(f"\n{len(subjects)} user-defined subject(s) in {subjects_dir()}:")
    for s in subjects:
        print(f"  {s.slug:42} {len(s.modules):3} modules, {s.n_topics:3} topics")

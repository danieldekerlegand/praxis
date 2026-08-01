#!/usr/bin/env python3
"""Single source of truth for the Praxis seed tutorial library.

Defines the 11 study domains and their topics. Drives:
  - scaffold_notebooks.py   (creates blank notebook scaffolds + reorgs the legacy 64)
  - launcher/app.py         (sidebar navigation + completion status)
  - ralph/generate_tasklists.py (one ralphy task per notebook below the rubric bar)
  - CURRICULUM.md / docs/gap-analysis.md (generated human indices)

Domains 1-10 are the new study curriculum (explicit topic lists below).
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

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Topic:
    slug: str
    title: str
    runnable: bool = True
    recommended: bool = False
    note: str = ""


@dataclass(frozen=True)
class Domain:
    dir: str  # notebooks/<dir>/
    title: str
    blurb: str
    topics: tuple[Topic, ...] = ()
    source: str = "manifest"  # "manifest" (topics below) or "filesystem" (scan disk)


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


def topic_path(domain: Domain, topic: Topic) -> Path:
    return NOTEBOOKS_DIR / domain.dir / f"{topic.slug}.ipynb"


def all_manifest_topics() -> list[tuple[Domain, Topic]]:
    return [(d, t) for d in DOMAINS for t in d.topics]


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

# Technologies

> **Status:** Current · **Updated:** 2026-08-15 · **Owner:** praxis

The catalog of subjects praxis covers. A linked entry has a notebook; an entry marked
_notebook not yet written_ is a planned subject with nothing behind it yet — the backfill
queue, stated plainly rather than as a link that 404s.

## AI/ML Workloads

* [AWS SageMaker](notebooks/11-devops-mlops-infra/sagemaker.ipynb)
* [AWS Bedrock](notebooks/11-devops-mlops-infra/bedrock.ipynb)
* [NVIDIA GPU Operator and MIG](notebooks/11-devops-mlops-infra/nvidia-gpu-components/nvidia-gpu-operator-mig.ipynb)
* [Karpenter and Cluster Autoscaler](notebooks/11-devops-mlops-infra/karpenter-cluster-autoscaler.ipynb)
* Kubeflow and Volcano — _notebook not yet written_

## AI/ML workloads

* [Generative AI model deployment](notebooks/11-devops-mlops-infra/techniques/model-deployment.ipynb) (e.g., deploying a model to Hugging Face Hub, model weights in an Amazon S3 bucket, or similar tool)
* AI agents — _notebook not yet written_ (e.g., autonomous or multi-agent systems using LLMs for task planning, tool calling, and orchestration)

## Worker node operating systems for AI/ML workloads

* Bottlerocket — _notebook not yet written_

## Storage CSI Drivers for AI/ML workloads on Amazon EKS

* Mountpoint for Amazon S3 — _notebook not yet written_
* Amazon FSx for Lustre — _notebook not yet written_
* Amazon FSx for OpenZFS — _notebook not yet written_
* Amazon EFS — _notebook not yet written_
* Amazon EBS — _notebook not yet written_

## Fine-tuning techniques for AI/ML models

* [Supervised Fine-Tuning (SFT)](notebooks/11-devops-mlops-infra/techniques/supervised-fine-tuning.ipynb) (e.g., training on task-specific labeled datasets)
* [Parameter-Efficient Fine-Tuning (PEFT)](notebooks/11-devops-mlops-infra/techniques/parameter-efficient-fine-tuning.ipynb) (e.g., LoRA, QLoRA, Adapters)
* [Reinforcement Learning (RL)](notebooks/11-devops-mlops-infra/techniques/reinforcement-learning.ipynb) (e.g., RLHF with PPO)
* [Full Parameter Fine-Tuning](notebooks/11-devops-mlops-infra/techniques/full-parameter-fine-tuning.ipynb) (e.g., updating all model weights on new data)
* [Instruction Fine-Tuning](notebooks/11-devops-mlops-infra/techniques/instruction-fine-tuning.ipynb) (e.g., fine-tuning on instruction-response pairs for chat models)
* [Continued Pre-Training](notebooks/11-devops-mlops-infra/techniques/continued-pre-training.ipynb) (e.g., unsupervised fine-tuning on domain-specific corpora)
* [Transfer Learning](notebooks/11-devops-mlops-infra/techniques/transfer-learning.ipynb) (e.g., adapting pre-trained models to new tasks or domains)
* [Domain-Specific Fine-Tuning](notebooks/11-devops-mlops-infra/techniques/domain-specific-fine-tuning.ipynb) (e.g., customizing models for industry-specific data like healthcare or finance)
* [Sequential Fine-Tuning](notebooks/11-devops-mlops-infra/techniques/sequential-fine-tuning.ipynb) (e.g., fine-tuning in stages across multiple tasks)

## Persistent challenges when running real-time online inference for AI/ML workloads

* Resource allocation and scaling — _notebook not yet written_ (e.g., GPU/CPU provisioning for variable traffic, auto-scaling delays during demand spikes, or handling large models in memory)
* Data management — _notebook not yet written_ (e.g., real-time data ingestion/streaming, input preprocessing bottlenecks, or caching mechanisms for frequent queries)
* Cost optimization — _notebook not yet written_ (e.g., high compute expenses for always-on endpoints, inefficient utilization during low traffic, or over-provisioning)
* Dependency and environment setup — _notebook not yet written_ (e.g., managing serving container images, libraries like vLLM/TGI, or ensuring reproducible deployments)
* Monitoring and observability — _notebook not yet written_ (e.g., tracking inference metrics like latency/throughput with Prometheus/Grafana, error diagnosis in production, or alerting on anomalies)
* Integration with other services — _notebook not yet written_ (e.g., connecting to API gateways/load balancers, hybrid workflows with SageMaker/Bedrock, or IAM/security for endpoints)
* Performance tuning — _notebook not yet written_ (e.g., optimizing for low latency/high throughput, handling concurrent requests with tools like TensorRT-LLM, or hardware-specific inference tweaks)
* Cluster management — _notebook not yet written_ (e.g., node provisioning for inference pods, handling upgrades without downtime, or managing failures in EKS)
* Security and compliance — _notebook not yet written_ (e.g., protecting endpoints from attacks, data privacy in real-time processing, or regulatory requirements for inference outputs)

## Persistent challenges when fine-tuning AI/ML models

* Resource allocation and scaling — _notebook not yet written_ (e.g., GPU/CPU provisioning, auto-scaling delays, or handling large models)
* Data management — _notebook not yet written_ (e.g., loading large datasets, storage integration with EFS/EBS/FSx, or data preprocessing bottlenecks)
* Cost optimization — _notebook not yet written_ (e.g., high compute expenses, spot instance interruptions, or inefficient resource utilization)
* Dependency and environment setup — _notebook not yet written_ (e.g., managing container images, libraries like PyTorch/Hugging Face, or reproducibility issues)
* Monitoring and observability — _notebook not yet written_ (e.g., tracking metrics with Prometheus/Grafana, error diagnosis in distributed training, or model performance insights)
* Data integration with other services — _notebook not yet written_ (e.g., connecting to SageMaker/Bedrock for hybrid workflows, or IAM/security configurations)
* Performance tuning — _notebook not yet written_ (e.g., optimizing for throughput/latency, handling distributed fine-tuning with tools like DeepSpeed, or hardware-specific tweaks)
* Cluster management — _notebook not yet written_ (e.g., node provisioning, upgrades, or handling failures in EKS)
* Security and compliance — _notebook not yet written_ (e.g., data privacy, access controls, or regulatory requirements)

## Selected open-weight models for fine-tuning

* TTS/STT — _notebook not yet written_
* Diffusion — _notebook not yet written_ (e.g., diffusers or stable-diffusion for image generation)
* Video — _notebook not yet written_ (e.g., video-diffusion or nvidia/nemo for video generation)
* meta-llama/Meta-Llama-3.1-70B-Instruct — _notebook not yet written_
* mistralai/Mistral-7B-Instruct-v0.3 — _notebook not yet written_
* google/gemma-2-27b-it — _notebook not yet written_

## Selected open-weight models for real-time inference

* openai/gpt-oss-20b — _notebook not yet written_
* meta-llama/Llama-3-8B-Instruct — _notebook not yet written_
* google/gemma-2-9b-it — _notebook not yet written_

## AWS networking adapters for AI/ML workloads on Amazon EKS

* [Elastic Fabric Adapter (EFA)](notebooks/11-devops-mlops-infra/efa.ipynb)
* [Elastic Network Adapter (ENA)](notebooks/11-devops-mlops-infra/ena.ipynb)

## Methods or tools to pre-pull container images

* SOCI Snapshotter — _notebook not yet written_
* DaemonSets for pre-pulling — _notebook not yet written_
* Kubernetes Jobs for pre-pulling — _notebook not yet written_
* Baking images into custom AMIs — _notebook not yet written_
* Bottlerocket data volume for prefetching — _notebook not yet written_
* Bootstrap scripts to pull images on node startup — _notebook not yet written_
* Amazon ECR pull-through cache — _notebook not yet written_

## Model serving libraries for AI/ML workloads

* [BentoML / OpenLLM](notebooks/11-devops-mlops-infra/model-serving-libraries/bentoml-openllm.ipynb)
* [DeepSpeed-MII](notebooks/11-devops-mlops-infra/model-serving-libraries/deepspeed-mii.ipynb)
* [Llama.cpp](notebooks/11-devops-mlops-infra/model-serving-libraries/llama-cpp.ipynb)
* [LMDeploy](notebooks/11-devops-mlops-infra/model-serving-libraries/lmdeploy.ipynb)
* [MLServer](notebooks/11-devops-mlops-infra/model-serving-libraries/mlserver.ipynb)
* [Mosec](notebooks/11-devops-mlops-infra/model-serving-libraries/mosec.ipynb)
* [Ollama](notebooks/11-devops-mlops-infra/model-serving-libraries/ollama.ipynb)
* [SGLang](notebooks/11-devops-mlops-infra/model-serving-libraries/sglang.ipynb)
* [TensorFlow Serving](notebooks/11-devops-mlops-infra/model-serving-libraries/tensorflow-serving.ipynb)
* [TensorRT-LLM](notebooks/11-devops-mlops-infra/model-serving-libraries/tensorrt-llm.ipynb)
* [TGI](notebooks/11-devops-mlops-infra/model-serving-libraries/tgi.ipynb)
* [TorchServe](notebooks/11-devops-mlops-infra/model-serving-libraries/torchserve.ipynb)
* [Triton Inference Server](notebooks/11-devops-mlops-infra/model-serving-libraries/triton-inference-server.ipynb)
* [vLLM](notebooks/03-llm-inference-training-optimization/vllm.ipynb)
* [Python frameworks (e.g., FastAPI)](notebooks/11-devops-mlops-infra/model-serving-libraries/fastapi-serving.ipynb)

## Tools for distributed training in AI/ML workloads

* [Ray Train](notebooks/11-devops-mlops-infra/distributed-training-tools/ray-train.ipynb) (e.g., distributed training with Ray clusters)
* [Hugging Face Accelerate](notebooks/11-devops-mlops-infra/distributed-training-tools/huggingface-accelerate.ipynb) (e.g., multi-GPU/TPU training with minimal code changes)
* [DeepSpeed](notebooks/11-devops-mlops-infra/distributed-training-tools/deepspeed.ipynb) (e.g., ZeRO optimization for large model training)
* [Horovod](notebooks/11-devops-mlops-infra/distributed-training-tools/horovod.ipynb) (e.g., distributed training framework for TensorFlow/Keras/PyTorch)
* [torchX](notebooks/11-devops-mlops-infra/distributed-training-tools/torchx.ipynb) (e.g., PyTorch job launcher for distributed workloads)
* [Kubeflow Training Operators](notebooks/11-devops-mlops-infra/distributed-training-tools/kubeflow-training-operators.ipynb) (e.g., PyTorchJob, TFJob for managed distributed training)
* [PyTorch Distributed](notebooks/11-devops-mlops-infra/distributed-training-tools/pytorch-distributed.ipynb) (e.g., DDP, FSDP for native PyTorch multi-node training)
* [TensorFlow Distribution Strategies](notebooks/11-devops-mlops-infra/distributed-training-tools/tensorflow-distribution-strategies.ipynb) (e.g., MirroredStrategy, TPUStrategy for multi-device training)

## Advanced NVIDIA GPU components to optimize AI/ML workloads

* [NVIDIA Container Toolkit](notebooks/11-devops-mlops-infra/nvidia-gpu-components/nvidia-container-toolkit.ipynb)
* [DCGM Exporter](notebooks/11-devops-mlops-infra/nvidia-gpu-components/dcgm-exporter.ipynb)
* [GPU Feature Discovery](notebooks/11-devops-mlops-infra/nvidia-gpu-components/gpu-feature-discovery.ipynb)
* [Multi-Instance GPUs (MIGs)](notebooks/11-devops-mlops-infra/nvidia-gpu-components/multi-instance-gpus.ipynb)
* [MIG Manager](notebooks/11-devops-mlops-infra/nvidia-gpu-components/mig-manager.ipynb)
* [Time-Slicing for GPU sharing](notebooks/11-devops-mlops-infra/nvidia-gpu-components/time-slicing.ipynb)
* [Multi-Process Service (MPS) for GPU sharing](notebooks/11-devops-mlops-infra/nvidia-gpu-components/multi-process-service.ipynb)
* [Dynamic Resource Allocation (DRA) / NVIDIA DRA Driver](notebooks/11-devops-mlops-infra/nvidia-gpu-components/dynamic-resource-allocation.ipynb)
* [GPUDirect Storage (GDS)](notebooks/11-devops-mlops-infra/nvidia-gpu-components/gpudirect-storage.ipynb)

## Techniques to create or deploy models in AI/ML workloads

* Model Distillation — _notebook not yet written_ (e.g., knowledge transfer from large to small models for efficiency)
* [Pruning](notebooks/03-llm-inference-training-optimization/pruning.ipynb) (e.g., removing redundant weights or parameters to reduce model size)
* Quantization — _notebook not yet written_ (e.g., reducing weight precision like from FP32 to INT8 for faster inference)
* Low-Rank Approximation — _notebook not yet written_ (e.g., matrix factorization to compress layers)
* [Sparsity Induction](notebooks/03-llm-inference-training-optimization/sparsity-induction.ipynb) (e.g., encouraging zero weights during training)
* Model Compression via Ensembling — _notebook not yet written_ (e.g., combining multiple small models)

## Job orchestration or scheduling tools for AI/ML workloads

* [Slurm](notebooks/11-devops-mlops-infra/job-orchestration-tools/slurm.ipynb)
* [Run:ai](notebooks/11-devops-mlops-infra/job-orchestration-tools/runai.ipynb)
* [KAI Scheduler](notebooks/11-devops-mlops-infra/job-orchestration-tools/kai-scheduler.ipynb)
* [Kubeflow](notebooks/11-devops-mlops-infra/job-orchestration-tools/kubeflow.ipynb)
* [Argo Workflows](notebooks/11-devops-mlops-infra/job-orchestration-tools/argo-workflows.ipynb)
* [AWS Batch](notebooks/11-devops-mlops-infra/job-orchestration-tools/aws-batch.ipynb)
* [Volcano](notebooks/11-devops-mlops-infra/job-orchestration-tools/volcano.ipynb)
* [Kueue](notebooks/11-devops-mlops-infra/job-orchestration-tools/kueue.ipynb)
* [YuniKorn](notebooks/11-devops-mlops-infra/job-orchestration-tools/yunikorn.ipynb)
* [Airflow](notebooks/11-devops-mlops-infra/job-orchestration-tools/airflow.ipynb)
* [Ray Serve](notebooks/11-devops-mlops-infra/job-orchestration-tools/ray-serve.ipynb)
* [Kubernetes JobSets](notebooks/11-devops-mlops-infra/job-orchestration-tools/kubernetes-jobsets.ipynb)

## Symbolic AI & Logic Programming

* [SWI-Prolog](notebooks/01-symbolic-ai-logic/swi-prolog.ipynb)
* Ensemble — _notebook not yet written_
* Insimul DSL — _notebook not yet written_
* [Datalog](notebooks/01-symbolic-ai-logic/datalog.ipynb)
* ASP (Answer Set Programming) — _notebook not yet written_
* [CLIPS](notebooks/01-symbolic-ai-logic/clips.ipynb)
* [Pyke](notebooks/01-symbolic-ai-logic/pyke.ipynb)
* [Knowledge Graphs](notebooks/01-symbolic-ai-logic/knowledge-graphs.ipynb)
* OWL (Web Ontology Language) — _notebook not yet written_
* [SPARQL](notebooks/01-symbolic-ai-logic/sparql.ipynb)
* Social Physics — _notebook not yet written_

## AI Tools

* [PyTorch](notebooks/02-ai-ml-tooling/pytorch.ipynb)
* [Keras](notebooks/02-ai-ml-tooling/keras.ipynb)
* [TensorFlow](notebooks/02-ai-ml-tooling/tensorflow.ipynb)
* [MLFLow](notebooks/02-ai-ml-tooling/mlflow.ipynb)
* [Jupyter](notebooks/02-ai-ml-tooling/jupyter.ipynb)
* [HuggingFace](notebooks/02-ai-ml-tooling/huggingface.ipynb)

## LocalLLaMA

* GPT4All — _notebook not yet written_
* LLMUnity — _notebook not yet written_
* [llama.cpp](notebooks/11-devops-mlops-infra/model-serving-libraries/llama-cpp.ipynb)
* [Ollama](notebooks/11-devops-mlops-infra/model-serving-libraries/ollama.ipynb)
* OpenHands — _notebook not yet written_
* Bolt.diy — _notebook not yet written_
* Continue — _notebook not yet written_
* Cline — _notebook not yet written_
* Dyad — _notebook not yet written_
* December — _notebook not yet written_

## LLM Training

* [Open R1](notebooks/03-llm-inference-training-optimization/open-r1.ipynb)
* [MinGPT](notebooks/03-llm-inference-training-optimization/mingpt.ipynb)
* [Megatron LM](notebooks/03-llm-inference-training-optimization/megatron-lm.ipynb)
* Finetune Tranformer LM — _notebook not yet written_

## Agentic AI

* Model Context Protocol (MCP) — _notebook not yet written_
* Agent-to-Agent (A2A) — _notebook not yet written_
* Agent Development Kit (ADK) — _notebook not yet written_
* [LangChain](notebooks/04-agentic-ai/langchain.ipynb)
* [LangGraph](notebooks/04-agentic-ai/langgraph.ipynb)
* [CrewAI](notebooks/04-agentic-ai/crewai.ipynb)
* [AutoGen](notebooks/04-agentic-ai/autogen.ipynb)
* [BabyAGI](notebooks/04-agentic-ai/babyagi.ipynb)
* AgentGPT — _notebook not yet written_
* [Semantic Kernel](notebooks/04-agentic-ai/semantic-kernel.ipynb)
* ReAct (Reasoning + Acting) — _notebook not yet written_
* Dify — _notebook not yet written_
* Flowise — _notebook not yet written_

## Inference & Optimization

* [DSPy](notebooks/03-llm-inference-training-optimization/dspy.ipynb)
* Retrieval-Augmented Generation (RAG) — _notebook not yet written_
* [FAISS](notebooks/03-llm-inference-training-optimization/faiss.ipynb)
* [ChromaDB](notebooks/03-llm-inference-training-optimization/chromadb.ipynb)
* [Pinecone](notebooks/03-llm-inference-training-optimization/pinecone.ipynb)
* [Vector Embeddings](notebooks/03-llm-inference-training-optimization/vector-embeddings.ipynb)
* [Semantic Search](notebooks/03-llm-inference-training-optimization/semantic-search.ipynb)
* [Prompt Engineering](notebooks/03-llm-inference-training-optimization/prompt-engineering.ipynb)
* [Few-Shot Learning](notebooks/03-llm-inference-training-optimization/few-shot-learning.ipynb)
* Chain-of-Thought Prompting — _notebook not yet written_
* [LoRA/ControlNet](notebooks/03-llm-inference-training-optimization/lora-controlnet.ipynb)

## Speech & Audio

* [ffmpeg](notebooks/05-speech-audio/ffmpeg.ipynb)
* [Whisper STT](notebooks/05-speech-audio/whisper-stt.ipynb)
* [Coqui TTS](notebooks/05-speech-audio/coqui-tts.ipynb)
* [Piper TTS](notebooks/05-speech-audio/piper-tts.ipynb)
* [ElevenLabs](notebooks/05-speech-audio/elevenlabs.ipynb)
* [Google Cloud TTS](notebooks/05-speech-audio/google-cloud-tts.ipynb)
* [espeak-ng](notebooks/05-speech-audio/espeak-ng.ipynb)
* Oculus Lip Sync — _notebook not yet written_
* SALSA — _notebook not yet written_
* Azure Speech Services — _notebook not yet written_
* [Amazon Polly](notebooks/05-speech-audio/amazon-polly.ipynb)
* [Wav2Vec](notebooks/05-speech-audio/wav2vec.ipynb)
* [DeepSpeech](notebooks/05-speech-audio/deepspeech.ipynb)
* [Tacotron](notebooks/05-speech-audio/tacotron.ipynb)
* [VITS](notebooks/05-speech-audio/vits.ipynb)
* [Phoneme Analysis](notebooks/05-speech-audio/phoneme-analysis.ipynb)

## Game Engines & VR

* Unity — _notebook not yet written_
* Unity Sentis — _notebook not yet written_
* Unreal Engine 5 — _notebook not yet written_
* MetaHumans — _notebook not yet written_
* Oculus SDK — _notebook not yet written_
* OpenXR — _notebook not yet written_
* SteamVR — _notebook not yet written_
* XR Interaction Toolkit — _notebook not yet written_
* Godot — _notebook not yet written_
* WebXR — _notebook not yet written_
* A-Frame — _notebook not yet written_
* Spatial Audio SDK — _notebook not yet written_

## Programming Languages & Frameworks

* Python — _notebook not yet written_
* Rust — _notebook not yet written_
* Golang — _notebook not yet written_
* TypeScript — _notebook not yet written_
* Node.js — _notebook not yet written_
* C#/.NET — _notebook not yet written_
* Clojure — _notebook not yet written_
* Java — _notebook not yet written_
* [React](notebooks/04-agentic-ai/react.ipynb)
* Vue — _notebook not yet written_

## Mobile Development

* React Native — _notebook not yet written_
* Android (Java and Kotlin) — _notebook not yet written_
* iOS (Objective-C and Swift) — _notebook not yet written_

## Databases

* MongoDB — _notebook not yet written_
* PostgreSQL — _notebook not yet written_
* Drizzle ORM — _notebook not yet written_
* MySQL — _notebook not yet written_
* SQLite — _notebook not yet written_
* Redis — _notebook not yet written_
* Neo4j — _notebook not yet written_
* Prisma — _notebook not yet written_
* TypeORM — _notebook not yet written_
* Supabase — _notebook not yet written_

## DevOps & MLOps

* Terraform — _notebook not yet written_
* Helm — _notebook not yet written_
* Chef — _notebook not yet written_
* Ansible — _notebook not yet written_
* Kubernetes — _notebook not yet written_
* Jenkins — _notebook not yet written_
* Jenkins X — _notebook not yet written_
* CircleCI — _notebook not yet written_
* AWS — _notebook not yet written_
* GCP — _notebook not yet written_
* Grafana — _notebook not yet written_
* Sentry — _notebook not yet written_
* Datadog — _notebook not yet written_
* Kibana — _notebook not yet written_
* Prometheus — _notebook not yet written_
* GitHub Actions — _notebook not yet written_

## Machine Learning Architectures

* Recurrent Neural Networks (RNN) — _notebook not yet written_
* Convolutional Neural Networks (CNN) — _notebook not yet written_
* Long Short-Term Memory (LSTM) — _notebook not yet written_
* Generative Adversarial Networks (GAN) — _notebook not yet written_
* Bidirectional Encoder Representations from Transformers (BERT) — _notebook not yet written_
* [Transformer](notebooks/08-architectures/transformer.ipynb)
* Text-to-Text Transfer Transformer (T5) — _notebook not yet written_
* [Attention Mechanisms](notebooks/08-architectures/attention-mechanisms.ipynb)
* Encoder-Decoder Models — _notebook not yet written_
* Variational Autoencoders (VAE) — _notebook not yet written_
* [ResNet](notebooks/08-architectures/resnet.ipynb)
* [U-Net](notebooks/08-architectures/u-net.ipynb)
* Graph Neural Networks (GNN) — _notebook not yet written_
* [Diffusion Models](notebooks/08-architectures/diffusion-models.ipynb)

## Procedural Generation

* [Tracery](notebooks/09-procedural-generation/tracery.ipynb)
* [Perlin Noise](notebooks/09-procedural-generation/perlin-noise.ipynb)
* [Wave Function Collapse](notebooks/09-procedural-generation/wave-function-collapse.ipynb)
* [L-Systems](notebooks/09-procedural-generation/l-systems.ipynb)
* [Markov Chains](notebooks/09-procedural-generation/markov-chains.ipynb)
* [Context-Free Grammars](notebooks/09-procedural-generation/context-free-grammars.ipynb)
* [Cellular Automata](notebooks/09-procedural-generation/cellular-automata.ipynb)
* Noise Functions (Simplex, Worley) — _notebook not yet written_
* [PCG Algorithms](notebooks/09-procedural-generation/pcg-algorithms.ipynb)
* [Rule-Based Generation](notebooks/09-procedural-generation/rule-based-generation.ipynb)

## Data Analysis & Research Tools

* R — _notebook not yet written_
* [lme4](notebooks/10-data-analysis-research/lme4.ipynb)
* [Montreal Forced Aligner](notebooks/10-data-analysis-research/montreal-forced-aligner.ipynb)
* NVivo — _notebook not yet written_
* Python (NumPy, Pandas, SciPy) — _notebook not yet written_
* [Matplotlib](notebooks/10-data-analysis-research/matplotlib.ipynb)
* [ggplot2](notebooks/10-data-analysis-research/ggplot2.ipynb)
* SPSS — _notebook not yet written_
* Jupyter Notebooks — _notebook not yet written_
* Tableau — _notebook not yet written_
* [Statistical Modeling](notebooks/10-data-analysis-research/statistical-modeling.ipynb)
* [Mixed-Effects Models](notebooks/10-data-analysis-research/mixed-effects-models.ipynb)

## Proprietary Models and Coding AI

* [Google Gemini](notebooks/07-proprietary-coding-ai/google-gemini.ipynb)
* [Google Vertex](notebooks/07-proprietary-coding-ai/google-vertex.ipynb)
* GitHub Copilot — _notebook not yet written_
* Claude Code — _notebook not yet written_
* Windsurf — _notebook not yet written_
* Cursor — _notebook not yet written_
* Repl.it — _notebook not yet written_
* Base 44 — _notebook not yet written_
* [Grok](notebooks/07-proprietary-coding-ai/grok.ipynb)
* ChatGPT Codex — _notebook not yet written_
* [LLaMA](notebooks/07-proprietary-coding-ai/llama.ipynb)
* [Mistral](notebooks/07-proprietary-coding-ai/mistral.ipynb)
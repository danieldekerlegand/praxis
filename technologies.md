# Technologies

## AI/ML Workloads

* [AWS SageMaker](notebooks/critical-reasons-self-hosting/sagemaker.ipynb)
* [AWS Bedrock](notebooks/critical-reasons-self-hosting/bedrock.ipynb)
* [NVIDIA GPU Operator and MIG](notebooks/critical-reasons-self-hosting/nvidia-gpu-operator-mig.ipynb)
* [Karpenter and Cluster Autoscaler](notebooks/critical-reasons-self-hosting/karpenter-cluster-autoscaler.ipynb)
* [Kubeflow and Volcano](notebooks/critical-reasons-self-hosting/kubeflow-volcano.ipynb)

## AI/ML workloads

* [Generative AI model deployment](notebooks/ai-ml-workloads/model-deployment.ipynb) (e.g., deploying a model to Hugging Face Hub, model weights in an Amazon S3 bucket, or similar tool)
* [AI agents](notebooks/ai-ml-workloads/ai-agents.ipynb) (e.g., autonomous or multi-agent systems using LLMs for task planning, tool calling, and orchestration)

## Worker node operating systems for AI/ML workloads

* [Bottlerocket](notebooks/worker-node-os/bottlerocket.ipynb)

## Storage CSI Drivers for AI/ML workloads on Amazon EKS

* [Mountpoint for Amazon S3](notebooks/storage-csi-drivers/mountpoint-s3.ipynb)
* [Amazon FSx for Lustre](notebooks/storage-csi-drivers/fsx-lustre.ipynb)
* [Amazon FSx for OpenZFS](notebooks/storage-csi-drivers/fsx-openzfs.ipynb)
* [Amazon EFS](notebooks/storage-csi-drivers/efs.ipynb)
* [Amazon EBS](notebooks/storage-csi-drivers/ebs.ipynb)

## Fine-tuning techniques for AI/ML models

* [Supervised Fine-Tuning (SFT)](notebooks/fine-tuning-techniques/supervised-fine-tuning.ipynb) (e.g., training on task-specific labeled datasets)
* [Parameter-Efficient Fine-Tuning (PEFT)](notebooks/fine-tuning-techniques/parameter-efficient-fine-tuning.ipynb) (e.g., LoRA, QLoRA, Adapters)
* [Reinforcement Learning (RL)](notebooks/fine-tuning-techniques/reinforcement-learning.ipynb) (e.g., RLHF with PPO)
* [Full Parameter Fine-Tuning](notebooks/fine-tuning-techniques/full-parameter-fine-tuning.ipynb) (e.g., updating all model weights on new data)
* [Instruction Fine-Tuning](notebooks/fine-tuning-techniques/instruction-fine-tuning.ipynb) (e.g., fine-tuning on instruction-response pairs for chat models)
* [Continued Pre-Training](notebooks/fine-tuning-techniques/continued-pre-training.ipynb) (e.g., unsupervised fine-tuning on domain-specific corpora)
* [Transfer Learning](notebooks/fine-tuning-techniques/transfer-learning.ipynb) (e.g., adapting pre-trained models to new tasks or domains)
* [Domain-Specific Fine-Tuning](notebooks/fine-tuning-techniques/domain-specific-fine-tuning.ipynb) (e.g., customizing models for industry-specific data like healthcare or finance)
* [Sequential Fine-Tuning](notebooks/fine-tuning-techniques/sequential-fine-tuning.ipynb) (e.g., fine-tuning in stages across multiple tasks)

## Persistent challenges when running real-time online inference for AI/ML workloads

* [Resource allocation and scaling](notebooks/inference-challenges/resource-allocation-scaling.ipynb) (e.g., GPU/CPU provisioning for variable traffic, auto-scaling delays during demand spikes, or handling large models in memory)
* [Data management](notebooks/inference-challenges/data-management.ipynb) (e.g., real-time data ingestion/streaming, input preprocessing bottlenecks, or caching mechanisms for frequent queries)
* [Cost optimization](notebooks/inference-challenges/cost-optimization-inference.ipynb) (e.g., high compute expenses for always-on endpoints, inefficient utilization during low traffic, or over-provisioning)
* [Dependency and environment setup](notebooks/inference-challenges/dependency-setup.ipynb) (e.g., managing serving container images, libraries like vLLM/TGI, or ensuring reproducible deployments)
* [Monitoring and observability](notebooks/inference-challenges/monitoring-observability.ipynb) (e.g., tracking inference metrics like latency/throughput with Prometheus/Grafana, error diagnosis in production, or alerting on anomalies)
* [Integration with other services](notebooks/inference-challenges/service-integration.ipynb) (e.g., connecting to API gateways/load balancers, hybrid workflows with SageMaker/Bedrock, or IAM/security for endpoints)
* [Performance tuning](notebooks/inference-challenges/performance-tuning.ipynb) (e.g., optimizing for low latency/high throughput, handling concurrent requests with tools like TensorRT-LLM, or hardware-specific inference tweaks)
* [Cluster management](notebooks/inference-challenges/cluster-management.ipynb) (e.g., node provisioning for inference pods, handling upgrades without downtime, or managing failures in EKS)
* [Security and compliance](notebooks/inference-challenges/security-compliance.ipynb) (e.g., protecting endpoints from attacks, data privacy in real-time processing, or regulatory requirements for inference outputs)

## Persistent challenges when fine-tuning AI/ML models

* [Resource allocation and scaling](notebooks/fine-tuning-challenges/resource-allocation.ipynb) (e.g., GPU/CPU provisioning, auto-scaling delays, or handling large models)
* [Data management](notebooks/fine-tuning-challenges/data-management-ft.ipynb) (e.g., loading large datasets, storage integration with EFS/EBS/FSx, or data preprocessing bottlenecks)
* [Cost optimization](notebooks/fine-tuning-challenges/cost-optimization-ft.ipynb) (e.g., high compute expenses, spot instance interruptions, or inefficient resource utilization)
* [Dependency and environment setup](notebooks/fine-tuning-challenges/dependency-setup-ft.ipynb) (e.g., managing container images, libraries like PyTorch/Hugging Face, or reproducibility issues)
* [Monitoring and observability](notebooks/fine-tuning-challenges/monitoring-observability-ft.ipynb) (e.g., tracking metrics with Prometheus/Grafana, error diagnosis in distributed training, or model performance insights)
* [Data integration with other services](notebooks/fine-tuning-challenges/data-integration.ipynb) (e.g., connecting to SageMaker/Bedrock for hybrid workflows, or IAM/security configurations)
* [Performance tuning](notebooks/fine-tuning-challenges/performance-tuning-ft.ipynb) (e.g., optimizing for throughput/latency, handling distributed fine-tuning with tools like DeepSpeed, or hardware-specific tweaks)
* [Cluster management](notebooks/fine-tuning-challenges/cluster-management-ft.ipynb) (e.g., node provisioning, upgrades, or handling failures in EKS)
* [Security and compliance](notebooks/fine-tuning-challenges/security-compliance-ft.ipynb) (e.g., data privacy, access controls, or regulatory requirements)

## Selected open-weight models for fine-tuning

* [TTS/STT](notebooks/audio-models.ipynb)
* [Diffusion](notebooks/model-types/image-models.ipynb) (e.g., diffusers or stable-diffusion for image generation)
* [Video](notebooks/model-types/video-models.ipynb) (e.g., video-diffusion or nvidia/nemo for video generation)
* [meta-llama/Meta-Llama-3.1-70B-Instruct](notebooks/open-weight-models-fine-tuning/llama-3-70b.ipynb)
* [mistralai/Mistral-7B-Instruct-v0.3](notebooks/open-weight-models-fine-tuning/mistral-7b.ipynb)
* [google/gemma-2-27b-it](notebooks/open-weight-models-fine-tuning/gemma-2-27b.ipynb)

## Selected open-weight models for real-time inference

* [openai/gpt-oss-20b](notebooks/open-weight-models-inference/gpt-oss-20b.ipynb)
* [meta-llama/Llama-3-8B-Instruct](notebooks/open-weight-models-inference/llama-3-8b.ipynb)
* [google/gemma-2-9b-it](notebooks/open-weight-models-inference/gemma-2-9b.ipynb)

## AWS networking adapters for AI/ML workloads on Amazon EKS

* [Elastic Fabric Adapter (EFA)](notebooks/aws-networking-adapters/efa.ipynb)
* [Elastic Network Adapter (ENA)](notebooks/aws-networking-adapters/ena.ipynb)

## Methods or tools to pre-pull container images

* [SOCI Snapshotter](notebooks/container-image-pre-pulling/soci-snapshotter.ipynb)
* [DaemonSets for pre-pulling](notebooks/container-image-pre-pulling/daemonsets.ipynb)
* [Kubernetes Jobs for pre-pulling](notebooks/container-image-pre-pulling/kubernetes-jobs.ipynb)
* [Baking images into custom AMIs](notebooks/container-image-pre-pulling/custom-amis.ipynb)
* [Bottlerocket data volume for prefetching](notebooks/container-image-pre-pulling/bottlerocket-data-volume.ipynb)
* [Bootstrap scripts to pull images on node startup](notebooks/container-image-pre-pulling/bootstrap-scripts.ipynb)
* [Amazon ECR pull-through cache](notebooks/container-image-pre-pulling/ecr-pull-through-cache.ipynb)

## Model serving libraries for AI/ML workloads

* [BentoML / OpenLLM](notebooks/model-serving-libraries/bentoml-openllm.ipynb)
* [DeepSpeed-MII](notebooks/model-serving-libraries/deepspeed-mii.ipynb)
* [Llama.cpp](notebooks/model-serving-libraries/llama-cpp.ipynb)
* [LMDeploy](notebooks/model-serving-libraries/lmdeploy.ipynb)
* [MLServer](notebooks/model-serving-libraries/mlserver.ipynb)
* [Mosec](notebooks/model-serving-libraries/mosec.ipynb)
* [Ollama](notebooks/model-serving-libraries/ollama.ipynb)
* [SGLang](notebooks/model-serving-libraries/sglang.ipynb)
* [TensorFlow Serving](notebooks/model-serving-libraries/tensorflow-serving.ipynb)
* [TensorRT-LLM](notebooks/model-serving-libraries/tensorrt-llm.ipynb)
* [TGI](notebooks/model-serving-libraries/tgi.ipynb)
* [TorchServe](notebooks/model-serving-libraries/torchserve.ipynb)
* [Triton Inference Server](notebooks/model-serving-libraries/triton-inference-server.ipynb)
* [vLLM](notebooks/model-serving-libraries/vllm.ipynb)
* [Python frameworks (e.g., FastAPI)](notebooks/model-serving-libraries/fastapi-serving.ipynb)

## Tools for distributed training in AI/ML workloads

* [Ray Train](notebooks/distributed-training-tools/ray-train.ipynb) (e.g., distributed training with Ray clusters)
* [Hugging Face Accelerate](notebooks/distributed-training-tools/huggingface-accelerate.ipynb) (e.g., multi-GPU/TPU training with minimal code changes)
* [DeepSpeed](notebooks/distributed-training-tools/deepspeed.ipynb) (e.g., ZeRO optimization for large model training)
* [Horovod](notebooks/distributed-training-tools/horovod.ipynb) (e.g., distributed training framework for TensorFlow/Keras/PyTorch)
* [torchX](notebooks/distributed-training-tools/torchx.ipynb) (e.g., PyTorch job launcher for distributed workloads)
* [Kubeflow Training Operators](notebooks/distributed-training-tools/kubeflow-training-operators.ipynb) (e.g., PyTorchJob, TFJob for managed distributed training)
* [PyTorch Distributed](notebooks/distributed-training-tools/pytorch-distributed.ipynb) (e.g., DDP, FSDP for native PyTorch multi-node training)
* [TensorFlow Distribution Strategies](notebooks/distributed-training-tools/tensorflow-distribution-strategies.ipynb) (e.g., MirroredStrategy, TPUStrategy for multi-device training)

## Advanced NVIDIA GPU components to optimize AI/ML workloads

* [NVIDIA Container Toolkit](notebooks/nvidia-gpu-components/nvidia-container-toolkit.ipynb)
* [DCGM Exporter](notebooks/nvidia-gpu-components/dcgm-exporter.ipynb)
* [GPU Feature Discovery](notebooks/nvidia-gpu-components/gpu-feature-discovery.ipynb)
* [Multi-Instance GPUs (MIGs)](notebooks/nvidia-gpu-components/multi-instance-gpus.ipynb)
* [MIG Manager](notebooks/nvidia-gpu-components/mig-manager.ipynb)
* [Time-Slicing for GPU sharing](notebooks/nvidia-gpu-components/time-slicing.ipynb)
* [Multi-Process Service (MPS) for GPU sharing](notebooks/nvidia-gpu-components/multi-process-service.ipynb)
* [Dynamic Resource Allocation (DRA) / NVIDIA DRA Driver](notebooks/nvidia-gpu-components/dynamic-resource-allocation.ipynb)
* [GPUDirect Storage (GDS)](notebooks/nvidia-gpu-components/gpudirect-storage.ipynb)

## Techniques to create or deploy models in AI/ML workloads

* [Model Distillation](notebooks/model-deployment-techniques/model-distillation.ipynb) (e.g., knowledge transfer from large to small models for efficiency)
* [Pruning](notebooks/model-deployment-techniques/pruning.ipynb) (e.g., removing redundant weights or parameters to reduce model size)
* [Quantization](notebooks/model-deployment-techniques/quantization.ipynb) (e.g., reducing weight precision like from FP32 to INT8 for faster inference)
* [Low-Rank Approximation](notebooks/model-deployment-techniques/low-rank-approximation.ipynb) (e.g., matrix factorization to compress layers)
* [Sparsity Induction](notebooks/model-deployment-techniques/sparsity-induction.ipynb) (e.g., encouraging zero weights during training)
* [Model Compression via Ensembling](notebooks/model-deployment-techniques/model-compression-ensembling.ipynb) (e.g., combining multiple small models)

## Job orchestration or scheduling tools for AI/ML workloads

* [Slurm](notebooks/job-orchestration-tools/slurm.ipynb)
* [Run:ai](notebooks/job-orchestration-tools/runai.ipynb)
* [KAI Scheduler](notebooks/job-orchestration-tools/kai-scheduler.ipynb)
* [Kubeflow](notebooks/job-orchestration-tools/kubeflow.ipynb)
* [Argo Workflows](notebooks/job-orchestration-tools/argo-workflows.ipynb)
* [AWS Batch](notebooks/job-orchestration-tools/aws-batch.ipynb)
* [Volcano](notebooks/job-orchestration-tools/volcano.ipynb)
* [Kueue](notebooks/job-orchestration-tools/kueue.ipynb)
* [YuniKorn](notebooks/job-orchestration-tools/yunikorn.ipynb)
* [Airflow](notebooks/job-orchestration-tools/airflow.ipynb)
* [Ray Serve](notebooks/job-orchestration-tools/ray-serve.ipynb)
* [Kubernetes JobSets](notebooks/job-orchestration-tools/kubernetes-jobsets.ipynb)

## Symbolic AI & Logic Programming

* [SWI-Prolog](notebooks/symbolic-ai-logic-programming/swi-prolog.ipynb)
* [Ensemble](notebooks/symbolic-ai-logic-programming/ensemble.ipynb)
* [Insimul DSL](notebooks/symbolic-ai-logic-programming/insimul-dsl.ipynb)
* [Datalog](notebooks/symbolic-ai-logic-programming/datalog.ipynb)
* [ASP (Answer Set Programming)](notebooks/symbolic-ai-logic-programming/asp-answer-set-programming.ipynb)
* [CLIPS](notebooks/symbolic-ai-logic-programming/clips.ipynb)
* [Pyke](notebooks/symbolic-ai-logic-programming/pyke.ipynb)
* [Knowledge Graphs](notebooks/symbolic-ai-logic-programming/knowledge-graphs.ipynb)
* [OWL (Web Ontology Language)](notebooks/symbolic-ai-logic-programming/owl-web-ontology-language.ipynb)
* [SPARQL](notebooks/symbolic-ai-logic-programming/sparql.ipynb)
* [Social Physics](notebooks/symbolic-ai-logic-programming/social-physics.ipynb)

## AI Tools

* [PyTorch](notebooks/ai-tools/pytorch.ipynb)
* [Keras](notebooks/ai-tools/keras.ipynb)
* [TensorFlow](notebooks/ai-tools/tensorflow.ipynb)
* [MLFLow](notebooks/ai-tools/mlflow.ipynb)
* [Jupyter](notebooks/ai-tools/jupyter.ipynb)
* [HuggingFace](notebooks/ai-tools/huggingface.ipynb)

## LocalLLaMA

* [GPT4All](notebooks/local-llama/gpt4all.ipynb)
* [LLMUnity](notebooks/local-llama/llmunity.ipynb)
* [llama.cpp](notebooks/local-llama/llama-cpp.ipynb)
* [Ollama](notebooks/local-llama/ollama.ipynb)
* [OpenHands](notebooks/local-llama/openhands.ipynb)
* [Bolt.diy](notebooks/local-llama/bolt-diy.ipynb)
* [Continue](notebooks/local-llama/continue.ipynb)
* [Cline](notebooks/local-llama/cline.ipynb)
* [Dyad](notebooks/local-llama/dyad.ipynb)
* [December](notebooks/local-llama/december.ipynb)

## LLM Training

* [Open R1](notebooks/llm-training/open-r1.ipynb)
* [MinGPT](notebooks/llm-training/mingpt.ipynb)
* [Megatron LM](notebooks/llm-training/megatron-lm.ipynb)
* [Finetune Tranformer LM](notebooks/llm-training/finetune-tranformer-lm.ipynb)

## Agentic AI

* [Model Context Protocol (MCP)](notebooks/agentic-ai/model-context-protocol-mcp.ipynb)
* [Agent-to-Agent (A2A)](notebooks/agentic-ai/agent-to-agent-a2a.ipynb)
* [Agent Development Kit (ADK)](notebooks/agentic-ai/agent-development-kit-adk.ipynb)
* [LangChain](notebooks/agentic-ai/langchain.ipynb)
* [LangGraph](notebooks/agentic-ai/langgraph.ipynb)
* [CrewAI](notebooks/agentic-ai/crewai.ipynb)
* [AutoGen](notebooks/agentic-ai/autogen.ipynb)
* [BabyAGI](notebooks/agentic-ai/babyagi.ipynb)
* [AgentGPT](notebooks/agentic-ai/agentgpt.ipynb)
* [Semantic Kernel](notebooks/agentic-ai/semantic-kernel.ipynb)
* [ReAct (Reasoning + Acting)](notebooks/agentic-ai/react-reasoning-acting.ipynb)
* [Dify](notebooks/agentic-ai/dify.ipynb)
* [Flowise](notebooks/agentic-ai/flowise.ipynb)

## Inference & Optimization

* [DSPy](notebooks/inference-optimization/dspy.ipynb)
* [Retrieval-Augmented Generation (RAG)](notebooks/inference-optimization/retrieval-augmented-generation-rag.ipynb)
* [FAISS](notebooks/inference-optimization/faiss.ipynb)
* [ChromaDB](notebooks/inference-optimization/chromadb.ipynb)
* [Pinecone](notebooks/inference-optimization/pinecone.ipynb)
* [Vector Embeddings](notebooks/inference-optimization/vector-embeddings.ipynb)
* [Semantic Search](notebooks/inference-optimization/semantic-search.ipynb)
* [Prompt Engineering](notebooks/inference-optimization/prompt-engineering.ipynb)
* [Few-Shot Learning](notebooks/inference-optimization/few-shot-learning.ipynb)
* [Chain-of-Thought Prompting](notebooks/inference-optimization/chain-of-thought-prompting.ipynb)
* [LoRA/ControlNet](notebooks/inference-optimization/lora-controlnet.ipynb)

## Speech & Audio

* [ffmpeg](notebooks/speech-audio/ffmpeg.ipynb)
* [Whisper STT](notebooks/speech-audio/whisper-stt.ipynb)
* [Coqui TTS](notebooks/speech-audio/coqui-tts.ipynb)
* [Piper TTS](notebooks/speech-audio/piper-tts.ipynb)
* [ElevenLabs](notebooks/speech-audio/elevenlabs.ipynb)
* [Google Cloud TTS](notebooks/speech-audio/google-cloud-tts.ipynb)
* [espeak-ng](notebooks/speech-audio/espeak-ng.ipynb)
* [Oculus Lip Sync](notebooks/speech-audio/oculus-lip-sync.ipynb)
* [SALSA](notebooks/speech-audio/salsa.ipynb)
* [Azure Speech Services](notebooks/speech-audio/azure-speech-services.ipynb)
* [Amazon Polly](notebooks/speech-audio/amazon-polly.ipynb)
* [Wav2Vec](notebooks/speech-audio/wav2vec.ipynb)
* [DeepSpeech](notebooks/speech-audio/deepspeech.ipynb)
* [Tacotron](notebooks/speech-audio/tacotron.ipynb)
* [VITS](notebooks/speech-audio/vits.ipynb)
* [Phoneme Analysis](notebooks/speech-audio/phoneme-analysis.ipynb)

## Game Engines & VR

* [Unity](notebooks/game-engines-vr/unity.ipynb)
* [Unity Sentis](notebooks/game-engines-vr/unity-sentis.ipynb)
* [Unreal Engine 5](notebooks/game-engines-vr/unreal-engine-5.ipynb)
* [MetaHumans](notebooks/game-engines-vr/metahumans.ipynb)
* [Oculus SDK](notebooks/game-engines-vr/oculus-sdk.ipynb)
* [OpenXR](notebooks/game-engines-vr/openxr.ipynb)
* [SteamVR](notebooks/game-engines-vr/steamvr.ipynb)
* [XR Interaction Toolkit](notebooks/game-engines-vr/xr-interaction-toolkit.ipynb)
* [Godot](notebooks/game-engines-vr/godot.ipynb)
* [WebXR](notebooks/game-engines-vr/webxr.ipynb)
* [A-Frame](notebooks/game-engines-vr/a-frame.ipynb)
* [Spatial Audio SDK](notebooks/game-engines-vr/spatial-audio-sdk.ipynb)

## Programming Languages & Frameworks

* [Python](notebooks/programming-languages-frameworks/python.ipynb)
* [Rust](notebooks/programming-languages-frameworks/rust.ipynb)
* [Golang](notebooks/programming-languages-frameworks/golang.ipynb)
* [TypeScript](notebooks/programming-languages-frameworks/typescript.ipynb)
* [Node.js](notebooks/programming-languages-frameworks/nodejs.ipynb)
* [C#/.NET](notebooks/programming-languages-frameworks/csharp-dotnet.ipynb)
* [Clojure](notebooks/programming-languages-frameworks/clojure.ipynb)
* [Java](notebooks/programming-languages-frameworks/java.ipynb)
* [React](notebooks/programming-languages-frameworks/react.ipynb)
* [Vue](notebooks/programming-languages-frameworks/vue.ipynb)

## Mobile Development

* [React Native](notebooks/mobile-development/react-native.ipynb)
* [Android (Java and Kotlin)](notebooks/mobile-development/android-java-kotlin.ipynb)
* [iOS (Objective-C and Swift)](notebooks/mobile-development/ios-objectivec-swift.ipynb)

## Databases

* [MongoDB](notebooks/databases/mongodb.ipynb)
* [PostgreSQL](notebooks/databases/postgresql.ipynb)
* [Drizzle ORM](notebooks/databases/drizzle-orm.ipynb)
* [MySQL](notebooks/databases/mysql.ipynb)
* [SQLite](notebooks/databases/sqlite.ipynb)
* [Redis](notebooks/databases/redis.ipynb)
* [Neo4j](notebooks/databases/neo4j.ipynb)
* [Prisma](notebooks/databases/prisma.ipynb)
* [TypeORM](notebooks/databases/typeorm.ipynb)
* [Supabase](notebooks/databases/supabase.ipynb)

## DevOps & MLOps

* [Terraform](notebooks/devops-mlops/terraform.ipynb)
* [Helm](notebooks/devops-mlops/helm.ipynb)
* [Chef](notebooks/devops-mlops/chef.ipynb)
* [Ansible](notebooks/devops-mlops/ansible.ipynb)
* [Kubernetes](notebooks/devops-mlops/kubernetes.ipynb)
* [Jenkins](notebooks/devops-mlops/jenkins.ipynb)
* [Jenkins X](notebooks/devops-mlops/jenkins-x.ipynb)
* [CircleCI](notebooks/devops-mlops/circleci.ipynb)
* [AWS](notebooks/devops-mlops/aws.ipynb)
* [GCP](notebooks/devops-mlops/gcp.ipynb)
* [Grafana](notebooks/devops-mlops/grafana.ipynb)
* [Sentry](notebooks/devops-mlops/sentry.ipynb)
* [Datadog](notebooks/devops-mlops/datadog.ipynb)
* [Kibana](notebooks/devops-mlops/kibana.ipynb)
* [Prometheus](notebooks/devops-mlops/prometheus.ipynb)
* [GitHub Actions](notebooks/devops-mlops/github-actions.ipynb)

## Machine Learning Architectures

* [Recurrent Neural Networks (RNN)](notebooks/machine-learning-architectures/recurrent-neural-networks-rnn.ipynb)
* [Convolutional Neural Networks (CNN)](notebooks/machine-learning-architectures/convolutional-neural-networks-cnn.ipynb)
* [Long Short-Term Memory (LSTM)](notebooks/machine-learning-architectures/long-short-term-memory-lstm.ipynb)
* [Generative Adversarial Networks (GAN)](notebooks/machine-learning-architectures/generative-adversarial-networks-gan.ipynb)
* [Bidirectional Encoder Representations from Transformers (BERT)](notebooks/machine-learning-architectures/bert-bidirectional-encoder-representations-from-transformers.ipynb)
* [Transformer](notebooks/machine-learning-architectures/transformer.ipynb)
* [Text-to-Text Transfer Transformer (T5)](notebooks/machine-learning-architectures/text-to-text-transfer-transformer-t5.ipynb)
* [Attention Mechanisms](notebooks/machine-learning-architectures/attention-mechanisms.ipynb)
* [Encoder-Decoder Models](notebooks/machine-learning-architectures/encoder-decoder-models.ipynb)
* [Variational Autoencoders (VAE)](notebooks/machine-learning-architectures/variational-autoencoders-vae.ipynb)
* [ResNet](notebooks/machine-learning-architectures/resnet.ipynb)
* [U-Net](notebooks/machine-learning-architectures/u-net.ipynb)
* [Graph Neural Networks (GNN)](notebooks/machine-learning-architectures/graph-neural-networks-gnn.ipynb)
* [Diffusion Models](notebooks/machine-learning-architectures/diffusion-models.ipynb)

## Procedural Generation

* [Tracery](notebooks/procedural-generation/tracery.ipynb)
* [Perlin Noise](notebooks/procedural-generation/perlin-noise.ipynb)
* [Wave Function Collapse](notebooks/procedural-generation/wave-function-collapse.ipynb)
* [L-Systems](notebooks/procedural-generation/l-systems.ipynb)
* [Markov Chains](notebooks/procedural-generation/markov-chains.ipynb)
* [Context-Free Grammars](notebooks/procedural-generation/context-free-grammars.ipynb)
* [Cellular Automata](notebooks/procedural-generation/cellular-automata.ipynb)
* [Noise Functions (Simplex, Worley)](notebooks/procedural-generation/noise-functions-simplex-worley.ipynb)
* [PCG Algorithms](notebooks/procedural-generation/pcg-algorithms.ipynb)
* [Rule-Based Generation](notebooks/procedural-generation/rule-based-generation.ipynb)

## Data Analysis & Research Tools

* [R](notebooks/data-analysis-research-tools/r.ipynb)
* [lme4](notebooks/data-analysis-research-tools/lme4.ipynb)
* [Montreal Forced Aligner](notebooks/data-analysis-research-tools/montreal-forced-aligner.ipynb)
* [NVivo](notebooks/data-analysis-research-tools/nvivo.ipynb)
* [Python (NumPy, Pandas, SciPy)](notebooks/data-analysis-research-tools/python-numpy-pandas-scipy.ipynb)
* [Matplotlib](notebooks/data-analysis-research-tools/matplotlib.ipynb)
* [ggplot2](notebooks/data-analysis-research-tools/ggplot2.ipynb)
* [SPSS](notebooks/data-analysis-research-tools/spss.ipynb)
* [Jupyter Notebooks](notebooks/data-analysis-research-tools/jupyter-notebooks.ipynb)
* [Tableau](notebooks/data-analysis-research-tools/tableau.ipynb)
* [Statistical Modeling](notebooks/data-analysis-research-tools/statistical-modeling.ipynb)
* [Mixed-Effects Models](notebooks/data-analysis-research-tools/mixed-effects-models.ipynb)

## Proprietary Models and Coding AI

* [Google Gemini](notebooks/proprietary-models-coding-ai/google-gemini.ipynb)
* [Google Vertex](notebooks/proprietary-models-coding-ai/google-vertex.ipynb)
* [GitHub Copilot](notebooks/proprietary-models-coding-ai/github-copilot.ipynb)
* [Claude Code](notebooks/proprietary-models-coding-ai/claude-code.ipynb)
* [Windsurf](notebooks/proprietary-models-coding-ai/windsurf.ipynb)
* [Cursor](notebooks/proprietary-models-coding-ai/cursor.ipynb)
* [Repl.it](notebooks/proprietary-models-coding-ai/replit.ipynb)
* [Base 44](notebooks/proprietary-models-coding-ai/base-44.ipynb)
* [Grok](notebooks/proprietary-models-coding-ai/grok.ipynb)
* [ChatGPT Codex](notebooks/proprietary-models-coding-ai/chatgpt-codex.ipynb)
* [LLaMA](notebooks/proprietary-models-coding-ai/llama.ipynb)
* [Mistral](notebooks/proprietary-models-coding-ai/mistral.ipynb)
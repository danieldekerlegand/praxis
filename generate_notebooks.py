#!/usr/bin/env python3
"""
Generate comprehensive Jupyter notebooks for all MLOps technologies.
"""

import json
import os
from pathlib import Path
from typing import Dict, List

# Define all sections and their items
SECTIONS = {
    "critical-reasons-self-hosting": {
        "title": "Critical Reasons for Self-hosting AI/ML Workloads",
        "items": [
            ("aws-integration", "Seamless Integration with AWS Services"),
            ("managed-kubernetes", "Managed Kubernetes Control Plane"),
            ("gpu-support", "Strong Support for GPU-accelerated Workloads"),
            ("scalability", "Advanced Scalability and Auto-scaling Features"),
            ("security-compliance", "Robust Security and Compliance Features"),
            ("cost-optimization", "Cost Optimization Capabilities"),
            ("open-source-ecosystem", "Rich Open-source Ecosystem and Community Support"),
            ("high-availability", "High Availability and Reliability"),
            ("performance-optimization", "Performance Optimizations for Distributed Workloads"),
            ("ease-of-deployment", "Ease of Deployment and Management"),
        ]
    },
    "ai-ml-workloads": {
        "title": "AI/ML Workloads",
        "items": [
            ("model-training", "Model Training"),
            ("model-fine-tuning", "Model Fine-tuning"),
            ("real-time-inference", "Real-time Online Inference"),
            ("batch-inference", "Batch Offline Inference"),
            ("rag-pipelines", "Retrieval Augmented Generation (RAG) Pipelines"),
            ("model-deployment", "Generative AI Model Deployment"),
            ("ai-agents", "AI Agents"),
        ]
    },
    "model-types": {
        "title": "Selected Model Types",
        "items": [
            ("text-models", "Text Models"),
            ("audio-models", "Audio Models"),
            ("image-models", "Image Models"),
            ("video-models", "Video Models"),
        ]
    },
    "open-source-model-benefits": {
        "title": "Reasons to Prefer Open-source Models",
        "items": [
            ("customization", "Customization and Fine-tuning Capabilities"),
            ("cost-savings", "Cost Savings"),
            ("transparency", "Transparency"),
            ("data-privacy", "Data Privacy and Security"),
            ("deployment-control", "Greater Control over Deployment"),
            ("community-collaboration", "Community Collaboration and Support"),
            ("innovation-accessibility", "Drives Innovation and Accessibility"),
            ("ethical-considerations", "Ethical Considerations"),
            ("flexibility", "Flexibility and Avoidance of Vendor Lock-in"),
            ("offline-usage", "Better Suited for Offline or Local Usage"),
        ]
    },
    "inference-challenges": {
        "title": "Persistent Challenges When Running Real-time Online Inference",
        "items": [
            ("resource-allocation-scaling", "Resource Allocation and Scaling"),
            ("data-management", "Data Management"),
            ("cost-optimization-inference", "Cost Optimization"),
            ("dependency-setup", "Dependency and Environment Setup"),
            ("monitoring-observability", "Monitoring and Observability"),
            ("service-integration", "Integration with Other Services"),
            ("performance-tuning", "Performance Tuning"),
            ("cluster-management", "Cluster Management"),
            ("security-compliance", "Security and Compliance"),
        ]
    },
    "fine-tuning-challenges": {
        "title": "Persistent Challenges When Fine-tuning AI/ML Models",
        "items": [
            ("resource-allocation", "Resource Allocation and Scaling"),
            ("data-management-ft", "Data Management"),
            ("cost-optimization-ft", "Cost Optimization"),
            ("dependency-setup-ft", "Dependency and Environment Setup"),
            ("monitoring-observability-ft", "Monitoring and Observability"),
            ("data-integration", "Data Integration with Other Services"),
            ("performance-tuning-ft", "Performance Tuning"),
            ("cluster-management-ft", "Cluster Management"),
            ("security-compliance-ft", "Security and Compliance"),
        ]
    },
    "open-weight-models-fine-tuning": {
        "title": "Selected Open-weight Models for Fine-tuning",
        "items": [
            ("llama-3-70b", "Meta-Llama-3.1-70B-Instruct"),
            ("mistral-7b", "Mistral-7B-Instruct-v0.3"),
            ("gemma-2-27b", "Gemma-2-27b-it"),
        ]
    },
    "open-weight-models-inference": {
        "title": "Selected Open-weight Models for Real-time Inference",
        "items": [
            ("gpt-oss-20b", "GPT-OSS-20B"),
            ("llama-3-8b", "Llama-3-8B-Instruct"),
            ("gemma-2-9b", "Gemma-2-9b-it"),
        ]
    },
    "model-serving-libraries": {
        "title": "Model Serving Libraries for AI/ML Workloads",
        "items": [
            ("bentoml-openllm", "BentoML / OpenLLM"),
            ("deepspeed-mii", "DeepSpeed-MII"),
            ("llama-cpp", "Llama.cpp"),
            ("lmdeploy", "LMDeploy"),
            ("mlserver", "MLServer"),
            ("mosec", "Mosec"),
            ("ollama", "Ollama"),
            ("sglang", "SGLang"),
            ("tensorflow-serving", "TensorFlow Serving"),
            ("tensorrt-llm", "TensorRT-LLM"),
            ("tgi", "TGI (Text Generation Inference)"),
            ("torchserve", "TorchServe"),
            ("triton-inference-server", "Triton Inference Server"),
            ("fastapi-serving", "Python Frameworks (FastAPI)"),
        ]
    },
    "fine-tuning-techniques": {
        "title": "Fine-tuning Techniques for AI/ML Models",
        "items": [
            ("supervised-fine-tuning", "Supervised Fine-Tuning (SFT)"),
            ("parameter-efficient-fine-tuning", "Parameter-Efficient Fine-Tuning (PEFT)"),
            ("reinforcement-learning", "Reinforcement Learning (RL)"),
            ("full-parameter-fine-tuning", "Full Parameter Fine-Tuning"),
            ("instruction-fine-tuning", "Instruction Fine-Tuning"),
            ("continued-pre-training", "Continued Pre-Training"),
            ("transfer-learning", "Transfer Learning"),
            ("domain-specific-fine-tuning", "Domain-Specific Fine-Tuning"),
            ("sequential-fine-tuning", "Sequential Fine-Tuning"),
        ]
    },
    "distributed-training-tools": {
        "title": "Tools for Distributed Training in AI/ML Workloads",
        "items": [
            ("ray-train", "Ray Train"),
            ("huggingface-accelerate", "Hugging Face Accelerate"),
            ("deepspeed", "DeepSpeed"),
            ("horovod", "Horovod"),
            ("torchx", "torchX"),
            ("kubeflow-training-operators", "Kubeflow Training Operators"),
            ("pytorch-distributed", "PyTorch Distributed"),
            ("tensorflow-distribution-strategies", "TensorFlow Distribution Strategies"),
        ]
    },
    "nvidia-gpu-components": {
        "title": "Advanced NVIDIA GPU Components to Optimize AI/ML Workloads",
        "items": [
            ("nvidia-container-toolkit", "NVIDIA Container Toolkit"),
            ("dcgm-exporter", "DCGM Exporter"),
            ("gpu-feature-discovery", "GPU Feature Discovery"),
            ("multi-instance-gpus", "Multi-Instance GPUs (MIGs)"),
            ("mig-manager", "MIG Manager"),
            ("time-slicing", "Time-Slicing for GPU sharing"),
            ("multi-process-service", "Multi-Process Service (MPS)"),
            ("dynamic-resource-allocation", "Dynamic Resource Allocation (DRA)"),
            ("gpudirect-storage", "GPUDirect Storage (GDS)"),
        ]
    },
    "job-orchestration-tools": {
        "title": "Job Orchestration or Scheduling Tools for AI/ML Workloads",
        "items": [
            ("slurm", "Slurm"),
            ("runai", "Run:ai"),
            ("kai-scheduler", "KAI Scheduler"),
            ("kubeflow", "Kubeflow"),
            ("argo-workflows", "Argo Workflows"),
            ("aws-batch", "AWS Batch"),
            ("volcano", "Volcano"),
            ("kueue", "Kueue"),
            ("yunikorn", "YuniKorn"),
            ("airflow", "Airflow"),
            ("ray-serve", "Ray Serve"),
            ("kubernetes-jobsets", "Kubernetes JobSets"),
        ]
    },
    "model-deployment-techniques": {
        "title": "Techniques to Create or Deploy Models in AI/ML Workloads",
        "items": [
            ("model-distillation", "Model Distillation"),
            ("pruning", "Pruning"),
            ("quantization", "Quantization"),
            ("low-rank-approximation", "Low-Rank Approximation"),
            ("sparsity-induction", "Sparsity Induction"),
            ("model-compression-ensembling", "Model Compression via Ensembling"),
        ]
    },
    "storage-csi-drivers": {
        "title": "Storage CSI Drivers for AI/ML Workloads on Amazon EKS",
        "items": [
            ("mountpoint-s3", "Mountpoint for Amazon S3"),
            ("fsx-lustre", "Amazon FSx for Lustre"),
            ("fsx-openzfs", "Amazon FSx for OpenZFS"),
            ("efs", "Amazon EFS"),
            ("ebs", "Amazon EBS"),
        ]
    },
    "container-image-pre-pulling": {
        "title": "Methods or Tools to Pre-pull Container Images",
        "items": [
            ("soci-snapshotter", "SOCI Snapshotter"),
            ("daemonsets", "DaemonSets for Pre-pulling"),
            ("kubernetes-jobs", "Kubernetes Jobs for Pre-pulling"),
            ("custom-amis", "Baking Images into Custom AMIs"),
            ("bottlerocket-data-volume", "Bottlerocket Data Volume"),
            ("bootstrap-scripts", "Bootstrap Scripts"),
            ("ecr-pull-through-cache", "Amazon ECR Pull-through Cache"),
        ]
    },
    "worker-node-os": {
        "title": "Worker Node Operating Systems for AI/ML Workloads",
        "items": [
            ("amazon-linux", "Amazon Linux"),
            ("bottlerocket", "Bottlerocket"),
            ("ubuntu", "Ubuntu"),
            ("rhel-centos", "Red Hat Enterprise Linux (RHEL) / CentOS"),
            ("windows-server", "Windows Server"),
            ("custom-ami", "Custom AMI"),
        ]
    },
    "aws-networking-adapters": {
        "title": "AWS Networking Adapters for AI/ML Workloads on Amazon EKS",
        "items": [
            ("efa", "Elastic Fabric Adapter (EFA)"),
            ("ena", "Elastic Network Adapter (ENA)"),
        ]
    },
}


def create_technology_notebook(filename: str, title: str, section_name: str) -> Dict:
    """Create a comprehensive notebook for a specific technology."""

    cells = [
        # Title
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                f"# {title}\n",
                "\n",
                f"A comprehensive guide to {title} for AI/ML workloads."
            ]
        },
        # Table of Contents
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Table of Contents\n",
                "\n",
                "1. [Introduction](#introduction)\n",
                "2. [Key Features](#key-features)\n",
                "3. [Architecture Overview](#architecture)\n",
                "4. [Installation](#installation)\n",
                "5. [Basic Usage](#basic-usage)\n",
                "6. [Advanced Features](#advanced-features)\n",
                "7. [Use Cases](#use-cases)\n",
                "8. [Best Practices](#best-practices)\n",
                "9. [Common Pitfalls](#pitfalls)\n",
                "10. [Performance Optimization](#performance)\n",
                "11. [Production Deployment](#deployment)\n",
                "12. [Monitoring and Observability](#monitoring)\n",
                "13. [Troubleshooting](#troubleshooting)\n",
                "14. [Comparison with Alternatives](#comparison)\n",
                "15. [Resources](#resources)"
            ]
        },
        # Introduction
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Introduction\n",
                "\n",
                f"{title} is a key technology in the MLOps ecosystem. This notebook provides a comprehensive guide to understanding and implementing {title} in production AI/ML workloads.\n",
                "\n",
                "### What is it?\n",
                "\n",
                f"{title} is designed to [provide description here].\n",
                "\n",
                "### Why use it?\n",
                "\n",
                f"Key benefits of using {title}:\n",
                "\n",
                "- Benefit 1\n",
                "- Benefit 2\n",
                "- Benefit 3\n",
                "\n",
                "### When to use it?\n",
                "\n",
                f"{title} is particularly useful when:\n",
                "\n",
                "- Scenario 1\n",
                "- Scenario 2\n",
                "- Scenario 3"
            ]
        },
        # Key Features
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Key Features\n",
                "\n",
                f"### Core Capabilities of {title}\n",
                "\n",
                "| Feature | Description | Benefit |\n",
                "|---------|-------------|----------|\n",
                "| Feature 1 | Description | Why it matters |\n",
                "| Feature 2 | Description | Why it matters |\n",
                "| Feature 3 | Description | Why it matters |"
            ]
        },
        # Architecture
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Architecture Overview\n",
                "\n",
                f"Understanding the architecture of {title}:\n",
                "\n",
                "```\n",
                "[Add architecture diagram here]\n",
                "```\n",
                "\n",
                "### Components\n",
                "\n",
                "1. **Component 1**: Description\n",
                "2. **Component 2**: Description\n",
                "3. **Component 3**: Description"
            ]
        },
        # Installation
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Installation\n",
                "\n",
                "### Prerequisites\n",
                "\n",
                "- Python 3.8+\n",
                "- CUDA toolkit (for GPU support)\n",
                "- Other dependencies\n",
                "\n",
                "### Installation Steps\n",
                "\n",
                "**Note**: Uncomment the following cell to install in Google Colab."
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# Uncomment to install\n",
                f"# !pip install {filename.replace('-', '_')}"
            ]
        },
        # Basic Usage
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Basic Usage\n",
                "\n",
                "### Quick Start Example\n",
                "\n",
                f"Here's a simple example to get started with {title}:"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                f"# Basic usage example for {title}\n",
                "\n",
                "# Import necessary libraries\n",
                "import os\n",
                "import sys\n",
                "\n",
                "# Example code here\n",
                "print(f'Hello from {title}!')"
            ]
        },
        # Advanced Features
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Advanced Features\n",
                "\n",
                f"### Advanced Capabilities of {title}\n",
                "\n",
                "#### Feature 1: Advanced Usage\n",
                "\n",
                "Description and example."
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# Advanced feature example\n",
                "# Add code here"
            ]
        },
        # Use Cases
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Use Cases\n",
                "\n",
                f"### Real-world Applications of {title}\n",
                "\n",
                "#### Use Case 1: Description\n",
                "\n",
                "- Context\n",
                "- Implementation\n",
                "- Results\n",
                "\n",
                "#### Use Case 2: Description\n",
                "\n",
                "- Context\n",
                "- Implementation\n",
                "- Results"
            ]
        },
        # Best Practices
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Best Practices\n",
                "\n",
                f"### Recommended Practices for {title}\n",
                "\n",
                "1. **Best Practice 1**: Description and rationale\n",
                "2. **Best Practice 2**: Description and rationale\n",
                "3. **Best Practice 3**: Description and rationale\n",
                "4. **Best Practice 4**: Description and rationale\n",
                "5. **Best Practice 5**: Description and rationale"
            ]
        },
        # Common Pitfalls
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Common Pitfalls\n",
                "\n",
                f"### What to Avoid When Using {title}\n",
                "\n",
                "1. **Pitfall 1**: Description and how to avoid\n",
                "2. **Pitfall 2**: Description and how to avoid\n",
                "3. **Pitfall 3**: Description and how to avoid"
            ]
        },
        # Performance
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Performance Optimization\n",
                "\n",
                f"### Optimizing {title} for Production\n",
                "\n",
                "#### Configuration Tuning\n",
                "\n",
                "Key parameters to optimize:\n",
                "\n",
                "- Parameter 1: Description\n",
                "- Parameter 2: Description\n",
                "- Parameter 3: Description"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# Performance optimization example\n",
                "# Add benchmarking code"
            ]
        },
        # Deployment
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Production Deployment\n",
                "\n",
                f"### Deploying {title} in Production\n",
                "\n",
                "#### Docker Deployment\n",
                "\n",
                "```dockerfile\n",
                "# Example Dockerfile\n",
                "FROM python:3.10-slim\n",
                "# Add deployment configuration\n",
                "```\n",
                "\n",
                "#### Kubernetes Deployment\n",
                "\n",
                "```yaml\n",
                "# Example Kubernetes manifest\n",
                "apiVersion: v1\n",
                "kind: Service\n",
                "# Add K8s configuration\n",
                "```"
            ]
        },
        # Monitoring
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Monitoring and Observability\n",
                "\n",
                f"### Monitoring {title} in Production\n",
                "\n",
                "#### Key Metrics to Track\n",
                "\n",
                "- Metric 1: Description\n",
                "- Metric 2: Description\n",
                "- Metric 3: Description\n",
                "\n",
                "#### Logging Best Practices\n",
                "\n",
                "- Log what matters\n",
                "- Structure your logs\n",
                "- Use appropriate log levels"
            ]
        },
        # Troubleshooting
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Troubleshooting\n",
                "\n",
                f"### Common Issues with {title}\n",
                "\n",
                "#### Issue 1: Problem Description\n",
                "\n",
                "**Symptoms**: What you might see\n",
                "\n",
                "**Cause**: Why it happens\n",
                "\n",
                "**Solution**: How to fix it\n",
                "\n",
                "#### Issue 2: Problem Description\n",
                "\n",
                "**Symptoms**: What you might see\n",
                "\n",
                "**Cause**: Why it happens\n",
                "\n",
                "**Solution**: How to fix it"
            ]
        },
        # Comparison
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Comparison with Alternatives\n",
                "\n",
                f"### How {title} Compares to Other Solutions\n",
                "\n",
                "| Feature | {title} | Alternative 1 | Alternative 2 |\n",
                "|---------|---------|---------------|---------------|\n",
                "| Feature 1 | Value | Value | Value |\n",
                "| Feature 2 | Value | Value | Value |\n",
                "| Feature 3 | Value | Value | Value |\n",
                "\n",
                "### When to Choose This Tool\n",
                "\n",
                f"Choose {title} when:\n",
                "\n",
                "- Criterion 1\n",
                "- Criterion 2\n",
                "- Criterion 3"
            ]
        },
        # Resources
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Resources\n",
                "\n",
                "### Official Documentation\n",
                "\n",
                "- Official website: [Link]\n",
                "- Documentation: [Link]\n",
                "- GitHub repository: [Link]\n",
                "\n",
                "### Tutorials and Guides\n",
                "\n",
                "- Tutorial 1: [Link]\n",
                "- Tutorial 2: [Link]\n",
                "- Tutorial 3: [Link]\n",
                "\n",
                "### Community Resources\n",
                "\n",
                "- Community forum: [Link]\n",
                "- Discord/Slack: [Link]\n",
                "- Stack Overflow tag: [Link]\n",
                "\n",
                "### Related Technologies\n",
                "\n",
                "- Related tech 1\n",
                "- Related tech 2\n",
                "- Related tech 3"
            ]
        },
    ]

    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3"
            },
            "language_info": {
                "codemirror_mode": {
                    "name": "ipython",
                    "version": 3
                },
                "file_extension": ".py",
                "mimetype": "text/x-python",
                "name": "python",
                "nbconvert_exporter": "python",
                "pygments_lexer": "ipython3",
                "version": "3.10.0"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 4
    }

    return notebook


def generate_all_notebooks():
    """Generate all notebooks for the MLOps technologies."""
    base_dir = Path("notebooks")

    for section_dir, section_info in SECTIONS.items():
        section_path = base_dir / section_dir
        section_path.mkdir(parents=True, exist_ok=True)

        for filename, title in section_info["items"]:
            notebook_path = section_path / f"{filename}.ipynb"

            # Skip if already exists (like vllm.ipynb)
            if notebook_path.exists():
                print(f"Skipping {notebook_path} (already exists)")
                continue

            print(f"Creating {notebook_path}")
            notebook = create_technology_notebook(filename, title, section_dir)

            with open(notebook_path, 'w') as f:
                json.dump(notebook, f, indent=1)

    print("\nNotebook generation complete!")
    print(f"Total notebooks created in {base_dir}/")


if __name__ == "__main__":
    generate_all_notebooks()

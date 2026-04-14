# IELTS-RAG Environment Fix Guide

This guide ensures the environment matches the Baseline requirements perfectly and is compatible with NVIDIA Driver 12.8+ and RTX 3090.

## 1. Clean Installation
Run the following commands to install the exact versions required:

```bash
# Install Torch stack with CUDA 12.1 support
pip install torch==2.2.0+cu121 torchvision==0.17.0+cu121 torchaudio==2.2.0+cu121 --index-url https://download.pytorch.org/whl/cu121

# Install other core libraries
pip install transformers==4.37.1 bitsandbytes==0.43.1 accelerate==0.30.1 triton==2.2.0
```

## 2. Apply Transformers Patch (CRITICAL)
Library `transformers==4.37.1` has a known bug in its bitsandbytes integration that causes `NameError: name 'torch' is not defined`. 

**The Patch:**
Find the file in your virtual environment: 
`site-packages/transformers/integrations/bitsandbytes.py`

Add `import torch` at the top level of the file (around line 7).

## 3. Incremental Saving (Code Level)
The current version of `videorag/videorag.py` has been modified to:
- **Skip Whisper** if transcripts already exist in `kv_store_video_segments.json`.
- **Parallel processing** of Video Saving and Captioning.
- **Fail-fast monitor**: If one process fails, the other is terminated immediately.

## 4. CUDA Mismatch Warning
If you see `The NVIDIA driver on your system is too old (found version 12080)`, it means your `torch` version is too NEW (e.g. cu130). Always use `+cu121` or `+cu118` to stay compatible with common drivers.

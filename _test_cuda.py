#!/usr/bin/env python3
"""Test CUDA availability in the venv."""
import torch
print(f"PyTorch: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")
    free, total = torch.cuda.mem_get_info()
    print(f"VRAM: {free/1024**3:.1f}GB free / {total/1024**3:.1f}GB total")
else:
    print("GPU: none (CPU mode)")

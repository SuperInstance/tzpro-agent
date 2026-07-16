#!/usr/bin/env python3
"""Test Florence-2 import and model loading."""
import os
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")

print("Testing transformers import...")
import transformers
print(f"Transformers version: {transformers.__version__}")

print("\nLoading vision model...")
from vision import load_model
print("Loading Florence-2...")
r = load_model()
print(f"Result: {r}")

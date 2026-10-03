#!/usr/bin/env python3
"""Local preflight checks for SkillForge v7."""
from __future__ import annotations
import json
import os
import sys
import urllib.request

BASE = os.getenv("SKILLFORGE_CHECK_URL", "http://127.0.0.1:3010")
checks = [
    ("health", "/api/health"),
    ("catalog", "/api/catalog"),
]
for name, path in checks:
    with urllib.request.urlopen(BASE + path, timeout=5) as r:
        data = json.loads(r.read().decode())
    if not data.get("ok"):
        raise SystemExit(f"{name}: failed: {data}")
    print(f"{name}: OK")
print("SkillForge v7 preflight: PASS")

# -*- coding: utf-8 -*-
"""URL safety tests: private/local targets must be rejected by default."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.url_safety import UnsafeURLError, assert_public_http_url  # noqa: E402


def check(label, cond):
    print(("[PASS] " if cond else "[FAIL] ") + label)
    if not cond:
        raise SystemExit(1)


os.environ.pop("FW_ALLOW_PRIVATE_NETWORK", None)
for bad in ("http://127.0.0.1:8501", "http://localhost:8501", "http://169.254.169.254/"):
    try:
        assert_public_http_url(bad)
        check("拒绝 " + bad, False)
    except UnsafeURLError:
        check("拒绝 " + bad, True)

os.environ["FW_ALLOW_PRIVATE_NETWORK"] = "1"
check("显式允许本机", assert_public_http_url("http://127.0.0.1:8501") == "http://127.0.0.1:8501")
print("URL SAFETY PASS")

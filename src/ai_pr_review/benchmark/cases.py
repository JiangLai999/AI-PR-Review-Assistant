"""基准样例库：每个样例都预埋了已知缺陷及其准确行号。

样例只依赖静态规则与 AST 规则，不调用任何模型，因此可以离线、可重复地
衡量确定性分析策略的效果。
"""

from __future__ import annotations

from ai_pr_review.benchmark.models import BenchmarkCase, ExpectedFinding

SECURITY_SOURCE = """import hashlib
import pickle
import subprocess

import requests

API_KEY = "sk-live-9f8e7d6c5b4a3210"

def load_session(payload):
    return pickle.loads(payload)

def run_command(command):
    subprocess.run(command, shell=True)

def fetch(url):
    return requests.get(url, verify=False)

def hash_password(password):
    return hashlib.md5(password.encode()).hexdigest()

def build_query(user_id):
    return f"SELECT * FROM users WHERE id = {user_id}"
"""

CORRECTNESS_SOURCE = """def collect(item, bucket=[], cache={}):
    bucket.append(item)
    cache[item] = True
    return bucket

def is_ready(state):
    return state is "ready"

def divide(a, b):
    return a / b
"""

ERROR_HANDLING_SOURCE = """import json

def parse(payload):
    try:
        return json.loads(payload)
    except:
        return None

def read_config(path):
    handle = open(path)
    return handle.read()

def load_yaml(payload):
    return yaml.load(payload)
"""

CLEAN_SOURCE = """import json
from pathlib import Path

import requests

TIMEOUT_SECONDS = 30

def load_config(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)

def format_name(first, last=None):
    if last is None:
        return first
    return f"{first} {last}"

def fetch_status(url):
    return requests.get(url, timeout=TIMEOUT_SECONDS)
"""

BENCHMARK_CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase(
        case_id="security-python-01",
        filename="src/security_hotspots.py",
        language="python",
        source=SECURITY_SOURCE,
        expected=[
            ExpectedFinding(
                rule="hardcoded_secret",
                line=7,
                severity="critical",
                category="security",
                description="API key embedded in source",
            ),
            ExpectedFinding(
                rule="unsafe_deserialization",
                line=10,
                severity="critical",
                category="security",
                description="pickle.loads on untrusted payload",
            ),
            ExpectedFinding(
                rule="subprocess_shell_true",
                line=13,
                severity="high",
                category="security",
                description="shell=True enables command injection",
            ),
            ExpectedFinding(
                rule="tls_verification_disabled",
                line=16,
                severity="high",
                category="security",
                description="verify=False disables certificate validation",
            ),
            ExpectedFinding(
                rule="sql_interpolation",
                line=22,
                severity="high",
                category="security",
                description="f-string SQL query",
            ),
            ExpectedFinding(
                rule="weak_hash_algorithm",
                line=19,
                severity="medium",
                category="security",
                description="md5 used for password hashing",
            ),
            ExpectedFinding(
                rule="http_request_without_timeout",
                line=16,
                severity="medium",
                category="resource",
                description="outbound request without a timeout",
            ),
        ],
        tags=["security", "owasp"],
    ),
    BenchmarkCase(
        case_id="correctness-python-01",
        filename="src/state_helpers.py",
        language="python",
        source=CORRECTNESS_SOURCE,
        expected=[
            ExpectedFinding(
                rule="mutable_default_argument",
                line=1,
                severity="medium",
                category="correctness",
                description="shared mutable defaults across calls",
            ),
            ExpectedFinding(
                rule="is_literal_comparison",
                line=7,
                severity="medium",
                category="correctness",
                description="identity comparison against a string literal",
            ),
        ],
        tags=["correctness"],
    ),
    BenchmarkCase(
        case_id="error-handling-python-01",
        filename="src/parsers.py",
        language="python",
        source=ERROR_HANDLING_SOURCE,
        expected=[
            ExpectedFinding(
                rule="bare_except",
                line=6,
                severity="medium",
                category="error_handling",
                description="bare except hides all failures",
            ),
            ExpectedFinding(
                rule="unclosed_resource",
                line=10,
                severity="medium",
                category="resource",
                description="file handle never closed",
            ),
            ExpectedFinding(
                rule="unsafe_yaml_load",
                line=14,
                severity="critical",
                category="security",
                description="unsafe YAML loader",
            ),
        ],
        tags=["error_handling", "resource"],
    ),
    BenchmarkCase(
        case_id="clean-python-01",
        filename="src/clean_module.py",
        language="python",
        source=CLEAN_SOURCE,
        expected=[],
        tags=["negative-control"],
        notes="对照组：不应产生任何静态发现，用于衡量误报。",
    ),
)


def load_cases() -> list[BenchmarkCase]:
    """返回全部基准样例的副本列表。"""
    return list(BENCHMARK_CASES)


def get_case(case_id: str) -> BenchmarkCase:
    for case in BENCHMARK_CASES:
        if case.case_id == case_id:
            return case
    raise KeyError(f"Unknown benchmark case: {case_id}")


__all__ = ["BENCHMARK_CASES", "get_case", "load_cases"]

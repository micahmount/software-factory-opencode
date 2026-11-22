"""Helpers for loading the extensionless factory scripts in tests."""

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
BIN = REPO / "factory" / "bin"

EXPECTED_CONFIG = {
    "concurrency": 1,
    "max_rounds": 3,
    "base_branch": "main",
    "merge_method": "squash",
    "labels": {
        "queue": "factory",
        "needs_info": "factory:needs-info",
        "needs_human": "factory:needs-human",
    },
    "routing": {
        "low": {"code": "anthropic/claude-haiku-5-5"},
        "medium": {"code": "anthropic/claude-sonnet-5-5"},
        "high": {"code": "anthropic/claude-sonnet-5-5"},
    },
    "surface_reviewers": {
        "ui": {
            "ux": "anthropic/claude-sonnet-5-5",
            "ui": "anthropic/claude-haiku-5-5",
        },
        "security": {"security": "anthropic/claude-opus-5-5"},
    },
    "protected_paths": ["factory/checks.sh", "factory/config.json"],
    "ports": {"base": 5100, "step": 10},
    "prices_usd_per_mtok": {
        "claude-fable-5-2": {
            "input": 10.0,
            "output": 50.0,
            "cache_write_5m": 12.5,
            "cache_write_1h": 20.0,
            "cache_read": 0.25,
        },
        "claude-opus-5-5": {
            "input": 4.0,
            "output": 20.0,
            "cache_write_5m": 5.0,
            "cache_write_1h": 8.0,
            "cache_read": 0.20,
        },
        "claude-sonnet-5-5": {
            "input": 2.0,
            "output": 10.0,
            "cache_write_5m": 2.5,
            "cache_write_1h": 4.0,
            "cache_read": 0.20,
        },
        "claude-haiku-5-5": {
            "input": 0.10,
            "output": 0.50,
            "cache_write_5m": 0.125,
            "cache_write_1h": 0.20,
            "cache_read": 0.01,
        },
    },
}


def load_script(name):
    """Load factory/bin/<name> as an importable module for unit tests."""
    path = BIN / name
    loader = importlib.machinery.SourceFileLoader(f"factory_{name}_{id(path)}", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def write_config(root, config=None):
    factory = root / "factory"
    factory.mkdir(parents=True, exist_ok=True)
    payload = config if config is not None else EXPECTED_CONFIG
    (factory / "config.json").write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def make_job(root, job_id="001-test", **overrides):
    jobs = root / "factory" / "jobs" / job_id
    jobs.mkdir(parents=True, exist_ok=True)
    job = {
        "id": job_id,
        "issue": 12,
        "title": "Add a subtract function",
        "issue_url": "https://github.com/example/project/issues/12",
        "pr": 34,
        "pr_url": "https://github.com/example/project/pull/34",
        "branch": f"factory/{job_id}",
        "worktree": str(root / ".worktrees" / job_id),
        "stage": "intake",
        "round": 0,
        "round_limit": 3,
        "intake": None,
        "agents": None,
        "gate": None,
        "reviews": {},
        "sessions": {},
        "cost_usd": 0.0,
        "started": "2026-11-22T00:00:00Z",
        "ended": None,
    }
    job.update(overrides)
    (jobs / "job.json").write_text(json.dumps(job, indent=2) + "\n")
    return job


def configure(module, root, config=None):
    """Point a loaded script at a temporary project checkout."""
    payload = write_config(root, config)
    module.REPO = root
    module.FACTORY = root / "factory"
    module.JOBS = root / "factory" / "jobs"
    module.BIN = root / "factory" / "bin"
    module.CONFIG = payload
    module.LABELS = payload["labels"]
    module.BASE = payload["base_branch"]
    module.CONCURRENCY = payload["concurrency"]
    if hasattr(module, "CHECKS"):
        module.CHECKS = root / "factory" / "checks.sh"
    return payload

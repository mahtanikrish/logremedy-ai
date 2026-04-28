from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple

@dataclass(frozen=True)
class ReplayConfig:
    act_binary: str = "act"
    event: str = "push"
    job: Optional[str] = None
    workdir: Optional[str] = None
    timeout_s: int = 900

def act_available(act_binary: str = "act") -> bool:
    from shutil import which
    return which(act_binary) is not None


def replay_skipped_evidence(*, reason: str, cfg: Optional[ReplayConfig], repo: str) -> Dict[str, Any]:
    return {
        "attempted": False,
        "tool_available": act_available(cfg.act_binary if cfg is not None else "act"),
        "cmd": [],
        "job": cfg.job if cfg is not None else None,
        "event": cfg.event if cfg is not None else None,
        "workdir": repo,
        "returncode": None,
        "classification": "skipped",
        "stdout_tail": "",
        "stderr_tail": reason,
    }


def replay_with_act(repo: str, cfg: ReplayConfig) -> Tuple[str, Dict[str, Any]]:
    """Try to replay workflow with `act`. Returns (status, evidence)."""
    if not act_available(cfg.act_binary):
        return "inconclusive", {
            "attempted": False,
            "tool_available": False,
            "cmd": [],
            "job": cfg.job,
            "event": cfg.event,
            "workdir": repo,
            "returncode": None,
            "classification": "tool_unavailable",
            "stdout_tail": "",
            "stderr_tail": "act not installed",
        }

    cmd = [cfg.act_binary, cfg.event]
    if cfg.job:
        cmd += ["-j", cfg.job]

    try:
        p = subprocess.run(
            cmd,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=cfg.timeout_s,
        )
        evidence = {
            "attempted": True,
            "tool_available": True,
            "cmd": cmd,
            "job": cfg.job,
            "event": cfg.event,
            "workdir": repo,
            "returncode": p.returncode,
            "classification": "passed" if p.returncode == 0 else "failed",
            "stdout_tail": p.stdout[-4000:],
            "stderr_tail": p.stderr[-4000:],
        }
        if p.returncode == 0:
            return "verified", evidence
        return "failed", evidence
    except subprocess.TimeoutExpired:
        return "inconclusive", {
            "attempted": True,
            "tool_available": True,
            "cmd": cmd,
            "job": cfg.job,
            "event": cfg.event,
            "workdir": repo,
            "returncode": None,
            "classification": "timeout",
            "stdout_tail": "",
            "stderr_tail": "act replay timeout",
        }
    except Exception as e:
        return "inconclusive", {
            "attempted": True,
            "tool_available": True,
            "cmd": cmd,
            "job": cfg.job,
            "event": cfg.event,
            "workdir": repo,
            "returncode": None,
            "classification": "runtime_error",
            "stdout_tail": "",
            "stderr_tail": f"act replay error: {e}",
        }

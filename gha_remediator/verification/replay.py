from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple

@dataclass(frozen=True)
class ReplayConfig:
    act_binary: str = "act"
    # You can specify a job name or event; left minimal for prototype.
    event: str = "push"
    job: Optional[str] = None
    workdir: Optional[str] = None
    timeout_s: int = 900

def act_available(act_binary: str = "act") -> bool:
    from shutil import which
    return which(act_binary) is not None

def replay_with_act(repo: str, cfg: ReplayConfig) -> Tuple[str, Dict[str, Any]]:
    """Try to replay workflow with `act`. Returns (status, evidence)."""
    if not act_available(cfg.act_binary):
        return "inconclusive", {"reason": "act not installed"}

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
            "cmd": cmd,
            "returncode": p.returncode,
            "stdout_tail": p.stdout[-4000:],
            "stderr_tail": p.stderr[-4000:],
        }
        if p.returncode == 0:
            return "verified", evidence
        return "failed", evidence
    except subprocess.TimeoutExpired:
        return "inconclusive", {"reason": "act replay timeout", "cmd": cmd}
    except Exception as e:
        return "inconclusive", {"reason": f"act replay error: {e}", "cmd": cmd}

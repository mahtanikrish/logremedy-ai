from __future__ import annotations

import subprocess
import tempfile
from typing import Tuple, Dict, Any


def verify_commands_locally(
    commands: list[str],
    repo: str,
    timeout_s: int = 30,
) -> Tuple[str, Dict[str, Any]]:
    """
    Fast, deterministic sandbox verification.
    Runs remediation commands locally without GitHub Actions or act.
    """

    if not commands:
        return "inconclusive", {"reason": "no commands to run"}

    try:
        for cmd in commands:
            p = subprocess.run(
                cmd,
                shell=True,
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
            if p.returncode != 0:
                return "failed", {
                    "command": cmd,
                    "stdout_tail": p.stdout[-2000:],
                    "stderr_tail": p.stderr[-2000:],
                }

        return "verified", {"commands": commands}

    except subprocess.TimeoutExpired:
        return "inconclusive", {"reason": "local sandbox timeout"}
    except Exception as e:
        return "inconclusive", {"reason": f"sandbox error: {e}"}
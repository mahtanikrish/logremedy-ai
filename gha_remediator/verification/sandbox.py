from __future__ import annotations

import os
import subprocess
from typing import Tuple, Dict, Any


def verify_commands_locally(commands: list[str], repo: str, workdir: str = ".", timeout_s: int = 30,) -> Tuple[str, Dict[str, Any]]:

    if not commands:
        return "inconclusive", {"reason": "no commands to run"}

    try:
        command_cwd = repo if workdir in ("", ".") else os.path.join(repo, workdir)
        if not os.path.isdir(command_cwd):
            return "failed", {
                "reason": "grounded sandbox working directory does not exist",
                "workdir": workdir,
            }
        for cmd in commands:
            p = subprocess.run(
                cmd,
                shell=True,
                cwd=command_cwd,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
            if p.returncode != 0:
                return "failed", {
                    "command": cmd,
                    "workdir": workdir,
                    "stdout_tail": p.stdout[-2000:],
                    "stderr_tail": p.stderr[-2000:],
                }

        return "verified", {"commands": commands, "workdir": workdir}

    except subprocess.TimeoutExpired:
        return "inconclusive", {"reason": "local sandbox timeout"}
    except Exception as e:
        return "inconclusive", {"reason": f"sandbox error: {e}"}

"""Venv-based verifier for Python dependency remediation commands."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Tuple


def verify_python_dependency(
    package_name: str,
    timeout_s: int = 60,
) -> Tuple[str, Dict[str, Any]]:
    """Create a fresh venv and attempt `pip install <package_name>`."""
    tmp = tempfile.mkdtemp(prefix="gha_venv_")
    try:
        venv_dir = Path(tmp) / "env"

        create_result = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if create_result.returncode != 0:
            return "inconclusive", {
                "reason": "venv creation failed",
                "stderr": create_result.stderr[-1000:],
            }

        if sys.platform == "win32":
            pip_path = str(venv_dir / "Scripts" / "pip.exe")
        else:
            pip_path = str(venv_dir / "bin" / "pip")

        install_result = subprocess.run(
            [pip_path, "install", package_name],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )

        evidence: Dict[str, Any] = {
            "package": package_name,
            "returncode": install_result.returncode,
            "stdout_tail": install_result.stdout[-2000:],
            "stderr_tail": install_result.stderr[-2000:],
        }

        if install_result.returncode == 0:
            return "verified", evidence
        return "failed", evidence

    except subprocess.TimeoutExpired:
        return "inconclusive", {
            "reason": "venv pip install timed out",
            "package": package_name,
        }
    except Exception as e:
        return "inconclusive", {"reason": f"venv verifier error: {e}"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

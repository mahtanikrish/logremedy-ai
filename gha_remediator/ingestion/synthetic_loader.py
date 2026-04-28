from pathlib import Path
import json
from typing import Optional, Dict, List


def _load_ground_truth(log_path: Path) -> Optional[Dict]:
    """
    Given a .log file path, load the corresponding .json ground truth
    if it exists. Returns None if missing or invalid.
    """
    gt_path = log_path.with_suffix(".json")
    if not gt_path.exists():
        return None

    try:
        return json.loads(gt_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_failure_logs(root: str = "dataset/synthetic",limit: Optional[int] = None,with_ground_truth: bool = True,) -> List[Dict]:
    """
    Load synthetic failure logs. Optionally attach ground-truth labels.

    Each returned item:
      {
        path: str
        content: str
        source: "synthetic"
        ground_truth: dict | None
      }
    """
    logs: List[Dict] = []
    root_path = Path(root)

    log_files = sorted(root_path.rglob("*.log"))
    if limit is not None:
        log_files = log_files[:limit]

    for log_file in log_files:
        entry = {
            "path": str(log_file),
            "content": log_file.read_text(encoding="utf-8"),
            "source": "synthetic",
        }

        if with_ground_truth:
            entry["ground_truth"] = _load_ground_truth(log_file)

        logs.append(entry)

    return logs
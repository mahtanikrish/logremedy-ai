from typing import Dict, Any
import json
from pathlib import Path

def log_case(
    out_dir: str,
    case_id: str,
    log_meta: Dict[str, Any],
    verification,
):
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    record = {
        "case_id": case_id,
        "log": log_meta,
        "verification_status": verification.status,
        "reason": verification.reason,
        "evidence": verification.evidence,
    }

    with open(Path(out_dir) / f"{case_id}.json", "w") as f:
        json.dump(record, f, indent=2)
from __future__ import annotations

from typing import List, Optional

from ..types import RCAReport, RemediationPlan, Patch
from ..rag import Doc
from ..llm.base import LLMClient, LLMConfig
from .. import prompts

def plan_with_llm(report: RCAReport, docs: List[Doc], llm: LLMClient, llm_cfg: Optional[LLMConfig] = None) -> RemediationPlan:
    llm_cfg = llm_cfg or LLMConfig()
    docs_text = "\n\n".join([f"[{d.doc_id}] {d.title}\n{d.text}" for d in docs])[:12000]

    user = (
        f"Failure class: {report.failure_class}\n"
        f"RCA hypotheses: {report.root_causes}\n\n"
        f"Curated evidence:\n{prompts.format_blocks(report.blocks)}\n\n"
        f"Retrieved knowledge:\n{docs_text}\n\n"
        f"Constraints:\n- Prefer minimal changes\n- Keep risk low when possible\n- Provide rollback\n"
    )

    out = llm.generate_json(
        system=prompts.PLAN_SYSTEM,
        user=user,
        schema_hint=prompts.PLAN_SCHEMA_HINT,
        cfg=llm_cfg,
    )

    patches = [Patch(path=p.get("path",""), diff=p.get("diff","")) for p in out.get("patches", []) if p.get("path")]
    return RemediationPlan(
        failure_class=report.failure_class,
        fix_type=str(out.get("fix_type", "llm_plan")),
        patches=patches,
        commands=[str(c) for c in out.get("commands", [])],
        assumptions=[str(a) for a in out.get("assumptions", [])],
        rollback=[str(r) for r in out.get("rollback", [])],
        risk_level=str(out.get("risk_level", "medium")),
        evidence={"planner": "llm", "retrieved_docs": [{"id": d.doc_id, "title": d.title, "source": d.source} for d in docs]},
    )

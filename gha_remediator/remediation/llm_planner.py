from __future__ import annotations

from typing import List, Optional

from ..types import RCAReport, RemediationPlan, Patch, RepoContext
from ..rag import Doc
from ..llm.base import LLMClient, LLMConfig
from .. import prompts
from ..repo_context import format_repo_context

def build_planner_user_prompt(
    report: RCAReport,
    docs: List[Doc],
    repo_context: Optional[RepoContext],
) -> str:
    docs_text = "\n\n".join([f"[{d.doc_id}] {d.title}\n{d.text}" for d in docs])[:12000]
    repo_text = format_repo_context(repo_context) if repo_context is not None else "Repo context unavailable."

    return (
        f"Failure class: {report.failure_class}\n"
        f"RCA hypotheses: {report.root_causes}\n\n"
        f"Curated evidence:\n{prompts.format_blocks(report.blocks)}\n\n"
        f"Repository context:\n{repo_text}\n\n"
        f"Retrieved knowledge:\n{docs_text}\n\n"
        f"Constraints:\n- Prefer minimal changes\n- Keep risk low when possible\n- Provide rollback\n"
    )

def plan_with_llm(
    report: RCAReport,
    docs: List[Doc],
    repo_context: Optional[RepoContext],
    llm: LLMClient,
    llm_cfg: Optional[LLMConfig] = None,
) -> RemediationPlan:
    llm_cfg = llm_cfg or LLMConfig()
    user = build_planner_user_prompt(report, docs, repo_context)

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
        evidence={
            "planner": "llm",
            "repo_context_used": repo_context is not None,
            "retrieved_docs": [{"id": d.doc_id, "title": d.title, "source": d.source} for d in docs],
        },
    )

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Optional, List, Dict, Any

from .rca import run_rca
from .rag import KnowledgeBase, Doc
from .remediation.templates import choose_template, render_plan
from .remediation.llm_planner import plan_with_llm
from .repo_context import build_repo_context
from .verification.verify import verify_plan
from .verification.replay import ReplayConfig
from .types import RCAReport, RemediationPlan, RepoContext, VerificationResult
from .llm.base import LLMClient, LLMConfig

class GHARemediator:
    def __init__(self, kb: Optional[KnowledgeBase] = None, llm: Optional[LLMClient] = None, llm_cfg: Optional[LLMConfig] = None):
        self.kb = kb or KnowledgeBase([])
        self.llm = llm
        self.llm_cfg = llm_cfg or LLMConfig()

    def analyze(self, raw_log_text: str, success_logs: Optional[List[str]] = None) -> RCAReport:
        return run_rca(raw_log_text, success_log_texts=success_logs, llm=self.llm, llm_cfg=self.llm_cfg)

    def retrieve_knowledge(self, report: RCAReport, top_k: int = 5) -> List[Doc]:
        query = (" ".join(report.root_causes) + "\n" + "\n".join([b.to_text() for b in report.blocks[:1]]))[:5000]
        return self.kb.retrieve(query, top_k=top_k)

    def propose_fix(
        self,
        report: RCAReport,
        docs: Optional[List[Doc]] = None,
        repo_context: Optional[RepoContext] = None,
    ) -> RemediationPlan:
        docs = docs or []
        if self.llm is not None:
            try:
                plan = plan_with_llm(report, docs, repo_context, self.llm, self.llm_cfg)
                if repo_context is not None:
                    plan.evidence["repo_context"] = asdict(repo_context)
                return plan
            except Exception as e:
                tm = choose_template(report, repo_context=repo_context)
                plan = render_plan(report, tm, repo_context=repo_context)
                plan.evidence["planner_error"] = str(e)
                plan.evidence["planner"] = "template_fallback"
                if docs:
                    plan.evidence["retrieved_docs"] = [{"id": d.doc_id, "title": d.title, "source": d.source} for d in docs]
                if repo_context is not None:
                    plan.evidence["repo_context"] = asdict(repo_context)
                return plan

        tm = choose_template(report, repo_context=repo_context)
        plan = render_plan(report, tm, repo_context=repo_context)
        if docs:
            plan.evidence["retrieved_docs"] = [{"id": d.doc_id, "title": d.title, "source": d.source} for d in docs]
        if repo_context is not None:
            plan.evidence["repo_context"] = asdict(repo_context)
        return plan

    def verify(self, plan: RemediationPlan, repo: Optional[str], replay: bool = False, job: Optional[str] = None) -> VerificationResult:
        if repo is None or not str(repo).strip():
            return VerificationResult(
                status="inconclusive",
                reason="verification skipped: repo not provided",
                evidence={"gate": "preconditions", "repo_provided": False},
            )

        repo_path = Path(repo).expanduser()
        if not repo_path.exists() or not repo_path.is_dir():
            return VerificationResult(
                status="inconclusive",
                reason=f"verification skipped: repo does not exist: {repo}",
                evidence={"gate": "preconditions", "repo_provided": True, "repo_exists": False},
            )

        replay_cfg = None
        if replay:
            replay_cfg = ReplayConfig(job=job)
        return verify_plan(plan, repo=str(repo_path), replay_cfg=replay_cfg)

    def run(self, raw_log_text: str, repo: Optional[str], success_logs: Optional[List[str]] = None, replay: bool = False, job: Optional[str] = None) -> Dict[str, Any]:
        report = self.analyze(raw_log_text, success_logs=success_logs)
        docs = self.retrieve_knowledge(report, top_k=5)
        repo_context = build_repo_context(repo=repo, raw_log_text=raw_log_text, report=report)
        plan = self.propose_fix(report, docs=docs, repo_context=repo_context)
        ver = self.verify(plan, repo=repo, replay=replay, job=job)
        return {
            "rca": {
                "failure_class": report.failure_class,
                "root_causes": report.root_causes,
                "metadata": report.metadata,
                "key_lines": [asdict(l) for l in report.key_lines[:30]],
                "blocks": [{"start": b.start, "end": b.end, "weight_density": b.weight_density} for b in report.blocks],
            },
            "remediation": {
                "fix_type": plan.fix_type,
                "risk_level": plan.risk_level,
                "commands": plan.commands,
                "assumptions": plan.assumptions,
                "rollback": plan.rollback,
                "patches": [{"path": p.path, "diff": p.diff} for p in plan.patches],
                "evidence": plan.evidence,
            },
            "verification": {
                "status": ver.status,
                "reason": ver.reason,
                "evidence": ver.evidence,
            }
        }

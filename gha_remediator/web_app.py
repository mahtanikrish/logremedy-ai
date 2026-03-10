from __future__ import annotations

import argparse
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .ingestion.github_actions import load_github_actions_logs
from .llm.base import LLMConfig
from .llm.github_models_client import GitHubModelsClient
from .pipeline import GHARemediator
from .rag import Doc, KnowledgeBase

try:
    from flask import Flask, jsonify, render_template_string, request
except ImportError as e:
    raise RuntimeError("Flask is not installed. Run: pip install -e '.[web]'") from e


def _default_kb() -> KnowledgeBase:
    docs = [
        Doc(
            "py-missing-module",
            "Python: ModuleNotFoundError in CI",
            "If CI fails with ModuleNotFoundError, ensure the dependency is listed in requirements/pyproject and installed in the workflow. Prefer pinning known-good versions.",
        ),
        Doc(
            "gha-yaml",
            "GitHub Actions: YAML workflow invalid",
            "Validate YAML syntax and check action inputs. Ensure uses: references exist and step keys are correctly indented.",
        ),
        Doc(
            "node-build",
            "Node: build failed",
            "Run npm ci before build. Ensure correct node-version and that package-lock matches. Check tsc errors and tsconfig.",
        ),
    ]
    return KnowledgeBase(docs)


def _build_remediator(model: str) -> GHARemediator:
    llm = GitHubModelsClient()
    cfg = LLMConfig(model=model, max_output_tokens=1400, temperature=0)
    return GHARemediator(kb=_default_kb(), llm=llm, llm_cfg=cfg)


def _list_log_files(root: str) -> List[str]:
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists() or not root_path.is_dir():
        raise ValueError(f"Directory does not exist: {root_path}")
    files = sorted(p.resolve() for p in root_path.rglob("*.log"))
    return [str(p) for p in files]


def _read_log_file(path: str) -> str:
    p = Path(path).expanduser().resolve()
    if not p.exists() or not p.is_file():
        raise ValueError(f"Log file does not exist: {p}")
    return p.read_text(encoding="utf-8", errors="replace")


def _run_pipeline_for_log(raw_log_text: str, verify_repo: str, replay: bool, model: str) -> Dict[str, Any]:
    remediator = _build_remediator(model=model)
    return remediator.run(raw_log_text=raw_log_text, repo=verify_repo, replay=replay, job=None)


def _run_pipeline_for_latest_failed_run(
    github_repo: str,
    verify_repo: str,
    model: str,
    replay: bool,
) -> Dict[str, Any]:
    logs = load_github_actions_logs(repo=github_repo, limit=1)
    if not logs:
        raise RuntimeError("No failed GitHub Actions runs found.")

    run_id = logs[0].get("metadata", {}).get("run_id")
    ordered_logs = sorted(logs, key=lambda x: x.get("path", ""))
    combined = []
    for entry in ordered_logs:
        combined.append(f"===== {entry.get('path', 'log')} =====")
        combined.append(entry.get("content", ""))
    raw_log = "\n".join(combined)

    result = _run_pipeline_for_log(raw_log_text=raw_log, verify_repo=verify_repo, replay=replay, model=model)
    return {"run_id": run_id, "result": result}


@dataclass
class GitHubState:
    running: bool = False
    last_checked_at: Optional[float] = None
    last_run_id: Optional[int] = None
    latest_payload: Optional[Dict[str, Any]] = None
    latest_error: Optional[str] = None


HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GHA Remediator App</title>
  <style>
    :root {
      --ink: #192232;
      --muted: #5d6c84;
      --paper: #ffffff;
      --line: #d5dce7;
      --sea: #0c6b8f;
      --sea-dark: #084c66;
      --mint: #dff5ed;
      --bg-a: #f2f8ff;
      --bg-b: #fff8ef;
      --shadow: 0 14px 40px rgba(34, 63, 92, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      font-family: "Manrope", "Avenir Next", "Segoe UI", sans-serif;
      background:
        radial-gradient(1200px 550px at -10% -10%, #ddefff, transparent 60%),
        radial-gradient(900px 500px at 120% 10%, #ffe9cd, transparent 60%),
        linear-gradient(180deg, var(--bg-a), var(--bg-b));
      min-height: 100vh;
    }
    .wrap {
      max-width: 1080px;
      margin: 26px auto;
      padding: 0 16px 30px;
    }
    .head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-end;
      margin-bottom: 16px;
    }
    .title {
      margin: 0;
      font-size: 1.7rem;
      font-weight: 800;
      letter-spacing: -0.03em;
    }
    .subtitle {
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 0.95rem;
    }
    .mode-badge {
      border: 1px solid #7ec2dd;
      background: #ecfaff;
      color: #0b5e7f;
      border-radius: 999px;
      padding: 8px 12px;
      font-weight: 700;
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .panel {
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: var(--shadow);
      padding: 18px;
      margin-bottom: 14px;
      animation: reveal 300ms ease-out;
    }
    @keyframes reveal {
      from { opacity: 0; transform: translateY(6px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    label { display: block; font-weight: 700; margin: 10px 0 6px; }
    input, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px 11px;
      font: inherit;
      background: #fff;
    }
    .hint { margin: 6px 0 0; color: var(--muted); font-size: 0.86rem; }
    .actions { margin-top: 12px; display: flex; gap: 10px; flex-wrap: wrap; }
    button {
      border: 0;
      border-radius: 10px;
      padding: 10px 14px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      color: #fff;
      background: linear-gradient(140deg, var(--sea), var(--sea-dark));
    }
    button.secondary {
      background: #f1f5fb;
      color: #254262;
      border: 1px solid #d7e2f0;
    }
    .status {
      background: var(--mint);
      border: 1px solid #9edcbf;
      color: #1c5e40;
      border-radius: 12px;
      padding: 10px 12px;
      font-weight: 600;
      margin-bottom: 10px;
    }
    .error {
      background: #fff0ef;
      border: 1px solid #f1bdb8;
      color: #9d3025;
      border-radius: 12px;
      padding: 10px 12px;
      margin-bottom: 10px;
      white-space: pre-wrap;
    }
    pre {
      margin: 0;
      border-radius: 12px;
      border: 1px solid #2a3f5f;
      background: #122033;
      color: #d9ecff;
      padding: 14px;
      overflow: auto;
      max-height: 520px;
      font-size: 0.84rem;
      line-height: 1.38;
    }
    @media (max-width: 820px) {
      .grid { grid-template-columns: 1fr; }
      .head { flex-direction: column; align-items: flex-start; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="head">
      <div>
        <h1 class="title">GHA Remediator App</h1>
        <p class="subtitle">LLM mode is always enabled. Token is read from <code>GITHUB_TOKEN</code>.</p>
      </div>
      <span class="mode-badge">{{ mode }} mode</span>
    </div>

    {% if mode == "synthetic" %}
    <section class="panel">
      <div class="grid">
        <div>
          <label for="root">Synthetic Log Directory</label>
          <input id="root" value="{{ default_root }}" />
          <p class="hint">Example: dataset/synthetic</p>
        </div>
        <div>
          <label for="verify_repo">Repo Path For Verification Gates</label>
          <input id="verify_repo" value="{{ default_verify_repo }}" />
          <p class="hint">Usually the current repo path.</p>
        </div>
      </div>
      <div class="grid">
        <div>
          <label for="model">Model</label>
          <input id="model" value="{{ default_model }}" />
        </div>
        <div>
          <label for="log_file">Log File</label>
          <select id="log_file"></select>
        </div>
      </div>
      <div class="actions">
        <button id="load_files">Load Files</button>
        <button id="run_selected">Run Pipeline</button>
      </div>
    </section>
    {% else %}
    <section class="panel">
      <div class="grid">
        <div>
          <label>GitHub Repo</label>
          <input value="{{ github_repo }}" disabled />
          <p class="hint">Monitoring failed workflow runs continuously.</p>
        </div>
        <div>
          <label for="verify_repo">Local Repo Path For Verification</label>
          <input id="verify_repo" value="{{ default_verify_repo }}" />
          <p class="hint">Used for precondition/policy/static/replay gates.</p>
        </div>
      </div>
      <div class="grid">
        <div>
          <label for="model">Model</label>
          <input id="model" value="{{ default_model }}" />
        </div>
        <div>
          <label for="replay">Replay Gate (act)</label>
          <select id="replay">
            <option value="false">Off</option>
            <option value="true">On</option>
          </select>
        </div>
      </div>
      <div class="actions">
        <button id="apply_monitor">Apply Monitor Settings</button>
        <button id="force_refresh" class="secondary">Force Check Now</button>
      </div>
    </section>
    {% endif %}

    <section class="panel">
      <div id="status" class="status">Ready.</div>
      <div id="error"></div>
      <pre id="output">{}</pre>
    </section>
  </div>

  <script>
    const mode = "{{ mode }}";
    const statusEl = document.getElementById("status");
    const errorEl = document.getElementById("error");
    const outputEl = document.getElementById("output");

    function showError(message) {
      errorEl.className = "error";
      errorEl.textContent = message || "";
    }

    function clearError() {
      errorEl.className = "";
      errorEl.textContent = "";
    }

    function renderJson(obj) {
      outputEl.textContent = JSON.stringify(obj, null, 2);
    }

    async function loadSyntheticFiles() {
      clearError();
      const root = document.getElementById("root").value.trim();
      const sel = document.getElementById("log_file");
      statusEl.textContent = "Loading log files...";
      const res = await fetch(`/api/synthetic/files?root=${encodeURIComponent(root)}`);
      const data = await res.json();
      if (!res.ok) {
        showError(data.error || "Could not list files.");
        statusEl.textContent = "Failed to load files.";
        return;
      }
      sel.innerHTML = "";
      for (const path of data.files) {
        const opt = document.createElement("option");
        opt.value = path;
        opt.textContent = path;
        sel.appendChild(opt);
      }
      statusEl.textContent = `Loaded ${data.files.length} log files.`;
    }

    async function runSynthetic() {
      clearError();
      const payload = {
        log_file: document.getElementById("log_file").value,
        verify_repo: document.getElementById("verify_repo").value.trim(),
        model: document.getElementById("model").value.trim()
      };
      statusEl.textContent = "Running pipeline...";
      const res = await fetch("/api/synthetic/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) {
        showError(data.error || "Run failed.");
        statusEl.textContent = "Run failed.";
        return;
      }
      renderJson(data.result);
      statusEl.textContent = "Run complete.";
    }

    async function applyGitHubSettings() {
      clearError();
      const payload = {
        verify_repo: document.getElementById("verify_repo").value.trim(),
        model: document.getElementById("model").value.trim(),
        replay: document.getElementById("replay").value === "true"
      };
      const res = await fetch("/api/github/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) {
        showError(data.error || "Could not apply settings.");
        return;
      }
      statusEl.textContent = "Monitor settings updated.";
    }

    async function pollGitHubStatus() {
      const res = await fetch("/api/github/status");
      const data = await res.json();
      if (!res.ok) {
        showError(data.error || "Monitor error.");
        return;
      }
      if (data.latest_error) {
        showError(data.latest_error);
      } else {
        clearError();
      }
      const rid = data.last_run_id ? `Last processed run: ${data.last_run_id}` : "No failed run processed yet.";
      statusEl.textContent = data.running ? `Monitoring active. ${rid}` : `Monitoring paused. ${rid}`;
      if (data.latest_payload && data.latest_payload.result) {
        renderJson(data.latest_payload.result);
      }
    }

    async function forceGitHubRefresh() {
      clearError();
      statusEl.textContent = "Checking latest failed run now...";
      const res = await fetch("/api/github/check", { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        showError(data.error || "Check failed.");
        return;
      }
      await pollGitHubStatus();
    }

    if (mode === "synthetic") {
      document.getElementById("load_files").addEventListener("click", (e) => {
        e.preventDefault();
        loadSyntheticFiles();
      });
      document.getElementById("run_selected").addEventListener("click", (e) => {
        e.preventDefault();
        runSynthetic();
      });
      loadSyntheticFiles();
    } else {
      document.getElementById("apply_monitor").addEventListener("click", (e) => {
        e.preventDefault();
        applyGitHubSettings();
      });
      document.getElementById("force_refresh").addEventListener("click", (e) => {
        e.preventDefault();
        forceGitHubRefresh();
      });
      pollGitHubStatus();
      setInterval(pollGitHubStatus, 5000);
    }
  </script>
</body>
</html>
"""


def create_app(
    *,
    mode: str,
    github_repo: Optional[str],
    verify_repo: str,
    synthetic_root: str,
    poll_seconds: int,
    model: str,
) -> Flask:
    if mode not in {"synthetic", "github"}:
        raise ValueError("mode must be 'synthetic' or 'github'")

    app = Flask(__name__)
    app.config["MODE"] = mode
    app.config["GITHUB_REPO"] = github_repo
    app.config["VERIFY_REPO"] = verify_repo
    app.config["SYNTHETIC_ROOT"] = synthetic_root
    app.config["POLL_SECONDS"] = max(3, poll_seconds)
    app.config["MODEL"] = model
    app.config["REPLAY"] = False
    app.config["GITHUB_STATE"] = GitHubState()
    app.config["STATE_LOCK"] = threading.Lock()

    def _poll_once() -> None:
        with app.config["STATE_LOCK"]:
            verify_repo_path = app.config["VERIFY_REPO"]
            selected_model = app.config["MODEL"]
            replay_enabled = bool(app.config["REPLAY"])

        payload = _run_pipeline_for_latest_failed_run(
            github_repo=app.config["GITHUB_REPO"],
            verify_repo=verify_repo_path,
            model=selected_model,
            replay=replay_enabled,
        )

        with app.config["STATE_LOCK"]:
            state: GitHubState = app.config["GITHUB_STATE"]
            run_id = payload.get("run_id")
            if run_id != state.last_run_id:
                state.last_run_id = run_id
                state.latest_payload = payload
            state.latest_error = None
            state.last_checked_at = time.time()

    def _github_monitor_loop() -> None:
        while True:
            with app.config["STATE_LOCK"]:
                state: GitHubState = app.config["GITHUB_STATE"]
                running = state.running
            if running:
                try:
                    _poll_once()
                except Exception as e:
                    with app.config["STATE_LOCK"]:
                        state = app.config["GITHUB_STATE"]
                        state.latest_error = str(e)
                        state.last_checked_at = time.time()
            time.sleep(app.config["POLL_SECONDS"])

    @app.route("/", methods=["GET"])
    def index():
        return render_template_string(
            HTML,
            mode=app.config["MODE"],
            github_repo=app.config["GITHUB_REPO"],
            default_root=app.config["SYNTHETIC_ROOT"],
            default_verify_repo=app.config["VERIFY_REPO"],
            default_model=app.config["MODEL"],
        )

    @app.route("/api/synthetic/files", methods=["GET"])
    def synthetic_files():
        if app.config["MODE"] != "synthetic":
            return jsonify({"error": "Synthetic endpoint disabled in github mode."}), 400
        try:
            root = request.args.get("root", app.config["SYNTHETIC_ROOT"])
            files = _list_log_files(root)
            return jsonify({"files": files})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/synthetic/run", methods=["POST"])
    def synthetic_run():
        if app.config["MODE"] != "synthetic":
            return jsonify({"error": "Synthetic endpoint disabled in github mode."}), 400
        try:
            payload = request.get_json(force=True)
            log_file = str(payload.get("log_file", "")).strip()
            verify_repo_path = str(payload.get("verify_repo", app.config["VERIFY_REPO"])).strip() or "."
            model_name = str(payload.get("model", app.config["MODEL"])).strip() or app.config["MODEL"]
            raw_log = _read_log_file(log_file)
            result = _run_pipeline_for_log(raw_log, verify_repo=verify_repo_path, replay=False, model=model_name)
            return jsonify({"result": result})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/github/config", methods=["POST"])
    def github_config():
        if app.config["MODE"] != "github":
            return jsonify({"error": "GitHub monitor endpoint disabled in synthetic mode."}), 400
        try:
            payload = request.get_json(force=True)
            verify_repo_path = str(payload.get("verify_repo", app.config["VERIFY_REPO"])).strip() or "."
            model_name = str(payload.get("model", app.config["MODEL"])).strip() or app.config["MODEL"]
            replay_enabled = bool(payload.get("replay", False))
            with app.config["STATE_LOCK"]:
                app.config["VERIFY_REPO"] = verify_repo_path
                app.config["MODEL"] = model_name
                app.config["REPLAY"] = replay_enabled
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/github/check", methods=["POST"])
    def github_check():
        if app.config["MODE"] != "github":
            return jsonify({"error": "GitHub monitor endpoint disabled in synthetic mode."}), 400
        try:
            _poll_once()
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/github/status", methods=["GET"])
    def github_status():
        if app.config["MODE"] != "github":
            return jsonify({"error": "GitHub monitor endpoint disabled in synthetic mode."}), 400
        with app.config["STATE_LOCK"]:
            state: GitHubState = app.config["GITHUB_STATE"]
            return jsonify(
                {
                    "running": state.running,
                    "last_checked_at": state.last_checked_at,
                    "last_run_id": state.last_run_id,
                    "latest_payload": state.latest_payload,
                    "latest_error": state.latest_error,
                }
            )

    if app.config["MODE"] == "github":
        with app.config["STATE_LOCK"]:
            app.config["GITHUB_STATE"].running = True
        t = threading.Thread(target=_github_monitor_loop, daemon=True)
        t.start()

    return app


def main() -> None:
    parser = argparse.ArgumentParser(prog="gha-remediator-web")
    parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repository in owner/name format. If provided, app runs in github mode.",
    )
    parser.add_argument(
        "--verify-repo",
        default=".",
        help="Local repository path used by verification gates.",
    )
    parser.add_argument(
        "--synthetic-root",
        default="dataset/synthetic",
        help="Local directory containing synthetic .log files (synthetic mode).",
    )
    parser.add_argument("--poll-seconds", type=int, default=20, help="GitHub monitor polling interval.")
    parser.add_argument("--model", default="gpt-4o-mini", help="LLM model name.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()

    mode = "github" if args.repo else "synthetic"
    app = create_app(
        mode=mode,
        github_repo=args.repo,
        verify_repo=args.verify_repo,
        synthetic_root=args.synthetic_root,
        poll_seconds=args.poll_seconds,
        model=args.model,
    )
    app.run(host=args.host, port=args.port, debug=True)


if __name__ == "__main__":
    main()

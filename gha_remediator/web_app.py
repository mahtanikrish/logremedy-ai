from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict

from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge

from .app_settings import AppSettings, load_app_settings, save_app_settings, settings_payload
from .services.analysis_runtime import (
    describe_kb,
    run_github_analysis,
    run_synthetic_analysis,
    run_synthetic_analysis_text,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

    @app.after_request
    def add_dev_cors_headers(response: Response) -> Response:
        if request.path.startswith("/api/"):
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        return response

    @app.route("/api/health", methods=["GET", "OPTIONS"])
    def health() -> Response:
        if request.method == "OPTIONS":
            return Response(status=204)
        return jsonify({"status": "ok"})

    @app.route("/api/settings", methods=["GET", "POST", "OPTIONS"])
    def settings() -> Response:
        if request.method == "OPTIONS":
            return Response(status=204)

        if request.method == "GET":
            payload = settings_payload()
            payload["knowledgeBase"].update(describe_kb())
            return jsonify(payload)

        payload = _json_payload()
        settings = AppSettings(
            knowledge_base_path=str(payload.get("knowledgeBasePath", "")).strip(),
            env_file_path=str(payload.get("envFilePath", "")).strip(),
        )
        save_app_settings(settings)
        response_payload = settings_payload(settings)
        response_payload["knowledgeBase"].update(describe_kb(settings))
        return jsonify(response_payload)

    @app.errorhandler(RequestEntityTooLarge)
    def handle_large_upload(_: RequestEntityTooLarge) -> tuple[Response, int]:
        return jsonify({"error": "Uploaded log file is too large. Keep uploads under 100 MB for now."}), 413

    @app.route("/api/analyze/synthetic", methods=["POST", "OPTIONS"])
    def analyze_synthetic() -> Response:
        if request.method == "OPTIONS":
            return Response(status=204)

        uploaded_file = request.files.get("logFile")

        if uploaded_file is not None:
            log_path = ""
            log_name = uploaded_file.filename or "uploaded.log"
            raw_log_text = uploaded_file.read().decode("utf-8", errors="replace")
            repo = str(request.form.get("repo", "")).strip()
            model = str(request.form.get("model", "")).strip() or "gpt-4o-mini"
        else:
            payload = _json_payload()
            log_path = str(payload.get("logPath", "")).strip()
            log_name = str(payload.get("logName", "")).strip()
            raw_log_text = str(payload.get("rawLogText", ""))
            repo = str(payload.get("repo", "")).strip()
            model = str(payload.get("model", "")).strip() or "gpt-4o-mini"

        if not log_path and not raw_log_text.strip():
            return jsonify({"error": "Either logPath or rawLogText is required"}), 400

        try:
            if raw_log_text.strip():
                result = run_synthetic_analysis_text(raw_log_text=raw_log_text, repo=repo, model=model)
                display_name = log_name or "uploaded.log"
            else:
                result, raw_log_text = run_synthetic_analysis(log_path=log_path, repo=repo, model=model)
                display_name = Path(log_path).name
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

        return jsonify(
            {
                "mode": "synthetic",
                "statusText": f"Synthetic run complete: {display_name}",
                "result": result,
                "rawLog": raw_log_text,
            }
        )

    @app.route("/api/analyze/github", methods=["POST", "OPTIONS"])
    def analyze_github() -> Response:
        if request.method == "OPTIONS":
            return Response(status=204)

        payload = _json_payload()
        repo_name = str(payload.get("repoName", "")).strip()
        verify_repo = str(payload.get("verifyRepo", "")).strip()
        model = str(payload.get("model", "")).strip() or "gpt-4o-mini"
        run_id_value = payload.get("runId")
        run_id = int(run_id_value) if str(run_id_value).strip() else None

        if not repo_name:
            return jsonify({"error": "repoName is required"}), 400

        try:
            result, active_run_id, raw_log_text = run_github_analysis(
                repo_name=repo_name,
                run_id=run_id,
                verify_repo=verify_repo,
                model=model,
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

        return jsonify(
            {
                "mode": "github",
                "statusText": f"GitHub run complete: {repo_name} #{active_run_id}",
                "result": result,
                "rawLog": raw_log_text,
                "runId": active_run_id,
            }
        )

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def frontend(path: str) -> Response:
        if FRONTEND_DIST_DIR.exists():
            target = FRONTEND_DIST_DIR / path
            if path and target.exists() and target.is_file():
                return send_from_directory(FRONTEND_DIST_DIR, path)
            return send_from_directory(FRONTEND_DIST_DIR, "index.html")
        return Response(_dev_index_html(), mimetype="text/html")

    return app


def _json_payload() -> Dict[str, Any]:
    if request.data:
        return request.get_json(force=True, silent=False) or {}
    return {}


def _dev_index_html() -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Log Clinic</title>
    <style>
      body {{
        margin: 0;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: linear-gradient(180deg, #f5efe7 0%, #efe5d7 100%);
        color: #1f2a33;
      }}
      main {{
        max-width: 920px;
        margin: 80px auto;
        background: rgba(255,255,255,0.82);
        border: 1px solid rgba(198,171,138,0.45);
        border-radius: 28px;
        padding: 32px;
        box-shadow: 0 24px 70px rgba(112, 88, 58, 0.12);
      }}
      code {{
        background: #f2e8da;
        padding: 3px 8px;
        border-radius: 999px;
      }}
      pre {{
        background: #162330;
        color: #e8f1fb;
        padding: 18px;
        border-radius: 18px;
        overflow: auto;
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>GHA Remediator Web App</h1>
      <p>The Python backend is running, but the React frontend has not been built yet.</p>
      <p>To run the full web app:</p>
      <pre>pip install -e .[web]
cd frontend
npm install
npm run dev</pre>
      <p>Or build the frontend and let Flask serve it:</p>
      <pre>cd frontend
npm install
npm run build
python -m gha_remediator.web_app</pre>
      <p>API health endpoint: <code>/api/health</code></p>
    </main>
  </body>
</html>"""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the gha-remediator Flask web app")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "8000")),
        help="Port to bind",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    app = create_app()
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()

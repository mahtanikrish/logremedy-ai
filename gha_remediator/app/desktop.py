from __future__ import annotations

import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .runtime import run_github_analysis, run_synthetic_analysis
from .views import GitHubPage, ResultPanel, SyntheticPage


class DesktopApp:
    def __init__(self) -> None:
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("GHA Remediator")
        self.root.geometry("1440x920")
        self.root.minsize(1280, 840)
        self.root.configure(fg_color="#EFE8DD")

        self.model_var = ctk.StringVar(value="gpt-4o-mini")
        self.synthetic_log_var = ctk.StringVar()
        self.synthetic_repo_var = ctk.StringVar(value=str(Path(".").resolve()))
        self.github_repo_var = ctk.StringVar(value="")
        self.github_run_id_var = ctk.StringVar(value="")
        self.github_verify_repo_var = ctk.StringVar(value=str(Path(".").resolve()))

        self._build_ui()

    def _build_ui(self) -> None:
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self.root, fg_color="#F7F2EA", corner_radius=0, height=92)
        top.grid(row=0, column=0, columnspan=2, sticky="nsew")
        top.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(top, text="GHA Remediator", font=ctk.CTkFont(size=28, weight="bold"), text_color="#1E2833").grid(row=0, column=0, sticky="w", padx=24, pady=(18, 0))
        ctk.CTkLabel(top, text="A desktop app for synthetic and GitHub Actions log analysis", text_color="#6A6259").grid(row=1, column=0, sticky="w", padx=24, pady=(0, 18))

        nav = ctk.CTkFrame(self.root, fg_color="#1E2833", corner_radius=0, width=280)
        nav.grid(row=1, column=0, sticky="nsew")
        nav.grid_rowconfigure(6, weight=1)

        ctk.CTkLabel(nav, text="Workflows", font=ctk.CTkFont(size=18, weight="bold"), text_color="#F6F0E8").pack(anchor="w", padx=20, pady=(20, 16))

        self.synthetic_button = ctk.CTkButton(nav, text="Synthetic Logs", height=44, corner_radius=12, fg_color="#D7B08A", hover_color="#C79A70", text_color="#1E2833", command=self.show_synthetic_page)
        self.synthetic_button.pack(fill="x", padx=16, pady=(0, 10))
        self.github_button = ctk.CTkButton(nav, text="GitHub Logs", height=44, corner_radius=12, fg_color="#2D3B49", hover_color="#394A5B", text_color="#F6F0E8", command=self.show_github_page)
        self.github_button.pack(fill="x", padx=16)

        tips = ctk.CTkFrame(nav, fg_color="#273442", corner_radius=16)
        tips.pack(fill="x", padx=16, pady=(24, 0))
        ctk.CTkLabel(tips, text="How to use it", font=ctk.CTkFont(size=14, weight="bold"), text_color="#F6F0E8").pack(anchor="w", padx=14, pady=(12, 8))
        self.tips_label = ctk.CTkLabel(tips, text="", justify="left", wraplength=220, text_color="#C9D7E3")
        self.tips_label.pack(anchor="w", padx=14, pady=(0, 12))

        self.content = ctk.CTkFrame(self.root, fg_color="transparent")
        self.content.grid(row=1, column=1, sticky="nsew", padx=18, pady=18)
        self.content.grid_columnconfigure(1, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.page_host = ctk.CTkFrame(self.content, fg_color="#EFE8DD")
        self.page_host.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        self.result_panel = ResultPanel(self.content)
        self.result_panel.grid(row=0, column=1, sticky="nsew")

        self.synthetic_page = SyntheticPage(self.page_host, self)
        self.github_page = GitHubPage(self.page_host, self)

        self.show_synthetic_page()

    def show_synthetic_page(self) -> None:
        self.github_page.pack_forget()
        self.synthetic_page.pack(fill="both", expand=True)
        self.synthetic_button.configure(fg_color="#D7B08A", text_color="#1E2833")
        self.github_button.configure(fg_color="#2D3B49", text_color="#F6F0E8")
        self.tips_label.configure(
            text="1. Choose a local .log file.\n2. Check the repo path.\n3. Run the analysis."
        )

    def show_github_page(self) -> None:
        self.synthetic_page.pack_forget()
        self.github_page.pack(fill="both", expand=True)
        self.github_button.configure(fg_color="#D7B08A", text_color="#1E2833")
        self.synthetic_button.configure(fg_color="#2D3B49", text_color="#F6F0E8")
        self.tips_label.configure(
            text="1. Enter owner/name.\n2. Leave run ID blank for the latest failed run.\n3. Point verification to a local clone."
        )

    def pick_synthetic_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose synthetic log file",
            filetypes=[("Log files", "*.log"), ("All files", "*.*")],
        )
        if path:
            self.synthetic_log_var.set(path)

    def load_sample_synthetic(self) -> None:
        self.show_synthetic_page()
        self.synthetic_log_var.set(str(Path("dataset/synthetic/dependency_errors/log_1_20251121-164424.log").resolve()))
        self.synthetic_repo_var.set(str(Path(".").resolve()))
        self.result_panel.status_label.configure(text="Loaded sample synthetic case.")

    def load_demo_github(self) -> None:
        self.show_github_page()
        self.github_repo_var.set("mahtanikrish/actions-log-generator")
        self.github_run_id_var.set("")
        self.github_verify_repo_var.set(str(Path(".").resolve()))
        self.result_panel.status_label.configure(text="Loaded demo GitHub case.")

    def run_synthetic(self) -> None:
        log_path = self.synthetic_log_var.get().strip()
        repo = self.synthetic_repo_var.get().strip() or "."
        if not log_path:
            messagebox.showwarning("Missing log file", "Choose a synthetic log file first.")
            return
        self._run_in_background(self._run_synthetic_worker, log_path, repo)

    def run_github(self) -> None:
        repo_name = self.github_repo_var.get().strip()
        verify_repo = self.github_verify_repo_var.get().strip() or "."
        run_id_text = self.github_run_id_var.get().strip()
        if not repo_name:
            messagebox.showwarning("Missing repository", "Enter a GitHub repo in owner/name form.")
            return
        run_id = int(run_id_text) if run_id_text else None
        self._run_in_background(self._run_github_worker, repo_name, run_id, verify_repo)

    def _run_in_background(self, fn, *args) -> None:
        self.result_panel.status_label.configure(text="Running analysis...")
        thread = threading.Thread(target=fn, args=args, daemon=True)
        thread.start()

    def _run_synthetic_worker(self, log_path: str, repo: str) -> None:
        try:
            result, raw_log_text = run_synthetic_analysis(log_path, repo, self.model_var.get().strip())
            self.root.after(0, lambda: self.result_panel.update_result(result, f"Synthetic run complete: {Path(log_path).name}", raw_log_text=raw_log_text))
        except Exception as e:
            self.root.after(0, lambda: self.result_panel.show_error(str(e)))

    def _run_github_worker(self, repo_name: str, run_id: int | None, verify_repo: str) -> None:
        try:
            result, active_run_id, raw_log_text = run_github_analysis(repo_name, run_id, verify_repo, self.model_var.get().strip())
            self.root.after(0, lambda: self.result_panel.update_result(result, f"GitHub run complete: {repo_name} #{active_run_id}", raw_log_text=raw_log_text))
        except Exception as e:
            self.root.after(0, lambda: self.result_panel.show_error(str(e)))

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    DesktopApp().run()

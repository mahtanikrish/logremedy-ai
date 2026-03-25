from __future__ import annotations

import customtkinter as ctk


class SyntheticPage(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, app: "DesktopApp") -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)

        hero = ctk.CTkFrame(self, fg_color="#F7F2EA", corner_radius=20)
        hero.grid(row=0, column=0, sticky="ew", padx=24, pady=(24, 14))
        ctk.CTkLabel(hero, text="Synthetic Logs", font=ctk.CTkFont(size=24, weight="bold"), text_color="#1C2834").pack(anchor="w", padx=18, pady=(18, 4))
        ctk.CTkLabel(
            hero,
            text="Use a local failure log from the synthetic dataset and run the full LLM pipeline against a chosen verification repository.",
            text_color="#5C5A57",
            wraplength=560,
            justify="left",
        ).pack(anchor="w", padx=18, pady=(0, 18))

        form = ctk.CTkFrame(self, fg_color="#F7F2EA", corner_radius=20)
        form.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 24))
        form.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(form, text="Log file", font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 6))
        file_row = ctk.CTkFrame(form, fg_color="transparent")
        file_row.grid(row=1, column=0, sticky="ew", padx=18)
        file_row.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(file_row, textvariable=app.synthetic_log_var, height=40).grid(row=0, column=0, sticky="ew", padx=(0, 10))
        ctk.CTkButton(file_row, text="Browse", width=110, command=app.pick_synthetic_file).grid(row=0, column=1)
        ctk.CTkLabel(form, text="Choose one `.log` file from `dataset/synthetic` or another local failure log.", text_color="#66625c").grid(row=2, column=0, sticky="w", padx=18, pady=(6, 14))

        ctk.CTkLabel(form, text="Verification repo", font=ctk.CTkFont(size=13, weight="bold")).grid(row=3, column=0, sticky="w", padx=18, pady=(0, 6))
        ctk.CTkEntry(form, textvariable=app.synthetic_repo_var, height=40).grid(row=4, column=0, sticky="ew", padx=18)
        ctk.CTkLabel(form, text="This local repo path is used by the precondition, policy, static, and replay checks.", text_color="#66625c").grid(row=5, column=0, sticky="w", padx=18, pady=(6, 18))

        actions = ctk.CTkFrame(form, fg_color="transparent")
        actions.grid(row=6, column=0, sticky="ew", padx=18, pady=(0, 18))
        ctk.CTkButton(actions, text="Load Sample Case", width=150, fg_color="#A96C41", hover_color="#8D5833", command=app.load_sample_synthetic).pack(side="left", padx=(0, 10))
        ctk.CTkButton(actions, text="Run Synthetic Analysis", width=200, fg_color="#2A6D77", hover_color="#215963", command=app.run_synthetic).pack(side="left")


class GitHubPage(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, app: "DesktopApp") -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)

        hero = ctk.CTkFrame(self, fg_color="#F7F2EA", corner_radius=20)
        hero.grid(row=0, column=0, sticky="ew", padx=24, pady=(24, 14))
        ctk.CTkLabel(hero, text="GitHub Logs", font=ctk.CTkFont(size=24, weight="bold"), text_color="#1C2834").pack(anchor="w", padx=18, pady=(18, 4))
        ctk.CTkLabel(
            hero,
            text="Fetch a recent failed GitHub Actions run, combine its logs, and analyze it against a local clone for verification.",
            text_color="#5C5A57",
            wraplength=560,
            justify="left",
        ).pack(anchor="w", padx=18, pady=(0, 18))

        form = ctk.CTkFrame(self, fg_color="#F7F2EA", corner_radius=20)
        form.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 24))
        form.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(form, text="GitHub repo (owner/name)", font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 6))
        ctk.CTkEntry(form, textvariable=app.github_repo_var, height=40).grid(row=1, column=0, sticky="ew", padx=18)
        ctk.CTkLabel(form, text="Example: mahtanikrish/actions-log-generator", text_color="#66625c").grid(row=2, column=0, sticky="w", padx=18, pady=(6, 14))

        ctk.CTkLabel(form, text="Run ID", font=ctk.CTkFont(size=13, weight="bold")).grid(row=3, column=0, sticky="w", padx=18, pady=(0, 6))
        ctk.CTkEntry(form, textvariable=app.github_run_id_var, height=40).grid(row=4, column=0, sticky="ew", padx=18)
        ctk.CTkLabel(form, text="Leave blank to use the latest failed run with downloadable logs.", text_color="#66625c").grid(row=5, column=0, sticky="w", padx=18, pady=(6, 14))

        ctk.CTkLabel(form, text="Verification repo", font=ctk.CTkFont(size=13, weight="bold")).grid(row=6, column=0, sticky="w", padx=18, pady=(0, 6))
        ctk.CTkEntry(form, textvariable=app.github_verify_repo_var, height=40).grid(row=7, column=0, sticky="ew", padx=18)
        ctk.CTkLabel(form, text="Use a local clone of the same repo if you want meaningful verification results.", text_color="#66625c").grid(row=8, column=0, sticky="w", padx=18, pady=(6, 18))

        actions = ctk.CTkFrame(form, fg_color="transparent")
        actions.grid(row=9, column=0, sticky="ew", padx=18, pady=(0, 18))
        ctk.CTkButton(actions, text="Load Demo Repo", width=150, fg_color="#A96C41", hover_color="#8D5833", command=app.load_demo_github).pack(side="left", padx=(0, 10))
        ctk.CTkButton(actions, text="Run GitHub Analysis", width=200, fg_color="#2A6D77", hover_color="#215963", command=app.run_github).pack(side="left")

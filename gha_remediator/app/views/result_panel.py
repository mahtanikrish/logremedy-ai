from __future__ import annotations

from tkinter import messagebox
from typing import Any, Dict

import customtkinter as ctk

from ..renderers import empty_result_view, flatten_sections, render_result_sections


class ResultPanel(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass) -> None:
        super().__init__(master, fg_color="#F6F0E8", corner_radius=20)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self.status_label = ctk.CTkLabel(
            self,
            text="Ready.",
            anchor="w",
            fg_color="#DCECDD",
            text_color="#1E4C35",
            corner_radius=12,
            padx=14,
            pady=10,
            font=ctk.CTkFont(size=13, weight="bold"),
            wraplength=720,
        )
        self.status_label.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 10))

        self.summary_frame = ctk.CTkFrame(self, fg_color="#EADDCF", corner_radius=16)
        self.summary_frame.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 10))
        for idx in range(3):
            self.summary_frame.grid_columnconfigure(idx, weight=1)
        self.failure_card = self._make_summary_card(self.summary_frame, 0, "Failure Class", "Waiting for analysis", wraplength=180)
        self.fix_card = self._make_summary_card(self.summary_frame, 1, "Fix Type", "Waiting for analysis", wraplength=180)
        self.verification_card = self._make_summary_card(self.summary_frame, 2, "Verification", "Waiting for analysis", wraplength=180)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 10))
        self.copy_json_button = ctk.CTkButton(
            actions,
            text="Copy Raw Log",
            width=140,
            corner_radius=12,
            fg_color="#4B93D2",
            hover_color="#337AB8",
            command=lambda: None,
        )
        self.copy_json_button.pack(side="left", padx=(0, 8))
        self.copy_verification_button = ctk.CTkButton(
            actions,
            text="Copy Verification",
            width=150,
            corner_radius=12,
            fg_color="#4B93D2",
            hover_color="#337AB8",
            command=lambda: None,
        )
        self.copy_verification_button.pack(side="left")

        self.tabview = ctk.CTkTabview(
            self,
            fg_color="#EFE6DA",
            segmented_button_fg_color="#DCC8B0",
            segmented_button_selected_color="#2A6D77",
            segmented_button_selected_hover_color="#215963",
            segmented_button_unselected_color="#CBB79F",
            segmented_button_unselected_hover_color="#BCA589",
        )
        self.tabview.grid(row=3, column=0, sticky="nsew", padx=18, pady=(0, 18))
        self.rca_tab = self._make_content_tab("RCA")
        self.remediation_tab = self._make_content_tab("Remediation")
        self.verification_tab = self._make_content_tab("Verification")
        self.raw_log_box = self._make_textbox("Raw Log")
        self._set_empty_state()

    def _make_summary_card(self, master: ctk.CTkFrame, column: int, label: str, value: str, wraplength: int) -> ctk.CTkLabel:
        card = ctk.CTkFrame(master, fg_color="#F5EADF", corner_radius=14)
        card.grid(row=0, column=column, sticky="nsew", padx=8, pady=8)
        ctk.CTkLabel(
            card,
            text=label,
            anchor="w",
            text_color="#8A5A33",
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(12, 4))
        value_label = ctk.CTkLabel(
            card,
            text=value,
            anchor="w",
            justify="left",
            wraplength=wraplength,
            text_color="#2B2A28",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        value_label.pack(anchor="w", fill="x", padx=14, pady=(0, 12))
        return value_label

    def _make_content_tab(self, tab_name: str) -> ctk.CTkScrollableFrame:
        tab = self.tabview.add(tab_name)
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        frame = ctk.CTkScrollableFrame(
            tab,
            fg_color="#FBF7F1",
            corner_radius=18,
            scrollbar_button_color="#C8AE8E",
            scrollbar_button_hover_color="#B6946C",
        )
        frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        frame.grid_columnconfigure(0, weight=1)
        return frame

    def _make_textbox(self, tab_name: str) -> ctk.CTkTextbox:
        tab = self.tabview.add(tab_name)
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        box = ctk.CTkTextbox(
            tab,
            fg_color="#162330",
            text_color="#E8F1FB",
            border_width=0,
            font=ctk.CTkFont(family="Menlo", size=12),
            wrap="word",
        )
        box.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        return box

    def update_result(self, result: Dict[str, Any], status: str, raw_log_text: str = "") -> None:
        sections = render_result_sections(result, raw_log_text=raw_log_text)
        self._render_content_tab(self.rca_tab, sections["rca"], accent="#B8683D")
        self._render_content_tab(self.remediation_tab, sections["remediation"], accent="#2A6D77")
        self._render_content_tab(self.verification_tab, sections["verification"], accent="#4F7A57")
        self._write_box(self.raw_log_box, sections["raw_log"])

        self.status_label.configure(text=status)
        self.failure_card.configure(text=sections["summary"]["failure_class"])
        self.fix_card.configure(text=sections["summary"]["fix_type"])
        self.verification_card.configure(text=sections["summary"]["verification"])
        self.copy_json_button.configure(command=lambda: self._copy_text(sections["raw_log"]))
        verification_text = flatten_sections(sections["verification"])
        self.copy_verification_button.configure(command=lambda: self._copy_text(verification_text))

    def show_error(self, message: str) -> None:
        self.status_label.configure(text="Analysis failed.")
        self.failure_card.configure(text="No result")
        self.fix_card.configure(text="No result")
        self.verification_card.configure(text="Failed")
        messagebox.showerror("Analysis failed", message)

    def _set_empty_state(self) -> None:
        empty_view = empty_result_view()
        self._render_content_tab(self.rca_tab, empty_view, accent="#B8683D")
        self._render_content_tab(self.remediation_tab, empty_view, accent="#2A6D77")
        self._render_content_tab(self.verification_tab, empty_view, accent="#4F7A57")
        self._write_box(self.raw_log_box, "No raw log yet.\nRun a synthetic or GitHub case to populate this panel.")
        self.failure_card.configure(text="Waiting for analysis")
        self.fix_card.configure(text="Waiting for analysis")
        self.verification_card.configure(text="Waiting for analysis")

    def _render_content_tab(self, container: ctk.CTkScrollableFrame, payload: Dict[str, Any], accent: str) -> None:
        for child in container.winfo_children():
            child.destroy()

        hero = ctk.CTkFrame(container, fg_color="#F6EFE5", corner_radius=18)
        hero.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 10))
        hero.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            hero,
            text=payload.get("headline", ""),
            anchor="w",
            text_color="#1F2A33",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 6))
        ctk.CTkFrame(hero, fg_color=accent, height=4, corner_radius=999).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 16))

        for index, section in enumerate(payload.get("sections", []), start=1):
            card = ctk.CTkFrame(container, fg_color="#FFFFFF", corner_radius=18, border_width=1, border_color="#E8DCCB")
            card.grid(row=index, column=0, sticky="ew", padx=12, pady=(0, 10))
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                card,
                text=section.get("title", ""),
                anchor="w",
                text_color="#22313B",
                font=ctk.CTkFont(size=16, weight="bold"),
            ).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 6))
            body_label = ctk.CTkLabel(
                card,
                text=section.get("body", ""),
                anchor="w",
                justify="left",
                wraplength=560,
                text_color="#655D55",
                font=ctk.CTkFont(size=13),
            )
            body_label.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 10))

            bullets = section.get("bullets", [])
            if bullets:
                bullets_frame = ctk.CTkFrame(card, fg_color="#F9F4EC", corner_radius=14)
                bullets_frame.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 16))
                bullets_frame.grid_columnconfigure(0, weight=1)
                for bullet_index, bullet in enumerate(bullets):
                    bullet_label = ctk.CTkLabel(
                        bullets_frame,
                        text=f"- {bullet}",
                        anchor="w",
                        justify="left",
                        wraplength=540,
                        text_color="#2F3A44",
                        font=ctk.CTkFont(size=13),
                    )
                    bullet_label.grid(row=bullet_index, column=0, sticky="ew", padx=14, pady=(10 if bullet_index == 0 else 2, 2 if bullet_index < len(bullets) - 1 else 10))

    def _write_box(self, box: ctk.CTkTextbox, text: str) -> None:
        box.delete("1.0", "end")
        box.insert("1.0", text)

    def _copy_text(self, value: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(value)
        self.status_label.configure(text="Copied to clipboard.")

# gui_builder.py - BuilderMixin：_build_ui
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, scrolledtext

from i18n import _
from gui_theme import (
    COLOR_BLACK, COLOR_RED, COLOR_GREEN, COLOR_BLUE, COLOR_GRAY,
    COLOR_MAGENTA, COLOR_ORANGE, COLOR_WHITE,
)


class BuilderMixin:
    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding="5")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)

        vertical_container = ttk.Frame(main_frame)
        vertical_container.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.rowconfigure(0, weight=1)
        vertical_container.columnconfigure(0, weight=1)

        vertical_container.rowconfigure(0, weight=0)
        vertical_container.rowconfigure(1, weight=1)
        vertical_container.rowconfigure(2, weight=0)
        vertical_container.rowconfigure(3, weight=1)

        self.history_font = tkfont.Font(family="Consolas", size=9)
        self.status_font = tkfont.Font(family="Consolas", size=12, weight="bold")
        self.button_font = tkfont.Font(family="Consolas", size=12, weight="bold")
        self.label_font = tkfont.Font(family="Consolas", size=10)

        top_container = ttk.Frame(vertical_container)
        top_container.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        top_container.columnconfigure(0, weight=1)

        time_row_frame = ttk.Frame(top_container)
        time_row_frame.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        time_row_frame.columnconfigure(0, weight=1)
        ttk.Label(time_row_frame, textvariable=self.time_var,
                  font=self.status_font, anchor="center").grid(row=0, column=0, sticky="ew")

        top_frame = tk.Frame(top_container, bg=COLOR_WHITE)
        top_frame.grid(row=1, column=0, sticky="ew", pady=(0, 0))
        for c in range(4):
            top_frame.columnconfigure(c, weight=1)

        self.led_label = tk.Label(top_frame, text=_("Receive"), font=self.status_font,
                                  fg=COLOR_WHITE, bg=COLOR_BLACK, anchor="center")
        self.led_label.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)

        self.callsign_btn = tk.Button(top_frame, text=self.core.callsign or _("(empty)"),
                                      command=self._edit_callsign,
                                      bg=COLOR_BLUE, fg=COLOR_WHITE,
                                      font=self.button_font, relief="flat")
        self.callsign_btn.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)

        self.contacts_btn = tk.Button(top_frame, text=_("Contacts"),
                                      command=self._show_contacts_dialog,
                                      bg=COLOR_MAGENTA, fg=COLOR_WHITE,
                                      font=self.button_font, relief="flat")
        self.contacts_btn.grid(row=0, column=2, sticky="nsew", padx=0, pady=0)

        self.about_btn = tk.Button(top_frame, text=_("About"),
                                   command=self._show_about,
                                   bg=COLOR_GRAY, fg=COLOR_WHITE,
                                   font=self.button_font, relief="flat")
        self.about_btn.grid(row=0, column=3, sticky="nsew", padx=0, pady=0)

        history_frame = ttk.LabelFrame(vertical_container, text="", padding="5")
        history_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 2))
        history_container = ttk.Frame(history_frame)
        history_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

        self.history_text = tk.Text(history_container, wrap=tk.WORD,
                                    font=self.history_font, bg=COLOR_WHITE)
        scrollbar = ttk.Scrollbar(history_container, orient=tk.VERTICAL, command=self.history_text.yview)
        self.history_text.configure(yscrollcommand=scrollbar.set)
        self.history_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # ---------- History area color scheme ----------
        self.history_text.tag_config("recv_receiving_header", foreground=COLOR_BLACK, font=self.history_font)
        self.history_text.tag_config("recv_receiving_text", foreground=COLOR_BLACK)

        self.history_text.tag_config("recv_free_text_header", foreground=COLOR_BLACK, font=self.history_font)
        self.history_text.tag_config("recv_free_text_text", foreground=COLOR_BLACK)

        self.history_text.tag_config("recv_frame_ok_header", foreground=COLOR_BLACK, font=self.history_font)
        self.history_text.tag_config("recv_frame_ok_text", foreground=COLOR_BLACK)

        self.history_text.tag_config("recv_fail_header", foreground=COLOR_RED, font=self.history_font)
        self.history_text.tag_config("recv_fail_text", foreground=COLOR_RED)

        self.history_text.tag_config("send_sending_header", foreground=COLOR_GREEN, font=self.history_font)
        self.history_text.tag_config("send_sending_text", foreground=COLOR_GREEN)

        self.history_text.tag_config("send_complete_header", foreground=COLOR_GREEN, font=self.history_font)
        self.history_text.tag_config("send_complete_text", foreground=COLOR_GREEN)

        self.history_text.tag_config("send_fail_header", foreground=COLOR_RED, font=self.history_font)
        self.history_text.tag_config("send_fail_text", foreground=COLOR_RED)

        # ---------- Beacon tags ----------
        # Sent beacon: all green (header + body).
        # Received beacon: all orange (header + body).
        self.history_text.tag_config("beacon_send_header", foreground=COLOR_GREEN, font=self.history_font)
        self.history_text.tag_config("beacon_send_text", foreground=COLOR_GREEN)
        self.history_text.tag_config("beacon_recv_header", foreground=COLOR_ORANGE, font=self.history_font)
        self.history_text.tag_config("beacon_recv_text", foreground=COLOR_ORANGE)

        self.history_text.tag_config("contact_note", foreground=COLOR_BLACK, font=self.history_font)
        self.history_text.tag_config("self_header", foreground=COLOR_BLUE, font=self.history_font)
        self.history_text.tag_config("self_highlight", foreground=COLOR_BLUE, font=self.history_font, underline=False)

        self.history_text.tag_config("history_left", justify='left')
        self.history_text.tag_config("history_right", justify='right')

        self.history_text.config(state=tk.DISABLED)

        self.history_context_menu = tk.Menu(self.root, tearoff=0)
        self.history_context_menu.add_command(label=_("Copy"), command=self._copy_history)
        self.history_context_menu.add_separator()
        self.history_context_menu.add_command(label=_("Clear"), command=self._clear_history)
        self.history_text.bind("<Button-3>", self._show_history_menu)

        tx_container = ttk.LabelFrame(vertical_container, text="", padding="5")
        tx_container.grid(row=2, column=0, sticky="ew", pady=2)
        tx_container.columnconfigure(0, weight=1)

        data_row = ttk.Frame(tx_container)
        data_row.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=5, pady=5)
        data_row.columnconfigure(0, weight=1)

        # Beacon button: left-aligned, same size as the TX button.
        # Closed state: black background. Active state: green background.
        self.beacon_btn = tk.Button(data_row, text="📡", command=self._toggle_beacon,
                                    width=8, bg=COLOR_BLACK, fg=COLOR_WHITE,
                                    relief="raised", font=self.button_font)
        self.beacon_btn.pack(side=tk.LEFT, padx=2)

        self.tx_data_entry = ttk.Entry(data_row, width=50, font=self.label_font)
        self.tx_data_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        self.tx_action_btn = tk.Button(data_row, text=_("Transmit"), command=self._on_tx_action,
                                       width=8, bg=COLOR_GREEN, fg=COLOR_WHITE, relief="raised",
                                       font=self.button_font)
        self.tx_action_btn.pack(side=tk.RIGHT, padx=2)

        self._placeholder_text = _("Max 574 bytes UTF-8, auto frame (CRC8+EOT)")
        self.tx_data_entry.insert(0, self._placeholder_text)
        self.tx_data_entry.config(foreground=COLOR_GRAY)
        self.tx_data_entry.bind("<FocusIn>", self._on_entry_focus_in)
        self.tx_data_entry.bind("<FocusOut>", self._on_entry_focus_out)
        self.tx_data_entry.bind("<KeyRelease>", self._update_input_stats)

        self.tx_context_menu = tk.Menu(self.root, tearoff=0)
        self.tx_context_menu.add_command(label=_("Copy"), command=self._tx_copy)
        self.tx_context_menu.add_command(label=_("Paste"), command=self._tx_paste)
        self.tx_context_menu.add_command(label=_("Clear"), command=self._tx_clear)
        self.tx_data_entry.bind("<Button-3>", self._show_tx_menu)

        stats_row = ttk.Frame(tx_container)
        stats_row.grid(row=1, column=0, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.byte_count_label = ttk.Label(stats_row, text=_("Bytes: 0"), foreground=COLOR_BLACK,
                                          font=self.label_font)
        self.byte_count_label.pack(side=tk.LEFT, padx=5)
        self.frame_count_label = ttk.Label(stats_row, text=_("Frames: 0"), foreground=COLOR_BLACK,
                                           font=self.label_font)
        self.frame_count_label.pack(side=tk.LEFT, padx=20)

        ttk.Label(stats_row, text=_("Freq (Hz):"), font=self.label_font).pack(side=tk.LEFT, padx=(20, 5))
        freq_spinbox = tk.Spinbox(stats_row, from_=self.core.fixed_freq_start, to=self.core.fixed_freq_end,
                                  textvariable=self.tx_freq_var, width=8, increment=1,
                                  command=self._on_freq_changed,
                                  font=self.label_font)
        freq_spinbox.pack(side=tk.LEFT, padx=5)
        freq_spinbox.bind("<FocusOut>", self._on_freq_changed)
        freq_spinbox.bind("<Return>", self._on_freq_changed)
        ttk.Label(stats_row, text=_("(300-3000)"), font=self.label_font).pack(side=tk.LEFT, padx=5)

        chk_noise = tk.Checkbutton(stats_row, text=_("noise"), variable=self.preamble_noise_var,
                                   command=lambda: self.core.set_preamble_noise(self.preamble_noise_var.get()),
                                   font=self.label_font)
        chk_noise.pack(side=tk.LEFT, padx=10)

        display_frame = ttk.LabelFrame(vertical_container, text="", padding="5")
        display_frame.grid(row=3, column=0, sticky="nsew", pady=(2,0))
        self.display_text = scrolledtext.ScrolledText(display_frame, wrap=tk.WORD,
                                                      font=self.label_font, foreground=COLOR_BLACK)
        self.display_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)
        self.display_text.tag_config("info", foreground=COLOR_BLACK)
        self.display_text.tag_config("decode", foreground=COLOR_BLACK)
        self.display_text.tag_config("error", foreground=COLOR_BLACK)
        self.display_text.tag_config("tx", foreground=COLOR_BLACK)
        self.display_text.tag_config("halfduplex", foreground=COLOR_BLACK)
        self.display_text.tag_config("transparent", foreground=COLOR_BLACK)
        self.display_text.tag_config("auto_contact", foreground=COLOR_BLUE)

        self.display_context_menu = tk.Menu(self.root, tearoff=0)
        self.display_context_menu.add_command(label=_("Copy"), command=self._copy_display)
        self.display_context_menu.add_separator()
        self.display_context_menu.add_command(label=_("Clear"), command=self._clear_display)
        self.display_text.bind("<Button-3>", self._show_display_menu)

        self._update_input_stats()


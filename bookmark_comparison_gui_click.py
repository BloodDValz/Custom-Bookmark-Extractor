#!/usr/bin/env python3
"""
Bookmark Extractor - Three modes:
  1. Normal     – select/filter/export bookmarks from a single file
  2. Duplicates – find bookmarks with the same URL appearing more than once, review & clean
  3. Compare    – load two exports, compare by URL, export matching or non-matching bookmarks

Compare mode compares bookmarks by their full URL (case-insensitive, trailing slash ignored).
The bookmark name/title is NOT used for matching — only the link address (href).
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from collections import defaultdict
from html.parser import HTMLParser
from typing import List, Optional, TypedDict
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import os
from datetime import datetime


# ─────────────────────────────────────────────
#  THEME PALETTES
# ─────────────────────────────────────────────

LIGHT_COLORS = {
    "bg":      "#f0f4f8",
    "panel":   "#ffffff",
    "accent":  "#2563eb",
    "accent2": "#16a34a",
    "danger":  "#dc2626",
    "text":    "#1e293b",
    "subtext": "#64748b",
    "sel":     "#bfdbfe",
}

DARK_COLORS = {
    "bg":      "#1e2330",
    "panel":   "#252b3b",
    "accent":  "#3b82f6",
    "accent2": "#22c55e",
    "danger":  "#ef4444",
    "text":    "#e2e8f0",
    "subtext": "#94a3b8",
    "sel":     "#2d3a55",
}


# ─────────────────────────────────────────────
#  NODE TYPES
# ─────────────────────────────────────────────

class BookmarkNode(TypedDict):
    type:     str            # "bookmark"
    name:     str
    href:     str
    add_date: Optional[str]
    icon:     Optional[str]

class FolderNode(TypedDict):
    type:     str            # "folder"
    name:     str
    href:     None
    add_date: Optional[str]
    children: List           # List[BookmarkNode | FolderNode]


# ─────────────────────────────────────────────
#  PARSER
# ─────────────────────────────────────────────

class BookmarkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = {"type": "folder", "name": "ROOT", "children": [], "href": None}
        self._stack = [self.root]
        self._current_tag = None
        self._pending_folder_name = None
        self._pending_bookmark = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self._current_tag = tag.upper()
        if tag.upper() == "DL":
            # Create a folder even if no preceding <H3>; fall back to "(unnamed)"
            # Only push a new folder if we have a pending name OR we're below root
            if self._pending_folder_name is not None:
                folder_name = self._pending_folder_name or "(unnamed)"
                folder: FolderNode = {
                    "type":     "folder",
                    "name":     folder_name,
                    "children": [],
                    "href":     None,
                    "add_date": attrs.get("add_date"),
                }
                self._stack[-1]["children"].append(folder)
                self._stack.append(folder)
                self._pending_folder_name = None
        elif tag.upper() == "H3":
            self._pending_folder_name = ""
        elif tag.upper() == "A":
            bm: BookmarkNode = {
                "type":     "bookmark",
                "name":     "",
                "href":     attrs.get("href", ""),
                "add_date": attrs.get("add_date"),
                "icon":     attrs.get("icon"),
            }
            self._pending_bookmark = bm

    def handle_endtag(self, tag):
        if tag.upper() == "DL":
            if len(self._stack) > 1:
                self._stack.pop()
        elif tag.upper() == "A":
            if self._pending_bookmark:
                self._stack[-1]["children"].append(self._pending_bookmark)
                self._pending_bookmark = None
        self._current_tag = None

    def handle_data(self, data):
        data = data.strip()
        if not data:
            return
        if self._current_tag == "H3" and self._pending_folder_name is not None:
            self._pending_folder_name += data
        elif self._current_tag == "A" and self._pending_bookmark is not None:
            self._pending_bookmark["name"] += data


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def parse_file(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    p = BookmarkParser()
    p.feed(content)
    return p.root


def escape_html(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def export_to_html(nodes, output_path):
    """Write a valid Netscape bookmark HTML from a flat list of bookmark dicts."""
    lines = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        "<!-- This is an automatically generated file. -->",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
        "<TITLE>Bookmarks</TITLE>",
        "<H1>Bookmarks</H1>",
        "<DL><p>",
    ]

    def write_node(node, indent=1):
        pad = "    " * indent
        if node["type"] == "folder":
            lines.append(f"{pad}<DT><H3>{escape_html(node['name'])}</H3>")
            lines.append(f"{pad}<DL><p>")
            for child in node.get("children", []):
                write_node(child, indent + 1)
            lines.append(f"{pad}</DL><p>")
        else:
            href     = escape_html(node.get("href", ""))
            name     = escape_html(node.get("name", ""))
            add_date = node.get("add_date") or ""
            date_attr = f' ADD_DATE="{add_date}"' if add_date else ""
            lines.append(f'{pad}<DT><A HREF="{href}"{date_attr}>{name}</A>')

    for node in nodes:
        write_node(node)
    lines.append("</DL><p>")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def count_bookmarks(nodes):
    total = 0
    for node in nodes:
        if node["type"] == "bookmark":
            total += 1
        elif node["type"] == "folder":
            total += count_bookmarks(node.get("children", []))
    return total


def collect_all_bookmarks(root):
    result = []
    def walk(nodes):
        for n in nodes:
            if n["type"] == "bookmark":
                result.append(n)
            elif n["type"] == "folder":
                walk(n.get("children", []))
    walk(root.get("children", []))
    return result


_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "referrer", "source", "fbclid", "gclid", "msclkid",
    "mc_cid", "mc_eid", "yclid", "_ga",
})

def normalise_url(url):
    """Normalise a URL for deduplication.

    - Lowercases and strips whitespace
    - Strips trailing slash
    - Removes the fragment (#…)
    - Removes common tracking query parameters (utm_*, fbclid, ref, etc.)
    """
    url = (url or "").strip().lower()
    parts = urlsplit(url)
    # Strip fragment; filter tracking params from query string
    kept_params = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k not in _TRACKING_PARAMS
    ]
    clean = parts._replace(
        query=urlencode(kept_params) if kept_params else "",
        fragment="",
    )
    return urlunsplit(clean).rstrip("/")


# ─────────────────────────────────────────────
#  MAIN APP SHELL
# ─────────────────────────────────────────────

class BookmarkExtractorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bookmark Extractor")
        self.geometry("980x700")
        self.minsize(760, 520)
        self.configure(bg="#f0f4f8")

        self._current_mode = "normal"
        self._dark_mode = False
        self._setup_styles()
        c = self._colors

        tab_bar = tk.Frame(self, bg=c["bg"])
        tab_bar.pack(fill=tk.X, padx=20, pady=(16, 0))

        self._btn_normal     = self._make_tab_btn(tab_bar, "◈  Normal Mode",     "normal")
        self._btn_duplicates = self._make_tab_btn(tab_bar, "⊕  Duplicates Mode", "duplicates")
        self._btn_compare    = self._make_tab_btn(tab_bar, "⇌  Compare Mode",    "compare")
        self._btn_normal.pack(side=tk.LEFT, padx=(0, 4))
        self._btn_duplicates.pack(side=tk.LEFT, padx=(0, 4))
        self._btn_compare.pack(side=tk.LEFT)

        # Dark mode toggle button (right side of tab bar)
        self._dark_btn = tk.Button(tab_bar, text="🌙  Dark Mode",
            bg=self._colors["sel"], fg=self._colors["text"],
            font=("Segoe UI", 10), relief="flat", bd=0,
            padx=14, pady=7, cursor="hand2",
            command=self._toggle_dark_mode)
        self._dark_btn.pack(side=tk.RIGHT)

        self._normal_frame     = NormalModeFrame(self, self._colors)
        self._duplicates_frame = DuplicatesModeFrame(self, self._colors)
        self._compare_frame    = CompareModeFrame(self, self._colors)

        self._switch_mode("normal")
        self._bind_shortcuts()

    def _toggle_dark_mode(self):
        self._dark_mode = not self._dark_mode
        if self._dark_mode:
            self._dark_btn.config(text="☀  Light Mode")
            colors = DARK_COLORS
        else:
            self._dark_btn.config(text="🌙  Dark Mode")
            colors = LIGHT_COLORS
        self._colors = colors
        self._apply_theme(colors)
        # Propagate to child frames
        for frame in (self._normal_frame, self._duplicates_frame, self._compare_frame):
            frame.apply_colors(colors)
        # Refresh the current mode styling
        self._switch_mode(self._current_mode)

    def _apply_theme(self, c):
        style = ttk.Style(self)
        self.configure(bg=c["bg"])
        style.configure("App.TFrame",      background=c["bg"])
        style.configure("Panel.TFrame",    background=c["panel"])
        style.configure("App.TLabel",      background=c["bg"],    foreground=c["text"],    font=("Segoe UI", 10))
        style.configure("Title.TLabel",    background=c["bg"],    foreground=c["text"],    font=("Segoe UI", 15, "bold"))
        style.configure("Sub.TLabel",      background=c["bg"],    foreground=c["subtext"], font=("Segoe UI", 9))
        style.configure("Panel.TLabel",    background=c["panel"], foreground=c["text"],    font=("Segoe UI", 10))
        style.configure("PanelSub.TLabel", background=c["panel"], foreground=c["subtext"], font=("Segoe UI", 9))
        for name, bg_col, hover in [
            ("Accent.TButton",  c["accent"],  "#1d4ed8" if not self._dark_mode else "#2563eb"),
            ("Green.TButton",   c["accent2"], "#15803d" if not self._dark_mode else "#16a34a"),
            ("Danger.TButton",  c["danger"],  "#b91c1c" if not self._dark_mode else "#dc2626"),
        ]:
            style.configure(name, background=bg_col, foreground="#ffffff",
                            font=("Segoe UI", 10, "bold"), borderwidth=0,
                            relief="flat", padding=(12, 6))
            style.map(name, background=[("active", hover)])
        style.configure("Ghost.TButton", background=c["panel"], foreground=c["subtext"],
                        font=("Segoe UI", 9), borderwidth=1, relief="solid", padding=(8, 4))
        style.map("Ghost.TButton", background=[("active", c["sel"])])
        style.configure("Treeview", background=c["panel"], foreground=c["text"],
                        fieldbackground=c["panel"], rowheight=26,
                        font=("Segoe UI", 10), borderwidth=0)
        style.configure("Treeview.Heading", background=c["sel"], foreground=c["subtext"],
                        font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Treeview",
                  background=[("selected", c["sel"])],
                  foreground=[("selected", c["text"])])
        style.configure("TScrollbar", background=c["sel"], troughcolor=c["bg"],
                        arrowcolor=c["subtext"], borderwidth=0)
        # Update tab bar background and dark button
        for widget in self.winfo_children():
            if isinstance(widget, tk.Frame):
                widget.configure(bg=c["bg"])
                for child in widget.winfo_children():
                    if isinstance(child, tk.Button):
                        child.configure(bg=c["sel"], fg=c["text"])
        if hasattr(self, "_dark_btn"):
            self._dark_btn.configure(bg=c["sel"], fg=c["text"])

    def _make_tab_btn(self, parent, label, mode):
        c = self._colors
        return tk.Button(parent, text=label,
            bg=c["accent"], fg="#ffffff",
            font=("Segoe UI", 10, "bold"),
            relief="flat", bd=0, padx=14, pady=7,
            cursor="hand2",
            command=lambda m=mode: self._switch_mode(m))

    def _switch_mode(self, mode):
        self._current_mode = mode
        c = self._colors
        self._normal_frame.pack_forget()
        self._duplicates_frame.pack_forget()
        self._compare_frame.pack_forget()

        active_frame = {
            "normal":     self._normal_frame,
            "duplicates": self._duplicates_frame,
            "compare":    self._compare_frame,
        }[mode]
        active_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=12)

        for btn, m in [
            (self._btn_normal,     "normal"),
            (self._btn_duplicates, "duplicates"),
            (self._btn_compare,    "compare"),
        ]:
            if m == mode:
                btn.config(bg=c["accent"], fg="#ffffff")
            else:
                btn.config(bg=c["sel"], fg=c["text"])
        self._dark_btn.config(bg=c["sel"], fg=c["text"])

    def _bind_shortcuts(self):
        """Global keyboard shortcuts — delegate to the active mode frame."""
        self.bind_all("<Control-o>", lambda e: self._dispatch_shortcut("open"))
        self.bind_all("<Control-O>", lambda e: self._dispatch_shortcut("open"))
        self.bind_all("<Control-e>", lambda e: self._dispatch_shortcut("export"))
        self.bind_all("<Control-E>", lambda e: self._dispatch_shortcut("export"))
        self.bind_all("<Control-f>", lambda e: self._dispatch_shortcut("focus_filter"))
        self.bind_all("<Control-F>", lambda e: self._dispatch_shortcut("focus_filter"))

    def _dispatch_shortcut(self, action):
        frame = {
            "normal":     self._normal_frame,
            "duplicates": self._duplicates_frame,
            "compare":    self._compare_frame,
        }[self._current_mode]
        handler = getattr(frame, f"_shortcut_{action}", None)
        if handler:
            handler()

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        self._colors = LIGHT_COLORS
        self._apply_theme(LIGHT_COLORS)


# ─────────────────────────────────────────────
#  NORMAL MODE
# ─────────────────────────────────────────────

class NormalModeFrame(ttk.Frame):
    def __init__(self, master, colors):
        super().__init__(master, style="App.TFrame")
        self._colors = colors
        self._parsed_root = None
        self._node_map    = {}   # iid → node dict
        self._check_vars  = {}   # iid → BooleanVar  ("checked" = fully checked)
        self._all_checked = True # global toggle state for heading click

        # Drag-to-reorder state
        self._drag_locked      = True
        self._drag_iid         = None
        self._drag_prev_target = None
        self._drag_prev_folder = None
        self._ghost            = None   # created lazily on first drag
        self._ghost_lbl        = None
        self._scroll_job       = None   # after() id for continuous auto-scroll
        self._indicator_iid    = None   # fake item used as the blue drop line

        self._build_ui()

    # ── UI ───────────────────────────────────

    def _build_ui(self):
        c = self._colors

        ttk.Label(self, text="Select · Filter · Export", style="Sub.TLabel").pack(anchor="w", pady=(0, 6))

        toolbar = ttk.Frame(self, style="App.TFrame")
        toolbar.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(toolbar, text="⊕  Open Bookmarks File", style="Accent.TButton",
                   command=self._open_file).pack(side=tk.LEFT, padx=(0, 8))
        self._file_label = ttk.Label(toolbar, text="No file loaded", style="Sub.TLabel")
        self._file_label.pack(side=tk.LEFT)

        # Lock/unlock drag-to-reorder toggle
        self._lock_btn = tk.Button(toolbar, text="🔒  Reorder: Locked",
            bg=c["sel"], fg=c["text"],
            font=("Segoe UI", 9), relief="flat", bd=0, padx=10, pady=4,
            cursor="hand2", command=self._toggle_drag_lock)
        self._lock_btn.pack(side=tk.RIGHT, padx=(4, 0))

        ttk.Button(toolbar, text="⊞ Select All", style="Ghost.TButton",
                   command=self._select_all).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(toolbar, text="⊟ Deselect All", style="Ghost.TButton",
                   command=self._deselect_all).pack(side=tk.RIGHT, padx=(4, 0))

        sf = ttk.Frame(self, style="App.TFrame")
        sf.pack(fill=tk.X, pady=(0, 8))
        self._search_lbl = tk.Label(sf, text="⌕  Search:", bg=c["bg"], fg=c["subtext"],
                 font=("Courier New", 10))
        self._search_lbl.pack(side=tk.LEFT, padx=(0, 6))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search)
        self._search_entry = tk.Entry(sf, textvariable=self._search_var, bg=c["panel"], fg=c["text"],
                      insertbackground=c["text"], font=("Courier New", 10), relief="flat",
                      highlightthickness=1, highlightbackground=c["sel"],
                      highlightcolor=c["accent"])
        self._search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)
        self._search_clear_btn = tk.Button(sf, text="✕", bg=c["panel"], fg=c["subtext"], font=("Segoe UI", 9),
                  relief="flat", bd=0, command=lambda: self._search_var.set(""),
                  cursor="hand2")
        self._search_clear_btn.pack(side=tk.LEFT, padx=(4, 0))

        pane = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg=c["bg"],
                              sashwidth=6, sashrelief="flat", sashpad=3)
        pane.pack(fill=tk.BOTH, expand=True)

        tree_outer = ttk.Frame(pane, style="Panel.TFrame", padding=2)
        pane.add(tree_outer, minsize=400, stretch="always")

        th = ttk.Frame(tree_outer, style="Panel.TFrame")
        th.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(th, text="BOOKMARK TREE", style="PanelSub.TLabel").pack(side=tk.LEFT)
        self._count_label = ttk.Label(th, text="", style="PanelSub.TLabel")
        self._count_label.pack(side=tk.RIGHT)

        tf = ttk.Frame(tree_outer, style="Panel.TFrame")
        tf.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # columns: check | type
        self._tree = ttk.Treeview(tf, columns=("check", "type"),
                                  show="tree headings", selectmode="extended")
        self._tree.heading("#0",    text="Name")
        self._tree.heading("check", text="✓  (click to toggle all)",
                           command=self._heading_toggle_all)
        self._tree.heading("type",  text="Type")
        self._tree.column("#0",     width=300, stretch=True)
        self._tree.column("check",  width=140, stretch=False, anchor="center")
        self._tree.column("type",   width=70,  stretch=False, anchor="center")

        vsb = ttk.Scrollbar(tf, orient=tk.VERTICAL,   command=self._tree.yview)
        hsb = ttk.Scrollbar(tf, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)

        # No canvas needed — we draw the drop indicator as a tagged tree item

        self._tree.bind("<ButtonPress-1>",   self._on_button_press)
        self._tree.bind("<B1-Motion>",       self._on_drag_motion)
        self._tree.bind("<ButtonRelease-1>", self._on_drag_release)
        self._tree.bind("<<TreeviewSelect>>", lambda e: self._update_info())

        # Tags for drag visuals
        self._tree.tag_configure("drag_folder",    background="#dbeafe", foreground=c["text"])
        self._tree.tag_configure("drop_line",      background="#2563eb", foreground="#2563eb", font=("Segoe UI", 2))

        info_outer = ttk.Frame(pane, style="Panel.TFrame", padding=8)
        pane.add(info_outer, minsize=200, stretch="never")
        ttk.Label(info_outer, text="SELECTION INFO", style="PanelSub.TLabel").pack(anchor="w")
        self._info_text = tk.Text(info_outer, bg=c["panel"], fg=c["text"],
                                  font=("Segoe UI", 9), relief="flat",
                                  wrap=tk.WORD, width=28, state=tk.DISABLED,
                                  highlightthickness=0, cursor="arrow",
                                  exportselection=True)
        self._info_text.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        bottom = ttk.Frame(self, style="App.TFrame")
        bottom.pack(fill=tk.X, pady=(10, 0))
        self._status_var = tk.StringVar(value="Load a bookmarks HTML file to begin")
        ttk.Label(bottom, textvariable=self._status_var, style="Sub.TLabel").pack(side=tk.LEFT)
        ttk.Button(bottom, text="⬇  Export Selected", style="Green.TButton",
                   command=self._export).pack(side=tk.RIGHT)

    # ── File ─────────────────────────────────

    def _open_file(self):
        path = filedialog.askopenfilename(
            title="Select Exported Bookmark HTML File",
            filetypes=[("HTML files", "*.html *.htm"), ("All files", "*.*")])
        if not path:
            return
        self._status_var.set("Loading…")
        self._file_label.config(text="Loading…")
        self.update_idletasks()

        import threading
        def _load():
            try:
                root = parse_file(path)
            except Exception as e:
                err = str(e)
                self.after(0, lambda err=err: (
                    messagebox.showerror("Error", f"Could not read file:\n{err}"),
                    self._status_var.set("Load a bookmarks HTML file to begin"),
                    self._file_label.config(text="No file loaded"),
                ))
                return
            self.after(0, lambda: self._on_file_loaded(path, root))

        threading.Thread(target=_load, daemon=True).start()

    def _on_file_loaded(self, path, root):
        self._parsed_root = root
        self._file_label.config(text=os.path.basename(path))
        self._populate_tree(self._parsed_root)

    # ── Tree population ───────────────────────

    def _populate_tree(self, root, search_term=""):
        self._tree.delete(*self._tree.get_children())
        self._node_map.clear()
        self._check_vars.clear()

        total = count_bookmarks(root.get("children", []))

        def insert(parent_iid, nodes):
            for node in nodes:
                if search_term and not self._node_matches(node, search_term):
                    continue
                name  = node.get("name") or "(unnamed)"
                ntype = node["type"]
                icon  = "📁" if ntype == "folder" else "🔖"
                var   = tk.BooleanVar(value=True)
                iid   = self._tree.insert(parent_iid, "end",
                            text=f"  {icon}  {name}",
                            values=("☑", ntype),
                            open=not bool(search_term))
                self._node_map[iid]   = node
                self._check_vars[iid] = var
                if ntype == "folder":
                    insert(iid, node.get("children", []))

        insert("", root.get("children", []))
        self._count_label.config(
            text=f"{len(self._node_map)} items  |  {total} bookmarks total")
        self._status_var.set(f"Loaded: {total} bookmarks")
        self._all_checked = True
        self._update_info()

    def _node_matches(self, node, term):
        term = term.lower()
        if term in (node.get("name") or "").lower() or term in (node.get("href") or "").lower():
            return True
        if node["type"] == "folder":
            return any(self._node_matches(c, term) for c in node.get("children", []))
        return False

    # ── Interaction ───────────────────────────

    def _toggle_drag_lock(self):
        self._drag_locked = not self._drag_locked
        c = self._colors
        if self._drag_locked:
            self._lock_btn.config(text="🔒  Reorder: Locked",
                bg=c["sel"], fg=c["text"])
            self._tree.config(cursor="")
        else:
            self._lock_btn.config(text="🔓  Reorder: Unlocked",
                bg=c["accent"], fg="#ffffff")
            self._tree.config(cursor="fleur")

    # ── Drag helpers ──────────────────────────

    def _drop_info(self, event_y):
        """
        Given a y position over the tree, return (insert_parent, insert_index, drop_mode)
        where drop_mode is 'into' (folder highlight) or 'between' (insertion line).
        Also returns target_iid for folder highlighting.
        """
        iid     = self._tree.identify_row(event_y)
        if not iid or iid not in self._node_map:
            return None, None, None, None

        bbox = self._tree.bbox(iid)
        if not bbox:
            return None, None, None, None

        item_top    = bbox[1]
        item_bottom = bbox[1] + bbox[3]
        item_mid    = (item_top + item_bottom) // 2
        node        = self._node_map[iid]

        # For folders: drop INTO unless cursor is in the top/bottom 4px strip
        # (those thin strips still allow inserting before/after the folder itself).
        EDGE = 4
        if node["type"] == "folder" and item_top + EDGE < event_y < item_bottom - EDGE:
            return iid, "end", "into", iid

        # Above midpoint → insert before; below → insert after
        parent  = self._tree.parent(iid)
        sibs    = list(self._tree.get_children(parent))
        idx     = sibs.index(iid)
        if event_y < item_mid:
            return parent, idx, "between", iid
        else:
            return parent, idx + 1, "between", iid

    def _clear_drop_indicator(self):
        """Remove the blue drop-line item and folder highlight."""
        if self._indicator_iid:
            try:
                self._tree.delete(self._indicator_iid)
            except Exception:
                pass
            self._indicator_iid = None
        if self._drag_prev_folder:
            try:
                prev_tags = [t for t in self._tree.item(self._drag_prev_folder, "tags")
                             if t != "drag_folder"]
                self._tree.item(self._drag_prev_folder, tags=prev_tags)
            except Exception:
                pass
            self._drag_prev_folder = None

    def _show_insertion_line(self, event_y, target_iid, drop_mode):
        """Show a Chrome-style blue line between rows, or highlight a folder."""
        tree = self._tree

        self._clear_drop_indicator()

        if drop_mode == "into":
            cur_tags = [t for t in tree.item(target_iid, "tags") if t != "drag_folder"]
            tree.item(target_iid, tags=cur_tags + ["drag_folder"])
            self._drag_prev_folder = target_iid
            return

        # Insert a zero-height blue separator item just before/after target_iid
        bbox = tree.bbox(target_iid)
        if not bbox:
            return
        item_mid = bbox[1] + bbox[3] // 2
        insert_after = event_y >= item_mid   # True = insert AFTER target

        parent = tree.parent(target_iid)
        sibs   = list(tree.get_children(parent))
        idx    = sibs.index(target_iid)
        insert_idx = idx + 1 if insert_after else idx

        # Insert a dummy item styled as a solid blue bar
        self._indicator_iid = tree.insert(
            parent, insert_idx,
            text="─" * 120,   # wide dash line fills the row
            values=("", ""),
            tags=("drop_line",))

    def _hide_drag_ui(self):
        """Hide ghost and drop indicator."""
        if self._ghost:
            self._ghost.withdraw()
        self._cancel_scroll()
        self._clear_drop_indicator()

    # ── Drag events ───────────────────────────

    def _on_button_press(self, event):
        col = self._tree.identify_column(event.x)
        iid = self._tree.identify_row(event.y)

        # Check-column click: toggle checkbox and stop — never start a drag.
        if iid and col == "#1":
            self._toggle_check(iid)
            return "break"

        # Drag start — only when unlocked and clicking a real node.
        if self._drag_locked:
            return
        if not iid or iid not in self._node_map:
            return
        self._drag_iid         = iid
        self._drag_prev_target = None
        self._drag_prev_folder = None
        node = self._node_map[iid]
        label = ("📁  " if node["type"] == "folder" else "🔖  ") + (node.get("name") or "(unnamed)")[:40]

        # Create ghost on first use
        if self._ghost is None:
            self._ghost = tk.Toplevel(self)
            self._ghost.withdraw()
            self._ghost.overrideredirect(True)
            self._ghost.attributes("-alpha", 0.55)
            self._ghost.attributes("-topmost", True)
            self._ghost_lbl = tk.Label(self._ghost, font=("Segoe UI", 10),
                                       bg="#2563eb", fg="#ffffff",
                                       padx=10, pady=4, relief="flat")
            self._ghost_lbl.pack()

        self._ghost_lbl.config(text=label)
        self._tree.selection_set(iid)

    # ── Auto-scroll helpers ──────────────────────────────────────────────

    def _cancel_scroll(self):
        if self._scroll_job is not None:
            try:
                self.after_cancel(self._scroll_job)
            except Exception:
                pass
            self._scroll_job = None
        self._scroll_dir = 0

    def _do_scroll(self):
        if not self._drag_iid or not hasattr(self, "_scroll_dir"):
            return
        if self._scroll_dir != 0:
            self._tree.yview_scroll(self._scroll_dir, "units")
            self._scroll_job = self.after(80, self._do_scroll)
        else:
            self._scroll_job = None

    def _on_drag_motion(self, event):
        if self._drag_locked or not self._drag_iid:
            return

        # Move ghost label near cursor
        rx = self._tree.winfo_rootx() + event.x + 16
        ry = self._tree.winfo_rooty() + event.y + 8
        self._ghost.geometry(f"+{rx}+{ry}")
        self._ghost.deiconify()
        self._ghost.lift()

        # ── Continuous auto-scroll ────────────────────────────────────────
        tree_h      = self._tree.winfo_height()
        scroll_zone = 30
        if event.y < scroll_zone:
            new_dir = -1
        elif event.y > tree_h - scroll_zone:
            new_dir = 1
        else:
            new_dir = 0

        if new_dir != getattr(self, "_scroll_dir", 0):
            self._cancel_scroll()
            self._scroll_dir = new_dir
            if new_dir != 0:
                self._scroll_job = self.after(80, self._do_scroll)

        # ── Drop indicator ────────────────────────────────────────────────
        # Skip the indicator item itself
        target_iid = self._tree.identify_row(event.y)
        if not target_iid or target_iid == self._drag_iid or target_iid == self._indicator_iid:
            return

        _, _, drop_mode, highlight_iid = self._drop_info(event.y)
        if drop_mode is None:
            self._clear_drop_indicator()
            return

        self._show_insertion_line(event.y, highlight_iid, drop_mode)

    def _on_drag_release(self, event):
        if self._drag_locked or not self._drag_iid:
            return

        src            = self._drag_iid
        indicator_iid  = self._indicator_iid   # capture before hide clears it
        self._drag_iid = None
        self._hide_drag_ui()

        # If we had an indicator item, use its position directly
        if indicator_iid:
            try:
                parent = self._tree.parent(indicator_iid)
                sibs   = list(self._tree.get_children(parent))
                idx    = sibs.index(indicator_iid)
                # Adjust for the indicator being in the list
                src_parent = self._tree.parent(src)
                if src_parent == parent:
                    src_idx = sibs.index(src)
                    if src_idx < idx:
                        idx -= 1
                self._tree.move(src, parent, idx)
                self._tree.selection_set(src)
                self._tree.see(src)
                return
            except Exception:
                pass

        # Fallback: use hit-test
        target_iid = self._tree.identify_row(event.y)
        if not target_iid or target_iid == src or target_iid not in self._node_map:
            self._tree.selection_set(src)
            return

        insert_parent, insert_idx, drop_mode, _ = self._drop_info(event.y)
        if drop_mode is None:
            self._tree.selection_set(src)
            return

        src_parent = self._tree.parent(src)
        if src_parent == insert_parent and drop_mode == "between":
            sibs    = list(self._tree.get_children(insert_parent))
            src_idx = sibs.index(src)
            if src_idx < insert_idx:
                insert_idx -= 1

        if drop_mode == "into":
            self._tree.move(src, insert_parent, "end")
            self._tree.item(insert_parent, open=True)
        else:
            self._tree.move(src, insert_parent, insert_idx)

        self._tree.selection_set(src)
        self._tree.see(src)

    # ── Keyboard shortcut targets ─────────────

    def _shortcut_open(self):
        self._open_file()

    def _shortcut_export(self):
        self._export()

    def _shortcut_focus_filter(self):
        self._search_entry.focus_set()

    def apply_colors(self, c):
        """Update all manually-colored widgets when theme changes."""
        self._colors = c
        self._search_lbl.config(bg=c["bg"], fg=c["subtext"])
        self._search_entry.config(bg=c["panel"], fg=c["text"],
                                  insertbackground=c["text"],
                                  highlightbackground=c["sel"],
                                  highlightcolor=c["accent"])
        self._search_clear_btn.config(bg=c["panel"], fg=c["subtext"])
        self._info_text.config(bg=c["panel"], fg=c["text"])
        # Lock button — keep its state-appropriate color
        if self._drag_locked:
            self._lock_btn.config(bg=c["sel"], fg=c["text"])
        else:
            self._lock_btn.config(bg=c["accent"], fg="#ffffff")

    def _heading_toggle_all(self):
        """Click on ✓ column header → toggle all items."""
        self._all_checked = not self._all_checked
        for iid in list(self._node_map.keys()):
            self._set_check(iid, self._all_checked, propagate=False)
        self._refresh_folder_indicators()
        self._update_info()

    def _toggle_check(self, iid, state=None):
        if iid not in self._check_vars:
            return
        var = self._check_vars[iid]
        new_state = state if state is not None else not var.get()
        self._set_check(iid, new_state, propagate=True)
        # Refresh parent folder indicators up the tree
        parent = self._tree.parent(iid)
        while parent:
            self._refresh_single_folder(parent)
            parent = self._tree.parent(parent)
        self._update_info()

    def _set_check(self, iid, state, propagate=True):
        """Set the check state of a single item (and optionally all descendants)."""
        if iid not in self._check_vars:
            return
        self._check_vars[iid].set(state)
        vals = self._tree.item(iid, "values")
        ntype = vals[1] if len(vals) > 1 else ""
        if ntype == "folder":
            child_iids = self._tree.get_children(iid)
            if propagate:
                for ciid in child_iids:
                    self._set_check(ciid, state, propagate=True)
            # After setting children, recalculate folder indicator
            self._refresh_single_folder(iid)
        else:
            self._tree.item(iid, values=("☑" if state else "☐", ntype))

    def _refresh_single_folder(self, iid):
        """Update a folder's check symbol based on its children's actual states."""
        node = self._node_map.get(iid)
        if not node or node["type"] != "folder":
            return
        child_iids = self._tree.get_children(iid)
        if not child_iids:
            # Empty folder — honour its own var
            state = self._check_vars[iid].get()
            self._tree.item(iid, values=("☑" if state else "☐", "folder"))
            return

        checked_count   = sum(1 for c in child_iids if self._check_vars.get(c, tk.BooleanVar()).get())
        partial_count   = sum(1 for c in child_iids
                              if self._tree.item(c, "values")[0:1] == ("☒",))
        total_children  = len(child_iids)

        all_checked  = (checked_count == total_children and partial_count == 0)
        none_checked = (checked_count == 0 and partial_count == 0)

        if all_checked:
            symbol = "☑"
            self._check_vars[iid].set(True)
        elif none_checked:
            symbol = "☐"
            self._check_vars[iid].set(False)
        else:
            symbol = "☒"          # partial — some children checked
            self._check_vars[iid].set(False)   # treat as "not fully checked"

        vals = self._tree.item(iid, "values")
        self._tree.item(iid, values=(symbol, vals[1] if len(vals) > 1 else "folder"))

    def _refresh_folder_indicators(self):
        """Refresh all folder indicators bottom-up."""
        def refresh_subtree(iid):
            for ciid in self._tree.get_children(iid):
                refresh_subtree(ciid)
            node = self._node_map.get(iid)
            if node and node["type"] == "folder":
                self._refresh_single_folder(iid)
        for iid in self._tree.get_children(""):
            refresh_subtree(iid)

    def _select_all(self):
        for iid in self._tree.get_children(""):
            self._set_check(iid, True, propagate=True)
        self._all_checked = True
        self._update_info()

    def _deselect_all(self):
        for iid in self._tree.get_children(""):
            self._set_check(iid, False, propagate=True)
        self._all_checked = False
        self._update_info()

    def _on_search(self, *_):
        if self._parsed_root:
            self._populate_tree(self._parsed_root,
                                search_term=self._search_var.get().strip())

    # ── Info panel ────────────────────────────

    def _update_info(self):
        selected_nodes = self._collect_selected()
        bm_count     = count_bookmarks(selected_nodes)
        folder_count = sum(1 for n in self._iter_all(selected_nodes) if n["type"] == "folder")
        self._info_text.config(state=tk.NORMAL)
        self._info_text.delete("1.0", tk.END)
        lines = [
            "Selected items:\n",
            f"  Bookmarks : {bm_count}\n",
            f"  Folders   : {folder_count}\n\n",
        ]
        sel = self._tree.selection()
        if sel:
            node = self._node_map.get(sel[-1])
            if node:
                lines += [f"Last selected:\n  {node.get('name','')[:30]}\n"]
                if node["type"] == "bookmark":
                    lines.append(f"\n  {node.get('href','')}\n")
        self._info_text.insert("1.0", "".join(lines))
        self._info_text.config(state=tk.DISABLED)

    def _iter_all(self, nodes):
        for n in nodes:
            yield n
            if n["type"] == "folder":
                yield from self._iter_all(n.get("children", []))

    # ── Collection & Export ───────────────────

    def _collect_selected(self):
        result = []
        for iid in self._tree.get_children(""):
            node = self._collect_node(iid)
            if node:
                result.append(node)
        return result

    def _collect_node(self, iid):
        var  = self._check_vars.get(iid)
        node = self._node_map.get(iid)
        if not node:
            return None
        if node["type"] == "bookmark":
            return dict(node) if var and var.get() else None
        # Folder: always recurse to collect checked children
        child_iids = self._tree.get_children(iid)
        children   = [cn for ci in child_iids
                      for cn in [self._collect_node(ci)] if cn]
        if (var and var.get()) or children:
            folder = dict(node)
            folder["children"] = children
            return folder
        return None

    def _export(self):
        if not self._parsed_root:
            messagebox.showwarning("No file", "Please load a bookmarks file first.")
            return
        selected  = self._collect_selected()
        bm_count  = count_bookmarks(selected)
        if bm_count == 0:
            messagebox.showwarning("Nothing selected", "No bookmarks are selected.")
            return
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = filedialog.asksaveasfilename(
            title="Save Exported Bookmarks",
            initialfile=f"bookmarks_export_{ts}.html",
            defaultextension=".html",
            filetypes=[("HTML files", "*.html"), ("All files", "*.*")])
        if not out_path:
            return
        try:
            export_to_html(selected, out_path)
            messagebox.showinfo("Export Complete",
                f"Exported {bm_count} bookmarks!\n\nSaved to:\n{out_path}")
            self._status_var.set(
                f"Exported {bm_count} bookmarks → {os.path.basename(out_path)}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export:\n{e}")


# ─────────────────────────────────────────────
#  DUPLICATES MODE
# ─────────────────────────────────────────────

class DuplicatesModeFrame(ttk.Frame):
    """
    Loads a single bookmark file, finds all URLs that appear more than once,
    and displays them grouped by URL.  The user can check which copies to keep
    and export a cleaned file containing only the kept copies.
    """

    def __init__(self, master, colors):
        super().__init__(master, style="App.TFrame")
        self._colors       = colors
        self._parsed_root  = None
        self._groups       = []        # list of (norm_url, [bookmark, ...])
        self._check_vars   = {}        # iid → BooleanVar
        self._node_map     = {}        # iid → bookmark dict
        self._all_checked  = True
        self._build_ui()

    # ── UI ───────────────────────────────────

    def _build_ui(self):
        c = self._colors

        ttk.Label(self,
            text="Finds bookmarks whose URL appears more than once.  "
                 "Check which copies to keep, then export the cleaned result.",
            style="Sub.TLabel").pack(anchor="w", pady=(0, 8))

        # Toolbar
        toolbar = ttk.Frame(self, style="App.TFrame")
        toolbar.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(toolbar, text="⊕  Open Bookmarks File", style="Accent.TButton",
                   command=self._open_file).pack(side=tk.LEFT, padx=(0, 8))
        self._file_label = ttk.Label(toolbar, text="No file loaded", style="Sub.TLabel")
        self._file_label.pack(side=tk.LEFT)

        ttk.Button(toolbar, text="⊞ Keep All",     style="Ghost.TButton",
                   command=self._select_all).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(toolbar, text="⊟ Discard All",  style="Ghost.TButton",
                   command=self._deselect_all).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(toolbar, text="⊡ Keep Second",  style="Ghost.TButton",
                   command=self._keep_second_only).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(toolbar, text="⊡ Keep First",   style="Ghost.TButton",
                   command=self._keep_first_only).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(toolbar, text="⊞ Expand All",   style="Ghost.TButton",
                   command=self._expand_all).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(toolbar, text="⊟ Collapse All", style="Ghost.TButton",
                   command=self._collapse_all).pack(side=tk.RIGHT, padx=(4, 0))

        # Filter bar
        sf = ttk.Frame(self, style="App.TFrame")
        sf.pack(fill=tk.X, pady=(0, 8))
        self._search_lbl = tk.Label(sf, text="⌕  Filter:", bg=c["bg"], fg=c["subtext"],
                 font=("Courier New", 10))
        self._search_lbl.pack(side=tk.LEFT, padx=(0, 6))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search)
        self._search_entry = tk.Entry(sf, textvariable=self._search_var,
                      bg=c["panel"], fg=c["text"],
                      insertbackground=c["text"], font=("Courier New", 10),
                      relief="flat", highlightthickness=1,
                      highlightbackground=c["sel"], highlightcolor=c["accent"])
        self._search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)
        self._search_clear_btn = tk.Button(sf, text="✕", bg=c["panel"], fg=c["subtext"], font=("Segoe UI", 9),
                  relief="flat", bd=0, command=lambda: self._search_var.set(""),
                  cursor="hand2")
        self._search_clear_btn.pack(side=tk.LEFT, padx=(4, 0))

        # Results panel
        res_outer = ttk.Frame(self, style="Panel.TFrame", padding=4)
        res_outer.pack(fill=tk.BOTH, expand=True)

        rh = ttk.Frame(res_outer, style="Panel.TFrame")
        rh.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(rh, text="DUPLICATE GROUPS", style="PanelSub.TLabel").pack(side=tk.LEFT)
        self._count_label = ttk.Label(rh, text="", style="PanelSub.TLabel")
        self._count_label.pack(side=tk.RIGHT)

        # Treeview — grouped: parent = URL group, children = individual copies
        # columns: keep | name | folder_path
        tf = ttk.Frame(res_outer, style="Panel.TFrame")
        tf.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._tree = ttk.Treeview(tf, columns=("keep", "folder"),
                                  show="tree headings", selectmode="extended")
        self._tree.heading("#0",    text="Name / URL")
        self._tree.heading("keep",  text="✓ Keep  (click header = toggle all)",
                           command=self._heading_toggle_all)
        self._tree.heading("folder", text="Folder path")
        self._tree.column("#0",     width=320, stretch=True)
        self._tree.column("keep",   width=170, stretch=False, anchor="center")
        self._tree.column("folder", width=220, stretch=False)

        # Visual tags for group headers vs copy rows
        self._tree.tag_configure("group_hdr",
            font=("Segoe UI", 10, "bold"), foreground=c["accent"])
        self._tree.tag_configure("copy_row",
            font=("Segoe UI", 10),        foreground=c["text"])
        self._tree.tag_configure("copy_discard",
            font=("Segoe UI", 10),        foreground=c["subtext"])

        vsb = ttk.Scrollbar(tf, orient=tk.VERTICAL,   command=self._tree.yview)
        hsb = ttk.Scrollbar(tf, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)

        self._tree.bind("<Button-1>", self._on_click)

        # Bottom bar
        bottom = ttk.Frame(self, style="App.TFrame")
        bottom.pack(fill=tk.X, pady=(10, 0))
        self._status_var = tk.StringVar(value="Load a bookmarks HTML file to begin")
        ttk.Label(bottom, textvariable=self._status_var,
                  style="Sub.TLabel").pack(side=tk.LEFT)
        ttk.Button(bottom, text="⬇  Export Kept Bookmarks", style="Green.TButton",
                   command=self._export).pack(side=tk.RIGHT)
        ttk.Button(bottom, text="⬇  Export Duplicates Only", style="Accent.TButton",
                   command=self._export_duplicates_only).pack(side=tk.RIGHT, padx=(0, 16))

    # ── File loading ──────────────────────────

    def _open_file(self):
        path = filedialog.askopenfilename(
            title="Select Exported Bookmark HTML File",
            filetypes=[("HTML files", "*.html *.htm"), ("All files", "*.*")])
        if not path:
            return
        self._status_var.set("Loading…")
        self._file_label.config(text="Loading…")
        self.update_idletasks()

        import threading
        def _load():
            try:
                root = parse_file(path)
            except Exception as e:
                err = str(e)
                self.after(0, lambda err=err: (
                    messagebox.showerror("Error", f"Could not read file:\n{err}"),
                    self._status_var.set("Load a bookmarks HTML file to begin"),
                    self._file_label.config(text="No file loaded"),
                ))
                return
            self.after(0, lambda: self._on_file_loaded(path, root))

        threading.Thread(target=_load, daemon=True).start()

    def _on_file_loaded(self, path, root):
        self._parsed_root = root
        self._file_label.config(text=os.path.basename(path))
        self._find_duplicates()

    # ── Duplicate detection ───────────────────

    def _find_duplicates(self, filter_term=""):
        """Walk all bookmarks, group by normalised URL, keep groups with count > 1."""
        all_bm = []
        self._collect_with_path(self._parsed_root.get("children", []), [], all_bm)

        # Group by normalised URL
        groups = defaultdict(list)
        for bm, path in all_bm:
            groups[normalise_url(bm["href"])].append((bm, path))

        # Keep only groups with 2+ copies
        self._groups = [
            (url, copies)
            for url, copies in groups.items()
            if len(copies) > 1
        ]
        self._groups.sort(key=lambda x: (-len(x[1]), x[0]))

        self._populate_tree(filter_term)

    def _collect_with_path(self, nodes, path, result):
        """Recursively collect (bookmark, folder_path_string) pairs."""
        for node in nodes:
            if node["type"] == "bookmark":
                result.append((node, " › ".join(path) if path else "(root)"))
            elif node["type"] == "folder":
                self._collect_with_path(
                    node.get("children", []),
                    path + [node.get("name") or ""],
                    result)

    # ── Tree population ───────────────────────

    def _populate_tree(self, filter_term=""):
        self._tree.delete(*self._tree.get_children())
        self._check_vars.clear()
        self._node_map.clear()

        ft         = filter_term.lower()
        total_grps = 0
        total_dups = 0

        for norm_url, copies in self._groups:
            # Apply filter
            if ft:
                match = any(
                    ft in (bm.get("name") or "").lower() or ft in (bm.get("href") or "").lower()
                    for bm, _ in copies
                )
                if not match:
                    continue

            total_grps += 1
            total_dups += len(copies)

            # Group header row (not individually checkable)
            display_url = norm_url if len(norm_url) <= 70 else norm_url[:67] + "…"
            grp_iid = self._tree.insert("", "end",
                text=f"  🔗  {display_url}",
                values=(f"{len(copies)} copies", ""),
                open=True,
                tags=("group_hdr",))

            for bm, folder_path in copies:
                name = bm.get("name") or "(unnamed)"
                var  = tk.BooleanVar(value=True)
                iid  = self._tree.insert(grp_iid, "end",
                    text=f"    📌  {name}",
                    values=("☑  Keep", folder_path),
                    tags=("copy_row",))
                self._check_vars[iid] = var
                self._node_map[iid]   = bm

        dup_bm = total_dups - total_grps   # extra copies beyond the first
        self._count_label.config(
            text=f"{total_grps} duplicate groups  |  {total_dups} total copies  "
                 f"({dup_bm} redundant)")
        self._status_var.set(
            f"{total_grps} URLs with duplicates — review and export a cleaned file")
        self._all_checked = True

    # ── Interaction ───────────────────────────

    def _on_click(self, event):
        col = self._tree.identify_column(event.x)
        iid = self._tree.identify_row(event.y)
        if not iid:
            return
        # Only act on copy rows (group headers have no check_var)
        if iid in self._check_vars and col == "#1":
            self._toggle(iid)
            return "break"

    def _toggle(self, iid, state=None):
        if iid not in self._check_vars:
            return
        var       = self._check_vars[iid]
        new_state = state if state is not None else not var.get()
        var.set(new_state)
        self._tree.item(iid,
            values=("☑  Keep" if new_state else "☐  Discard",
                    self._tree.item(iid, "values")[1]),
            tags=("copy_row" if new_state else "copy_discard",))

    def _heading_toggle_all(self):
        self._all_checked = not self._all_checked
        for iid in list(self._check_vars.keys()):
            self._toggle(iid, self._all_checked)

    def _select_all(self):
        for iid in self._check_vars:
            self._toggle(iid, True)
        self._all_checked = True

    def _deselect_all(self):
        for iid in self._check_vars:
            self._toggle(iid, False)
        self._all_checked = False

    def _keep_first_only(self):
        """For every duplicate group, keep only the first copy, discard the rest."""
        for grp_iid in self._tree.get_children(""):
            child_iids = self._tree.get_children(grp_iid)
            for idx, ciid in enumerate(child_iids):
                if ciid in self._check_vars:
                    self._toggle(ciid, idx == 0)

    def _keep_second_only(self):
        """For every duplicate group, keep only the second copy, discard the rest."""
        for grp_iid in self._tree.get_children(""):
            child_iids = self._tree.get_children(grp_iid)
            for idx, ciid in enumerate(child_iids):
                if ciid in self._check_vars:
                    self._toggle(ciid, idx == 1)

    def _on_search(self, *_):
        if self._parsed_root:
            self._find_duplicates(filter_term=self._search_var.get().strip())

    # ── Export ────────────────────────────────

    def _export_duplicates_only(self):
        """Export only the checked duplicate copies as a flat bookmark list."""
        checked = [self._node_map[iid]
                   for iid, var in self._check_vars.items() if var.get()]
        if not checked:
            messagebox.showwarning("Nothing checked",
                                   "Check at least one duplicate copy to export.")
            return
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = filedialog.asksaveasfilename(
            title="Save Duplicate Bookmarks",
            initialfile=f"bookmarks_duplicates_{ts}.html",
            defaultextension=".html",
            filetypes=[("HTML files", "*.html"), ("All files", "*.*")])
        if not out_path:
            return
        try:
            export_to_html(checked, out_path)
            messagebox.showinfo("Export Complete",
                f"Exported {len(checked)} duplicate bookmark(s).\n\n"
                f"Saved to:\n{out_path}")
            self._status_var.set(
                f"Exported {len(checked)} duplicates → {os.path.basename(out_path)}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export:\n{e}")

    def _export(self):
        if not self._parsed_root:
            messagebox.showwarning("No file", "Please load a bookmarks file first.")
            return

        # Build a set of IDs of bookmarks to REMOVE (unchecked copies)
        ids_to_remove = {
            id(self._node_map[iid])
            for iid, var in self._check_vars.items()
            if not var.get()
        }

        # Optionally inform the user that the output is identical to the original
        if not ids_to_remove:
            proceed = messagebox.askokcancel(
                "No duplicates removed",
                "All duplicates are marked Keep, so the exported file will be "
                "identical to the original.\n\nContinue anyway?")
            if not proceed:
                return

        # Deep-copy the tree, dropping bookmarks that are in ids_to_remove
        def clean(nodes):
            result = []
            for node in nodes:
                if node["type"] == "bookmark":
                    if id(node) not in ids_to_remove:
                        result.append(dict(node))
                elif node["type"] == "folder":
                    children = clean(node.get("children", []))
                    folder   = dict(node)
                    folder["children"] = children
                    result.append(folder)
            return result

        cleaned = clean(self._parsed_root.get("children", []))

        kept_bm     = count_bookmarks(cleaned)
        removed_bm  = len(ids_to_remove)
        ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path    = filedialog.asksaveasfilename(
            title="Save Cleaned Bookmarks",
            initialfile=f"bookmarks_deduped_{ts}.html",
            defaultextension=".html",
            filetypes=[("HTML files", "*.html"), ("All files", "*.*")])
        if not out_path:
            return
        try:
            export_to_html(cleaned, out_path)
            messagebox.showinfo("Export Complete",
                f"Removed {removed_bm} duplicate copies.\n"
                f"Kept {kept_bm} bookmarks.\n\n"
                f"Saved to:\n{out_path}")
            self._status_var.set(
                f"Exported {kept_bm} bookmarks (removed {removed_bm} duplicates) "
                f"→ {os.path.basename(out_path)}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export:\n{e}")

    # ── Expand / Collapse ─────────────────────

    def _expand_all(self):
        for iid in self._tree.get_children(""):
            self._tree.item(iid, open=True)

    def _collapse_all(self):
        for iid in self._tree.get_children(""):
            self._tree.item(iid, open=False)

    # ── Keyboard shortcut targets ─────────────

    def _shortcut_open(self):
        self._open_file()

    def _shortcut_export(self):
        self._export()

    def _shortcut_focus_filter(self):
        self._search_entry.focus_set()

    def apply_colors(self, c):
        """Update manually-colored widgets when theme changes."""
        self._colors = c
        self._search_lbl.config(bg=c["bg"], fg=c["subtext"])
        self._search_entry.config(bg=c["panel"], fg=c["text"],
                                  insertbackground=c["text"],
                                  highlightbackground=c["sel"],
                                  highlightcolor=c["accent"])
        self._search_clear_btn.config(bg=c["panel"], fg=c["subtext"])
        self._tree.tag_configure("group_hdr", foreground=c["accent"])
        self._tree.tag_configure("copy_row",  foreground=c["text"])
        self._tree.tag_configure("copy_discard", foreground=c["subtext"])


# ─────────────────────────────────────────────
#  COMPARE MODE
# ─────────────────────────────────────────────

class CompareModeFrame(ttk.Frame):
    def __init__(self, master, colors):
        super().__init__(master, style="App.TFrame")
        self._colors            = colors
        self._root_a            = None
        self._root_b            = None
        self._count_a           = 0    # cached total for file A (set on load)
        self._count_b           = 0    # cached total for file B (set on load)
        self._result_bookmarks  = []   # full list after last compare
        self._check_vars        = {}   # iid → BooleanVar
        self._node_map          = {}   # iid → bookmark dict
        self._all_checked       = True
        self._build_ui()

    # ── UI ───────────────────────────────────

    def _build_ui(self):
        c = self._colors

        ttk.Label(self,
            text="Compares bookmarks by full URL (case-insensitive). "
                 "Bookmark names are ignored — only the link address is matched.",
            style="Sub.TLabel").pack(anchor="w", pady=(0, 8))

        # ── File loader row ──────────────────
        files_frame = ttk.Frame(self, style="App.TFrame")
        files_frame.pack(fill=tk.X, pady=(0, 8))

        for which, attr_label in [("A", "_label_a"), ("B", "_label_b")]:
            panel = ttk.Frame(files_frame, style="Panel.TFrame", padding=10)
            panel.pack(side=tk.LEFT, fill=tk.X, expand=True,
                       padx=(0, 6) if which == "A" else (6, 0))
            ttk.Label(panel, text=f"FILE {which}", style="PanelSub.TLabel").pack(anchor="w")
            lbl = ttk.Label(panel, text="No file loaded", style="Panel.TLabel")
            lbl.pack(anchor="w", pady=(2, 6))
            setattr(self, attr_label, lbl)
            ttk.Button(panel, text=f"⊕  Open File {which}", style="Accent.TButton",
                       command=lambda w=which: self._load_file(w)).pack(anchor="w")
            if which == "A":
                # Swap button centred between the two file panels
                swap_col = ttk.Frame(files_frame, style="App.TFrame")
                swap_col.pack(side=tk.LEFT, padx=4)
                tk.Button(swap_col, text="⇄", font=("Segoe UI", 14),
                          bg=self._colors["sel"], fg=self._colors["text"],
                          relief="flat", bd=0, padx=8, pady=4, cursor="hand2",
                          command=self._swap_files).pack(expand=True)

        # ── Compare-mode buttons (click = select + run immediately) ───
        ctrl = ttk.Frame(self, style="App.TFrame")
        ctrl.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(ctrl, text="Show:", style="App.TLabel").pack(side=tk.LEFT, padx=(0, 8))

        self._mode_btns   = {}   # val → tk.Button
        self._active_mode = "only_in_a"

        for label, val in [
            ("Only in A",    "only_in_a"),
            ("Only in B",    "only_in_b"),
            ("In both",      "in_both"),
            ("Either in A or B only (Not in both)",  "not_in_both"),
        ]:
            btn = tk.Button(ctrl, text=label,
                            bg=c["sel"], fg=c["text"],
                            font=("Segoe UI", 10),
                            relief="flat", bd=0, padx=12, pady=6,
                            cursor="hand2",
                            command=lambda v=val: self._select_mode(v))
            btn.pack(side=tk.LEFT, padx=(0, 4))
            self._mode_btns[val] = btn

        # Highlight the default selection
        self._mode_btns["only_in_a"].config(bg=c["accent"], fg="#ffffff",
                                            font=("Segoe UI", 10, "bold"))

        # ── Results panel ────────────────────
        res_outer = ttk.Frame(self, style="Panel.TFrame", padding=4)
        res_outer.pack(fill=tk.BOTH, expand=True)

        rh = ttk.Frame(res_outer, style="Panel.TFrame")
        rh.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(rh, text="COMPARISON RESULTS", style="PanelSub.TLabel").pack(side=tk.LEFT)
        self._res_count = ttk.Label(rh, text="", style="PanelSub.TLabel")
        self._res_count.pack(side=tk.RIGHT)

        # Select all / deselect all buttons
        sel_bar = ttk.Frame(res_outer, style="Panel.TFrame")
        sel_bar.pack(fill=tk.X, padx=4, pady=(0, 2))
        ttk.Button(sel_bar, text="⊞ Select All", style="Ghost.TButton",
                   command=self._select_all_results).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(sel_bar, text="⊟ Deselect All", style="Ghost.TButton",
                   command=self._deselect_all_results).pack(side=tk.LEFT)

        # Filter bar
        sf = ttk.Frame(res_outer, style="Panel.TFrame")
        sf.pack(fill=tk.X, padx=4, pady=(0, 4))
        self._res_search_lbl = tk.Label(sf, text="⌕  Filter:", bg=c["panel"], fg=c["subtext"],
                 font=("Courier New", 9))
        self._res_search_lbl.pack(side=tk.LEFT, padx=(0, 4))
        self._res_search_var = tk.StringVar()
        self._res_search_var.trace_add("write", self._on_res_search)
        self._res_search_entry = tk.Entry(sf, textvariable=self._res_search_var,
                      bg="#f8fafc", fg=c["text"],
                      insertbackground=c["text"], font=("Courier New", 9),
                      relief="flat", highlightthickness=1,
                      highlightbackground=c["sel"], highlightcolor=c["accent"])
        self._res_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        self._res_search_clear = tk.Button(sf, text="✕", bg=c["panel"], fg=c["subtext"],
                  font=("Segoe UI", 9), relief="flat", bd=0,
                  command=lambda: self._res_search_var.set(""),
                  cursor="hand2")
        self._res_search_clear.pack(side=tk.LEFT, padx=(4, 0))

        # columns: check | source | url
        # #0 = Name tree column, #1 = check, #2 = source, #3 = url
        rf = ttk.Frame(res_outer, style="Panel.TFrame")
        rf.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        self._res_tree = ttk.Treeview(rf, columns=("check", "source", "url"),
                                      show="tree headings", selectmode="extended")
        self._res_tree.heading("#0",     text="Name")
        self._res_tree.heading("check",  text="✓  (click to toggle all)",
                               command=self._heading_toggle_all_results)
        self._res_tree.heading("source", text="Source")
        self._res_tree.heading("url",    text="URL")
        self._res_tree.column("#0",      width=240, stretch=False)
        self._res_tree.column("check",   width=140, stretch=False, anchor="center")
        self._res_tree.column("source",  width=62,  stretch=False, anchor="center")
        self._res_tree.column("url",     width=380, stretch=True)

        # Tag colours for A / B badges
        self._res_tree.tag_configure("src_a",  foreground="#1d4ed8", font=("Segoe UI", 10, "bold"))
        self._res_tree.tag_configure("src_b",  foreground="#15803d", font=("Segoe UI", 10, "bold"))
        self._res_tree.tag_configure("src_ab", foreground="#64748b", font=("Segoe UI", 10, "bold"))

        vsb = ttk.Scrollbar(rf, orient=tk.VERTICAL,   command=self._res_tree.yview)
        hsb = ttk.Scrollbar(rf, orient=tk.HORIZONTAL, command=self._res_tree.xview)
        self._res_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._res_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        rf.rowconfigure(0, weight=1)
        rf.columnconfigure(0, weight=1)

        # Bind click on check column (#1)
        self._res_tree.bind("<Button-1>", self._on_res_click)

        # Bottom bar
        bottom = ttk.Frame(self, style="App.TFrame")
        bottom.pack(fill=tk.X, pady=(8, 0))
        self._cmp_status = tk.StringVar(value="Load both files and click Compare")
        ttk.Label(bottom, textvariable=self._cmp_status,
                  style="Sub.TLabel").pack(side=tk.LEFT)
        ttk.Button(bottom, text="⬇  Export Checked Results", style="Green.TButton",
                   command=self._export_results).pack(side=tk.RIGHT)

    # ── File Loading ─────────────────────────

    def _swap_files(self):
        """Swap File A and File B, then re-run the comparison."""
        self._root_a,  self._root_b  = self._root_b,  self._root_a
        self._count_a, self._count_b = self._count_b, self._count_a
        text_a = self._label_a.cget("text")
        text_b = self._label_b.cget("text")
        self._label_a.config(text=text_b)
        self._label_b.config(text=text_a)
        if self._root_a and self._root_b:
            self._run_compare()
        elif self._root_a or self._root_b:
            self._cmp_status.set("Files swapped. Load the missing file to compare.")

    def _load_file(self, which):
        path = filedialog.askopenfilename(
            title=f"Select Bookmark File {which}",
            filetypes=[("HTML files", "*.html *.htm"), ("All files", "*.*")])
        if not path:
            return
        lbl = self._label_a if which == "A" else self._label_b
        lbl.config(text="Loading…")
        self._cmp_status.set(f"Loading File {which}…")
        self.update_idletasks()

        import threading
        def _load():
            try:
                root = parse_file(path)
            except Exception as e:
                err = str(e)
                self.after(0, lambda err=err: (
                    messagebox.showerror("Error", f"Could not read file:\n{err}"),
                    lbl.config(text="No file loaded"),
                    self._cmp_status.set("Load both files and click Compare"),
                ))
                return
            self.after(0, lambda: self._on_file_loaded(which, path, root))

        threading.Thread(target=_load, daemon=True).start()

    def _on_file_loaded(self, which, path, root):
        name = os.path.basename(path)
        count = count_bookmarks(root.get("children", []))   # compute once on load
        if which == "A":
            self._root_a  = root
            self._count_a = count
            self._label_a.config(text=f"✔  {name}")
        else:
            self._root_b  = root
            self._count_b = count
            self._label_b.config(text=f"✔  {name}")
        self._cmp_status.set(
            f"File {which} loaded ({count} bookmarks). "
            "Click ⇌ Compare when both files are ready.")
        # Auto-run if both files are now loaded
        if self._root_a and self._root_b:
            self._run_compare()

    # ── Mode selection ────────────────────────

    def _select_mode(self, val):
        c = self._colors
        # Update button highlight
        for v, btn in self._mode_btns.items():
            if v == val:
                btn.config(bg=c["accent"], fg="#ffffff",
                           font=("Segoe UI", 10, "bold"))
            else:
                btn.config(bg=c["sel"], fg=c["text"],
                           font=("Segoe UI", 10))
        self._active_mode = val
        # Auto-run if both files loaded
        if self._root_a and self._root_b:
            self._run_compare()
        else:
            missing = []
            if not self._root_a: missing.append("A")
            if not self._root_b: missing.append("B")
            self._cmp_status.set(
                f"Mode set. Load file{'s' if len(missing)>1 else ''} "
                f"{' and '.join(missing)} to compare.")

    # ── Comparison ───────────────────────────

    def _run_compare(self):
        if not self._root_a or not self._root_b:
            messagebox.showwarning("Missing Files",
                                   "Please load both File A and File B first.")
            return

        bm_a = collect_all_bookmarks(self._root_a)
        bm_b = collect_all_bookmarks(self._root_b)

        set_a = {normalise_url(b["href"]) for b in bm_a}
        set_b = {normalise_url(b["href"]) for b in bm_b}

        mode = self._active_mode
        if mode == "only_in_a":
            result = [dict(b, _source="A") for b in bm_a if normalise_url(b["href"]) not in set_b]
        elif mode == "only_in_b":
            result = [dict(b, _source="B") for b in bm_b if normalise_url(b["href"]) not in set_a]
        elif mode == "in_both":
            result = [dict(b, _source="A+B") for b in bm_a if normalise_url(b["href"]) in set_b]
        else:   # not_in_both
            only_a = [dict(b, _source="A") for b in bm_a if normalise_url(b["href"]) not in set_b]
            only_b = [dict(b, _source="B") for b in bm_b if normalise_url(b["href"]) not in set_a]
            result = only_a + only_b

        self._result_bookmarks = result
        self._populate_results(result)

    # ── Results tree ─────────────────────────

    def _populate_results(self, bookmarks, filter_term=""):
        self._res_tree.delete(*self._res_tree.get_children())
        self._check_vars.clear()
        self._node_map.clear()

        ft = filter_term.lower()
        for bm in bookmarks:
            name   = bm.get("name") or "(unnamed)"
            href   = bm.get("href") or ""
            source = bm.get("_source", "")          # "A", "B", or ""
            if ft and ft not in name.lower() and ft not in href.lower():
                continue
            var = tk.BooleanVar(value=True)
            badge    = f"[{source}]" if source else ""
            src_tag  = {"A": "src_a", "B": "src_b", "A+B": "src_ab"}.get(source, "")
            iid = self._res_tree.insert("", "end",
                      text=f"  🔖  {name}",
                      values=("☑", badge, href),
                      tags=(src_tag,) if src_tag else ())
            self._check_vars[iid] = var
            self._node_map[iid]   = bm

        count = len(self._node_map)
        self._res_count.config(text=f"{count} bookmarks")

        mode = self._active_mode
        mode_labels = {
            "only_in_a":   "unique to File A",
            "only_in_b":   "unique to File B",
            "in_both":     "present in both files",
            "not_in_both": "unique across both files (non-matching)",
        }
        total_a = self._count_a
        total_b = self._count_b
        self._cmp_status.set(
            f"Found {count} bookmarks {mode_labels.get(mode, '')}  "
            f"(A: {total_a} total  |  B: {total_b} total)")
        self._all_checked = True

    def _on_res_search(self, *_):
        if self._result_bookmarks:
            self._populate_results(self._result_bookmarks,
                                   filter_term=self._res_search_var.get().strip())

    # ── Check interactions ────────────────────

    def _on_res_click(self, event):
        col = self._res_tree.identify_column(event.x)
        iid = self._res_tree.identify_row(event.y)
        if iid and col == "#1":      # "#1" = "check" column
            self._toggle_result(iid)
            return "break"

    def _heading_toggle_all_results(self):
        self._all_checked = not self._all_checked
        new_sym = "☑" if self._all_checked else "☐"
        for iid, var in self._check_vars.items():
            var.set(self._all_checked)
            vals = self._res_tree.item(iid, "values")
            self._res_tree.item(iid, values=(new_sym, vals[1] if len(vals) > 1 else "", vals[2] if len(vals) > 2 else ""))

    def _toggle_result(self, iid, state=None):
        if iid not in self._check_vars:
            return
        var       = self._check_vars[iid]
        new_state = state if state is not None else not var.get()
        var.set(new_state)
        vals = self._res_tree.item(iid, "values")
        self._res_tree.item(iid,
            values=("☑" if new_state else "☐",
                    vals[1] if len(vals) > 1 else "",
                    vals[2] if len(vals) > 2 else ""))

    def _select_all_results(self):
        for iid in self._check_vars:
            self._toggle_result(iid, True)
        self._all_checked = True

    def _deselect_all_results(self):
        for iid in self._check_vars:
            self._toggle_result(iid, False)
        self._all_checked = False

    # ── Export ────────────────────────────────

    def _export_results(self):
        checked = [self._node_map[iid]
                   for iid, var in self._check_vars.items() if var.get()]
        if not checked:
            messagebox.showwarning("Nothing checked",
                                   "Check at least one bookmark to export.")
            return
        ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
        mode   = self._active_mode
        suffix = {
            "only_in_a":   "unique_to_A",
            "only_in_b":   "unique_to_B",
            "in_both":     "matching",
            "not_in_both": "non_matching",
        }.get(mode, "compare")
        out_path = filedialog.asksaveasfilename(
            title="Save Comparison Export",
            initialfile=f"bookmarks_{suffix}_{ts}.html",
            defaultextension=".html",
            filetypes=[("HTML files", "*.html"), ("All files", "*.*")])
        if not out_path:
            return
        try:
            export_to_html(checked, out_path)
            messagebox.showinfo("Export Complete",
                f"Exported {len(checked)} bookmarks!\n\nSaved to:\n{out_path}\n\n"
                "You can import this file into any browser.")
            self._cmp_status.set(
                f"Exported {len(checked)} bookmarks → {os.path.basename(out_path)}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export:\n{e}")

    # ── Keyboard shortcut targets ─────────────

    def _shortcut_open(self):
        # Open whichever file slot isn't loaded yet; if both are loaded, ask which to replace
        if not self._root_a:
            self._load_file("A")
        elif not self._root_b:
            self._load_file("B")
        else:
            # Both files already loaded — ask the user which one to replace
            answer = messagebox.askquestion(
                "Replace file",
                "Both files are already loaded.\n\nReplace File A? (No = replace File B)",
                icon="question",
            )
            self._load_file("A" if answer == "yes" else "B")

    def _shortcut_export(self):
        self._export_results()

    def _shortcut_focus_filter(self):
        self._res_search_entry.focus_set()

    def apply_colors(self, c):
        """Update manually-colored widgets when theme changes."""
        self._colors = c
        self._res_search_lbl.config(bg=c["panel"], fg=c["subtext"])
        self._res_search_entry.config(
            bg=c["panel"], fg=c["text"],
            insertbackground=c["text"],
            highlightbackground=c["sel"],
            highlightcolor=c["accent"])
        self._res_search_clear.config(bg=c["panel"], fg=c["subtext"])
        # Update mode buttons
        for v, btn in self._mode_btns.items():
            if v == self._active_mode:
                btn.config(bg=c["accent"], fg="#ffffff")
            else:
                btn.config(bg=c["sel"], fg=c["text"])


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app = BookmarkExtractorApp()
    app.mainloop()

#!/usr/bin/env python3
"""
Bookmark Extractor - Two modes:
  1. Normal   – select/filter/export bookmarks from a single file
  2. Compare  – load two exports, compare by URL, export matching or non-matching bookmarks

Compare mode compares bookmarks by their full URL (case-insensitive, trailing slash ignored).
The bookmark name/title is NOT used for matching — only the link address (href).
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from html.parser import HTMLParser
import os
from datetime import datetime


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
            if self._pending_folder_name is not None:
                folder = {
                    "type": "folder",
                    "name": self._pending_folder_name,
                    "children": [],
                    "href": None,
                    "add_date": attrs.get("add_date"),
                }
                self._stack[-1]["children"].append(folder)
                self._stack.append(folder)
                self._pending_folder_name = None
        elif tag.upper() == "H3":
            self._pending_folder_name = ""
        elif tag.upper() == "A":
            self._pending_bookmark = {
                "type": "bookmark",
                "name": "",
                "href": attrs.get("href", ""),
                "add_date": attrs.get("add_date"),
                "icon": attrs.get("icon"),
            }

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
            href = node.get("href", "")
            name = escape_html(node.get("name", ""))
            lines.append(f'{pad}<DT><A HREF="{href}">{name}</A>')

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


def normalise_url(url):
    return (url or "").strip().rstrip("/").lower()


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

        self._setup_styles()
        c = self._colors

        tab_bar = tk.Frame(self, bg=c["bg"])
        tab_bar.pack(fill=tk.X, padx=20, pady=(16, 0))

        self._btn_normal  = self._make_tab_btn(tab_bar, "◈  Normal Mode",  "normal")
        self._btn_compare = self._make_tab_btn(tab_bar, "⇌  Compare Mode", "compare")
        self._btn_normal.pack(side=tk.LEFT, padx=(0, 4))
        self._btn_compare.pack(side=tk.LEFT)

        self._normal_frame  = NormalModeFrame(self, self._colors)
        self._compare_frame = CompareModeFrame(self, self._colors)

        self._switch_mode("normal")

    def _make_tab_btn(self, parent, label, mode):
        c = self._colors
        return tk.Button(parent, text=label,
            bg=c["accent"], fg="#ffffff",
            font=("Segoe UI", 10, "bold"),
            relief="flat", bd=0, padx=14, pady=7,
            cursor="hand2",
            command=lambda m=mode: self._switch_mode(m))

    def _switch_mode(self, mode):
        c = self._colors
        if mode == "normal":
            self._compare_frame.pack_forget()
            self._normal_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=12)
            self._btn_normal.config(bg=c["accent"], fg="#ffffff")
            self._btn_compare.config(bg=c["sel"], fg=c["text"])
        else:
            self._normal_frame.pack_forget()
            self._compare_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=12)
            self._btn_compare.config(bg=c["accent"], fg="#ffffff")
            self._btn_normal.config(bg=c["sel"], fg=c["text"])

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        bg      = "#f0f4f8"
        panel   = "#ffffff"
        accent  = "#2563eb"
        accent2 = "#16a34a"
        danger  = "#dc2626"
        text    = "#1e293b"
        subtext = "#64748b"
        sel     = "#bfdbfe"

        style.configure("App.TFrame",    background=bg)
        style.configure("Panel.TFrame",  background=panel)
        style.configure("App.TLabel",    background=bg,    foreground=text,    font=("Segoe UI", 10))
        style.configure("Title.TLabel",  background=bg,    foreground=text,    font=("Segoe UI", 15, "bold"))
        style.configure("Sub.TLabel",    background=bg,    foreground=subtext, font=("Segoe UI", 9))
        style.configure("Panel.TLabel",  background=panel, foreground=text,    font=("Segoe UI", 10))
        style.configure("PanelSub.TLabel", background=panel, foreground=subtext, font=("Segoe UI", 9))

        for name, bg_col, hover in [
            ("Accent.TButton",  accent,  "#1d4ed8"),
            ("Green.TButton",   accent2, "#15803d"),
            ("Danger.TButton",  danger,  "#b91c1c"),
        ]:
            style.configure(name, background=bg_col, foreground="#ffffff",
                            font=("Segoe UI", 10, "bold"), borderwidth=0,
                            relief="flat", padding=(12, 6))
            style.map(name, background=[("active", hover)])

        style.configure("Ghost.TButton", background=panel, foreground=subtext,
                        font=("Segoe UI", 9), borderwidth=1, relief="solid", padding=(8, 4))
        style.map("Ghost.TButton", background=[("active", "#f1f5f9")])

        style.configure("Treeview", background=panel, foreground=text,
                        fieldbackground=panel, rowheight=26,
                        font=("Segoe UI", 10), borderwidth=0)
        style.configure("Treeview.Heading", background="#e2e8f0", foreground=subtext,
                        font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Treeview",
                  background=[("selected", sel)],
                  foreground=[("selected", text)])
        style.configure("TScrollbar", background="#e2e8f0", troughcolor=bg,
                        arrowcolor=subtext, borderwidth=0)

        self._colors = {
            "bg": bg, "panel": panel, "accent": accent,
            "accent2": accent2, "danger": danger,
            "text": text, "subtext": subtext, "sel": sel
        }


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
        ttk.Button(toolbar, text="⊞ Select All", style="Ghost.TButton",
                   command=self._select_all).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(toolbar, text="⊟ Deselect All", style="Ghost.TButton",
                   command=self._deselect_all).pack(side=tk.RIGHT, padx=(4, 0))

        sf = ttk.Frame(self, style="App.TFrame")
        sf.pack(fill=tk.X, pady=(0, 8))
        tk.Label(sf, text="⌕  Search:", bg=c["bg"], fg=c["subtext"],
                 font=("Courier New", 10)).pack(side=tk.LEFT, padx=(0, 6))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search)
        se = tk.Entry(sf, textvariable=self._search_var, bg=c["panel"], fg=c["text"],
                      insertbackground=c["text"], font=("Courier New", 10), relief="flat",
                      highlightthickness=1, highlightbackground=c["sel"],
                      highlightcolor=c["accent"])
        se.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)
        tk.Button(sf, text="✕", bg=c["panel"], fg=c["subtext"], font=("Segoe UI", 9),
                  relief="flat", bd=0, command=lambda: self._search_var.set(""),
                  cursor="hand2").pack(side=tk.LEFT, padx=(4, 0))

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

        self._tree.bind("<Button-1>", self._on_tree_click)
        self._tree.bind("<<TreeviewSelect>>", lambda e: self._update_info())

        info_outer = ttk.Frame(pane, style="Panel.TFrame", padding=8)
        pane.add(info_outer, minsize=200, stretch="never")
        ttk.Label(info_outer, text="SELECTION INFO", style="PanelSub.TLabel").pack(anchor="w")
        self._info_text = tk.Text(info_outer, bg=c["panel"], fg=c["text"],
                                  font=("Segoe UI", 9), relief="flat",
                                  wrap=tk.WORD, width=28, state=tk.DISABLED,
                                  highlightthickness=0)
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
        try:
            self._parsed_root = parse_file(path)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read file:\n{e}")
            return
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

    def _on_tree_click(self, event):
        col = self._tree.identify_column(event.x)
        iid = self._tree.identify_row(event.y)
        if iid and col == "#1":          # "#1" = first named column = "check"
            self._toggle_check(iid)
            return "break"

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
        for iid in self._node_map:
            var = self._check_vars.get(iid)
            if var:
                var.set(True)
            vals = self._tree.item(iid, "values")
            ntype = vals[1] if len(vals) > 1 else ""
            self._tree.item(iid, values=("☑", ntype))
        self._all_checked = True
        self._update_info()

    def _deselect_all(self):
        for iid in self._node_map:
            var = self._check_vars.get(iid)
            if var:
                var.set(False)
            vals = self._tree.item(iid, "values")
            ntype = vals[1] if len(vals) > 1 else ""
            self._tree.item(iid, values=("☐", ntype))
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
                    lines.append(f"\n  {node.get('href','')[:40]}\n")
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
        if var and var.get():
            folder = dict(node); folder["children"] = children; return folder
        elif children:
            folder = dict(node); folder["children"] = children; return folder
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
#  COMPARE MODE
# ─────────────────────────────────────────────

class CompareModeFrame(ttk.Frame):
    def __init__(self, master, colors):
        super().__init__(master, style="App.TFrame")
        self._colors            = colors
        self._root_a            = None
        self._root_b            = None
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

        # ── Compare-mode buttons (click = select + run immediately) ───
        ctrl = ttk.Frame(self, style="App.TFrame")
        ctrl.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(ctrl, text="Show:", style="App.TLabel").pack(side=tk.LEFT, padx=(0, 8))

        self._mode_var    = tk.StringVar(value="only_in_a")
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
        tk.Label(sf, text="⌕  Filter:", bg=c["panel"], fg=c["subtext"],
                 font=("Courier New", 9)).pack(side=tk.LEFT, padx=(0, 4))
        self._res_search_var = tk.StringVar()
        self._res_search_var.trace_add("write", self._on_res_search)
        se = tk.Entry(sf, textvariable=self._res_search_var,
                      bg="#f8fafc", fg=c["text"],
                      insertbackground=c["text"], font=("Courier New", 9),
                      relief="flat", highlightthickness=1,
                      highlightbackground=c["sel"], highlightcolor=c["accent"])
        se.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        tk.Button(sf, text="✕", bg=c["panel"], fg=c["subtext"],
                  font=("Segoe UI", 9), relief="flat", bd=0,
                  command=lambda: self._res_search_var.set(""),
                  cursor="hand2").pack(side=tk.LEFT, padx=(4, 0))

        # Results treeview
        # columns: check | url
        # #0 = Name tree column, #1 = check, #2 = url
        rf = ttk.Frame(res_outer, style="Panel.TFrame")
        rf.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        self._res_tree = ttk.Treeview(rf, columns=("check", "url"),
                                      show="tree headings", selectmode="extended")
        self._res_tree.heading("#0",    text="Name")
        self._res_tree.heading("check", text="✓  (click to toggle all)",
                               command=self._heading_toggle_all_results)
        self._res_tree.heading("url",   text="URL")
        self._res_tree.column("#0",     width=260, stretch=False)
        self._res_tree.column("check",  width=150, stretch=False, anchor="center")
        self._res_tree.column("url",    width=400, stretch=True)

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

    def _load_file(self, which):
        path = filedialog.askopenfilename(
            title=f"Select Bookmark File {which}",
            filetypes=[("HTML files", "*.html *.htm"), ("All files", "*.*")])
        if not path:
            return
        try:
            root = parse_file(path)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read file:\n{e}")
            return
        name = os.path.basename(path)
        if which == "A":
            self._root_a = root
            self._label_a.config(text=f"✔  {name}")
        else:
            self._root_b = root
            self._label_b.config(text=f"✔  {name}")
        count = count_bookmarks(root.get("children", []))
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
        self._mode_var.set(val)
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
            result = [b for b in bm_a if normalise_url(b["href"]) not in set_b]
        elif mode == "only_in_b":
            result = [b for b in bm_b if normalise_url(b["href"]) not in set_a]
        elif mode == "in_both":
            result = [b for b in bm_a if normalise_url(b["href"]) in set_b]
        else:   # not_in_both
            only_a = [b for b in bm_a if normalise_url(b["href"]) not in set_b]
            only_b = [b for b in bm_b if normalise_url(b["href"]) not in set_a]
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
            name = bm.get("name") or "(unnamed)"
            href = bm.get("href") or ""
            if ft and ft not in name.lower() and ft not in href.lower():
                continue
            var = tk.BooleanVar(value=True)
            iid = self._res_tree.insert("", "end",
                      text=f"  🔖  {name}",
                      values=("☑", href))
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
        total_a = count_bookmarks(self._root_a.get("children", [])) if self._root_a else 0
        total_b = count_bookmarks(self._root_b.get("children", [])) if self._root_b else 0
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
            self._res_tree.item(iid, values=(new_sym, vals[1] if len(vals) > 1 else ""))

    def _toggle_result(self, iid, state=None):
        if iid not in self._check_vars:
            return
        var       = self._check_vars[iid]
        new_state = state if state is not None else not var.get()
        var.set(new_state)
        vals = self._res_tree.item(iid, "values")
        self._res_tree.item(iid,
            values=("☑" if new_state else "☐", vals[1] if len(vals) > 1 else ""))

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


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app = BookmarkExtractorApp()
    app.mainloop()

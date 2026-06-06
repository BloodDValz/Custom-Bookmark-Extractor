#!/usr/bin/env python3
"""
Bookmark Extractor - Select and export specific folders/bookmarks
from browser-exported bookmark HTML files (Chrome, Firefox, Edge, Safari).
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from html.parser import HTMLParser
import os
import re
from datetime import datetime


# ─────────────────────────────────────────────
#  PARSER
# ─────────────────────────────────────────────

class BookmarkParser(HTMLParser):
    """Parse Netscape Bookmark HTML format used by all major browsers."""

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
            # Push a new child container if we have a pending folder
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
            # Next data will be folder name
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
#  EXPORTER
# ─────────────────────────────────────────────

def export_to_html(selected_nodes, output_path):
    """Write a valid Netscape bookmark HTML file from selected nodes."""
    lines = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        "<!-- This is an automatically generated file.",
        "     It will be read and overwritten.",
        "     DO NOT EDIT! -->",
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

    for node in selected_nodes:
        write_node(node)

    lines.append("</DL><p>")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def escape_html(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def count_bookmarks(nodes):
    """Count total bookmarks (not folders) in a list of nodes recursively."""
    total = 0
    for node in nodes:
        if node["type"] == "bookmark":
            total += 1
        elif node["type"] == "folder":
            total += count_bookmarks(node.get("children", []))
    return total


# ─────────────────────────────────────────────
#  GUI
# ─────────────────────────────────────────────

class BookmarkExtractorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bookmark Extractor")
        self.geometry("880x640")
        self.minsize(700, 500)
        self.configure(bg="#f0f4f8")

        self._parsed_root = None
        self._node_map = {}       # iid → node dict
        self._check_vars = {}     # iid → BooleanVar (checked state)
        self._children_map = {}   # iid → list of child iids

        self._setup_styles()
        self._build_ui()

    # ── Styles ──────────────────────────────

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        bg = "#f0f4f8"
        panel = "#ffffff"
        accent = "#2563eb"
        accent2 = "#16a34a"
        text = "#1e293b"
        subtext = "#64748b"
        sel = "#bfdbfe"

        style.configure("App.TFrame", background=bg)
        style.configure("Panel.TFrame", background=panel)
        style.configure("App.TLabel", background=bg, foreground=text,
                        font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=bg, foreground=text,
                        font=("Segoe UI", 16, "bold"))
        style.configure("Sub.TLabel", background=bg, foreground=subtext,
                        font=("Segoe UI", 9))
        style.configure("Panel.TLabel", background=panel, foreground=text,
                        font=("Segoe UI", 10))
        style.configure("PanelSub.TLabel", background=panel, foreground=subtext,
                        font=("Segoe UI", 9))

        style.configure("Accent.TButton",
                        background=accent, foreground="#ffffff",
                        font=("Segoe UI", 10, "bold"),
                        borderwidth=0, relief="flat", padding=(12, 6))
        style.map("Accent.TButton",
                  background=[("active", "#1d4ed8"), ("pressed", "#1e40af")])

        style.configure("Danger.TButton",
                        background=accent2, foreground="#ffffff",
                        font=("Segoe UI", 10, "bold"),
                        borderwidth=0, relief="flat", padding=(12, 6))
        style.map("Danger.TButton",
                  background=[("active", "#15803d"), ("pressed", "#166534")])

        style.configure("Ghost.TButton",
                        background=panel, foreground=subtext,
                        font=("Segoe UI", 9),
                        borderwidth=1, relief="solid", padding=(8, 4))
        style.map("Ghost.TButton",
                  background=[("active", "#f1f5f9")])

        style.configure("Treeview",
                        background=panel, foreground=text,
                        fieldbackground=panel,
                        rowheight=26,
                        font=("Segoe UI", 10),
                        borderwidth=0)
        style.configure("Treeview.Heading",
                        background="#e2e8f0", foreground=subtext,
                        font=("Segoe UI", 9, "bold"),
                        relief="flat")
        style.map("Treeview",
                  background=[("selected", sel)],
                  foreground=[("selected", text)])

        style.configure("TScrollbar",
                        background="#e2e8f0", troughcolor=bg,
                        arrowcolor=subtext, borderwidth=0)

        self._colors = {
            "bg": bg, "panel": panel, "accent": accent,
            "accent2": accent2, "text": text, "subtext": subtext, "sel": sel
        }

    # ── UI ──────────────────────────────────

    def _build_ui(self):
        c = self._colors
        root_frame = ttk.Frame(self, style="App.TFrame", padding=20)
        root_frame.pack(fill=tk.BOTH, expand=True)

        # Header
        hdr = ttk.Frame(root_frame, style="App.TFrame")
        hdr.pack(fill=tk.X, pady=(0, 16))

        ttk.Label(hdr, text="◈ BOOKMARK EXTRACTOR", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Label(hdr, text="  select · filter · export",
                  style="Sub.TLabel").pack(side=tk.LEFT, pady=(6, 0))

        # Toolbar
        toolbar = ttk.Frame(root_frame, style="App.TFrame")
        toolbar.pack(fill=tk.X, pady=(0, 12))

        ttk.Button(toolbar, text="⊕  Open Bookmarks File",
                   style="Accent.TButton",
                   command=self._open_file).pack(side=tk.LEFT, padx=(0, 8))

        self._file_label = ttk.Label(toolbar, text="No file loaded",
                                     style="Sub.TLabel")
        self._file_label.pack(side=tk.LEFT)

        ttk.Button(toolbar, text="⊞ Select All", style="Ghost.TButton",
                   command=self._select_all).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(toolbar, text="⊟ Deselect All", style="Ghost.TButton",
                   command=self._deselect_all).pack(side=tk.RIGHT, padx=(4, 0))

        # Search bar
        search_frame = ttk.Frame(root_frame, style="App.TFrame")
        search_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(search_frame, text="⌕  Search:", bg=c["bg"], fg=c["subtext"],
                 font=("Courier New", 10)).pack(side=tk.LEFT, padx=(0, 6))

        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search)
        search_entry = tk.Entry(search_frame, textvariable=self._search_var,
                                bg=c["panel"], fg=c["text"], insertbackground=c["text"],
                                font=("Courier New", 10), relief="flat",
                                highlightthickness=1, highlightbackground=c["sel"],
                                highlightcolor=c["accent"])
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)

        tk.Button(search_frame, text="✕", bg=c["panel"], fg=c["subtext"],
                  font=("Segoe UI", 9), relief="flat", bd=0,
                  command=lambda: self._search_var.set(""),
                  cursor="hand2").pack(side=tk.LEFT, padx=(4, 0))

        # Main pane: tree + info
        pane = tk.PanedWindow(root_frame, orient=tk.HORIZONTAL,
                              bg=c["bg"], sashwidth=6,
                              sashrelief="flat", sashpad=3)
        pane.pack(fill=tk.BOTH, expand=True)

        # Tree panel
        tree_outer = ttk.Frame(pane, style="Panel.TFrame", padding=2)
        pane.add(tree_outer, minsize=400, stretch="always")

        tree_header = ttk.Frame(tree_outer, style="Panel.TFrame")
        tree_header.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(tree_header, text="BOOKMARK TREE", style="PanelSub.TLabel").pack(side=tk.LEFT)
        self._count_label = ttk.Label(tree_header, text="", style="PanelSub.TLabel")
        self._count_label.pack(side=tk.RIGHT)

        tree_frame = ttk.Frame(tree_outer, style="Panel.TFrame")
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._tree = ttk.Treeview(tree_frame, columns=("check", "type"),
                                  show="tree headings", selectmode="extended")
        self._tree.heading("#0", text="Name")
        self._tree.heading("check", text="✓")
        self._tree.heading("type", text="Type")
        self._tree.column("#0", width=300, stretch=True)
        self._tree.column("check", width=30, stretch=False, anchor="center")
        self._tree.column("type", width=70, stretch=False, anchor="center")

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL,
                            command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL,
                            command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self._tree.bind("<Button-1>", self._on_tree_click)
        self._tree.bind("<<TreeviewSelect>>", self._on_selection_change)

        # Info panel
        info_outer = ttk.Frame(pane, style="Panel.TFrame", padding=8)
        pane.add(info_outer, minsize=200, stretch="never")

        ttk.Label(info_outer, text="SELECTION INFO", style="PanelSub.TLabel").pack(anchor="w")

        self._info_text = tk.Text(info_outer, bg=c["panel"], fg=c["text"],
                                  font=("Segoe UI", 9), relief="flat",
                                  wrap=tk.WORD, width=28, state=tk.DISABLED,
                                  highlightthickness=0)
        self._info_text.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        # Bottom bar
        bottom = ttk.Frame(root_frame, style="App.TFrame")
        bottom.pack(fill=tk.X, pady=(12, 0))

        self._status_var = tk.StringVar(value="Load a bookmarks HTML file to begin")
        ttk.Label(bottom, textvariable=self._status_var,
                  style="Sub.TLabel").pack(side=tk.LEFT)

        ttk.Button(bottom, text="⬇  Export Selected",
                   style="Danger.TButton",
                   command=self._export).pack(side=tk.RIGHT)

    # ── File Loading ─────────────────────────

    def _open_file(self):
        path = filedialog.askopenfilename(
            title="Select Exported Bookmark HTML File",
            filetypes=[("HTML files", "*.html *.htm"), ("All files", "*.*")]
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            messagebox.showerror("Error", f"Could not read file:\n{e}")
            return

        parser = BookmarkParser()
        parser.feed(content)
        self._parsed_root = parser.root

        self._file_label.config(text=os.path.basename(path))
        self._populate_tree(self._parsed_root)

    def _populate_tree(self, root, search_term=""):
        self._tree.delete(*self._tree.get_children())
        self._node_map.clear()
        self._check_vars.clear()
        self._children_map.clear()

        total = count_bookmarks(root.get("children", []))

        def insert(parent_iid, nodes):
            for node in nodes:
                name = node.get("name") or "(unnamed)"
                ntype = node["type"]

                if search_term:
                    # Only show nodes that match or contain matches
                    if not self._node_matches(node, search_term):
                        continue

                icon = "📁" if ntype == "folder" else "🔖"
                checked = self._check_vars.get(id(node), tk.BooleanVar(value=True))
                self._check_vars[id(node)] = checked

                iid = self._tree.insert(
                    parent_iid, "end",
                    text=f"  {icon}  {name}",
                    values=("☑" if checked.get() else "☐", ntype),
                    open=not bool(search_term)
                )
                self._node_map[iid] = node
                self._check_vars[iid] = checked

                if ntype == "folder":
                    child_iids = []
                    child_iids_ref = [child_iids]
                    insert(iid, node.get("children", []))
                    self._children_map[iid] = [
                        c for c in self._tree.get_children(iid)
                    ]

        insert("", root.get("children", []))

        visible = len(self._node_map)
        self._count_label.config(
            text=f"{visible} items  |  {total} bookmarks total"
        )
        self._status_var.set(f"Loaded: {total} bookmarks across all folders")
        self._update_info()

    def _node_matches(self, node, term):
        term = term.lower()
        name = (node.get("name") or "").lower()
        href = (node.get("href") or "").lower()
        if term in name or term in href:
            return True
        if node["type"] == "folder":
            for child in node.get("children", []):
                if self._node_matches(child, term):
                    return True
        return False

    # ── Interaction ──────────────────────────

    def _on_tree_click(self, event):
        region = self._tree.identify_region(event.x, event.y)
        col = self._tree.identify_column(event.x)
        iid = self._tree.identify_row(event.y)

        if iid and col == "#1":  # Check column clicked
            self._toggle_check(iid)
            return "break"

    def _toggle_check(self, iid, state=None):
        if iid not in self._check_vars:
            return
        var = self._check_vars[iid]
        new_state = state if state is not None else not var.get()
        var.set(new_state)
        vals = self._tree.item(iid, "values")
        self._tree.item(iid, values=("☑" if new_state else "☐", vals[1] if vals else ""))

        # Propagate to children
        for child_iid in self._tree.get_children(iid):
            self._toggle_check(child_iid, new_state)

        self._update_info()

    def _on_selection_change(self, event):
        self._update_info()

    def _select_all(self):
        for iid in self._node_map:
            self._toggle_check(iid, True)

    def _deselect_all(self):
        for iid in self._node_map:
            self._toggle_check(iid, False)

    def _on_search(self, *_):
        term = self._search_var.get().strip()
        if self._parsed_root:
            self._populate_tree(self._parsed_root, search_term=term)

    # ── Info Panel ───────────────────────────

    def _update_info(self):
        selected_nodes = self._collect_selected()
        bm_count = count_bookmarks(selected_nodes)
        folder_count = sum(1 for n in self._iter_all(selected_nodes) if n["type"] == "folder")

        self._info_text.config(state=tk.NORMAL)
        self._info_text.delete("1.0", tk.END)
        lines = [
            f"Selected items:\n",
            f"  Bookmarks : {bm_count}\n",
            f"  Folders   : {folder_count}\n",
            f"\n",
        ]
        sel = self._tree.selection()
        if sel:
            iid = sel[-1]
            node = self._node_map.get(iid)
            if node:
                lines += [
                    "Last selected:\n",
                    f"  {node.get('name', '')[:30]}\n",
                ]
                if node["type"] == "bookmark":
                    href = node.get("href", "")
                    lines.append(f"\n  {href[:40]}\n")
        self._info_text.insert("1.0", "".join(lines))
        self._info_text.config(state=tk.DISABLED)

    def _iter_all(self, nodes):
        for n in nodes:
            yield n
            if n["type"] == "folder":
                yield from self._iter_all(n.get("children", []))

    # ── Collection & Export ──────────────────

    def _collect_selected(self):
        """Collect top-level checked nodes from the tree (tree root level only)."""
        result = []
        top_iids = self._tree.get_children("")
        for iid in top_iids:
            node = self._collect_node(iid)
            if node:
                result.append(node)
        return result

    def _collect_node(self, iid):
        """Recursively collect a node if it or any of its children is checked."""
        var = self._check_vars.get(iid)
        node = self._node_map.get(iid)
        if not node:
            return None

        if node["type"] == "bookmark":
            if var and var.get():
                return dict(node)
            return None

        # Folder: collect checked children
        child_iids = self._tree.get_children(iid)
        children = []
        for ciid in child_iids:
            child_node = self._collect_node(ciid)
            if child_node:
                children.append(child_node)

        if var and var.get():
            # Include whole folder (use collected children subset)
            folder = dict(node)
            folder["children"] = children
            return folder
        elif children:
            # Partially selected folder — include as folder with selected children
            folder = dict(node)
            folder["children"] = children
            return folder

        return None

    def _export(self):
        if not self._parsed_root:
            messagebox.showwarning("No file", "Please load a bookmarks file first.")
            return

        selected = self._collect_selected()
        bm_count = count_bookmarks(selected)

        if bm_count == 0:
            messagebox.showwarning("Nothing selected",
                                   "No bookmarks are selected. Check items in the tree.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"bookmarks_export_{timestamp}.html"

        out_path = filedialog.asksaveasfilename(
            title="Save Exported Bookmarks",
            initialfile=default_name,
            defaultextension=".html",
            filetypes=[("HTML files", "*.html"), ("All files", "*.*")]
        )
        if not out_path:
            return

        try:
            export_to_html(selected, out_path)
            messagebox.showinfo(
                "Export Complete",
                f"Exported {bm_count} bookmarks!\n\nSaved to:\n{out_path}\n\n"
                "You can import this file into any browser."
            )
            self._status_var.set(f"Exported {bm_count} bookmarks → {os.path.basename(out_path)}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export:\n{e}")


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app = BookmarkExtractorApp()
    app.mainloop()

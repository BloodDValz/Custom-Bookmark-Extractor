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
from collections import defaultdict, deque
from html.parser import HTMLParser
from typing import List, Optional, TypedDict
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import os
from datetime import datetime


# ─────────────────────────────────────────────
#  DRAG-AND-DROP FILE HELPER  (ctypes / WM_DROPFILES — no install needed)
# ─────────────────────────────────────────────

import sys as _sys
import ctypes as _ctypes

if _sys.platform == "win32":
    import ctypes.wintypes as _wt

    _WM_DROPFILES   = 0x0233
    _GWL_WNDPROC    = -4
    _WndProcType    = _ctypes.WINFUNCTYPE(
        _ctypes.c_long, _wt.HWND, _wt.UINT, _wt.WPARAM, _wt.LPARAM)

    _user32  = _ctypes.windll.user32
    _shell32 = _ctypes.windll.shell32

    # Explicit argtypes/restype — without these, 64-bit HWNDs/pointers can be
    # silently truncated to 32-bit ints by ctypes' default int assumptions,
    # which causes the whole subclass/DragAcceptFiles chain to fail quietly.
    _user32.GetAncestor.argtypes  = [_wt.HWND, _ctypes.c_uint]
    _user32.GetAncestor.restype   = _wt.HWND
    _user32.SetWindowLongPtrW = getattr(_user32, "SetWindowLongPtrW", _user32.SetWindowLongW)
    _user32.SetWindowLongPtrW.argtypes = [_wt.HWND, _ctypes.c_int, _ctypes.c_void_p]
    _user32.SetWindowLongPtrW.restype  = _ctypes.c_void_p
    _user32.CallWindowProcW.argtypes = [_ctypes.c_void_p, _wt.HWND, _wt.UINT, _wt.WPARAM, _wt.LPARAM]
    _user32.CallWindowProcW.restype  = _ctypes.c_long
    _user32.ClientToScreen.argtypes = [_wt.HWND, _ctypes.POINTER(_wt.POINT)]
    _user32.ClientToScreen.restype  = _wt.BOOL
    _shell32.DragAcceptFiles.argtypes = [_wt.HWND, _wt.BOOL]
    _shell32.DragAcceptFiles.restype  = None
    _shell32.DragQueryPoint.argtypes  = [_wt.HANDLE, _ctypes.POINTER(_wt.POINT)]
    _shell32.DragQueryFileW.argtypes  = [_wt.HANDLE, _wt.UINT, _wt.LPWSTR, _wt.UINT]
    _shell32.DragFinish.argtypes      = [_wt.HANDLE]

    def _extract_drop_path(hdrop):
        """Return the first file path from a HDROP handle."""
        # MAX_PATH on Windows is 260 chars, but extended-length paths can reach
        # 32 767 chars.  Use 32 768 to handle both safely.
        _BUF = 32768
        buf = _ctypes.create_unicode_buffer(_BUF)
        _shell32.DragQueryFileW(hdrop, 0, buf, _BUF)
        _shell32.DragFinish(hdrop)
        return buf.value

    def _real_toplevel_hwnd(toplevel):
        """
        tkinter's winfo_id() can return an HWND for an inner/child window
        rather than the actual OS-level top-level frame. WM_DROPFILES is
        delivered to the true top-level window, so walk up via GetAncestor
        (GA_ROOT) to find it.
        """
        GA_ROOT = 2
        hwnd = toplevel.winfo_id()
        try:
            root_hwnd = _user32.GetAncestor(hwnd, GA_ROOT)
            if root_hwnd:
                return root_hwnd
        except Exception:
            pass
        return hwnd

    def _enable_window_drop(toplevel, hit_test_fn, debug=False):
        """
        Enable WM_DROPFILES on the toplevel window's real OS-level HWND.
        hit_test_fn(x, y) -> callback or None. Coordinates are screen coordinates
        (same space as winfo_rootx/rooty), matching what DragQueryPoint returns
        once converted from client to screen space.
        Call once, after the toplevel window exists.
        """
        hwnd = _real_toplevel_hwnd(toplevel)
        if debug:
            print(f"[dnd] winfo_id={toplevel.winfo_id()}  real_toplevel_hwnd={hwnd}")
        _shell32.DragAcceptFiles(hwnd, True)
        if debug:
            print(f"[dnd] DragAcceptFiles({hwnd}) called")

        _prev = [None]

        def _wndproc(hwnd_, msg, wp, lp):
            if debug and msg == _WM_DROPFILES:
                print(f"[dnd] WM_DROPFILES received! hwnd={hwnd_}")
            if msg == _WM_DROPFILES:
                hdrop = wp
                pt = _wt.POINT(0, 0)
                _shell32.DragQueryPoint(hdrop, _ctypes.byref(pt))
                # DragQueryPoint gives client coords — convert to screen coords
                _user32.ClientToScreen(hwnd_, _ctypes.byref(pt))
                path = _extract_drop_path(hdrop)
                if debug:
                    print(f"[dnd] dropped path={path!r}  screen_pt=({pt.x},{pt.y})")
                cb = hit_test_fn(pt.x, pt.y)
                if debug:
                    print(f"[dnd] hit_test callback found={cb is not None}")
                if cb and path:
                    cb(path)
                return 0
            return _user32.CallWindowProcW(_prev[0], hwnd_, msg, wp, lp)

        proc = _WndProcType(_wndproc)
        _prev[0] = _ctypes.cast(_user32.SetWindowLongPtrW(hwnd, _GWL_WNDPROC,
                                 _ctypes.cast(proc, _ctypes.c_void_p)), _ctypes.c_void_p)
        if debug:
            print(f"[dnd] subclass installed, prev_wndproc={_prev[0]}")
        # Keep references alive so Python doesn't GC the callback / ctypes objects
        toplevel._wndproc_ref  = proc
        toplevel._wndproc_prev = _prev

    def _widget_hit_test(widget_callbacks):
        """
        Build a hit_test_fn(x, y) from a list of (widget, callback) pairs.
        Coordinates are screen coordinates. Returns the callback for the first
        widget (in list order — put more specific/nested widgets first) whose
        bounding box contains the point, or None.
        """
        def _hit(x, y):
            for widget, cb in widget_callbacks:
                try:
                    if not widget.winfo_exists():
                        continue
                    wx = widget.winfo_rootx()
                    wy = widget.winfo_rooty()
                    ww = widget.winfo_width()
                    wh = widget.winfo_height()
                    if wx <= x <= wx + ww and wy <= y <= wy + wh:
                        return cb
                except Exception:
                    pass
            return None
        return _hit

else:
    def _enable_window_drop(*a, **kw):
        pass  # No-op on non-Windows
    def _widget_hit_test(*a, **kw):
        return lambda x, y: None


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
            # Always push a new folder node.  If no <H3> preceded this <DL>
            # (e.g. the root <DL> or a bare nested list), use "(unnamed)" so
            # that bookmarks inside are never silently lost.
            if len(self._stack) > 1 or self._pending_folder_name is not None:
                folder_name = self._pending_folder_name if self._pending_folder_name is not None else "(unnamed)"
                folder_name = folder_name or "(unnamed)"
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
        self.geometry("980x720")
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

        # ── File drag-and-drop (Windows native, no extra install) ─────────
        self.after(200, self._init_file_drop)

    def _init_file_drop(self):
        """
        Wire WM_DROPFILES once on the toplevel window. Hit-testing is done
        dynamically against whichever mode frame is currently visible, so a
        single registration covers Normal, Duplicates, and Compare (A/B/C).
        """
        def _hit_test(x, y):
            if self._current_mode == "normal":
                pairs = [(self._normal_frame, lambda p: self._normal_frame._open_file(p))]
            elif self._current_mode == "duplicates":
                pairs = [(self._duplicates_frame, lambda p: self._duplicates_frame._open_file(p))]
            else:  # compare — check the smaller A/B/C panels before the whole frame
                cf = self._compare_frame
                pairs = []
                if hasattr(cf, "_panel_a"):
                    pairs.append((cf._panel_a, lambda p: cf._load_file("A", p)))
                if hasattr(cf, "_panel_b"):
                    pairs.append((cf._panel_b, lambda p: cf._load_file("B", p)))
                if hasattr(cf, "_panel_c"):
                    pairs.append((cf._panel_c, lambda p: cf._load_file("C", p)))
            return _widget_hit_test(pairs)(x, y)

        _enable_window_drop(self, _hit_test, debug=False)

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
        self.bind_all("<Control-z>", lambda e: self._dispatch_shortcut("undo"))
        self.bind_all("<Control-Z>", lambda e: self._dispatch_shortcut("undo"))
        self.bind_all("<Control-y>", lambda e: self._dispatch_shortcut("redo"))
        self.bind_all("<Control-Y>", lambda e: self._dispatch_shortcut("redo"))
        self.bind_all("<Control-g>", lambda e: self._dispatch_shortcut("jump_to_folder"))
        self.bind_all("<Control-G>", lambda e: self._dispatch_shortcut("jump_to_folder"))

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

        # Undo / Redo stacks (unlimited depth)
        self._undo_stack: deque = deque()
        self._redo_stack: deque = deque()

        # folder iid → direct bookmark count (for statistics label)
        self._folder_bm_counts: dict = {}

        # Active filters dict — populated by the filter dialog
        # Keys: "type" ("bookmark"|"folder"|None), "date_after" (int|None),
        #       "date_before" (int|None), "folders" (list of node refs|None)
        self._active_filters: dict = {
            "type": None, "date_after": None,
            "date_before": None, "folders": None,
        }

        # Drag-to-reorder state
        self._drag_locked      = True
        self._drag_iid         = None
        self._drag_iids        = []     # all items being dragged (multi-select)
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
        self._expand_all_state = False
        self._expand_all_btn = ttk.Button(toolbar, text="⊞ Expand All", style="Ghost.TButton",
                   command=self._toggle_expand_all)
        self._expand_all_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self._expand_sub_state = False
        self._expand_sub_btn = ttk.Button(toolbar, text="⊞ Expand Subfolders", style="Ghost.TButton",
                   command=self._toggle_expand_subfolders)
        self._expand_sub_btn.pack(side=tk.RIGHT, padx=(4, 0))

        # ── Second toolbar row: Undo / Redo / Bulk Rename ───────────────────
        toolbar2 = ttk.Frame(self, style="App.TFrame")
        toolbar2.pack(fill=tk.X, pady=(0, 4))

        self._undo_btn = ttk.Button(toolbar2, text="↷ Undo", style="Ghost.TButton",
                   command=self._undo)
        self._undo_btn.pack(side=tk.LEFT, padx=(0, 4))
        self._undo_btn.config(state=tk.DISABLED)

        self._redo_btn = ttk.Button(toolbar2, text="↶ Redo", style="Ghost.TButton",
                   command=self._redo)
        self._redo_btn.pack(side=tk.LEFT, padx=(0, 4))
        self._redo_btn.config(state=tk.DISABLED)

        ttk.Button(toolbar2, text="✎ Bulk Rename", style="Ghost.TButton",
                   command=self._open_bulk_rename).pack(side=tk.LEFT, padx=(0, 4))

        ttk.Button(toolbar2, text="⌖ Jump to Folder", style="Ghost.TButton",
                   command=self._open_jump_to_folder).pack(side=tk.LEFT, padx=(0, 4))

        self._filter_btn = ttk.Button(toolbar2, text="⊿ Filter", style="Ghost.TButton",
                   command=self._open_filter_dialog)
        self._filter_btn.pack(side=tk.RIGHT, padx=(4, 0))

        self._remove_file_btn = ttk.Button(toolbar2, text="✕  Remove File", style="Ghost.TButton",
                   command=self._clear_loaded_file)
        self._remove_file_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self._remove_file_btn.config(state=tk.DISABLED)

        # ── Active-filter indicator bar (hidden until a filter is set) ───────
        self._filter_bar = tk.Frame(self, bg=c["bg"])
        # not packed yet — shown dynamically by _refresh_filter_bar
        self._filter_bar_inner = tk.Frame(self._filter_bar, bg=c["bg"])
        self._filter_bar_inner.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(self._filter_bar, text="✕ Clear All", bg=c["bg"], fg=c["danger"],
                  font=("Segoe UI", 8), relief="flat", bd=0, cursor="hand2",
                  command=self._clear_all_filters).pack(side=tk.RIGHT, padx=(0, 4))

        sf = ttk.Frame(self, style="App.TFrame")
        sf.pack(fill=tk.X, pady=(0, 8))
        self._search_bar_frame = sf
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

        # ── Breadcrumb bar (scrollable, clickable segments) ──────────────────
        bc_frame = tk.Frame(tree_outer, bg=c["sel"])
        bc_frame.pack(fill=tk.X, padx=4, pady=(0, 2))
        self._bc_canvas = tk.Canvas(bc_frame, bg=c["sel"], height=22,
                                    highlightthickness=0, bd=0)
        self._bc_canvas.pack(fill=tk.X, expand=True)
        self._bc_inner = tk.Frame(self._bc_canvas, bg=c["sel"])
        self._bc_canvas_win = self._bc_canvas.create_window(
            (0, 0), window=self._bc_inner, anchor="nw")
        self._bc_inner.bind("<Configure>",
            lambda e: self._bc_canvas.configure(
                scrollregion=self._bc_canvas.bbox("all")))
        self._bc_frame = bc_frame
        def _bc_scroll(event):
            self._bc_canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
        self._bc_canvas.bind("<MouseWheel>", _bc_scroll)
        self._bc_inner.bind("<MouseWheel>",  _bc_scroll)

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
        self._tree.bind("<<TreeviewSelect>>", lambda e: (self._update_info(), self._update_breadcrumb()))
        self._tree.bind("<space>", self._on_space_toggle)
        self._tree.bind("<Control-a>", self._on_ctrl_a)
        self._tree.bind("<Shift-Up>",   self._on_shift_up)
        self._tree.bind("<Shift-Down>", self._on_shift_down)
        self._tree.bind("<Up>",   self._on_plain_up)
        self._tree.bind("<Down>", self._on_plain_down)

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

    def _open_file(self, path=None):
        if not path:
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
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._populate_tree(self._parsed_root)
        self._reset_expand_btns()
        self._refresh_undo_btns()
        self._remove_file_btn.config(state=tk.NORMAL)

    def _clear_loaded_file(self):
        self._parsed_root = None
        self._file_label.config(text="No file loaded")
        self._tree.delete(*self._tree.get_children())
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._refresh_undo_btns()
        self._remove_file_btn.config(state=tk.DISABLED)
        self._status_var.set("Load a bookmarks HTML file to begin")

    # ── Tree population ───────────────────────

    def _populate_tree(self, root, search_term=""):
        self._tree.delete(*self._tree.get_children())
        self._node_map.clear()
        self._check_vars.clear()
        self._folder_bm_counts.clear()

        total = count_bookmarks(root.get("children", []))

        def insert(parent_iid, nodes):
            for node in nodes:
                if search_term and not self._node_matches(node, search_term):
                    continue
                if not self._node_passes_filter(node):
                    continue
                name  = node.get("name") or "(unnamed)"
                ntype = node["type"]
                if ntype == "folder":
                    bm_count = count_bookmarks(node.get("children", []))
                    icon_lbl = f"  📁  {name} ({bm_count})"
                else:
                    icon_lbl = f"  🔖  {name}"
                iid = self._tree.insert(parent_iid, "end",
                            text=icon_lbl,
                            values=("☑", ntype),
                            open=not bool(search_term))
                self._node_map[iid] = node
                self._check_vars[iid] = tk.BooleanVar(value=True)
                if ntype == "folder":
                    self._folder_bm_counts[iid] = bm_count
                    insert(iid, node.get("children", []))

        insert("", root.get("children", []))
        self._count_label.config(
            text=f"{len(self._node_map)} items  |  {total} bookmarks total")
        self._status_var.set(f"Loaded: {total} bookmarks")
        self._all_checked = True
        self._update_info()
        self._update_breadcrumb()

    def _node_matches(self, node, term):
        """Check if node (or any descendant) matches the already-lowercased term."""
        if term in (node.get("name") or "").lower() or term in (node.get("href") or "").lower():
            return True
        if node["type"] == "folder":
            return any(self._node_matches(c, term) for c in node.get("children", []))
        return False

    # ── Undo / Redo engine ───────────────────────────

    def _snapshot(self):
        """Capture a serialisable snapshot of the full tree state."""
        def snap_iid(iid):
            node = self._node_map.get(iid, {})
            var  = self._check_vars.get(iid)
            sibs = list(self._tree.get_children(self._tree.parent(iid)))
            return {
                "iid":      iid,
                "parent":   self._tree.parent(iid),
                "index":    sibs.index(iid) if iid in sibs else 0,
                "checked":  var.get() if var else True,
                "symbol":   (self._tree.item(iid, "values") or ["☑"])[0],
                "name":     node.get("name", ""),
                "href":     node.get("href", ""),
                "children": [snap_iid(c) for c in self._tree.get_children(iid)],
            }
        return [snap_iid(iid) for iid in self._tree.get_children("")]

    def _push_undo(self, snapshot=None):
        """Push current state onto undo stack (call BEFORE making a change)."""
        if snapshot is None:
            snapshot = self._snapshot()
        self._undo_stack.append(snapshot)
        self._redo_stack.clear()
        self._refresh_undo_btns()

    def _restore_snapshot(self, snapshot):
        """Restore tree to a previously captured snapshot."""
        def restore_children(parent_iid, items):
            for i, s in enumerate(items):
                iid = s["iid"]
                if iid not in self._node_map:
                    continue
                self._tree.move(iid, parent_iid, i)
                var = self._check_vars.get(iid)
                if var:
                    var.set(s["checked"])
                vals  = self._tree.item(iid, "values")
                ntype = vals[1] if len(vals) > 1 else self._node_map[iid].get("type", "")
                self._tree.item(iid, values=(s["symbol"], ntype))
                node = self._node_map.get(iid)
                if node:
                    node["name"] = s["name"]
                    node["href"] = s["href"]
                    if node["type"] == "folder":
                        cnt = self._folder_bm_counts.get(iid, count_bookmarks(node.get("children", [])))
                        self._tree.item(iid, text=f"  📁  {s['name']} ({cnt})")
                    else:
                        self._tree.item(iid, text=f"  🔖  {s['name']}")
                restore_children(iid, s["children"])
        restore_children("", snapshot)
        self._recalculate_folder_bm_counts()
        self._refresh_folder_indicators()
        self._update_info()

    def _undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        self._restore_snapshot(self._undo_stack.pop())
        self._sync_parsed_root_from_tree()
        self._refresh_undo_btns()

    def _redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        self._restore_snapshot(self._redo_stack.pop())
        self._sync_parsed_root_from_tree()
        self._refresh_undo_btns()

    def _refresh_undo_btns(self):
        self._undo_btn.config(state=tk.NORMAL if self._undo_stack else tk.DISABLED)
        self._redo_btn.config(state=tk.NORMAL if self._redo_stack else tk.DISABLED)

    def _sync_parsed_root_from_tree(self):
        """Rebuild _parsed_root["children"] to match the current tree order.

        Called after every drag-and-drop move and after undo/redo so that
        exports always reflect the rearranged layout rather than the original
        parse order.
        """
        if not self._parsed_root:
            return

        def build_children(parent_iid):
            children = []
            for iid in self._tree.get_children(parent_iid):
                node = self._node_map.get(iid)
                if node is None:
                    continue
                if node["type"] == "folder":
                    node = dict(node)
                    node["children"] = build_children(iid)
                children.append(node)
            return children

        self._parsed_root["children"] = build_children("")
        self._recalculate_folder_bm_counts()

    def _recalculate_folder_bm_counts(self):
        """Recount and relabel every folder in the tree.

        Called after drag-and-drop moves and undo/redo so the displayed counts
        never drift from reality.
        """
        def update(iid):
            for child_iid in self._tree.get_children(iid):
                update(child_iid)
            node = self._node_map.get(iid)
            if node and node["type"] == "folder":
                cnt = count_bookmarks(node.get("children", []))
                self._folder_bm_counts[iid] = cnt
                name = node.get("name") or "(unnamed)"
                self._tree.item(iid, text=f"  📁  {name} ({cnt})")

        for iid in self._tree.get_children(""):
            update(iid)

    # ── Expand / Collapse ─────────────────────

    def _tree_is_expanded(self):
        """Return True if any non-top-level folder is currently open."""
        def any_open(iid, depth):
            for child in self._tree.get_children(iid):
                if self._node_map.get(child, {}).get("type") == "folder":
                    if depth > 0 and self._tree.item(child, "open"):
                        return True
                    if any_open(child, depth + 1):
                        return True
            return False
        return any_open("", 0)

    def _tree_all_expanded(self):
        """Return True if every folder in the tree is open."""
        def all_open(iid):
            for child in self._tree.get_children(iid):
                if self._node_map.get(child, {}).get("type") == "folder":
                    if not self._tree.item(child, "open"):
                        return False
                    if not all_open(child):
                        return False
            return True
        return all_open("")

    def _reset_expand_btns(self):
        """Sync button labels to actual tree state (call after load or manual expand)."""
        self._expand_all_btn.config(text="⊞ Expand All")
        self._expand_sub_btn.config(text="⊞ Expand Subfolders")

    def _toggle_expand_all(self):
        # Read actual state so manual tree clicks never desync the button
        expanding = not self._tree_all_expanded()
        self._expand_all_btn.config(
            text="⊟ Collapse All" if expanding else "⊞ Expand All")
        def walk(iid):
            self._tree.item(iid, open=expanding)
            for child in self._tree.get_children(iid):
                walk(child)
        for iid in self._tree.get_children(""):
            walk(iid)

    def _toggle_expand_subfolders(self):
        # Read actual state so manual tree clicks never desync the button
        expanding = not self._tree_is_expanded()
        self._expand_sub_btn.config(
            text="⊟ Collapse Subfolders" if expanding else "⊞ Expand Subfolders")
        def walk(iid, depth):
            for child_iid in self._tree.get_children(iid):
                child_node = self._node_map.get(child_iid)
                if child_node and child_node["type"] == "folder":
                    if depth > 0:
                        self._tree.item(child_iid, open=expanding)
                    walk(child_iid, depth + 1)
        walk("", 0)

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

    def _show_insertion_line(self, event_y, target_iid, drop_mode, insert_parent=None, insert_idx=None):
        """Show a Chrome-style blue line between rows, or highlight a folder.

        insert_parent and insert_idx are pre-computed by _drop_info; if omitted
        they are re-derived here (fallback for direct calls).
        """
        tree = self._tree

        self._clear_drop_indicator()

        if drop_mode == "into":
            cur_tags = [t for t in tree.item(target_iid, "tags") if t != "drag_folder"]
            tree.item(target_iid, tags=cur_tags + ["drag_folder"])
            self._drag_prev_folder = target_iid
            return

        # Use pre-computed position if available, otherwise derive it
        if insert_parent is None or insert_idx is None:
            bbox = tree.bbox(target_iid)
            if not bbox:
                return
            item_mid = bbox[1] + bbox[3] // 2
            insert_after = event_y >= item_mid
            insert_parent = tree.parent(target_iid)
            sibs = list(tree.get_children(insert_parent))
            idx  = sibs.index(target_iid)
            insert_idx = idx + 1 if insert_after else idx

        # Insert a dummy item styled as a solid blue bar
        self._indicator_iid = tree.insert(
            insert_parent, insert_idx,
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
            self._reset_sel_anchor()
            return
        if not iid or iid not in self._node_map:
            return
        self._drag_iid         = iid
        self._drag_prev_target = None
        self._drag_prev_folder = None

        # Collect all currently-selected items that are real nodes.
        # If the clicked item isn't in the current selection, start fresh with just it.
        current_sel = [s for s in self._tree.selection() if s in self._node_map]
        if iid not in current_sel:
            current_sel = [iid]
            self._tree.selection_set(iid)

        # Build a flat in-order list using the tree's own traversal
        ordered = []
        def collect(p):
            for child in self._tree.get_children(p):
                if child in current_sel:
                    ordered.append(child)
                collect(child)
        collect("")
        self._drag_iids = ordered if ordered else [iid]

        # Build the ghost label
        if len(self._drag_iids) == 1:
            node  = self._node_map[iid]
            label = ("📁  " if node["type"] == "folder" else "🔖  ") + (node.get("name") or "(unnamed)")[:40]
        else:
            label = f"🔖  {len(self._drag_iids)} items selected"

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
        self._tree.selection_set(*self._drag_iids)

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
        # Skip the indicator item itself and any dragged item
        drag_set   = set(self._drag_iids)
        target_iid = self._tree.identify_row(event.y)
        if not target_iid or target_iid in drag_set or target_iid == self._indicator_iid:
            return

        insert_parent, insert_idx, drop_mode, highlight_iid = self._drop_info(event.y)
        if drop_mode is None:
            self._clear_drop_indicator()
            return

        self._show_insertion_line(event.y, highlight_iid, drop_mode, insert_parent, insert_idx)

    def _on_drag_release(self, event):
        if self._drag_locked or not self._drag_iid:
            return

        drag_iids      = list(self._drag_iids)   # ordered list of all items being moved
        indicator_iid  = self._indicator_iid      # capture before hide clears it
        self._drag_iid  = None
        self._drag_iids = []
        self._hide_drag_ui()

        def do_move(parent, idx):
            """Move all dragged items to (parent, idx) in original relative order."""
            self._push_undo()
            # Filter out items that are ancestors/descendants conflicts — keep it simple:
            # just skip any dragged item that IS the target parent.
            items_to_move = [i for i in drag_iids if i != parent]
            if not items_to_move:
                return
            # Insert items one by one; adjust idx as we go for same-parent items
            # that come before the insertion point.
            insert_at = idx
            for item in items_to_move:
                item_parent = self._tree.parent(item)
                if item_parent == parent:
                    sibs    = list(self._tree.get_children(parent))
                    item_idx = sibs.index(item) if item in sibs else -1
                    if 0 <= item_idx < insert_at:
                        insert_at -= 1
                self._tree.move(item, parent, insert_at)
                insert_at += 1
            self._tree.selection_set(*items_to_move)
            self._tree.see(items_to_move[0])
            self._sync_parsed_root_from_tree()

        # If we had an indicator item, use its position directly
        if indicator_iid:
            try:
                parent = self._tree.parent(indicator_iid)
                sibs   = list(self._tree.get_children(parent))
                idx    = sibs.index(indicator_iid)
                do_move(parent, idx)
                return
            except Exception:
                pass

        # Fallback: use hit-test
        target_iid = self._tree.identify_row(event.y)
        drag_set   = set(drag_iids)
        if not target_iid or target_iid in drag_set or target_iid not in self._node_map:
            self._tree.selection_set(*[i for i in drag_iids if i in self._node_map])
            return

        insert_parent, insert_idx, drop_mode, _ = self._drop_info(event.y)
        if drop_mode is None:
            self._tree.selection_set(*[i for i in drag_iids if i in self._node_map])
            return

        if drop_mode == "into":
            self._push_undo()
            items_to_move = [i for i in drag_iids if i != insert_parent]
            for item in items_to_move:
                self._tree.move(item, insert_parent, "end")
            self._tree.item(insert_parent, open=True)
            if items_to_move:
                self._tree.selection_set(*items_to_move)
                self._tree.see(items_to_move[0])
            self._sync_parsed_root_from_tree()
        else:
            do_move(insert_parent, insert_idx)

    # ── Bulk Rename ────────────────────────────────────────

    def _open_bulk_rename(self):
        if not self._parsed_root:
            messagebox.showwarning("No file", "Load a bookmarks file first.")
            return

        dlg = tk.Toplevel(self)
        dlg.title("Bulk Rename")
        dlg.geometry("680x520")
        dlg.minsize(500, 400)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        c = self._colors

        ctrl = tk.Frame(dlg, bg=c["bg"])
        ctrl.pack(fill=tk.X, padx=12, pady=(12, 6))

        tk.Label(ctrl, text="Field:", bg=c["bg"], fg=c["text"],
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", padx=(0,6))
        field_var = tk.StringVar(value="name")
        ff = tk.Frame(ctrl, bg=c["bg"])
        ff.grid(row=0, column=1, sticky="w")
        tk.Radiobutton(ff, text="Name", variable=field_var, value="name",
                       bg=c["bg"], fg=c["text"], selectcolor=c["sel"],
                       font=("Segoe UI", 9), activebackground=c["bg"]).pack(side=tk.LEFT)
        tk.Radiobutton(ff, text="URL", variable=field_var, value="href",
                       bg=c["bg"], fg=c["text"], selectcolor=c["sel"],
                       font=("Segoe UI", 9), activebackground=c["bg"]).pack(
                       side=tk.LEFT, padx=(10, 0))

        tk.Label(ctrl, text="Find:", bg=c["bg"], fg=c["text"],
                 font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=(6,0))
        find_var = tk.StringVar()
        tk.Entry(ctrl, textvariable=find_var, bg=c["panel"], fg=c["text"],
                 insertbackground=c["text"], font=("Segoe UI", 9), relief="flat",
                 highlightthickness=1, highlightbackground=c["sel"],
                 highlightcolor=c["accent"]).grid(row=1, column=1, sticky="ew", pady=(6,0))

        tk.Label(ctrl, text="Replace:", bg=c["bg"], fg=c["text"],
                 font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", pady=(4,0))
        replace_var = tk.StringVar()
        tk.Entry(ctrl, textvariable=replace_var, bg=c["panel"], fg=c["text"],
                 insertbackground=c["text"], font=("Segoe UI", 9), relief="flat",
                 highlightthickness=1, highlightbackground=c["sel"],
                 highlightcolor=c["accent"]).grid(row=2, column=1, sticky="ew", pady=(4,0))

        case_var = tk.BooleanVar(value=True)
        tk.Checkbutton(ctrl, text="Case-sensitive", variable=case_var,
                       bg=c["bg"], fg=c["text"], selectcolor=c["sel"],
                       font=("Segoe UI", 9), activebackground=c["bg"]).grid(
                       row=3, column=1, sticky="w", pady=(4,0))
        ctrl.columnconfigure(1, weight=1)

        # Preview label row with Select All / None toggles
        plbl_row = tk.Frame(dlg, bg=c["bg"])
        plbl_row.pack(fill=tk.X, padx=12, pady=(4, 0))
        tk.Label(plbl_row, text="Preview  (tick rows to include in rename):",
                 bg=c["bg"], fg=c["subtext"], font=("Segoe UI", 9)).pack(side=tk.LEFT)
        tk.Button(plbl_row, text="All", bg=c["bg"], fg=c["accent"],
                  font=("Segoe UI", 9), relief="flat", bd=0, cursor="hand2",
                  command=lambda: _toggle_all(True)).pack(side=tk.RIGHT)
        tk.Label(plbl_row, text="/", bg=c["bg"], fg=c["subtext"],
                 font=("Segoe UI", 9)).pack(side=tk.RIGHT)
        tk.Button(plbl_row, text="None", bg=c["bg"], fg=c["accent"],
                  font=("Segoe UI", 9), relief="flat", bd=0, cursor="hand2",
                  command=lambda: _toggle_all(False)).pack(side=tk.RIGHT)
        tk.Label(plbl_row, text="Select: ", bg=c["bg"], fg=c["subtext"],
                 font=("Segoe UI", 9)).pack(side=tk.RIGHT)

        pf = tk.Frame(dlg, bg=c["panel"])
        pf.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 4))
        pt = ttk.Treeview(pf, columns=("apply", "field", "before", "after"),
                          show="headings", selectmode="none")
        pt.heading("apply",  text="☑",      anchor="center",
                   command=lambda: _toggle_all(not all(i["var"].get() for i in _preview_vars.values())))
        pt.heading("field",  text="Field",  anchor="center")
        pt.heading("before", text="Before")
        pt.heading("after",  text="After")
        pt.column("apply",  width=34,  stretch=False, anchor="center")
        pt.column("field",  width=60,  stretch=False, anchor="center")
        pt.column("before", width=220, stretch=True)
        pt.column("after",  width=220, stretch=True)
        pt.tag_configure("checked",   foreground=c["accent"])
        pt.tag_configure("unchecked", foreground=c["subtext"])
        ptsb = ttk.Scrollbar(pf, orient=tk.VERTICAL, command=pt.yview)
        pt.configure(yscrollcommand=ptsb.set)
        pt.grid(row=0, column=0, sticky="nsew")
        ptsb.grid(row=0, column=1, sticky="ns")
        pf.rowconfigure(0, weight=1)
        pf.columnconfigure(0, weight=1)

        # Map preview-row iid → (tree_iid, BooleanVar)
        _preview_vars = {}   # pt_iid → {"tree_iid": ..., "var": BooleanVar}

        def _sync_header():
            if not _preview_vars:
                pt.heading("apply", text="☑")
                return
            states = [i["var"].get() for i in _preview_vars.values()]
            if all(states):
                pt.heading("apply", text="☑")
            elif any(states):
                pt.heading("apply", text="☒")
            else:
                pt.heading("apply", text="☐")

        def _set_row_display(pt_iid):
            info = _preview_vars.get(pt_iid)
            if not info:
                return
            checked = info["var"].get()
            vals    = pt.item(pt_iid, "values")
            pt.item(pt_iid,
                    values=("☑" if checked else "☐", vals[1], vals[2], vals[3]),
                    tags=("checked" if checked else "unchecked",))
            _sync_header()
            _refresh_match_lbl()

        def _on_pt_click(event):
            col = pt.identify_column(event.x)
            iid = pt.identify_row(event.y)
            if iid and col == "#1":
                info = _preview_vars.get(iid)
                if info:
                    info["var"].set(not info["var"].get())
                    _set_row_display(iid)

        pt.bind("<ButtonPress-1>", _on_pt_click)

        def _toggle_all(state):
            for pt_iid, info in _preview_vars.items():
                info["var"].set(state)
                vals = pt.item(pt_iid, "values")
                pt.item(pt_iid,
                        values=("☑" if state else "☐", vals[1], vals[2], vals[3]),
                        tags=("checked" if state else "unchecked",))
            _sync_header()
            _refresh_match_lbl()

        match_lbl = tk.Label(dlg, text="", bg=c["bg"], fg=c["subtext"],
                             font=("Segoe UI", 9))
        match_lbl.pack(anchor="w", padx=12)

        def _refresh_match_lbl():
            checked = sum(1 for i in _preview_vars.values() if i["var"].get())
            total   = len(_preview_vars)
            if total == 0:
                match_lbl.config(text="")
            else:
                match_lbl.config(
                    text=f"{total} match{'es' if total != 1 else ''}  —  "
                         f"{checked} selected for rename.")

        def _all_iids():
            result = []
            def walk(iid):
                result.append(iid)
                for ch in self._tree.get_children(iid):
                    walk(ch)
            for iid in self._tree.get_children(""):
                walk(iid)
            return result

        def _do_preview(*_):
            import re as _re
            find    = find_var.get()
            replace = replace_var.get()
            field   = field_var.get()
            case    = case_var.get()
            pt.delete(*pt.get_children())
            _preview_vars.clear()
            if not find:
                match_lbl.config(text="")
                return
            for tree_iid in _all_iids():
                node = self._node_map.get(tree_iid)
                if not node:
                    continue
                orig = node.get(field) or ""
                nv   = orig.replace(find, replace) if case else \
                       _re.sub(_re.escape(find), replace, orig, flags=_re.IGNORECASE)
                if nv != orig:
                    var    = tk.BooleanVar(value=True)
                    pt_iid = pt.insert("", "end",
                                       values=("☑", field, orig[:100], nv[:100]),
                                       tags=("checked",))
                    _preview_vars[pt_iid] = {"tree_iid": tree_iid, "var": var}
            _refresh_match_lbl()
            _sync_header()

        find_var.trace_add("write", _do_preview)
        replace_var.trace_add("write", _do_preview)
        field_var.trace_add("write", _do_preview)
        case_var.trace_add("write", _do_preview)

        def _apply():
            import re as _re
            find    = find_var.get()
            replace = replace_var.get()
            field   = field_var.get()
            case    = case_var.get()
            if not find:
                messagebox.showwarning("Empty search",
                                       "Enter a Find value.", parent=dlg)
                return
            selected = {info["tree_iid"] for info in _preview_vars.values()
                        if info["var"].get()}
            if not selected:
                messagebox.showwarning("Nothing selected",
                                       "Tick at least one row to rename.", parent=dlg)
                return
            self._push_undo()
            count = 0
            for tree_iid in selected:
                node = self._node_map.get(tree_iid)
                if not node:
                    continue
                orig = node.get(field) or ""
                nv   = orig.replace(find, replace) if case else \
                       _re.sub(_re.escape(find), replace, orig, flags=_re.IGNORECASE)
                if nv != orig:
                    node[field] = nv
                    if field == "name":
                        if node["type"] == "folder":
                            cnt = self._folder_bm_counts.get(tree_iid, count_bookmarks(node.get("children", [])))
                            self._tree.item(tree_iid, text=f"  📁  {nv} ({cnt})")
                        else:
                            self._tree.item(tree_iid, text=f"  🔖  {nv}")
                    count += 1
            dlg.destroy()
            self._status_var.set(
                f"Bulk rename: {count} item{'s' if count != 1 else ''} updated.")

        br = tk.Frame(dlg, bg=c["bg"])
        br.pack(fill=tk.X, padx=12, pady=(0, 12))
        tk.Button(br, text="Apply", bg=c["accent"], fg="#ffffff",
                  font=("Segoe UI", 9, "bold"), relief="flat", padx=12, pady=4,
                  cursor="hand2", command=_apply).pack(side=tk.RIGHT, padx=(6,0))
        tk.Button(br, text="Cancel", bg=c["sel"], fg=c["text"],
                  font=("Segoe UI", 9), relief="flat", padx=12, pady=4,
                  cursor="hand2", command=dlg.destroy).pack(side=tk.RIGHT)

        dlg.bind("<Return>", lambda e: _apply())
        dlg.bind("<Escape>", lambda e: dlg.destroy())

    # ── Filtering ─────────────────────────────

    def _node_passes_filter(self, node):
        """Return True if node should be visible given active filters."""
        f = self._active_filters
        ntype = node.get("type", "bookmark")

        # ── Type filter ───────────────────────────────────────────────────
        if f["type"]:
            if ntype == "folder":
                # Keep folder only if at least one descendant passes all filters
                return any(self._node_passes_filter(c) for c in node.get("children", []))
            elif ntype != f["type"]:
                return False

        # ── Folder-scope filter ───────────────────────────────────────────
        if f["folders"]:
            if ntype == "folder":
                # Keep folder structure if any child passes
                return any(self._node_passes_filter(c) for c in node.get("children", []))
            elif ntype == "bookmark":
                # Bookmark must be a descendant of one of the selected folders
                if not self._folder_nodes_selected(node, f["folders"]):
                    return False

        # ── Date filter (bookmarks only) ──────────────────────────────────
        if ntype == "bookmark":
            add_date = node.get("add_date")
            ts = int(add_date) if add_date and str(add_date).isdigit() else None
            if f["date_after"] is not None and (ts is None or ts < f["date_after"]):
                return False
            if f["date_before"] is not None and (ts is None or ts > f["date_before"]):
                return False

        return True

    def _folder_nodes_selected(self, node, selected_folder_nodes):
        """Return True if node is a descendant of any node in selected_folder_nodes."""
        return any(
            self._is_descendant(node, fn) for fn in selected_folder_nodes
        )

    def _is_descendant(self, node, ancestor):
        """Return True if node is anywhere inside ancestor's children tree."""
        for child in ancestor.get("children", []):
            if child is node:
                return True
            if child.get("type") == "folder" and self._is_descendant(node, child):
                return True
        return False

    def _has_active_filters(self):
        f = self._active_filters
        return any([f["type"], f["date_after"] is not None,
                    f["date_before"] is not None, f["folders"]])

    def _refresh_filter_bar(self):
        c = self._colors
        for w in self._filter_bar_inner.winfo_children():
            w.destroy()

        if not self._has_active_filters():
            self._filter_bar.pack_forget()
            self._filter_btn.config(style="Ghost.TButton")
            return

        # Show the bar
        self._filter_bar.pack(fill=tk.X, pady=(0, 4), before=self._search_bar_frame)
        self._filter_btn.config(style="Accent.TButton")

        f = self._active_filters
        chips = []
        if f["type"]:
            chips.append((f"Type: {f['type']}s only", "type"))
        if f["date_after"] is not None:
            chips.append((f"After: {datetime.fromtimestamp(f['date_after']).strftime('%Y-%m-%d')}", "date_after"))
        if f["date_before"] is not None:
            chips.append((f"Before: {datetime.fromtimestamp(f['date_before']).strftime('%Y-%m-%d')}", "date_before"))
        if f["folders"]:
            names = ", ".join((fn.get("name") or "(unnamed)")[:20] for fn in f["folders"][:3])
            if len(f["folders"]) > 3:
                names += f" +{len(f['folders'])-3}"
            chips.append((f"Folders: {names}", "folders"))

        tk.Label(self._filter_bar_inner, text="Filters:", bg=c["bg"],
                 fg=c["subtext"], font=("Segoe UI", 8), padx=4).pack(side=tk.LEFT)
        for label, key in chips:
            chip = tk.Frame(self._filter_bar_inner, bg=c["sel"], padx=2, pady=1)
            chip.pack(side=tk.LEFT, padx=(0, 4))
            tk.Label(chip, text=label, bg=c["sel"], fg=c["text"],
                     font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(4, 2))
            def _make_clear(k):
                def _clear():
                    self._active_filters[k] = None
                    self._refresh_filter_bar()
                    self._repopulate()
                return _clear
            tk.Button(chip, text="✕", bg=c["sel"], fg=c["subtext"],
                      font=("Segoe UI", 7), relief="flat", bd=0,
                      cursor="hand2", command=_make_clear(key)).pack(side=tk.LEFT)

    def _clear_all_filters(self):
        self._active_filters = {"type": None, "date_after": None,
                                "date_before": None, "folders": None}
        self._refresh_filter_bar()
        self._repopulate()

    def _repopulate(self):
        if self._parsed_root:
            self._populate_tree(self._parsed_root,
                                search_term=self._search_var.get().strip().lower())

    def _open_filter_dialog(self):
        if not self._parsed_root:
            messagebox.showwarning("No file", "Load a bookmarks file first.")
            return

        c = self._colors
        f = self._active_filters
        dlg = tk.Toplevel(self)
        dlg.title("Filter Bookmarks")
        dlg.geometry("600x520")
        dlg.minsize(480, 400)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()

        # ── Tab bar ────────────────────────────────────────────────────────
        tab_frame = tk.Frame(dlg, bg=c["bg"])
        tab_frame.pack(fill=tk.X, padx=12, pady=(12, 0))
        content_frame = tk.Frame(dlg, bg=c["bg"])
        content_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(6, 0))

        _tab_panels = {}
        _active_tab = tk.StringVar(value="type")

        def _switch_tab(name):
            _active_tab.set(name)
            for n, panel in _tab_panels.items():
                panel.pack_forget()
            _tab_panels[name].pack(fill=tk.BOTH, expand=True)
            for n, btn in _tab_btns.items():
                btn.config(bg=c["accent"] if n == name else c["sel"],
                           fg="#ffffff" if n == name else c["text"])

        _tab_btns = {}
        for tab_name, tab_label in [("type", "Type"), ("date", "Date"), ("folders", "Folders")]:
            btn = tk.Button(tab_frame, text=tab_label,
                            bg=c["sel"], fg=c["text"],
                            font=("Segoe UI", 9), relief="flat", bd=0,
                            padx=14, pady=5, cursor="hand2",
                            command=lambda n=tab_name: _switch_tab(n))
            btn.pack(side=tk.LEFT, padx=(0, 4))
            _tab_btns[tab_name] = btn

        # ── Type panel ────────────────────────────────────────────────────
        type_panel = tk.Frame(content_frame, bg=c["bg"])
        _tab_panels["type"] = type_panel

        tk.Label(type_panel, text="Show only:", bg=c["bg"], fg=c["text"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12, 6))
        type_var = tk.StringVar(value=f["type"] or "all")
        for val, lbl, desc in [
            ("all",      "All items",       "Show both folders and bookmarks (default)"),
            ("bookmark", "Bookmarks only",  "Hide all folders, show only bookmark entries"),
            ("folder",   "Folders only",    "Show only folder nodes"),
        ]:
            row = tk.Frame(type_panel, bg=c["bg"])
            row.pack(fill=tk.X, pady=2)
            tk.Radiobutton(row, text=lbl, variable=type_var, value=val,
                           bg=c["bg"], fg=c["text"], selectcolor=c["sel"],
                           font=("Segoe UI", 10), activebackground=c["bg"]).pack(side=tk.LEFT)
            tk.Label(row, text=f"  — {desc}", bg=c["bg"], fg=c["subtext"],
                     font=("Segoe UI", 9)).pack(side=tk.LEFT)

        # ── Date panel ────────────────────────────────────────────────────
        date_panel = tk.Frame(content_frame, bg=c["bg"])
        _tab_panels["date"] = date_panel

        tk.Label(date_panel, text="Filter by ADD_DATE (Unix timestamp or YYYY-MM-DD):",
                 bg=c["bg"], fg=c["text"], font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12, 6))

        def _ts_to_str(ts):
            if ts is None:
                return ""
            try:
                return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            except Exception:
                return str(ts)

        def _str_to_ts(s):
            s = s.strip()
            if not s:
                return None
            if s.isdigit():
                return int(s)
            try:
                # Parse as UTC midnight so date comparisons are timezone-neutral.
                import calendar
                t = datetime.strptime(s, "%Y-%m-%d")
                return calendar.timegm(t.timetuple())
            except Exception:
                return None

        after_var  = tk.StringVar(value=_ts_to_str(f["date_after"]))
        before_var = tk.StringVar(value=_ts_to_str(f["date_before"]))

        for label, var in [("Added after:",  after_var),
                           ("Added before:", before_var)]:
            row = tk.Frame(date_panel, bg=c["bg"])
            row.pack(fill=tk.X, pady=(0, 8))
            tk.Label(row, text=label, bg=c["bg"], fg=c["text"],
                     font=("Segoe UI", 9), width=14, anchor="w").pack(side=tk.LEFT)
            tk.Entry(row, textvariable=var, bg=c["panel"], fg=c["text"],
                     insertbackground=c["text"], font=("Segoe UI", 9), relief="flat",
                     highlightthickness=1, highlightbackground=c["sel"],
                     highlightcolor=c["accent"], width=20).pack(side=tk.LEFT, ipady=4)
            tk.Label(row, text="  e.g. 2023-06-15", bg=c["bg"], fg=c["subtext"],
                     font=("Segoe UI", 8)).pack(side=tk.LEFT)

        date_err = tk.Label(date_panel, text="", bg=c["bg"], fg=c["danger"],
                            font=("Segoe UI", 8))
        date_err.pack(anchor="w")

        # ── Folders panel ─────────────────────────────────────────────────
        folders_panel = tk.Frame(content_frame, bg=c["bg"])
        _tab_panels["folders"] = folders_panel

        tk.Label(folders_panel,
                 text="Show only bookmarks inside selected folders:",
                 bg=c["bg"], fg=c["text"], font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12, 4))

        ffilter_var = tk.StringVar()
        fe = tk.Entry(folders_panel, textvariable=ffilter_var, bg=c["panel"], fg=c["text"],
                      insertbackground=c["text"], font=("Segoe UI", 9), relief="flat",
                      highlightthickness=1, highlightbackground=c["sel"],
                      highlightcolor=c["accent"])
        fe.pack(fill=tk.X, pady=(0, 4), ipady=4)
        tk.Label(folders_panel, text="⌕  Type to filter list", bg=c["bg"], fg=c["subtext"],
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 4))

        # Build full folder list: [(name_path, node_ref)]
        all_folders = []
        def _collect_folders(nodes, path=""):
            for node in nodes:
                if node["type"] == "folder":
                    name = node.get("name") or "(unnamed)"
                    all_folders.append((path + name, node))
                    _collect_folders(node.get("children", []), path + name + " › ")
        _collect_folders(self._parsed_root.get("children", []))

        # Currently selected folder nodes
        _sel_nodes = set(id(n) for n in (f["folders"] or []))

        flf = tk.Frame(folders_panel, bg=c["panel"])
        flf.pack(fill=tk.BOTH, expand=True)
        flb = tk.Listbox(flf, bg=c["panel"], fg=c["text"],
                         font=("Segoe UI", 9), relief="flat",
                         selectbackground=c["sel"], selectforeground=c["text"],
                         activestyle="none", highlightthickness=0,
                         selectmode=tk.MULTIPLE)
        flsb = ttk.Scrollbar(flf, orient=tk.VERTICAL, command=flb.yview)
        flb.configure(yscrollcommand=flsb.set)
        flb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        flsb.pack(side=tk.RIGHT, fill=tk.Y)

        _displayed = []   # parallel list of node refs for current listbox

        def _refresh_folder_list(*_):
            term = ffilter_var.get().strip().lower()
            flb.delete(0, tk.END)
            _displayed.clear()
            for path, node in all_folders:
                if not term or term in path.lower():
                    cnt = count_bookmarks(node.get("children", []))
                    flb.insert(tk.END, f"  📁  {path}  ({cnt})")
                    _displayed.append(node)
            # Restore selections
            for i, node in enumerate(_displayed):
                if id(node) in _sel_nodes:
                    flb.selection_set(i)

        ffilter_var.trace_add("write", _refresh_folder_list)
        _refresh_folder_list()

        sel_lbl = tk.Label(folders_panel, text="", bg=c["bg"], fg=c["subtext"],
                           font=("Segoe UI", 8))
        sel_lbl.pack(anchor="w", pady=(2, 0))

        def _on_folder_select(_event=None):
            n = len(flb.curselection())
            sel_lbl.config(text=f"{n} folder{'s' if n != 1 else ''} selected")
        flb.bind("<<ListboxSelect>>", _on_folder_select)
        _on_folder_select()

        # ── Bottom buttons ────────────────────────────────────────────────
        bf = tk.Frame(dlg, bg=c["bg"])
        bf.pack(fill=tk.X, padx=12, pady=(6, 10))

        def _apply_filters():
            # Type
            tv = type_var.get()
            self._active_filters["type"] = None if tv == "all" else tv

            # Date
            da = _str_to_ts(after_var.get())
            db = _str_to_ts(before_var.get())
            if after_var.get().strip() and da is None:
                date_err.config(text="⚠  Invalid 'After' date — use YYYY-MM-DD or Unix timestamp")
                _switch_tab("date")
                return
            if before_var.get().strip() and db is None:
                date_err.config(text="⚠  Invalid 'Before' date — use YYYY-MM-DD or Unix timestamp")
                _switch_tab("date")
                return
            self._active_filters["date_after"]  = da
            self._active_filters["date_before"] = db

            # Folders
            sel_indices = flb.curselection()
            if sel_indices:
                self._active_filters["folders"] = [_displayed[i] for i in sel_indices]
            else:
                self._active_filters["folders"] = None

            dlg.destroy()
            self._refresh_filter_bar()
            self._repopulate()

        tk.Button(bf, text="Apply Filters", bg=c["accent"], fg="#ffffff",
                  font=("Segoe UI", 9, "bold"), relief="flat", padx=12, pady=4,
                  cursor="hand2", command=_apply_filters).pack(side=tk.RIGHT, padx=(6, 0))
        tk.Button(bf, text="Clear All", bg=c["sel"], fg=c["text"],
                  font=("Segoe UI", 9), relief="flat", padx=12, pady=4,
                  cursor="hand2", command=self._clear_all_filters).pack(side=tk.RIGHT, padx=(6, 0))
        tk.Button(bf, text="Cancel", bg=c["sel"], fg=c["text"],
                  font=("Segoe UI", 9), relief="flat", padx=12, pady=4,
                  cursor="hand2", command=dlg.destroy).pack(side=tk.RIGHT)

        dlg.bind("<Escape>", lambda e: dlg.destroy())
        _switch_tab("type")

    # ── Breadcrumb ────────────────────────────

    def _update_breadcrumb(self):
        c = self._colors
        # Clear existing segments
        for w in self._bc_inner.winfo_children():
            w.destroy()

        sel = self._tree.selection()
        if not sel or not self._parsed_root:
            tk.Label(self._bc_inner, text="—", bg=c["sel"], fg=c["subtext"],
                     font=("Segoe UI", 8), padx=6, pady=2).pack(side=tk.LEFT)
            return

        iid = sel[-1]
        # Build list of (name, iid) from root down to selected item
        pairs = []   # [(name, iid)]
        cur = iid
        while cur:
            node = self._node_map.get(cur)
            if node:
                pairs.append((node.get("name") or "(unnamed)", cur))
            cur = self._tree.parent(cur)
        pairs.reverse()

        # "Bookmarks" root label (not clickable — no iid)
        tk.Label(self._bc_inner, text="Bookmarks", bg=c["sel"], fg=c["subtext"],
                 font=("Segoe UI", 8), padx=6, pady=2).pack(side=tk.LEFT)

        for i, (name, seg_iid) in enumerate(pairs):
            # Separator
            tk.Label(self._bc_inner, text="›", bg=c["sel"], fg=c["subtext"],
                     font=("Segoe UI", 8), padx=2, pady=2).pack(side=tk.LEFT)

            is_last = (i == len(pairs) - 1)
            node = self._node_map.get(seg_iid, {})
            if node.get("type") == "folder":
                btn = tk.Label(self._bc_inner, text=name, bg=c["sel"],
                               fg=c["subtext"], font=("Segoe UI", 8, "underline"),
                               padx=2, pady=2, cursor="hand2")
                btn.pack(side=tk.LEFT)
                def _make_jump(target):
                    def _jump(_event=None):
                        parent = self._tree.parent(target)
                        while parent:
                            self._tree.item(parent, open=True)
                            parent = self._tree.parent(parent)
                        self._tree.item(target, open=True)
                        self._tree.selection_set(target)
                        self._tree.focus(target)
                        self._tree.see(target)
                        self._update_breadcrumb()
                    return _jump
                btn.bind("<Button-1>", _make_jump(seg_iid))
                btn.bind("<Enter>", lambda e, b=btn: b.config(fg=c["text"]))
                btn.bind("<Leave>", lambda e, b=btn: b.config(fg=c["subtext"]))
            else:
                tk.Label(self._bc_inner, text=name, bg=c["sel"],
                         fg=c["text"] if is_last else c["subtext"],
                         font=("Segoe UI", 8, "bold" if is_last else "normal"),
                         padx=2, pady=2).pack(side=tk.LEFT)

        # Auto-scroll to the right end so the deepest item is always visible
        self._bc_inner.update_idletasks()
        self._bc_canvas.configure(scrollregion=self._bc_canvas.bbox("all"))
        self._bc_canvas.xview_moveto(1.0)

    # ── Jump to Folder ────────────────────────

    def _open_jump_to_folder(self):
        if not self._parsed_root:
            messagebox.showwarning("No file", "Load a bookmarks file first.")
            return

        folders = []   # [(display_path, iid)]
        def walk(iid, path):
            node = self._node_map.get(iid)
            if not node:
                return
            if node["type"] == "folder":
                name = node.get("name") or "(unnamed)"
                folders.append((path + name, iid))
                for ch in self._tree.get_children(iid):
                    walk(ch, path + name + "  ›  ")
        for iid in self._tree.get_children(""):
            walk(iid, "")

        if not folders:
            messagebox.showinfo("No Folders", "No folders found in the tree.")
            return

        c = self._colors
        dlg = tk.Toplevel(self)
        dlg.title("Jump to Folder")
        dlg.geometry("540x380")
        dlg.minsize(400, 280)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()

        tk.Label(dlg, text="Type to filter folders:", bg=c["bg"], fg=c["subtext"],
                 font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(12, 2))

        filter_var = tk.StringVar()
        entry = tk.Entry(dlg, textvariable=filter_var, bg=c["panel"], fg=c["text"],
                         insertbackground=c["text"], font=("Segoe UI", 10), relief="flat",
                         highlightthickness=1, highlightbackground=c["sel"],
                         highlightcolor=c["accent"])
        entry.pack(fill=tk.X, padx=12, ipady=6)
        entry.focus_set()

        lf = tk.Frame(dlg, bg=c["panel"])
        lf.pack(fill=tk.BOTH, expand=True, padx=12, pady=(6, 4))
        lb = tk.Listbox(lf, bg=c["panel"], fg=c["text"], font=("Segoe UI", 9),
                        relief="flat", selectbackground=c["sel"], selectforeground=c["text"],
                        activestyle="none", highlightthickness=0, borderwidth=0)
        lsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=lb.yview)
        lb.configure(yscrollcommand=lsb.set)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        lsb.pack(side=tk.RIGHT, fill=tk.Y)

        _filtered = []

        def _refresh_list(*_):
            term = filter_var.get().strip().lower()
            lb.delete(0, tk.END)
            _filtered.clear()
            for path, iid in folders:
                if not term or term in path.lower():
                    cnt = self._folder_bm_counts.get(iid, "")
                    suffix = f" ({cnt})" if cnt != "" else ""
                    lb.insert(tk.END, f"  📁  {path}{suffix}")
                    _filtered.append(iid)
            if _filtered:
                lb.selection_set(0)

        filter_var.trace_add("write", _refresh_list)
        _refresh_list()

        def _jump(*_):
            sel_idx = lb.curselection()
            if not sel_idx or not _filtered:
                return
            target_iid = _filtered[sel_idx[0]]
            dlg.destroy()
            parent = self._tree.parent(target_iid)
            while parent:
                self._tree.item(parent, open=True)
                parent = self._tree.parent(parent)
            self._tree.selection_set(target_iid)
            self._tree.focus(target_iid)
            self._tree.see(target_iid)
            self._update_breadcrumb()

        def _on_key(event):
            if event.keysym == "Down":
                cur = lb.curselection()
                nxt = (cur[0] + 1) if cur and cur[0] < lb.size() - 1 else 0
                lb.selection_clear(0, tk.END)
                lb.selection_set(nxt)
                lb.see(nxt)
                return "break"
            if event.keysym == "Up":
                cur = lb.curselection()
                prv = (cur[0] - 1) if cur and cur[0] > 0 else lb.size() - 1
                lb.selection_clear(0, tk.END)
                lb.selection_set(prv)
                lb.see(prv)
                return "break"
            if event.keysym == "Return":
                _jump()
                return "break"
            if event.keysym == "Escape":
                dlg.destroy()
                return "break"

        entry.bind("<Key>", _on_key)
        lb.bind("<Double-Button-1>", _jump)
        lb.bind("<Return>", _jump)

        bf = tk.Frame(dlg, bg=c["bg"])
        bf.pack(fill=tk.X, padx=12, pady=(0, 10))
        tk.Button(bf, text="Jump", bg=c["accent"], fg="#ffffff",
                  font=("Segoe UI", 9, "bold"), relief="flat", padx=12, pady=4,
                  cursor="hand2", command=_jump).pack(side=tk.RIGHT, padx=(6, 0))
        tk.Button(bf, text="Cancel", bg=c["sel"], fg=c["text"],
                  font=("Segoe UI", 9), relief="flat", padx=12, pady=4,
                  cursor="hand2", command=dlg.destroy).pack(side=tk.RIGHT)

        # ── Keyboard shortcut targets ─────────────

    def _shortcut_jump_to_folder(self):
        self._open_jump_to_folder()

    def _shortcut_open(self):
        self._open_file()

    def _shortcut_export(self):
        self._export()

    def _shortcut_focus_filter(self):
        self._search_entry.focus_set()

    def _shortcut_undo(self):
        self._undo()

    def _shortcut_redo(self):
        self._redo()

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
        self._bc_frame.config(bg=c["sel"])
        self._bc_canvas.config(bg=c["sel"])
        self._bc_inner.config(bg=c["sel"])
        self._update_breadcrumb()
        # Lock button — keep its state-appropriate color
        if self._drag_locked:
            self._lock_btn.config(bg=c["sel"], fg=c["text"])
        else:
            self._lock_btn.config(bg=c["accent"], fg="#ffffff")

    def _visible_iids(self):
        """Return all currently visible (not inside collapsed folder) iids in tree order."""
        result = []
        def walk(iid):
            result.append(iid)
            if self._tree.item(iid, "open"):
                for ch in self._tree.get_children(iid):
                    walk(ch)
        for iid in self._tree.get_children(""):
            walk(iid)
        return result

    def _reset_sel_anchor(self):
        sel = self._tree.selection()
        self._sel_anchor = self._tree.focus() or (sel[0] if sel else None)

    def _on_plain_up(self, event):
        # Plain Up — let tkinter handle movement, just reset anchor after
        self.after_idle(self._reset_sel_anchor)

    def _on_plain_down(self, event):
        # Plain Down — let tkinter handle movement, just reset anchor after
        self.after_idle(self._reset_sel_anchor)

    def _on_shift_up(self, event):
        sel = list(self._tree.selection())
        if not sel:
            return "break"
        focus = self._tree.focus() or sel[0]
        # Set anchor on first shift keypress
        if not getattr(self, "_sel_anchor", None):
            self._reset_sel_anchor()
        all_iids = self._visible_iids()
        if focus not in all_iids:
            return "break"
        fi = all_iids.index(focus)
        if fi == 0:
            return "break"
        new_focus = all_iids[fi - 1]
        ai = all_iids.index(self._sel_anchor) if self._sel_anchor in all_iids else fi
        lo, hi = min(ai, fi - 1), max(ai, fi - 1)
        self._tree.selection_set(all_iids[lo:hi+1])
        self._tree.focus(new_focus)
        self._tree.see(new_focus)
        return "break"

    def _on_shift_down(self, event):
        sel = list(self._tree.selection())
        if not sel:
            return "break"
        focus = self._tree.focus() or sel[0]
        # Set anchor on first shift keypress
        if not getattr(self, "_sel_anchor", None):
            self._reset_sel_anchor()
        all_iids = self._visible_iids()
        if focus not in all_iids:
            return "break"
        fi = all_iids.index(focus)
        if fi >= len(all_iids) - 1:
            return "break"
        new_focus = all_iids[fi + 1]
        ai = all_iids.index(self._sel_anchor) if self._sel_anchor in all_iids else fi
        lo, hi = min(ai, fi + 1), max(ai, fi + 1)
        self._tree.selection_set(all_iids[lo:hi+1])
        self._tree.focus(new_focus)
        self._tree.see(new_focus)
        return "break"

    def _on_space_toggle(self, event):
        # Only toggle on plain Space — let Shift+Space and Ctrl+Space pass through
        if event.state & 0x1 or event.state & 0x4:   # Shift or Ctrl held
            return
        for iid in self._tree.selection():
            self._toggle_check(iid)
        return "break"

    def _on_ctrl_a(self, event):
        """Ctrl+A — select all visible tree items."""
        all_iids = list(self._node_map.keys())
        if all_iids:
            self._tree.selection_set(all_iids)
        return "break"

    def _heading_toggle_all(self):
        """Click on ✓ column header → toggle all items."""
        self._push_undo()
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
        self._push_undo()
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

    def _set_all_checked(self, state: bool):
        """Set every item in the tree to checked (True) or unchecked (False)."""
        self._push_undo()
        for iid in self._tree.get_children(""):
            self._set_check(iid, state, propagate=True)
        self._all_checked = state
        self._update_info()

    def _select_all(self):
        self._set_all_checked(True)

    def _deselect_all(self):
        self._set_all_checked(False)

    def _on_search(self, *_):
        if self._parsed_root:
            # Preserve undo/redo stacks — a search repopulates the tree with
            # new iids, which would invalidate old snapshots.  We save/restore
            # the stacks so they survive the rebuild (the snapshots contain
            # node data, not just iids, so they remain meaningful).
            saved_undo = list(self._undo_stack)
            saved_redo = list(self._redo_stack)
            self._populate_tree(self._parsed_root,
                                search_term=self._search_var.get().strip().lower())
            self._undo_stack.clear()
            self._undo_stack.extend(saved_undo)
            self._redo_stack.clear()
            self._redo_stack.extend(saved_redo)
            self._refresh_undo_btns()

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
        self._remove_file_btn = ttk.Button(bottom, text="✕  Remove File", style="Ghost.TButton",
                   command=self._clear_loaded_file)
        self._remove_file_btn.pack(side=tk.RIGHT, padx=(0, 16))
        self._remove_file_btn.config(state=tk.DISABLED)

    # ── File loading ──────────────────────────

    def _open_file(self, path=None):
        if not path:
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
        self._remove_file_btn.config(state=tk.NORMAL)

    def _clear_loaded_file(self):
        self._parsed_root = None
        self._groups = []
        self._file_label.config(text="No file loaded")
        self._tree.delete(*self._tree.get_children())
        self._check_vars.clear()
        self._node_map.clear()
        self._count_label.config(text="")
        self._status_var.set("Load a bookmarks HTML file to begin")
        self._remove_file_btn.config(state=tk.DISABLED)

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
        self._root_c            = None
        self._count_a           = 0
        self._count_b           = 0
        self._count_c           = 0
        self._result_bookmarks  = []
        self._check_vars        = {}
        self._node_map          = {}
        self._all_checked       = True
        self._diff_view_active  = False
        self._advanced_open     = False   # whether the advanced panel is visible
        self._three_way_active  = False   # True when File C is loaded and 3-way mode is on
        self._active_3way_mode  = "only_in_a"
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

        for which, attr_label, attr_clear in [("A", "_label_a", "_clear_a_btn"), ("B", "_label_b", "_clear_b_btn")]:
            panel = ttk.Frame(files_frame, style="Panel.TFrame", padding=10)
            panel.pack(side=tk.LEFT, fill=tk.X, expand=True,
                       padx=(0, 6) if which == "A" else (6, 0))
            ttk.Label(panel, text=f"FILE {which}", style="PanelSub.TLabel").pack(anchor="w")
            lbl = ttk.Label(panel, text="No file loaded", style="Panel.TLabel")
            lbl.pack(anchor="w", pady=(2, 6))
            setattr(self, attr_label, lbl)
            if which == "A": self._panel_a = panel
            else:            self._panel_b = panel
            btn_row_ab = ttk.Frame(panel, style="Panel.TFrame")
            btn_row_ab.pack(fill=tk.X)
            ttk.Button(btn_row_ab, text=f"⊕  Open File {which}", style="Accent.TButton",
                       command=lambda w=which: self._load_file(w)).pack(side=tk.LEFT, padx=(0, 8))
            clear_btn = ttk.Button(btn_row_ab, text=f"✕  Remove File {which}", style="Ghost.TButton",
                       command=lambda w=which: self._clear_file_ab(w))
            clear_btn.pack(side=tk.RIGHT)
            clear_btn.config(state=tk.DISABLED)
            setattr(self, attr_clear, clear_btn)
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

        # Advanced button — far right of mode bar
        self._advanced_btn = tk.Button(ctrl, text="Advanced ▾",
            bg=c["sel"], fg=c["text"],
            font=("Segoe UI", 10), relief="flat", bd=0, padx=12, pady=6,
            cursor="hand2", command=self._toggle_advanced)
        self._advanced_btn.pack(side=tk.RIGHT)

        # ── Advanced / 3-way panel (hidden by default) ────────────────────
        self._advanced_panel = ttk.Frame(self, style="Panel.TFrame", padding=10)
        # not packed yet

        adv_top = ttk.Frame(self._advanced_panel, style="Panel.TFrame")
        adv_top.pack(fill=tk.X)
        ttk.Label(adv_top, text="3-WAY COMPARE", style="PanelSub.TLabel").pack(side=tk.LEFT)
        ttk.Label(adv_top,
            text="Load a third file and find what's unique to each or common across all three.",
            style="PanelSub.TLabel").pack(side=tk.LEFT, padx=(10, 0))

        # File C loader
        file_c_panel = ttk.Frame(self._advanced_panel, style="Panel.TFrame")
        file_c_panel.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(file_c_panel, text="FILE C", style="PanelSub.TLabel").pack(anchor="w")
        self._label_c = ttk.Label(file_c_panel, text="No file loaded", style="Panel.TLabel")
        self._label_c.pack(anchor="w", pady=(2, 6))
        btn_row = ttk.Frame(file_c_panel, style="Panel.TFrame")
        btn_row.pack(anchor="w")
        ttk.Button(btn_row, text="⊕  Open File C", style="Accent.TButton",
                   command=lambda: self._load_file("C")).pack(side=tk.LEFT, padx=(0, 8))
        self._panel_c = file_c_panel  # used by hit-test in _init_file_drop
        self._clear_c_btn = ttk.Button(btn_row, text="✕  Remove File C", style="Ghost.TButton",
                   command=self._clear_file_c)
        self._clear_c_btn.pack(side=tk.LEFT)
        self._clear_c_btn.config(state=tk.DISABLED)

        # 3-way mode buttons
        mode3_row = ttk.Frame(self._advanced_panel, style="Panel.TFrame")
        mode3_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(mode3_row, text="Show:", style="App.TLabel").pack(side=tk.LEFT, padx=(0, 8))

        self._mode3_btns  = {}
        self._active_3way_mode = "3_only_a"

        for label, val in [
            ("Only in A",       "3_only_a"),
            ("Only in B",       "3_only_b"),
            ("Only in C",       "3_only_c"),
            ("In all three",    "3_in_all"),
            ("In A & B only",   "3_ab_only"),
            ("In A & C only",   "3_ac_only"),
            ("In B & C only",   "3_bc_only"),
            ("Unique (not in all)", "3_not_all"),
        ]:
            btn = tk.Button(mode3_row, text=label,
                            bg=c["sel"], fg=c["text"],
                            font=("Segoe UI", 9),
                            relief="flat", bd=0, padx=10, pady=5,
                            cursor="hand2",
                            command=lambda v=val: self._select_3way_mode(v))
            btn.pack(side=tk.LEFT, padx=(0, 3))
            self._mode3_btns[val] = btn

        # ── Results panel ────────────────────
        res_outer = ttk.Frame(self, style="Panel.TFrame", padding=4)
        res_outer.pack(fill=tk.BOTH, expand=True)
        self._res_outer_ref = res_outer

        rh = ttk.Frame(res_outer, style="Panel.TFrame")
        rh.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(rh, text="COMPARISON RESULTS", style="PanelSub.TLabel").pack(side=tk.LEFT)
        self._res_count = ttk.Label(rh, text="", style="PanelSub.TLabel")
        self._res_count.pack(side=tk.RIGHT, padx=(8, 0))

        # Toggle diff view button
        self._diff_toggle_btn = tk.Button(rh, text="⇔  Diff View",
            bg=c["sel"], fg=c["text"],
            font=("Segoe UI", 9), relief="flat", bd=0, padx=10, pady=3,
            cursor="hand2", command=self._toggle_diff_view)
        self._diff_toggle_btn.pack(side=tk.RIGHT, padx=(0, 4))

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

        # ── List view (default) ───────────────────────────────────────────
        self._list_view_frame = ttk.Frame(res_outer, style="Panel.TFrame")
        self._list_view_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        # columns: check | source | url
        rf = self._list_view_frame

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

        # Tag colours for A / B / C badges
        self._res_tree.tag_configure("src_a",  foreground="#1d4ed8", font=("Segoe UI", 10, "bold"))
        self._res_tree.tag_configure("src_b",  foreground="#15803d", font=("Segoe UI", 10, "bold"))
        self._res_tree.tag_configure("src_c",  foreground="#7c3aed", font=("Segoe UI", 10, "bold"))
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

        # ── Diff view (hidden until toggled) ─────────────────────────────
        self._diff_view_frame = ttk.Frame(res_outer, style="Panel.TFrame")
        # not packed yet; shown by _toggle_diff_view
        self._diff_view_frame.columnconfigure(0, weight=1)
        self._diff_view_frame.columnconfigure(1, weight=1)
        self._diff_view_frame.rowconfigure(1, weight=1)

        # Column headers
        self._diff_hdr_a = tk.Label(self._diff_view_frame,
            text="FILE A", bg="#fee2e2", fg="#991b1b",
            font=("Segoe UI", 9, "bold"), padx=8, pady=4, anchor="w")
        self._diff_hdr_a.grid(row=0, column=0, sticky="ew", padx=(0, 2), pady=(0, 2))

        self._diff_hdr_b = tk.Label(self._diff_view_frame,
            text="FILE B", bg="#dcfce7", fg="#166534",
            font=("Segoe UI", 9, "bold"), padx=8, pady=4, anchor="w")
        self._diff_hdr_b.grid(row=0, column=1, sticky="ew", padx=(2, 0), pady=(0, 2))

        # Left treeview — File A
        frame_a = ttk.Frame(self._diff_view_frame, style="Panel.TFrame")
        frame_a.grid(row=1, column=0, sticky="nsew", padx=(0, 2))
        frame_a.rowconfigure(0, weight=1)
        frame_a.columnconfigure(0, weight=1)

        self._diff_tree_a = ttk.Treeview(frame_a, columns=("check", "url"),
                                          show="tree headings", selectmode="extended")
        self._diff_tree_a.heading("#0",    text="Name (File A)")
        self._diff_tree_a.heading("check", text="✓",
                                   command=lambda: self._diff_toggle_all("A"))
        self._diff_tree_a.heading("url",   text="URL")
        self._diff_tree_a.column("#0",     width=200, stretch=True)
        self._diff_tree_a.column("check",  width=40,  stretch=False, anchor="center")
        self._diff_tree_a.column("url",    width=220, stretch=True)
        self._diff_tree_a.tag_configure("only_a", background="#fee2e2", foreground="#991b1b")
        self._diff_tree_a.tag_configure("shared", foreground="#64748b")

        vsb_a = ttk.Scrollbar(frame_a, orient=tk.VERTICAL, command=self._diff_tree_a.yview)
        self._diff_tree_a.configure(yscrollcommand=vsb_a.set)
        self._diff_tree_a.grid(row=0, column=0, sticky="nsew")
        vsb_a.grid(row=0, column=1, sticky="ns")
        self._diff_tree_a.bind("<Button-1>", lambda e: self._on_diff_click(e, "A"))

        # Right treeview — File B
        frame_b = ttk.Frame(self._diff_view_frame, style="Panel.TFrame")
        frame_b.grid(row=1, column=1, sticky="nsew", padx=(2, 0))
        frame_b.rowconfigure(0, weight=1)
        frame_b.columnconfigure(0, weight=1)

        self._diff_tree_b = ttk.Treeview(frame_b, columns=("check", "url"),
                                          show="tree headings", selectmode="extended")
        self._diff_tree_b.heading("#0",    text="Name (File B)")
        self._diff_tree_b.heading("check", text="✓",
                                   command=lambda: self._diff_toggle_all("B"))
        self._diff_tree_b.heading("url",   text="URL")
        self._diff_tree_b.column("#0",     width=200, stretch=True)
        self._diff_tree_b.column("check",  width=40,  stretch=False, anchor="center")
        self._diff_tree_b.column("url",    width=220, stretch=True)
        self._diff_tree_b.tag_configure("only_b", background="#dcfce7", foreground="#166534")
        self._diff_tree_b.tag_configure("shared", foreground="#64748b")

        vsb_b = ttk.Scrollbar(frame_b, orient=tk.VERTICAL, command=self._diff_tree_b.yview)
        self._diff_tree_b.configure(yscrollcommand=vsb_b.set)
        self._diff_tree_b.grid(row=0, column=0, sticky="nsew")
        vsb_b.grid(row=0, column=1, sticky="ns")
        self._diff_tree_b.bind("<Button-1>", lambda e: self._on_diff_click(e, "B"))

        # Per-side check state: iid → BooleanVar
        self._diff_check_a: dict = {}
        self._diff_check_b: dict = {}
        self._diff_node_a:  dict = {}   # iid → bookmark dict
        self._diff_node_b:  dict = {}
        self._diff_all_a = True
        self._diff_all_b = True

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

    def _load_file(self, which, path=None):
        if not path:
            path = filedialog.askopenfilename(
                title=f"Select Bookmark File {which}",
                filetypes=[("HTML files", "*.html *.htm"), ("All files", "*.*")])
        if not path:
            return
        lbl = self._label_a if which == "A" else self._label_b if which == "B" else self._label_c
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
        name  = os.path.basename(path)
        count = count_bookmarks(root.get("children", []))
        if which == "A":
            self._root_a  = root
            self._count_a = count
            self._label_a.config(text=f"✔  {name}")
            self._clear_a_btn.config(state=tk.NORMAL)
        elif which == "B":
            self._root_b  = root
            self._count_b = count
            self._label_b.config(text=f"✔  {name}")
            self._clear_b_btn.config(state=tk.NORMAL)
        else:  # C
            self._root_c  = root
            self._count_c = count
            self._label_c.config(text=f"✔  {name}")
            self._clear_c_btn.config(state=tk.NORMAL)
            # Auto-activate 3-way mode with the current 3-way mode selection
            self._three_way_active = True
            c = self._colors
            for v, btn in self._mode3_btns.items():
                if v == self._active_3way_mode:
                    btn.config(bg=c["accent2"], fg="#ffffff", font=("Segoe UI", 9, "bold"))
                else:
                    btn.config(bg=c["sel"], fg=c["text"], font=("Segoe UI", 9))
            for btn in self._mode_btns.values():
                btn.config(bg=c["sel"], fg=c["subtext"], font=("Segoe UI", 10))
        self._cmp_status.set(
            f"File {which} loaded ({count} bookmarks).")
        if self._root_a and self._root_b:
            self._run_compare()

    # ── Mode selection ────────────────────────

    def _select_mode(self, val):
        c = self._colors
        # Switch off 3-way mode
        self._three_way_active = False
        for v, btn in self._mode3_btns.items():
            btn.config(bg=c["sel"], fg=c["text"], font=("Segoe UI", 9))
        # Update 2-way button highlight
        for v, btn in self._mode_btns.items():
            if v == val:
                btn.config(bg=c["accent"], fg="#ffffff",
                           font=("Segoe UI", 10, "bold"))
            else:
                btn.config(bg=c["sel"], fg=c["text"],
                           font=("Segoe UI", 10))
        self._active_mode = val
        if self._root_a and self._root_b:
            self._run_compare()
        else:
            missing = []
            if not self._root_a: missing.append("A")
            if not self._root_b: missing.append("B")
            self._cmp_status.set(
                f"Mode set. Load file{'s' if len(missing)>1 else ''} "
                f"{' and '.join(missing)} to compare.")

    # ── Diff view toggle ──────────────────────

    def _toggle_diff_view(self):
        c = self._colors
        self._diff_view_active = not self._diff_view_active
        if self._diff_view_active:
            self._list_view_frame.pack_forget()
            self._diff_view_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
            self._diff_toggle_btn.config(text="☰  List View",
                                         bg=c["accent"], fg="#ffffff")
            if self._root_a and self._root_b:
                self._populate_diff_view()
        else:
            self._diff_view_frame.pack_forget()
            self._list_view_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
            self._diff_toggle_btn.config(text="⇔  Diff View",
                                         bg=c["sel"], fg=c["text"])

    def _populate_diff_view(self, filter_term=""):
        """Populate the two side-by-side diff Treeviews, mirroring the active compare mode."""
        ft    = filter_term.lower()
        mode  = self._active_mode
        bm_a  = collect_all_bookmarks(self._root_a) if self._root_a else []
        bm_b  = collect_all_bookmarks(self._root_b) if self._root_b else []
        set_a = {normalise_url(b["href"]) for b in bm_a}
        set_b = {normalise_url(b["href"]) for b in bm_b}

        def matches(bm):
            return (not ft or ft in (bm.get("name") or "").lower()
                    or ft in (bm.get("href") or "").lower())

        # Mirror exactly what _run_compare puts in each source column
        if mode == "only_in_a":
            items_a = [b for b in bm_a if normalise_url(b["href"]) not in set_b]
            items_b = []
            tag_a, tag_b = "only_a", "only_b"
        elif mode == "only_in_b":
            items_a = []
            items_b = [b for b in bm_b if normalise_url(b["href"]) not in set_a]
            tag_a, tag_b = "only_a", "only_b"
        elif mode == "in_both":
            items_a = [b for b in bm_a if normalise_url(b["href"]) in set_b]
            items_b = [b for b in bm_b if normalise_url(b["href"]) in set_a]
            tag_a, tag_b = "shared", "shared"
        else:  # not_in_both
            items_a = [b for b in bm_a if normalise_url(b["href"]) not in set_b]
            items_b = [b for b in bm_b if normalise_url(b["href"]) not in set_a]
            tag_a, tag_b = "only_a", "only_b"

        def fill(tree, check_map, node_map, items, tag):
            tree.delete(*tree.get_children())
            check_map.clear()
            node_map.clear()
            for bm in items:
                if not matches(bm):
                    continue
                var = tk.BooleanVar(value=True)
                iid = tree.insert("", "end",
                          text=f"  🔖  {bm.get('name') or '(unnamed)'}",
                          values=("☑", bm.get("href") or ""),
                          tags=(tag,))
                check_map[iid] = var
                node_map[iid]  = bm

        fill(self._diff_tree_a, self._diff_check_a, self._diff_node_a, items_a, tag_a)
        fill(self._diff_tree_b, self._diff_check_b, self._diff_node_b, items_b, tag_b)

        self._diff_all_a = True
        self._diff_all_b = True

        ca = len([b for b in items_a if matches(b)])
        cb = len([b for b in items_b if matches(b)])
        mode_hdr = {
            "only_in_a":   ("Only in A",  "—"),
            "only_in_b":   ("—",          "Only in B"),
            "in_both":     ("In both",    "In both"),
            "not_in_both": ("Only in A",  "Only in B"),
        }
        la, lb = mode_hdr.get(mode, ("FILE A", "FILE B"))
        self._diff_hdr_a.config(text=f"FILE A  —  {la}  ({ca} items)")
        self._diff_hdr_b.config(text=f"FILE B  —  {lb}  ({cb} items)")

    def _on_diff_click(self, event, side):
        tree      = self._diff_tree_a if side == "A" else self._diff_tree_b
        col = tree.identify_column(event.x)
        iid = tree.identify_row(event.y)
        if iid and col == "#1":   # check column
            self._diff_toggle_item(iid, side)
            return "break"

    def _diff_toggle_item(self, iid, side, state=None):
        check_map = self._diff_check_a if side == "A" else self._diff_check_b
        tree      = self._diff_tree_a  if side == "A" else self._diff_tree_b
        if iid not in check_map:
            return
        var       = check_map[iid]
        new_state = state if state is not None else not var.get()
        var.set(new_state)
        vals = tree.item(iid, "values")
        tree.item(iid, values=("☑" if new_state else "☐",
                               vals[1] if len(vals) > 1 else ""))

    def _diff_toggle_all(self, side):
        if side == "A":
            self._diff_all_a = not self._diff_all_a
            new_state = self._diff_all_a
            check_map = self._diff_check_a
        else:
            self._diff_all_b = not self._diff_all_b
            new_state = self._diff_all_b
            check_map = self._diff_check_b
        for iid in check_map:
            self._diff_toggle_item(iid, side, new_state)

    # ── Advanced panel toggle ─────────────────

    def _toggle_advanced(self):
        c = self._colors
        self._advanced_open = not self._advanced_open
        if self._advanced_open:
            self._advanced_panel.pack(fill=tk.X, pady=(0, 6),
                                      before=self._res_outer_ref)
            self._advanced_btn.config(text="Advanced ▴", bg=c["accent"], fg="#ffffff")
        else:
            self._advanced_panel.pack_forget()
            self._advanced_btn.config(text="Advanced ▾", bg=c["sel"], fg=c["text"])

    def _clear_results(self, status_msg):
        """Wipe the results tree, the side-by-side diff view, and related state."""
        self._res_tree.delete(*self._res_tree.get_children())
        self._check_vars.clear()
        self._node_map.clear()
        self._res_count.config(text="0 bookmarks")

        self._diff_tree_a.delete(*self._diff_tree_a.get_children())
        self._diff_tree_b.delete(*self._diff_tree_b.get_children())
        self._diff_check_a.clear()
        self._diff_check_b.clear()
        self._diff_node_a.clear()
        self._diff_node_b.clear()

        self._cmp_status.set(status_msg)

    def _clear_file_ab(self, which):
        if which == "A":
            self._root_a  = None
            self._count_a = 0
            self._label_a.config(text="No file loaded")
            self._clear_a_btn.config(state=tk.DISABLED)
        else:
            self._root_b  = None
            self._count_b = 0
            self._label_b.config(text="No file loaded")
            self._clear_b_btn.config(state=tk.DISABLED)
        self._cmp_status.set(f"File {which} removed.")
        if self._root_a and self._root_b:
            self._run_compare()
        else:
            self._clear_results(f"File {which} removed. Load both files and click Compare.")

    def _clear_file_c(self):
        self._root_c  = None
        self._count_c = 0
        self._label_c.config(text="No file loaded")
        self._clear_c_btn.config(state=tk.DISABLED)
        self._three_way_active = False
        # Deactivate all 3-way mode buttons
        c = self._colors
        for btn in self._mode3_btns.values():
            btn.config(bg=c["sel"], fg=c["subtext"])
        self._cmp_status.set("File C removed. Using 2-way comparison.")
        if self._root_a and self._root_b:
            self._run_compare()
        else:
            self._clear_results("File C removed. Load both files and click Compare.")

    # ── 3-way mode selection ──────────────────

    def _select_3way_mode(self, val):
        if not self._root_c:
            messagebox.showwarning("No File C", "Load File C first to use 3-way compare.")
            return
        c = self._colors
        for v, btn in self._mode3_btns.items():
            if v == val:
                btn.config(bg=c["accent2"], fg="#ffffff", font=("Segoe UI", 9, "bold"))
            else:
                btn.config(bg=c["sel"], fg=c["text"], font=("Segoe UI", 9))
        # Deactivate 2-way mode buttons visually
        for btn in self._mode_btns.values():
            btn.config(bg=c["sel"], fg=c["subtext"], font=("Segoe UI", 10))
        self._active_3way_mode = val
        self._three_way_active = True
        self._run_compare()

    # ── Comparison ───────────────────────────

    def _run_compare(self):
        if self._three_way_active and self._root_c:
            self._run_3way_compare()
            return
        if not self._root_a or not self._root_b:
            messagebox.showwarning("Missing Files",
                                   "Please load both File A and File B first.")
            return
        self._run_2way_compare()

    def _run_2way_compare(self):
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

    def _run_3way_compare(self):
        bm_a = collect_all_bookmarks(self._root_a)
        bm_b = collect_all_bookmarks(self._root_b)
        bm_c = collect_all_bookmarks(self._root_c)
        set_a = {normalise_url(b["href"]) for b in bm_a}
        set_b = {normalise_url(b["href"]) for b in bm_b}
        set_c = {normalise_url(b["href"]) for b in bm_c}

        mode = self._active_3way_mode
        if mode == "3_only_a":
            result = [dict(b, _source="A") for b in bm_a
                      if normalise_url(b["href"]) not in set_b
                      and normalise_url(b["href"]) not in set_c]
        elif mode == "3_only_b":
            result = [dict(b, _source="B") for b in bm_b
                      if normalise_url(b["href"]) not in set_a
                      and normalise_url(b["href"]) not in set_c]
        elif mode == "3_only_c":
            result = [dict(b, _source="C") for b in bm_c
                      if normalise_url(b["href"]) not in set_a
                      and normalise_url(b["href"]) not in set_b]
        elif mode == "3_in_all":
            result = [dict(b, _source="A+B+C") for b in bm_a
                      if normalise_url(b["href"]) in set_b
                      and normalise_url(b["href"]) in set_c]
        elif mode == "3_ab_only":
            result = [dict(b, _source="A+B") for b in bm_a
                      if normalise_url(b["href"]) in set_b
                      and normalise_url(b["href"]) not in set_c]
        elif mode == "3_ac_only":
            result = [dict(b, _source="A+C") for b in bm_a
                      if normalise_url(b["href"]) in set_c
                      and normalise_url(b["href"]) not in set_b]
        elif mode == "3_bc_only":
            result = [dict(b, _source="B+C") for b in bm_b
                      if normalise_url(b["href"]) in set_c
                      and normalise_url(b["href"]) not in set_a]
        else:  # 3_not_all — not present in ALL three files simultaneously
            # A bookmark qualifies only when it is absent from at least one of
            # the other two files (AND, not OR, avoids the duplicate-entry bug).
            only_a = [dict(b, _source="A") for b in bm_a
                      if not (normalise_url(b["href"]) in set_b
                              and normalise_url(b["href"]) in set_c)]
            only_b = [dict(b, _source="B") for b in bm_b
                      if not (normalise_url(b["href"]) in set_a
                              and normalise_url(b["href"]) in set_c)]
            only_c = [dict(b, _source="C") for b in bm_c
                      if not (normalise_url(b["href"]) in set_a
                              and normalise_url(b["href"]) in set_b)]
            result = only_a + only_b + only_c

        self._result_bookmarks = result
        self._populate_results(result, mode_label_override=
            {"3_only_a":  "unique to File A (not in B or C)",
             "3_only_b":  "unique to File B (not in A or C)",
             "3_only_c":  "unique to File C (not in A or B)",
             "3_in_all":  "present in all three files",
             "3_ab_only": "in A & B only (not in C)",
             "3_ac_only": "in A & C only (not in B)",
             "3_bc_only": "in B & C only (not in A)",
             "3_not_all": "not shared across all three files",
            }.get(mode, ""))

    # ── Results tree ─────────────────────────

    def _populate_results(self, bookmarks, filter_term="", mode_label_override=None):
        self._res_tree.delete(*self._res_tree.get_children())
        self._check_vars.clear()
        self._node_map.clear()

        ft = filter_term.lower()
        for bm in bookmarks:
            name   = bm.get("name") or "(unnamed)"
            href   = bm.get("href") or ""
            source = bm.get("_source", "")
            if ft and ft not in name.lower() and ft not in href.lower():
                continue
            var = tk.BooleanVar(value=True)
            badge   = f"[{source}]" if source else ""
            src_tag = {"A": "src_a", "B": "src_b", "A+B": "src_ab",
                       "C": "src_c", "A+C": "src_ab", "B+C": "src_ab",
                       "A+B+C": "src_ab"}.get(source, "")
            iid = self._res_tree.insert("", "end",
                      text=f"  🔖  {name}",
                      values=("☑", badge, href),
                      tags=(src_tag,) if src_tag else ())
            self._check_vars[iid] = var
            self._node_map[iid]   = bm

        count = len(self._node_map)
        self._res_count.config(text=f"{count} bookmarks")

        if mode_label_override is not None:
            label = mode_label_override
        else:
            label = {
                "only_in_a":   "unique to File A",
                "only_in_b":   "unique to File B",
                "in_both":     "present in both files",
                "not_in_both": "unique across both files (non-matching)",
            }.get(self._active_mode, "")

        totals = f"A: {self._count_a}"
        if self._count_b: totals += f"  |  B: {self._count_b}"
        if self._count_c: totals += f"  |  C: {self._count_c}"
        self._cmp_status.set(f"Found {count} bookmarks {label}  ({totals})")
        self._all_checked = True
        # If diff view is currently visible, rebuild it with the same filter
        if self._diff_view_active:
            self._populate_diff_view(filter_term=filter_term)

    def _on_res_search(self, *_):
        ft = self._res_search_var.get().strip()
        if self._result_bookmarks:
            self._populate_results(self._result_bookmarks, filter_term=ft)
        elif self._diff_view_active and self._root_a and self._root_b:
            self._populate_diff_view(filter_term=ft)

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
        if self._diff_view_active:
            for iid in self._diff_check_a:
                self._diff_toggle_item(iid, "A", True)
            for iid in self._diff_check_b:
                self._diff_toggle_item(iid, "B", True)
            self._diff_all_a = True
            self._diff_all_b = True
        else:
            for iid in self._check_vars:
                self._toggle_result(iid, True)
            self._all_checked = True

    def _deselect_all_results(self):
        if self._diff_view_active:
            for iid in self._diff_check_a:
                self._diff_toggle_item(iid, "A", False)
            for iid in self._diff_check_b:
                self._diff_toggle_item(iid, "B", False)
            self._diff_all_a = False
            self._diff_all_b = False
        else:
            for iid in self._check_vars:
                self._toggle_result(iid, False)
            self._all_checked = False

    # ── Export ────────────────────────────────

    def _export_results(self):
        # When Diff View is active, collect from the two side-by-side panels
        # instead of the (empty) _check_vars dict that belongs to the list view.
        if self._diff_view_active:
            checked = (
                [self._diff_node_a[iid]
                 for iid, var in self._diff_check_a.items() if var.get()]
                + [self._diff_node_b[iid]
                   for iid, var in self._diff_check_b.items() if var.get()]
            )
        else:
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
        # Diff toggle button
        if self._diff_view_active:
            self._diff_toggle_btn.config(bg=c["accent"], fg="#ffffff")
        else:
            self._diff_toggle_btn.config(bg=c["sel"], fg=c["text"])


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app = BookmarkExtractorApp()
    app.mainloop()

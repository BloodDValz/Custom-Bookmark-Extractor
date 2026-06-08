# Custom-Bookmark-Extractor
A Python GUI tool for extracting, filtering, deduplicating, and comparing browser bookmarks from exported HTML files.
Built with Tkinter, this tool helps you organize bookmarks, clean exports, find duplicates, and compare bookmark collections between two files.

---

## 🚀 Features

### ◈ Normal Mode
- Load an exported browser bookmark HTML file
- Browse bookmarks in a full tree structure (folders + links)
- Search bookmarks by name or URL (live filtering)
- Select / deselect individual bookmarks and folders
  - Folders show a partial-check indicator (☒) when only some children are selected
  - Clicking a folder propagates the check state to all its children
- Select All / Deselect All with one click (or via the column heading)
- **Drag-to-reorder** bookmarks and folders within the tree
  - Toggle a lock/unlock button to enable or disable reordering
- Side panel shows selection info: count of selected bookmarks and folders, plus the URL of the last selected item
- Export selected bookmarks (preserving folder structure) to a clean Netscape HTML file

### ⊕ Duplicates Mode
- Load a single bookmark file and automatically detect all URLs that appear more than once
- Duplicates are grouped by normalised URL (case-insensitive, trailing slash stripped, tracking parameters removed)
- Each group shows how many copies exist and which folder each copy lives in
- Toolbar quick-actions:
  - **Keep First** — keep only the first copy in each group
  - **Keep Second** — keep only the second copy in each group
  - **Keep All** / **Discard All** — bulk select/deselect across all groups
  - **Expand All** / **Collapse All** — expand or collapse all duplicate groups
- Filter groups by name or URL
- Two export options:
  - **Export Kept Bookmarks** — full deduplicated file (all non-duplicate bookmarks + the copies you chose to keep)
  - **Export Duplicates Only** — just the kept copies from duplicate groups

### ⇌ Compare Mode
- Load two separate bookmark HTML files (File A and File B)
- Compare by URL only (case-insensitive, trailing slash ignored) — bookmark titles are not used for matching
- Four comparison views, switchable at any time:
  - **Only in A** — bookmarks unique to File A
  - **Only in B** — bookmarks unique to File B
  - **In Both** — bookmarks present in both files
  - **Not in Both** — all non-matching bookmarks from either file (union of "Only in A" and "Only in B")
- Results show a source badge ([A], [B], or [A+B]) for each bookmark
- Filter results by name or URL
- Select / deselect individual results; toggle-all via the column heading
- Export selected results to a Netscape HTML file (filename is auto-suffixed based on the active mode)

---

## 🎨 Theming
- Toggle between **Light Mode** and **Dark Mode** using the button in the top-right corner
- Theme applies instantly across all three modes

---

## ⌨️ Keyboard Shortcuts
All shortcuts work globally and are delegated to whichever mode tab is currently active.

| Shortcut | Action |
|---|---|
| `Ctrl+O` | Open a bookmarks file |
| `Ctrl+E` | Export selected bookmarks |
| `Ctrl+F` | Focus the search / filter bar |

---

## 🔧 URL Normalisation
URLs are normalised before any comparison or duplicate detection:
- Lowercased and whitespace-stripped
- Trailing slash removed
- Fragment (`#…`) removed
- Common tracking parameters stripped (`utm_*`, `fbclid`, `gclid`, `ref`, `_ga`, and others)

This means bookmarks that differ only by tracking parameters or case are correctly treated as the same URL.

---

## 📦 Supported Formats
Works with standard browser bookmark exports:
- Chrome
- Edge
- Firefox
- Any Netscape-compatible HTML bookmark file

---

## 🖥️ Requirements
- Python 3.x
- No external dependencies — uses built-in libraries only

Modules used:
- `tkinter`
- `html.parser`
- `urllib.parse`
- `collections`
- `datetime`
- `threading`
- `os`

---

## ▶️ How to Run

### Standard Python file:
```bash
python bookmark_comparison_gui_click.pyw
```

### Windowless (Windows — `.pyw` extension suppresses the console):
Double-click `bookmark_comparison_gui_click.pyw` directly, or run:
```bash
pythonw bookmark_comparison_gui_click.pyw
```

---

## 📤 Export Format
All exports produce a valid **Netscape Bookmark HTML** file that can be imported into any major browser (Chrome, Edge, Firefox, etc.). Normal Mode exports preserve the original folder structure; Duplicates and Compare Mode exports produce a flat list.

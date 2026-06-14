# Custom-Bookmark-Extractor
A Python GUI tool for extracting, filtering, deduplicating, and comparing browser bookmarks from exported HTML files.
Built with Tkinter, this tool helps you organize bookmarks, clean exports, find duplicates, and compare bookmark collections between files.

---

## 🚀 Features

### ◈ Normal Mode
- Load an exported browser bookmark HTML file
- Browse bookmarks in a full tree structure (folders + links)
  - Folders display a bookmark count in parentheses next to their name
- Search bookmarks by name or URL (live filtering)
- Select / deselect individual bookmarks and folders
  - Folders show a partial-check indicator (☒) when only some children are selected
  - Clicking a folder propagates the check state to all its children
- Select All / Deselect All with one click (or via the column heading)
- **Drag-to-reorder** bookmarks and folders within the tree
  - Toggle a lock/unlock button to enable or disable reordering
- **Undo / Redo** — unlimited undo and redo for all tree changes (reordering, check toggles, bulk renames)
- **Breadcrumb bar** — shows the full folder path of the selected item; folder segments are clickable and jump to that folder in the tree
- **Jump to Folder** (`Ctrl+G`) — type-to-filter dialog listing all folders; arrow keys navigate, Enter jumps to the selection
- **Filter dialog** — filter the visible tree by:
  - Item type (bookmarks only, folders only, or all)
  - `ADD_DATE` date range (YYYY-MM-DD or Unix timestamp)
  - One or more specific folders
  - Active filters shown as dismissible chips; clear individually or all at once
- **Expand All / Collapse All** and **Expand Subfolders / Collapse Subfolders** toggle buttons
- **Bulk Rename** — find-and-replace across Name or URL fields across all bookmarks
  - Live preview table with before/after diff
  - Tick or untick individual matches before applying
  - Supports case-sensitive and case-insensitive matching
- Side panel shows selection info: count of selected bookmarks and folders, plus the URL of the last selected item
- Export selected bookmarks (preserving folder structure) to a clean Netscape HTML file
  - `ADD_DATE` is preserved in all exports
- Non-blocking file loading — large files are parsed on a background thread so the UI stays responsive

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
- Non-blocking file loading

### ⇌ Compare Mode
- Load two separate bookmark HTML files (File A and File B)
- **Swap Files (⇄)** — swap File A and File B and immediately re-run the comparison
- Compare by URL only (case-insensitive, trailing slash ignored) — bookmark titles are not used for matching
- Four comparison views, switchable at any time:
  - **Only in A** — bookmarks unique to File A
  - **Only in B** — bookmarks unique to File B
  - **In Both** — bookmarks present in both files
  - **Not in Both** — all non-matching bookmarks from either file
- **Diff View** — toggle to a side-by-side split panel showing File A on the left and File B on the right
  - Bookmarks unique to one side are highlighted (red = only in A, green = only in B, grey = shared)
  - Each side has independent check/uncheck controls
- **3-Way Compare (Advanced panel)** — load an optional third file (File C) to compare three exports at once
  - Eight comparison modes: Only in A, Only in B, Only in C, In all three, In A & B only, In A & C only, In B & C only, Not shared across all three
  - File C can be removed at any time to return to 2-way mode
- Results show a source badge (`[A]`, `[B]`, `[C]`, `[A+B]`, `[A+C]`, `[B+C]`, or `[A+B+C]`) for each bookmark
- Filter results by name or URL
- Select / deselect individual results; toggle-all via the column heading
- Export selected results to a Netscape HTML file (filename is auto-suffixed based on the active mode)
- Non-blocking file loading

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
| `Ctrl+G` | Jump to Folder (Normal Mode) |
| `Ctrl+Z` | Undo (Normal Mode) |
| `Ctrl+Y` | Redo (Normal Mode) |

---

## 🔧 URL Normalisation
URLs are normalised before any comparison or duplicate detection:
- Lowercased and whitespace-stripped
- Trailing slash removed
- Fragment (`#…`) removed
- Common tracking parameters stripped (`utm_*`, `fbclid`, `gclid`, `ref`, `_ga`, and others)

This means bookmarks that differ only by tracking parameters, fragments, or case are correctly treated as the same URL.

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
- `typing`
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
All exports produce a valid **Netscape Bookmark HTML** file that can be imported into any major browser (Chrome, Edge, Firefox, etc.). Normal Mode exports preserve the original folder structure and `ADD_DATE` metadata; Duplicates and Compare Mode exports produce a flat list.

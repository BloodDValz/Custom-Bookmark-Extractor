# Custom-Bookmark-Extractor

A Python GUI tool for extracting, filtering, and comparing browser bookmarks from exported HTML files.

Built with Tkinter, this tool helps you organize bookmarks, clean exports, and compare bookmark collections between two files.

---

## 🚀 Features

### 📁 Normal Mode
- Load exported browser bookmark HTML files
- Browse bookmarks in a tree structure (folders + links)
- Search bookmarks by name or URL
- Select / deselect bookmarks and folders
- Select all / deselect all functionality
- Export selected bookmarks into a clean HTML file

### 🔍 Compare Mode
- Compare two bookmark files side-by-side
- Match bookmarks using URL only (not titles)
- Case-insensitive comparison
- Ignores trailing slashes in URLs
- View results:
  - Only in File A
  - Only in File B
  - Present in both files
  - Non-matching bookmarks
- Filter comparison results
- Export selected comparison results

---

## 📦 Supported Format

This tool works with standard browser bookmark exports:
- Chrome
- Edge
- Firefox
- Any Netscape-compatible HTML bookmark file

---

## 🖥️ Requirements

- Python 3.x
- No external dependencies (uses built-in libraries only)

Modules used:
- `tkinter`
- `html.parser`
- `datetime`
- `os`

---

## ▶️ How to Run

### Normal Python file:
```bash
python BookmarkExtractor.py

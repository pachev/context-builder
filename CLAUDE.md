# Context Builder

Essential info about the Context Builder project for Claude and other AI assistants.

## Project Overview

Context Builder is a terminal UI application (Textual) that helps users create context files for LLMs. Users browse project files, select which to include, and generate formatted output for use with LLMs like Claude.

## Project Structure

```
context-builder/
├── .pre-commit-config.yaml  # ruff lint + format hooks
├── pyproject.toml           # Project configuration and dependencies
├── CLAUDE.md
├── src/
│   └── context_builder/
│       ├── __init__.py      # Package marker and version
│       ├── __main__.py      # Entry point for running as module
│       ├── app.py           # Textual TUI application
│       ├── cli.py           # CLI entry point
│       └── utils.py         # Pure utility functions (no GUI deps)
```

## Architecture

1. **Utils (utils.py)** — Pure functions, no GUI deps:
   - `is_likely_binary_file()`, `should_ignore()`, `read_gitignore()`
   - `add_line_numbers()`, `estimate_tokens()`, `generate_project_tree()`
   - `generate_output()` — main context generation logic

2. **TUI Application (app.py)** — Textual-based:
   - `CheckboxFileTree` — custom `Tree` widget with checkbox toggling and lazy loading
   - `ContextBuilderApp` — main app: sidebar options, file tree, preview pane
   - Debounced preview updates via worker threads

3. **CLI (cli.py)** — Parses path arg, launches TUI

4. **Entry Points**
   - `__main__.py`: `python -m context_builder`
   - `ctx-builder` command: defined in pyproject.toml

## Key Implementation Details

### CheckboxFileTree
- Subclasses Textual's `Tree` widget (not `DirectoryTree`)
- Lazy-loads children on expand via `_on_tree_node_expanded`
- Stores `{path, checked, is_dir, loaded}` in `node.data`
- Recursive check/uncheck on directory toggle
- Skips binary files during tree population

### Output Formats
- **XML**: `<context>` > `<projectTree>` + `<files>` > `<file path="..." type="...">`
- **Markdown**: fenced code blocks with language detection
- **Plain Text**: `--- File: path ---` separators

### Token Counting
- tiktoken (gpt-4 encoding) with fallback to `len(text) // 4`

## Development

### Commands
```bash
uv sync                    # Install deps
uv run ctx-builder .       # Run the app
uv run ruff check src/     # Lint
uv run ruff format src/    # Format
```

### Code Quality
- **Ruff**: lint + format, enforced via pre-commit hooks and CI
- **Pre-commit**: `ruff` (with --fix) + `ruff-format` on every commit
- **CI**: GitHub Actions runs ruff lint + format check on push/PR

### Code Conventions
- CamelCase classes, snake_case functions, UPPER_SNAKE_CASE constants
- 4-space indent, 120 char line length
- Single quotes (ruff format config)

## UI Widget Hierarchy

```
ContextBuilderApp (App)
├── Header
├── Horizontal
│   ├── Vertical#sidebar
│   │   ├── Vertical#sidebar-options
│   │   │   ├── Select#format-select
│   │   │   ├── Switch#line-nums + Label
│   │   │   ├── Switch#proj-tree + Label
│   │   │   ├── Switch#hidden + Label
│   │   │   └── Switch#gitignore + Label
│   │   ├── Rule
│   │   ├── CheckboxFileTree#file-tree
│   │   └── Horizontal#tree-buttons
│   │       ├── Button#sel-all
│   │       └── Button#desel-all
│   └── Vertical#main-content
│       ├── Label#instructions-label
│       ├── TextArea#instructions
│       ├── Rule
│       ├── Horizontal#preview-header
│       │   ├── Static#preview-label
│       │   └── Static#token-count
│       └── TextArea#preview (read-only)
└── Footer
```

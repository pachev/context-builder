"""
Utility functions for Context Builder.

Pure functions with no GUI dependencies — shared between TUI and any future interfaces.
"""

import os
import sys
import traceback
from typing import Optional
from fnmatch import fnmatch

# Attempt to import tiktoken for accurate token counting
try:
    import tiktoken

    TIKTOKEN_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    TIKTOKEN_AVAILABLE = False

# --- Constants ---

EXT_TO_LANG: dict[str, str] = {
    'py': 'python',
    'c': 'c',
    'cpp': 'cpp',
    'java': 'java',
    'js': 'javascript',
    'ts': 'typescript',
    'tsx': 'typescript',
    'html': 'html',
    'css': 'css',
    'xml': 'xml',
    'json': 'json',
    'yaml': 'yaml',
    'yml': 'yaml',
    'sh': 'bash',
    'rb': 'ruby',
    'kt': 'kotlin',
    'go': 'go',
    'php': 'php',
    'swift': 'swift',
    'sql': 'sql',
    'rs': 'rust',
    'md': 'markdown',
    'toml': 'toml',
    'ex': 'elixir',
    'exs': 'elixir',
}

DEFAULT_TOKENIZER_MODEL = 'gpt-4'
BINARY_CHECK_CHUNK_SIZE = 1024


def is_likely_binary_file(filepath: str, chunk_size: int = BINARY_CHECK_CHUNK_SIZE) -> bool:
    """Heuristically checks if a file is likely binary by looking for null bytes."""
    try:
        with open(filepath, 'rb') as f:
            chunk = f.read(chunk_size)
        return b'\x00' in chunk
    except (OSError, Exception):
        return True


def should_ignore(path: str, gitignore_rules: list[str]) -> bool:
    """Checks if a path should be ignored based on simplified .gitignore rules."""
    basename = os.path.basename(path)
    normalized_path = os.path.normpath(path)
    ignored = False
    negated_match = False

    for rule in gitignore_rules:
        if not rule or rule.startswith('#'):
            continue
        is_negating = rule.startswith('!')
        if is_negating:
            rule = rule[1:]

        match = False
        if rule.endswith('/'):
            if os.path.isdir(normalized_path) and fnmatch(basename, rule.rstrip('/')):
                match = True
        elif '/' in rule:
            if fnmatch(normalized_path, '*' + rule.replace('/', os.sep)):
                match = True
        else:
            if fnmatch(basename, rule):
                match = True

        if match:
            if is_negating:
                ignored = False
                negated_match = True
            elif not negated_match:
                ignored = True
    return ignored


def read_gitignore(directory_path: str) -> list[str]:
    """Reads and parses a .gitignore file."""
    gitignore_path = os.path.join(directory_path, '.gitignore')
    rules: list[str] = []
    if os.path.isfile(gitignore_path):
        try:
            with open(gitignore_path, 'r', encoding='utf-8') as f:
                rules = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        except (OSError, UnicodeDecodeError) as e:
            print(f'Warning: Could not read .gitignore: {e}', file=sys.stderr)
    return rules


def add_line_numbers(content: str) -> str:
    """Prepends line numbers to each line of a string."""
    lines = content.splitlines()
    if not lines:
        return ''
    padding = len(str(len(lines)))
    return '\n'.join(f'{i + 1:<{padding}} | {line}' for i, line in enumerate(lines))


def estimate_tokens(text: str, model: str = DEFAULT_TOKENIZER_MODEL) -> int:
    """Estimates token count using tiktoken or character approximation."""
    if TIKTOKEN_AVAILABLE:
        try:
            enc = tiktoken.encoding_for_model(model)
            return len(enc.encode(text))
        except (KeyError, Exception):
            pass
    return len(text) // 4


def generate_project_tree(
    path: str,
    prefix: str = '',
    ignore_hidden: bool = True,
    gitignore_rules: Optional[list[str]] = None,
) -> list[str]:
    """Generates a text tree representation of a directory."""
    if gitignore_rules is None:
        gitignore_rules = []
    tree_lines: list[str] = []
    try:
        entries = os.listdir(path)
    except (PermissionError, FileNotFoundError):
        return tree_lines

    filtered_entries: list[tuple[str, str, bool]] = []
    for entry in entries:
        full_path = os.path.join(path, entry)
        if ignore_hidden and entry.startswith('.'):
            continue
        if gitignore_rules and should_ignore(full_path, gitignore_rules):
            continue
        try:
            is_dir = os.path.isdir(full_path)
            filtered_entries.append((entry, full_path, is_dir))
        except OSError:
            continue

    filtered_entries.sort(key=lambda x: (not x[2], x[0].lower()))

    entry_count = len(filtered_entries)
    for i, (entry_name, full_path, is_dir) in enumerate(filtered_entries):
        is_last = i == (entry_count - 1)
        connector = '└── ' if is_last else '├── '
        tree_lines.append(f'{prefix}{connector}{entry_name}')
        if is_dir:
            next_prefix = prefix + ('    ' if is_last else '│   ')
            tree_lines.extend(generate_project_tree(full_path, next_prefix, ignore_hidden, gitignore_rules))
    return tree_lines


def generate_output(
    file_paths: list[str],
    output_format: str,
    include_line_numbers: bool,
    include_project_tree: bool,
    base_dir: Optional[str],
    ignore_hidden: bool = True,
    gitignore_rules: Optional[list[str]] = None,
    custom_instructions: str = '',
) -> str:
    """Generates the final context string."""
    if gitignore_rules is None:
        gitignore_rules = []
    result_lines: list[str] = []

    def escape_xml(text: str) -> str:
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # Add custom instructions before context
    if custom_instructions.strip():
        result_lines.append(custom_instructions.strip())
        result_lines.append('')

    if output_format == 'xml':
        result_lines.append('<context>')

    # Project structure tree
    if include_project_tree and base_dir:
        tree_lines = generate_project_tree(base_dir, ignore_hidden=ignore_hidden, gitignore_rules=gitignore_rules)
        base_dir_name = os.path.basename(base_dir)
        full_tree_text = base_dir_name + '\n' + '\n'.join(tree_lines)

        if output_format == 'xml':
            result_lines.extend(['<projectTree>', escape_xml(full_tree_text), '</projectTree>'])
        elif output_format == 'markdown':
            result_lines.extend(['**Project Structure:**', '```', full_tree_text, '```'])
        else:
            result_lines.extend(['--- Project Structure ---', full_tree_text, '--- End Structure ---'])
        result_lines.append('')

    # File contents
    if file_paths:
        if output_format == 'xml':
            result_lines.append('<files>')
        elif output_format in ['markdown', 'plaintext']:
            result_lines.extend(['--- Files ---', ''])

        for file_path in sorted(file_paths):
            if is_likely_binary_file(file_path):
                continue

            try:
                rel_path = file_path
                abs_base_dir = os.path.abspath(base_dir) if base_dir else None
                abs_file_path = os.path.abspath(file_path)
                if abs_base_dir and abs_file_path.startswith(abs_base_dir + os.sep):
                    rel_path = os.path.relpath(abs_file_path, abs_base_dir)

                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                if include_line_numbers:
                    content = add_line_numbers(content)

                if output_format == 'plaintext':
                    result_lines.extend([f'--- File: {rel_path} ---', content, '--- End File ---', ''])
                elif output_format == 'xml':
                    file_ext = os.path.splitext(rel_path)[1].lstrip('.')
                    result_lines.extend([
                        f'<file path="{escape_xml(rel_path)}" type="{escape_xml(file_ext)}">',
                        escape_xml(content),
                        '</file>',
                    ])
                elif output_format == 'markdown':
                    lang = EXT_TO_LANG.get(file_path.split('.')[-1].lower(), '')
                    result_lines.extend([f'**File:** `{rel_path}`', f'```{lang}', content, '```', ''])

            except (UnicodeDecodeError, OSError) as e:
                print(f'Warning: Error processing file {file_path}: {e}', file=sys.stderr)
            except Exception as e:
                print(f'Warning: Unexpected error processing file {file_path}: {e}', file=sys.stderr)
                traceback.print_exc()

        if output_format == 'xml':
            result_lines.append('</files>')

    if output_format == 'xml':
        result_lines.append('</context>')
    return '\n'.join(result_lines)

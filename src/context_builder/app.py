"""
Context Builder - A native macOS app for building context files for LLMs

This module contains the main application logic for the Context Builder GUI,
built using PyQt6.
"""

import os
import sys
import signal
import traceback
from typing import Any, Dict, List, Tuple, Optional
from fnmatch import fnmatch

# Attempt to import tiktoken for accurate token counting
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    TIKTOKEN_AVAILABLE = False
    print("Warning: tiktoken library not found. Using approximate token counting.", file=sys.stderr)

# PyQt6 imports
from PyQt6.QtGui import QFont, QAction, QStandardItem, QGuiApplication, QStandardItemModel
from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QWidget,
    QToolBar,
    QCheckBox,
    QComboBox,
    QSplitter,
    QTextEdit,
    QTreeView,
    QStatusBar,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QApplication,
)

# --- Constants ---

EXT_TO_LANG: Dict[str, str] = {
    'py': 'python', 'c': 'c', 'cpp': 'cpp', 'java': 'java',
    'js': 'javascript', 'ts': 'typescript', 'tsx': 'typescript',
    'html': 'html', 'css': 'css', 'xml': 'xml', 'json': 'json',
    'yaml': 'yaml', 'yml': 'yaml', 'sh': 'bash', 'rb': 'ruby',
    'kt': 'kotlin', 'go': 'go', 'php': 'php', 'swift': 'swift',
    'sql': 'sql',
}
DEFAULT_TOKENIZER_MODEL = 'gpt-4'
UPDATE_DEBOUNCE_MS = 300
STATUS_MESSAGE_TIMEOUT_MS = 3000
BINARY_CHECK_CHUNK_SIZE = 1024 # Bytes to read for binary check

# --- Utility Functions ---

def is_likely_binary_file(filepath: str, chunk_size: int = BINARY_CHECK_CHUNK_SIZE) -> bool:
    """
    Heuristically checks if a file is likely binary by looking for null bytes.
    """
    try:
        with open(filepath, 'rb') as f:
            chunk = f.read(chunk_size)
        # Check for null byte presence
        return b'\x00' in chunk
    except OSError:
        # If we can't even open it to check, treat it as potentially problematic/binary
        return True
    except Exception:
         # Catch other potential issues during the check
         return True

def should_ignore(path: str, gitignore_rules: List[str]) -> bool:
    """
    Checks if a path should be ignored based on simplified .gitignore rules.
    Note: This is a simplified implementation.
    """
    basename = os.path.basename(path)
    normalized_path = os.path.normpath(path)
    ignored = False
    negated_match = False

    for rule in gitignore_rules:
        if not rule or rule.startswith('#'): continue
        is_negating = rule.startswith('!')
        if is_negating: rule = rule[1:]

        match = False
        if rule.endswith('/'): # Directory rule
            if os.path.isdir(normalized_path) and fnmatch(basename, rule.rstrip('/')):
                match = True
        elif '/' in rule: # Path rule (simplified)
            if fnmatch(normalized_path, '*' + rule.replace('/', os.sep)):
                 match = True
        else: # File/Pattern rule
            if fnmatch(basename, rule):
                match = True

        if match:
            if is_negating:
                ignored = False
                negated_match = True
            elif not negated_match:
                ignored = True
    return ignored


def read_gitignore(directory_path: str) -> List[str]:
    """Reads and parses a .gitignore file."""
    gitignore_path = os.path.join(directory_path, '.gitignore')
    rules: List[str] = []
    if os.path.isfile(gitignore_path):
        try:
            with open(gitignore_path, 'r', encoding='utf-8') as f:
                rules = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        except OSError as e:
            print(f"Warning: Could not read .gitignore file at {gitignore_path}: {e}", file=sys.stderr)
        except UnicodeDecodeError as e:
             print(f"Warning: Could not decode .gitignore file at {gitignore_path} as UTF-8: {e}", file=sys.stderr)
    return rules


def add_line_numbers(content: str) -> str:
    """Prepends line numbers to each line of a string."""
    lines = content.splitlines()
    if not lines: return ""
    padding = len(str(len(lines)))
    return '\n'.join(f'{i + 1:<{padding}} | {line}' for i, line in enumerate(lines))


def estimate_tokens(text: str, model: str = DEFAULT_TOKENIZER_MODEL) -> int:
    """Estimates token count using tiktoken or character approximation."""
    if TIKTOKEN_AVAILABLE:
        try:
            enc = tiktoken.encoding_for_model(model)
            return len(enc.encode(text))
        except KeyError:
            print(f"Warning: Tiktoken encoding for model '{model}' not found. Using approximation.", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Error using tiktoken ({type(e).__name__}). Using approximation.", file=sys.stderr)
    # Fallback: ~4 chars per token
    return len(text) // 4

def generate_project_tree(
    path: str, prefix: str = '', ignore_hidden: bool = True, gitignore_rules: Optional[List[str]] = None
) -> List[str]:
    """Generates a text tree representation of a directory."""
    if gitignore_rules is None: gitignore_rules = []
    tree_lines: List[str] = []
    try:
        entries = os.listdir(path)
    except (PermissionError, FileNotFoundError) as e:
        print(f"Warning: Cannot list directory '{path}': {e}", file=sys.stderr)
        return tree_lines

    filtered_entries: List[Tuple[str, str, bool]] = []
    for entry in entries:
        full_path = os.path.join(path, entry)
        if ignore_hidden and entry.startswith('.'): continue
        if gitignore_rules and should_ignore(full_path, gitignore_rules): continue
        try:
            is_dir = os.path.isdir(full_path)
            filtered_entries.append((entry, full_path, is_dir))
        except OSError as e:
             print(f"Warning: Cannot access '{full_path}': {e}. Skipping.", file=sys.stderr)

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

# --- GUI Classes ---

class FileTreeModel(QStandardItemModel):
    """Manages the file tree data and filtering."""
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(['Files'])
        self.ignore_hidden: bool = True
        self.use_gitignore: bool = True
        self.gitignore_rules: List[str] = []
        self.current_root_path: Optional[str] = None

    def load_directory(self, path: str) -> None:
        """Loads directory structure into the model."""
        self.clear()
        self.setHorizontalHeaderLabels(['Files'])
        self.current_root_path = os.path.abspath(path)
        self.gitignore_rules = read_gitignore(self.current_root_path) if self.use_gitignore else []
        root_item = self.invisibleRootItem()
        self._load_directory_recursive(self.current_root_path, root_item)

    def _load_directory_recursive(self, path: str, parent_item: QStandardItem) -> None:
        """Recursively loads directory contents."""
        dir_entries_to_process: List[Tuple[str, QStandardItem, bool]] = []
        try:
            entries = os.listdir(path)
        except (PermissionError, FileNotFoundError): return

        for entry_name in entries:
            full_path = os.path.join(path, entry_name)
            if self.ignore_hidden and entry_name.startswith('.'): continue
            if self.use_gitignore and should_ignore(full_path, self.gitignore_rules): continue
            try:
                is_dir = os.path.isdir(full_path)
            except OSError: continue

            # Skip adding likely binary files to the tree model itself
            # This prevents users from even selecting them.
            if not is_dir and is_likely_binary_file(full_path):
                 print(f"Skipping likely binary file: {entry_name}", file=sys.stderr)
                 continue

            item = QStandardItem(entry_name)
            item.setData(full_path, Qt.ItemDataRole.UserRole)
            item.setCheckable(True)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            dir_entries_to_process.append((entry_name, item, is_dir))
            if is_dir:
                self._load_directory_recursive(full_path, item)

        sorted_entries = sorted(dir_entries_to_process, key=lambda x: (not x[2], x[0].lower()))
        for _, item, _ in sorted_entries:
            parent_item.appendRow(item)


class FileTree(QTreeView):
    """Displays the file structure with checkboxes."""
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.file_model = FileTreeModel()
        self.setModel(self.file_model)
        self.setHeaderHidden(True)
        self.setMouseTracking(True)
        self.file_model.dataChanged.connect(self.data_changed_handler)

    def data_changed_handler(self, _topLeft: Any, _bottomRight: Any, roles: List[int]) -> None:
        """Updates viewport when check state changes."""
        check_state_role = getattr(Qt.ItemDataRole, 'CheckStateRole', None)
        if check_state_role and check_state_role in roles:
            self.viewport().update()

    def mousePressEvent(self, event: Any) -> None:
        """Handles clicks on checkboxes."""
        index = self.indexAt(event.pos())
        if index.isValid():
            checkbox_rect_width = self.indentation() + 20
            item_rect = self.visualRect(index)
            if event.pos().x() >= item_rect.left() and event.pos().x() <= item_rect.left() + checkbox_rect_width:
                item = self.file_model.itemFromIndex(index)
                if item and item.isCheckable():
                    new_checked_state = (item.checkState() != Qt.CheckState.Checked)
                    self.set_check_state_recursive(item, new_checked_state)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def set_check_state_recursive(self, item: QStandardItem, checked: bool) -> None:
        """Sets check state for an item and its children."""
        check_state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        if item.checkState() == check_state: return
        item.setCheckState(check_state)
        for row in range(item.rowCount()):
            child = item.child(row)
            if child is not None:
                self.set_check_state_recursive(child, checked)

    def get_checked_files(self) -> List[str]:
        """Returns a list of full paths for checked files."""
        checked_files: List[str] = []
        root = self.file_model.invisibleRootItem()
        self._get_checked_files_recursive(root, checked_files)
        return checked_files

    def _get_checked_files_recursive(self, item: QStandardItem, checked_files: List[str]) -> None:
        """Recursive helper for get_checked_files."""
        if item.isCheckable() and item.checkState() == Qt.CheckState.Checked:
            path = item.data(Qt.ItemDataRole.UserRole)
            # Check path exists and is a file (redundant check as binaries are excluded earlier, but safe)
            if path and os.path.isfile(path):
                checked_files.append(path)
        for row in range(item.rowCount()):
            child = item.child(row)
            if child is not None:
                self._get_checked_files_recursive(child, checked_files)


class ContextBuilder(QMainWindow):
    """Main application window."""
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('Context Builder')
        self.setMinimumSize(1000, 700)
        self.current_dir: Optional[str] = None
        self.toolbar: QToolBar
        self.file_tree: FileTree
        self.main_splitter: QSplitter
        self.format_combo: QComboBox
        self.line_numbers_check: QCheckBox
        self.project_tree_check: QCheckBox
        self.hidden_check: QCheckBox
        self.gitignore_check: QCheckBox
        self.preview: QTextEdit
        self.token_count_label: QLabel
        self.status_bar: QStatusBar
        self.status_timer: QTimer
        self.update_timer: QTimer
        self.create_toolbar()
        self.create_main_ui()
        self.create_statusbar()
        self.setup_timers()
        self.connect_signals()
        self.setCentralWidget(self.main_splitter)
        self.update_filter_settings()

    def create_toolbar(self) -> None:
        """Creates the main toolbar."""
        self.toolbar = QToolBar('Main Toolbar')
        self.toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(self.toolbar)
        open_action = QAction('Open Folder...', self)
        self.toolbar.addAction(open_action)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(QLabel(' Format: '))
        self.format_combo = QComboBox()
        self.format_combo.addItems(['XML', 'Markdown', 'Plain Text'])
        self.format_combo.setToolTip("Select the output format.")
        self.toolbar.addWidget(self.format_combo)
        self.toolbar.addSeparator()
        self.line_numbers_check = QCheckBox('Line Numbers')
        self.line_numbers_check.setToolTip("Prepend line numbers to file content.")
        self.toolbar.addWidget(self.line_numbers_check)
        self.project_tree_check = QCheckBox('Include Project Structure')
        self.project_tree_check.setToolTip("Include a text representation of the project tree.")
        self.toolbar.addWidget(self.project_tree_check)
        self.toolbar.addSeparator()
        self.hidden_check = QCheckBox('Show Hidden Files')
        self.hidden_check.setToolTip("Show files/folders starting with '.' (requires reload).")
        self.toolbar.addWidget(self.hidden_check)
        self.gitignore_check = QCheckBox('Use .gitignore')
        self.gitignore_check.setChecked(True)
        self.gitignore_check.setToolTip("Respect rules in project's .gitignore (requires reload).")
        self.toolbar.addWidget(self.gitignore_check)
        self.toolbar.addSeparator()
        copy_action = QAction('Copy to Clipboard', self)
        copy_action.setToolTip("Copy the generated context to the clipboard.")
        self.toolbar.addAction(copy_action)
        save_action = QAction('Save to File...', self)
        save_action.setToolTip("Save the generated context to a file.")
        self.toolbar.addAction(save_action)
        open_action.triggered.connect(self.open_directory)
        copy_action.triggered.connect(self.copy_to_clipboard)
        save_action.triggered.connect(self.save_to_file)

    def create_main_ui(self) -> None:
        """Creates the main splitter layout."""
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        self.file_tree = FileTree()
        left_layout.addWidget(self.file_tree)
        button_layout = QHBoxLayout()
        select_all_btn = QPushButton('Select All')
        deselect_all_btn = QPushButton('Deselect All')
        button_layout.addWidget(select_all_btn)
        button_layout.addWidget(deselect_all_btn)
        left_layout.addLayout(button_layout)
        self.main_splitter.addWidget(left_widget)
        select_all_btn.clicked.connect(self.select_all_files)
        deselect_all_btn.clicked.connect(self.deselect_all_files)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(5, 5, 5, 5)
        right_layout.setSpacing(6)
        token_layout = QHBoxLayout()
        token_layout.setContentsMargins(0, 0, 0, 0)
        token_layout.addWidget(QLabel('Estimated Token Count:'))
        self.token_count_label = QLabel('0')
        self.token_count_label.setStyleSheet("font-weight: bold;")
        self.token_count_label.setToolTip("Estimated token count (using tiktoken if available).")
        token_layout.addWidget(self.token_count_label)
        token_layout.addStretch()
        right_layout.addLayout(token_layout)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        right_layout.addWidget(separator)
        preview_label = QLabel("Generated Context Preview:")
        preview_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(preview_label)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        mono_font = QFont("Monaco", 11)
        if not mono_font.exactMatch(): mono_font = QFont("Courier New", 11)
        self.preview.setFont(mono_font)
        self.preview.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        right_layout.addWidget(self.preview)
        self.main_splitter.addWidget(right_widget)
        self.main_splitter.setSizes([350, 650])
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 3)

    def create_statusbar(self) -> None:
        """Creates the status bar."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage('Ready. Open a folder to begin.')

    def setup_timers(self) -> None:
        """Initializes QTimers."""
        self.status_timer = QTimer(self)
        self.status_timer.setSingleShot(True)
        self.status_timer.timeout.connect(self.restore_status_message)
        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.update_preview_and_tokens)

    def connect_signals(self) -> None:
        """Connects UI signals to slots."""
        self.format_combo.currentTextChanged.connect(self.schedule_update)
        self.line_numbers_check.stateChanged.connect(self.schedule_update)
        self.project_tree_check.stateChanged.connect(self.schedule_update)
        self.hidden_check.stateChanged.connect(self.update_filter_settings_and_reload)
        self.gitignore_check.stateChanged.connect(self.update_filter_settings_and_reload)
        self.file_tree.file_model.itemChanged.connect(self.handle_item_changed)

    # --- Slots ---
    def handle_item_changed(self, item: QStandardItem) -> None:
        if item.isCheckable(): self.schedule_update()

    def update_filter_settings(self) -> None:
        self.file_tree.file_model.ignore_hidden = not self.hidden_check.isChecked()
        self.file_tree.file_model.use_gitignore = self.gitignore_check.isChecked()

    def update_filter_settings_and_reload(self) -> None:
        self.update_filter_settings()
        if self.current_dir:
            self.file_tree.file_model.load_directory(self.current_dir)
            self.show_temporary_message("Filters updated and tree reloaded.")
            self.schedule_update()
        else:
             self.show_temporary_message("Filter settings changed.")

    def open_directory(self) -> None:
        start_dir = self.current_dir if self.current_dir else os.path.expanduser("~")
        dir_path = QFileDialog.getExistingDirectory(self, 'Select Project Directory', start_dir)
        if dir_path: self.open_directory_path(dir_path)

    def select_all_files(self) -> None:
        root_item = self.file_tree.file_model.invisibleRootItem()
        self.file_tree.file_model.blockSignals(True)
        for row in range(root_item.rowCount()):
            item = root_item.child(row)
            if item is not None: self.file_tree.set_check_state_recursive(item, True)
        self.file_tree.file_model.blockSignals(False)
        self.schedule_update()
        self.file_tree.viewport().update()

    def deselect_all_files(self) -> None:
        root_item = self.file_tree.file_model.invisibleRootItem()
        self.file_tree.file_model.blockSignals(True)
        for row in range(root_item.rowCount()):
            item = root_item.child(row)
            if item is not None: self.file_tree.set_check_state_recursive(item, False)
        self.file_tree.file_model.blockSignals(False)
        self.schedule_update()
        self.file_tree.viewport().update()

    def schedule_update(self) -> None:
        self.update_timer.start(UPDATE_DEBOUNCE_MS)

    def update_preview_and_tokens(self) -> None:
        """Updates the preview text and token count."""
        if not self.current_dir:
            self.preview.setText("Open a folder to begin.")
            self.token_count_label.setText('0')
            return

        checked_files = self.file_tree.get_checked_files()
        include_proj_tree = self.project_tree_check.isChecked()

        if not checked_files and not include_proj_tree:
            self.preview.setText('No files selected and project structure not included.')
            self.token_count_label.setText('0')
            return

        output_format = self.format_combo.currentText().lower().replace(" ", "")
        include_line_nums = self.line_numbers_check.isChecked()

        try:
            preview_text = self.generate_output(
                file_paths=checked_files,
                output_format=output_format,
                include_line_numbers=include_line_nums,
                include_project_tree=include_proj_tree,
                base_dir=self.current_dir
            )
            self.preview.setText(preview_text)
            tokens = estimate_tokens(preview_text)
            self.token_count_label.setText(f"{tokens:,}")

        except Exception as e:
            error_message = f"Error generating preview:\n\n{type(e).__name__}: {e}"
            self.preview.setText(error_message)
            self.token_count_label.setText('Error')
            self.show_temporary_message("Error generating preview.", 5000)
            print(f"Error during output generation: {e}", file=sys.stderr)
            traceback.print_exc()

    def generate_output(
        self,
        file_paths: List[str],
        output_format: str,
        include_line_numbers: bool,
        include_project_tree: bool,
        base_dir: Optional[str]
    ) -> str:
        """Generates the final context string, skipping binary files."""
        result_lines: List[str] = []

        def escape_xml(text: str) -> str:
            return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        if output_format == 'xml': result_lines.append('<context>')

        # Add project structure tree
        if include_project_tree and base_dir:
            model = self.file_tree.file_model
            tree_gitignore_rules = model.gitignore_rules if model.use_gitignore else []
            tree_ignore_hidden = not self.hidden_check.isChecked()
            tree_lines = generate_project_tree(
                base_dir, ignore_hidden=tree_ignore_hidden, gitignore_rules=tree_gitignore_rules
            )
            base_dir_name = os.path.basename(base_dir)
            full_tree_text = base_dir_name + '\n' + '\n'.join(tree_lines)

            if output_format == 'xml':
                result_lines.extend(['<projectTree>', escape_xml(full_tree_text), '</projectTree>'])
            elif output_format == 'markdown':
                result_lines.extend(['**Project Structure:**', '```', full_tree_text, '```'])
            else: # plaintext
                result_lines.extend(['--- Project Structure ---', full_tree_text, '--- End Structure ---'])
            result_lines.append('')

        # Add file contents
        if file_paths:
            if output_format == 'xml': result_lines.append('<files>')
            elif output_format in ['markdown', 'plaintext']:
                result_lines.extend(['--- Files ---', ''])

            for file_path in sorted(file_paths):
                # --- Binary File Check ---
                # Although excluded from the tree, double-check here in case state changes
                if is_likely_binary_file(file_path):
                    warning_msg = f"Skipping likely binary file: {os.path.basename(file_path)}"
                    if output_format == 'xml': result_lines.append(f'')
                    else: result_lines.append(f'# {warning_msg}')
                    print(warning_msg, file=sys.stderr)
                    continue # Skip to the next file

                try:
                    rel_path = file_path
                    abs_base_dir = os.path.abspath(base_dir) if base_dir else None
                    abs_file_path = os.path.abspath(file_path)
                    if abs_base_dir and abs_file_path.startswith(abs_base_dir + os.sep):
                        rel_path = os.path.relpath(abs_file_path, abs_base_dir)

                    # Read as text, assuming it's not binary now
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f: content = f.read()
                    if include_line_numbers: content = add_line_numbers(content)

                    # Format output
                    if output_format == 'plaintext':
                        result_lines.extend([f"--- File: {rel_path} ---", content, "--- End File ---", ''])
                    elif output_format == 'xml':
                        file_ext = os.path.splitext(rel_path)[1].lstrip('.')
                        result_lines.extend([
                            f'<file path="{escape_xml(rel_path)}" type="{escape_xml(file_ext)}">',
                            escape_xml(content), '</file>'
                        ])
                    elif output_format == 'markdown':
                        lang = EXT_TO_LANG.get(file_path.split('.')[-1].lower(), '')
                        result_lines.extend([f"**File:** `{rel_path}`", f'```{lang}', content, '```', ''])

                except (UnicodeDecodeError, OSError) as e: # Catch specific errors during read/process
                    warning_msg = f"Warning: Error processing file '{os.path.basename(file_path)}': {e}"
                    if output_format == 'xml': result_lines.append(f'')
                    else: result_lines.append(f'# {warning_msg}')
                    print(warning_msg, file=sys.stderr)
                except Exception as e: # Catch any other unexpected errors
                    warning_msg = f"Warning: Unexpected error processing file '{os.path.basename(file_path)}': {e}"
                    if output_format == 'xml': result_lines.append(f'')
                    else: result_lines.append(f'# {warning_msg}')
                    print(warning_msg, file=sys.stderr)
                    traceback.print_exc() # Print traceback for unexpected errors

            if output_format == 'xml': result_lines.append('</files>')

        if output_format == 'xml': result_lines.append('</context>')
        return '\n'.join(result_lines)

    def restore_status_message(self) -> None:
        display_path = self.current_dir if self.current_dir else None
        message = f'Current Directory: {display_path}' if display_path else 'Ready. Open a folder.'
        self.status_bar.showMessage(message)

    def show_temporary_message(self, message: str, timeout: int = STATUS_MESSAGE_TIMEOUT_MS) -> None:
        self.status_bar.showMessage(message, timeout)
        self.status_timer.start(timeout + 100)

    def copy_to_clipboard(self) -> None:
        preview_content = self.preview.toPlainText()
        placeholder_texts = [
            'No files selected.', 'No files selected and project structure not included.',
            'Open a folder to begin.'
        ]
        if preview_content and preview_content not in placeholder_texts and not preview_content.startswith("Error"):
            try:
                QGuiApplication.clipboard().setText(preview_content)
                self.show_temporary_message('Copied to clipboard!')
            except Exception as e:
                self.show_temporary_message(f'Error copying: {e}', 5000)
                print(f"Clipboard error: {e}", file=sys.stderr)
        else:
             self.show_temporary_message('Nothing to copy.')

    def save_to_file(self) -> None:
        preview_content = self.preview.toPlainText()
        placeholder_texts = [
            'No files selected.', 'No files selected and project structure not included.',
            'Open a folder to begin.'
        ]
        if not preview_content or preview_content in placeholder_texts or preview_content.startswith("Error"):
            self.show_temporary_message('Nothing to save.')
            return

        suggested_filename = f"{os.path.basename(self.current_dir)}_context" if self.current_dir else "context_output"
        current_format = self.format_combo.currentText().lower()
        default_suffix, file_filter = ".txt", "Text Files (*.txt);;XML Files (*.xml);;Markdown Files (*.md);;All Files (*)"
        if current_format == 'xml': default_suffix, file_filter = ".xml", "XML Files (*.xml);;Text Files (*.txt);;Markdown Files (*.md);;All Files (*)"
        elif current_format == 'markdown': default_suffix, file_filter = ".md", "Markdown Files (*.md);;Text Files (*.txt);;XML Files (*.xml);;All Files (*)"
        suggested_path = os.path.join(self.current_dir or os.path.expanduser("~"), suggested_filename + default_suffix)

        file_path, selected_filter = QFileDialog.getSaveFileName(self, 'Save Context File', suggested_path, file_filter)

        if file_path:
            _, ext = os.path.splitext(file_path)
            if not ext:
                 if "(*.xml)" in selected_filter: file_path += ".xml"
                 elif "(*.md)" in selected_filter: file_path += ".md"
                 elif "(*.txt)" in selected_filter: file_path += ".txt"

            try:
                with open(file_path, 'w', encoding='utf-8') as f: f.write(preview_content)
                self.show_temporary_message(f'Saved to {os.path.basename(file_path)}')
            except OSError as e:
                self.show_temporary_message(f'Error saving file: {e}', 5000)
                print(f"Error saving file {file_path}: {e}", file=sys.stderr)
            except Exception as e:
                 self.show_temporary_message(f'Unexpected error saving: {e}', 5000)
                 print(f"Unexpected error saving file {file_path}: {e}", file=sys.stderr)

    def closeEvent(self, event: Any) -> None:
        print("Context Builder closing.")
        event.accept()

    def open_directory_path(self, path: str) -> None:
        """Opens a specific directory path."""
        if path and os.path.isdir(path):
            self.current_dir = os.path.abspath(path)
            self.status_bar.showMessage(f'Loading directory: {self.current_dir}...')
            QApplication.processEvents()
            try:
                self.update_filter_settings()
                self.file_tree.file_model.load_directory(self.current_dir)
                self.setWindowTitle(f'Context Builder - {os.path.basename(self.current_dir)}')
                self.restore_status_message()
                self.schedule_update()
            except Exception as e:
                error_msg = f"Error loading directory: {e}"
                self.status_bar.showMessage(error_msg)
                print(f"Error loading directory {path}: {e}", file=sys.stderr)

# --- Application Entry Point ---
def signal_handler(_sig: int, _frame: Any) -> None:
    print("\nCtrl+C detected. Exiting...")
    QApplication.quit()

def main() -> None:
    """Initializes and runs the application."""
    app = QApplication(sys.argv)
    app.setApplicationName('Context Builder')
    signal.signal(signal.SIGINT, signal_handler)
    signal_timer = QTimer()
    signal_timer.start(500)
    signal_timer.timeout.connect(lambda: None)
    window = ContextBuilder()
    window.show()
    initial_dir_to_open = None
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
        initial_dir_to_open = os.path.abspath(sys.argv[1])
    elif len(sys.argv) > 1:
        print(f"Warning: Argument '{sys.argv[1]}' not a valid directory.", file=sys.stderr)
    if initial_dir_to_open:
        QTimer.singleShot(100, lambda path=initial_dir_to_open: window.open_directory_path(path))
    sys.exit(app.exec())

if __name__ == '__main__':
    main()

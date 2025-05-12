"""
Context Builder - A native macOS app for building context files for LLMs
"""

import os
import sys
import signal
from typing import Any, Dict, List, Tuple, Optional
from fnmatch import fnmatch

from PyQt6.QtGui import QFont, QAction, QStandardItem, QStandardItemModel
from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtWidgets import (
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

EXT_TO_LANG: Dict[str, str] = {
    'py': 'python',
    'c': 'c',
    'cpp': 'cpp',
    'java': 'java',
    'js': 'javascript',
    'ts': 'typescript',
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
    'tsx': 'typescript',
}


def should_ignore(path: str, gitignore_rules: List[str]) -> bool:
    for rule in gitignore_rules:
        if fnmatch(os.path.basename(path), rule):
            return True
        if os.path.isdir(path) and fnmatch(os.path.basename(path) + '/', rule):
            return True
    return False


def read_gitignore(path: str) -> List[str]:
    gitignore_path = os.path.join(path, '.gitignore')
    if os.path.isfile(gitignore_path):
        with open(gitignore_path, 'r') as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    return []


def add_line_numbers(content: str) -> str:
    lines = content.splitlines()
    padding = len(str(len(lines)))
    numbered_lines = [f'{i + 1:{padding}}  {line}' for i, line in enumerate(lines)]
    return '\n'.join(numbered_lines)


def estimate_tokens(text: str) -> int:
    """Estimate token count using a simple heuristic"""
    # GPT models use roughly 4 characters per token on average
    return len(text) // 4


def generate_project_tree(
    path: str, prefix: str = '', ignore_hidden: bool = True, gitignore_rules: Optional[List[str]] = None
) -> List[str]:
    """Generate a formatted text tree representation of the directory structure"""
    if gitignore_rules is None:
        gitignore_rules = []

    result: List[str] = []

    try:
        entries = os.listdir(path)
    except PermissionError:
        return result

    # Filter and sort entries
    filtered_entries: List[Tuple[str, str, bool]] = []
    for entry in entries:
        if ignore_hidden and entry.startswith('.'):
            continue

        full_path = os.path.join(path, entry)
        if gitignore_rules and should_ignore(full_path, gitignore_rules):
            continue

        is_dir = os.path.isdir(full_path)
        filtered_entries.append((entry, full_path, is_dir))

    # Sort directories first, then files
    filtered_entries.sort(key=lambda x: (not x[2], x[0].lower()))

    # Generate tree lines
    for i, (entry, full_path, is_dir) in enumerate(filtered_entries):
        is_last = i == len(filtered_entries) - 1
        connector = '└── ' if is_last else '├── '

        result.append(f'{prefix}{connector}{entry}')

        if is_dir:
            # Adjust the prefix for the next level
            next_prefix = prefix + ('    ' if is_last else '│   ')
            subtree = generate_project_tree(full_path, next_prefix, ignore_hidden, gitignore_rules)
            result.extend(subtree)

    return result


class FileTreeModel(QStandardItemModel):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(['Files'])  # type: ignore
        self.ignore_hidden: bool = True
        self.ignore_gitignore: bool = False
        self.file_extensions: List[str] = []
        self.ignore_patterns: List[str] = []
        self.gitignore_rules: List[str] = []

    def load_directory(self, path: str) -> None:
        self.clear()
        self.setHorizontalHeaderLabels(['Files'])  # type: ignore
        if not self.ignore_gitignore:
            self.gitignore_rules = read_gitignore(path)

        root_item = self.invisibleRootItem()  # type: ignore
        self._load_directory_recursive(path, root_item)

    def _load_directory_recursive(self, path: str, parent_item: QStandardItem) -> None:
        dir_entries: List[Tuple[str, QStandardItem, bool]] = []

        try:
            entries = os.listdir(path)
        except PermissionError:
            # Handle permission errors gracefully
            return

        for entry in entries:
            full_path = os.path.join(path, entry)

            # Check if we should ignore this entry
            if self.ignore_hidden and entry.startswith('.'):
                continue

            if not self.ignore_gitignore and should_ignore(full_path, self.gitignore_rules):
                continue

            if self.ignore_patterns and any(fnmatch(entry, pattern) for pattern in self.ignore_patterns):
                continue

            is_dir = os.path.isdir(full_path)

            if not is_dir and self.file_extensions and not any(entry.endswith(ext) for ext in self.file_extensions):
                continue

            # Create item with improved checkbox handling
            item = QStandardItem(entry)
            item.setData(full_path, Qt.ItemDataRole.UserRole)
            item.setCheckable(True)
            # Explicitly set the initial state to unchecked
            item.setCheckState(Qt.CheckState.Unchecked)

            # Add flags to ensure it's clickable and checkable
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)

            if is_dir:
                # Recursively load subdirectories
                self._load_directory_recursive(full_path, item)

            dir_entries.append((entry, item, is_dir))

        # Sort directories first, then files
        sorted_entries = sorted(dir_entries, key=lambda x: (not x[2], x[0].lower()))
        for _, item, _ in sorted_entries:
            parent_item.appendRow(item)  # type: ignore


class FileTree(QTreeView):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.model = FileTreeModel()
        self.setModel(self.model)
        self.setSelectionMode(QTreeView.SelectionMode.SingleSelection)

        # Critical: Allow clicking on checkboxes
        self.setMouseTracking(True)

        # Handle clicks properly
        self.clicked.connect(self.item_clicked)

    def mousePressEvent(self, event: Any) -> None:
        # Override to properly handle checkbox clicks
        index = self.indexAt(event.pos())
        if index.isValid():
            # Get the item rect
            rect = self.visualRect(index)
            # Approximate checkbox area (adjust as needed)
            check_rect_width = 20
            if event.pos().x() <= rect.left() + check_rect_width:
                # Click in the checkbox region
                item = self.model.itemFromIndex(index)
                if item.isCheckable():
                    checked = item.checkState() == Qt.CheckState.Checked
                    self.set_check_state_recursive(item, not checked)
                    return
        # For clicks elsewhere, use standard behavior
        super().mousePressEvent(event)

    def item_clicked(self, index: Any) -> None:
        # This will handle non-checkbox area clicks
        # Do other click handling here (but not checkbox toggling)
        # For example, you might want to expand/collapse folders
        pass

    def set_check_state_recursive(self, item: QStandardItem, checked: bool) -> None:
        check_state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        item.setCheckState(check_state)

        # Apply to all children
        for row in range(item.rowCount()):
            child = item.child(row)
            if child is not None:
                self.set_check_state_recursive(child, checked)

        # Force UI update
        self.viewport().update()

    def get_checked_files(self) -> List[str]:
        checked_files: List[str] = []
        self._get_checked_files_recursive(self.model.invisibleRootItem(), checked_files)
        return checked_files

    def _get_checked_files_recursive(self, item: QStandardItem, checked_files: List[str]) -> None:
        if item.isCheckable() and item.checkState() == Qt.CheckState.Checked:
            path = item.data(Qt.ItemDataRole.UserRole)
            if path and os.path.isfile(path):
                checked_files.append(path)

        # Check children
        for row in range(item.rowCount()):
            child = item.child(row)
            if child is not None:
                self._get_checked_files_recursive(child, checked_files)


class ContextBuilder(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('Context Builder')
        self.setMinimumSize(1000, 700)

        # Initialize instance variables that will be set later
        self.toolbar: QToolBar
        self.file_tree: FileTree
        self.main_splitter: QSplitter
        self.format_combo: QComboBox
        self.line_numbers_check: QCheckBox
        self.project_tree_check: QCheckBox
        self.hidden_check: QCheckBox
        self.gitignore_check: QCheckBox
        self.preview: QTextEdit
        self.token_count: QLabel
        self.statusBar: QStatusBar

        # Init UI components
        self.create_toolbar()
        self.create_main_ui()
        self.create_statusbar()

        # Set the central widget
        self.setCentralWidget(self.main_splitter)

        # Variables
        self.current_dir: Optional[str] = None
        self.output_format: str = 'xml'
        self.include_line_numbers: bool = False
        self.include_project_tree: bool = False

        # Set up a timer for restoring status bar message after temporary messages
        self.status_timer = QTimer()
        self.status_timer.setSingleShot(True)
        self.status_timer.timeout.connect(self.restore_status_message)

        # Create a timer for debounced updates (to avoid too many updates while checking boxes)
        self.update_timer = QTimer()
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.update_preview)

        # Connect file tree model's data changed signal
        self.file_tree.model.dataChanged.connect(self.schedule_update)

    def create_toolbar(self) -> None:
        self.toolbar = QToolBar('Main Toolbar')
        self.toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(self.toolbar)

        # Open directory button
        open_action = QAction('Open Folder', self)
        open_action.triggered.connect(self.open_directory)
        self.toolbar.addAction(open_action)

        self.toolbar.addSeparator()

        # Format selection
        self.format_combo = QComboBox()
        self.format_combo.addItems(['XML', 'Markdown', 'Plain Text'])
        self.format_combo.currentTextChanged.connect(self.update_preview)
        self.toolbar.addWidget(QLabel('Format: '))
        self.toolbar.addWidget(self.format_combo)

        self.toolbar.addSeparator()

        # Line numbers checkbox
        self.line_numbers_check = QCheckBox('Line Numbers')
        self.line_numbers_check.stateChanged.connect(self.toggle_line_numbers)
        self.toolbar.addWidget(self.line_numbers_check)

        # Project tree checkbox
        self.project_tree_check = QCheckBox('Include Project Structure')
        self.project_tree_check.stateChanged.connect(self.toggle_project_tree)
        self.toolbar.addWidget(self.project_tree_check)

        self.toolbar.addSeparator()

        # Filter options
        self.hidden_check = QCheckBox('Include Hidden')
        self.hidden_check.stateChanged.connect(self.toggle_hidden_files)
        self.toolbar.addWidget(self.hidden_check)

        self.gitignore_check = QCheckBox('Ignore .gitignore')
        self.gitignore_check.stateChanged.connect(self.toggle_gitignore)
        self.toolbar.addWidget(self.gitignore_check)

        self.toolbar.addSeparator()

        # Copy to clipboard button
        copy_action = QAction('Copy to Clipboard', self)
        copy_action.triggered.connect(self.copy_to_clipboard)
        self.toolbar.addAction(copy_action)

        # Save to file button
        save_action = QAction('Save to File', self)
        save_action.triggered.connect(self.save_to_file)
        self.toolbar.addAction(save_action)

    def create_main_ui(self) -> None:
        # Main splitter
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left pane - File tree
        self.file_tree = FileTree()
        self.main_splitter.addWidget(self.file_tree)

        # Right pane - Preview and controls
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # Token counter
        token_layout = QHBoxLayout()
        token_layout.addWidget(QLabel('Estimated Token Count:'))
        self.token_count = QLabel('0')
        token_layout.addWidget(self.token_count)
        token_layout.addStretch()
        right_layout.addLayout(token_layout)

        # Preview text area
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        font = QFont('Menlo', 11)  # Use a monospace font
        self.preview.setFont(font)
        right_layout.addWidget(self.preview)

        # Create button layout
        button_layout = QHBoxLayout()

        # Add select all / deselect all buttons
        select_all_btn = QPushButton('Select All Files')
        select_all_btn.clicked.connect(self.select_all_files)
        button_layout.addWidget(select_all_btn)

        deselect_all_btn = QPushButton('Deselect All')
        deselect_all_btn.clicked.connect(self.deselect_all_files)
        button_layout.addWidget(deselect_all_btn)

        right_layout.addLayout(button_layout)

        self.main_splitter.addWidget(right_widget)

        # Set initial sizes
        self.main_splitter.setSizes([300, 700])

    def create_statusbar(self) -> None:
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage('Ready')

    def open_directory(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(self, 'Select Directory')
        if dir_path:
            self.current_dir = dir_path
            self.file_tree.model.load_directory(dir_path)
            self.statusBar.showMessage(f'Directory: {dir_path}')
            self.setWindowTitle(f'Context Builder - {os.path.basename(dir_path)}')

    def toggle_hidden_files(self, state: int) -> None:
        self.file_tree.model.ignore_hidden = not bool(state)
        if self.current_dir:
            self.file_tree.model.load_directory(self.current_dir)

    def toggle_gitignore(self, state: int) -> None:
        self.file_tree.model.ignore_gitignore = bool(state)
        if self.current_dir:
            self.file_tree.model.load_directory(self.current_dir)

    def toggle_line_numbers(self, state: int) -> None:
        self.include_line_numbers = bool(state)
        self.update_preview()

    def toggle_project_tree(self, state: int) -> None:
        self.include_project_tree = bool(state)
        self.update_preview()

    def select_all_files(self) -> None:
        # Set all checkboxes to checked
        root_item = self.file_tree.model.invisibleRootItem()
        for row in range(root_item.rowCount()):
            item = root_item.child(row)
            if item is not None:
                self.file_tree.set_check_state_recursive(item, True)
        self.update_preview()

    def deselect_all_files(self) -> None:
        # Set all checkboxes to unchecked
        root_item = self.file_tree.model.invisibleRootItem()
        for row in range(root_item.rowCount()):
            item = root_item.child(row)
            if item is not None:
                self.file_tree.set_check_state_recursive(item, False)
        self.update_preview()

    def update_preview(self) -> None:
        checked_files = self.file_tree.get_checked_files()

        if not checked_files:
            self.preview.setText('No files selected.')
            self.token_count.setText('0')
            return

        output_format = self.format_combo.currentText().lower()
        preview_text = self.generate_output(checked_files, output_format)

        # Update token count
        tokens = estimate_tokens(preview_text)
        self.token_count.setText(str(tokens))

        # Update preview
        self.preview.setText(preview_text)

    def generate_output(self, file_paths: List[str], output_format: str) -> str:
        result: List[str] = []
        global_index = 1

        # Include project structure tree if enabled
        if self.include_project_tree and self.current_dir:
            # Add project structure header based on format
            if output_format == 'xml':
                result.append('<documents>')
                result.append('<document index="0">')
                result.append('<source>PROJECT_STRUCTURE</source>')
                result.append('<document_content>')

            elif output_format == 'markdown':
                result.append('PROJECT_STRUCTURE')
                result.append('```')

            else:  # Plain text
                result.append('PROJECT_STRUCTURE')
                result.append('---')

            # Generate the tree structure
            gitignore_rules: List[str] = []
            if not self.file_tree.model.ignore_gitignore:
                gitignore_rules = self.file_tree.model.gitignore_rules

            tree_lines = generate_project_tree(
                self.current_dir,
                ignore_hidden=self.file_tree.model.ignore_hidden,
                gitignore_rules=gitignore_rules,
            )

            # Add base directory name as the root
            base_dir = os.path.basename(self.current_dir)
            tree_text = base_dir + '\n' + '\n'.join(tree_lines)
            result.append(tree_text)

            # Close the structure section based on format
            if output_format == 'xml':
                result.append('</document_content>')
                result.append('</document>')

            elif output_format == 'markdown':
                result.append('```')
                result.append('')

            else:  # Plain text
                result.append('')
                result.append('---')
                result.append('')

        # Start document wrapper if needed
        if output_format == 'xml' and not self.include_project_tree:
            # Only add the opening tag if we haven't already added it with the project tree
            result.append('<documents>')

        for path in file_paths:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()

                if self.include_line_numbers:
                    content = add_line_numbers(content)

                # Plain Text format
                if output_format == 'plain text':
                    result.append(path)
                    result.append('---')
                    result.append(content)
                    result.append('')
                    result.append('---')

                # XML-ish format
                elif output_format == 'xml':
                    result.append(f'<document index="{global_index}">')
                    result.append(f'<source>{path}</source>')
                    result.append('<document_content>')
                    result.append(content)
                    result.append('</document_content>')
                    result.append('</document>')
                    global_index += 1

                # Markdown format
                elif output_format == 'markdown':
                    lang = EXT_TO_LANG.get(path.split('.')[-1], '')
                    result.append(path)
                    result.append(f'```{lang}')
                    result.append(content)
                    result.append('```')

            except UnicodeDecodeError:
                result.append(f'# Warning: Skipping file {path} due to UnicodeDecodeError')

        # End document wrapper if needed
        if output_format == 'xml':
            result.append('</documents>')

        return '\n'.join(result)

    def schedule_update(self) -> None:
        # Debounce the update to prevent multiple rapid updates
        self.update_timer.start(300)  # 300ms debounce time

    def restore_status_message(self) -> None:
        """Restore the status bar to show the current directory"""
        if self.current_dir:
            self.statusBar.showMessage(f'Directory: {self.current_dir}')
        else:
            self.statusBar.showMessage('Ready')

    def show_temporary_message(self, message: str, timeout: int = 3000) -> None:
        """Show a temporary message and then restore directory path"""
        self.statusBar.showMessage(message, timeout)
        self.status_timer.start(timeout + 100)  # Add a small delay to ensure message is shown

    def copy_to_clipboard(self) -> None:
        if self.preview.toPlainText():
            clipboard = QApplication.clipboard()
            clipboard.setText(self.preview.toPlainText())
            self.show_temporary_message('Copied to clipboard', 3000)

    def save_to_file(self) -> None:
        if not self.preview.toPlainText():
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            'Save Context',
            '',
            'Text Files (*.txt);;XML Files (*.xml);;Markdown Files (*.md);;All Files (*)',
        )

        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.preview.toPlainText())
                self.show_temporary_message(f'Saved to {file_path}', 3000)
            except Exception as e:
                self.show_temporary_message(f'Error saving file: {str(e)}', 5000)


def signal_handler(_sig: int, _frame: Any) -> None:
    """Handle SIGINT (Ctrl+C) signal to gracefully close the application"""
    QApplication.quit()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName('Context Builder')

    # Set up signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)

    window = ContextBuilder()
    window.show()

    # If a directory was passed as argument, open it
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
        window.current_dir = sys.argv[1]
        window.file_tree.model.load_directory(sys.argv[1])
        window.setWindowTitle(f'Context Builder - {os.path.basename(sys.argv[1])}')
        window.statusBar.showMessage(f'Directory: {sys.argv[1]}')

    # Create a timer to allow Python to process SIGINT
    # This is needed because Qt's event loop doesn't let Python check for signals frequently
    timer = QTimer()
    timer.start(500)  # 500ms interval
    timer.timeout.connect(lambda: None)  # Just wake up Python interpreter

    sys.exit(app.exec())


if __name__ == '__main__':
    main()

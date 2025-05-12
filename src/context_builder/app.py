"""
Context Builder - A native macOS app for building context files for LLMs
"""

import os
import sys
import signal
from fnmatch import fnmatch
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QSplitter, QTreeView, QTextEdit,
    QVBoxLayout, QHBoxLayout, QWidget, QCheckBox, QLabel,
    QPushButton, QFileDialog, QComboBox, QStatusBar, QToolBar, QStyle
)
from PyQt6.QtCore import Qt, QDir, QModelIndex, QSize
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QFont, QAction, QIcon

EXT_TO_LANG = {
    "py": "python",
    "c": "c",
    "cpp": "cpp",
    "java": "java",
    "js": "javascript",
    "ts": "typescript",
    "html": "html",
    "css": "css",
    "xml": "xml",
    "json": "json",
    "yaml": "yaml",
    "yml": "yaml",
    "sh": "bash",
    "rb": "ruby",
    "kt": "kotlin",
    "go": "go",
    "php": "php",
    "swift": "swift",
    "sql": "sql",
    "tsx": "typescript",
}

def should_ignore(path, gitignore_rules):
    for rule in gitignore_rules:
        if fnmatch(os.path.basename(path), rule):
            return True
        if os.path.isdir(path) and fnmatch(os.path.basename(path) + "/", rule):
            return True
    return False

def read_gitignore(path):
    gitignore_path = os.path.join(path, ".gitignore")
    if os.path.isfile(gitignore_path):
        with open(gitignore_path, "r") as f:
            return [
                line.strip() for line in f if line.strip() and not line.startswith("#")
            ]
    return []

def add_line_numbers(content):
    lines = content.splitlines()
    padding = len(str(len(lines)))
    numbered_lines = [f"{i + 1:{padding}}  {line}" for i, line in enumerate(lines)]
    return "\n".join(numbered_lines)

def estimate_tokens(text):
    """Estimate token count using a simple heuristic"""
    # GPT models use roughly 4 characters per token on average
    return len(text) // 4

class FileTreeModel(QStandardItemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(["Files"])
        self.ignore_hidden = True
        self.ignore_gitignore = False
        self.file_extensions = []
        self.ignore_patterns = []
        self.gitignore_rules = []
        
    def load_directory(self, path):
        self.clear()
        self.setHorizontalHeaderLabels(["Files"])
        if not self.ignore_gitignore:
            self.gitignore_rules = read_gitignore(path)
        
        root_item = self.invisibleRootItem()
        self._load_directory_recursive(path, root_item)
        
    def _load_directory_recursive(self, path, parent_item):
        dir_entries = []
        
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
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | 
                         Qt.ItemFlag.ItemIsSelectable | 
                         Qt.ItemFlag.ItemIsUserCheckable)
            
            if is_dir:
                # Recursively load subdirectories
                self._load_directory_recursive(full_path, item)
                
            dir_entries.append((entry, item, is_dir))
        
        # Sort directories first, then files
        for entry, item, is_dir in sorted(dir_entries, key=lambda x: (not x[2], x[0].lower())):
            parent_item.appendRow(item)

class FileTree(QTreeView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = FileTreeModel()
        self.setModel(self.model)
        self.setSelectionMode(QTreeView.SelectionMode.SingleSelection)
        
        # Critical: Allow clicking on checkboxes
        self.setMouseTracking(True)
        
        # Handle clicks properly
        self.clicked.connect(self.item_clicked)
        
    def mousePressEvent(self, event):
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
        
    def item_clicked(self, index):
        # This will handle non-checkbox area clicks
        item = self.model.itemFromIndex(index)
        # Do other click handling here (but not checkbox toggling)
        # For example, you might want to expand/collapse folders
        
    def set_check_state_recursive(self, item, checked):
        check_state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        item.setCheckState(check_state)
        
        # Apply to all children
        for row in range(item.rowCount()):
            child = item.child(row)
            self.set_check_state_recursive(child, checked)
        
        # Force UI update
        self.viewport().update()
            
    def get_checked_files(self):
        checked_files = []
        self._get_checked_files_recursive(self.model.invisibleRootItem(), checked_files)
        return checked_files
        
    def _get_checked_files_recursive(self, item, checked_files):
        if item.isCheckable() and item.checkState() == Qt.CheckState.Checked:
            path = item.data(Qt.ItemDataRole.UserRole)
            if path and os.path.isfile(path):
                checked_files.append(path)
        
        # Check children
        for row in range(item.rowCount()):
            child = item.child(row)
            self._get_checked_files_recursive(child, checked_files)

class ContextBuilder(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Context Builder")
        self.setMinimumSize(1000, 700)
        
        # Init UI components
        self.create_toolbar()
        self.create_main_ui()
        self.create_statusbar()
        
        # Set the central widget
        self.setCentralWidget(self.main_splitter)
        
        # Variables
        self.current_dir = None
        self.output_format = "xml"
        self.include_line_numbers = False
        
        # Connect checkbox signals
        # Create a timer for debounced updates (to avoid too many updates while checking boxes)
        from PyQt6.QtCore import QTimer
        self.update_timer = QTimer()
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.update_preview)
        
        # Connect file tree model's data changed signal
        self.file_tree.model.dataChanged.connect(self.schedule_update)
        
    def create_toolbar(self):
        self.toolbar = QToolBar("Main Toolbar")
        self.toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(self.toolbar)
        
        # Open directory button
        open_action = QAction("Open Folder", self)
        open_action.triggered.connect(self.open_directory)
        self.toolbar.addAction(open_action)
        
        self.toolbar.addSeparator()
        
        # Format selection
        self.format_combo = QComboBox()
        self.format_combo.addItems(["XML", "Markdown", "Plain Text"])
        self.format_combo.currentTextChanged.connect(self.update_preview)
        self.toolbar.addWidget(QLabel("Format: "))
        self.toolbar.addWidget(self.format_combo)
        
        self.toolbar.addSeparator()
        
        # Line numbers checkbox
        self.line_numbers_check = QCheckBox("Line Numbers")
        self.line_numbers_check.stateChanged.connect(self.toggle_line_numbers)
        self.toolbar.addWidget(self.line_numbers_check)
        
        self.toolbar.addSeparator()
        
        # Filter options
        self.hidden_check = QCheckBox("Include Hidden")
        self.hidden_check.stateChanged.connect(self.toggle_hidden_files)
        self.toolbar.addWidget(self.hidden_check)
        
        self.gitignore_check = QCheckBox("Ignore .gitignore")
        self.gitignore_check.stateChanged.connect(self.toggle_gitignore)
        self.toolbar.addWidget(self.gitignore_check)
        
        self.toolbar.addSeparator()
        
        # Copy to clipboard button
        copy_action = QAction("Copy to Clipboard", self)
        copy_action.triggered.connect(self.copy_to_clipboard)
        self.toolbar.addAction(copy_action)
        
        # Save to file button
        save_action = QAction("Save to File", self)
        save_action.triggered.connect(self.save_to_file)
        self.toolbar.addAction(save_action)
        
    def create_main_ui(self):
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
        token_layout.addWidget(QLabel("Estimated Token Count:"))
        self.token_count = QLabel("0")
        token_layout.addWidget(self.token_count)
        token_layout.addStretch()
        right_layout.addLayout(token_layout)
        
        # Preview text area
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        font = QFont("Menlo", 11)  # Use a monospace font
        self.preview.setFont(font)
        right_layout.addWidget(self.preview)
        
        # Create button layout
        button_layout = QHBoxLayout()
        
        # Add select all / deselect all buttons
        select_all_btn = QPushButton("Select All Files")
        select_all_btn.clicked.connect(self.select_all_files)
        button_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(self.deselect_all_files)
        button_layout.addWidget(deselect_all_btn)
        
        right_layout.addLayout(button_layout)
        
        self.main_splitter.addWidget(right_widget)
        
        # Set initial sizes
        self.main_splitter.setSizes([300, 700])
        
    def create_statusbar(self):
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready")
        
    def open_directory(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Directory")
        if dir_path:
            self.current_dir = dir_path
            self.file_tree.model.load_directory(dir_path)
            self.statusBar.showMessage(f"Loaded directory: {dir_path}")
            self.setWindowTitle(f"Context Builder - {os.path.basename(dir_path)}")
            
    def toggle_hidden_files(self, state):
        self.file_tree.model.ignore_hidden = not bool(state)
        if self.current_dir:
            self.file_tree.model.load_directory(self.current_dir)
            
    def toggle_gitignore(self, state):
        self.file_tree.model.ignore_gitignore = bool(state)
        if self.current_dir:
            self.file_tree.model.load_directory(self.current_dir)
            
    def toggle_line_numbers(self, state):
        self.include_line_numbers = bool(state)
        self.update_preview()
    
    def select_all_files(self):
        # Set all checkboxes to checked
        root_item = self.file_tree.model.invisibleRootItem()
        for row in range(root_item.rowCount()):
            item = root_item.child(row)
            self.file_tree.set_check_state_recursive(item, True)
        self.update_preview()
    
    def deselect_all_files(self):
        # Set all checkboxes to unchecked
        root_item = self.file_tree.model.invisibleRootItem()
        for row in range(root_item.rowCount()):
            item = root_item.child(row)
            self.file_tree.set_check_state_recursive(item, False)
        self.update_preview()
            
    def update_preview(self):
        checked_files = self.file_tree.get_checked_files()
        
        if not checked_files:
            self.preview.setText("No files selected.")
            self.token_count.setText("0")
            return
            
        output_format = self.format_combo.currentText().lower()
        preview_text = self.generate_output(checked_files, output_format)
        
        # Update token count
        tokens = estimate_tokens(preview_text)
        self.token_count.setText(str(tokens))
        
        # Update preview
        self.preview.setText(preview_text)
        
    def generate_output(self, file_paths, output_format):
        result = []
        global_index = 1
        
        # Start document wrapper if needed
        if output_format == "xml":
            result.append("<documents>")
            
        for path in file_paths:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                    
                if self.include_line_numbers:
                    content = add_line_numbers(content)
                
                # Plain Text format
                if output_format == "plain text":
                    result.append(path)
                    result.append("---")
                    result.append(content)
                    result.append("")
                    result.append("---")
                    
                # XML-ish format
                elif output_format == "xml":
                    result.append(f'<document index="{global_index}">')
                    result.append(f"<source>{path}</source>")
                    result.append("<document_content>")
                    result.append(content)
                    result.append("</document_content>")
                    result.append("</document>")
                    global_index += 1
                    
                # Markdown format
                elif output_format == "markdown":
                    lang = EXT_TO_LANG.get(path.split(".")[-1], "")
                    result.append(path)
                    result.append(f"```{lang}")
                    result.append(content)
                    result.append("```")
                    
            except UnicodeDecodeError:
                result.append(f"# Warning: Skipping file {path} due to UnicodeDecodeError")
                
        # End document wrapper if needed
        if output_format == "xml":
            result.append("</documents>")
            
        return "\n".join(result)
        
    def schedule_update(self):
        # Debounce the update to prevent multiple rapid updates
        self.update_timer.start(300)  # 300ms debounce time
    
    def copy_to_clipboard(self):
        if self.preview.toPlainText():
            clipboard = QApplication.clipboard()
            clipboard.setText(self.preview.toPlainText())
            self.statusBar.showMessage("Copied to clipboard", 3000)
            
    def save_to_file(self):
        if not self.preview.toPlainText():
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Context", "", 
            "Text Files (*.txt);;XML Files (*.xml);;Markdown Files (*.md);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(self.preview.toPlainText())
                self.statusBar.showMessage(f"Saved to {file_path}", 3000)
            except Exception as e:
                self.statusBar.showMessage(f"Error saving file: {str(e)}", 5000)

def signal_handler(sig, frame):
    """Handle SIGINT (Ctrl+C) signal to gracefully close the application"""
    QApplication.quit()

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Context Builder")

    # Set up signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)

    window = ContextBuilder()
    window.show()

    # If a directory was passed as argument, open it
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
        window.current_dir = sys.argv[1]
        window.file_tree.model.load_directory(sys.argv[1])
        window.setWindowTitle(f"Context Builder - {os.path.basename(sys.argv[1])}")

    # Create a timer to allow Python to process SIGINT
    # This is needed because Qt's event loop doesn't let Python check for signals frequently
    from PyQt6.QtCore import QTimer
    timer = QTimer()
    timer.start(500)  # 500ms interval
    timer.timeout.connect(lambda: None)  # Just wake up Python interpreter

    sys.exit(app.exec())

if __name__ == "__main__":
    main()

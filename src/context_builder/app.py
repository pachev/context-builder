"""
Context Builder TUI — built with Textual.

Browse project files, select what to include, generate formatted context for LLMs.
"""

import os
import sys
import subprocess
from typing import Optional

from textual import work
from rich.text import Text
from textual.app import App, ComposeResult
from textual.timer import Timer
from textual.binding import Binding
from textual.message import Message
from textual.widgets import (
    Rule,
    Tree,
    Label,
    Button,
    Footer,
    Header,
    Select,
    Static,
    Switch,
    TextArea,
)
from textual.reactive import reactive
from textual.containers import Vertical, Horizontal
from textual.widgets.tree import TreeNode

from context_builder.utils import (
    should_ignore,
    read_gitignore,
    estimate_tokens,
    generate_output,
    is_likely_binary_file,
)

# --- Custom File Tree Widget ---

CHECKED = '☑ '
UNCHECKED = '☐ '
FOLDER_OPEN = '📂 '
FOLDER_CLOSED = '📁 '
FILE_ICON = '📄 '


class CheckboxFileTree(Tree[dict]):
    """File tree with checkbox toggling and lazy loading."""

    class CheckChanged(Message):
        """Posted when any checkbox changes."""

    def __init__(self, path: str, **kwargs) -> None:
        label = os.path.basename(os.path.abspath(path))
        super().__init__(label, **kwargs)
        self.root_path = os.path.abspath(path)
        self.ignore_hidden = True
        self.use_gitignore = True
        self.gitignore_rules: list[str] = []

    def on_mount(self) -> None:
        self.load_directory()

    def load_directory(self) -> None:
        """Reload the tree from the root path."""
        self.clear()
        self.gitignore_rules = read_gitignore(self.root_path) if self.use_gitignore else []
        self.root.data = {'path': self.root_path, 'checked': False, 'is_dir': True, 'loaded': True}
        self._load_children(self.root_path, self.root)
        self.root.expand()

    def _load_children(self, path: str, parent_node: TreeNode) -> None:
        """Load immediate children of a directory node."""
        try:
            entries = os.listdir(path)
        except (PermissionError, FileNotFoundError):
            return

        items: list[tuple[str, str, bool]] = []
        for entry in entries:
            full_path = os.path.join(path, entry)
            if self.ignore_hidden and entry.startswith('.'):
                continue
            if self.use_gitignore and self.gitignore_rules and should_ignore(full_path, self.gitignore_rules):
                continue
            try:
                is_dir = os.path.isdir(full_path)
            except OSError:
                continue
            if not is_dir and is_likely_binary_file(full_path):
                continue
            items.append((entry, full_path, is_dir))

        items.sort(key=lambda x: (not x[2], x[0].lower()))

        for entry_name, full_path, is_dir in items:
            node_data = {'path': full_path, 'checked': False, 'is_dir': is_dir, 'loaded': False}
            if is_dir:
                node = parent_node.add(entry_name, data=node_data, expand=False, allow_expand=True)
                # Add a placeholder so the expand arrow shows
                node.add_leaf('...', data=None)
            else:
                parent_node.add_leaf(entry_name, data=node_data)

    def _on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        """Lazy-load children when a directory is expanded."""
        node = event.node
        if node.data and node.data.get('is_dir') and not node.data.get('loaded'):
            node.data['loaded'] = True
            # Remove placeholder
            node.remove_children()
            self._load_children(node.data['path'], node)

    def render_label(self, node: TreeNode, _base_style, style) -> Text:
        """Render checkbox prefix on each node."""
        if node.data is None:
            return Text('...')

        checked = node.data.get('checked', False)
        is_dir = node.data.get('is_dir', False)
        check_mark = CHECKED if checked else UNCHECKED

        if is_dir:
            icon = FOLDER_OPEN if node.is_expanded else FOLDER_CLOSED
        else:
            icon = FILE_ICON

        label = Text.assemble(
            (check_mark, 'bold green' if checked else 'dim'),
            (icon, ''),
            (str(node.label), style),
        )
        return label

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Toggle check state on selection."""
        node = event.node
        if node.data is None:
            return
        new_state = not node.data.get('checked', False)
        self._set_checked_recursive(node, new_state)
        self.post_message(self.CheckChanged())

    def _set_checked_recursive(self, node: TreeNode, checked: bool) -> None:
        """Set check state for node and all children."""
        if node.data is not None:
            node.data['checked'] = checked
        # If it's a directory that hasn't been loaded yet, load it first
        if node.data and node.data.get('is_dir') and not node.data.get('loaded'):
            node.data['loaded'] = True
            node.remove_children()
            self._load_children(node.data['path'], node)
        for child in node.children:
            self._set_checked_recursive(child, checked)
        node.refresh()

    def get_checked_files(self) -> list[str]:
        """Return list of checked file paths."""
        files: list[str] = []
        self._collect_checked(self.root, files)
        return files

    def _collect_checked(self, node: TreeNode, files: list[str]) -> None:
        if node.data and node.data.get('checked') and not node.data.get('is_dir'):
            files.append(node.data['path'])
        for child in node.children:
            self._collect_checked(child, files)

    def select_all(self) -> None:
        self._set_checked_recursive(self.root, True)
        self.post_message(self.CheckChanged())

    def deselect_all(self) -> None:
        self._set_checked_recursive(self.root, False)
        self.post_message(self.CheckChanged())


# --- Main App ---

FORMAT_OPTIONS = [('XML', 'xml'), ('Markdown', 'markdown'), ('Plain Text', 'plaintext')]


class ContextBuilderApp(App):
    """Context Builder TUI application."""

    TITLE = 'Context Builder'

    CSS = """
    #sidebar {
        width: 38;
        height: 100%;
        padding: 0 1;
    }

    #sidebar-options {
        height: auto;
        padding: 0;
    }

    .option-row {
        height: 3;
        align: left middle;
        padding: 0;
    }

    .option-label {
        width: 20;
        padding: 0 1;
    }

    .option-switch {
        width: auto;
    }

    #format-select {
        width: 100%;
        margin: 0 0 1 0;
    }

    #file-tree {
        height: 1fr;
        border: solid $primary-background;
    }

    #tree-buttons {
        height: 3;
        align: center middle;
        padding: 0;
    }

    #tree-buttons Button {
        margin: 0 1;
    }

    #main-content {
        height: 100%;
        padding: 0 1;
    }

    #instructions-label {
        margin: 0;
        text-style: bold;
    }

    #instructions {
        height: 5;
        margin: 0 0 1 0;
    }

    #preview-header {
        height: 1;
        margin: 0;
    }

    #preview-label {
        text-style: bold;
    }

    #token-count {
        text-style: bold;
        color: $success;
        margin: 0 0 0 2;
    }

    #preview {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding('c', 'copy_clipboard', 'Copy', show=True),
        Binding('ctrl+s', 'save_file', 'Save', show=True),
        Binding('a', 'select_all', 'Select All', show=True, priority=True),
        Binding('d', 'deselect_all', 'Deselect All', show=True, priority=True),
        Binding('q', 'quit', 'Quit', show=True),
    ]

    output_format: reactive[str] = reactive('xml')

    def __init__(self, path: Optional[str] = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.project_path = os.path.abspath(path) if path else os.getcwd()
        self._update_timer: Optional[Timer] = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id='sidebar'):
                with Vertical(id='sidebar-options'):
                    yield Select(FORMAT_OPTIONS, value='xml', id='format-select', allow_blank=False)
                    with Horizontal(classes='option-row'):
                        yield Switch(value=False, id='line-nums', classes='option-switch')
                        yield Label('Line Numbers', classes='option-label')
                    with Horizontal(classes='option-row'):
                        yield Switch(value=False, id='proj-tree', classes='option-switch')
                        yield Label('Project Tree', classes='option-label')
                    with Horizontal(classes='option-row'):
                        yield Switch(value=False, id='hidden', classes='option-switch')
                        yield Label('Hidden Files', classes='option-label')
                    with Horizontal(classes='option-row'):
                        yield Switch(value=True, id='gitignore', classes='option-switch')
                        yield Label('Use .gitignore', classes='option-label')
                yield Rule()
                yield CheckboxFileTree(self.project_path, id='file-tree')
                with Horizontal(id='tree-buttons'):
                    yield Button('Select All', id='sel-all', variant='default')
                    yield Button('Deselect', id='desel-all', variant='default')
            with Vertical(id='main-content'):
                yield Label('Custom Instructions', id='instructions-label')
                yield TextArea(id='instructions')
                yield Rule()
                with Horizontal(id='preview-header'):
                    yield Static('Preview', id='preview-label')
                    yield Static('Tokens: 0', id='token-count')
                yield TextArea(id='preview', read_only=True)
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self.project_path
        preview = self.query_one('#preview', TextArea)
        preview.language = 'xml'

    # --- Event Handlers ---

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == 'format-select' and event.value is not None:
            self.output_format = str(event.value)
            preview = self.query_one('#preview', TextArea)
            lang_map = {'xml': 'xml', 'markdown': 'markdown', 'plaintext': None}
            preview.language = lang_map.get(self.output_format)
            self.schedule_update()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        switch_id = event.switch.id
        if switch_id in ('hidden', 'gitignore'):
            tree = self.query_one('#file-tree', CheckboxFileTree)
            tree.ignore_hidden = not self.query_one('#hidden', Switch).value
            tree.use_gitignore = self.query_one('#gitignore', Switch).value
            tree.load_directory()
            self.schedule_update()
        elif switch_id in ('line-nums', 'proj-tree'):
            self.schedule_update()

    def on_checkbox_file_tree_check_changed(self, _event: CheckboxFileTree.CheckChanged) -> None:
        self.schedule_update()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == 'instructions':
            self.schedule_update()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        tree = self.query_one('#file-tree', CheckboxFileTree)
        if event.button.id == 'sel-all':
            tree.select_all()
        elif event.button.id == 'desel-all':
            tree.deselect_all()

    # --- Actions ---

    def action_select_all(self) -> None:
        self.query_one('#file-tree', CheckboxFileTree).select_all()

    def action_deselect_all(self) -> None:
        self.query_one('#file-tree', CheckboxFileTree).deselect_all()

    def action_copy_clipboard(self) -> None:
        preview = self.query_one('#preview', TextArea)
        text = preview.text
        if not text.strip():
            self.notify('Nothing to copy', severity='warning')
            return
        try:
            # Try macOS pbcopy first, then xclip
            if sys.platform == 'darwin':
                subprocess.run(['pbcopy'], input=text.encode('utf-8'), check=True)
            else:
                subprocess.run(['xclip', '-selection', 'clipboard'], input=text.encode('utf-8'), check=True)
            self.notify('Copied to clipboard!')
        except (FileNotFoundError, subprocess.CalledProcessError):
            self.notify('Clipboard not available', severity='error')

    def action_save_file(self) -> None:
        preview = self.query_one('#preview', TextArea)
        text = preview.text
        if not text.strip():
            self.notify('Nothing to save', severity='warning')
            return
        ext_map = {'xml': '.xml', 'markdown': '.md', 'plaintext': '.txt'}
        ext = ext_map.get(self.output_format, '.txt')
        base_name = os.path.basename(self.project_path)
        filename = f'{base_name}_context{ext}'
        filepath = os.path.join(self.project_path, filename)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(text)
            self.notify(f'Saved to {filename}')
        except OSError as e:
            self.notify(f'Error saving: {e}', severity='error')

    # --- Preview Update ---

    def schedule_update(self) -> None:
        """Debounced preview update."""
        if self._update_timer is not None:
            try:
                self._update_timer.stop()
            except Exception:
                pass
        self._update_timer = self.set_timer(0.3, self._do_update)

    @work(thread=True)
    def _do_update(self) -> None:
        """Generate output in a worker thread."""
        tree = self.query_one('#file-tree', CheckboxFileTree)
        checked_files = tree.get_checked_files()
        include_proj_tree = self.query_one('#proj-tree', Switch).value
        include_line_nums = self.query_one('#line-nums', Switch).value
        instructions_area = self.query_one('#instructions', TextArea)
        custom_instructions = instructions_area.text

        if not checked_files and not include_proj_tree:
            self.call_from_thread(self._set_preview, 'Select files to build context.', 0)
            return

        output = generate_output(
            file_paths=checked_files,
            output_format=self.output_format,
            include_line_numbers=include_line_nums,
            include_project_tree=include_proj_tree,
            base_dir=self.project_path,
            ignore_hidden=tree.ignore_hidden,
            gitignore_rules=tree.gitignore_rules,
            custom_instructions=custom_instructions,
        )

        tokens = estimate_tokens(output)
        self.call_from_thread(self._set_preview, output, tokens)

    def _set_preview(self, text: str, tokens: int) -> None:
        preview = self.query_one('#preview', TextArea)
        token_label = self.query_one('#token-count', Static)
        preview.load_text(text)
        token_label.update(f'Tokens: {tokens:,}')


def main(path: Optional[str] = None) -> None:
    """Run the Context Builder TUI."""
    app = ContextBuilderApp(path=path)
    app.run()


if __name__ == '__main__':
    main()

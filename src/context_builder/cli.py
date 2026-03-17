"""
Command-line launcher for Context Builder.
"""

import os
import sys


def main() -> None:
    """Main entry point — parses path argument and launches TUI."""
    from context_builder.app import main as app_main

    path = '.'
    if len(sys.argv) > 1:
        path = sys.argv[1]

    if path == '.':
        path = os.getcwd()
    else:
        path = os.path.abspath(path)

    if not os.path.isdir(path):
        print(f'Error: Not a directory: {path}')
        sys.exit(1)

    app_main(path=path)


if __name__ == '__main__':
    main()

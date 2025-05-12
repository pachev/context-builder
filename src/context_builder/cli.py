"""
Command-line launcher for Context Builder
"""

import os
import sys


def main() -> None:
    """
    Main entry point for the command-line interface.
    Handles command-line arguments and launches the GUI application.
    """
    # Check for arguments
    if len(sys.argv) > 1:
        # Convert relative path to absolute path if needed
        path = sys.argv[1]
        if path == '.':
            path = os.getcwd()
        else:
            path = os.path.abspath(path)

        # Ensure the path exists
        if not os.path.exists(path):
            print(f'Error: Path does not exist: {path}')
            sys.exit(1)

        # Launch the GUI application with the specified path
        try:
            # Import our own app module and run it
            from context_builder.app import main as app_main

            # Modify sys.argv to pass the path to the app
            sys.argv = [sys.argv[0], path]
            app_main()
        except ImportError as e:
            print(f'Error: Could not import the application module: {e}')
            sys.exit(1)
    else:
        # No arguments, just launch the app
        try:
            from context_builder.app import main as app_main

            app_main()
        except ImportError as e:
            print(f'Error: Could not import the application module: {e}')
            sys.exit(1)


if __name__ == '__main__':
    main()

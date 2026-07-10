"""CLI entry point for Bull Run."""

import sys
from pathlib import Path

import streamlit.web.cli as stcli


def main():
    """Launch the Bull Run Streamlit app."""
    app_path = str(Path(__file__).parent / "app.py")
    sys.exit(stcli.main(["run", app_path, *sys.argv[1:]]))


if __name__ == "__main__":
    main()

import sys

from snapscript.interfaces.cli import main

# uv run python -m snapscript -> official package execution method
# executing package/module -> find snapscript/__main__.py and run it
if __name__ == "__main__":
    sys.exit(main())

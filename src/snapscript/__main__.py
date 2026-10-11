import sys

from snapscript.interfaces.cli import main

# uv run python -m snapscript -> official package execution method
# executing package/module -> find snapscript/__main__.py and run it
# ex: uv run python -m snapscript "Keep orders over 1000" --file orders.csv --output out.csv
if __name__ == "__main__":
    sys.exit(main())

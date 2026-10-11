'''
CLI entrypoint wrapper (dev mode)

uv run python main.py "task" --file orders.csv ...

interfaces.cli.main
'''

import sys

from snapscript.interfaces.cli import main

# uv run python main.py
if __name__ == "__main__":
    sys.exit(main())

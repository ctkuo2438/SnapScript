import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="snapscript",
        description="Generate and run local Python scripts for CSV/Excel tasks.",
    )
    parser.add_argument("task", nargs="?", help="Natural-language data processing task.")
    return parser


def main() -> None:
    parser = build_parser()
    parser.parse_args()

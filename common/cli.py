"""Wspólny interfejs CLI wszystkich ingestów: --project, --dataset, --start/--lookback-days, --end."""

import argparse
from datetime import date, timedelta


def make_parser(description: str, default_dataset: str) -> argparse.ArgumentParser:
    """Parser ze wspólnymi argumentami; zwracany, żeby źródło mogło dodać swoje przed parsowaniem."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--project", required=True, help="ID projektu GCP")
    parser.add_argument("--dataset", default=default_dataset)
    parser.add_argument("--end", type=date.fromisoformat, default=date.today())
    start_group = parser.add_mutually_exclusive_group(required=True)
    start_group.add_argument("--start", type=date.fromisoformat)
    start_group.add_argument("--lookback-days", type=int, help="start = end minus tyle dni")
    return parser


def parse(parser: argparse.ArgumentParser, argv: list[str] | None = None) -> argparse.Namespace:
    """Parsuje i zamienia --lookback-days na --start."""
    args = parser.parse_args(argv)
    if args.lookback_days is not None:
        if args.lookback_days < 0:
            parser.error("--lookback-days nie może być ujemne")
        args.start = args.end - timedelta(days=args.lookback_days)
    return args

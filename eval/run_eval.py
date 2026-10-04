"""Run the pipeline over a question set and report execution accuracy.

From the repo root, with the backend's virtual environment active and
.env filled in (the model must be reachable):

    python eval/run_eval.py                    # test questions, no retrieval
    python eval/run_eval.py --retrieval        # same questions, with retrieval
    python eval/run_eval.py --limit 5          # quick smoke run
    python eval/run_eval.py --ids t47          # rerun one question, e.g. after an outage
    python eval/run_eval.py --check-gold       # run only the gold SQL, no model

Each run writes eval/results/<time>-<mode>.jsonl (one line per question)
and a .summary.json next to it. eval/results/ is gitignored; copy the
summary numbers into docs/decisions.md when they settle a decision.

Gold SQL runs through the same validator and read-only connection as the
app, so the comparison is like for like.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from eval.metrics import exact_match, lenient_match, summarize_run  # noqa: E402
from nl2sql.config import load_settings  # noqa: E402
from nl2sql.db import DatabaseError  # noqa: E402
from nl2sql.execute import execute  # noqa: E402
from nl2sql.llm import LLMError  # noqa: E402
from nl2sql.pipeline import answer_question  # noqa: E402
from nl2sql.schema import get_schema  # noqa: E402
from nl2sql.validate import validate_sql  # noqa: E402

DEFAULT_DATASET = ROOT / "eval" / "datasets" / "pagila_v1.jsonl"
RESULTS = ROOT / "eval" / "results"


def load(path: Path, split: str) -> list[dict[str, Any]]:
    items = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [i for i in items if split == "all" or i["split"] == split]


def run_gold(item: dict[str, Any], settings, schema) -> list[tuple]:
    query = validate_sql(item["sql"], allowed_tables=schema.allowed_tables)
    return execute(query, settings).rows


def check_gold(items: list[dict[str, Any]], settings, schema) -> int:
    """Run every gold query; report any that fail or return nothing."""
    problems = 0
    for item in items:
        try:
            rows = run_gold(item, settings, schema)
        except Exception as exc:  # noqa: BLE001 - report every kind of failure
            print(f"FAIL {item['id']}: {exc}")
            problems += 1
            continue
        flag = "" if rows else "  <- returns no rows"
        print(f"ok   {item['id']}: {len(rows)} row(s){flag}")
    print(f"\n{len(items) - problems} of {len(items)} gold queries ran.")
    return 1 if problems else 0


def evaluate(item: dict[str, Any], settings, schema, retriever) -> dict[str, Any]:
    gold = run_gold(item, settings, schema)
    record = {
        "id": item["id"],
        "difficulty": item["difficulty"],
        "question": item["question"],
        "gold_sql": item["sql"],
        "exact": False,
        "lenient": False,
    }
    started = time.perf_counter()
    try:
        answer = answer_question(
            item["question"], settings, schema, retriever=retriever
        )
    except (LLMError, DatabaseError) as exc:
        return record | {"status": "outage", "error": str(exc), "seconds": None}
    seconds = round(time.perf_counter() - started, 2)
    record |= {
        "sql": answer.sql,
        "attempts": answer.attempts,
        "seconds": seconds,
        "used_retrieval": answer.used_retrieval,
    }
    if answer.error is not None:
        return record | {"status": answer.error_code, "error": answer.error}
    ordered = bool(item.get("ordered"))
    return record | {
        "status": "ok",
        "exact": exact_match(gold, answer.rows, ordered),
        "lenient": lenient_match(gold, answer.rows, ordered),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--split", choices=["test", "train", "all"], default="test")
    parser.add_argument(
        "--retrieval", action="store_true", help="use the vector retriever"
    )
    parser.add_argument("--limit", type=int, help="only the first N questions")
    parser.add_argument(
        "--ids", help="only these question ids, comma separated, e.g. t47,t50"
    )
    parser.add_argument(
        "--check-gold", action="store_true", help="run gold SQL only; no model calls"
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    schema = get_schema(settings)
    items = load(args.dataset, args.split)
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",")}
        items = [i for i in items if i["id"] in wanted]
    items = items[: args.limit]
    if args.check_gold:
        return check_gold(items, settings, schema)

    retriever = None
    if args.retrieval:
        from nl2sql.retrieval.select import VectorRetriever

        retriever = VectorRetriever(settings)

    mode = "retrieval" if args.retrieval else "baseline"
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{stamp}-{mode}.jsonl"
    records = []
    with out.open("w", encoding="utf-8") as handle:
        for number, item in enumerate(items, start=1):
            record = evaluate(item, settings, schema, retriever)
            records.append(record)
            handle.write(json.dumps(record, default=str) + "\n")
            handle.flush()
            mark = "PASS" if record["lenient"] else record["status"].upper()
            print(f"[{number}/{len(items)}] {mark:12} {item['id']} {item['question']}")

    summary = summarize_run(records) | {
        "mode": mode,
        "model": settings.ollama_model,
        "dataset": args.dataset.name,
        "split": args.split,
    }
    out.with_suffix(".summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    print(f"\nPer-question results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

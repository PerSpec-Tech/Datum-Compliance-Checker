"""compile a clause file into a checked draft rule.

Usage:
  just compile-rule fixtures/clauses/udcpr-9.4.1-bath.txt [--review] [--save]

The clause file has YAML front-matter (authority, clause_ref, source) followed by the clause text,
copied from the source document. --save writes rules/drafts/<slug>.yaml for human review;
a person must check it against the source and set status: verified before moving it into a rule set.
"""

import sys
from pathlib import Path

import yaml

from compliance.agents.compiler import compile_clause, parse_clause_file, save_draft
from compliance.engine.rules import load_rulebase
from compliance.llm.client import LLMClient
from compliance.store.db import get_db
from compliance.store.repo import Store

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__)
        return 2
    clause = parse_clause_file(Path(args[0]))
    store = Store(get_db())
    result = compile_clause(
        clause, LLMClient(store), load_rulebase(), review="--review" in sys.argv
    )

    print(f"{'OK' if result.ok else 'FAILED'} after {result.attempts} attempt(s)")
    for i, errs in enumerate(result.history, 1):
        if errs:
            print(f"  attempt {i}: " + "; ".join(errs))
    if result.rule:
        print("\n" + yaml.safe_dump(result.rule, sort_keys=False, allow_unicode=True, width=100))
    for t in result.tables:
        print("table:\n" + yaml.safe_dump(t, sort_keys=False, allow_unicode=True, width=100))
    if result.notes:
        print("notes:", result.notes)
    if result.dry_run:
        print("dry run:", result.dry_run)
    for earlier in result.review_history:
        print(f"first review ({earlier['verdict']}) → revised by Super:")
        for n in earlier["notes"]:
            print("  -", n)
    if result.review:
        print(f"review ({result.review['verdict']}):")
        for n in result.review["notes"]:
            print("  -", n)
    if result.ok and "--save" in sys.argv:
        print("saved", save_draft(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""verify Tavily search + extract against Pune/Maharashtra government domains.

Usage: just smoke-tavily
"""

import json
import sys
from datetime import datetime

import yaml
from tavily import TavilyClient

from compliance.config import get_settings

QUERY = "UDCPR Maharashtra transit oriented development regulation Pune metro"
DCR_WORDS = ("regulation", "fsi", "development control", "udcpr", "notification", "building")


def main() -> int:
    s = get_settings()
    if not s.tavily_api_key:
        print("TAVILY_API_KEY is empty. Fill in .env first.")
        return 1
    authority = yaml.safe_load(
        (s.rules_dir / "cities" / "pmc" / "authority.yaml").read_text("utf-8")
    )
    domains = authority["tavily_domains"]

    client = TavilyClient(api_key=s.tavily_api_key)
    res = client.search(QUERY, include_domains=domains, max_results=8, search_depth="advanced")
    results = res.get("results", [])
    print(f"search: {len(results)} results (domains: {', '.join(domains)})")
    for r in results:
        print(f"  - {r['url']}\n      {r.get('title', '')[:90]}")

    gov = [r for r in results if any(d in r["url"] for d in domains)]
    extracted = {}
    if results:
        top = results[0]["url"]
        extracted = client.extract(urls=[top])
        text = " ".join(x.get("raw_content") or "" for x in extracted.get("results", []))
        hits = [w for w in DCR_WORDS if w in text.lower()]
        print(f"\nextract {top}: {len(text)} chars; development-control words found: {hits}")
    else:
        hits = []

    out = s.cache_dir / "tavily"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (out / f"smoke-{stamp}.json").write_text(
        json.dumps({"query": QUERY, "search": res, "extract": extracted}, indent=2),
        encoding="utf-8",
    )
    print(f"raw output saved to .cache/tavily/smoke-{stamp}.json")

    ok = len(gov) >= 3 and bool(hits)
    print("\nDONE CHECK:", "PASS" if ok else f"FAIL (gov results={len(gov)}, words={hits})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

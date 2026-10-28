"""extract source PDFs page by page and search them with BM25.

Usage:
  just extract-sources [--force]   extract manifest entries with index: true, then build the index
  just find-clause "<query>"       top 5 pages as "<doc_id> p.<printed> (pdf p.N)" with a snippet

Output: .cache/sources/<doc_id>/p<NNNN>.txt (PDF page numbers), _meta.json,
        and .cache/sources/index.pkl
"""

import hashlib
import json
import logging
import pickle
import re
import sys
from pathlib import Path

import yaml
from pypdf import PdfReader
from rank_bm25 import BM25Okapi

from compliance.config import REPO_ROOT, get_settings

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# Font-encoding warnings on NBC 2016 are harmless.
logging.getLogger("pypdf").setLevel(logging.ERROR)

OUT = get_settings().cache_dir / "sources"
INDEX = OUT / "index.pkl"
MANIFEST = REPO_ROOT / "sources" / "manifest.yaml"
GLYPH_HEX = re.compile(r"/G([0-9A-Fa-f]{2})")
TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)*")
LOW_TEXT = 50


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fix_text(text: str, fix: str | None) -> str:
    if fix == "glyph_hex":
        text = GLYPH_HEX.sub(lambda m: chr(int(m[1], 16)), text)
    return text


def tokens(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def extract(doc: dict, force: bool) -> None:
    path = REPO_ROOT / doc["file"]
    if not path.exists():
        print(f"[{doc['id']}] MISSING file {doc['file']}, skipped")
        return
    digest = sha256(path)
    if doc.get("sha256") and doc["sha256"] != digest:
        print(f"[{doc['id']}] WARNING sha256 mismatch: the file differs from the manifest")
    out = OUT / doc["id"]
    meta_path = out / "_meta.json"
    if not force and meta_path.exists() and json.loads(meta_path.read_text())["sha256"] == digest:
        print(f"[{doc['id']}] up to date, skipped (use --force to redo)")
        return

    reader = PdfReader(str(path))
    first, last = doc.get("pdf_pages") or (1, len(reader.pages))
    offset = doc.get("pdf_page_offset")
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("p*.txt"):
        old.unlink()
    pages, low = [], []
    for n in range(first, last + 1):
        text = fix_text(reader.pages[n - 1].extract_text() or "", doc.get("text_fix"))
        if len(text.strip()) < LOW_TEXT:
            low.append(n)
        (out / f"p{n:04d}.txt").write_text(text, encoding="utf-8")
        pages.append({"pdf": n, "printed": (n - offset) if offset and n > offset else None})
        if (n - first) % 200 == 0:
            print(f"[{doc['id']}] … page {n}/{last}", flush=True)
    meta = {"sha256": digest, "pages": pages, "low_text_pages": low}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    note = f"; {len(low)} pages probably scanned (need OCR): {low[:10]}" if low else ""
    print(f"[{doc['id']}] extracted {len(pages)} pages{note}")


def build_index(docs: list[dict]) -> None:
    entries, corpus = [], []
    for doc in docs:
        meta_path = OUT / doc["id"] / "_meta.json"
        if not meta_path.exists():
            continue
        for p in json.loads(meta_path.read_text())["pages"]:
            f = OUT / doc["id"] / f"p{p['pdf']:04d}.txt"
            entries.append(
                {"doc": doc["id"], "authority": doc.get("authority"), **p, "file": f.relative_to(REPO_ROOT).as_posix()}
            )
            corpus.append(tokens(f.read_text(encoding="utf-8")))
    INDEX.write_bytes(pickle.dumps({"entries": entries, "bm25": BM25Okapi(corpus)}))
    print(
        f"index: {len(entries)} pages from {len({e['doc'] for e in entries})} documents → {INDEX}"
    )


def snippet(text: str, q: list[str], width: int = 220) -> str:
    low = text.lower()
    pos = min((i for t in q if (i := low.find(t)) >= 0), default=0)
    s = text[max(0, pos - width // 3) : pos + width]
    return re.sub(r"\s+", " ", s).strip()


def find(query: str, k: int = 5) -> None:
    if not INDEX.exists():
        print("No index yet. Run: just extract-sources")
        sys.exit(1)
    data = pickle.loads(INDEX.read_bytes())
    q = tokens(query)
    scores = data["bm25"].get_scores(q)
    top = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
    for i in top:
        e = data["entries"][i]
        printed = f"p.{e['printed']} " if e["printed"] else ""
        text = (REPO_ROOT / e["file"]).read_text(encoding="utf-8")
        print(f"{e['doc']} {printed}(pdf p.{e['pdf']}) [{e['authority']}] score={scores[i]:.1f}")
        print(f"    {snippet(text, q)}")
        print(f"    file: {e['file']}")


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "find":
        find(" ".join(args[1:]))
        return
    docs = [
        d
        for d in yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["documents"]
        if d.get("index")
    ]
    for doc in docs:
        extract(doc, force="--force" in args)
    build_index(docs)


if __name__ == "__main__":
    main()

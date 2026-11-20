#!/usr/bin/env python3
"""Offline Codex handoff search. Keyword index by default; optional LOCAL semantic embeddings.
Never downloads models, calls an API, or uploads project content.
Usage:
  python3 docs/codex/index_local.py index
  python3 docs/codex/index_local.py search "rollback"
  python3 docs/codex/index_local.py index --model-dir /path/to/already-installed-embedding-model
  python3 docs/codex/index_local.py search "restore older working version" --model-dir /path/to/already-installed-embedding-model
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys

BASE = Path(__file__).resolve().parent
REPO = BASE.parents[1].name
DEFAULT_DB = Path.home() / ".cache" / "tihulu-codex" / REPO / "context.sqlite3"

def load_model(path):
    if not path:
        return None
    path = Path(path).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError("The embedding model must be an existing LOCAL directory.")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    from sentence_transformers import SentenceTransformer  # optional, preinstalled only
    return SentenceTransformer(str(path), local_files_only=True, trust_remote_code=False)

def encode(model, texts):
    values = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [list(map(float, x)) for x in values]

def rebuild(db_path, model):
    records = [json.loads(line) for line in (BASE / "KNOWLEDGE.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [x["id"] for x in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate knowledge IDs")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path))
    try:
        with connection:
            connection.execute("DROP TABLE IF EXISTS snippets")
            connection.execute("DROP TABLE IF EXISTS snippets_fts")
            connection.execute("CREATE TABLE snippets (id TEXT PRIMARY KEY, title TEXT, tags TEXT, content TEXT, source TEXT, confidence TEXT, embedding TEXT)")
            connection.execute("CREATE VIRTUAL TABLE snippets_fts USING fts5(id UNINDEXED, title, tags, content)")
            vectors = encode(model, [r["title"] + "\n" + r["content"] for r in records]) if model else [None] * len(records)
            for r, vector in zip(records, vectors):
                tags = " ".join(r["tags"])
                connection.execute("INSERT INTO snippets VALUES (?, ?, ?, ?, ?, ?, ?)",
                                   (r["id"], r["title"], tags, r["content"], r["source"], r["confidence"], json.dumps(vector) if vector is not None else None))
                connection.execute("INSERT INTO snippets_fts VALUES (?, ?, ?, ?)", (r["id"], r["title"], tags, r["content"]))
        print("Indexed %d chunks locally (%s)." % (len(records), "semantic vectors + FTS5" if model else "FTS5 keywords only"))
    finally:
        connection.close()

def search(db_path, query, model, limit):
    if not db_path.is_file():
        raise FileNotFoundError("Index missing: run 'index' first")
    connection = sqlite3.connect(str(db_path))
    try:
        if model:
            qvec = encode(model, [query])[0]
            rows = connection.execute("SELECT id, title, content, source, embedding FROM snippets WHERE embedding IS NOT NULL").fetchall()
            if not rows:
                raise ValueError("No semantic vectors stored. Run 'index --model-dir ...' first.")
            results = []
            for id_, title, content, source, serialized in rows:
                vec = json.loads(serialized)
                if len(vec) != len(qvec):
                    raise ValueError("Model dimension mismatch; rebuild index using this model.")
                score = sum(a*b for a,b in zip(qvec,vec))  # normalized cosine similarity
                results.append((score, id_, title, content, source))
            results.sort(reverse=True)
        else:
            terms = re.findall(r"\w+", query, flags=re.UNICODE)
            if not terms:
                return
            expression = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
            results = [(-float(rank), id_, title, content, source)
                       for id_, title, content, source, rank in connection.execute(
                        "SELECT s.id,s.title,s.content,s.source,bm25(f) FROM snippets_fts f JOIN snippets s ON s.id=f.id WHERE f MATCH ? ORDER BY bm25(f) LIMIT ?",
                        (expression, limit))]
        for score, id_, title, content, source in results[:limit]:
            print("\n%s | %.3f | %s\n%s\n%s" % (id_, score, title, content, source))
    finally:
        connection.close()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["index", "search"])
    parser.add_argument("query", nargs="?")
    parser.add_argument("--model-dir", help="Existing local sentence-transformers model; never downloaded")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    try:
        model = load_model(args.model_dir)
        if args.action == "index":
            rebuild(args.db.expanduser(), model)
        elif args.query:
            search(args.db.expanduser(), args.query, model, max(1, args.limit))
        else:
            parser.error("A search query is required.")
    except (OSError, ValueError, sqlite3.Error, ImportError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        raise SystemExit(2)

if __name__ == "__main__":
    main()

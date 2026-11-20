# Offline retrieval / vector semantics

The file `KNOWLEDGE.jsonl` contains the **authoritative, small, source-linked chunks to index**. Each record has a unique ID, title, tags, content, source, confidence, date and release gate. Do not treat PR claims as independently accepted tests.

**Already available:** `python3 docs/codex/index_local.py index` builds a local SQLite FTS5 **lexical** index in the user's cache; `search "terms"` searches it. GitHub does NOT create semantic vectors automatically merely by storing Markdown/JSONL.

**Genuine local semantic search (opt-in):** provide an already-installed local sentence-transformers-compatible embedding-model directory to `index --model-dir /existing/local/model` and `search "natural language" --model-dir /same/model`. No models are downloaded; index/query use only local inference. This stores normalized embeddings alongside text in a local SQLite file outside Git. The same model and dimensions must be used for index and query. Start with small chunks; never index binary archives, raw owner-host logs, secrets, coordinates, private recordings or out-of-scope repositories.

Update chunks and their exact source URLs whenever the handoff facts change, then rebuild the local index. **No semantic index was precomputed in this PR**; separate explicit running and validation are required before claiming active vector search.

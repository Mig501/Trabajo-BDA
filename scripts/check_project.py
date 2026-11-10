"""check_project.py - Advanced Databases, project proposal check.

Runs your embedding model on a SAMPLE of your corpus and reports:
  - the dimension and maximum sequence length of the model,
  - how the sample is distributed across languages,
  - how many 256-token chunks your FULL corpus will produce,
  - how long your laptop would take to compute all the embeddings,
and checks the corpus requirements of the project brief (Part 1).

READ README.md BEFORE RUNNING IT: it explains how to prepare the sample.

Usage (example):
    python check_project.py --sample muestra --model intfloat/multilingual-e5-base \
        --total-docs 8000 --query-prefix "query: " --passage-prefix "passage: "

Copy the whole output into your proposal:
    python check_project.py ... > check_project.txt
"""
import argparse
import json
import math
import platform
import sys
import time
from pathlib import Path

CHUNK_TOKENS = 256          # unit used to measure the corpus (brief, section 2.1)
MIN_CHUNKS = 25_000         # minimum size of the corpus, in 256-token chunks
RECOMMENDED_CHUNKS = 50_000
MIN_DOCS = 1_000
MIN_LANG_SHARE = 0.20       # each language >= 20 % of the chunks
MAX_DIM = 1024
MIN_SEQ = 512
MIN_SAMPLE_DOCS = 50
SPEED_CHUNKS = 128          # chunks encoded to measure the speed
WARMUP_CHUNKS = 16


def fail(msg):
    print(f"\nERROR: {msg}\n")
    sys.exit(1)


# ---------------------------------------------------------------- sample ---
def load_sample(path):
    """Returns a list of (language, text). Accepts a folder (format A) or a
    .csv / .jsonl file (format B). See README.md."""
    p = Path(path)
    if not p.exists():
        similar = sorted(str(c) for c in p.parent.glob(p.name + "*")) if p.parent.exists() else []
        hint = f" Did you mean: {', '.join(similar)}?" if similar else ""
        fail(f"'{path}' does not exist. Check the path given to --sample "
             f"(for format B, include the extension .csv or .jsonl).{hint}")

    docs = []
    if p.is_dir():  # Format A: one subfolder per language, one .txt per document
        subdirs = sorted(d for d in p.iterdir() if d.is_dir() and not d.name.startswith("."))
        if not subdirs:
            fail(f"The folder '{path}' has no subfolders. Format A needs one subfolder "
                 "per language (e.g. muestra/es, muestra/en). See README.md.")
        for d in subdirs:
            files = sorted(d.glob("*.txt"))
            if not files:
                print(f"WARNING: subfolder '{d.name}' has no .txt files; ignored.")
            for f in files:
                docs.append((d.name, f.read_text(encoding="utf-8", errors="replace")))
    elif p.suffix.lower() in (".csv", ".jsonl"):  # Format B
        try:
            import pandas as pd
        except ImportError:
            fail("Format B needs pandas: pip install pandas")
        try:
            df = (pd.read_csv(p) if p.suffix.lower() == ".csv"
                  else pd.read_json(p, lines=True))
        except Exception as e:  # noqa: BLE001
            fail(f"Could not read '{path}': {e}")
        missing = {"text", "language"} - set(df.columns)
        if missing:
            fail(f"'{path}' must have the columns 'text' and 'language'. "
                 f"Missing: {sorted(missing)}. Columns found: {list(df.columns)}. "
                 "See README.md.")
        df = df.dropna(subset=["text", "language"])
        docs = [(str(l).strip(), str(t)) for l, t in zip(df["language"], df["text"])]
    else:
        fail(f"'{path}' is neither a folder nor a .csv / .jsonl file. See README.md.")

    empty = sum(1 for _, t in docs if not t.strip())
    docs = [(l, t) for l, t in docs if t.strip()]
    if empty:
        print(f"WARNING: {empty} empty documents ignored.")
    if not docs:
        fail("The sample has no documents with text.")
    return docs


# ----------------------------------------------------------------- model ---
def load_model(name):
    try:
        import sentence_transformers
        from sentence_transformers import SentenceTransformer
    except ImportError:
        fail('sentence-transformers is not installed: pip install -U "sentence-transformers>=5.6"')
    major_minor = tuple(int(x) for x in sentence_transformers.__version__.split(".")[:2])
    if major_minor < (5, 6):
        fail(f"sentence-transformers {sentence_transformers.__version__} is too old. "
             'Update it: pip install -U "sentence-transformers>=5.6"')
    try:
        model = SentenceTransformer(name, trust_remote_code=False)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "trust_remote_code" in msg:
            fail(f"'{name}' needs trust_remote_code=True to load. It does not meet "
                 "criterion 5 of the brief (section 4.1): choose another model.")
        fail(f"Could not load the model '{name}':\n{msg}\n"
             "Check the name (copy it from Hugging Face) and your internet connection.")
    return model, sentence_transformers.__version__


# ------------------------------------------------------------------ main ---
def main():
    ap = argparse.ArgumentParser(description="Project proposal check (see README.md).")
    ap.add_argument("--sample", required=True,
                    help="folder (format A) or .csv/.jsonl file (format B) with the sample")
    ap.add_argument("--model", required=True,
                    help="Hugging Face name of the model, e.g. intfloat/multilingual-e5-base")
    ap.add_argument("--total-docs", required=True, type=int,
                    help="estimated number of documents of your FULL corpus")
    ap.add_argument("--query-prefix", default="",
                    help="text your model needs before each query (may be empty)")
    ap.add_argument("--passage-prefix", default="",
                    help="text your model needs before each passage (may be empty)")
    args = ap.parse_args()
    if args.total_docs <= 0:
        fail("--total-docs must be a positive number.")

    print("=" * 70)
    print("check_project.py - project proposal check")
    print("=" * 70)
    print(f"Sample:          {args.sample}")
    print(f"Model:           {args.model}")
    print(f"Total documents: {args.total_docs:,} (your estimate for the full corpus)")
    print(f"Query prefix:    {json.dumps(args.query_prefix)}")
    print(f"Passage prefix:  {json.dumps(args.passage_prefix)}")

    docs = load_sample(args.sample)
    model, st_version = load_model(args.model)
    import torch  # installed with sentence-transformers

    print(f"Python {platform.python_version()} | sentence-transformers {st_version} | "
          f"torch {torch.__version__} | {platform.system()} {platform.machine()}")

    # --- 1. Model ---------------------------------------------------------
    dim = model.get_embedding_dimension()
    max_seq = model.max_seq_length
    print("\n1. MODEL")
    print(f"   Device:             {model.device}")
    print(f"   Dimension:          {dim}")
    print(f"   max_seq_length:     {max_seq}")

    # --- 2. Tokens and chunks of the sample ------------------------------
    tok = model.tokenizer
    overhead = len(tok(args.passage_prefix)["input_ids"])  # prefix + special tokens
    usable = CHUNK_TOKENS - overhead
    print(f"   Tokens taken by the passage prefix and special tokens: {overhead} "
          f"-> {usable} text tokens per {CHUNK_TOKENS}-token chunk")

    stats = {}           # language -> dict
    chunk_texts = []     # (language, chunk text) for the speed test
    for lang, text in docs:
        ids = tok(text, add_special_tokens=False, verbose=False)["input_ids"]
        n_chunks = max(1, math.ceil(len(ids) / usable))
        s = stats.setdefault(lang, {"docs": 0, "tokens": 0, "chunks": 0, "words": 0})
        s["docs"] += 1
        s["tokens"] += len(ids)
        s["chunks"] += n_chunks
        s["words"] += len(text.split())
        for start in range(0, len(ids), usable):
            chunk_texts.append((lang, ids[start:start + usable]))

    n_docs = sum(s["docs"] for s in stats.values())
    n_chunks = sum(s["chunks"] for s in stats.values())
    n_words = sum(s["words"] for s in stats.values())
    print(f"\n2. SAMPLE ({n_docs} documents)")
    print(f"   {'language':<10}{'docs':>8}{'words':>12}{'tokens':>12}{'chunks':>10}{'% chunks':>10}")
    for lang, s in sorted(stats.items()):
        print(f"   {lang:<10}{s['docs']:>8}{s['words']:>12,}{s['tokens']:>12,}"
              f"{s['chunks']:>10,}{100 * s['chunks'] / n_chunks:>9.1f}%")
    n_tokens = sum(s["tokens"] for s in stats.values())
    print(f"   Words per full {CHUNK_TOKENS}-token chunk: {n_words / n_tokens * usable:.0f} "
          "(the last chunk of each document is usually shorter)")

    # --- 3. Extrapolation to the full corpus -----------------------------
    est_chunks = n_chunks / n_docs * args.total_docs
    print("\n3. FULL CORPUS (estimate)")
    print(f"   Chunks per document (sample average): {n_chunks / n_docs:.1f}")
    print(f"   Estimated {CHUNK_TOKENS}-token chunks: {est_chunks:,.0f}")

    # --- 4. Speed ---------------------------------------------------------
    # Take chunks spread over the whole sample (all languages).
    step = max(1, len(chunk_texts) // (SPEED_CHUNKS + WARMUP_CHUNKS))
    picked = chunk_texts[::step][:SPEED_CHUNKS + WARMUP_CHUNKS]
    texts = [args.passage_prefix + tok.decode(ids) for _, ids in picked]
    warmup, timed = texts[:WARMUP_CHUNKS], texts[WARMUP_CHUNKS:]
    print(f"\n4. SPEED (encoding {len(timed)} chunks of your sample; please wait)")
    model.encode(warmup, batch_size=32, show_progress_bar=False)
    t0 = time.perf_counter()
    model.encode(timed, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
    dt = time.perf_counter() - t0
    speed = len(timed) / dt if dt > 0 else float("inf")
    est_seconds = est_chunks / speed
    h, rem = divmod(int(est_seconds), 3600)
    print(f"   {len(timed)} chunks in {dt:.1f} s -> {speed:.1f} chunks/s")
    shown = "less than 1 min" if est_seconds < 60 else f"{h} h {rem // 60} min"
    print(f"   Estimated time for the full corpus: {shown} "
          "(embeddings only; reading, chunking and inserting not included)")

    # --- 5. Checks ---------------------------------------------------------
    print("\n5. REQUIREMENTS (brief, Part 1)")
    def check(ok, value, op, limit, note):
        shown = op if ok else {">=": "<", "<=": ">"}[op]
        print(f"   [{'OK' if ok else 'WARNING'}] {value} {shown} {limit} {note}")

    check(dim <= MAX_DIM, f"Dimension {dim}", "<=", MAX_DIM, "(section 4.1)")
    check(max_seq >= MIN_SEQ, f"max_seq_length {max_seq}", ">=", MIN_SEQ, "(section 4.1)")
    check(len(stats) >= 2, f"Languages in the sample: {len(stats)}", ">=", 2, "(section 3)")
    for lang, s in sorted(stats.items()):
        share = s["chunks"] / n_chunks
        check(share >= MIN_LANG_SHARE, f"Language '{lang}': {100 * share:.1f} % of the chunks",
              ">=", "20 %", "(section 3)")
    check(args.total_docs >= MIN_DOCS, f"Documents: {args.total_docs:,}", ">=", f"{MIN_DOCS:,}",
          "(section 2.1)")
    check(est_chunks >= MIN_CHUNKS, f"Chunks: {est_chunks:,.0f}", ">=", f"{MIN_CHUNKS:,}",
          f"(section 2.1; recommended ~{RECOMMENDED_CHUNKS:,})")
    check(n_docs >= MIN_SAMPLE_DOCS, f"Documents in the sample: {n_docs}", ">=", MIN_SAMPLE_DOCS,
          "(with fewer, the estimates are unreliable)")
    if args.query_prefix == "" and args.passage_prefix == "":
        print("   [NOTE] No prefixes given. Check in your model's card whether it needs them "
              "for queries and passages (section 4.3).")
    print("\nRemember: these are estimates from a sample. Copy this whole output into your proposal.")


if __name__ == "__main__":
    main()

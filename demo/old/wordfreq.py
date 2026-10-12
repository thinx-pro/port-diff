#!/usr/bin/env python3
"""wordfreq (reference implementation): print the most frequent words in a text file."""
import argparse
import json
import re
import sys
import time
from collections import Counter

WORD = re.compile(r"\w+(?:'\w+)*")


def main():
    p = argparse.ArgumentParser(prog="wordfreq")
    p.add_argument("file")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--json", metavar="OUT")
    a = p.parse_args()
    t0 = time.perf_counter()
    try:
        with open(a.file, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        print(f"wordfreq: cannot read {a.file}: {exc.strerror}", file=sys.stderr)
        return 2
    words = WORD.findall(text.lower())
    if not words:
        print("no words")
        return 0
    counts = Counter(words)
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[: a.top]
    for word, n in top:
        print(f"{n:>6} {word}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump({"total": len(words), "unique": len(counts),
                       "top": [{"word": w, "count": n} for w, n in top]}, fh, ensure_ascii=False)
    ms = (time.perf_counter() - t0) * 1000
    print(f"processed {len(words)} words in {ms:.1f}ms", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

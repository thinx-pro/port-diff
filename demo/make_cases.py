#!/usr/bin/env python3
"""Regenerate demo/cases/. Deterministic; run from anywhere."""
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = os.path.join(HERE, "cases")

SMALL = {
    "01-plain.txt": "the quick brown fox jumps over the lazy dog the fox\nthe end of the fox\n",
    "02-ties.txt": "pear apple pear apple zebra mango zebra mango kiwi\n",
    "03-unicode.txt": "Café au lait, café noir. Naïve café owners in Zürich.\n東京 東京 京都\n",
    "04-empty.txt": "  \n\n  ...  \n",
    "05-contractions.txt": "Don't stop. It's fine, it's fine, don't panic. Won't you? It's done.\n",
    "06-mixed-case.txt": "The THE the tHe Rust rust RUST go Go\n",
}


def big_unique():
    rng = random.Random(42)
    hot = [f"hot{i}" for i in range(10)]
    words = []
    for i, w in enumerate(hot):
        words += [w] * (200 - i * 7)
    words += [f"w{n:05d}" for n in range(30000)]
    rng.shuffle(words)
    lines = [" ".join(words[i:i + 16]) for i in range(0, len(words), 16)]
    return "\n".join(lines) + "\n"


def main():
    os.makedirs(CASES, exist_ok=True)
    for name, text in SMALL.items():
        with open(os.path.join(CASES, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(CASES, "07-large-vocabulary.txt"), "w", encoding="utf-8") as fh:
        fh.write(big_unique())
    print(f"wrote {len(SMALL) + 1} cases to {CASES}")


if __name__ == "__main__":
    main()

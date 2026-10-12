#!/usr/bin/env node
// wordfreq (port): a plausible agent-written translation of ../old/wordfreq.py.
// It compiles, it runs, and on most inputs it prints the same thing. It contains four
// realistic porting mistakes on purpose, so the demo has something to find:
//   1. JS `\w` is ASCII-only, Python's is Unicode-aware  -> "café" becomes "caf"
//   2. ties keep insertion order instead of alphabetical
//   3. empty input exits 1 instead of 0
//   4. unique-word bookkeeping uses Array.includes      -> quadratic on large inputs
'use strict';
const fs = require('fs');

function main(argv) {
  let file = null, top = 5, jsonOut = null;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--top') top = parseInt(argv[++i], 10);
    else if (argv[i] === '--json') jsonOut = argv[++i];
    else file = argv[i];
  }
  const t0 = process.hrtime.bigint();
  let text;
  try {
    text = fs.readFileSync(file, 'utf8');
  } catch (e) {
    process.stderr.write(`wordfreq: cannot read ${file}: ${e.code === 'ENOENT' ? 'No such file or directory' : e.message}\n`);
    return 2;
  }
  const words = text.toLowerCase().match(/\w+(?:'\w+)*/g) || [];
  if (words.length === 0) {
    console.log('no words');
    return 1;
  }
  const counts = new Map();
  const seen = [];
  for (const w of words) {
    if (!seen.includes(w)) seen.push(w);
    counts.set(w, (counts.get(w) || 0) + 1);
  }
  const ranked = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, top);
  for (const [w, n] of ranked) console.log(`${String(n).padStart(6)} ${w}`);
  if (jsonOut) {
    fs.writeFileSync(jsonOut, JSON.stringify({
      unique: seen.length, total: words.length,
      top: ranked.map(([w, n]) => ({ count: n, word: w })),
    }, null, 2));
  }
  const ms = Number(process.hrtime.bigint() - t0) / 1e6;
  process.stderr.write(`processed ${words.length} words in ${ms.toFixed(3)}ms\n`);
  return 0;
}

process.exitCode = main(process.argv.slice(2));

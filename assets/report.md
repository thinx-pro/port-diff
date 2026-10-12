### port-diff: 7 cases · 1 BREAK · 4 DIFF · 1 PERF · 1 NOISE

- old: `python3 demo/old/wordfreq.py {case} --json out.json`
- new: `node demo/new/wordfreq.js {case} --json out.json`

| verdict | case | old ms | new ms | first finding |
|---|---|---:|---:|---|
| **DIFF** | `01-plain.txt` | 34 | 38 | stdout: only in new: '1 quick' |
| **DIFF** | `02-ties.txt` | 35 | 39 | stdout: only in new: '2 pear' |
| **DIFF** | `03-unicode.txt` | 34 | 39 | stdout: '3 café' -> '3 caf' |
| **BREAK** | `04-empty.txt` | 35 | 36 | exit 0 -> exit 1 |
| **DIFF** | `05-contractions.txt` | 36 | 38 | stdout: '1 done' -> '1 stop' |
| **NOISE** | `06-mixed-case.txt` | 37 | 37 | identical after durations, json, trailing-ws |
| **PERF** | `07-large-vocabulary.txt` | 53 | 717 | 53 ms -> 717 ms (13.6x slower) |

<details><summary>DIFF · 01-plain.txt</summary>

**stdout: only in new: '1 quick'**

```diff
--- old/stdout
+++ new/stdout
@@ -1,5 +1,5 @@
      5 the
      3 fox
+     1 quick
      1 brown
-     1 dog
-     1 end
+     1 jumps
```

**out.json: only in new: '"word": "quick"'**

```diff
--- old/out.json
+++ new/out.json
@@ -11,13 +11,13 @@
   {
    "count": 1,
+   "word": "quick"
+  },
+  {
+   "count": 1,
    "word": "brown"
   },
   {
    "count": 1,
-   "word": "dog"
-  },
-  {
-   "count": 1,
-   "word": "end"
+   "word": "jumps"
   }
  ],
```

</details>

<details><summary>DIFF · 02-ties.txt</summary>

**stdout: only in new: '2 pear'**

```diff
--- old/stdout
+++ new/stdout
@@ -1,5 +1,5 @@
+     2 pear
      2 apple
+     2 zebra
      2 mango
-     2 pear
-     2 zebra
      1 kiwi
```

**out.json: only in new: '{'**

```diff
--- old/out.json
+++ new/out.json
@@ -1,4 +1,8 @@
 {
  "top": [
+  {
+   "count": 2,
+   "word": "pear"
+  },
   {
    "count": 2,
@@ -7,13 +11,9 @@
   {
    "count": 2,
-   "word": "mango"
+   "word": "zebra"
   },
   {
    "count": 2,
-   "word": "pear"
-  },
-  {
-   "count": 2,
-   "word": "zebra"
+   "word": "mango"
   },
   {
```

</details>

<details><summary>DIFF · 03-unicode.txt</summary>

**stdout: '3 café' -> '3 caf'**

```diff
--- old/stdout
+++ new/stdout
@@ -1,5 +1,5 @@
-     3 café
-     2 東京
+     3 caf
      1 au
-     1 in
      1 lait
+     1 noir
+     1 na
```

**out.json: '"word": "café"' -> '"word": "caf"'**

```diff
--- old/out.json
+++ new/out.json
@@ -3,9 +3,5 @@
   {
    "count": 3,
-   "word": "café"
-  },
-  {
-   "count": 2,
-   "word": "東京"
+   "word": "caf"
   },
   {
@@ -15,12 +11,16 @@
   {
    "count": 1,
-   "word": "in"
+   "word": "lait"
   },
   {
    "count": 1,
-   "word": "lait"
+   "word": "noir"
+  },
+  {
+   "count": 1,
+   "word": "na"
   }
  ],
- "total": 13,
+ "total": 12,
  "unique": 10
 }
```

**stderr: 'processed 13 words in <DUR>' -> 'processed 12 words in <DUR>'**

```diff
--- old/stderr
+++ new/stderr
@@ -1 +1 @@
-processed 13 words in <DUR>
+processed 12 words in <DUR>
```

</details>

<details><summary>DIFF · 05-contractions.txt</summary>

**stdout: '1 done' -> '1 stop'**

```diff
--- old/stdout
+++ new/stdout
@@ -2,4 +2,4 @@
      2 don't
      2 fine
-     1 done
+     1 stop
      1 panic
```

**out.json: '"word": "done"' -> '"word": "stop"'**

```diff
--- old/out.json
+++ new/out.json
@@ -15,5 +15,5 @@
   {
    "count": 1,
-   "word": "done"
+   "word": "stop"
   },
   {
```

</details>

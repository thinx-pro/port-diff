"""Normalizers: rewrite output so that differences nobody cares about disappear.

Each normalizer is a function (text, ctx) -> text. A spec string selects one:

    name              apply to every stream
    name=ARG          with an argument (e.g. floats=6)
    name:stderr,files restrict to some streams (stdout, stderr, files)
"""
import json
import re

STREAMS = ("stdout", "stderr", "files")

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
TS_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?\b"
    r"|\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b"
)
DUR_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?\s?(?:ns|µs|us|ms|s|sec|secs|seconds)\b")
ADDR_RE = re.compile(r"\b0x[0-9a-fA-F]{6,16}\b")
TMP_RE = re.compile(r"(?:/private)?/var/folders/[\w/.+-]+|/tmp/[\w/.+-]+|[A-Za-z]:\\[^\s]*\\Temp\\[^\s]*")
FLOAT_RE = re.compile(r"(?<![\w.])-?\d+\.\d+(?:[eE][-+]?\d+)?(?![\w.])")


def _ansi(text, ctx, arg):
    return ANSI_RE.sub("", text)


def _crlf(text, ctx, arg):
    return text.replace("\r\n", "\n")


def _trailing_ws(text, ctx, arg):
    lines = [ln.rstrip() for ln in text.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + ("\n" if lines else "")


def _workdir(text, ctx, arg):
    for p in sorted(ctx.get("workdirs", []), key=len, reverse=True):
        if p:
            text = text.replace(p, "<WORKDIR>")
    return text


def _tmpdir(text, ctx, arg):
    return TMP_RE.sub("<TMP>", text)


def _timestamps(text, ctx, arg):
    return TS_RE.sub("<TIME>", text)


def _durations(text, ctx, arg):
    return DUR_RE.sub("<DUR>", text)


def _addrs(text, ctx, arg):
    return ADDR_RE.sub("<ADDR>", text)


def _floats(text, ctx, arg):
    digits = int(arg or 6)

    def fmt(m):
        try:
            return format(float(m.group(0)), f".{digits}g")
        except ValueError:
            return m.group(0)

    return FLOAT_RE.sub(fmt, text)


def _sort_lines(text, ctx, arg):
    lines = text.split("\n")
    trailing = lines and lines[-1] == ""
    body = sorted(lines[:-1] if trailing else lines)
    return "\n".join(body) + ("\n" if trailing else "")


def _json(text, ctx, arg):
    try:
        return json.dumps(json.loads(text), sort_keys=True, indent=1, ensure_ascii=False) + "\n"
    except (ValueError, TypeError):
        return text


def _ws(text, ctx, arg):
    return "\n".join(" ".join(ln.split()) for ln in text.split("\n"))


def _case(text, ctx, arg):
    return text.lower()


RULES = {
    "ansi": (_ansi, "strip ANSI colour / cursor codes"),
    "crlf": (_crlf, "CRLF -> LF"),
    "trailing-ws": (_trailing_ws, "ignore trailing spaces and trailing blank lines"),
    "workdir": (_workdir, "the per-run scratch directory -> <WORKDIR>"),
    "tmpdir": (_tmpdir, "other temp paths (/tmp, /var/folders, %TEMP%) -> <TMP>"),
    "timestamps": (_timestamps, "ISO dates and HH:MM:SS clocks -> <TIME>"),
    "durations": (_durations, "12ms / 1.5s / 3 seconds -> <DUR>"),
    "addrs": (_addrs, "hex pointers like 0x7ffd5e8a -> <ADDR>"),
    "floats": (_floats, "round floats to N significant digits (floats=6)"),
    "sort-lines": (_sort_lines, "treat output as an unordered set of lines"),
    "json": (_json, "parse JSON and re-serialise with sorted keys"),
    "ws": (_ws, "collapse runs of whitespace"),
    "case": (_case, "lower-case everything"),
}

DEFAULTS = ["ansi", "crlf", "trailing-ws", "workdir", "tmpdir", "timestamps", "durations", "addrs"]


class Normalizer:
    def __init__(self, specs=None, disabled=(), subs=(), raw=False):
        self.steps = []  # (name, fn, arg, streams)
        chosen = [] if raw else [s for s in DEFAULTS if s not in disabled]
        chosen += list(specs or [])
        for spec in chosen:
            self.steps.append(self.parse(spec))
        for i, sub in enumerate(subs):
            if "=>" not in sub:
                raise ValueError(f"--sub expects 'REGEX=>REPLACEMENT', got {sub!r}")
            pat, repl = sub.split("=>", 1)
            rx = re.compile(pat, re.M)
            self.steps.append((f"sub#{i + 1}", lambda t, c, a, rx=rx, repl=repl: rx.sub(repl, t), None, set(STREAMS)))

    @staticmethod
    def parse(spec):
        streams = set(STREAMS)
        if ":" in spec:
            spec, scope = spec.split(":", 1)
            streams = {s.strip() for s in scope.split(",") if s.strip()}
            bad = streams - set(STREAMS)
            if bad:
                raise ValueError(f"unknown stream(s) {sorted(bad)}; use stdout, stderr, files")
        arg = None
        if "=" in spec:
            spec, arg = spec.split("=", 1)
        if spec not in RULES:
            raise ValueError(f"unknown normalizer {spec!r}; known: {', '.join(RULES)}")
        return (spec, RULES[spec][0], arg, streams)

    def apply(self, text, ctx, stream):
        """Return (normalized_text, names of rules that changed something)."""
        touched = []
        for name, fn, arg, streams in self.steps:
            if stream not in streams:
                continue
            out = fn(text, ctx, arg)
            if out != text:
                touched.append(name)
                text = out
        return text, touched

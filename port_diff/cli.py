"""port-diff command line."""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from . import __version__, report
from .compare import RANK, compare, summarize
from .normalize import DEFAULTS, RULES, Normalizer
from .runner import absolutize, discover_cases, run_case

EPILOG = """examples:
  # compare two builds on every input in cases/ (each run gets a fresh scratch dir)
  port-diff run --old "python3 old/tool.py {case}" --new "./target/release/tool {case}" --cases cases/

  # argument-driven CLIs: one case per line of args.txt
  port-diff run --old "old-cli {args}" --new "new-cli {args}" --args-file args.txt

  # the old binary won't be around forever: record once, check many times
  port-diff record --old "tsc --noEmit -p {case}" --cases repos/ --out baseline.json
  port-diff check  --new "tsc-rs --noEmit -p {case}" --cases repos/ --baseline baseline.json --json -

placeholders: {case} path of the copied case, {name} case name, {args} line from --args-file,
              {here} the directory you ran port-diff from
Each run happens in a fresh scratch directory; relative paths in the command that exist
where you run port-diff (./target/release/tool, old/tool.py) are made absolute for you.
exit status: 0 equivalent, 1 findings at or above --fail-on, 2 usage error
"""


def _add_common(p, need_cases=True):
    g = p.add_argument_group("cases")
    g.add_argument("--cases", metavar="DIR", help="every entry in DIR is one case (file or directory)")
    g.add_argument("--args-file", metavar="FILE", help="one case per line, substituted for {args}")
    g.add_argument("--case", action="append", default=[], metavar="PATH", help="add a single case path (repeatable)")
    g.add_argument("--filter", metavar="TEXT", help="only cases whose name contains TEXT")
    g.add_argument("--stdin", action="store_true", help="feed the case file (or DIR/stdin) to standard input")
    r = p.add_argument_group("running")
    r.add_argument("--timeout", type=float, default=60, help="seconds per run (default 60)")
    r.add_argument("--repeat", type=int, default=1, help="runs per case; >1 enables timing medians and a determinism check")
    r.add_argument("--jobs", "-j", type=int, default=1, help="parallel cases (timings get noisier)")
    r.add_argument("--env", action="append", default=[], metavar="K=V", help="extra environment variable (repeatable)")
    r.add_argument("--ignore-file", action="append", default=[], metavar="GLOB", help="don't compare files matching GLOB")
    r.add_argument("--keep", action="store_true", help="keep scratch directories (for debugging)")
    n = p.add_argument_group("normalization")
    n.add_argument("--norm", action="append", default=[], metavar="SPEC",
                   help="add a normalizer, e.g. json:files, sort-lines:stderr, floats=6")
    n.add_argument("--no-norm", action="append", default=[], metavar="NAME", help="disable a default normalizer")
    n.add_argument("--raw", action="store_true", help="disable all default normalizers")
    n.add_argument("--sub", action="append", default=[], metavar="'RE=>REPL'", help="custom regex substitution")
    n.add_argument("--list-norms", action="store_true", help="list normalizers and exit")


def _add_output(p):
    o = p.add_argument_group("reporting")
    o.add_argument("--json", metavar="PATH", help="machine-readable report ('-' for stdout; feed this to your agent)")
    o.add_argument("--md", metavar="PATH", help="Markdown report for a PR comment")
    o.add_argument("--html", metavar="PATH", help="self-contained HTML report")
    o.add_argument("--quiet", "-q", action="store_true", help="summary table only, no diffs")
    o.add_argument("--fail-on", choices=["break", "diff", "warn", "perf", "never"], default="diff",
                   help="lowest severity that makes the exit status 1 (default diff)")
    o.add_argument("--strict-stderr", action="store_true", help="treat stderr differences as DIFF instead of WARN")
    o.add_argument("--perf-ratio", type=float, default=2.0, help="flag PERF when new > ratio x old (default 2.0)")
    o.add_argument("--perf-min-ms", type=float, default=100, help="...and slower by at least this many ms (default 100)")
    o.add_argument("--max-diff-lines", type=int, default=40)


def build_parser():
    p = argparse.ArgumentParser(
        prog="port-diff", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=EPILOG,
        description="Behavior-equivalence check for rewrites and ports: run the old and the new implementation "
                    "on the same inputs, normalize away noise, and grade what actually changed.")
    p.add_argument("--version", action="version", version=f"port-diff {__version__}")
    sub = p.add_subparsers(dest="command")

    run = sub.add_parser("run", help="run old and new live and compare", formatter_class=argparse.RawDescriptionHelpFormatter,
                         epilog=EPILOG)
    run.add_argument("--old", help="command template for the reference implementation")
    run.add_argument("--new", help="command template for the port")
    _add_common(run)
    _add_output(run)

    rec = sub.add_parser("record", help="record the old implementation's behavior to a baseline file")
    rec.add_argument("--old", help="command template for the reference implementation")
    rec.add_argument("--out", default="port-diff-baseline.json", help="baseline file to write")
    _add_common(rec)

    chk = sub.add_parser("check", help="run the new implementation against a recorded baseline")
    chk.add_argument("--new", help="command template for the port")
    chk.add_argument("--baseline", default="port-diff-baseline.json", help="baseline file from `record`")
    _add_common(chk)
    _add_output(chk)
    return p


def _env(pairs):
    env = dict(os.environ)
    env.setdefault("TZ", "UTC")
    env["NO_COLOR"] = "1"
    for kv in pairs:
        if "=" not in kv:
            raise ValueError(f"--env expects K=V, got {kv!r}")
        k, v = kv.split("=", 1)
        env[k] = v
    return env


def _run_all(template, cases, a, env):
    template = absolutize(template)

    def one(case):
        return case.name, run_case(template, case, timeout=a.timeout, repeat=a.repeat, use_stdin=a.stdin,
                                   env=env, ignore=a.ignore_file, keep=a.keep)

    if a.jobs > 1:
        with ThreadPoolExecutor(max_workers=a.jobs) as ex:
            return dict(ex.map(one, cases))
    return dict(one(c) for c in cases)


def _emit(results, a, meta):
    summary = summarize(results)
    if a.json == "-":
        sys.stdout.write(report.to_json(results, summary, meta) + "\n")
    else:
        report.terminal(results, summary, meta, show_diffs=not a.quiet)
        if a.json:
            _write(a.json, report.to_json(results, summary, meta) + "\n")
    if a.md:
        _write(a.md, report.markdown(results, summary, meta))
    if a.html:
        _write(a.html, report.to_html(results, summary, meta))
    if a.fail_on == "never":
        return 0
    threshold = RANK[a.fail_on.upper()]
    return 1 if any(RANK[r["verdict"]] >= threshold for r in results) else 0


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {path}", file=sys.stderr)


def _cases(a):
    if not (a.cases or a.args_file or a.case):
        raise ValueError("no cases: pass --cases DIR, --args-file FILE or --case PATH")
    cases = discover_cases(a.cases, a.args_file, a.case, a.filter)
    if not cases:
        raise ValueError("no cases found")
    return cases


def main(argv=None):
    parser = build_parser()
    a = parser.parse_args(argv)
    if getattr(a, "list_norms", False):
        for name, (_, desc) in RULES.items():
            mark = "default" if name in DEFAULTS else "opt-in "
            print(f"  {name:<12} {mark}  {desc}")
        return 0
    if not a.command:
        parser.print_help()
        return 2
    try:
        norm = Normalizer(a.norm, disabled=set(a.no_norm), subs=a.sub, raw=a.raw)
        env = _env(a.env)
        if a.command == "run":
            if not (a.old and a.new):
                raise ValueError("run needs both --old and --new")
            cases = _cases(a)
            old = _run_all(a.old, cases, a, env)
            new = _run_all(a.new, cases, a, env)
            results = [compare(c.name, old[c.name], new[c.name], norm, a.perf_ratio, a.perf_min_ms,
                               a.strict_stderr, a.max_diff_lines) for c in cases]
            return _emit(results, a, {"old": a.old, "new": a.new, "mode": "run"})
        if a.command == "record":
            if not a.old:
                raise ValueError("record needs --old")
            cases = _cases(a)
            obs = _run_all(a.old, cases, a, env)
            data = {"tool": "port-diff", "version": __version__, "old": a.old,
                    "recorded": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "cases": {c.name: {"case": c.to_json(), "obs": obs[c.name]} for c in cases}}
            _write(a.out, json.dumps(data, indent=1, ensure_ascii=False))
            print(f"recorded {len(cases)} cases from: {a.old}", file=sys.stderr)
            return 0
        if a.command == "check":
            if not a.new:
                raise ValueError("check needs --new")
            with open(a.baseline, encoding="utf-8") as fh:
                base = json.load(fh)
            cases = _cases(a)
            missing = [c.name for c in cases if c.name not in base["cases"]]
            if missing:
                raise ValueError(f"cases not in baseline (re-record?): {missing[:5]}")
            new = _run_all(a.new, cases, a, env)
            results = [compare(c.name, base["cases"][c.name]["obs"], new[c.name], norm, a.perf_ratio,
                               a.perf_min_ms, a.strict_stderr, a.max_diff_lines) for c in cases]
            return _emit(results, a, {"old": base.get("old", "") + f"  (baseline {base.get('recorded', '')})",
                                      "new": a.new, "mode": "check"})
    except (ValueError, OSError, KeyError) as exc:
        print(f"port-diff: error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())

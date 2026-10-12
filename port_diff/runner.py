"""Run one implementation on one case in a fresh scratch directory and record what it did."""
import fnmatch
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time

TEXT_LIMIT = 1_000_000  # bytes; larger artefacts are compared by hash only


class Case:
    """A single input. Either a path (file or directory copied into the scratch dir) or an argument string."""

    def __init__(self, name, path=None, args=""):
        self.name = name
        self.path = path
        self.args = args

    def to_json(self):
        return {"name": self.name, "path": self.path, "args": self.args}


def discover_cases(cases_dir=None, args_file=None, paths=(), name_filter=None):
    cases = []
    if cases_dir:
        for entry in sorted(os.listdir(cases_dir)):
            if entry.startswith("."):
                continue
            cases.append(Case(entry, path=os.path.abspath(os.path.join(cases_dir, entry))))
    if args_file:
        with open(args_file, encoding="utf-8") as fh:
            n = 0
            for line in fh:
                line = line.rstrip("\n")
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                n += 1
                cases.append(Case(f"args-{n:03d}", args=line.strip()))
    for p in paths:
        cases.append(Case(os.path.basename(os.path.normpath(p)), path=os.path.abspath(p)))
    if name_filter:
        cases = [c for c in cases if name_filter in c.name]
    names = [c.name for c in cases]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ValueError(f"duplicate case names: {sorted(dupes)}")
    return cases


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _snapshot(root, ignore):
    snap = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for f in sorted(filenames):
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if any(fnmatch.fnmatch(rel, g) for g in ignore):
                continue
            try:
                with open(full, "rb") as fh:
                    data = fh.read()
            except OSError:
                continue
            snap[rel] = data
    return snap


def _decode(data):
    if len(data) > TEXT_LIMIT:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def absolutize(template, here=None):
    """Commands run inside a scratch dir, so rewrite tokens that are existing relative paths
    (./target/release/tool, old/tool.py) to absolute ones. Also expands {here}."""
    here = here or os.getcwd()
    try:
        tokens = shlex.split(template)
    except ValueError:
        tokens = template.split()
    for tok in set(tokens):
        if "{" in tok or os.path.isabs(tok) or tok.startswith("-") or os.sep not in tok and "." not in tok:
            continue
        if not os.path.exists(os.path.join(here, tok)):
            continue
        absolute = shlex.quote(os.path.abspath(os.path.join(here, tok)))
        template = re.sub(r"(?<![^\s=])" + re.escape(tok) + r"(?!\S)", lambda m: absolute, template)
    return template.replace("{here}", shlex.quote(here))


def build_command(template, case, case_path):
    cmd = template
    cmd = cmd.replace("{case}", shlex.quote(case_path) if case_path else "")
    cmd = cmd.replace("{name}", shlex.quote(case.name))
    cmd = cmd.replace("{args}", case.args)
    return cmd


def _one_run(template, case, timeout, use_stdin, env, ignore, keep):
    workdir = tempfile.mkdtemp(prefix="port-diff-")
    case_path = None
    stdin_data = None
    try:
        if case.path:
            if os.path.isdir(case.path):
                case_path = os.path.join(workdir, case.name)
                shutil.copytree(case.path, case_path)
                if use_stdin and os.path.isfile(os.path.join(case.path, "stdin")):
                    with open(os.path.join(case.path, "stdin"), "rb") as fh:
                        stdin_data = fh.read()
            else:
                case_path = os.path.join(workdir, case.name)
                shutil.copy2(case.path, case_path)
                if use_stdin:
                    with open(case.path, "rb") as fh:
                        stdin_data = fh.read()
        before = _snapshot(workdir, ignore)
        cmd = build_command(template, case, case_path)
        t0 = time.perf_counter()
        status = "ok"
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=workdir, input=stdin_data if stdin_data is not None else b"",
                capture_output=True, timeout=timeout, env=env,
            )
            out, err, code = proc.stdout, proc.stderr, proc.returncode
            if code < 0:
                status = f"signal {-code}"
        except subprocess.TimeoutExpired as exc:
            out, err, code = exc.stdout or b"", exc.stderr or b"", None
            status = "timeout"
        elapsed_ms = (time.perf_counter() - t0) * 1000
        after = _snapshot(workdir, ignore)
        files = {}
        for rel, data in after.items():
            if before.get(rel) == data:
                continue
            files[rel] = {"sha256": _sha(data), "size": len(data), "text": _decode(data)}
        deleted = sorted(set(before) - set(after))
        return {
            "cmd": cmd,
            "status": status,
            "exit": code,
            "stdout": out.decode("utf-8", errors="replace"),
            "stderr": err.decode("utf-8", errors="replace"),
            "files": files,
            "deleted": deleted,
            "ms": round(elapsed_ms, 2),
            "workdirs": [workdir, os.path.realpath(workdir)],
        }
    finally:
        if not keep:
            shutil.rmtree(workdir, ignore_errors=True)


def run_case(template, case, timeout=60, repeat=1, use_stdin=False, env=None, ignore=(), keep=False):
    """Run `repeat` times, each in a fresh scratch dir. The first run is the observation;
    all runs feed the timing and the determinism check."""
    runs = [_one_run(template, case, timeout, use_stdin, env, ignore, keep) for _ in range(max(1, repeat))]
    obs = dict(runs[0])
    times = sorted(r["ms"] for r in runs)
    obs["ms_all"] = [r["ms"] for r in runs]
    obs["ms_median"] = times[len(times) // 2]
    obs["repeat_outputs"] = [
        {k: r[k] for k in ("status", "exit", "stdout", "stderr")} | {
            "files": {p: f["text"] if f["text"] is not None else "sha256:" + f["sha256"]
                      for p, f in r["files"].items()},
            "workdirs": r["workdirs"],
        }
        for r in runs[1:]
    ]
    return obs

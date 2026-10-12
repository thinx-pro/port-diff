"""Compare two observations of the same case and grade the differences."""
import difflib

SEVERITY = ["SAME", "NOISE", "PERF", "WARN", "DIFF", "BREAK"]
RANK = {s: i for i, s in enumerate(SEVERITY)}


def worst(levels):
    return max(levels, key=lambda s: RANK[s]) if levels else "SAME"


def unified(a, b, label, max_lines):
    lines = list(difflib.unified_diff(
        a.splitlines(), b.splitlines(), fromfile=f"old/{label}", tofile=f"new/{label}", lineterm="", n=2,
    ))
    if len(lines) > max_lines:
        hidden = len(lines) - max_lines
        lines = lines[:max_lines] + [f"... {hidden} more diff lines"]
    return "\n".join(lines)


def first_change(a, b, width=48):
    """A short hint like: '3 café' -> '3 caf'."""
    al, bl = a.splitlines(), b.splitlines()
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, al, bl, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        old = al[i1].strip() if i1 < i2 else ""
        new = bl[j1].strip() if j1 < j2 else ""
        cut = lambda s: (s[: width - 1] + "…") if len(s) > width else s
        if old and new:
            return f"{cut(old)!r} -> {cut(new)!r}"
        return f"only in old: {cut(old)!r}" if old else f"only in new: {cut(new)!r}"
    return ""


def _outcome(obs):
    if obs["status"] != "ok":
        return obs["status"]
    return f"exit {obs['exit']}"


def _flaky(obs, norm, label):
    """True when repeated runs of the same implementation disagree after normalization."""
    first = {
        "status": obs["status"], "exit": obs["exit"],
        "stdout": norm.apply(obs["stdout"], obs, "stdout")[0],
        "stderr": norm.apply(obs["stderr"], obs, "stderr")[0],
        "files": {p: norm.apply(f["text"], obs, "files")[0] if f["text"] is not None else "sha256:" + f["sha256"]
                  for p, f in obs["files"].items()},
    }
    for rep in obs.get("repeat_outputs", []):
        ctx = {"workdirs": rep["workdirs"]}
        other = {
            "status": rep["status"], "exit": rep["exit"],
            "stdout": norm.apply(rep["stdout"], ctx, "stdout")[0],
            "stderr": norm.apply(rep["stderr"], ctx, "stderr")[0],
            "files": {p: norm.apply(v, ctx, "files")[0] if not v.startswith("sha256:") else v
                      for p, v in rep["files"].items()},
        }
        if other != first:
            changed = [k for k in first if first[k] != other[k]]
            return f"{label} implementation is nondeterministic on this case ({', '.join(changed)} changed between repeats)"
    return None


def compare(name, old, new, norm, perf_ratio=2.0, perf_min_ms=100.0, strict_stderr=False, max_diff_lines=40):
    findings = []
    noise = set()

    def add(severity, kind, detail, diff=""):
        findings.append({"severity": severity, "kind": kind, "detail": detail, "diff": diff})

    # 1. outcome: exit code, crash, timeout
    if _outcome(old) != _outcome(new):
        add("BREAK", "outcome", f"{_outcome(old)} -> {_outcome(new)}")

    # 2. streams
    for stream in ("stdout", "stderr"):
        a_raw, b_raw = old[stream], new[stream]
        if a_raw == b_raw:
            continue
        a, ta = norm.apply(a_raw, old, stream)
        b, tb = norm.apply(b_raw, new, stream)
        if a == b:
            noise.update(ta + tb)
            continue
        sev = "DIFF" if stream == "stdout" or strict_stderr else "WARN"
        hint = first_change(a, b)
        add(sev, stream, f"{stream}: {hint}" if hint else f"{stream} differs", unified(a, b, stream, max_diff_lines))

    # 3. files produced / modified
    of, nf = old["files"], new["files"]
    for rel in sorted(set(of) | set(nf)):
        if rel not in nf:
            add("BREAK", "file", f"{rel}: produced by old, missing in new")
            continue
        if rel not in of:
            add("DIFF", "file", f"{rel}: extra file produced only by new")
            continue
        fa, fb = of[rel], nf[rel]
        if fa["sha256"] == fb["sha256"]:
            continue
        if fa["text"] is None or fb["text"] is None:
            add("DIFF", "file", f"{rel}: binary content differs ({fa['size']} -> {fb['size']} bytes)")
            continue
        a, ta = norm.apply(fa["text"], old, "files")
        b, tb = norm.apply(fb["text"], new, "files")
        if a == b:
            noise.update(ta + tb)
            continue
        hint = first_change(a, b)
        add("DIFF", "file", f"{rel}: {hint}" if hint else f"{rel}: content differs", unified(a, b, rel, max_diff_lines))
    for rel in sorted(set(old.get("deleted", [])) ^ set(new.get("deleted", []))):
        who = "old" if rel in old.get("deleted", []) else "new"
        add("DIFF", "file", f"{rel}: deleted only by {who}")

    # 4. determinism
    for label, obs in (("old", old), ("new", new)):
        msg = _flaky(obs, norm, label)
        if msg:
            add("WARN", "flaky", msg)

    # 5. performance (median of repeats)
    t_old, t_new = old.get("ms_median", old["ms"]), new.get("ms_median", new["ms"])
    if t_new > t_old * perf_ratio and (t_new - t_old) >= perf_min_ms:
        add("PERF", "time", f"{t_old:.0f} ms -> {t_new:.0f} ms ({t_new / max(t_old, 0.001):.1f}x slower)")

    levels = [f["severity"] for f in findings]
    if noise and not levels:
        levels.append("NOISE")
    return {
        "case": name,
        "verdict": worst(levels),
        "findings": sorted(findings, key=lambda f: -RANK[f["severity"]]),
        "noise_rules": sorted(noise),
        "ms_old": round(t_old, 2),
        "ms_new": round(t_new, 2),
        "cmd_old": old.get("cmd", ""),
        "cmd_new": new.get("cmd", ""),
    }


def summarize(results):
    counts = {s: 0 for s in SEVERITY}
    for r in results:
        counts[r["verdict"]] += 1
    t_old = sum(r["ms_old"] for r in results)
    t_new = sum(r["ms_new"] for r in results)
    return {
        "cases": len(results),
        "counts": counts,
        "equivalent": counts["SAME"] + counts["NOISE"],
        "ms_old_total": round(t_old, 1),
        "ms_new_total": round(t_new, 1),
    }

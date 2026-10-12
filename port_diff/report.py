"""Render results: terminal, Markdown (PR comment), JSON (for agents), HTML (to share)."""
import html
import json
import os
import sys

from . import __version__
from .compare import SEVERITY

COLORS = {"BREAK": "1;37;41", "DIFF": "1;31", "WARN": "33", "PERF": "35", "NOISE": "36", "SAME": "32"}
MEANING = {
    "BREAK": "outcome changed (exit code, crash, timeout) or an artefact disappeared",
    "DIFF": "observable output or produced files differ after normalization",
    "WARN": "stderr wording differs, or an implementation is nondeterministic",
    "PERF": "new is slower beyond the threshold",
    "NOISE": "differs byte-for-byte, identical after normalization",
    "SAME": "byte-identical",
}


def use_color(stream):
    return hasattr(stream, "isatty") and stream.isatty() and not os.environ.get("NO_COLOR")


def paint(text, sev, color):
    return f"\x1b[{COLORS[sev]}m{text}\x1b[0m" if color else text


def _diff_line_color(line, color):
    if not color:
        return line
    if line.startswith("+") and not line.startswith("+++"):
        return f"\x1b[32m{line}\x1b[0m"
    if line.startswith("-") and not line.startswith("---"):
        return f"\x1b[31m{line}\x1b[0m"
    if line.startswith("@@"):
        return f"\x1b[36m{line}\x1b[0m"
    return line


def summary_line(summary):
    parts = [f"{summary['cases']} cases"]
    for sev in reversed(SEVERITY):
        n = summary["counts"][sev]
        if n:
            parts.append(f"{n} {sev}")
    return " · ".join(parts)


def terminal(results, summary, meta, color=None, show_diffs=True, out=None):
    out = out or sys.stdout
    color = use_color(out) if color is None else color
    w = out.write
    w(f"port-diff {__version__}\n")
    w(f"  old: {meta.get('old', '')}\n  new: {meta.get('new', '')}\n\n")
    name_w = max([len(r["case"]) for r in results] + [4])
    for r in results:
        sev = r["verdict"]
        tag = paint(f" {sev:<5} ", sev, color)
        first = r["findings"][0]["detail"] if r["findings"] else (
            "identical after " + ", ".join(r["noise_rules"]) if r["noise_rules"] else "identical")
        w(f"{tag} {r['case']:<{name_w}}  {r['ms_old']:>8.0f}ms -> {r['ms_new']:>6.0f}ms  {first}\n")
    w("\n" + summary_line(summary) + "\n")
    if show_diffs:
        for r in results:
            shown = [f for f in r["findings"] if f["severity"] in ("BREAK", "DIFF", "WARN", "PERF")]
            if not shown:
                continue
            w("\n" + paint(f"── {r['case']} ", r["verdict"], color) + "\n")
            for f in shown:
                w(f"  [{f['severity']}] {f['detail']}\n")
                if f["diff"]:
                    for line in f["diff"].splitlines():
                        w("    " + _diff_line_color(line, color) + "\n")


def to_json(results, summary, meta):
    return json.dumps({"tool": "port-diff", "version": __version__, "meta": meta,
                       "summary": summary, "results": results}, indent=2, ensure_ascii=False)


def markdown(results, summary, meta):
    lines = [f"### port-diff: {summary_line(summary)}", ""]
    lines += [f"- old: `{meta.get('old', '')}`", f"- new: `{meta.get('new', '')}`", ""]
    lines += ["| verdict | case | old ms | new ms | first finding |", "|---|---|---:|---:|---|"]
    for r in results:
        first = r["findings"][0]["detail"] if r["findings"] else (
            "identical after " + ", ".join(r["noise_rules"]) if r["noise_rules"] else "identical")
        lines.append(f"| **{r['verdict']}** | `{r['case']}` | {r['ms_old']:.0f} | {r['ms_new']:.0f} | {first.replace('|', '/')} |")
    for r in results:
        diffs = [f for f in r["findings"] if f["diff"]]
        if not diffs:
            continue
        lines += ["", f"<details><summary>{r['verdict']} · {r['case']}</summary>", ""]
        for f in diffs:
            lines += [f"**{f['detail']}**", "", "```diff", f["diff"], "```", ""]
        lines.append("</details>")
    return "\n".join(lines) + "\n"


CSS = """
:root{--bg:#0d1117;--card:#161b22;--line:#30363d;--fg:#e6edf3;--mute:#8b949e;
--BREAK:#f85149;--DIFF:#ff7b72;--WARN:#d29922;--PERF:#bc8cff;--NOISE:#39c5cf;--SAME:#3fb950}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;padding:28px}
.wrap{max-width:1040px;margin:0 auto}h1{font-size:22px;margin:0 0 4px}h1 small{color:var(--mute);font-weight:400;font-size:14px}
.cmd{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--mute);margin:2px 0}
.tiles{display:flex;gap:10px;margin:18px 0;flex-wrap:wrap}.tile{flex:1;min-width:110px;background:var(--card);
border:1px solid var(--line);border-radius:10px;padding:10px 14px}.tile b{display:block;font-size:24px}
.tile span{color:var(--mute);font-size:12px}table{width:100%;border-collapse:collapse;background:var(--card);
border:1px solid var(--line);border-radius:10px;overflow:hidden}th,td{padding:8px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--mute);font-weight:500;font-size:12px}td.num{text-align:right;font-variant-numeric:tabular-nums;color:var(--mute)}
.badge{display:inline-block;min-width:58px;text-align:center;border-radius:6px;padding:1px 8px;font-weight:600;font-size:12px;color:#0d1117}
code{font:12px ui-monospace,SFMono-Regular,Menlo,monospace}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:12px 0;padding:10px 14px}
summary{cursor:pointer;font-weight:600}pre{background:#0b0f14;border-radius:8px;padding:10px;overflow:auto;font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}
.add{color:#3fb950}.del{color:#ff7b72}.hunk{color:#39c5cf}.legend{color:var(--mute);font-size:12px;margin-top:16px}
"""


def _diff_html(diff):
    out = []
    for line in diff.splitlines():
        cls = ""
        if line.startswith("+") and not line.startswith("+++"):
            cls = "add"
        elif line.startswith("-") and not line.startswith("---"):
            cls = "del"
        elif line.startswith("@@"):
            cls = "hunk"
        esc = html.escape(line)
        out.append(f'<span class="{cls}">{esc}</span>' if cls else esc)
    return "\n".join(out)


def to_html(results, summary, meta):
    e = html.escape
    tiles = "".join(
        f'<div class="tile"><b style="color:var(--{s})">{summary["counts"][s]}</b><span>{s}</span></div>'
        for s in reversed(SEVERITY))
    rows = []
    for r in results:
        first = r["findings"][0]["detail"] if r["findings"] else (
            "identical after " + ", ".join(r["noise_rules"]) if r["noise_rules"] else "identical")
        rows.append(
            f'<tr><td><span class="badge" style="background:var(--{r["verdict"]})">{r["verdict"]}</span></td>'
            f'<td><code>{e(r["case"])}</code></td><td class="num">{r["ms_old"]:.0f}</td>'
            f'<td class="num">{r["ms_new"]:.0f}</td><td>{e(first)}</td></tr>')
    details = []
    for r in results:
        shown = [f for f in r["findings"] if f["severity"] != "NOISE"]
        if not shown:
            continue
        body = "".join(
            f'<p><b>[{f["severity"]}]</b> {e(f["detail"])}</p>' + (f'<pre>{_diff_html(f["diff"])}</pre>' if f["diff"] else "")
            for f in shown)
        details.append(f'<details open><summary><span class="badge" style="background:var(--{r["verdict"]})">'
                       f'{r["verdict"]}</span> {e(r["case"])}</summary>{body}</details>')
    legend = " · ".join(f"<b>{s}</b> {e(MEANING[s])}" for s in reversed(SEVERITY))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>port-diff report</title><style>{CSS}</style></head>
<body><div class="wrap"><h1>port-diff report <small>{e(summary_line(summary))}</small></h1>
<div class="cmd">old: {e(meta.get('old', ''))}</div><div class="cmd">new: {e(meta.get('new', ''))}</div>
<div class="tiles">{tiles}</div>
<table><thead><tr><th>verdict</th><th>case</th><th>old ms</th><th>new ms</th><th>first finding</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
{''.join(details)}
<p class="legend">{legend}</p></div></body></html>
"""

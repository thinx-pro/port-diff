import io
import json
import os
import shlex
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from port_diff import cli  # noqa: E402
from port_diff.compare import compare  # noqa: E402
from port_diff.normalize import Normalizer  # noqa: E402
from port_diff.runner import Case, absolutize, discover_cases, run_case  # noqa: E402

PY = shlex.quote(sys.executable)


def obs(stdout="", stderr="", exit=0, status="ok", files=None, ms=10.0, workdir="/w"):
    return {"stdout": stdout, "stderr": stderr, "exit": exit, "status": status, "files": files or {},
            "deleted": [], "ms": ms, "ms_median": ms, "workdirs": [workdir], "repeat_outputs": []}


def ftext(text):
    import hashlib
    return {"sha256": hashlib.sha256(text.encode()).hexdigest(), "size": len(text), "text": text}


class NormalizeTests(unittest.TestCase):
    def test_defaults_absorb_timing_and_paths(self):
        n = Normalizer()
        a, _ = n.apply("done in 12ms at 2026-10-12T08:00:01Z in /w/x\n", {"workdirs": ["/w"]}, "stdout")
        b, touched = n.apply("done in 3.5ms at 2026-10-11 23:59:59 in /v/x  \n\n", {"workdirs": ["/v"]}, "stdout")
        self.assertEqual(a, b)
        self.assertIn("durations", touched)

    def test_scoped_and_arg_specs(self):
        n = Normalizer(["floats=3:stdout", "sort-lines:stderr"], raw=True)
        self.assertEqual(n.apply("pi 3.14159\n", {}, "stdout")[0], "pi 3.14\n")
        self.assertEqual(n.apply("pi 3.14159\n", {}, "stderr")[0], "pi 3.14159\n")
        self.assertEqual(n.apply("b\na\n", {}, "stderr")[0], "a\nb\n")

    def test_json_and_sub(self):
        n = Normalizer(["json"], subs=[r"id=\d+=>id=N"], raw=True)
        self.assertEqual(n.apply('{"b":1,"a":2}', {}, "files")[0], n.apply('{"a": 2, "b": 1}', {}, "files")[0])
        self.assertEqual(n.apply("id=42", {}, "stdout")[0], "id=N")

    def test_unknown_rule_rejected(self):
        with self.assertRaises(ValueError):
            Normalizer(["nope"])
        with self.assertRaises(ValueError):
            Normalizer(["json:bogus"])

    def test_raw_keeps_differences(self):
        n = Normalizer(raw=True)
        self.assertNotEqual(n.apply("1ms", {}, "stdout")[0], n.apply("2ms", {}, "stdout")[0])


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.n = Normalizer()

    def test_same(self):
        r = compare("c", obs("x\n"), obs("x\n"), self.n)
        self.assertEqual(r["verdict"], "SAME")

    def test_noise(self):
        r = compare("c", obs("took 5ms\n"), obs("took 7ms\n"), self.n)
        self.assertEqual(r["verdict"], "NOISE")
        self.assertEqual(r["noise_rules"], ["durations"])

    def test_exit_code_is_break(self):
        r = compare("c", obs(exit=0), obs(exit=1), self.n)
        self.assertEqual(r["verdict"], "BREAK")

    def test_timeout_is_break(self):
        r = compare("c", obs(), obs(exit=None, status="timeout"), self.n)
        self.assertEqual(r["verdict"], "BREAK")
        self.assertIn("timeout", r["findings"][0]["detail"])

    def test_stdout_diff_and_stderr_warn(self):
        self.assertEqual(compare("c", obs("a"), obs("b"), self.n)["verdict"], "DIFF")
        self.assertEqual(compare("c", obs(stderr="a"), obs(stderr="b"), self.n)["verdict"], "WARN")
        self.assertEqual(compare("c", obs(stderr="a"), obs(stderr="b"), self.n, strict_stderr=True)["verdict"], "DIFF")

    def test_files(self):
        old = obs(files={"out.txt": ftext("1"), "gone.txt": ftext("g")})
        new = obs(files={"out.txt": ftext("2"), "extra.txt": ftext("e")})
        r = compare("c", old, new, self.n)
        kinds = sorted(f["detail"].split(":")[0] for f in r["findings"])
        self.assertEqual(kinds, ["extra.txt", "gone.txt", "out.txt"])
        self.assertEqual(r["verdict"], "BREAK")

    def test_perf_needs_ratio_and_absolute(self):
        self.assertEqual(compare("c", obs(ms=10), obs(ms=50), self.n)["verdict"], "SAME")  # 5x but only 40ms
        self.assertEqual(compare("c", obs(ms=100), obs(ms=180), self.n)["verdict"], "SAME")  # 80ms but 1.8x
        self.assertEqual(compare("c", obs(ms=100), obs(ms=400), self.n)["verdict"], "PERF")

    def test_flaky_old_is_warned(self):
        old = obs("1\n")
        old["repeat_outputs"] = [{"status": "ok", "exit": 0, "stdout": "2\n", "stderr": "", "files": {}, "workdirs": ["/w"]}]
        r = compare("c", old, obs("1\n"), self.n)
        self.assertEqual(r["verdict"], "WARN")
        self.assertIn("nondeterministic", r["findings"][0]["detail"])


class RunnerTests(unittest.TestCase):
    def test_absolutize(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "old"))
            open(os.path.join(d, "old", "tool.py"), "w").close()
            t = absolutize("python3 old/tool.py {case} --out x.json | sort", here=d)
            self.assertIn(os.path.join(d, "old", "tool.py"), t)
            self.assertIn("x.json | sort", t)
            self.assertTrue(t.startswith("python3 "))
            self.assertIn(shlex.quote(d), absolutize("cd {here}", here=d))

    def test_run_case_captures_files_and_isolation(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "in.txt")
            with open(p, "w") as fh:
                fh.write("hello")
            case = Case("in.txt", path=p)
            cmd = f"{PY} -c \"import sys;d=open(sys.argv[1]).read();open('out.txt','w').write(d.upper());print(len(d))\" {{case}}"
            o = run_case(cmd, case, repeat=2)
            self.assertEqual(o["exit"], 0)
            self.assertEqual(o["stdout"].strip(), "5")
            self.assertEqual(o["files"]["out.txt"]["text"], "HELLO")
            self.assertNotIn("in.txt", o["files"])  # unchanged inputs are not artefacts
            self.assertEqual(len(o["ms_all"]), 2)
            self.assertFalse(os.path.exists(o["workdirs"][0]))  # scratch dir cleaned up

    def test_timeout(self):
        o = run_case(f"{PY} -c \"import time;time.sleep(5)\"", Case("t"), timeout=0.5)
        self.assertEqual(o["status"], "timeout")

    def test_discover(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "cases"))
            for n in ("b.txt", "a.txt", ".hidden"):
                open(os.path.join(d, "cases", n), "w").close()
            with open(os.path.join(d, "args.txt"), "w") as fh:
                fh.write("# comment\n--help\n\n--version\n")
            cs = discover_cases(os.path.join(d, "cases"), os.path.join(d, "args.txt"))
            self.assertEqual([c.name for c in cs], ["a.txt", "b.txt", "args-001", "args-002"])
            self.assertEqual(cs[3].args, "--version")


class CliTests(unittest.TestCase):
    def _cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_run_json_and_exit_status(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "args.txt"), "w") as fh:
                fh.write("1\n2\n")
            old = f"{PY} -c \"import sys;print(int(sys.argv[1])*2)\" {{args}}"
            new = f"{PY} -c \"import sys;n=int(sys.argv[1]);print(n*2 if n==1 else n*3)\" {{args}}"
            code, out, _ = self._cli("run", "--old", old, "--new", new, "--args-file", os.path.join(d, "args.txt"), "--json", "-")
            self.assertEqual(code, 1)
            data = json.loads(out)
            self.assertEqual([r["verdict"] for r in data["results"]], ["SAME", "DIFF"])
            code, _, _ = self._cli("run", "--old", old, "--new", new, "--args-file", os.path.join(d, "args.txt"),
                                   "--json", os.path.join(d, "r.json"), "--fail-on", "break", "-q")
            self.assertEqual(code, 0)

    def test_record_then_check(self):
        with tempfile.TemporaryDirectory() as d:
            cases = os.path.join(d, "cases")
            os.makedirs(cases)
            with open(os.path.join(cases, "x.txt"), "w") as fh:
                fh.write("abc")
            base = os.path.join(d, "base.json")
            cat = f"{PY} -c \"import sys;print(open(sys.argv[1]).read())\" {{case}}"
            code, _, _ = self._cli("record", "--old", cat, "--cases", cases, "--out", base)
            self.assertEqual(code, 0)
            code, out, _ = self._cli("check", "--new", cat, "--cases", cases, "--baseline", base, "--json", "-")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["results"][0]["verdict"], "SAME")
            html = os.path.join(d, "r.html")
            md = os.path.join(d, "r.md")
            rev = f"{PY} -c \"import sys;print(open(sys.argv[1]).read()[::-1])\" {{case}}"
            code, _, _ = self._cli("check", "--new", rev, "--cases", cases, "--baseline", base, "--html", html, "--md", md, "-q")
            self.assertEqual(code, 1)
            with open(html) as fh:
                self.assertIn("DIFF", fh.read())
            with open(md) as fh:
                self.assertIn("```diff", fh.read())

    def test_usage_errors(self):
        self.assertEqual(self._cli("run", "--old", "true", "--new", "true")[0], 2)  # no cases
        self.assertEqual(self._cli()[0], 2)


if __name__ == "__main__":
    unittest.main()

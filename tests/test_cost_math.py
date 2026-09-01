#!/usr/bin/env python3
"""Unit tests for the cost-math helper that lives inside spend-cap.json.

The helper is JavaScript in an n8n Code node, so there is no second Python copy
to drift out of sync. This test extracts the block between the
"--- COST MATH START ---" and "--- COST MATH END ---" sentinels straight out of
the workflow JSON, appends a small harness, and runs it with node. If someone
edits the cost math in the n8n editor and re-exports the JSON, these tests still
test the real code.

Requires: node on PATH.
Run:      python tests/test_cost_math.py
Exit:     0 = pass, 1 = fail, 2 = cannot run (node missing).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SPEND_CAP = os.path.join(REPO, "workflows", "spend-cap.json")
START = "// --- COST MATH START ---"
END = "// --- COST MATH END ---"

# (label, model, input_tokens, output_tokens, expected_usd)
CASES = [
    # Exact table hit. 1M in at 2.5 + 1M out at 10.0
    ("exact model name", "gpt-4o", 1000000, 1000000, 12.5),
    # Sub-million arithmetic, rounded to 6 dp.
    ("small call", "gpt-4o-mini", 1200, 300, 0.00036),
    # Case and whitespace are normalised.
    ("case insensitive", "  GPT-4O  ", 1000000, 0, 2.5),
    # Longest prefix wins: 'gpt-4o-mini-2024-07-18' must NOT price as 'gpt-4o'.
    ("longest prefix wins", "gpt-4o-mini-2024-07-18", 1000000, 0, 0.15),
    # Versioned name falls back to its prefix.
    ("versioned prefix", "claude-sonnet-4-20250514", 1000000, 0, 3.0),
    # Unknown model uses the pessimistic default, never zero.
    ("unknown model uses default", "some-new-model", 1000000, 1000000, 20.0),
    # Missing / junk token counts coerce to 0 rather than NaN.
    ("null tokens", "gpt-4o", None, None, 0.0),
    ("string tokens", "gpt-4o", "1000000", "0", 2.5),
    ("garbage tokens", "gpt-4o", "not-a-number", 0, 0.0),
    # Empty model name still resolves to default, not a crash.
    ("empty model", "", 1000000, 0, 5.0),
    # Zero-token call is free but must not throw.
    ("zero call", "claude-opus", 0, 0, 0.0),
    # Expensive model, realistic-ish call.
    ("opus call", "claude-opus", 50000, 2000, 0.9),
]

THROW_CASES = [
    ("negative input tokens", "gpt-4o", -1, 0),
    ("negative output tokens", "gpt-4o", 0, -5),
]


def extract_cost_math():
    with open(SPEND_CAP, "r", encoding="utf-8") as f:
        doc = json.load(f)
    for node in doc.get("nodes", []):
        js = (node.get("parameters") or {}).get("jsCode")
        if isinstance(js, str) and START in js and END in js:
            block = js.split(START, 1)[1].split(END, 1)[0]
            return START + block + END
    raise SystemExit(
        "FAIL: could not find the cost-math sentinel block in {}".format(SPEND_CAP))


HARNESS = """
var CASES = __CASES__;
var THROWS = __THROWS__;
var results = { pass: [], fail: [] };

for (var i = 0; i < CASES.length; i++) {
  var c = CASES[i];
  var label = c[0];
  var got, err = null;
  try {
    got = estimateCostUsd(c[1], c[2], c[3], null);
  } catch (e) {
    err = String(e && e.message ? e.message : e);
  }
  if (err !== null) {
    results.fail.push(label + ': threw ' + err);
  } else if (Math.abs(got - c[4]) > 1e-9) {
    results.fail.push(label + ': expected ' + c[4] + ', got ' + got);
  } else {
    results.pass.push(label + ' -> ' + got);
  }
}

for (var k = 0; k < THROWS.length; k++) {
  var t = THROWS[k];
  var threw = false;
  try {
    estimateCostUsd(t[1], t[2], t[3], null);
  } catch (e) {
    threw = true;
  }
  if (threw) {
    results.pass.push(t[0] + ' -> threw as expected');
  } else {
    results.fail.push(t[0] + ': expected a throw, got a number');
  }
}

// A custom table must fully replace the defaults for models it defines.
var custom = { 'my-model': { input: 1.0, output: 2.0 }, 'default': { input: 9.0, output: 9.0 } };
var customCost = estimateCostUsd('my-model', 1000000, 1000000, custom);
if (Math.abs(customCost - 3.0) > 1e-9) {
  results.fail.push('custom table: expected 3, got ' + customCost);
} else {
  results.pass.push('custom table -> ' + customCost);
}
var customDefault = estimateCostUsd('gpt-4o', 1000000, 0, custom);
if (Math.abs(customDefault - 9.0) > 1e-9) {
  results.fail.push('custom table default: expected 9, got ' + customDefault);
} else {
  results.pass.push('custom table default -> ' + customDefault);
}

console.log(JSON.stringify(results));
"""


def main():
    node = shutil.which("node")
    if not node:
        print("SKIP: node is not on PATH; cannot execute the Code node JavaScript.")
        return 2

    script = (
        extract_cost_math()
        + "\n"
        + HARNESS.replace("__CASES__", json.dumps(CASES))
                 .replace("__THROWS__", json.dumps(THROW_CASES))
    )

    tmpdir = tempfile.mkdtemp(prefix="cb-cost-math-")
    tmp = os.path.join(tmpdir, "cost_math_test.js")
    try:
        with open(tmp, "w", encoding="ascii", newline="\n") as f:
            f.write(script)
        proc = subprocess.run([node, tmp], capture_output=True, text=True)
        if proc.returncode != 0:
            print("FAIL: node exited {}".format(proc.returncode))
            print(proc.stderr.strip())
            return 1
        results = json.loads(proc.stdout.strip().splitlines()[-1])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    for line in results["pass"]:
        print("[OK  ] {}".format(line))
    for line in results["fail"]:
        print("[FAIL] {}".format(line))

    print("")
    print("{} passed, {} failed".format(len(results["pass"]), len(results["fail"])))
    return 1 if results["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())

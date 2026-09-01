#!/usr/bin/env python3
"""Self-test for validate_workflows.py.

A validator that never fails is not a validator. This takes a real workflow from
workflows/, breaks it one way at a time in a temp directory, and asserts that
validate_workflows reports a failure for each mutation -- and still passes on the
untouched copy.

Run:  python tests/test_validator.py
Exit: 0 = pass, 1 = fail.
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
VALIDATOR = os.path.join(HERE, "validate_workflows.py")
SOURCE = os.path.join(REPO, "workflows", "spend-cap.json")


def load():
    with open(SOURCE, "r", encoding="utf-8") as f:
        return json.load(f)


def code_node(doc):
    for n in doc["nodes"]:
        if n["type"] == "n8n-nodes-base.code":
            return n
    raise SystemExit("FAIL: spend-cap.json has no Code node to mutate")


def drop_typeversion(doc):
    del doc["nodes"][1]["typeVersion"]


def dangling_connection(doc):
    first = list(doc["connections"].keys())[0]
    doc["connections"][first]["main"][0][0]["node"] = "A Node That Does Not Exist"


def duplicate_name(doc):
    doc["nodes"][2]["name"] = doc["nodes"][1]["name"]


def non_ascii_js(doc):
    n = code_node(doc)
    # U+2019 right single quotation mark: the classic paste-from-a-doc failure.
    # Written as an escape so this source file stays ASCII too.
    smart_quote = "\u2019"
    n["parameters"]["jsCode"] = (
        n["parameters"]["jsCode"] + "\n// don" + smart_quote + "t do this\n")


def kill_connections(doc):
    doc["connections"] = []


def kill_settings(doc):
    del doc["settings"]


def bad_position(doc):
    doc["nodes"][1]["position"] = "0,0"


def unknown_connection_key(doc):
    doc["connections"]["Ghost Node"] = {"main": [[]]}


MUTATIONS = [
    ("missing typeVersion", drop_typeversion),
    ("connection to a missing node", dangling_connection),
    ("duplicate node name", duplicate_name),
    ("non-ASCII jsCode", non_ascii_js),
    ("connections is not an object", kill_connections),
    ("missing settings", kill_settings),
    ("position is not [x, y]", bad_position),
    ("connections key is not a node", unknown_connection_key),
]


def run_validator(workdir):
    """Run the validator against a temp repo whose workflows/ dir we control."""
    proc = subprocess.run(
        [sys.executable, os.path.join(workdir, "tests", "validate_workflows.py")],
        capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def build_temp_repo(root, doc):
    os.makedirs(os.path.join(root, "workflows"), exist_ok=True)
    os.makedirs(os.path.join(root, "tests"), exist_ok=True)
    shutil.copyfile(VALIDATOR, os.path.join(root, "tests", "validate_workflows.py"))
    with open(os.path.join(root, "workflows", "spend-cap.json"), "w",
              encoding="ascii", newline="\n") as f:
        json.dump(doc, f, indent=2, ensure_ascii=True)


def main():
    base = load()
    passed, failed = [], []

    tmp = tempfile.mkdtemp(prefix="cb-validator-selftest-")
    try:
        # Control: the untouched copy must pass.
        control = os.path.join(tmp, "control")
        build_temp_repo(control, base)
        rc, out = run_validator(control)
        if rc == 0:
            passed.append("control (unmodified workflow) passes")
        else:
            failed.append("control should pass but exited {}:\n{}".format(rc, out))

        for i, (label, mutate) in enumerate(MUTATIONS):
            doc = copy.deepcopy(base)
            mutate(doc)
            d = os.path.join(tmp, "case{}".format(i))
            build_temp_repo(d, doc)
            rc, out = run_validator(d)
            if rc != 0:
                passed.append("caught: {}".format(label))
            else:
                failed.append("MISSED: {} was not reported".format(label))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    for line in passed:
        print("[OK  ] {}".format(line))
    for line in failed:
        print("[FAIL] {}".format(line))

    print("")
    print("{} passed, {} failed".format(len(passed), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

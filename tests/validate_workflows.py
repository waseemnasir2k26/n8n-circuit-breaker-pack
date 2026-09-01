#!/usr/bin/env python3
"""Structural validator for every workflow JSON in workflows/.

n8n will happily import a workflow that is subtly broken and only fail at run
time, and the n8n public API rejects Code nodes containing non-ASCII characters
with an unhelpful error. This script catches both before you import anything.

Run:  python tests/validate_workflows.py
Exit: 0 = all files valid, 1 = at least one failure.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
WORKFLOW_DIR = os.path.join(REPO, "workflows")

REQUIRED_NODE_FIELDS = ("id", "name", "type", "typeVersion", "position", "parameters")

# Node types that carry user JavaScript we must keep ASCII-only.
JS_FIELDS = {
    "n8n-nodes-base.code": ("jsCode",),
    "n8n-nodes-base.function": ("functionCode",),
    "n8n-nodes-base.functionItem": ("functionCode",),
}

# Every module must be reachable from something that can start it.
TRIGGER_MARKERS = ("Trigger", "webhook")


class Failure(Exception):
    pass


def fail(errors, path, msg):
    errors.append("{}: {}".format(os.path.basename(path), msg))


def non_ascii_positions(text):
    """Return [(index, char)] for every non-ASCII character in text."""
    bad = []
    for i, ch in enumerate(text):
        if ord(ch) > 127:
            bad.append((i, ch))
    return bad


def validate_file(path, errors):
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    try:
        doc = json.loads(raw)
    except ValueError as exc:
        fail(errors, path, "not valid JSON: {}".format(exc))
        return

    if not isinstance(doc, dict):
        fail(errors, path, "top level must be an object")
        return

    # --- top-level shape -------------------------------------------------
    nodes = doc.get("nodes")
    if not isinstance(nodes, list):
        fail(errors, path, "top-level 'nodes' must be an array")
        return
    if len(nodes) == 0:
        fail(errors, path, "'nodes' is empty")
        return

    connections = doc.get("connections")
    if not isinstance(connections, dict):
        fail(errors, path, "top-level 'connections' must be an object")
        return

    if not isinstance(doc.get("settings"), dict):
        fail(errors, path, "top-level 'settings' must be an object")

    if not isinstance(doc.get("name"), str) or not doc.get("name").strip():
        fail(errors, path, "top-level 'name' must be a non-empty string")

    # --- nodes -----------------------------------------------------------
    names = []
    ids = []
    for idx, node in enumerate(nodes):
        label = "node[{}]".format(idx)
        if not isinstance(node, dict):
            fail(errors, path, "{} is not an object".format(label))
            continue

        for field in REQUIRED_NODE_FIELDS:
            if field not in node:
                fail(errors, path, "{} missing required field '{}'".format(label, field))

        name = node.get("name")
        if isinstance(name, str) and name.strip():
            label = "node '{}'".format(name)
            names.append(name)
        else:
            fail(errors, path, "{} has an empty or non-string 'name'".format(label))

        node_id = node.get("id")
        if isinstance(node_id, str) and node_id.strip():
            ids.append(node_id)
        else:
            fail(errors, path, "{} has an empty or non-string 'id'".format(label))

        ntype = node.get("type")
        if not isinstance(ntype, str) or "." not in ntype:
            fail(errors, path, "{} has an invalid 'type': {!r}".format(label, ntype))

        tv = node.get("typeVersion")
        if not isinstance(tv, (int, float)) or isinstance(tv, bool):
            fail(errors, path, "{} 'typeVersion' must be a number".format(label))

        pos = node.get("position")
        if (not isinstance(pos, list) or len(pos) != 2
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in pos)):
            fail(errors, path, "{} 'position' must be [x, y] numbers".format(label))

        params = node.get("parameters")
        if not isinstance(params, dict):
            fail(errors, path, "{} 'parameters' must be an object".format(label))
            params = {}

        # --- ASCII-only JavaScript ---------------------------------------
        for field in JS_FIELDS.get(ntype, ()):
            js = params.get(field)
            if js is None:
                fail(errors, path, "{} is a {} but has no '{}'".format(label, ntype, field))
                continue
            if not isinstance(js, str):
                fail(errors, path, "{} '{}' must be a string".format(label, field))
                continue
            bad = non_ascii_positions(js)
            if bad:
                first_i, first_c = bad[0]
                fail(errors, path,
                     "{} '{}' contains {} non-ASCII character(s); first is U+{:04X} "
                     "at offset {} -- the n8n API rejects these"
                     .format(label, field, len(bad), ord(first_c), first_i))

    dupe_names = sorted({n for n in names if names.count(n) > 1})
    if dupe_names:
        fail(errors, path, "duplicate node names: {}".format(", ".join(dupe_names)))

    dupe_ids = sorted({i for i in ids if ids.count(i) > 1})
    if dupe_ids:
        fail(errors, path, "duplicate node ids: {}".format(", ".join(dupe_ids)))

    name_set = set(names)

    # --- connections -----------------------------------------------------
    for source, outputs in connections.items():
        if source not in name_set:
            fail(errors, path, "connections key '{}' is not a node in this workflow".format(source))
        if not isinstance(outputs, dict):
            fail(errors, path, "connections['{}'] must be an object".format(source))
            continue
        for out_type, branches in outputs.items():
            if not isinstance(branches, list):
                fail(errors, path,
                     "connections['{}']['{}'] must be an array".format(source, out_type))
                continue
            for b_i, branch in enumerate(branches):
                if branch is None:
                    continue
                if not isinstance(branch, list):
                    fail(errors, path,
                         "connections['{}']['{}'][{}] must be an array".format(
                             source, out_type, b_i))
                    continue
                for link in branch:
                    if not isinstance(link, dict):
                        fail(errors, path,
                             "connections['{}'] contains a non-object link".format(source))
                        continue
                    target = link.get("node")
                    if target not in name_set:
                        fail(errors, path,
                             "connection {} -> '{}' targets a node that does not exist"
                             .format(source, target))
                    if "type" not in link or "index" not in link:
                        fail(errors, path,
                             "connection {} -> '{}' missing 'type' or 'index'"
                             .format(source, target))

    # --- reachability: at least one trigger ------------------------------
    has_trigger = any(
        isinstance(n, dict) and isinstance(n.get("type"), str)
        and any(m.lower() in n["type"].lower() for m in TRIGGER_MARKERS)
        for n in nodes
    )
    if not has_trigger:
        fail(errors, path, "no trigger node found (nothing can start this workflow)")

    # --- orphan check: non-trigger nodes should be a connection target ----
    targets = set()
    for outputs in connections.values():
        if not isinstance(outputs, dict):
            continue
        for branches in outputs.values():
            if not isinstance(branches, list):
                continue
            for branch in branches:
                if isinstance(branch, list):
                    for link in branch:
                        if isinstance(link, dict) and isinstance(link.get("node"), str):
                            targets.add(link["node"])
    for n in nodes:
        if not isinstance(n, dict):
            continue
        name = n.get("name")
        ntype = n.get("type") or ""
        is_trigger = any(m.lower() in ntype.lower() for m in TRIGGER_MARKERS)
        if not is_trigger and name not in targets:
            fail(errors, path, "node '{}' is orphaned (no incoming connection)".format(name))


def main():
    if not os.path.isdir(WORKFLOW_DIR):
        print("FAIL: no workflows/ directory at {}".format(WORKFLOW_DIR))
        return 1

    files = sorted(
        os.path.join(WORKFLOW_DIR, f)
        for f in os.listdir(WORKFLOW_DIR)
        if f.endswith(".json")
    )
    if not files:
        print("FAIL: workflows/ contains no .json files")
        return 1

    errors = []
    for path in files:
        before = len(errors)
        validate_file(path, errors)
        status = "OK  " if len(errors) == before else "FAIL"
        try:
            with open(path, "r", encoding="utf-8") as f:
                node_count = len(json.load(f).get("nodes", []))
            detail = "{} nodes".format(node_count)
        except Exception:
            detail = "unreadable"
        print("[{}] {:<32} {}".format(status, os.path.basename(path), detail))

    print("")
    if errors:
        print("{} problem(s) found:".format(len(errors)))
        for e in errors:
            print("  - {}".format(e))
        return 1

    print("All {} workflow(s) valid: structure, node fields, connection targets, "
          "ASCII-only Code nodes.".format(len(files)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

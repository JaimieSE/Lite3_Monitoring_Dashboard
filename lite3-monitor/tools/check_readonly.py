#!/usr/bin/env python3
"""Static read-only audit for lite3-monitor.

Fails (exit 1) if the bridge or the web app contains anything that could
control the robot or execute commands:

  Python bridge (AST-based, comments/docstrings ignored):
    - publishers, service/action clients or servers, parameter mutation
    - process execution (subprocess, os.system, os.popen, exec, eval)
    - HTTP routes other than GET / websocket
    - any rclpy call other than an allow-listed set
  Web app (text scan of src/):
    - WebSocket .send( calls to the bridge (the dashboard never sends)
    - child_process / exec usage

Run:  python3 tools/check_readonly.py
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "bridge" / "lite3_bridge"
WEB_SRC = ROOT / "web" / "src"

FORBIDDEN_ATTRS = {
    "create_publisher", "create_client", "create_service", "create_guard_condition",
    "send_goal", "send_goal_async", "cancel_goal", "cancel_goal_async", "call", "call_async",
    "set_parameters", "set_parameters_atomically", "declare_parameter", "declare_parameters",
    "undeclare_parameter", "publish", "system", "popen", "spawn", "fork", "execv", "execvp",
    "post", "put", "delete", "patch",
}
FORBIDDEN_NAMES = {"ActionClient", "ActionServer", "Popen", "exec", "eval", "compile", "__import__"}
FORBIDDEN_IMPORTS = {"subprocess", "rclpy.action", "pty", "shlex", "multiprocessing"}
# Node methods the bridge is allowed to call.
ALLOWED_NODE_CALLS = {
    "create_subscription", "create_timer", "get_topic_names_and_types", "get_node_names_and_namespaces",
    "get_publishers_info_by_topic", "get_service_names_and_types", "destroy_publisher", "destroy_node", "publishers", "services", "clients",
}
# destroy_publisher is allowed ONLY to remove rclpy's built-in /parameter_events publisher.

errors: list[str] = []


def check_python(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rel = path.relative_to(ROOT)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
            # dict.pop/.get etc. are fine; flag only the forbidden names
            errors.append(f"{rel}:{node.lineno}: forbidden attribute '.{node.attr}'")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            errors.append(f"{rel}:{node.lineno}: forbidden name '{node.id}'")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for m in mods:
                if any(m == f or m.startswith(f + ".") for f in FORBIDDEN_IMPORTS):
                    errors.append(f"{rel}:{node.lineno}: forbidden import '{m}'")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            # self.node.<x>(...) / node.<x>(...) must be allow-listed
            owner_name = owner.attr if isinstance(owner, ast.Attribute) else getattr(owner, "id", "")
            if owner_name == "node" and node.func.attr not in ALLOWED_NODE_CALLS:
                errors.append(f"{rel}:{node.lineno}: node.{node.func.attr}() is not on the read-only allow-list")
    # destroy_publisher must only target the parameter-event publisher
    src = path.read_text(encoding="utf-8")
    for m in re.finditer(r"destroy_publisher\(([^)]*)\)", src):
        if m.group(1).strip() != "pub":
            errors.append(f"{rel}: unexpected destroy_publisher({m.group(1)})")


def check_web(path: Path) -> None:
    rel = path.relative_to(ROOT)
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if re.search(r"\b(ws|socket|websocket)\??\.send\(", line, re.I):
            errors.append(f"{rel}:{i}: dashboard must never send on the bridge websocket")
        if "child_process" in line or re.search(r"\bexecSync\b|\bspawn\(", line):
            errors.append(f"{rel}:{i}: process execution is not allowed in the web app")


def main() -> int:
    py_files = sorted(BRIDGE.rglob("*.py"))
    if not py_files:
        print("no bridge sources found", file=sys.stderr)
        return 2
    for p in py_files:
        check_python(p)
    web_files = sorted(list(WEB_SRC.rglob("*.ts")) + list(WEB_SRC.rglob("*.tsx"))) if WEB_SRC.exists() else []
    for p in web_files:
        check_web(p)
    if errors:
        print("READ-ONLY AUDIT FAILED:")
        for e in errors:
            print("  " + e)
        return 1
    print(f"read-only audit passed: {len(py_files)} bridge files, {len(web_files)} web files checked")
    return 0


if __name__ == "__main__":
    sys.exit(main())

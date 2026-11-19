"""Run Qiwen regression cases against a local Codex app server."""

import argparse
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
from queue import Empty, Queue
import re
import shutil
import subprocess
from threading import Thread
from time import monotonic
from uuid import uuid4


class AppServer:
    def __init__(self, executable, timeout):
        self.timeout = timeout
        self.messages = Queue()
        self.notifications = []
        self.request_id = 0
        self.process = subprocess.Popen(
            [executable, "app-server", "--stdio"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, text=True, encoding="utf-8", stderr=subprocess.DEVNULL,
        )
        Thread(target=self.read_messages, daemon=True).start()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)

    def read_messages(self):
        for line in self.process.stdout:
            self.messages.put(json.loads(line))
        self.messages.put(None)

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def receive(self, deadline):
        try:
            message = self.messages.get(timeout=max(0, deadline - monotonic()))
        except Empty as exc:
            raise TimeoutError("Codex app-server response timed out") from exc
        if message is None:
            raise RuntimeError("Codex app-server closed its event stream")
        if "method" in message and "id" in message:
            self.send({"id": message["id"], "error": {
                "code": -32601, "message": "This client accepts user decisions in the next chat turn.",
            }})
        return message

    def request(self, method, params):
        self.request_id += 1
        id_ = self.request_id
        self.send({"id": id_, "method": method, "params": params})
        deadline = monotonic() + self.timeout
        while True:
            message = self.receive(deadline)
            if message.get("id") == id_ and "method" not in message:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message["result"]
            self.notifications.append(message)

    def turn(self, thread_id, inputs):
        created = self.request("turn/start", {
            "threadId": thread_id, "input": inputs,
        })
        turn_id = created["turn"]["id"]
        items, requests = [], []
        deadline = monotonic() + self.timeout
        while True:
            message = self.notifications.pop(0) if self.notifications else self.receive(deadline)
            method, params = message.get("method"), message.get("params", {})
            if params.get("threadId") != thread_id:
                continue
            if method == "item/completed" and params["turnId"] == turn_id:
                items.append(params["item"])
            if "id" in message and method:
                requests.append(method)
            if method == "turn/completed" and params["turn"]["id"] == turn_id:
                return params["turn"], items, requests


def check(expect, final, questions, commands, earlier_commands=()):
    problems = []
    def successful_reads(items):
        return "\n".join(re.sub(r"[\\/]+", "/", item["command"].lower())
                         for item in items if item["exitCode"] == 0)

    successful = successful_reads(commands)
    all_commands = "\n".join(item["command"] for item in commands)
    for path in expect.get("reads", []):
        if path not in successful:
            problems.append(f"successful read was not observed: {path}")
    context_reads = successful + "\n" + successful_reads(earlier_commands)
    for path in expect.get("context_reads", []):
        if path not in context_reads:
            problems.append(f"successful read was not observed in the session: {path}")
    if "commands_exclude" in expect and re.search(expect["commands_exclude"], all_commands, re.I):
        problems.append("a command accessed content outside the expected scope")
    response = final + "\n" + questions
    for value in expect.get("contains", []):
        if value not in response:
            problems.append(f"missing response value: {value}")
    for pattern in expect.get("matches", []):
        if not re.search(pattern, response):
            problems.append(f"missing response pattern: {pattern}")
    if "excludes" in expect and re.search(expect["excludes"], response, re.I):
        problems.append("response matched a prohibited action or redundant question")
    if "question" in expect:
        asks_question = bool(questions or re.search(
            r"[？?]|(?:请(?:你|您)?|需要(?:你|您))\s*(?:确认|选择|决定|告诉我)", final
        ))
        if asks_question != expect["question"]:
            problems.append(f"question expected: {expect['question']}")
    if "exact" in expect and final.strip() != expect["exact"]:
        problems.append("final message differs from the expected exact answer")
    if "json" in expect:
        try:
            value = json.loads(final)
        except ValueError:
            value = None
        if value != expect["json"]:
            problems.append("final JSON differs from the expected result or has extra text")
    return problems


@contextmanager
def fixture_root(report_path):
    parent = report_path.resolve().parent
    parent.mkdir(parents=True, exist_ok=True)
    root = parent / f"qiwen-fixtures-{uuid4().hex}"
    # An ordinary mkdir inherits the parent's ACL, which the Windows sandbox can read.
    root.mkdir()
    try:
        yield root
    finally:
        if root.resolve() == root and root.parent == parent:
            shutil.rmtree(root)


def snapshot(folder):
    return {path.relative_to(folder).as_posix(): path.read_bytes() if path.is_file() else None
            for path in folder.rglob("*")}


def check_files(before, after, writes):
    problems, artifacts = [], {}
    changed = {name for name in before.keys() | after.keys()
               if name not in before or name not in after or before[name] != after[name]}
    if extra := changed - writes.keys():
        problems.append(f"changes outside the requested files: {', '.join(sorted(extra))}")
    for name, expect in writes.items():
        if name not in changed or after.get(name) is None:
            problems.append(f"expected file was not written: {name}")
            continue
        try:
            text = after[name].decode("utf-8-sig")
        except UnicodeError:
            problems.append(f"expected UTF-8 text: {name}")
            continue
        artifacts[name] = text
        problems.extend(f"{name}: {problem}" for problem in check(expect, text, "", []))
    return problems, artifacts


def run_case(server, case, folder, skills):
    folder.mkdir()
    fixture = {name: text.encode("utf-8") for name, text in case.get("files", {}).items()}
    for name, data in fixture.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    before = snapshot(folder)
    settings = {
        "cwd": str(folder), "ephemeral": True, "sandbox": "read-only", "approvalPolicy": "never",
    }
    writable = any(step["expect"].get("writes") for step in case["turns"])
    if writable:
        settings["sandbox"] = "workspace-write"
        settings["config"] = {"sandbox_workspace_write": {
            "writable_roots": [str(folder)], "exclude_tmpdir_env_var": True,
            "exclude_slash_tmp": True, "network_access": False,
        }}
    thread = server.request("thread/start", settings)
    sandbox = thread["sandbox"]
    if writable and (sandbox["type"] != "workspaceWrite" or Path(thread["cwd"]).resolve() != folder.resolve()
                     or {Path(path).resolve() for path in sandbox["writableRoots"]} - {folder.resolve()}
                     or not sandbox["excludeTmpdirEnvVar"] or not sandbox["excludeSlashTmp"]
                     or sandbox["networkAccess"]):
        raise RuntimeError("Codex did not confirm a write sandbox scoped to the temporary project")
    result = {"id": case["id"], "split": case.get("split", "development"), "model": thread.get("model"),
              "provider": thread.get("modelProvider"), "sandbox": sandbox, "turns": []}
    earlier_commands = []
    for entry in case["turns"]:
        inputs = [{"type": "text", "text": entry["prompt"]}]
        if name := entry.get("skill"):
            if name not in skills:
                raise RuntimeError(f"enabled skill was not discovered by Codex: {name}")
            inputs.append({"type": "skill", "name": name, "path": skills[name]})
        turn, items, requests = server.turn(thread["thread"]["id"], inputs)
        messages = [item for item in items if item["type"] == "agentMessage"]
        final = next((item["text"] for item in reversed(messages) if item.get("phase") == "final_answer"),
                     messages[-1]["text"] if messages else "")
        question_items = [item["questions"] for item in messages if item.get("questions")]
        questions = json.dumps(question_items, ensure_ascii=False) if question_items else ""
        commands = [{key: item.get(key) for key in ("command", "exitCode", "status")}
                    for item in items if item["type"] == "commandExecution"]
        problems = check(entry["expect"], final, questions, commands, earlier_commands)
        earlier_commands.extend(commands)
        writes = entry["expect"].get("writes", {})
        after = snapshot(folder)
        file_problems, artifacts = check_files(before, after, writes)
        problems.extend(file_problems)
        before = after
        allowed_paths = {(folder / name).resolve() for name in writes}
        for item in items:
            if item["type"] == "fileChange" and any(
                (folder / change["path"]).resolve() not in allowed_paths for change in item["changes"]
            ):
                problems.append("a file edit targeted a path outside the requested files")
            if item["type"] == "mcpToolCall" and item.get("readOnlyHint") is not True:
                problems.append("an MCP call exceeded the read-only scope")
        if turn["status"] != "completed":
            problems.append(f"turn did not complete: {turn.get('error') or turn['status']}")
        result["turns"].append({
            "status": turn["status"], "final": final, "questions": question_items, "explicit_skill": entry.get("skill"),
            "commentary": [item["text"] for item in messages if item.get("phase") == "commentary"],
            "commands": commands, "requests": requests, "problems": problems, "written_files": artifacts,
        })
        if turn["status"] != "completed":
            break
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default=shutil.which("codex.exe") or shutil.which("codex"))
    parser.add_argument("--report", type=Path, required=True, help="Local JSON report file")
    parser.add_argument("--timeout", type=int, default=150, help="Seconds per response or turn")
    parser.add_argument("case", nargs="*", help="Optional case IDs. The default runs all cases.")
    args = parser.parse_args()
    if not args.codex:
        parser.error("Codex executable was not found")
    case_bytes = Path(__file__).with_name("cases.json").read_bytes()
    cases = [case for case in json.loads(case_bytes) if not args.case or case["id"] in args.case]
    if not cases or set(args.case) - {case["id"] for case in cases}:
        parser.error("unknown case ID")
    skill = Path(__file__).resolve().parents[1]
    sources = [skill / "SKILL.md", skill / "references/grilling.md", skill / "references/domain-handoff.md",
               skill.parent / "yanlu/SKILL.md", skill.parent / "yanlu/modules/grilling/GUIDE.md",
               skill.parent / "yanlu/modules/domain-modeling/GUIDE.md"]
    report = {
        "case_sha256": sha256(case_bytes).hexdigest(),
        "runner_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_sha256": {str(f): sha256(f.read_bytes()).hexdigest() for f in sources},
        "cases": [],
    }
    with fixture_root(args.report) as scratch, AppServer(args.codex, args.timeout) as server:
        server.request("initialize", {"clientInfo": {"name": "qiwen-regression", "version": "1"}})
        server.send({"method": "initialized", "params": {}})
        catalog = server.request("skills/list", {"cwds": [str(scratch)], "forceReload": True})
        installed = {item["name"]: item["path"] for entry in catalog["data"] for item in entry["skills"]
                     if item["enabled"] and item["name"] in {"qiwen", "yanlu"}}
        report["discovered_skills"] = installed
        shared_instructions = Path.home() / ".codex/AGENTS.md"
        if shared_instructions.is_file():
            report["source_sha256"][str(shared_instructions)] = sha256(shared_instructions.read_bytes()).hexdigest()
        for case in cases:
            try:
                result = run_case(server, case, scratch / case["id"], installed)
                result["status"] = "fail" if any(turn["problems"] for turn in result["turns"]) else "pass"
            except (RuntimeError, TimeoutError) as exc:
                result = {"id": case["id"], "status": "blocked", "error": str(exc)}
            report["cases"].append(result)
            print(f"{case['id']}: {result['status']}", flush=True)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return int(any(case["status"] != "pass" for case in report["cases"]))


if __name__ == "__main__":
    raise SystemExit(main())

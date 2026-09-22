"""只读检查 Trellis Session 交接；不修改 Task、指针、Journal 或 Git。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone


# 中文说明：结构名称与 Harness 规范保持一致，禁止静默接受重复字段。
SECTIONS = (
    "Identity", "Current Position", "Progress Since Previous Checkpoint",
    "Decisions", "Rejected Approaches", "Known Issues / Blockers", "Verification",
    "Workspace Snapshot", "Uncommitted Work Ownership", "Next Action",
    "Resume Constraints",
)
STATUSES = {"pass", "fail", "blocked", "skipped"}
SNAPSHOT_PATHS = ("--", ".", ":(exclude,glob).trellis/tasks/*/verification.json")


def git(workspace: Path, *args: str, allowed: tuple[int, ...] = (0,)) -> bytes:
    """保留 Git 原始字节；现有公共封装会替换解码错误，不适合稳定指纹。"""
    # 不让外部 Git 环境变量把显式工作区重定向到其他仓库或 index。
    environment = os.environ.copy()
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        environment.pop(name, None)
    result = subprocess.run(
        ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", *args], cwd=workspace,
        capture_output=True, env=environment, timeout=60,
    )
    if result.returncode not in allowed:
        # stderr 可能包含敏感路径或外部程序输出；只报告操作与退出码。
        raise ValueError(f"Git {args[0]} failed (exit {result.returncode}); check repository/access.")
    return result.stdout


def repository(workspace: str | Path) -> Path:
    """将 cwd 或显式目录归一到当前 Git worktree 根目录。"""
    directory = Path(workspace).resolve(strict=True)
    return Path(os.fsdecode(git(directory, "rev-parse", "--show-toplevel").strip())).resolve()


def snapshot(workspace: Path) -> dict:
    """输出可恢复定位信息及只读代码指纹，未跟踪文件只读取 lstat 元数据。"""
    # 固定 diff 选项，禁用可能执行外部程序的 textconv / external diff。
    options = (
        "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames",
        "--ignore-submodules=none", "--no-relative", "--no-indent-heuristic",
        "--diff-algorithm=myers", "--src-prefix=a/", "--dst-prefix=b/", "--unified=3",
    )
    # verification.json is the Gate's generated runtime artifact; including it would
    # make a freshly written verification stale itself.
    staged = git(workspace, "diff", "--cached", *options, "--binary", "--full-index", *SNAPSHOT_PATHS)
    unstaged = git(workspace, "diff", *options, "--binary", "--full-index", *SNAPSHOT_PATHS)
    staged_files = sorted(os.fsdecode(item) for item in git(
        workspace, "diff", "--cached", *options, "--name-only", "-z", *SNAPSHOT_PATHS
    ).split(b"\0") if item)
    unstaged_files = sorted(os.fsdecode(item) for item in git(
        workspace, "diff", *options, "--name-only", "-z", *SNAPSHOT_PATHS
    ).split(b"\0") if item)
    untracked_files = sorted(os.fsdecode(item) for item in git(
        workspace, "ls-files", "--others", "--exclude-standard", "-z", *SNAPSHOT_PATHS
    ).split(b"\0") if item)
    untracked_metadata = []
    for name in untracked_files:
        path = workspace / name
        if not path.parent.resolve().is_relative_to(workspace):
            raise ValueError("Untracked path resolves outside workspace; retry after inspecting Git state.")
        metadata = path.lstat()
        untracked_metadata.append([name, metadata.st_size, metadata.st_mtime_ns])
    # ponytail: 未跟踪文件仅比较路径/大小/mtime；需要检测保留元数据的改动时再扩展。
    fingerprint = hashlib.sha256()
    for part in (staged, unstaged, json.dumps(untracked_metadata, separators=(",", ":")).encode()):
        fingerprint.update(len(part).to_bytes(8, "big"))
        fingerprint.update(part)
    return {
        "repository_root": str(workspace), "workspace_path": str(workspace),
        "branch": git(workspace, "symbolic-ref", "--quiet", "--short", "HEAD", allowed=(0, 1)).decode().strip() or "DETACHED",
        "head": git(workspace, "rev-parse", "--verify", "--quiet", "HEAD", allowed=(0, 1)).decode().strip() or "UNBORN",
        "dirty": bool(staged_files or unstaged_files or untracked_files),
        "staged_changed_files": staged_files, "unstaged_changed_files": unstaged_files,
        "untracked_files": untracked_files, "diff_fingerprint": fingerprint.hexdigest(),
        "checkpoint_at": datetime.now(timezone.utc).isoformat(),
        "source_session": os.environ.get("CODEX_SESSION_ID") or os.environ.get("CODEX_THREAD_ID") or None,
    }


def structural_text(text: str) -> str:
    """隐藏 Markdown 围栏正文，避免把代码示例误认成真实 section 或字段。"""
    lines = []
    fence = ""
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if not fence:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = ""
            lines.append("")
        else:
            lines.append("" if fence else line)
    return "\n".join(lines)


def fields(text: str, names: tuple[str, ...], section: str, errors: list[str]) -> dict:
    """读取单行 Key: value 字段，并累积缺失、重复或空值的诊断。"""
    values = {}
    for name in names:
        matches = re.findall(rf"^{re.escape(name)}:[ \t]*(.*)$", text, re.MULTILINE)
        if len(matches) != 1 or not matches[0].strip():
            errors.append(f"{section}: {name} must appear once with a non-empty value.")
        values[name] = matches[0].strip() if matches else ""
    return values


def checkpoint_time(value: str) -> datetime:
    """要求带时区的 ISO 8601 时间，以便跨 Session 稳定排序。"""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone missing")
    return parsed


def read_handoff(handoff: str | Path, workspace: Path) -> dict:
    """先检查真实路径和 Task 状态，再解析交接；不读取越界文件。"""
    errors = []
    path = Path(handoff)
    if not path.is_absolute():
        path = workspace / path
    path = Path(os.path.abspath(path))
    tasks = workspace / ".trellis" / "tasks"
    task = path.parent
    if (tasks.resolve() != tasks or task.parent != tasks or task.name.lower() == "archive"
            or task.resolve() != task or path.name != "handoff.md" or path.resolve() != path):
        raise ValueError("handoff must be a real handoff.md in a direct, non-archive .trellis/tasks/<task> directory; symlink/junction aliases are not allowed.")
    if not path.is_file():
        raise ValueError("handoff.md does not exist in the specified Task.")
    metadata_path = task / "task.json"
    if metadata_path.resolve() != metadata_path or not metadata_path.is_file():
        raise ValueError("Task task.json is missing or resolves through a symlink/junction.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    if not isinstance(metadata, dict) or not isinstance(metadata.get("status"), str) or not metadata["status"].strip():
        raise ValueError("Task task.json must contain a non-empty status.")
    if metadata["status"].strip().lower() == "completed":
        raise ValueError("Task status is completed; it cannot be resumed by handoff.")
    text = structural_text(path.read_text(encoding="utf-8-sig"))
    headings = list(re.finditer(r"^## ([^\n]+)$", text, re.MULTILINE))
    sections = {}
    for index, heading in enumerate(headings):
        name = heading.group(1).strip()
        if name in sections:
            errors.append(f"Duplicate section: {name}.")
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        sections[name] = text[heading.end():end].strip()
    for name in SECTIONS:
        if not sections.get(name):
            errors.append(f"Missing or empty section: {name}.")
    identity = fields(sections.get("Identity", ""), (
        "Task", "Checkpoint At", "Source Session", "Workspace",
    ), "Identity", errors)
    position = fields(sections.get("Current Position", ""), ("Phase", "Current Focus"), "Current Position", errors)
    saved = fields(sections.get("Workspace Snapshot", ""), (
        "Branch", "HEAD", "Dirty", "Diff Fingerprint",
    ), "Workspace Snapshot", errors)
    next_action = fields(sections.get("Next Action", ""), ("Action", "Expected Result"), "Next Action", errors)
    identity_task = Path(identity["Task"])
    if not identity_task.is_absolute():
        identity_task = workspace / identity_task
    if identity_task.resolve() != task or Path(os.path.abspath(identity_task)) != task:
        errors.append("Identity: Task must name the same direct Task directory containing handoff.md.")
    if not Path(identity["Workspace"]).is_absolute():
        errors.append("Identity: Workspace must be an absolute path.")
    try:
        checkpoint_time(identity["Checkpoint At"])
    except ValueError:
        errors.append("Identity: Checkpoint At must be ISO 8601 with a timezone.")
    if not re.fullmatch(r"UNBORN|[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", saved["HEAD"]):
        errors.append("Workspace Snapshot: HEAD must be a full Git object ID or UNBORN.")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", saved["Diff Fingerprint"]):
        errors.append("Workspace Snapshot: Diff Fingerprint must be a SHA-256 hex digest.")
    if saved["Dirty"] not in ("true", "false"):
        errors.append("Workspace Snapshot: Dirty must be true or false.")
    verification = []
    items = list(re.finditer(r"^### ([^\n]+)$", sections.get("Verification", ""), re.MULTILINE))
    if not items:
        errors.append("Verification: at least one ### item is required (use skipped if not run).")
    for index, item in enumerate(items):
        name = item.group(1).strip()
        end = items[index + 1].start() if index + 1 < len(items) else len(sections["Verification"])
        values = fields(sections["Verification"][item.end():end], (
            "Status", "Command / Method", "Scope", "Evidence", "Notes",
        ), f"Verification/{name}", errors)
        if not name or name in [entry["name"] for entry in verification]:
            errors.append("Verification: item names must be non-empty and unique.")
        if values["Status"] not in STATUSES:
            errors.append(f"Verification/{name}: Status must be pass, fail, blocked or skipped.")
        verification.append({"name": name, "status": values["Status"]})
    return {
        "valid": not errors, "errors": errors, "task": task.relative_to(workspace).as_posix(),
        "handoff": str(path), "identity": identity, "position": position,
        "snapshot": saved, "next_action": next_action, "verification": verification,
    }


def compare(handoff: dict, current: dict) -> dict:
    """比较身份和 Git 状态；任何差异都使旧验证需要重新确认。"""
    saved = handoff["snapshot"]
    changes = {
        "head_changed": saved["HEAD"].lower() != current["head"].lower(),
        "diff_changed": saved["Diff Fingerprint"].lower() != current["diff_fingerprint"].lower(),
        "branch_changed": saved["Branch"] != current["branch"],
        "workspace_changed": Path(handoff["identity"]["Workspace"]).resolve() != Path(current["workspace_path"]),
    }
    stale = any(changes.values())
    return {
        "same_code_state": not stale, **changes,
        "verification_status": "potentially stale" if stale else "current",
        "message": "Previous verification may be stale." if stale else "Checkpoint code state matches current workspace.",
        "requires_reverification": handoff["verification"] if stale else [],
    }


def candidates(workspace: Path) -> dict:
    """展示有效候选；只有唯一 workspace+branch 匹配才允许自动采用。"""
    current = snapshot(workspace)
    found = []
    rejected = []
    tasks = workspace / ".trellis" / "tasks"
    if tasks.resolve() != tasks:
        raise ValueError(".trellis/tasks resolves through a symlink/junction.")
    for task in sorted(tasks.iterdir()) if tasks.is_dir() else []:
        if task.name.lower() == "archive" or not task.is_dir() or not (task / "handoff.md").is_file():
            continue
        try:
            handoff = read_handoff(task / "handoff.md", workspace)
            if not handoff["valid"]:
                raise ValueError("; ".join(handoff["errors"]))
            changes = compare(handoff, current)
            found.append({
                "task": handoff["task"], "handoff": handoff["handoff"],
                "checkpoint_at": handoff["identity"]["Checkpoint At"],
                "workspace_match": not changes["workspace_changed"],
                "branch_match": not changes["branch_changed"],
                "current_focus": handoff["position"]["Current Focus"],
            })
        except (OSError, ValueError) as error:
            rejected.append({"task": task.name, "error": str(error)})
    found.sort(key=lambda item: (
        item["workspace_match"], item["branch_match"], checkpoint_time(item["checkpoint_at"]),
    ), reverse=True)
    confident = [item for item in found if item["workspace_match"] and item["branch_match"]]
    selected = confident[0]["task"] if len(confident) == 1 else None
    return {
        "candidates": found, "rejected": rejected, "selected_task": selected,
        "ambiguous": selected is None and len(found) > 1,
        "selection_status": "selected" if selected else "ambiguous" if len(found) > 1 else "explicit_task_required" if found else "none",
    }


def main() -> int:
    """所有正常结果输出 JSON；结构或运行失败返回非零，stale 比较仍成功。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".", help="Git worktree or a directory within it")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("snapshot", "validate", "compare", "candidates"):
        command = commands.add_parser(name)
        command.add_argument("--workspace", default=argparse.SUPPRESS)
        if name in ("validate", "compare"):
            command.add_argument("handoff")
    args = parser.parse_args()
    try:
        workspace = repository(args.workspace)
        if args.command == "snapshot":
            result = snapshot(workspace)
        elif args.command == "candidates":
            result = candidates(workspace)
        else:
            result = read_handoff(args.handoff, workspace)
            if result["valid"] and args.command == "compare":
                result = compare(result, snapshot(workspace))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        # 不回显用户文件正文，JSONDecodeError 只包含位置，不包含原文。
        result = {"valid": False, "errors": [str(error)]}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 1 if result.get("valid") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())

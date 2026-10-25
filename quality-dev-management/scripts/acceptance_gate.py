#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""acceptance_gate.py —— 验收闸门（零依赖，仅标准库）

用途：读一份验收清单 JSON，逐项执行检查，输出逐条结果与缺项清单。

退出码口径（唯一源：`00_工程规范.md` §三「退出码 rc 四档口径」）：
    0  干净 / 全过       判据跑完了，结论是没问题
    1  检出              判据跑完了，确实有未过项
    2  调用层崩了        本脚本自身异常（Traceback / 内部不一致）
    3  判据不可用（报灰）清单缺失/损坏/不合规、外部命令不可执行、超时
优先级：报灰(3) > 检出(1) > 全过(0)。「没查出来」绝不返回 0。

清单格式（items 每项一个检查，支持五类 type）：
    {
      "name": "示例验收清单",
      "base_dir": ".",                      // 可选，相对清单文件所在目录
      "items": [
        {"id": "AC-01", "desc": "SKILL.md 存在",
         "type": "file_exists", "path": "SKILL.md"},
        {"id": "AC-02", "desc": "含 frontmatter name",
         "type": "file_contains", "path": "SKILL.md",
         "patterns": ["name: quality-dev-management"], "min_hits": 1},
        {"id": "AC-03", "desc": "不该存在的文件",
         "type": "file_absent", "path": "TODO.md"},
        {"id": "AC-04", "desc": "行数在 200~320",
         "type": "line_count", "path": "SKILL.md", "min": 200, "max": 320},
        {"id": "AC-05", "desc": "脚本可编译",
         "type": "command", "cmd": ["python", "-m", "py_compile", "a.py"],
         "expect_rc": 0, "timeout": 60}
      ]
    }

用法：
    python acceptance_gate.py <验收清单.json>
    python acceptance_gate.py --example
    python acceptance_gate.py --selftest
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RC_OK = 0
RC_FOUND = 1
RC_CRASH = 2
RC_UNAVAILABLE = 3

KNOWN_TYPES = ("file_exists", "file_absent", "file_contains", "line_count", "command")

EXAMPLE = {
    "name": "示例验收清单（按项目替换）",
    "base_dir": ".",
    "items": [
        {"id": "AC-01", "desc": "主文档存在且非空", "type": "file_exists", "path": "SKILL.md"},
        {
            "id": "AC-02",
            "desc": "主文档含 frontmatter name",
            "type": "file_contains",
            "path": "SKILL.md",
            "patterns": ["name: quality-dev-management"],
            "min_hits": 1,
        },
        {"id": "AC-03", "desc": "临时占位文件已清理", "type": "file_absent", "path": "TODO.md"},
        {"id": "AC-04", "desc": "主文档 200~320 行", "type": "line_count", "path": "SKILL.md", "min": 200, "max": 320},
        {
            "id": "AC-05",
            "desc": "脚本可编译",
            "type": "command",
            "cmd": [sys.executable, "-m", "py_compile", "scripts/acceptance_gate.py"],
            "expect_rc": 0,
            "timeout": 60,
        },
    ],
}


class Unavailable(Exception):
    """判据不可用（rc=3）：清单缺失/损坏/不合规、外部依赖不可执行。"""


class UsageError(Exception):
    """用法错（rc=3）：参数写错不是检出，也不是崩溃。"""


# ---------------------------------------------------------------- 清单读取


def load_checklist(path: Path) -> tuple[list[dict], Path]:
    """读取并校验清单，返回 (items, base_dir)。任何不合规都抛 Unavailable。"""
    if not path.exists():
        raise Unavailable(f"清单不存在：{path}")
    if not path.is_file():
        raise Unavailable(f"清单不是文件：{path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise Unavailable(f"清单读不出来：{path}（{exc}）") from exc
    if not raw.strip():
        raise Unavailable(f"清单是空文件：{path}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Unavailable(f"清单不是合法 JSON：{path}（第 {exc.lineno} 行：{exc.msg}）") from exc
    if not isinstance(data, dict):
        raise Unavailable("清单顶层必须是对象 {…}")

    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise Unavailable("清单缺少非空的 items 数组")

    base = path.parent
    base_dir_field = data.get("base_dir")
    if base_dir_field is not None:
        if not isinstance(base_dir_field, str) or not base_dir_field.strip():
            raise Unavailable("base_dir 必须是非空字符串")
        base = (path.parent / base_dir_field).resolve()
    if not base.is_dir():
        raise Unavailable(f"base_dir 不是目录：{base}")

    seen: set[str] = set()
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise Unavailable(f"items 第 {idx} 项不是对象")
        iid = item.get("id")
        if not isinstance(iid, str) or not iid.strip():
            raise Unavailable(f"items 第 {idx} 项缺少非空字符串 id")
        if iid in seen:
            raise Unavailable(f"items 中 id 重复：{iid}")
        seen.add(iid)
        typ = item.get("type")
        if typ not in KNOWN_TYPES:
            raise Unavailable(f"{iid} 的 type 不支持：{typ!r}（可选 {'/'.join(KNOWN_TYPES)}）")
        if typ in ("file_exists", "file_absent", "file_contains", "line_count"):
            p = item.get("path")
            if not isinstance(p, str) or not p.strip():
                raise Unavailable(f"{iid} 缺少非空字符串 path")
        if typ == "file_contains":
            pats = item.get("patterns")
            if not isinstance(pats, list) or not pats or not all(isinstance(x, str) and x for x in pats):
                raise Unavailable(f"{iid} 的 patterns 必须是非空字符串数组")
            mh = item.get("min_hits", len(pats))
            if not isinstance(mh, int) or isinstance(mh, bool) or mh < 1:
                raise Unavailable(f"{iid} 的 min_hits 必须是 ≥1 的整数")
        if typ == "line_count":
            for key in ("min", "max"):
                if key in item:
                    v = item[key]
                    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                        raise Unavailable(f"{iid} 的 {key} 必须是 ≥0 的整数")
            lo, hi = item.get("min", 0), item.get("max")
            if hi is not None and lo > hi:
                raise Unavailable(f"{iid} 的 min({lo}) 大于 max({hi})")
        if typ == "command":
            cmd = item.get("cmd")
            if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) and x for x in cmd):
                raise Unavailable(f"{iid} 的 cmd 必须是非空字符串数组")
            er = item.get("expect_rc", 0)
            if not isinstance(er, int) or isinstance(er, bool):
                raise Unavailable(f"{iid} 的 expect_rc 必须是整数")
            to = item.get("timeout", 120)
            if not isinstance(to, (int, float)) or isinstance(to, bool) or to <= 0:
                raise Unavailable(f"{iid} 的 timeout 必须是正数")
        if "desc" in item and not isinstance(item["desc"], str):
            raise Unavailable(f"{iid} 的 desc 必须是字符串")

    return items, base


# ---------------------------------------------------------------- 单项检查


def _read_text(path: Path, iid: str) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise Unavailable(f"{iid} 读不出文件 {path}（{exc}）") from exc


def check_item(item: dict, base: Path) -> tuple[str, str]:
    """执行单项检查，返回 (状态, 说明)。状态 ∈ {"pass", "fail", "gray"}。"""
    iid = item["id"]
    typ = item["type"]

    if typ == "file_exists":
        p = base / item["path"]
        if not p.exists():
            return "fail", f"文件不存在：{p}"
        if not p.is_file():
            return "fail", f"不是文件：{p}"
        size = p.stat().st_size
        if size == 0:
            return "fail", f"文件为 0 字节：{p}"
        return "pass", f"{p}（{size} 字节）"

    if typ == "file_absent":
        p = base / item["path"]
        if p.exists():
            return "fail", f"不该存在的路径仍在：{p}"
        return "pass", f"确认不存在：{p}"

    if typ == "file_contains":
        p = base / item["path"]
        if not p.is_file():
            return "fail", f"文件不存在或不是文件：{p}"
        text = _read_text(p, iid)
        pats = item["patterns"]
        need = item.get("min_hits", len(pats))
        hits = [x for x in pats if x in text]
        if len(hits) >= need:
            return "pass", f"命中 {len(hits)}/{len(pats)}（要求 ≥{need}）"
        missing = [x for x in pats if x not in hits]
        return "fail", f"命中 {len(hits)}/{len(pats)} < 要求 {need}；缺：{missing}"

    if typ == "line_count":
        p = base / item["path"]
        if not p.is_file():
            return "fail", f"文件不存在或不是文件：{p}"
        text = _read_text(p, iid)
        n = len(text.splitlines())
        lo, hi = item.get("min", 0), item.get("max")
        if n < lo:
            return "fail", f"行数 {n} < 下限 {lo}"
        if hi is not None and n > hi:
            return "fail", f"行数 {n} > 上限 {hi}"
        rng = f"[{lo},{hi if hi is not None else '∞'}]"
        return "pass", f"行数 {n} 落在 {rng}"

    if typ == "command":
        cmd = item["cmd"]
        expect = item.get("expect_rc", 0)
        timeout = item.get("timeout", 120)
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(base),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except FileNotFoundError:
            return "gray", f"命令不可执行（找不到可执行文件）：{cmd[0]}"
        except subprocess.TimeoutExpired:
            return "gray", f"命令超时 {timeout}s，判据给不出结论：{' '.join(cmd)}"
        except OSError as exc:
            return "gray", f"命令起不来：{exc}"
        if proc.returncode == expect:
            return "pass", f"rc={proc.returncode}（期望 {expect}）"
        if proc.returncode == 2 and expect != 2:
            # 子命令 rc=2 = 它自己崩了（`00_工程规范.md` §三「调用层崩了」）⇒ 这次检查给不出结论
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-2:]
            return "gray", f"子命令 rc=2（自身崩溃，判据不可用）；输出尾部：{tail}"
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        return "fail", f"rc={proc.returncode}（期望 {expect}）；输出尾部：{tail}"

    return "gray", f"未知 type：{typ}"  # 理论不可达，load_checklist 已拦


# ---------------------------------------------------------------- 跑闸


def run_gate(checklist_path: Path, echo=print) -> int:
    """跑一份清单，返回 rc。清单不可用抛 Unavailable（调用方转 rc=3）。"""
    items, base = load_checklist(checklist_path)
    echo(f"验收清单：{checklist_path}")
    echo(f"基准目录：{base}")
    echo(f"检查项数：{len(items)}")
    echo("-" * 68)

    counts = {"pass": 0, "fail": 0, "gray": 0}
    bad: list[str] = []
    grays: list[str] = []

    for item in items:
        iid = item["id"]
        desc = item.get("desc") or item["type"]
        status, detail = check_item(item, base)
        counts[status] += 1
        tag = {"pass": "PASS", "fail": "FAIL", "gray": "GRAY"}[status]
        echo(f"[{tag}] {iid:<8} {desc} :: {detail}")
        if status == "fail":
            bad.append(f"{iid} {desc} :: {detail}")
        elif status == "gray":
            grays.append(f"{iid} {desc} :: {detail}")

    echo("-" * 68)
    echo(f"汇总：PASS {counts['pass']} / FAIL {counts['fail']} / GRAY {counts['gray']}")

    if counts["gray"]:
        echo("rc=3 判据不可用（报灰优先于检出），灰项：")
        for line in grays:
            echo(f"  - {line}")
        return RC_UNAVAILABLE
    if counts["fail"]:
        echo("rc=1 检出未过项，缺项清单：")
        for line in bad:
            echo(f"  - {line}")
        return RC_FOUND
    echo("rc=0 全过")
    return RC_OK


# ---------------------------------------------------------------- 自测


def _selftest() -> int:
    """内置三份清单：合格 → 0，故意失败 → 1，损坏 → 3。"""
    print("=" * 68)
    print("acceptance_gate.py --selftest")
    print("=" * 68)

    with tempfile.TemporaryDirectory(prefix="gate_selftest_") as tmp:
        root = Path(tmp)
        (root / "ok.md").write_text("line1\nline2\nline3\n", encoding="utf-8", newline="\n")

        good = {
            "name": "合格清单",
            "items": [
                {"id": "A-01", "desc": "文件存在", "type": "file_exists", "path": "ok.md"},
                {"id": "A-02", "desc": "含 line2", "type": "file_contains", "path": "ok.md", "patterns": ["line2"]},
                {"id": "A-03", "desc": "不该有 x.md", "type": "file_absent", "path": "x.md"},
                {"id": "A-04", "desc": "行数 3", "type": "line_count", "path": "ok.md", "min": 3, "max": 3},
                {
                    "id": "A-05",
                    "desc": "命令 rc=0",
                    "type": "command",
                    "cmd": [sys.executable, "-c", "raise SystemExit(0)"],
                },
            ],
        }
        # 故意失败：断言一个不存在的文件存在 + 一条必然非 0 的命令
        bad = {
            "name": "故意失败清单",
            "items": [
                {"id": "B-01", "desc": "不存在的文件", "type": "file_exists", "path": "nope.md"},
                {
                    "id": "B-02",
                    "desc": "命令 rc 应 0 实际 1",
                    "type": "command",
                    "cmd": [sys.executable, "-c", "raise SystemExit(1)"],
                },
            ],
        }
        p_good = root / "good.json"
        p_bad = root / "bad.json"
        p_broken = root / "broken.json"
        # 附加用例：子命令自身崩溃（rc=2）必须报灰，不能被当成「检出」
        crash = {
            "name": "崩溃命令清单",
            "items": [
                {
                    "id": "C-01",
                    "desc": "子命令 rc=2（自身崩溃）",
                    "type": "command",
                    "cmd": [sys.executable, "-c", "raise SystemExit(2)"],
                }
            ],
        }
        p_crash = root / "crash.json"
        p_good.write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8", newline="\n")
        p_bad.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8", newline="\n")
        p_crash.write_text(json.dumps(crash, ensure_ascii=False), encoding="utf-8", newline="\n")
        p_broken.write_text('{"items": [ {"id": "C-01", ', encoding="utf-8", newline="\n")

        cases = [
            ("合格清单", p_good, RC_OK),
            ("故意失败清单", p_bad, RC_FOUND),
            ("损坏清单", p_broken, RC_UNAVAILABLE),
            ("崩溃命令清单（应报灰不报检出）", p_crash, RC_UNAVAILABLE),
        ]
        failures: list[str] = []
        for label, path, expect in cases:
            print(f"\n--- 用例：{label}（期望 rc={expect}）")
            try:
                got = run_gate(path)
            except Unavailable as exc:
                print(f"[GRAY] {exc}")
                got = RC_UNAVAILABLE
            ok = got == expect
            print(f"断言：实测 rc={got}，期望 rc={expect} → {'通过' if ok else '不通过'}")
            if not ok:
                failures.append(f"{label}: rc={got} 期望 {expect}")

        # 追加一条元断言：损坏清单必须是 rc=3 而不是 1（防止「任何异常都报检出」）
    print("\n" + "-" * 68)
    if failures:
        print("自测不通过：")
        for line in failures:
            print(f"  - {line}")
        return RC_CRASH
    print("自测通过：四份清单 rc 分别为 0 / 1 / 3 / 3（最后一条验「崩溃命令报灰」）")
    return RC_OK


# ---------------------------------------------------------------- 入口


class _Parser:
    """极简参数解析：用法错一律 rc=3（`00_工程规范.md` §三「用法错归 3」），不沿用 argparse 的 exit(2)。"""

    def __init__(self) -> None:
        self.checklist: Path | None = None
        self.selftest = False
        self.example = False

    def parse(self, argv: list[str]) -> None:
        args = list(argv)
        if not args:
            raise UsageError("缺少参数：需要 <验收清单.json>，或 --selftest / --example")
        for a in args:
            if a in ("-h", "--help"):
                raise UsageError("用法：acceptance_gate.py <清单.json> | --selftest | --example")
            if a == "--selftest":
                self.selftest = True
            elif a == "--example":
                self.example = True
            elif a.startswith("-"):
                raise UsageError(f"未知选项：{a}")
            else:
                if self.checklist is not None:
                    raise UsageError(f"只接受一个清单路径，多余参数：{a}")
                self.checklist = Path(a)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        parser = _Parser()
        parser.parse(argv)
        if parser.selftest:
            return _selftest()
        if parser.example:
            print(json.dumps(EXAMPLE, ensure_ascii=False, indent=2))
            return RC_OK
        assert parser.checklist is not None
        return run_gate(parser.checklist)
    except UsageError as exc:
        print(f"[GRAY] 用法错：{exc}")
        return RC_UNAVAILABLE
    except Unavailable as exc:
        print(f"[GRAY] 判据不可用：{exc}")
        return RC_UNAVAILABLE
    except Exception as exc:  # 兜底：脚本自身崩了
        import traceback

        print(f"[CRASH] 脚本内部异常：{exc!r}")
        traceback.print_exc()
        return RC_CRASH


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(main())

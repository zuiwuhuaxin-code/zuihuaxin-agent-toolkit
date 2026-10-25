#!/usr/bin/env python3
"""prd_lint 的真跑自测。

为什么判据源就在本包内（发布规范 H2 的例外说明）：
    本 Skill 是**公开分发的自包含包**，外部用户机器上不存在任何可复用的「工具层」。
    因此判据源唯一 = `scripts/prd_lint.py`，本文件只**调用**它，不重写任何检查逻辑，
    也就不会出现「两份判据各说各话」的漂移。

每条断言都是「造输入 → 跑判据 → 断 rc」，⛔ 不用 `"某句话" in 源码` 这类静态钉
（静态钉只能证明文档里写了这句话，证明不了判据真的会拦）。

跑法：
    python tests/test_prd_lint.py      # rc=0 全过 / 1 有用例失败
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))

import prd_lint  # noqa: E402

_CASES: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _CASES.append((name, bool(ok), detail))
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f"  :: {detail}" if detail else ""))


def main() -> int:
    # 1) 脚本自带自测：它内部断言 rc 序列 0 / 1 / 3
    rc = prd_lint.selftest()
    check("内置 selftest 返回 0", rc == 0, f"期望 0，实得 {rc}")

    # 2) 真跑：空壳文本必须被检出（rc=1，不是 0 也不是 3）
    rc, results = prd_lint.lint_text("# 空壳 PRD\n\n什么也没有。\n")
    check("空壳文本判检出（rc=1）", rc == 1, f"喂『# 空壳 PRD』，期望 rc=1，实得 rc={rc}")

    # 3) 防恒真：8 项判据里必须有 ≥5 项报出缺项，否则说明判据根本没在执行
    fails = sum(1 for _, _, problems in results if problems)
    check("空壳文本缺项 ≥5 项", fails >= 5, f"实得 {fails} 项缺（共 {len(results)} 项判据）")

    # 4) 判据不可用（文件不存在）必须落 3，⛔ 不许落 1 —— 1 会让调用方去改正文
    with tempfile.TemporaryDirectory() as td:
        missing = Path(td) / "no_such_prd.md"
        rc_missing, _ = prd_lint.lint_file(missing)
        check("文件不存在 → rc=3（判据不可用）", rc_missing == 3, f"期望 3，实得 {rc_missing}")

        # 5) 空文件同样是「判据不可用」，不是「缺项」
        empty = Path(td) / "empty.md"
        empty.write_bytes(b"")
        rc_empty, _ = prd_lint.lint_file(empty)
        check("空文件 → rc=3（判据不可用）", rc_empty == 3, f"期望 3，实得 {rc_empty}")

    passed = sum(1 for _, ok, _ in _CASES if ok)
    total = len(_CASES)
    print("-" * 60)
    print(f"自测汇总：{total} 条，通过 {passed}，失败 {total - passed}")
    if passed != total:
        for name, ok, detail in _CASES:
            if not ok:
                print(f"  ✗ {name}  :: {detail}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""acceptance_gate 的真跑自测。

判据源唯一 = `scripts/acceptance_gate.py`，本文件只调用、不复写（发布规范 H2）。
每条断言都是「造清单 → 跑闸 → 断 rc」，⛔ 不用源码静态钉。

跑法：
    python tests/test_acceptance_gate.py      # rc=0 全过 / 1 有用例失败
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))

import acceptance_gate as ag  # noqa: E402

_CASES: list[tuple[str, bool, str]] = []
_QUIET = lambda *a, **k: None  # noqa: E731


def check(name: str, ok: bool, detail: str = "") -> None:
    _CASES.append((name, bool(ok), detail))
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f"  :: {detail}" if detail else ""))


def _write_list(path: Path, items: list[dict]) -> None:
    path.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    # 1) 脚本自带自测：内部断言四份清单 rc 序列 0 / 1 / 3 / 3
    rc = ag._selftest()
    check("内置 selftest 返回 0", rc == 0, f"期望 0，实得 {rc}")

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)

        # 2) 指向不存在的文件 → 检出（rc=1）
        miss = base / "no_such_file.txt"
        cl = base / "fail.json"
        _write_list(cl, [{"id": "C-01", "type": "file_exists", "path": str(miss)}])
        rc_fail = ag.run_gate(cl, echo=_QUIET)
        check("缺文件 → rc=1（检出）", rc_fail == 1, f"期望 1，实得 {rc_fail}")

        # 3) 文件真在 → 全过（rc=0）。与上一条成对照，证明不是「一律报错」
        okfile = base / "ok.txt"
        okfile.write_text("x", encoding="utf-8")
        cl2 = base / "pass.json"
        _write_list(cl2, [{"id": "C-01", "type": "file_exists", "path": str(okfile)}])
        rc_pass = ag.run_gate(cl2, echo=_QUIET)
        check("文件在 → rc=0（全过）", rc_pass == 0, f"期望 0，实得 {rc_pass}")

        # 4) 清单本身不存在 → 判据不可用（rc=3），⛔ 不许落 1
        rc_gray = ag.main([str(base / "nope.json")])
        check("清单不存在 → rc=3（判据不可用）", rc_gray == 3, f"期望 3，实得 {rc_gray}")

    # 5) 用法错（不带参数）→ rc=3，不是 argparse 默认的 2
    rc_usage = ag.main([])
    check("无参数（用法错）→ rc=3", rc_usage == 3, f"期望 3，实得 {rc_usage}")

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

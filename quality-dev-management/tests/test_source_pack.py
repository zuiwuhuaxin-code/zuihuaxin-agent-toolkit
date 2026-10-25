#!/usr/bin/env python3
"""source_pack 的真跑自测。

判据源唯一 = `scripts/source_pack.py`，本文件只调用、不复写（发布规范 H2）。
每条断言都是「造源码目录 → 打包 → 验产物内容」，⛔ 不用源码静态钉。

跑法：
    python tests/test_source_pack.py      # rc=0 全过 / 1 有用例失败
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))

import source_pack as sp  # noqa: E402

_CASES: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _CASES.append((name, bool(ok), detail))
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f"  :: {detail}" if detail else ""))


def main() -> int:
    # 1) 脚本自带自测：内部造 2 个文件，断言 HTML 含文件名 / 行号 / 无外链
    rc = sp._selftest()
    check("内置 selftest 返回 0", rc == 0, f"期望 0，实得 {rc}")

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        src = base / "src"
        src.mkdir()
        (src / "alpha.py").write_text("print('hello')\n", encoding="utf-8")
        (src / "beta.md").write_text("# 标题\n正文\n", encoding="utf-8")

        out = base / "packed.html"
        n_files, n_lines = sp.pack(
            src, out, sp.parse_exts(".py,.md"), set(), "自测打包", 10 * 1024 * 1024
        )

        # 2) 文件数要对（2 个都收进来了）
        check("打包文件数 = 2", n_files == 2, f"期望 2，实得 {n_files}")

        # 3) 产物真的在盘上且非空
        size = out.stat().st_size if out.is_file() else 0
        check("产物已落盘且非空", size > 0, f"实得 {size} bytes")

        html = out.read_text(encoding="utf-8") if size else ""

        # 4) 两个文件名都要出现在 HTML 里（证明真把内容装进去了，不只是生成了个空壳）
        check("含 alpha.py", "alpha.py" in html)
        check("含 beta.md", "beta.md" in html)

        # 5) 单文件自包含：⛔ 不许有外链（script / link / src= / @import）
        extern = sum(html.count(k) for k in ("<script", "<link", "src=", "@import"))
        check("无外部引用", extern == 0, f"外链计数期望 0，实得 {extern}")

        # 6) 写盘纯 LF
        raw = out.read_bytes() if size else b""
        cr = raw.count(b"\r")
        check("产物纯 LF", cr == 0, f"CR 计数期望 0，实得 {cr}")

        # 7) 源码目录不存在 → rc=3（判据不可用），⛔ 不许崩成 2
        rc3 = sp.main([str(base / "no_such_dir"), "-o", str(base / "x.html")])
        check("源码目录不存在 → rc=3", rc3 == 3, f"期望 3，实得 {rc3}")

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

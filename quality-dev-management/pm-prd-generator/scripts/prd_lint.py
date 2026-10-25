#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prd_lint.py —— 检查一份 PRD Markdown 是否满足 8 条硬要求（零依赖，纯标准库）。

用法：
    python prd_lint.py <prd.md>       检查一份 PRD
    python prd_lint.py --selftest     跑内置样例自检（1 合格 + 1 故意缺项）
    python prd_lint.py --checks       列出 8 项检查的编号与含义

退出码：
    0  全过
    1  有缺项（打印缺项清单，带行号或章节名）
    2  自检失败（仅 --selftest）
    3  判据不可用（文件不存在 / 读不了 / 内容为空）

8 条硬要求 = `references/00_PRD编写规范.md` §七 质量自检的可核子集，逐条对应：
    C1 五步走留痕表        C5 AC「给定/当/那么」
    C2 R 条目三行字段      C6 状态流转表
    C3 F 条目五要素        C7 业务流程图
    C4 异常五类必备        C8 本期不做什么
"""

from __future__ import annotations

import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------- 判据常量

FIVE_STEPS: tuple[str, ...] = ("调查事实", "摸清底数", "对标成熟方案", "先出方案", "最后执行")
R_FIELDS: tuple[str, ...] = ("为谁做", "解决什么问题", "带来什么价值")
F_FIELDS: tuple[str, ...] = ("触发条件", "前置条件", "展示内容", "操作规则", "系统反馈")
EXC_CLASSES: tuple[str, ...] = ("空数据", "权限不足", "网络异常", "重复提交", "操作超时")
AC_ALL: tuple[str, ...] = ("给定", "当", "那么")
AC_PATTERNS: dict[str, re.Pattern[str]] = {
    "给定": re.compile(r"给定\s*[【\[]?"),
    "当": re.compile(r"当\s*[【\[]"),
    "那么": re.compile(r"那么\s*[【\[]?"),
}
BLOCK_PREFIXES: tuple[str, ...] = ("R", "F", "AC", "E", "Q")
REASON_WORDS: tuple[str, ...] = ("理由", "因为", "原因", "由于")

HEAD_RE = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.、)])\s+\S")
SEP_ROW_RE = re.compile(r"^\|[\s\-:|]+\|$")
REASON_SEPS: tuple[str, ...] = ("——", "：", ":", "；", ";")


# ---------------------------------------------------------------- 结构解析


@dataclass(frozen=True)
class Section:
    level: int
    title: str
    start: int  # 0-based，标题所在行
    end: int  # 0-based，开区间


def strip_markers(line: str) -> str:
    """去掉标题井号、列表符号、加粗、表格竖线等前缀，便于识别 R-01 之类锚点。"""
    s = line.strip()
    s = re.sub(r"^#{1,6}\s*", "", s)
    s = re.sub(r"^[-*+]\s+", "", s)
    s = re.sub(r"^\*\*", "", s)
    s = re.sub(r"^\|\s*", "", s)
    return s.strip()


def parse_sections(lines: list[str]) -> list[Section]:
    heads: list[tuple[int, int, str]] = []
    for i, raw in enumerate(lines):
        m = HEAD_RE.match(raw)
        if m:
            heads.append((i, len(m.group(1)), m.group(2).strip()))
    out: list[Section] = []
    for k, (i, level, title) in enumerate(heads):
        end = len(lines)
        for j in range(k + 1, len(heads)):
            if heads[j][1] <= level:
                end = heads[j][0]
                break
        out.append(Section(level, title, i, end))
    return out


def find_section(sections: list[Section], words: tuple[str, ...]) -> Section | None:
    for sec in sections:
        if any(w in sec.title for w in words):
            return sec
    return None


def iter_blocks(
    lines: list[str], prefix: str, scope: tuple[int, int] | None = None
) -> list[tuple[str, int, str]]:
    """产出 (编号, 起始行 0-based, 块文本)。块 = 锚点行到下一个锚点/下一个标题。

    scope=(start, end) 时只在该区间内找锚点，避免把 §4 需求总览表里的
    「| R-01 | … |」误当成 §5 需求明细条目。
    """
    out: list[tuple[str, int, str]] = []
    lo, hi = scope if scope else (0, len(lines))
    starts: list[tuple[int, str]] = []
    for i in range(lo, min(hi, len(lines))):
        s = strip_markers(lines[i])
        m = re.match(rf"^{prefix}-(\d{{1,3}})(?!\d)", s)
        if m:
            starts.append((i, m.group(1)))
    for i, num in starts:
        end = i + 1
        limit = min(len(lines), hi, i + 41)
        while end < limit:
            s = strip_markers(lines[end])
            if any(re.match(rf"^{p}-(\d{{1,3}})(?!\d)", s) for p in BLOCK_PREFIXES):
                break
            if HEAD_RE.match(lines[end]):
                break
            end += 1
        out.append((num, i, "\n".join(lines[i + 1 : end])))
    return out


def scope_of(sections: list[Section], words: tuple[str, ...]) -> tuple[int, int] | None:
    sec = find_section(sections, words)
    return (sec.start, sec.end) if sec else None


# ---------------------------------------------------------------- 8 项检查


def check_five_steps(lines: list[str], sections: list[Section]) -> list[str]:
    sec = find_section(sections, ("五步",))
    if sec is None:
        return ["未见五步留痕章节（应在 §0 设表：调查事实/摸清底数/对标成熟方案/先出方案/最后执行）"]
    body = "\n".join(lines[sec.start : sec.end])
    missing = [s for s in FIVE_STEPS if s not in body]
    if missing:
        return [f"章节「{sec.title}」（第 {sec.start + 1} 行）缺步：{'、'.join(missing)}"]
    return []


def _check_fields(
    lines: list[str],
    prefix: str,
    fields: tuple[str, ...],
    label: str,
    scope: tuple[int, int] | None,
) -> list[str]:
    blocks = iter_blocks(lines, prefix, scope)
    if not blocks:
        return [f"未找到 {prefix}-xx {label}（应以 {prefix}-01 起编号，每条单独成块）"]
    problems: list[str] = []
    for num, idx, body in blocks:
        missing = [f for f in fields if f not in body]
        if missing:
            problems.append(
                f"{prefix}-{num}（第 {idx + 1} 行）缺「{'、'.join(missing)}」"
            )
    return problems


def check_r_fields(lines: list[str], sections: list[Section]) -> list[str]:
    return _check_fields(
        lines, "R", R_FIELDS, "需求条目", scope_of(sections, ("需求明细",))
    )


def check_f_fields(lines: list[str], sections: list[Section]) -> list[str]:
    return _check_fields(
        lines, "F", F_FIELDS, "功能点条目", scope_of(sections, ("功能点",))
    )


def check_exceptions(lines: list[str], sections: list[Section]) -> list[str]:
    text = "\n".join(lines)
    missing = [c for c in EXC_CLASSES if c not in text]
    if missing:
        sec = find_section(sections, ("异常",))
        where = f"章节「{sec.title}」（第 {sec.start + 1} 行）" if sec else "全文"
        return [f"{where}缺必备异常类别：{'、'.join(missing)}"]
    return []


def check_ac(lines: list[str], sections: list[Section]) -> list[str]:
    blocks = iter_blocks(lines, "AC", scope_of(sections, ("验收",)))
    if not blocks:
        return ["未找到 AC-xx 验收条目"]
    problems: list[str] = []
    for num, idx, body in blocks:
        text = body
        missing = [p for p in AC_ALL if not AC_PATTERNS[p].search(text)]
        if missing:
            hint = "「给定【…】当【…】那么【…】」" if "当" in missing else "、".join(missing)
            problems.append(f"AC-{num}（第 {idx + 1} 行）缺三段中的：{hint}")
    return problems


def check_state_table(lines: list[str], sections: list[Section]) -> list[str]:
    problems: list[str] = []
    rows = [
        (i, l)
        for i, l in enumerate(lines)
        if l.strip().startswith("|") and "状态" in l and ("进入条件" in l or "退出条件" in l)
    ]
    if not rows:
        return ["未找到状态流转表（应含「状态名/进入条件/退出条件/本态允许动作/负责人」五列）"]
    text = "\n".join(lines)
    if "初态" not in text:
        problems.append("状态表未见「初态」标记（状态机必须有初态）")
    if "终态" not in text:
        problems.append("状态表未见「终态」标记（状态机必须有终态）")
    return problems


def check_flow_chart(lines: list[str], sections: list[Section]) -> list[str]:
    sec = find_section(sections, ("流程图",))
    if sec is None:
        return ["未见业务流程图章节（§10：SVG 流程图 或 文字版流程说明）"]
    body = "\n".join(lines[sec.start : sec.end])
    has_svg = "<svg" in body.lower()
    arrows = body.count("→") + body.count("->")
    if not has_svg and arrows < 3:
        return [
            f"章节「{sec.title}」（第 {sec.start + 1} 行）既无 <svg>，文字流程说明也少于 3 步（当前箭头 {arrows} 个）"
        ]
    if "异常" not in body:
        return [f"章节「{sec.title}」（第 {sec.start + 1} 行）未见异常分支说明（异常分支必须画出）"]
    return []


def check_scope_out(lines: list[str], sections: list[Section]) -> list[str]:
    sec = find_section(sections, ("不做什么", "本期不做"))
    if sec is None:
        return ["未见「本期做什么 / 不做什么」章节（§11）"]
    body = lines[sec.start + 1 : sec.end]
    cut = -1
    for j, l in enumerate(body):
        m = HEAD_RE.match(l)
        if (m and "不做" in m.group(2)) or strip_markers(l).startswith("本期不做"):
            cut = j
    if cut >= 0:
        body = body[cut + 1 :]
    bullets = [l for l in body if BULLET_RE.match(l)]
    rows = [l for l in body if l.strip().startswith("|") and not SEP_ROW_RE.match(l.strip())]
    if bullets:
        items, reason_col = bullets, False
    else:
        items = rows[1:] if rows else []
        header = rows[0] if rows else ""
        reason_col = any(w in header for w in REASON_WORDS) or "说明" in header
    if len(items) < 3:
        return [
            f"章节「{sec.title}」（第 {sec.start + 1} 行）「不做」条目仅 {len(items)} 条，应 ≥3 条"
        ]
    if reason_col:
        def has_reason(row: str) -> bool:
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            return len(cells) >= 2 and cells[-1] not in ("", "—", "-", "无")
    else:
        def has_reason(row: str) -> bool:
            if any(w in row for w in REASON_WORDS):
                return True
            for sep in REASON_SEPS:
                if sep in row and len(row.split(sep, 1)[1].strip()) >= 8:
                    return True
            return False

    with_reason = [l for l in items if has_reason(l)]
    if len(with_reason) < 3:
        return [
            f"章节「{sec.title}」（第 {sec.start + 1} 行）带理由的「不做」条目仅 {len(with_reason)} 条，应 ≥3 条且各带理由"
        ]
    return []


CHECKS: list[tuple[str, str, object]] = [
    ("C1", "五步走留痕表", check_five_steps),
    ("C2", "R 条目三行字段", check_r_fields),
    ("C3", "F 条目五要素", check_f_fields),
    ("C4", "异常五类必备", check_exceptions),
    ("C5", "AC 三段句式", check_ac),
    ("C6", "状态流转表", check_state_table),
    ("C7", "业务流程图", check_flow_chart),
    ("C8", "本期不做什么", check_scope_out),
]


# ---------------------------------------------------------------- 主流程


def lint_text(text: str) -> tuple[int, list[tuple[str, str, list[str]]]]:
    """返回 (rc, [(编号, 名称, 缺项列表), ...])。"""
    lines = text.splitlines()
    sections = parse_sections(lines)
    results: list[tuple[str, str, list[str]]] = []
    for cid, title, fn in CHECKS:
        problems = fn(lines, sections)  # type: ignore[operator]
        results.append((cid, title, problems))
    rc = 0 if all(not p for _, _, p in results) else 1
    return rc, results


def lint_file(path: Path) -> tuple[int, list[tuple[str, str, list[str]]]]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        print(f"[rc=3] 判据不可用：读不了文件 {path} —— {exc}", file=sys.stderr)
        return 3, []
    if not raw.strip():
        print(f"[rc=3] 判据不可用：文件为空 {path}", file=sys.stderr)
        return 3, []
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        print(f"[rc=3] 判据不可用：不是 UTF-8 文本 {path} —— {exc}", file=sys.stderr)
        return 3, []
    return lint_text(text)


def report(path: Path, rc: int, results: list[tuple[str, str, list[str]]]) -> None:
    print(f"prd_lint v1.0 —— {path}")
    print("-" * 64)
    fails = 0
    for cid, title, problems in results:
        state = "FAIL" if problems else "PASS"
        fails += 1 if problems else 0
        print(f"[{cid}] {title} …… {state}")
        for p in problems:
            print(f"      - {p}")
    total = len(results)
    print("-" * 64)
    print(f"结论：{total - fails}/{total} 过，{fails} 项缺 → rc={rc}")
    if fails:
        print("处理建议：见 references/04_PRD八项要求.md 对应条目；缺项逐条补，⛔ 不写「后续补」。")
    else:
        print("建议下一步：S5 画原型出 HTML，再进 S6 质量自检 10 条。")


# ---------------------------------------------------------------- 自检样例

GOOD_PRD = """# 样例项目 产品需求文档（PRD）v1.0

## 0. 五步留痕与文档信息

| 步 | 在本项目的落地 | 落点 |
|---|---|---|
| 1 调查事实 | 实测 3 个目录、42 个脚本 | 分析报告 §1 |
| 2 摸清底数 | 存量 800 行，缺 2 个适配 | 本 PRD §2 |
| 3 对标成熟方案 | 对标 Notion 式看板 | 本 PRD §3 |
| 4 先出方案 | 本 PRD 即方案 | §4~§11 |
| 5 最后执行 | 排期 + AC 验收 | §12 |

## 5. 需求明细

### R-01 批量导入

- 为谁做：运营
- 解决什么问题：手工复制单篇 3 分钟，易漏
- 带来什么价值：单篇 20 秒，漏发为 0（AC-01）
- 验收指向：AC-01

## 6. 功能点规格

### F-01 导入按钮

| 要素 | 内容 |
|---|---|
| 触发条件 | 点击「开始导入」按钮 |
| 前置条件 | 已登录且剪贴板非空 |
| 展示内容 | 绿底白字主按钮「开始导入」 |
| 操作规则 | 单次 ≤50 条 |
| 系统反馈 | 成功提示「已导入 N 条」 |

## 7. 异常流程与边界场景

| 编号 | 场景 | 系统行为 |
|---|---|---|
| E-01 | 空数据 | 提示「还没有导入记录」 |
| E-02 | 权限不足 | 拦截并提示「无导入权限」 |
| E-03 | 网络异常 | 按钮置灰，提示「网络已断开」 |
| E-04 | 重复提交 | 去重并提示「已在队列中」 |
| E-05 | 操作超时 | 保留已完成部分，提示「已完成 32/50」 |

## 8. 验收标准

AC-01 【功能点 F-01】
  给定【已登录，剪贴板内有 1 条有效链接】
  当【点击「开始导入」】
  那么【列表新增 1 行，提示「已导入 1 条」】

## 9. 状态流转表

| 状态名 | 进入条件 | 退出条件 | 本态允许动作 | 负责人 |
|---|---|---|---|---|
| 待导入（初态） | 新建任务 | 提交成功 | 编辑、删除 | 运营 |
| 已完成（终态） | 全部导入成功 | — | 查看 | 运营 |

## 10. 业务流程图

<svg viewBox="0 0 1080 320"><rect x="20" y="20" width="120" height="40"/></svg>

流程说明：开始 → 校验登录 → 逐条导入 → 结束；异常分支：登录失效 → 提示重登。

## 11. 本期做什么 / 不做什么

### 本期做

- 批量导入（P0）

### 本期不做

- 不做自动发布：理由 发布需人工过审，自动发会绕过合规闸门
- 不做多账号并发：理由 本期只有 1 个运营账号
- 不做数据看板：理由 依赖埋点体系，本期无埋点
"""

BAD_PRD = """# 缺项样例 产品需求文档（PRD）v1.0

## 0. 五步留痕与文档信息

| 步 | 在本项目的落地 | 落点 |
|---|---|---|
| 1 调查事实 | 看过一些文件 | 无 |
| 2 摸清底数 | 大概几千行 | 无 |
| 3 对标成熟方案 | 对标大厂 | 无 |
| 4 先出方案 | 本 PRD | 无 |
| 5 最后执行 | 排期 | 无 |

## 5. 需求明细

### R-01 批量导入

- 为谁做：用户
- 解决什么问题：效率低

## 6. 功能点规格

### F-01 导入按钮

| 要素 | 内容 |
|---|---|
| 触发条件 | 用户操作时 |
| 前置条件 | 已登录 |
| 展示内容 | 一个按钮 |
| 操作规则 | 无 |

## 7. 异常流程与边界场景

| 编号 | 场景 |
|---|---|
| E-01 | 空数据：提示空 |
| E-02 | 权限不足：拦截 |
| E-03 | 网络异常：提示重试 |
| E-04 | 重复提交：去重 |
| E-05 | 操作超时：提示超时 |

## 8. 验收标准

AC-01 导入功能正常可用。

## 11. 本期做什么 / 不做什么

### 本期不做

- 其他后续再说
"""

EXPECTED_BAD_FAILS: set[str] = {"C2", "C3", "C5", "C6", "C7", "C8"}


def selftest() -> int:
    print("prd_lint --selftest：2 个内置样例")
    print("-" * 64)
    ok = True
    with tempfile.TemporaryDirectory(prefix="prd_lint_selftest_") as td:
        good = Path(td) / "good_prd.md"
        bad = Path(td) / "bad_prd.md"
        good.write_bytes(GOOD_PRD.encode("utf-8"))
        bad.write_bytes(BAD_PRD.encode("utf-8"))

        rc_good, res_good = lint_file(good)
        fails_good = [c for c, _, p in res_good if p]
        print(f"[样例1 合格] rc={rc_good}（期望 0）  失败项={fails_good or '无'}")
        if rc_good != 0:
            ok = False
            for c, t, p in res_good:
                for msg in p:
                    print(f"      意外缺项 {c} {t}：{msg}")

        rc_bad, res_bad = lint_file(bad)
        fails_bad = {c for c, _, p in res_bad if p}
        print(f"[样例2 缺项] rc={rc_bad}（期望 1）  失败项={sorted(fails_bad)}")
        if rc_bad != 1:
            ok = False
            print("      断言失败：故意缺项的样例应返回 rc=1")
        if fails_bad != EXPECTED_BAD_FAILS:
            ok = False
            print(f"      断言失败：期望失败项 {sorted(EXPECTED_BAD_FAILS)}，实际 {sorted(fails_bad)}")

        rc_missing, _ = lint_file(Path(td) / "not_exist.md")
        print(f"[样例3 不可用] rc={rc_missing}（期望 3，stderr 已打印原因）")
        if rc_missing != 3:
            ok = False

    print("-" * 64)
    print("自检结论：" + ("通过（rc=0）" if ok else "失败（rc=2）"))
    return 0 if ok else 2


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0 if argv else 3
    if argv[0] == "--selftest":
        return selftest()
    if argv[0] == "--checks":
        for cid, title, _ in CHECKS:
            print(f"{cid}  {title}")
        return 0
    path = Path(argv[0])
    if not path.is_file():
        print(f"[rc=3] 判据不可用：文件不存在 {path}", file=sys.stderr)
        return 3
    rc, results = lint_file(path)
    if rc == 3:
        return 3
    report(path, rc, results)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

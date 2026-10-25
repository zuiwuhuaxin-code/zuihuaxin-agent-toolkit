#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""打 WorkBuddy 开放平台可上传的技能包，并在打包前逐条自检。

为什么要有这个脚本
------------------
手工 `zip -r` 有三个坑，每一个都会让上传白跑一趟：

1. **根目录层级错**。平台要的是 `{skill-name}/SKILL.md`，不是 `SKILL.md`
   直接躺在 zip 根上，也不是多套一层 `skills/`。层级错了解析报错，且报的
   错（「缺 SKILL.md」）不会告诉你是层级问题。
2. **frontmatter 缺必填字段**。平台必填 8 项（`name` / `display_name` /
   `display_name_en` / `description` / `description_zh` / `description_en` /
   `version` / `author`）。缺了在**上传时**才报，本地无从感知。
   ⇒ 本脚本在打包前按官方字段表逐项核（字段表见
   https://open.workbuddy.cn/docs/skill）。
3. **把本地痕迹打进包**：`__pycache__`、`.pyc`、以及正文里的 `D:\\...` 绝对路径。
   第三条最阴 —— 包能装上、能跑，但换台机器就找不到文件，而卖家本地永远测不出来。

口径
----
- 只做**只读检查 + 产出 zip**，不改包内任何文件（唯一例外是 `__pycache__` 不打包，
  但也不删）。
- zip 内一律 `{skill}/...`，UTF-8 文件名（zipfile 对非 ASCII 自动置 flag bit 11）。
- 排除：`.git`、`.gitignore`、`__pycache__`、`*.pyc`、`.DS_Store`、`_marketplace`。
- **`tests/` 保留**：两份 SKILL.md 的「维护」章节要求「改判据后必跑 tests/」，
  删了等于让买家照着一个不存在的目录走。若平台解析因这个目录报错，
  见 `_marketplace/上架材料.md` 的降级方案。

用法
----
    python pack_marketplace.py            # 自检 + 打包
    python pack_marketplace.py --check    # 只自检，不打包
    python pack_marketplace.py --json     # 机读自检结果
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # 06_Skill包
OUT = ROOT / "_marketplace" / "dist"

#: 平台 frontmatter 必填字段（依据 open.workbuddy.cn/docs/skill 字段表）
REQUIRED_FIELDS = (
    "name", "display_name", "display_name_en",
    "description", "description_zh", "description_en",
    "version", "author",
)
#: 打包排除（目录名精确匹配 / 后缀匹配）
SKIP_DIRS = {".git", "__pycache__", "_marketplace", ".pytest_cache"}
SKIP_SUFFIX = {".pyc", ".pyo", ".DS_Store", ".zip"}
SKIP_NAMES = {".gitignore"}

#: 绝对路径痕迹：Windows 盘符 + 常见真实目录。包一旦公开，这些就是隐私泄漏点。
#: ⚠ `Users\<你>` / `Users\<name>` 这类**占位符**是正当的安装说明（README 里就要这么写），
#:   所以 `Users\` 之后紧跟 `<` `{` `%` `$` 的一律放过 —— 第一版没放过，把两条
#:   正常文档误报成泄漏（实测踩到）。真正要拦的是**具体用户名**和内部项目目录。
ABS_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/](?:"
    r"Users[\\/](?![<{$%])"                      # 具体用户名才算
    r"|作品库|公众号自动化|公众号矩阵自动化|_PRD|split_tools|影分身|小红书自动化"
    r")"
)
#: 疑似密钥：值长度 ≥16 的 key/token/secret 赋值
SECRET_RE = re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}")


def read_frontmatter(text: str) -> dict[str, str]:
    """取 SKILL.md 的 YAML frontmatter（只用标准库，避免依赖 pyyaml）。

    ⚠ 列表型字段（`examples_zh:` 后跟若干 `- "..."`）的键值是空的，
    第一版据此判「缺字段」，把两个**已经写好了示例**的包全报成缺 `examples_zh`（实测踩到）。
    现在：键后面跟了列表项就记为 `"<list:n>"`，表示「存在且非空」。
    """
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    block = text[3:end]
    out: dict[str, str] = {}
    key = None
    for line in block.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line.lstrip().startswith("- "):             # 列表项：记到上一个键上
            if key and not out.get(key):
                out[key] = "<list>"
            continue
        if line.startswith((" ", "\t")):               # 续行
            continue
        m = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$", line)
        if m:
            key = m.group(1)
            out[key] = m.group(2).strip()
    return out


def iter_files(skill_dir: Path) -> list[Path]:
    """包内应被打进 zip 的文件（排除清单见模块文档）。"""
    out: list[Path] = []
    for p in sorted(skill_dir.rglob("*")):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(skill_dir).parts
        if any(part in SKIP_DIRS for part in rel_parts[:-1]):
            continue
        if p.suffix in SKIP_SUFFIX or p.name in SKIP_NAMES:
            continue
        out.append(p)
    return out


def check_skill(skill_dir: Path) -> dict:
    """一个技能包的全部自检项。返回 {ok, problems, info}。"""
    problems: list[str] = []
    info: dict = {"skill": skill_dir.name, "files": 0, "zip_entries": []}

    sk = skill_dir / "SKILL.md"
    if not sk.is_file():
        return {"ok": False, "problems": ["缺 SKILL.md（平台必须项）"], "info": info}

    text = sk.read_text(encoding="utf-8")
    fm = read_frontmatter(text)
    missing = [k for k in REQUIRED_FIELDS if not fm.get(k)]
    if missing:
        problems.append(f"frontmatter 缺必填字段：{', '.join(missing)}")
    if fm.get("name") and fm["name"] != skill_dir.name:
        problems.append(f"frontmatter name={fm['name']!r} 与目录名 {skill_dir.name!r} 不一致"
                        "（平台按 name 建资产，不一致后面很乱）")
    if fm.get("version") and not re.fullmatch(r"\d+\.\d+\.\d+", fm["version"]):
        problems.append(f"version={fm['version']!r} 不是 x.y.z 语义化版本")
    if not fm.get("examples_zh"):
        problems.append("缺 examples_zh（非必填，但商品页「试试这样问我」会是空的，建议补）")

    files = iter_files(skill_dir)
    info["files"] = len(files)
    info["zip_entries"] = [f"{skill_dir.name}/{p.relative_to(skill_dir).as_posix()}" for p in files]

    # 目录结构：官方四类子目录之外的，只提示不拦（tests/ 是刻意保留的）
    tops = {p.relative_to(skill_dir).parts[0] for p in files if len(p.relative_to(skill_dir).parts) > 1}
    extra = tops - {"references", "scripts", "templates"}
    if extra:
        info["extra_dirs"] = sorted(extra)

    for p in files:
        rel = p.relative_to(skill_dir).as_posix()
        if p.suffix.lower() not in {".md", ".py", ".txt", ".yaml", ".yml", ".json", ".sh"}:
            continue
        try:
            t = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append(f"{rel} 不是 UTF-8（平台按 UTF-8 解析，会乱码）")
            continue
        m = ABS_PATH_RE.search(t)
        if m:
            problems.append(f"{rel} 含本地绝对路径：{m.group(0)}…")
        m = SECRET_RE.search(t)
        if m:
            problems.append(f"{rel} 疑似硬编码密钥：{m.group(1)}")
        if "\r\n" in t and p.suffix in {".py", ".md"}:
            problems.append(f"{rel} 含 CRLF（包内统一 LF）")

    return {"ok": not problems, "problems": problems, "info": info}


def run_selftest(skill_dir: Path) -> dict:
    """真跑技能自带的 selftest —— 「打得开」不等于「跑得动」。"""
    cmds: list[list[str]] = []
    for s in sorted((skill_dir / "scripts").glob("*.py")):
        cmds.append([sys.executable, str(s), "--selftest"])
    out = []
    for c in cmds:
        try:
            r = subprocess.run(c, capture_output=True, text=True, timeout=180,
                               cwd=str(skill_dir))
            ok = r.returncode == 0
            tail = (r.stdout or r.stderr).strip().splitlines()[-1:] or [""]
            out.append({"cmd": " ".join(Path(x).name if i == 1 else x for i, x in enumerate(c)),
                        "rc": r.returncode, "ok": ok, "tail": tail[0][:160]})
        except Exception as e:                              # noqa: BLE001 —— 留痕，不静默
            out.append({"cmd": " ".join(c), "rc": None, "ok": False,
                        "tail": f"{type(e).__name__}: {e}"})
    return {"ok": all(o["ok"] for o in out), "runs": out}


def build_zip(skill_dir: Path) -> Path:
    """打 zip：根目录为 {skill}/，UTF-8 文件名，固定时间戳（便于比对哈希）。"""
    OUT.mkdir(parents=True, exist_ok=True)
    zpath = OUT / f"{skill_dir.name}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in iter_files(skill_dir):
            arc = f"{skill_dir.name}/{p.relative_to(skill_dir).as_posix()}"
            zi = zipfile.ZipInfo(arc, date_time=(2026, 10, 25, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, p.read_bytes())
    return zpath


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="WorkBuddy 技能包自检 + 打包")
    ap.add_argument("--check", action="store_true", help="只自检，不打包")
    ap.add_argument("--json", action="store_true", help="机读输出")
    args = ap.parse_args(argv)

    skills = [d for d in sorted(ROOT.iterdir()) if d.is_dir() and (d / "SKILL.md").is_file()]
    if not skills:
        print("✗ 找不到任何技能目录（需含 SKILL.md）", file=sys.stderr)
        return 2

    report: dict = {"skills": [], "ok": True}
    for d in skills:
        r = check_skill(d)
        st = run_selftest(d) if not args.check else {"ok": True, "runs": []}
        entry = {"dir": d.name, **r, "selftest": st}
        report["skills"].append(entry)
        if not (r["ok"] and st["ok"]):
            report["ok"] = False

    if not args.check:
        report["zips"] = []
        if report["ok"]:
            for d in skills:
                z = build_zip(d)
                h = hashlib.sha256(z.read_bytes()).hexdigest()[:16]
                report["zips"].append({"zip": z.name, "bytes": z.stat().st_size, "sha256_16": h})
        else:
            report["zips_note"] = "自检未通过，未打包（先修问题，别把坏包传上去）"

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1

    for e in report["skills"]:
        print("=" * 74)
        print(f"【{e['info']['skill']}】文件 {e['info']['files']} 个")
        if e["info"].get("extra_dirs"):
            print(f"  非官方四类子目录（刻意保留）：{', '.join(e['info']['extra_dirs'])}")
        if e["problems"]:
            for p in e["problems"]:
                print(f"  ✗ {p}")
        else:
            print("  ✓ frontmatter / 路径 / 编码 / 换行 全部通过")
        for run in e["selftest"]["runs"]:
            mark = "✓" if run["ok"] else "✗"
            print(f"  {mark} selftest rc={run['rc']}  {run['tail']}")

    if report.get("zips"):
        print("=" * 74)
        for z in report["zips"]:
            print(f"  → _marketplace/dist/{z['zip']}  {z['bytes'] / 1024:.1f} KB  sha256:{z['sha256_16']}")
    elif report.get("zips_note"):
        print(f"\n⛔ {report['zips_note']}")

    print(f"\n总判定：{'全部通过' if report['ok'] else '有不通过项'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

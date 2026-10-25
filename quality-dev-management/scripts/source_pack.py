#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""source_pack.py —— 把源码目录打成单文件可读 HTML（零依赖，仅标准库）

产物特性：
    · 只有一份 .html，内联 <style>，无外部 JS / CSS / CDN / 图片
    · 左侧目录树：原生 <details> 折叠，不靠 JS
    · 点击文件名跳到对应源码，锚点 id 形如 f-1
    · 每行行号 + 极简语法高亮（注释 / 字符串 / 数字 / 关键字四类 CSS 类）
    · 纯 LF 写盘

退出码（口径见 `00_工程规范.md` §三）：
    0  打包成功
    2  脚本自身崩了
    3  判据/输入不可用（目录不存在、无匹配文件、输出目录不存在、用法错）

用法：
    python source_pack.py <源码目录> -o out.html [--ext .py,.md] [--exclude dir1,dir2]
                          [--title 名称] [--max-bytes 2000000]
    python source_pack.py --selftest
"""

from __future__ import annotations

import html
import os
import re
import sys
import tempfile
from pathlib import Path

RC_OK = 0
RC_CRASH = 2
RC_UNAVAILABLE = 3

DEFAULT_EXTS = (
    ".py .js .ts .tsx .jsx .java .go .rs .c .h .cpp .hpp .cs .php .rb .sh .bash "
    ".sql .html .htm .css .scss .md .txt .yml .yaml .json .toml .ini .cfg .conf"
).split()

DEFAULT_EXCLUDES = {
    ".git", ".svn", ".hg", "__pycache__", "node_modules", ".venv", "venv", "env",
    ".idea", ".vscode", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist",
    "build", ".tox", ".next", ".cache", "target",
}

CSTYLE = {".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".c", ".h", ".cpp", ".hpp", ".cs", ".php", ".scss"}
HSTYLE = {".py", ".rb", ".sh", ".bash", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf"}
SQLSTYLE = {".sql"}
HTMLSTYLE = {".html", ".htm"}

KEYWORDS = {
    "python": set("""and as assert async await break class continue def del elif else except finally for from
        global if import in is lambda nonlocal not or pass raise return try while with yield None True False
        self match case""".split()),
    "c": set("""abstract as bool break byte case catch char class const continue default delete do double else
        enum extends final finally float for function goto if implements import in instanceof int interface
        let long namespace new null package private protected public return short static struct super switch
        synchronized this throw throws transient try typeof var void volatile while yield true false
        fn pub use impl match mut mod const async await defer go chan func type range map string""".split()),
}

_NUM_RE = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?[a-zA-Z]*")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


# ---------------------------------------------------------------- 高亮


def _lang_of(ext: str) -> tuple[str, set[str], tuple[str, ...], str]:
    """返回 (语言, 关键字集, 行注释前缀元组, 引号字符)。"""
    if ext == ".py" or ext == ".rb":
        return "py", KEYWORDS["python"], ("#",), "'\""
    if ext in HSTYLE:
        return "hash", set(), ("#",), "'\""
    if ext in CSTYLE:
        return "c", KEYWORDS["c"], ("//", "/*"), "'\"`"
    if ext in SQLSTYLE:
        return "sql", set(), ("--",), "'\""
    if ext in HTMLSTYLE:
        return "html", set(), ("<!--",), "'\""
    return "plain", set(), (), ""


def _scan_string(line: str, start: int, quote: str) -> int:
    """从 start 扫到字符串结束，返回结束位置（不含）。未闭合则到行尾。"""
    i = start + 1
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "\\":
            i += 2
            continue
        if ch == quote:
            return i + 1
        i += 1
    return n


def tokenize(line: str, lang: str, kw: set[str], comments: tuple[str, ...], quotes: str):
    """把一行切成 (css 类, 文本) 序列。类为 "" 表示普通文本。"""
    tokens: list[tuple[str, str]] = []
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        hit = None
        for prefix in comments:
            if line.startswith(prefix, i):
                hit = prefix
                break
        if hit:
            tokens.append(("c", line[i:]))
            return tokens
        if quotes and ch in quotes:
            j = _scan_string(line, i, ch)
            tokens.append(("s", line[i:j]))
            i = j
            continue
        if ch.isdigit():
            m = _NUM_RE.match(line, i)
            if m:
                tokens.append(("n", m.group(0)))
                i = m.end()
                continue
        if ch.isalpha() or ch == "_":
            m = _IDENT_RE.match(line, i)
            if m:
                word = m.group(0)
                tokens.append(("k" if word in kw else "", word))
                i = m.end()
                continue
        tokens.append(("", ch))
        i += 1
    return tokens


def _md_line_class(line: str) -> tuple[str, int]:
    """markdown 行级简化高亮：返回 (类, 去掉的前缀长度)。"""
    stripped = line.lstrip()
    if stripped.startswith("```"):
        return "c", 0
    if stripped.startswith("#"):
        return "h", 0
    if stripped.startswith(("> ", "* ", "- ", "+ ")):
        return "b", 0
    return "", 0


def render_line(line: str, ext: str) -> str:
    """渲染一行源码为 HTML 片段（不含行号）。"""
    if ext in (".md", ".txt"):
        cls, _ = _md_line_class(line) if ext == ".md" else ("", 0)
        body = html.escape(line, quote=False)
        if not body:
            body = "&#8203;"
        return f'<span class="{cls}">{body}</span>' if cls else f'<span class="l">{body}</span>'

    lang, kw, comments, quotes = _lang_of(ext)
    parts: list[str] = []
    for cls, text in tokenize(line, lang, kw, comments, quotes):
        esc = html.escape(text, quote=False)
        parts.append(f'<span class="{cls}">{esc}</span>' if cls else esc)
    body = "".join(parts) or "&#8203;"
    return f'<span class="l">{body}</span>'


# ---------------------------------------------------------------- 收集文件


def collect(src: Path, exts: set[str], excludes: set[str], max_bytes: int):
    """返回 (files, skipped)。files 为 [(相对 posix 路径, 绝对路径, 行数, 字节数)]。"""
    files, skipped = [], []
    for root, dirs, names in os.walk(src):
        dirs[:] = sorted([d for d in dirs if d not in excludes and not d.startswith(".git")])
        for name in sorted(names):
            p = Path(root) / name
            if p.suffix.lower() not in exts:
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            rel = p.relative_to(src).as_posix()
            if size > max_bytes:
                skipped.append((rel, f"超过 {max_bytes} 字节（{size}）"))
                continue
            try:
                raw = p.read_bytes()
            except OSError as exc:
                skipped.append((rel, f"读不出：{exc}"))
                continue
            if b"\x00" in raw[:4096]:
                skipped.append((rel, "疑似二进制"))
                continue
            text = raw.decode("utf-8", errors="replace")
            files.append((rel, p, len(text.splitlines()), size))
    files.sort(key=lambda x: (x[0].count("/"), x[0].lower()))
    return files, skipped


# ---------------------------------------------------------------- 目录树


def build_tree(paths: list[str]) -> dict:
    tree: dict = {"files": [], "dirs": {}}
    for p in paths:
        node = tree
        parts = p.split("/")
        for d in parts[:-1]:
            node = node["dirs"].setdefault(d, {"files": [], "dirs": {}})
        node["files"].append(p)
    return tree


def render_tree(node: dict, index: dict[str, int], depth: int = 0) -> str:
    out: list[str] = []
    for dirname in sorted(node["dirs"], key=str.lower):
        child = node["dirs"][dirname]
        open_attr = " open" if depth < 1 else ""
        out.append(f'<details{open_attr}><summary class="dir">{html.escape(dirname)}/</summary>')
        out.append(render_tree(child, index, depth + 1))
        out.append("</details>")
    for p in sorted(node["files"], key=str.lower):
        n = index[p]
        name = p.split("/")[-1]
        out.append(f'<a class="fname" href="#f-{n}" title="{html.escape(p)}">{html.escape(name)}</a>')
    return "\n".join(out)


# ---------------------------------------------------------------- HTML 模板

CSS = """
:root{--bg:#fbfbfa;--fg:#1f2328;--mut:#6b7280;--line:#e5e7eb;--accent:#0b63c5;}
*{box-sizing:border-box;}
body{margin:0;background:var(--bg);color:var(--fg);
     font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;font-size:14px;}
#side{position:fixed;top:0;left:0;bottom:0;width:280px;overflow:auto;padding:12px;
      background:#fff;border-right:1px solid var(--line);font-size:13px;}
#side h1{font-size:14px;margin:0 0 8px;font-weight:600;}
#side .meta{color:var(--mut);font-size:12px;margin-bottom:10px;line-height:1.6;}
#side details{margin:2px 0 2px 10px;}
#side summary{cursor:pointer;color:var(--mut);padding:1px 0;}
#side .dir{color:#374151;}
#side a.fname{display:block;padding:1px 0 1px 10px;color:var(--accent);text-decoration:none;
      white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
#side a.fname:hover{background:#eef4fd;}
#main{margin-left:280px;padding:16px 20px 60px;}
section.file{margin-bottom:28px;}
section.file h2{font-size:14px;font-weight:600;margin:0 0 2px;word-break:break-all;}
section.file .stat{color:var(--mut);font-size:12px;margin-bottom:6px;}
pre.code{margin:0;background:#fff;border:1px solid var(--line);border-radius:6px;
      padding:8px 0;overflow:auto;font-family:Consolas,"Cascadia Mono",Menlo,monospace;
      font-size:12.5px;line-height:1.55;tab-size:4;}
pre.code .lnum{display:inline-block;width:52px;padding-right:12px;text-align:right;
      color:#9ca3af;user-select:none;-webkit-user-select:none;}
pre.code .l{white-space:pre;}
pre.code .k{color:#0b63c5;font-weight:600;}
pre.code .s{color:#0a7a3d;}
pre.code .c{color:#8b949e;font-style:italic;}
pre.code .n{color:#a4520a;}
pre.code .h{color:#0b63c5;font-weight:700;}
pre.code .b{color:#374151;font-weight:600;}
#skip{color:#a4520a;font-size:12px;}
"""


def build_html(title: str, src: Path, files, skipped) -> str:
    index = {rel: i for i, (rel, *_rest) in enumerate(files, start=1)}
    total_lines = sum(f[2] for f in files)
    total_bytes = sum(f[3] for f in files)

    tree_html = render_tree(build_tree([f[0] for f in files]), index)

    sections: list[str] = []
    for rel, path, nlines, size in files:
        n = index[rel]
        text = path.read_bytes().decode("utf-8", errors="replace")
        ext = path.suffix.lower()
        rows = []
        for no, line in enumerate(text.splitlines(), start=1):
            rows.append(f'<span class="lnum">{no}</span>{render_line(line, ext)}')
        if not rows:
            rows.append('<span class="lnum">1</span><span class="l">&#8203;</span>')
        sections.append(
            f'<section class="file" id="f-{n}" data-lines="{nlines}">\n'
            f'<h2>{html.escape(rel)}</h2>\n'
            f'<div class="stat">{nlines} 行 · {size} 字节</div>\n'
            f'<pre class="code">' + "\n".join(rows) + "</pre>\n</section>"
        )

    skip_html = ""
    if skipped:
        items = "".join(f"<li>{html.escape(r)}：{html.escape(w)}</li>" for r, w in skipped)
        skip_html = f'<section class="file"><h2>未打包</h2><ul id="skip">{items}</ul></section>'

    meta = (
        f'{len(files)} 个文件 · {total_lines} 行 · {total_bytes} 字节<br>'
        f'源目录：{html.escape(str(src))}<br>生成：source_pack.py（内联样式，无外链）'
    )
    return (
        "<!DOCTYPE html>\n"
        f"<!-- source_pack: files={len(files)} lines={total_lines} bytes={total_bytes} -->\n"
        "<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{html.escape(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
        f'<nav id="side"><h1>{html.escape(title)}</h1><div class="meta">{meta}</div>\n'
        f"{tree_html}\n</nav>\n<main id=\"main\">\n" + "\n".join(sections) + "\n" + skip_html + "\n</main>\n</body>\n</html>\n"
    )


# ---------------------------------------------------------------- 打包入口


def parse_exts(raw: str | None) -> set[str]:
    if not raw:
        return {e.lower() for e in DEFAULT_EXTS}
    out = set()
    for part in raw.replace(";", ",").split(","):
        p = part.strip().lower()
        if not p:
            continue
        out.add(p if p.startswith(".") else "." + p)
    return out


def pack(src: Path, out: Path, exts: set[str], excludes: set[str], title: str, max_bytes: int) -> tuple[int, int]:
    """执行打包，返回 (文件数, 总行数)。输入不可用抛 ValueError（调用方转 rc=3）。"""
    if not src.exists():
        raise ValueError(f"源码目录不存在：{src}")
    if not src.is_dir():
        raise ValueError(f"不是目录：{src}")
    if not out.parent.exists():
        raise ValueError(f"输出目录不存在：{out.parent}")
    files, skipped = collect(src, exts, excludes, max_bytes)
    if not files:
        raise ValueError(f"目录内没有匹配的文件（扩展名：{sorted(exts)}）")
    doc = build_html(title, src, files, skipped)
    out.write_bytes(doc.encode("utf-8"))
    return len(files), sum(f[2] for f in files)


# ---------------------------------------------------------------- 自测


def _selftest() -> int:
    print("=" * 68)
    print("source_pack.py --selftest")
    print("=" * 68)
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="pack_selftest_") as tmp:
        root = Path(tmp)
        (root / "a.py").write_text(
            "# 注释行\nimport os\n\n\ndef f(x):\n    return x + 1\n", encoding="utf-8", newline="\n"
        )
        (root / "b.md").write_text("# 标题\n\n正文一行\n", encoding="utf-8", newline="\n")
        out = root / "out.html"

        n, lines = pack(root, out, parse_exts(None), set(DEFAULT_EXCLUDES), "自测", 2_000_000)
        raw = out.read_bytes()
        doc = raw.decode("utf-8")

        checks = [
            ("文件数 = 2", n == 2, f"实测 {n}"),
            ("总行数 = 9", lines == 9, f"实测 {lines}"),
            ("含 a.py", "a.py" in doc, "未找到文件名 a.py"),
            ("含 b.md", "b.md" in doc, "未找到文件名 b.md"),
            ("有行号元素", doc.count('class="lnum"') == 9, f"实测 {doc.count('class=\"lnum\"')}"),
            ("无外部脚本", "<script" not in doc, "出现 <script"),
            ("无外链样式", "<link" not in doc, "出现 <link"),
            ("无 src= 引用", "src=" not in doc, "出现 src="),
            ("无 @import", "@import" not in doc, "出现 @import"),
            ("有锚点", 'id="f-1"' in doc and 'href="#f-1"' in doc, "锚点或跳转缺失"),
            ("有统计注释", "source_pack: files=2 lines=9" in doc, "缺 files/lines 统计注释"),
            ("有 data-lines", 'data-lines="6"' in doc, "缺 data-lines 属性"),
            ("有高亮类", 'class="k"' in doc and 'class="c"' in doc, "关键字/注释类缺失"),
            ("纯 LF 写盘", b"\r" not in raw, "检出 CRLF"),
        ]
        for label, ok, detail in checks:
            print(f"[{'PASS' if ok else 'FAIL'}] {label}" + ("" if ok else f" :: {detail}"))
            if not ok:
                failures.append(label)

        # 反向用例：目录不存在必须 rc=3（判据不可用），不能当成功
        try:
            pack(root / "no_such_dir", root / "x.html", parse_exts(None), set(DEFAULT_EXCLUDES), "t", 1000)
            failures.append("不存在目录未报不可用")
            print("[FAIL] 不存在目录应报不可用")
        except ValueError as exc:
            print(f"[PASS] 不存在目录 → 不可用（{exc}）")

    print("-" * 68)
    if failures:
        print("自测不通过：")
        for f in failures:
            print(f"  - {f}")
        return RC_CRASH
    print("自测通过：文件名 / 行号 / 无外链 / 纯 LF 全部符合")
    return RC_OK


# ---------------------------------------------------------------- 命令行


USAGE = """用法：
  python source_pack.py <源码目录> -o out.html [选项]
  python source_pack.py --selftest

选项：
  -o, --out <文件>       必填，输出 HTML 路径
  --ext a,b              扩展名白名单，逗号分隔（默认 30 余种文本扩展名）
  --exclude d1,d2        额外排除目录名（默认已排除 .git/__pycache__/node_modules 等）
  --title <名称>         页面标题（默认取目录名）
  --max-bytes <n>        单文件上限，超过则跳过并列入「未打包」（默认 2000000）
"""


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return RC_UNAVAILABLE if not argv else RC_OK
    if argv[0] == "--selftest":
        return _selftest()

    src_raw = None
    out_raw = None
    ext_raw = None
    exclude_raw = None
    title = None
    max_bytes = 2_000_000

    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-o", "--out"):
            if i + 1 >= len(argv):
                print("[GRAY] 用法错：-o 缺少参数")
                return RC_UNAVAILABLE
            out_raw = argv[i + 1]
            i += 2
            continue
        if a.startswith("--out="):
            out_raw = a.split("=", 1)[1]
            i += 1
            continue
        if a in ("--ext", "--exclude", "--title", "--max-bytes"):
            if i + 1 >= len(argv):
                print(f"[GRAY] 用法错：{a} 缺少参数")
                return RC_UNAVAILABLE
            val = argv[i + 1]
            if a == "--ext":
                ext_raw = val
            elif a == "--exclude":
                exclude_raw = val
            elif a == "--title":
                title = val
            else:
                try:
                    max_bytes = int(val)
                except ValueError:
                    print(f"[GRAY] 用法错：--max-bytes 需要整数，收到 {val!r}")
                    return RC_UNAVAILABLE
            i += 2
            continue
        if a.startswith("-"):
            print(f"[GRAY] 用法错：未知选项 {a}")
            return RC_UNAVAILABLE
        if src_raw is None:
            src_raw = a
        else:
            print(f"[GRAY] 用法错：多余参数 {a}")
            return RC_UNAVAILABLE
        i += 1

    if src_raw is None or out_raw is None:
        print("[GRAY] 用法错：必须同时给 <源码目录> 与 -o <输出.html>")
        print(USAGE)
        return RC_UNAVAILABLE

    src = Path(src_raw).resolve()
    out = Path(out_raw).resolve()
    exts = parse_exts(ext_raw)
    excludes = set(DEFAULT_EXCLUDES)
    for d in (exclude_raw or "").replace(";", ",").split(","):
        if d.strip():
            excludes.add(d.strip())
    ttl = title or src.name

    try:
        n, lines = pack(src, out, exts, excludes, ttl, max_bytes)
    except ValueError as exc:
        print(f"[GRAY] 输入不可用：{exc}")
        return RC_UNAVAILABLE
    print(f"已生成：{out}")
    print(f"文件 {n} 个 · 总行 {lines} 行 · {out.stat().st_size} 字节")
    print("自检：页面内无 <script> / <link> / src= / @import（纯内联样式，断网可开）")
    return RC_OK


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as exc:  # 兜底：脚本自身崩了
        import traceback

        print(f"[CRASH] 脚本内部异常：{exc!r}")
        traceback.print_exc()
        raise SystemExit(RC_CRASH)

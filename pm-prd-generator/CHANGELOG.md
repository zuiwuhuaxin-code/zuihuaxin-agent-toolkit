# 变更记录

格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

## [1.1.0] - 2026-10-25

### 变更
- **公开化改造**：PRD 编写规范内化进包，新增 `references/00_PRD编写规范.md`（14 章骨架、各章填写要求、SVG 流程图与原型图规范、HTML 交付规范、质量自检 10 条、五步走与依据四问）。
- 去掉全部外部文档依赖与内部路径引用，装进任何环境即可运行。
- `SKILL.md` 与 `README.md` 的骨架引用统一指向包内 `references/00`。
- 新增 `tests/test_prd_lint.py`（5 条真跑断言：正例/缺项/判据不可用三态 + 防恒真），并做过元验证（判据改成恒真 → 测试变红）。
- 补充 `LICENSE`（MIT）与 `.gitignore`。

### 兼容性
- 六阶段流程、`scripts/prd_lint.py` 的 8 项检查与退出码语义**未改动**。

## [1.0.0] - 2026-10-25

### 新增
- 首版：S1 需求澄清 → S2 十个关键问题 → S3 需求分析报告 → S4 PRD 生成 → S5 原型与 HTML → S6 自查与交付。
- `scripts/prd_lint.py`：8 条硬要求的机器判据，零依赖，rc 四档。

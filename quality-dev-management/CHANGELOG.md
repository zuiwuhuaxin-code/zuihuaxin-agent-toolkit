# 变更记录

格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

## [1.2.0] - 2026-10-25

### 变更
- **补齐 WorkBuddy 开放平台的 SKILL.md frontmatter 必填项**：`display_name`（展示名）、`display_name_en`、`description_zh`、`description_en`、`author`，并补 `examples_zh` / `examples_en`（商品页「试试这样问我」）。
- 依据 `https://open.workbuddy.cn/docs/skill` 的字段表逐项核对；原 frontmatter 只有 `name` / `description` / `version` / `agent_created` 四项，直接上传会因缺必填字段解析失败。

### 兼容性
- **指令正文一个字未改**，八阶段流程、四道闸、`acceptance_gate.py` 与 `source_pack.py` 的接口与退出码语义均未改动。
- 仅元数据变更，不影响已在本地安装的用法。

## [1.1.0] - 2026-10-25

### 变更
- **公开化改造**：工程规范内化进包，新增 `references/00_工程规范.md`（执行五步、依据四问、rc 四档、反向变异对照组、验调用不验定义、审查方≠施工方与审查三级判据、闸门四层与置信度降档、自测可靠性、产物核查）。
- 去掉全部外部规范文件引用与内部路径，8 份 reference 的判据指针统一指向包内 `00_工程规范.md`。
- `README.md` 的「出处」章节改为「判据索引（全部在包内）」。
- 新增 `tests/test_acceptance_gate.py`（5 条）与 `tests/test_source_pack.py`（8 条），全部真跑行为，并做过元验证（把「检出」分支改成恒不触发 → 测试变红）。
- 补充 `LICENSE`（MIT）与 `.gitignore`。

### 兼容性
- 八阶段流程、四道闸、`scripts/acceptance_gate.py` 与 `scripts/source_pack.py` 的接口与退出码语义**未改动**。

## [1.0.0] - 2026-10-25

### 新增
- 首版：S1 项目评估 → S2 施工计划 → S3 编码与自测 → S4 红队攻防 → S5 蓝队防守 → S6 独立审查 → S7 闭环完善 → S8 源码汇总。
- 三条贯穿硬规矩：产物可核 / 反向变异带对照组 / 审查方≠施工方。
- `scripts/acceptance_gate.py`：验收闸门，五类检查项。
- `scripts/source_pack.py`：源码汇总为单文件 HTML。

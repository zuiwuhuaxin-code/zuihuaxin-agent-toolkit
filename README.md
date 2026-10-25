# 醉花心 Agent 管理工具

> 两个把「一句话需求」变成「能验收的交付物」的 Agent Skill。
> 纯文档 + 零依赖 Python 脚本，装进任何支持 Skill 机制的 Agent 环境即可运行。

## 这个仓库解决什么问题

用 Agent 干活，最常见的两种失败不是「它不会写」，而是：

1. **需求没说清就开工** —— 交付一份看起来完整、但每条都无法验收的文档；
2. **自己写自己验** —— 测试全绿，上线就炸，因为绿灯是施工方自己点的。

两个 Skill 分别针对这两件事：

| Skill | 治什么病 | 产出 |
|---|---|---|
| [`pm-prd-generator`](pm-prd-generator/) | 需求模糊就动手，PRD 写成功能清单，验收标准写不出 | 六阶段推进：澄清 → 提问 → 需求分析 → PRD → 原型 → 自查交付；含 14 章 PRD 骨架与 8 条机器可核判据 |
| [`quality-dev-management`](quality-dev-management/) | 施工与验收同一个人，假绿通过 | 八阶段流程：评估 → 计划 → 编码自测 → 红队 → 蓝队 → 独立审查 → 闭环 → 源码汇总；含四道闸与审查三级判据 |

两个 Skill 各自**完整自包含**：判据、模板、检查清单全部在包内，不依赖任何外部文档。

## 快速开始

### WorkBuddy

```bash
git clone https://github.com/zuiwuhuaxin-code/醉花心Agent管理工具.git
cp -r "醉花心Agent管理工具/pm-prd-generator" ~/.workbuddy/skills/
cp -r "醉花心Agent管理工具/quality-dev-management" ~/.workbuddy/skills/
```

### Claude Code / 其它读取 SKILL.md 的环境

把两个目录放进该环境的 skills 目录即可（Claude Code 为 `~/.claude/skills/`）。`SKILL.md` 的 frontmatter 会被自动识别。

### 不使用 Skill 机制

两个包都能当**流程卡**手工照做：打开 `SKILL.md` 看阶段索引，每进一个阶段打开 `references/` 下对应文档，照「操作步骤」编号执行，用「输出模板」填空，交付前对照「反例」自检。

脚本可独立运行，不依赖 Agent：

```bash
# PRD 八项检查（零依赖）
python pm-prd-generator/scripts/prd_lint.py --selftest

# 验收闸门
python quality-dev-management/scripts/acceptance_gate.py --selftest

# 源码汇总为单文件 HTML
python quality-dev-management/scripts/source_pack.py --selftest
```

## 几条贯穿全部判据的主张

这些是设计这两个 Skill 时反复撞出来的结论，写在各自的 `references/00_*.md` 里，也是它们唯一的共同底色：

**判据必须机器可核。** 「文档写得清楚」不可核，「每个 F 编号在 §6 有对应表格行」可核。凡是要求人主观打分的条目，一律降级为提示，不进闸门。

**通过项也要有对照组。** 只验「该报的报了」不够——恒真的实现也能让它全绿。必须同时证明「不该报的没报」。

**审查方 ≠ 施工方。** 自己审自己等于没审。同一会话里换了角色的复审也不算，必须换人或换环境。

**退出码要分四档。** `0` 通过 / `1` 检出问题 / `2` 自身崩溃 / `3` 判据不可用。混成一个非零码，调用方就会把「文件读不出」当成「内容不合格」去改正文，白改一轮。

**闸门宁可降级，不要焊死。** 阈值定得太严，第一次被误判后使用者就会把它关掉，从此彻底失效。取分位而不是取均值，就是为此。

## 目录结构

```
.
├── README.md                     本文件
├── LICENSE                       MIT
├── .gitignore
├── pm-prd-generator/             产品经理：需求 → PRD
│   ├── SKILL.md                  六阶段索引
│   ├── references/               01~06 分阶段文档 + 00 内置规范
│   ├── scripts/prd_lint.py       8 条硬要求机器判据
│   └── tests/                    真跑断言
└── quality-dev-management/       研发管理：编码 → 可交付
    ├── SKILL.md                  八阶段索引 + 三条硬规矩
    ├── references/               01~08 分阶段文档 + 00 内置规范
    ├── scripts/                  验收闸门 + 源码汇总
    └── tests/                    真跑断言
```

## 版本与变更

各自包内的 `CHANGELOG.md` 为准。两个包版本独立演进，不强制同步。

## 许可

MIT，见 [LICENSE](LICENSE)。

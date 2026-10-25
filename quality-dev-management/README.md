# quality-dev-management · 使用说明

一套「从 PRD 到可验收代码」的工程管理范式，做成可独立上架的 Skill 包。给工程侧的人或 Agent 用：拿到一份 PRD 之后，按八个阶段推进，每个阶段都留下能被别人复核的证据。

配套的上游 Skill 是 `pm-prd-generator`（负责把需求写成 PRD）。本 Skill 只读 PRD，⛔ 不改需求。

## 一、它解决什么问题

拿到 PRD 直接开写，通常会坏三件事：

| 坏法 | 后果 | 本 Skill 的对策 |
|---|---|---|
| 照单全收 | PRD 与现状打架的地方没人说，写到一半返工 | S1 强制输出冲突清单，每条挂归属 |
| 自己说了算 | 自测全绿就交付，其实判据根本没抓错 | S3 反向变异 + 对照组；S6 换人只读审 |
| 交付不可核 | 「已完成」「已优化」写满报告，别人无法验证 | 全流程只用 rc / 文件 / 行号 / 哈希说话 |

## 二、八阶段一览

| 阶段 | 干什么 | 交出来的东西 | 详细说明 |
|---|---|---|---|
| S1 项目评估 | 读 PRD + 读现状，找冲突 | 评估报告 + 冲突清单 | `references/01_项目评估.md` |
| S2 施工计划 | 拆任务、定顺序、定验收点、定回滚点 | 施工计划 | `references/02_施工计划.md` |
| S3 编码与自测 | 写代码 + 正/反/边界自测 + 反向变异 | 代码 + 自测与变异记录 | `references/03_编码与自测.md` |
| S4 红队攻防 | 扮攻击者找缺口，自己先修一轮 | 红队报告（G/E/A/I/F 五列） | `references/04_红队攻防.md` |
| S5 蓝队防守 | 事前/事中/事后补全链路 | 防御报告 | `references/05_蓝队防守.md` |
| S6 独立审查 | 换身份、只读、先读 PRD 再读码 | 验收标准 + 测试用例 + 审查报告 | `references/06_独立审查.md` |
| S7 闭环完善 | 照审查报告逐条改，跑到闸绿 | 终版代码 + 整改对照表 | `references/07_闭环完善.md` |
| S8 源码汇总 | 全部源码打成一个 HTML | `源码.html` | `references/08_源码汇总HTML.md` |

阶段是串行的：上一阶段的产物是下一阶段的唯一输入。四道闸卡在 S1→S2、S2→S3、S3→S4、S6→S7 之间。

## 三、三条硬规矩（背下来就够用）

1. **产物必须可核**：说「做完了」不算，得给 rc、文件、行号、哈希。
2. **反向变异必带对照组**：改坏了要红，不改要绿；只红不绿说明不了任何事。
3. **审查方 ≠ 施工方**：独立审查必须换身份、只读；自审不算。

## 四、怎么用

### 4.1 作为 Skill 加载

本包是标准 Skill 目录结构（`SKILL.md` + `references/` + `scripts/`），**零依赖**（脚本只用 Python 标准库，Python 3.8+）。

把整个 `quality-dev-management/` 目录放到你的 skills 目录下：

| 环境 | 放置位置 |
|---|---|
| WorkBuddy | `~/.workbuddy/skills/quality-dev-management/`（Windows：`C:\Users\<你>\.workbuddy\skills\`） |
| Claude Code 及兼容实现 | 对应的 skills 目录，如 `~/.claude/skills/quality-dev-management/` |
| 没有 skills 机制 | 放哪都行 —— 把 `SKILL.md` 直接喂给模型，或按 §4.2 手工走 |

`SKILL.md` 的 frontmatter 会被自动识别；**目录名要与 `name` 字段一致**，否则部分实现不识别。
触发词：项目评估、施工计划、编码自测、红蓝攻防、独立审查、源码汇总。

### 4.2 手工按流程走

1. 先读 `SKILL.md` 的八阶段索引，确认当前在哪一阶段。
2. 进入某阶段前，读对应 `references/0X_*.md`（每份含目标、步骤、输出模板、反例、衔接条件）。
3. 照模板填产物，跑完该阶段的闸再进下一阶段。

### 4.3 两个脚本

**`scripts/acceptance_gate.py` —— 验收闸门**（零依赖，Python 3.8+）

```bash
python scripts/acceptance_gate.py 验收清单.json   # 0 全过 / 1 有未过项 / 3 判据不可用
python scripts/acceptance_gate.py --example      # 打印清单模板
python scripts/acceptance_gate.py --selftest     # 自测：四份清单应得 0 / 1 / 3 / 3
```

清单长这样（`items` 每项一个检查）：

```json
{
  "name": "示例验收清单",
  "base_dir": ".",
  "items": [
    {"id": "AC-01", "desc": "主文档存在", "type": "file_exists", "path": "SKILL.md"},
    {"id": "AC-02", "desc": "含关键字段", "type": "file_contains",
     "path": "SKILL.md", "patterns": ["version: 1.0.0"], "min_hits": 1},
    {"id": "AC-03", "desc": "占位文件已清理", "type": "file_absent", "path": "TODO.md"},
    {"id": "AC-04", "desc": "200~320 行", "type": "line_count", "path": "SKILL.md", "min": 200, "max": 320},
    {"id": "AC-05", "desc": "脚本可编译", "type": "command",
     "cmd": ["python", "-m", "py_compile", "scripts/source_pack.py"], "expect_rc": 0}
  ]
}
```

支持五类：`file_exists` / `file_absent` / `file_contains` / `line_count` / `command`。相对路径按清单文件所在目录（或 `base_dir`）解析。

两条容易踩的规则：子命令返回 rc=2 会被当作「它自己崩了」，整条报灰（rc=3），不会被误记成检出；报灰优先于检出，所以「有未过项 + 有灰项」时最终 rc 是 3。

**`scripts/source_pack.py` —— 源码汇总**

```bash
python scripts/source_pack.py <源码目录> -o 源码.html --title "项目名"
python scripts/source_pack.py <源码目录> -o 源码.html --ext .py,.md --exclude tests
python scripts/source_pack.py --selftest
```

产物是单文件 HTML：左侧原生 `<details>` 折叠目录树、点文件名跳转、每行行号、四类语法高亮，全靠内联 CSS，无 JS、无 CDN，断网可开。

## 五、产物清单（一个完整项目跑完会得到）

```
01_项目评估报告.md        现状基线 + 冲突清单
02_施工计划.md            任务表 + 依赖 + 验收点 + 回滚点
03_自测与反向变异记录.md   正/反/边界 + 变异红绿对照
04_红队报告.md            G/E/A/I/F 五列 + 轮次
05_蓝队防御报告.md        事前/事中/事后
06_独立审查报告.md        验收标准 + 测试用例 + 三级条目
07_整改对照表.md          报告行号 → 改后 file:line
验收清单.json + gate 输出  验收记录（rc）
源码.html                 单文件可读源码
```

## 六、常见问题

**Q：PRD 写得不对怎么办？**
写进 S1 的冲突清单，标 `归属=改 PRD`，退回产品侧。⛔ 不许在施工中私改需求——那样最终交付的东西没有需求依据。

**Q：反向变异太费时间，能省吗？**
不能。省掉它，自测就只是「断言没红」，不证明断言有用。可以缩小范围：只对关键判据（校验、权限、金额、状态流转）做，但必须带对照组。

**Q：红队报告要不要找专业工具？**
S4 是思维框架 + 报告格式，不产出真实渗透结果。需要工具级扫描时按「需专项工具，本 Skill 不覆盖」标注，另开专项。

**Q：审查能不能自己来？**
不能。自审的系统性偏差正好漏掉自己没想到的分支。至少要换角色设定、只读、先读 PRD 再读码，并把 `git status --porcelain` 为空的证据写进报告。

**Q：`acceptance_gate.py` 报 rc=3 是什么意思？**
判据不可用：清单坏了、路径不对、命令跑不起来。这不是通过，也不是检出，必须先修清单/环境再跑。

## 七、已知局限

- 不替代 SAST / DAST；红蓝攻防是框架与格式，不是扫描器。
- 不保证漏洞找全；攻击面清单是启发式的。
- `acceptance_gate.py` 只核「清单里写了什么」，清单是否覆盖真实验收点由 S6 兜底。
- `source_pack.py` 不适合超大仓库：单文件 HTML 会把所有源码塞进去，几万行会产出几十 MB，需按模块分批打包。
- 不覆盖部署上线、生产监控、真实压测。

## 八、目录结构

```
quality-dev-management/
├── SKILL.md                      八阶段索引 + 三条硬规矩 + rc 口径
├── README.md                     本文件
├── CHANGELOG.md                  变更记录
├── LICENSE                       MIT
├── references/
│   ├── 00_工程规范.md            ← 判据唯一源（执行五步 / 依据四问 / rc 四档 / 审查三级 / 闸门四层…）
│   ├── 01_项目评估.md
│   ├── 02_施工计划.md
│   ├── 03_编码与自测.md
│   ├── 04_红队攻防.md
│   ├── 05_蓝队防守.md
│   ├── 06_独立审查.md
│   ├── 07_闭环完善.md
│   └── 08_源码汇总HTML.md
├── scripts/
│   ├── acceptance_gate.py
│   └── source_pack.py
└── tests/
    ├── test_acceptance_gate.py   # 真跑：造清单 → 跑闸 → 断 rc
    └── test_source_pack.py       # 真跑：造源码目录 → 打包 → 验产物
```

## 九、维护

改任何判据时，同步改 `--selftest` 样例与 `tests/`；每次改动后跑五条：

```bash
python scripts/acceptance_gate.py --selftest
python scripts/source_pack.py --selftest
python tests/test_acceptance_gate.py
python tests/test_source_pack.py
python -m py_compile scripts/acceptance_gate.py scripts/source_pack.py
```

**改判据后必做元验证**：把判据换成已知有错的实现，`tests/` 必须变红。
一直绿的测试等于没测 —— 它只证明了「代码没崩」，没证明「判据能抓」。实测记录：
把 `acceptance_gate` 的「检出」分支改成恒不触发，`tests/test_acceptance_gate.py` 立刻 rc=1。

四条全过才算改完——⛔ 只改文档不改判据，等于闸门在验一句口号。

## 十、判据索引（全部在包内）

每条判据的唯一出处都在 `references/00_工程规范.md`。**改判据改那一份**，其余文件只引用，⛔ 不再写第二套。

| 判据 | 位置 |
|---|---|
| 执行五步（含「不做什么」） | `00_工程规范.md` §一 |
| 依据四问（提交方案必附） | `00_工程规范.md` §二 |
| rc 四档（唯一退出码口径） | `00_工程规范.md` §三 |
| 反向变异必带对照组 | `00_工程规范.md` §四 |
| 验调用不验定义 / 放宽收紧要双向 | `00_工程规范.md` §五 |
| 审查方 ≠ 施工方 · 审查三级判据 | `00_工程规范.md` §六 |
| 闸门四层与置信度降档 | `00_工程规范.md` §七 |
| 自测可靠性（异常数据 / 断言 / 打桩） | `00_工程规范.md` §八 |
| 产物核查与续跑 | `00_工程规范.md` §九 |
| 八阶段划分与四道闸 | `SKILL.md` §四（本包自有） |

> 本包**自包含**：装进任何环境都能跑，不依赖外部规范文件。若你的团队已有自己的工程规范，
> 把 `00_工程规范.md` 换成你们的即可 —— 但**只许有一份**，两套并存必然漂移。

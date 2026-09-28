# 合规、原创性与团队权属声明

> 适用范围：AI PR Review Assistant 参赛提交包（源码、随包前端产物、演示与文档）。
> 声明日期：2026-09-28。
> 配套文件：第三方组件与字体许可见 [`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)；
> 提交包密钥卫生守卫为 `scripts/check_submission_hygiene.py`。

---

## 一、项目定位

AI PR Review Assistant 是一个**本地优先、可解释、可复盘**的 AI PR 代码审查工作台：
以 GitHub Pull Request 为输入，生成透明的审查计划，结合确定性规则、Python AST 分析与
大模型判断输出 Finding，并对每条 Finding 做文件 / 行号 / diff 证据验证，最后把结果写入
本地历史供人工反馈与复盘。

核心能力主张是**「结论可验证」**：每条结论都必须能落到具体文件、具体行号、具体代码片段，
无法验证的结论会被显式标记为 `needs_review` 而不是直接呈现给用户。
本项目**不宣称**在真实 PR 上的泛化准确率 —— 内置 benchmark 是精选回归样例集，
只用于防止规则退化，不代表真实世界表现。

- 仓库：<https://github.com/JiangLai999/AI-PR-Review-Assistant>
- 许可证：MIT（见根目录 `LICENSE`）

---

## 二、许可声明

本项目**自研代码**以 **MIT License** 发布。版权所有者署名
**AI PR Review Assistant Contributors**，年份 **2026**。

MIT 许可证允许自由使用、复制、修改、合并、再分发与再许可（含商业用途），
条件是保留版权声明与许可声明；软件按「现状」提供，不附带任何担保。

需要特别区分的是**许可边界**：

- MIT 覆盖的是**本项目自研代码与文档**；
- **第三方组件不因被本项目使用而变成 MIT**，它们各自适用自己的许可证，
  逐条清单与证据见 [`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)；
- 其中 **PyGithub 为 LGPL-3.0**、**gsap 与 @gsap/react 为 GreenSock Standard License（非 OSI 开源许可）**、
  **字体为 SIL OFL-1.1**，这三类各有额外义务，再分发前必须读 [`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) §2.1、§四、§七。

本项目**不使用**任何「来源不明 / 禁止再分发 / 需付费授权」的组件。

---

## 三、团队主导与 AI 辅助的边界

**AI 工具不构成版权主体。** 
AI 生成的内容必须经团队理解、修改或明确复核后才进入仓库；未经团队审阅的 AI 产物不进入提交包。

###  AI 辅助部分（工具，非权利主体）

本项目在开发与评审过程中使用过下列 AI 工具：

| 工具 | 性质 | 是否版权主体 |
|---|---|---|
| Claude Code | 开发辅助 / 评审工具 | **否** |
| MiMo Code | 开发辅助 / 评审工具 | **否** |
| OpenCode | 协作 agent / 评审工具 | **否** |
| Codex | 协作 agent / 评审工具 | **否** |
| 大模型 API（DeepSeek、Qwen、GLM、MiMo、Anthropic 等） | 被评审对象 / 被调用服务 | **否** |

这些工具在本项目中的定位是**开发辅助与评审工具**，具体包括：提出候选方案、
起草与改写代码片段、生成文档草稿、执行只读审计、跑验证命令。

因此：

1. **AI 代理身份（例如 `codex`、`opencode`）只作为「工具」标注，不列为版权主体、
   不列入团队成员表。** git 历史中的 `codex` 作者名表示该提交由该 AI 工具产出，
   其内容的所有权与责任仍归属团队。
2. 本项目**不主张**任何 AI 工具输出的著作权归属；把 AI 工具写入作者列表会造成
   对权利归属的误读，故明确排除。
3. 提交包中若展示 AI 生成的图示或文案，按 §七 标注为「AI 生成的展示性材料」。

### 参考项目边界

本项目在设计过程中参考过以下开源 / 公开项目：

| 参考项目 | 参考了什么 | 明确没有做什么 |
|---|---|---|
| MiMo Code | 设计思路、交互范式、工程方法 | **未复制其源代码** |
| Claude Code | 设计思路、交互范式、工程方法 | **未复制其源代码** |
| OpenCode | 设计思路、协作 agent 分工、工程方法 | **未复制其源代码** |

参考**仅限设计、交互与工程方法**层面（例如「先规划再执行」「按 slot 分工」「让每一步
都可复核」这类做法），**不复制其代码**。本项目没有复制粘贴上述项目的任何源文件、
片段或提示词模板到提交包中；两者的命名、目录结构、命令与输出格式均为本项目独立设计。

若后续有证据表明提交包中混入了上述项目的代码，本声明即视为失效，团队将立即删除相关
内容并重新核算权属。

---

## 四、团队权属声明

1. 本项目提交包中的**全部自研代码、文档、配置与测试**，由参赛团队主导创作，
   著作权归 **AI PR Review Assistant Contributors** 共同所有，按 MIT 许可对外发布。
2. 提交包中**不含**任何来自商业软件的破解、反编译或受限资源，**不含**任何未授权的
   第三方素材。
3. 提交包中**不含**团队成员的邮箱、手机号、身份证件号等个人敏感信息；Git 提交元数据
   保留原始作者名，不做改写或伪造。
4. 项目名称、仓库描述与自有品牌资产归团队所有；第三方商标归各自所有者所有，
   声明见 [`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) §六 与根目录 `README.md` 的合规章节。
5. **外部贡献者**：截至 2026-09-28，本项目**没有来自团队外部的代码贡献者**。
   若未来引入外部贡献者，团队**必须**先补充**书面授权或贡献者协议（CLA）**，
    明确其贡献的许可条款与权利归属，并把该贡献纳入团队权属声明范围后再合并；
   在此之前，外部贡献不视为已获授权。
6. 本声明不因项目使用了 AI 工具而削弱

---

## 五、第三方权利归属

1. 本项目使用的全部第三方组件、字体与图标，**著作权与商标权均归各自上游作者 / 所有者**，
   本项目不主张其中任何权利。逐条清单、版本、许可证、上游链接与证据来源见
   [`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)。
2. 第三方组件仅以「依赖」与「随包捆绑」两种形式进入提交包，团队**没有修改**这些组件的
   源码；因此不存在对第三方代码主张改进权的基础。
3. 随包捆绑的第三方产物（如 `src/ai_pr_review/web_static/`、`src/ai_pr_review/tui_static/`
   下的构建输出）由对应工具链生成，**不是团队原创代码**，其权利归各自上游。
4. 第三方名称（GitHub、Python、OpenAI、Anthropic、Claude、DeepSeek、Qwen、GLM、MiMo、
   OpenCode、OpenTUI、GSAP 等）仅用于识别与说明，**不表示合作、赞助或背书**。
5. 若发现任何第三方权利主张，团队将第一时间停用相关素材并按上游许可证处理。

---

## 六、参赛作品的原创性口径

为避免歧义，明确本参赛作品**是**与**不是**什么：

**是**：

- 团队自主设计并实现的 AI PR 审查工作台，含可解释的审查计划、确定性规则、AST 分析、
  证据验证与历史复盘闭环；
- 团队自建的回归样例库与量化评测口径；
- 团队自述的真实能力边界（含明确的「不代表真实世界泛化准确率」声明）。

**不是**：

- 不是任何参考项目的复制品、fork 或二次分发；
- 不是「一次大模型调用」的包装 —— 审查是一个可复核的多步工作流；
- 不把内置 benchmark 的精选样例集成绩当作真实世界准确率宣传；
- 不主张任何第三方商标的所有权或授权关系。

---

## 七、AI 生成内容说明

如实登记提交包中由生成式工具产出的内容及其用途：

| 文件 / 素材 | 类型 | 用途 | 是否被核心逻辑依赖 |
|---|---|---|---|
| `docs/assets/p2/project-architecture.png` | **AI 生成的架构配图** | 文档与演示中展示系统结构 | **否** |
| `docs/assets/p2/review-pipeline.png` | **AI 生成的流水线配图** | 文档与演示中展示审查流水线 | **否** |
| `docs/assets/p2/review-flow-precise.png` | **AI 生成的流程配图** | 文档中展示精确流程 | **否** |
| `docs/assets/p2/competition-cover.png` | **AI 生成的封面海报** | 应用方案 PDF 封面 | **否** |
| `docs/assets/p2/trust-three-questions.png` | **AI 生成的说明配图** | 应用方案 PDF「信任三问」章节 | **否** |
| `docs/assets/p2/evidence-four-state.png` | **AI 生成的说明配图** | 应用方案 PDF「证据四态校验」章节 | **否** |
| `docs/assets/p2/finding-validation-chain.png` | **AI 生成的说明配图** | 应用方案 PDF「Finding 验证链」章节 | **否** |
| `docs/assets/p2/routing-cost-ledger.png` | **AI 生成的说明配图** | 应用方案 PDF「混合路由与成本账本」章节 | **否** |
| `docs/assets/p2/three-entrances-matrix.png` | **AI 生成的说明配图** | 应用方案 PDF「三入口与审查内核」章节 | **否** |
| `docs/assets/p2/business-model.png` | **AI 生成的说明配图** | 应用方案 PDF「商业模式分层」章节（图内已标注企业能力属于商业规划、不代表已实现） | **否** |
| `docs/assets/p2/roadmap.png` | **AI 生成的说明配图** | 应用方案 PDF「发展路线」章节 | **否** |
| `docs/assets/p2/context-fallback-three-levels.png` | **AI 生成的说明配图** | 三级上下文降级（tree-sitter → regex → diff-only）说明，文档/演示备用 | **否** |
| `docs/assets/p2/video-cover.png` | **AI 生成的封面图** | 演示视频封面 | **否** |
| `docs/screenshots/` 下的实机截图 | 项目实机截图 | README 与文档的功能展示 | 否（仅展示） |

说明：

- 上述配图是**用于展示的生成式配图**，它们是示意图，**核心代码与逻辑不依赖这些图片** ——
  删除它们不会影响 `pr-review` 的任何功能、测试或输出；图片与实际实现如有出入，
  **以代码与 `docs/API.md` 为准**。
- 截图是**项目实机截图**，反映真实运行界面。
- 部分文档段落由 AI 工具起草，经团队逐段审阅、修改与事实核对后定稿；
  文档中出现的实测数字以团队复跑命令为准。

---

## 八、参赛免责条款确认栏

> 以下为**团队自检确认表**，不是与主办方签署的法律文件。逐项打勾并随提交包留存即可。

| # | 确认项 | 状态 | 备注 |
|---|---|---|---|
| 1 | 本作品为参赛团队自主创作，未整包复制任何第三方项目 | ✅ 已确认 | 参考范围见 §3.3 |
| 2 | 提交包中不含他人未授权的源代码、素材或文档 | ✅ 已确认 | 第三方依赖按各自许可证合法使用 |
| 3 | 全部第三方组件已在许可总表中登记，并保留各自许可证 | ✅ 已确认 | [`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) |
| 4 | 第三方商标仅作识别用途，未主张所有权，未暗示合作 / 赞助 / 背书 | ✅ 已确认 | 同上 §六 |
| 5 | 本项目自研代码以 MIT 许可发布，权属归团队 | ✅ 已确认 | 见 §二、§四 |
| 6 | 无外部未授权贡献者；引入前将补书面授权或 CLA | ✅ 已确认 | 见 §四 第 5 条 |
| 7 | 提交包不含 API Key、GitHub Token 或任何本地凭据 | ✅ 已确认 | 见 §九；由 `scripts/check_submission_hygiene.py` 校验 |
| 8 | 已放弃 AI 工具的作者 / 版权主体身份 | ✅ 已确认 | 见 §3.2 |
| 9 | 文档中的能力主张与实测一致，未夸大 benchmark 成绩 | ✅ 已确认 | 见 §一、§六 |
| 10 | 团队成员信息未包含邮箱等个人敏感信息 | ✅ 已确认 | 见 §四 |
> 若任一项在提交前发生变化（例如引入外部贡献者、新增捆绑依赖、调整分发形态），
> 必须重新走一遍本表并更新日期。

---

## 九、提交前密钥清理清单

**任何**曾以明文形式出现在提交包、提交历史、聊天记录、日志、截图或演示视频中的
Key / Token，**必须在提交前轮换（rotate）**，而不是仅仅从文件里删掉。
仅删除而未轮换，等同于凭据已泄露。

### 9.1 提交包**不得**包含的路径

| 路径 | 性质 | 现状 |
|---|---|---|
| `.ai_pr_review/config.local.json` | 本地配置，含真实 GitHub Token / API Key | 已在 `.gitignore`，且由守卫校验未被 Git 跟踪 |
| `.ai_pr_review/config.json` | 本地配置 | 已在 `.gitignore` |
| `.ai_pr_review/config.web.json` | 本地 Web 配置 | 已在 `.gitignore`（`*.web.json`） |
| 任何其他 `*.web.json` | 本地 Web 配置 | 已在 `.gitignore` |
| `.env` / `secrets.env` | 环境变量与密钥文件 | 已在 `.gitignore` |
| `FIX_GITHUB_TOKEN.txt` | 一次性手工落盘的 Token | 已在 `.gitignore` |
| `_p5_verify/` | 本地 P5 安装环境与帧捕获 | 已在 `.gitignore` |
| 任何本地 web 配置 / 私有配置 | 本地私有配置 | 已在 `.gitignore` |

> 仓库里提交的 `.ai_pr_review/config.local.json.example` 是**只含占位符的模板**，
> 不含真实凭据，是**应当保留**的。

### 9.2 提交前逐项打勾

- [ ] 提交包中不存在上表任何路径
- [ ] `git ls-files` 不输出上表任何路径
- [ ] `.gitignore` 覆盖 `.ai_pr_review/config.local.json`、`.ai_pr_review/config.json`、
      `*.web.json`、`.env`、`secrets.env`、`_p5_verify/`
- [ ] **曾在聊天、日志、终端回显、截图、录屏或文档中粘贴过的 GitHub Token /
      API Key / 模型 Key 全部已轮换**（GitHub 在 Settings → Developer settings 里
      撤销旧 Token 并新建；模型侧在各自控制台作废旧 Key）
- [ ] 提交包内所有 `dist/` `build/` 产物均**不含**上述敏感路径
- [ ] 演示视频、截图、录屏中不出现 API Key、Token、个人绝对路径
- [ ] 运行 `python scripts/check_submission_hygiene.py` 退出码为 0
- [ ] 运行 `python -m pytest tests/test_submission_hygiene.py -q` 通过

### 9.3 自动校验

```bash
python scripts/check_submission_hygiene.py
```

该守卫会：检查敏感路径是否被 Git 跟踪、检查 `.gitignore` 覆盖度、扫描已跟踪文本文件里的
疑似真实密钥（只输出 `文件:行号 [已掩码]`，不输出任何原值）、检查 `dist/` `build/` 产物
是否夹带敏感路径，并校验本文档与第三方许可总表是否齐备。**它不会读取
`.ai_pr_review/config.local.json` 的内容。** 命中即以退出码 1 失败。

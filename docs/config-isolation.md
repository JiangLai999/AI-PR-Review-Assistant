# Web 工作台 / CLI 配置隔离

## 1. 为什么

改造前 `pr-review serve` 与 CLI 读写**同一份**配置文件（默认
`%APPDATA%\ai-pr-review\config.json`）。在 Web 设置页换供应商、模型或界面语言，
会立刻改掉 `pr-review review / plan / doctor / chat` 的行为 —— 两个入口互相踩。

用户诉求："web 审查工作台的设置不应和 cli 审查工作台相互影响"。

## 2. 两份配置

| 入口 | 配置文件 | 谁写 |
| --- | --- | --- |
| CLI（`review` / `plan` / `chat` / `config` / `doctor`） | `config.json` | 配置助手、`config init/import` |
| Web 工作台（`serve` 的设置页） | `config.web.json` | 设置页 `POST /api/config` |

路径由 `config.resolve_web_config_path()` 派生：与 CLI 配置**同目录、加 `.web` 后缀**。
`--config X` 时 Web 用 `X.web.json`；`AI_PR_REVIEW_CONFIG` 同理。

## 3. 首次启动的派生（seed）

`pr-review serve` 第一次跑时（`config.web.json` 不存在）：

1. 读取 CLI **实际生效的合并结果**（用户级 + 项目级 `.ai_pr_review/config.json`
   与 `config.local.json`），而不是只复制用户级文件；
2. 把它写成 `config.web.json`，并打印一行提示（`Web workbench config created: …`）；
3. 之后两者各自演进：**再次启动绝不覆盖** Web 那份（否则 Web 里的改动会被冲掉）。

### 密钥的存储姿态

派生时按用户**原本的**存储方式处理，不擅自升级也不擅自泄露：

- CLI 配置文件里本来就写了明文密钥 → 一并派生；
- 密钥只来自环境变量（`AI_PR_REVIEW_API_KEY` 等）→ **不落盘**，并打印一句说明
  （而不是让 `save()` 发一条误导性的"忘了 `save_key=True`"警告）；
- 没有任何可读的 CLI 配置文件（全新机器）→ 不创建文件，Web 直接用默认值 + env 覆盖。

## 4. 数据不隔离（刻意）

设置隔离 ≠ 数据隔离：历史、报告、finding 反馈与追问记录**共用一份
`results.db`**，这样 Web 的历史页能看到 CLI 跑出来的 run，反之亦然。

实现上必须显式钉住路径：`AppConfig.pin_result_store_path()` 把 CLI 生效的库路径
写成 Web 配置里的显式 `result_store.db_path`。

> 为什么非钉不可：`AppConfig.load()` 对"不在默认位置的配置"会调用
> `_derived_result_store_default()`，把库改成配置文件**旁边**的另一个文件。
> 实测（2026-09-27）：CLI 用 `%LOCALAPPDATA%\ai-pr-review\results.db`，而 Web 配置
> 在 `%APPDATA%\ai-pr-review\` 下会被改指到同目录的 `results.db` —— 历史页会突然
> "清空"，追问记录与报告也读不到既有 run。这是真机验收抓到的回归。

## 5. 踩过的坑：`resolve_save_path` 的优先级

`resolve_save_path()` 原本先看环境变量再看显式 `path` 参数，与
`resolve_config_path()` 文档里的"显式 > env > 默认"矛盾。派生 Web 配置时正好踩中：
env 有值时初值会被写回 CLI 配置。现已改为显式 `path` 优先，并由
`tests/test_config_precedence.py::test_explicit_save_path_beats_the_env_var` 锁住。

## 6. 真机验收（2026-09-27 实测）

```
Web workbench config created: C:\Users\21986\AppData\Roaming\ai-pr-review\config.web.json
web 生效的 config_path : ...\config.web.json
POST /api/config 落盘   : ...\config.web.json
CLI 配置 SHA256 是否变化: False
/api/history            : total_runs=20（CLI 跑出的 run 仍可见）
```

## 7. 还没做

- 设置页展示"当前配置文件路径 + 与 CLI 独立"的说明与「从 CLI 配置导入」按钮
  （派生只在首次发生，重装/搬迁后需要手动重来一次）；
- `pr-review serve --config X` 的错误提示里点名 `X.web.json`（目前只有首次创建时打印）。

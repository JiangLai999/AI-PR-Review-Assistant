# 第三方许可与商标声明 · Third-Party Notices

本文件汇总 **AI PR Review Assistant** 在源码仓库、随包前端产物与本地可执行文件中
使用的全部第三方组件、字体与商标。

- **本项目自有代码**以 MIT 许可证发布（见 [`LICENSE`](LICENSE)），版权所有者为
  **AI PR Review Assistant Contributors**；权属与原创性声明见
  [`docs/COMPLIANCE_AND_ORIGINALITY.md`](docs/COMPLIANCE_AND_ORIGINALITY.md)。
- **本文件列出的所有组件、字体、商标均非本项目自有**，其著作权、商标权与许可条款
  归各自上游作者 / 所有者所有。本项目不主张任何第三方权利。
- 本表不是法律意见；如果你要以其他方式再分发本项目，请以各上游许可证全文为准。

**版本口径**：下表「版本 / 范围」列写的是 `pyproject.toml`、`web/package.json`、
`frontend/tui/package.json` 里声明的范围；「实测版本」是 2026-09-28 在本仓库工作区
解析到的安装版本。声明范围与实测版本不一致时，**以实际随包分发的版本为准**。

**证据来源口径**：
- `pyproject.toml` / `package.json` —— 依赖声明来源；
- `dist-info 元数据` —— 已安装 Python 发行包的 `License` / `Classifier` / `licenses/` 字段；
- `node_modules/<pkg>/package.json` —— 已安装 npm 包的 `license` 字段；
- 随包产物 —— `src/ai_pr_review/web_static/`、`src/ai_pr_review/tui_static/`；
- `字体 name 表` —— 直接读取 `.ttf` 的 OpenType `name` 表（`nameID 0` 版权行、
  `nameID 14` 许可证 URL），属本地可复现证据；
- `上游仓库` —— 上游项目自己的 `LICENSE` / `OFL.txt`；
- `随包 LICENSE 文件` —— 组件自带并已随产物提交的许可证文件。

---

## 一、Python 直接运行时依赖

这些是 `pip install ai-pr-review` 时的硬依赖，见 `pyproject.toml` 的 `dependencies`。

| 组件 | 版本 / 范围 | 实测版本 | 许可证 | 上游链接 | 证据来源 |
|---|---|---|---|---|---|
| PyGithub | `>=2.5` | 2.10.0 | LGPL-3.0-or-later | https://github.com/PyGithub/PyGithub | `pyproject.toml`；dist-info `Classifier: License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)`；上游 `LICENSE` |
| anthropic（Anthropic Python SDK） | `>=0.52.0` | 1.7.0 | MIT | https://github.com/anthropics/anthropic-sdk-python | `pyproject.toml`；dist-info `License: MIT` + `licenses/LICENSE` |
| pydantic | `>=2.0` | 2.13.5 | MIT | https://github.com/pydantic/pydantic | `pyproject.toml`；dist-info `licenses/LICENSE`；pydantic-core 2.46.5 同为 MIT |
| click | `>=8.0` | 8.5.0 | BSD-3-Clause | https://github.com/pallets/click | `pyproject.toml`；dist-info `licenses/LICENSE.txt`；上游 `LICENSE` |
| rich | `>=13.0` | 15.0.0 | MIT | https://github.com/Textualize/rich | `pyproject.toml`；dist-info `License: MIT` + `licenses/LICENSE` |
| prompt-toolkit | `>=3.0` | 3.0.53 | BSD-3-Clause | https://github.com/prompt-toolkit/python-prompt-toolkit | `pyproject.toml`；dist-info `Classifier: License :: OSI Approved :: BSD License` + `licenses/LICENSE` |

### 1.1 可选 AST 依赖（`pip install -e ".[ast]"`）

未安装时自动降级到正则提取，不影响运行。

| 组件 | 版本 / 范围 | 实测版本 | 许可证 | 上游链接 | 证据来源 |
|---|---|---|---|---|---|
| tree-sitter（Python 绑定 + C 运行时） | `>=0.23` | 0.26.0 | MIT | https://github.com/tree-sitter/tree-sitter | `pyproject.toml [project.optional-dependencies].ast`；dist-info `Classifier: MIT` + `licenses/LICENSE` |
| tree-sitter-python | `>=0.23` | 0.25.0 | MIT | https://github.com/tree-sitter/tree-sitter-python | 同上；dist-info `License: MIT` |
| tree-sitter-javascript | `>=0.23` | 本机未安装 | MIT | https://github.com/tree-sitter/tree-sitter-javascript | `pyproject.toml`；上游 `LICENSE` |
| tree-sitter-typescript | `>=0.23` | 本机未安装 | MIT | https://github.com/tree-sitter/tree-sitter-typescript | `pyproject.toml`；上游 `LICENSE` |

### 1.2 被源码导入但未在 `pyproject.toml` 声明的第三方包

如实登记，不做粉饰：**`requests`**（Apache-2.0，https://github.com/psf/requests ）
只在 `src/ai_pr_review/benchmark/cases.py` 的样例抓取路径里被导入，且该模块不在
主安装路径上。`pyproject.toml` 目前没有声明它 —— 属于**待修的依赖声明缺口**
（见文末「已知未处理事项」），本项目不因此获得对该组件的分发授权声明之外的任何权利。

---

## 二、前端 / TUI 依赖

### 2.1 Web 工作台（`web/package.json`，React + Vite）

| 组件 | 版本 / 范围 | 实测版本 | 许可证 | 上游链接 | 证据来源 |
|---|---|---|---|---|---|
| react | `^18.3.1` | 18.3.1 | MIT | https://github.com/facebook/react | `web/package.json`；`web/node_modules/react/package.json` `license: MIT` |
| react-dom | `^18.3.1` | 18.3.1 | MIT | https://github.com/facebook/react | 同上 |
| gsap | `^3.15.0` | 3.15.0 | **GreenSock Standard License**（非 OSI 开源许可） | https://github.com/greensock/GSAP | `web/node_modules/gsap/package.json` `license: "Standard 'no charge' license: https://gsap.com/standard-license."` |
| @gsap/react | `^2.1.2` | 2.1.2 | **GreenSock Standard License**（非 OSI 开源许可） | https://github.com/greensock/react | `web/node_modules/@gsap/react/package.json` `license: "SEE LICENSE AT https://gsap.com/standard-license"` |

> **GSAP 特别提示**：gsap 与 `@gsap/react` 走的是 GreenSock Standard License，
> **不是** MIT / BSD。它允许免费使用（含商业项目），但对「受保护的免付费工具」
> 等特定用途有额外限制，且**不属于 OSI 认证的开源许可证**。再分发本项目时，
> 必须原样带上 <https://gsap.com/standard-license> 的条款，并确保不落入该许可
> 禁止的场景。本项目不修改 gsap 源码。

### 2.2 OpenTUI 终端界面（`frontend/tui/package.json`，Solid + OpenTUI）

| 组件 | 版本 / 范围 | 实测版本 | 许可证 | 上游链接 | 证据来源 |
|---|---|---|---|---|---|
| @opentui/core | `0.1.101` | 0.1.101 | MIT | https://github.com/anomalyco/opentui | `frontend/tui/package.json`；`frontend/tui/node_modules/@opentui/core/package.json` `license: MIT` |
| @opentui/solid | `0.1.101` | 0.1.101 | MIT | https://github.com/anomalyco/opentui | 同上 |
| solid-js | `1.9.11` | 1.9.11 | MIT | https://github.com/solidjs/solid | `frontend/tui/node_modules/solid-js/package.json` `license: MIT` |
| web-tree-sitter（JS/WASM 绑定） | 传递依赖 | 0.25.10 | MIT | https://github.com/tree-sitter/tree-sitter | `frontend/tui/node_modules/web-tree-sitter/package.json` `license: MIT` |

---

## 三、随包捆绑的第三方组件

以下内容**已提交进仓库并随 Python 包分发**，因此再分发时必须随包携带对应许可证。

| 组件 | 版本 | 许可证 | 上游链接 | 证据来源 | 随包位置 |
|---|---|---|---|---|---|
| @opentui/core-win32-x64（OpenTUI 原生运行时） | 0.1.101 | MIT | https://github.com/anomalyco/opentui | `src/ai_pr_review/tui_static/node_modules/@opentui/core-win32-x64/package.json` `license: MIT` | `src/ai_pr_review/tui_static/node_modules/@opentui/core-win32-x64/`（含 `opentui.dll`） |
| 同上 · 许可证文件 | — | MIT | 同上 | **随包 LICENSE 文件** | `src/ai_pr_review/tui_static/node_modules/@opentui/core-win32-x64/LICENSE` |
| OpenTUI TUI 前端构建产物（Solid + OpenTUI 打包进 `tui.js`） | 随构建变化 | MIT（各组件见 §2.2） | https://github.com/anomalyco/opentui | `frontend/tui/` 源码 + Bun 构建 | `src/ai_pr_review/tui_static/tui.js` |
| tree-sitter 语法 wasm（javascript / markdown / markdown_inline / typescript / zig） | 随构建变化 | MIT | https://github.com/tree-sitter/tree-sitter | `src/ai_pr_review/tui_static/*.wasm`（由 tree-sitter 各语法仓库构建） | `src/ai_pr_review/tui_static/tree-sitter-*.wasm` |
| React / React-DOM / GSAP / @gsap/react 的打包产物 | 随构建变化 | MIT / MIT / GSL / GSL（见 §2.1） | 见 §2.1 | `web/` 源码 + Vite 构建 | `src/ai_pr_review/web_static/assets/index-*.js` |
| Web 工作台自研样式与图标 | 随构建变化 | MIT（本项目） | — | `web/src/styles/`、`web/public/assets/site-icon.svg` | `src/ai_pr_review/web_static/assets/` |

> 随包 TUI 二进制 `src/ai_pr_review/tui_static/pr-review-tui.exe`（约 90 MB）
> **不入库**（见 `.gitignore`），需由构建者在本机生成。

---

## 四、字体

Web 工作台的界面字体随包分发（`web/public/fonts/` → 构建进
`src/ai_pr_review/web_static/fonts/`）。下表逐一核对了上游许可证。

| 字体 | 用途 | 版本 / 范围 | 许可证 | 版权 / 上游 | 证据来源 |
|---|---|---|---|---|---|
| DM Sans | 界面无衬线正文 | 未锁版本（Google Fonts 发行） | SIL OFL-1.1 | Google Fonts · https://github.com/google/fonts/tree/main/ofl/dmsans | 上游 `OFL.txt`（OFL-1.1） |
| Fragment Mono | 等宽正文 | 未锁版本 | SIL OFL-1.1 | Fragment-Mono Project Authors · https://github.com/weiweihuanghuang/fragment-mono | 上游 `LICENSE` 声明 OFL-1.1；Google Fonts `ofl/fragmentmono` 收录 |
| Host Grotesk | 标题 / 展示字 | 未锁版本 | SIL OFL-1.1 | Host Grotesk Project Authors · https://github.com/Element-Type/HostGrotesk | 上游 `OFL.txt`（OFL-1.1）；Google Fonts `ofl/hostgrotesk` 收录 |
| JetBrains Mono | 等宽代码 | Version 2.211 | SIL OFL-1.1 | The JetBrains Mono Project Authors · https://github.com/JetBrains/JetBrainsMono | **字体 name 表**：`nameID 0` = `Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono)`；`nameID 14` = `https://scripts.sil.org/OFL` |
| Manrope | 界面无衬线 | Version 4.504 | SIL OFL-1.1 | The Manrope Project Authors · https://github.com/sharanda/manrope | **字体 name 表**：`nameID 0` = `Copyright 2019 The Manrope Project Authors (https://github.com/sharanda/manrope)`；`nameID 14` = `http://scripts.sil.org/OFL` |
| Montserrat | 界面无衬线 | 未锁版本 | SIL OFL-1.1 | Google Fonts · https://github.com/google/fonts/tree/main/ofl/montserrat | 上游 `OFL.txt`（OFL-1.1） |

> **版权年份说明**：JetBrains Mono（2020）与 Manrope（2019）的年份来自字体文件
> `name` 表的原文引用，不是推断值；其余字体的**版权年份在本仓库中没有可核验的
> 证据来源，因此不予填写**，只给出上游项目与许可证。OFL-1.1 要求保留版权与许可
> 声明，随包分发时应把各字体上游的 `OFL.txt` 一并附上。

> **OFL-1.1 要点**：可自由使用、嵌入、修改与再分发（含商业用途）；**不得单独出售字体本身**；
> 保留字体版权与许可声明；使用保留字体名称（Reserved Font Name）时，衍生版本不得沿用原名。

---

## 五、开发依赖（通常不随最终包分发）

`pyproject.toml` 的 `dev` extra、`web/package.json` 与 `frontend/tui/package.json`
的 `devDependencies`。**它们只用于本地开发与构建，通常不随最终 Python 包分发**
（`[tool.hatch.build.targets.wheel] packages = ["src/ai_pr_review"]` 只打包
`src/ai_pr_review`），但列出以保持可复现。

| 组件 | 版本 / 范围 | 许可证 | 上游链接 |
|---|---|---|---|
| hatchling（构建后端） | 未 pin | MIT | https://github.com/pypa/hatch |
| pytest | `>=8.0` | MIT | https://github.com/pytest-dev/pytest |
| pytest-asyncio | `>=0.24` | MIT | https://github.com/pytest-dev/pytest-asyncio |
| pytest-cov | `>=5.0` | MIT | https://github.com/pytest-dev/pytest-cov |
| black | `==24.10.0` | MIT | https://github.com/psf/black |
| isort | `==5.13.2` | MIT | https://github.com/PyCQA/isort |
| mypy | `>=1.10` | MIT | https://github.com/python/mypy |
| twine | `>=5.1` | Apache-2.0 | https://github.com/pypa/twine |
| build | `>=1.2` | MIT | https://github.com/pypa/build |
| typescript | `^5.7.2`（web）/ `^5.8.2`（tui） | Apache-2.0 | https://github.com/microsoft/TypeScript |
| vite | `^6.0.5` | MIT | https://github.com/vitejs/vite |
| @vitejs/plugin-react | `^4.3.4` | MIT | https://github.com/vitejs/vite-plugin-react |
| @types/node / @types/react / @types/react-dom / @types/bun | 见各 `package.json` | MIT | https://github.com/DefinitelyTyped |
| playwright | `^1.63.0` | Apache-2.0 | https://github.com/microsoft/playwright |
| Bun（构建 TUI 的运行时） | 未 pin | MIT | https://github.com/oven-sh/bun |

> 传递依赖（`loose-envify`、`scheduler`、`csstype`、`yoga-layout`、`zod`、`reselect`
> 等）数量随构建工具链漂移，其许可证与著作权归各自上游所有。本项目不修改这些组件。
> 完整清单可用 `npm ls --all --json` / `pip-licenses` 在本地复现。

---

## 六、商标声明

本项目在其文档、界面与代码注释中提及下列名称，**仅用于识别所依赖的产品、平台或工具，
以及说明兼容 / 集成关系**。

> **免责声明**
>
> 1. 这些名称、标志及相关标识的**商标权归各自所有者**所有；本项目不主张、也不持有
>    上述任何商标。
> 2. 上述名称的使用**不表示**与相应所有者存在任何形式的**合作、赞助、授权、代理或背书**。
> 3. 各所有者对自身商标的描述性使用（如指称兼容性）可能有自己的品牌使用规范，
>    本项目不承担因第三方商标而产生的任何责任。
> 4. 本项目的产品名称、代码与自有品牌资产归 AI PR Review Assistant Contributors。

涉及名称（至少）：

| 名称 | 所有者 | 在本项目中的用法 |
|---|---|---|
| GitHub / GitHub Octocat | GitHub, Inc. | 说明 PR 审查的数据来源与 API 集成 |
| Python | Python Software Foundation | 说明主语言与运行环境 |
| OpenAI 及 ChatGPT 名称 | OpenAI | 列出本项目支持的模型供应商 |
| Anthropic | Anthropic, PBC | 说明 SDK 依赖与可用的模型供应商 |
| Claude | Anthropic, PBC | 列出可用的模型供应商；并在开发记录中作为**评审工具**提及 |
| DeepSeek | DeepSeek | 列出可用的模型供应商 |
| Qwen | Alibaba Cloud | 列出可用的模型供应商 |
| GLM | 智谱 AI（Zhipu AI） | 列出可用的模型供应商 |
| MiMo | 小米 | 列出可用的模型供应商；在开发记录中作为**评审工具**提及 |
| OpenCode | OpenCode 项目贡献者 | 在开发记录中作为**协作工具 / 智能体身份**提及 |
| OpenTUI | OpenTUI 项目贡献者 | 前端 TUI 框架依赖 |
| GSAP / GreenSock | GreenSock（Webflow） | Web 工作台动画依赖（见 §2.1 许可提示） |
| SQLite | SQLite / SQLite.org（非商标主张） | 本地存储 |

> 商标声明同样适用于 `README.md`、`docs/`、`web/`、`frontend/`、`website/` 下的
> 全部文件与界面文案。

---

## 七、二进制 / 一体化分发注意事项

如果提交包以**单文件可执行**（如 PyInstaller / Nuitka）或**一体化包**的形式捆绑依赖，
以下义务成立：

1. **许可证全文随包**。凡是被捆绑（而非由 `pip` 单独安装）的组件，都必须把它的
   许可证**全文**随包提供 —— 至少覆盖 §1、§2、§3、§四 中列出的全部组件与字体。
   本文件是索引，不替代许可证全文。
2. **LGPL-3.0 组件（PyGithub）必须可替换**。
   - 以「未修改的库 + 动态链接 / 独立模块」方式捆绑时：必须允许使用者**替换该库**，
     并提供 PyGithub 对应版本的**完整源码获取方式**（上游仓库 tag + 补丁说明），
     同时保留本项目对 PyGithub 的使用声明；
   - 一体化单文件构建若产生了「PyGithub 的衍生物」，则该衍生物整体需按 LGPL-3.0
     提供，并允许使用者替换/重新链接为未修改的 PyGithub；
   - 源码获取方式应指向：<https://github.com/PyGithub/PyGithub>（对应发布 tag），
     并在随包说明中写明「本项目对 PyGithub 的改动：无 / 具体补丁见 …」。
     截至 2026-09-28，**本项目未修改 PyGithub 源码**。
3. **GSAP 不是开源许可**。捆绑 gsap / `@gsap/react` 的产物必须附带
   <https://gsap.com/standard-license> 条款，并确认使用场景不在其禁止范围；
   本项目不修改 gsap 源码。
4. **OFL-1.1 字体**：随包需附上游 `OFL.txt`；不得单独出售字体文件本身；
   字体文件名 / `font-family` 的使用不得误导来源。
5. **不得把第三方组件写成项目自有**：随包说明、演示与文档中必须明确区分
   「本项目代码（MIT）」与「捆绑的第三方组件（各自许可证）」。
6. **不声称拥有第三方商标**，参见 §六。

---

## 八、已知未处理事项

如实登记本文件**尚未解决**的合规缺口（不属于本文件交付范围，需后续任务跟进）：

| 事项 | 现状 | 影响 |
|---|---|---|
| 未在 `pyproject.toml` 声明的 `requests` | `src/ai_pr_review/benchmark/cases.py` 导入但未进 `dependencies` | 干净环境下 `benchmark cases` 相关路径可能 ImportError；再分发时 `requests`（Apache-2.0）的声明缺失 |
| 字体版本未锁定 | §四 中 4 个字体未 pin 版本 | 重新构建可能引入不同版本的字体，OFL 版权声明随之变化 |
| 字体 OFL 全文未随包 | 仓库内没有 `web/public/fonts/OFL-*` | 严格按 OFL-1.1「保留版权与许可声明」再分发时需要补齐 |
| 传递依赖未逐一登记 | §五 末尾已说明 | 无法给出完整、逐条的传递依赖许可清单 |
| 捆绑包未内置许可证目录 | `dist/*.whl`、`dist/*.tar.gz` 内没有统一的 `LICENSES/` 目录 | §七 第 1 条要求分发时需补齐 |

你是本项目的协作 agent（mimo）。**收尾任务**：让设置页在英文界面下**不再出现后端返回的中文**
（保存提示、凭证面板），并把对应的词条写进词典。后端由 opencode 并行加"结构化键"，契约已冻结。

## 后端即将返回的新字段（契约，按此写前端）
1. `POST /api/config` 的响应新增：
   ```json
   { "ok": true, "message": "已保存 1 项到 config.json。",
     "message_key": "config.save.saved", "message_params": {"count": 1, "path": "config.json"}, ... }
   ```
   key 取值（只有这些）：`config.save.saved`(params: count,path) · `config.save.noop` ·
   `config.save.unsupported_key`(keys) · `config.save.unsupported_provider`(provider) ·
   `config.save.invalid_value`(name) · `config.save.invalid_value_options`(name,options) ·
   `config.save.verify_failed`(fields)。**可能为空串/缺失 → 回落现有 `message` 原文**。
2. `GET /api/credentials` 的每个 item 新增：
   ```json
   { "key": "github", "label": "GitHub", "detail": "…", "fix_hint": "…",
     "label_key": "credentials.github", "detail_key": "credentials.github.ok",
     "fix_hint_key": "", "params": {"login": "octocat"} }
   ```
   key 取值：`credentials.github` / `credentials.provider`（label）；
   `credentials.github.{missing,ok,invalid,forbidden,other}`、`credentials.provider.missing`（detail）；
   `credentials.github.{fix_token,fix_reissue,fix_retry,fix_network}`、`credentials.provider.fix_key`（fix_hint）。
   **空串/缺失 → 回落原文**。

## 要做的事（write_scope 内）
1. `web/src/api/types.ts`：给 `SaveConfigResponse` 加 `message_key?: string; message_params?: Record<string, string|number>`；
   给 `CredentialItem` 加 `label_key?/detail_key?/fix_hint_key?: string; params?: Record<string, string|number>`。
2. `web/src/pages/SettingsPage.tsx`：
   - 顶部保存提示：`message_key && hasKey(message_key) ? t(message_key, message_params) : result.message`
     （失败分支同理：`ok:false` 时优先用 `message_key`）；
   - 凭证面板：`label/detail/fix_hint` 三处都按上面的回落规则渲染；
   - **注意**：`title` 提示（鼠标悬停）也要用同一份本地化文案，不要只改可见文本。
3. `web/src/i18n/settings.ts`：补这两组词条（zh + en 两份都要），文案自己写得好一点：
   - `config.save.*`（7 个 key，带 `{count}`/`{path}`/`{keys}`/`{provider}`/`{name}`/`{options}`/`{fields}` 插值）
   - `credentials.*`（label 2 + detail 6 + fix_hint 4 ≈ 12 个 key）
4. `docs/mimo-settings-backend-i18n.md`：回落规则、key 清单、改动点、验证、未决项。

## 约束
- 只写：`web/src/pages/SettingsPage.tsx`、`web/src/api/types.ts`、`web/src/i18n/settings.ts`、`docs/mimo-settings-backend-i18n.md`；
- 需要 `hasKey()` 之类的判定：**用 `web/src/i18n/index.ts` 里已有的 `dictKeys()`**（`dictKeys().includes(key)`），
  **不要改 `i18n/index.ts`**（主控文件）；禁止改 `src/ai_pr_review/**`；禁止 git；禁止 `npm run build`。

## 验证（必须真跑，报数字）
```bash
cd web && npm run typecheck
```
并用你既有那套离线自证（Playwright + `page.route` 打桩，脚本放 `.pytest_mimo/mimo/`）：
1. 后端只回中文 `message`（无 key）→ 页面显示中文（回落路径）；
2. 后端回 `message_key=config.save.saved` + params → 页面显示**英文**（把语言切成 en-US）；
3. 凭证面板三条文案（label/detail/fix_hint）在有 key 时全部本地化，其中 `{login}` 插值正确；
4. key 缺失时回落原文，不出现空白。

完成后按总线报告：
`python scripts/agent_bridge.py report p4-frontend-i18n --agent mimo --status completed --summary "<一句话>" --evidence "<文件:行号 + typecheck 结果 + 四条自证结论>" --blocker "<未决项，没有写无>"`


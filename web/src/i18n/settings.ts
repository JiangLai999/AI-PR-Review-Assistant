/**
 * 命名空间：设置页 / 接口文档页（由 opencode 填充）。
 *
 * key 命名：
 * - `settings.<区域>.<名称>` —— SettingsPage.tsx
 * - `api.<区域>.<名称>` —— ApiPage.tsx（`api.error.*` 三个接口层错误文案在 shell.ts，勿重复定义）
 * - 控件常量只存 key，渲染时用 `t(key)` 取词，语言切换即时生效。
 * - 插值写法 `{name}`，调用 `t('key', { name })`。
 *
 * 术语：provider=供应商；credential=凭证；token=令牌；cost cap=成本上限。
 */
import type { Namespace } from './shell'

export const settings: Namespace = {
  'zh-CN': {
    // ── 设置页 · 页面骨架 ─────────────────────────────────────────────
    'settings.hero.title': '设置',
    'settings.hero.lead':
      '在这里配置模型供应商、凭证与界面偏好。所有内容只写入本机配置文件，不会上传到任何地方。密钥字段留空表示',
    'settings.hero.leadStrong': '保持原值不变',
    'settings.hero.leadTail': '。',

    // 阶段徽标 / 通用提示
    'settings.stage.provider': 'CLI 助手 2–4/6',
    'settings.stage.webOnly': 'Web 独有 · CLI 助手无此阶段',
    'settings.stage.preferences': 'CLI 助手 5/6',
    'settings.stage.save': 'CLI 助手 6/6',
    'settings.unsupported': '当前后端不支持这一项',

    // ── 设置页 · 数值项（6 个） ──────────────────────────────────────
    'settings.numeric.maxTokens.label': '单次最大输出 tokens',
    'settings.numeric.maxTokens.hint': '影响单次模型回复长度',
    'settings.numeric.timeout.label': '请求超时（秒）',
    'settings.numeric.timeout.hint': '模型响应慢就调大',
    'settings.numeric.concurrency.label': '并发审查文件数',
    'settings.numeric.concurrency.hint': '越大越快，但更容易触发限流',
    'settings.numeric.crossFile.label': '跨文件分析文件数上限',
    'settings.numeric.crossFile.hint': '参与接口影响对比的文件数量',
    'settings.numeric.costRun.label': '单次运行成本上限（$）',
    'settings.numeric.costRun.hint': '超过则中止本次审查',
    'settings.numeric.cost24h.label': '24 小时成本上限（$）',
    'settings.numeric.cost24h.hint': '滑动窗口总量',

    // ── 设置页 · 布尔项（2 个） ──────────────────────────────────────
    'settings.bool.staticAst.label': '启用静态与 AST 规则',
    'settings.bool.staticAst.hint': '规则命中不消耗模型调用',
    'settings.bool.crossFile.label': '启用跨文件 AI 审查',
    'settings.bool.crossFile.hint': '会额外消耗一次模型调用；关闭时仅做确定性的接口影响分析',

    // ── 设置页 · 6 个偏好项（label / hint） ──────────────────────────
    'settings.pref.uiLanguage.label': '界面语言',
    'settings.pref.uiLanguage.hint': '与 CLI 助手共用 preferences.ui_language',
    'settings.pref.outputFormat.label': '默认输出格式',
    'settings.pref.outputFormat.hint': 'CLI 导出的默认格式；报告导出按钮仍可单独选',
    'settings.pref.chatLayout.label': '对话布局',
    'settings.pref.chatLayout.hint': 'CLI 聊天界面的排版方式',
    'settings.pref.workbenchMode.label': '审查工作台显示',
    'settings.pref.workbenchMode.hint': 'auto = 有审查结果时才展开面板',
    'settings.pref.repoContext.label': '仓库上下文',
    'settings.pref.repoContext.hint': '审查时预取哪些仓库文件（测试文件 / 依赖）',
    'settings.pref.reviewEffort.label': '审查思考档位',
    'settings.pref.reviewEffort.hint': '档位越高越准，成本与耗时也越高',
    'settings.pref.staleOption': '{value}（当前值不在可选项内）',
    'settings.pref.unsupportedHint':
      '{unsupported}：后端未返回 options.{options}，已禁用且保存时不提交这个键。',
    'settings.pref.unsupportedNotice':
      '当前后端不支持这一项：后端没有返回 options / preferences（旧后端），本组控件已禁用，保存时也不会提交这些键。',

    // ── 设置页 · 两个偏好分组 ────────────────────────────────────────
    'settings.group.interface.title': '界面与输出',
    'settings.group.interface.desc':
      '与 CLI 助手第 5 阶段同一份 preferences：Web 改完，CLI 助手下次打开就是新值。',
    'settings.group.review.title': '审查偏好',
    'settings.group.review.desc':
      'CLI 助手里这两项也在第 5 阶段（紧跟在审查工作台之后），Web 拆成一组便于查找。',

    // ── 设置页 · 读写提示 ────────────────────────────────────────────
    'settings.message.loadFailed': '读取配置失败：{detail}',
    'settings.message.probeFailed': '探测失败：{detail}',
    'settings.message.saveRejected': '保存失败：服务端拒绝了这次改动。',
    'settings.error.saveHttp': '保存失败（HTTP {status}）',

    // ── 设置页 · 凭证健康面板 ────────────────────────────────────────
    'settings.credentials.title': '凭证健康',
    'settings.credentials.desc':
      '点「重新探测」会真实请求 GitHub 与模型端点，用来区分「没填」和「填错」。',
    'settings.credentials.probe': '重新探测',
    'settings.credentials.empty': '还没有探测结果。点击右上角「重新探测」开始检查。',
    'settings.credentials.fixHint': '修复建议：{hint}',
    'settings.credential.status.ok': '正常',
    'settings.credential.status.bad': '异常',
    'settings.credential.status.none': '未配置',

    // ── 后端结构化键 · POST /api/config 的 message_key ───────────────
    'config.save.saved': '已保存 {count} 项到 {path}。',
    'config.save.noop': '没有需要保存的改动。',
    'config.save.unsupported_key': '以下配置项当前后端不支持，已跳过：{keys}。',
    'config.save.unsupported_provider': '不支持的供应商「{provider}」，请换一个预设或改用 custom。',
    'config.save.invalid_value': '「{name}」的取值不合法，已拒绝写入。',
    'config.save.invalid_value_options': '「{name}」的取值不合法，可选：{options}。',
    'config.save.verify_failed': '保存前校验未通过，问题字段：{fields}。',

    // ── 后端结构化键 · GET /api/credentials 的 label/detail/fix_hint ─
    'credentials.github': 'GitHub',
    'credentials.provider': '模型服务',
    'credentials.github.missing': '尚未配置 GitHub Token。',
    'credentials.github.unprobed': '已配置（尚未探测连通性）。',
    'credentials.github.ok': '凭证可用，当前登录为 {login}。',
    'credentials.github.invalid': 'GitHub Token 无效或已过期。',
    'credentials.github.forbidden': 'GitHub Token 权限不足，无法读取该仓库。',
    'credentials.github.other': 'GitHub 凭证检查未通过（HTTP {status}）。',
    'credentials.provider.missing': '尚未配置模型 API Key。',
    'credentials.provider.unprobed': '已配置（尚未探测连通性）。',
    'credentials.provider.unprobed_model': '已配置（尚未探测连通性），模型 {model}。',
    'credentials.provider.ok': '模型端点连接正常。',
    'credentials.provider.ok_named': '已连接 {endpoint}。',
    'credentials.provider.ok_models': '模型端点连接正常，可用模型 {count} 个。',
    'credentials.provider.ok_named_models': '已连接 {endpoint}，可用模型 {count} 个。',
    'credentials.provider.model_missing':
      '密钥有效，但端点不提供模型 `{model}`。该端点可用模型：{models}',
    'credentials.provider.invalid': '密钥被端点拒绝（401 Invalid API Key）。',
    'credentials.provider.invalid_mismatch':
      '密钥被端点拒绝（401 Invalid API Key），且疑似与端点不属于同一家供应商。',
    'credentials.provider.not_found': '端点不存在（404）：{url}',
    'credentials.provider.unreachable': '无法连接端点：{reason}',
    'credentials.provider.error': '端点返回 HTTP {status}。',
    'credentials.github.fix_token': '到设置页填入有效的 GitHub Token（需要 repo 权限）。',
    'credentials.github.fix_reissue': '重新签发一个 GitHub Token，再到设置页更新。',
    'credentials.github.fix_retry': '稍后点「重新探测」再试一次。',
    'credentials.github.fix_network': '检查网络或代理设置后重新探测。',
    'credentials.provider.fix_key': '到设置页填入模型 API Key。',
    'credentials.provider.fix_model': '到设置页把模型名改成该端点实际提供的名称。',
    'credentials.provider.fix_mismatch':
      '核对 base_url 与 API Key 是否来自同一供应商（例如 DeepSeek 的密钥配 https://api.deepseek.com/v1）。',
    'credentials.provider.fix_endpoint':
      '检查 base_url 是否为 OpenAI 兼容端点（通常以 /v1 结尾）。',
    'credentials.provider.fix_network': '确认 base_url 可达，且本机网络允许访问。',

    // ── 设置页 · 模型服务与凭证 ──────────────────────────────────────
    'settings.provider.title': '模型服务与凭证',
    'settings.provider.desc': '运行模式（CLI 助手 1/6）在这里只读展示，槽位路由请用 CLI 助手修改。',
    'settings.provider.connection': '连接方式',
    'settings.provider.runtime': '运行模式 · {profile}',
    'settings.provider.presetLabel': '供应商预设',
    'settings.provider.customOption': 'custom（自定义端点）',
    'settings.provider.presetOption': '{display}（{name}）',
    'settings.provider.presetHint': '该预设默认端点：{url}',
    'settings.provider.baseUrlLabel': 'Base URL（OpenAI 兼容端点，通常以 /v1 结尾）',
    'settings.provider.modelLabel': '模型名',
    'settings.provider.formatLabel': 'API 格式',
    'settings.provider.apiKeyLabel': '模型 API Key',
    'settings.provider.configuredNote': ' — 当前已配置（{masked}），留空则不改动',
    'settings.provider.apiKeyKeep': '留空表示保持现有密钥',
    'settings.provider.tokenKeep': '留空表示保持现有 Token',
    'settings.provider.tokenHint': '只需 repo 权限；用于读取 PR 元数据与 diff。',

    // ── 设置页 · 成本与并发 ──────────────────────────────────────────
    'settings.cost.title': '成本与并发',
    'settings.cost.desc': 'CLI 配置助手没有这 8 项，它们只在 Web 设置页可改（后端白名单已支持）。',
    'settings.cost.range': '（允许范围 {min} ~ {max}）',

    // ── 设置页 · 保存 ────────────────────────────────────────────────
    'settings.save.title': '保存',
    'settings.save.desc': '对应 CLI 助手的第 6 阶段「确认保存」。',
    'settings.save.body':
      '保存会把密钥以明文写入上方的配置文件（这是本机工具，不做额外加密）。「校验后保存」会先真实请求一次 GitHub 与模型端点，任一不通就拒绝写入，避免把错误配置落盘。界面偏好与上面其余改动会一并提交。',
    'settings.save.validate': '校验后保存',
    'settings.save.direct': '直接保存',
    'settings.save.discard': '放弃改动',

    // ── 接口页 · 分组与骨架 ──────────────────────────────────────────
    'api.hero.title': '接口与命令',
    'api.hero.lead':
      '工作台是 Python 标准库服务端 + 本地 HTTP 接口之上的前端。共 18 条 API 与静态资源路由；所有能力都可以脱离界面，直接用命令行或 HTTP 调用。完整契约见 ',
    'api.hero.leadTail': '。',
    'api.group.review': '审查',
    'api.group.report': '报告与历史',
    'api.group.config': '配置与凭证',
    'api.group.demo': '演示',
    'api.group.publish': '发布',

    // ── 接口页 · 字段标签 ────────────────────────────────────────────
    'api.field.input': '入参',
    'api.field.body': '请求体',
    'api.field.response': '响应',
    'api.field.errors': '错误码',

    // ── 接口页 · 入参说明 ────────────────────────────────────────────
    'api.input.pathParamId': '路径参数 id = job_id',
    'api.input.queryRunId': 'query: run_id',
    'api.input.queryExport': 'query: run_id, format=markdown|json',
    'api.input.queryLimit': 'query: limit（可选）',
    'api.input.queryStrategy': 'query: strategy=static|ast|combined|all',
    'api.input.queryProbe': 'query: probe=0|1',
    'api.input.queryCase': 'query: case',

    // ── 接口页 · 端点说明 ────────────────────────────────────────────
    'api.endpoint.plan.desc': '抓取 PR、过滤文件并生成审查计划，不调用模型。',
    'api.endpoint.plan.errors': '400 pr_url 缺失 · 415 跨站或非 JSON',
    'api.endpoint.review.desc': '同步执行完整审查；async_job:true 时改走任务化，立即返回 job_id。',
    'api.endpoint.review.errors': '400 pr_url 缺失 · 415 跨站或非 JSON',
    'api.endpoint.review.response':
      '同步：{ pr, filter, plan, validation, review, interface_impacts, run }\n异步：202 { job_id, status, total_files, ... }',
    'api.endpoint.jobs.desc': '最近任务列表（固定 10 条）。',
    'api.endpoint.job.desc': '任务快照：状态、文件进度、错误与耗时。',
    'api.endpoint.job.errors': '404 任务不存在',
    'api.endpoint.jobEvents.desc': 'SSE 进度流（text/event-stream），逐文件推送进度事件。',
    'api.endpoint.jobEvents.errors': '404 任务不存在',
    'api.endpoint.jobCancel.desc': '服务端真取消，取消在文件边界生效。',
    'api.endpoint.jobCancel.errors': '404 任务不存在或已结束 · 415 跨站或非 JSON',
    'api.endpoint.jobCancel.response': '{ "ok": true, "job_id": "...", "message": "已请求停止。" }',
    'api.endpoint.feedback.desc': '记录人工对某条 finding 的判断并落库。',
    'api.endpoint.feedback.errors': '400 字段缺失 · 404 run/finding 不存在 · 415 跨站或非 JSON',
    'api.endpoint.report.desc': '单次 run 的完整报告：审查、计划、证据校验、接口影响与人工反馈。',
    'api.endpoint.report.errors': '400 run_id 缺失 · 404 run 不存在',
    'api.endpoint.reportExport.desc':
      '导出报告。markdown 走 text/markdown 并带附件名 pr<N>-<run8>.md；json 与 /api/report 同形。',
    'api.endpoint.reportExport.errors': '400 参数缺失或 format 非法 · 404 run 不存在',
    'api.endpoint.reportExport.response':
      'markdown：正文 + Content-Disposition: attachment; filename="pr<N>-<run8>.md"\njson：同 /api/report',
    'api.endpoint.history.desc': '历史 run 列表与聚合统计。limit 范围 1–200。',
    'api.endpoint.benchmark.desc': '基准准确率：precision / recall / F1 / 行号准确率，并附逐 case 明细。',
    'api.endpoint.config.desc': 'GET 读配置视图；POST 保存配置。掩码或留空 = 不改；未知键拒绝。',
    'api.endpoint.config.errors': '415 跨站或非 JSON · POST 未知键 → ok=false',
    'api.endpoint.config.response':
      'GET：{ provider, base_url, model, api_format, api_key(masked), available_providers }\nPOST：{ ok, changed, rejected? }',
    'api.endpoint.credentials.desc': '凭证健康检查。只返回掩码，绝不明文；probe=1 时做一次连通性探测。',
    'api.endpoint.meta.desc': '运行环境：规则数、供应商数、tree-sitter、跨文件开关、静态分析开关、模型。',
    'api.endpoint.health.desc': '存活探针，用于确认本地服务已就绪。',
    'api.endpoint.demoCases.desc': '离线演示用例清单。',
    'api.endpoint.demoRun.desc': '离线演示结果，无需 Token / API Key。',
    'api.endpoint.demoRun.errors': '404 case 不存在',
    'api.endpoint.publish.desc':
      '发布审查评论到 GitHub PR。confirm=false 只预览不碰 GitHub；confirm=true 才真正发布。',
    'api.endpoint.publish.errors':
      '400 run_id 缺失 · 404 run 不存在 · 409 无 GitHub PR 链接 · 415 跨站或非 JSON · 502 GitHub 侧失败 · 503 未配置 Token',
    'api.endpoint.publish.response':
      '预览：{ status: "preview", comment_chars, ... }\n发布：{ status: "published"|"already_published", comment_url, comment_id }',
    'api.endpoint.chat.desc':
      '对某次已完成的审查追问（无状态）。带 run_id 会注入该次审查的摘要与 findings；不带则按普通对话回答。',
    'api.endpoint.chat.errors':
      '400 text 缺失 · 404 run 不存在 · 415 跨站或非 JSON · 502 上游模型失败 · 503 未配置模型 API Key',
    'api.endpoint.chat.body': '{ "run_id": "<run_id，可选>", "text": "<问题>" }',
    'api.endpoint.chat.curl':
      'curl -X POST http://127.0.0.1:8787/api/chat \\\n  -H "Content-Type: application/json" \\\n  -d \'{"run_id":"<run_id>","text":"这次审查有几个 finding？"}\'',

    // ── 接口页 · 静态资源 ────────────────────────────────────────────
    'api.static.title': '静态资源',
    'api.static.body1': '前端构建产物挂在 ',
    'api.static.body2': '（',
    'api.static.body3': '），含 SPA fallback：未命中的非 ',
    'api.static.body4': ' 路径回退到入口页。',

    // ── 接口页 · 命令行等价能力 ──────────────────────────────────────
    'api.cli.title': '命令行等价能力',
    'api.cli.col.command': '命令',
    'api.cli.col.desc': '说明',
    'api.cli.run': '对指定 PR 执行完整审查',
    'api.cli.plan': '只生成审查计划，不调用模型',
    'api.cli.benchmark': '运行基准测试（--strategy all 可横向比较）',
    'api.cli.demo': '离线演示规划、静态规则与证据校验',
    'api.cli.feedback': '记录 finding 的人工反馈',
    'api.cli.history': '查看历史运行记录',
    'api.cli.stats': '查看聚合统计',
    'api.cli.serve': '启动本工作台',

    // ── 接口页 · 运行边界 ────────────────────────────────────────────
    'api.boundary.title': '运行边界',
    'api.boundary.local.title': '仅监听本机',
    'api.boundary.local.body': '服务绑定 127.0.0.1，不对局域网或公网开放。',
    'api.boundary.limit.title': '请求体上限 64 KB',
    'api.boundary.limit.body': '超过上限的请求在读取前即被拒绝并关闭连接。',
    'api.boundary.cors.title': '写端点同源守卫',
    'api.boundary.cors.body':
      '全部 POST 要求 Content-Type: application/json 且同源，否则 415；OPTIONS → 405，不返回任何 Access-Control-* 头。',
    'api.boundary.secrets.title': '凭据不外传',
    'api.boundary.secrets.body':
      'GitHub Token 与模型 API Key 只从本地配置读取，界面与接口都不会展示明文。',
    'api.boundary.cost.title': '费用由模型产生',
    'api.boundary.cost.body':
      '计划模式零成本；完整审查按你配置的供应商计费，受单次与 24 小时预算约束。',
  },
  'en-US': {
    // ── Settings · page shell ────────────────────────────────────────
    'settings.hero.title': 'Settings',
    'settings.hero.lead':
      'Configure the model provider, credentials and interface preferences here. Everything is written only to the local config file and never uploaded anywhere. Leaving a secret field blank ',
    'settings.hero.leadStrong': 'keeps the current value',
    'settings.hero.leadTail': '.',

    // Stage chips / shared hints
    'settings.stage.provider': 'CLI assistant 2–4/6',
    'settings.stage.webOnly': 'Web only · the CLI assistant has no such step',
    'settings.stage.preferences': 'CLI assistant 5/6',
    'settings.stage.save': 'CLI assistant 6/6',
    'settings.unsupported': 'The current backend does not support this item',

    // ── Settings · numeric fields ────────────────────────────────────
    'settings.numeric.maxTokens.label': 'Max output tokens per call',
    'settings.numeric.maxTokens.hint': 'Caps how long a single model reply can be',
    'settings.numeric.timeout.label': 'Request timeout (seconds)',
    'settings.numeric.timeout.hint': 'Raise it when the model responds slowly',
    'settings.numeric.concurrency.label': 'Concurrent review files',
    'settings.numeric.concurrency.hint': 'Higher is faster, but easier to hit rate limits',
    'settings.numeric.crossFile.label': 'Max files in cross-file analysis',
    'settings.numeric.crossFile.hint': 'How many files take part in the interface-impact comparison',
    'settings.numeric.costRun.label': 'Cost cap per run ($)',
    'settings.numeric.costRun.hint': 'Aborts this review once exceeded',
    'settings.numeric.cost24h.label': 'Cost cap per 24 hours ($)',
    'settings.numeric.cost24h.hint': 'Rolling-window total',

    // ── Settings · boolean fields ────────────────────────────────────
    'settings.bool.staticAst.label': 'Enable static and AST rules',
    'settings.bool.staticAst.hint': 'Rule hits cost no model calls',
    'settings.bool.crossFile.label': 'Enable cross-file AI review',
    'settings.bool.crossFile.hint':
      'Costs one extra model call; when off, only deterministic interface-impact analysis runs',

    // ── Settings · 6 preference fields ───────────────────────────────
    'settings.pref.uiLanguage.label': 'Interface language',
    'settings.pref.uiLanguage.hint': 'Shares preferences.ui_language with the CLI assistant',
    'settings.pref.outputFormat.label': 'Default output format',
    'settings.pref.outputFormat.hint':
      'Default format for CLI export; the report export button can still pick its own',
    'settings.pref.chatLayout.label': 'Chat layout',
    'settings.pref.chatLayout.hint': 'How the CLI chat screen is laid out',
    'settings.pref.workbenchMode.label': 'Review workbench display',
    'settings.pref.workbenchMode.hint': 'auto = expand the panel only when there are results',
    'settings.pref.repoContext.label': 'Repository context',
    'settings.pref.repoContext.hint': 'Which repository files are prefetched for review (tests / dependencies)',
    'settings.pref.reviewEffort.label': 'Review reasoning effort',
    'settings.pref.reviewEffort.hint': 'Higher levels are more accurate, but cost more and take longer',
    'settings.pref.staleOption': '{value} (not among the available options)',
    'settings.pref.unsupportedHint':
      '{unsupported}: the backend returned no options.{options}; the control is disabled and the key is not submitted on save.',
    'settings.pref.unsupportedNotice':
      'The current backend does not support this item: no options / preferences were returned (older backend). These controls are disabled and their keys are not submitted on save.',

    // ── Settings · preference groups ─────────────────────────────────
    'settings.group.interface.title': 'Interface & output',
    'settings.group.interface.desc':
      'The same preferences as step 5 of the CLI assistant: change them here and the CLI assistant picks up the new values next time it opens.',
    'settings.group.review.title': 'Review preferences',
    'settings.group.review.desc':
      'These two also sit in step 5 of the CLI assistant (right after the review workbench); the Web groups them separately so they are easy to find.',

    // ── Settings · load/save messages ────────────────────────────────
    'settings.message.loadFailed': 'Failed to load the config: {detail}',
    'settings.message.probeFailed': 'Probe failed: {detail}',
    'settings.message.saveRejected': 'Save failed: the server rejected this change.',
    'settings.error.saveHttp': 'Save failed (HTTP {status})',

    // ── Settings · credential panel ──────────────────────────────────
    'settings.credentials.title': 'Credential health',
    'settings.credentials.desc':
      'Clicking "Re-probe" really calls GitHub and the model endpoint, so you can tell "not set" from "set wrong".',
    'settings.credentials.probe': 'Re-probe',
    'settings.credentials.empty': 'No probe results yet. Click "Re-probe" in the top right to start.',
    'settings.credentials.fixHint': 'Fix suggestion: {hint}',
    'settings.credential.status.ok': 'OK',
    'settings.credential.status.bad': 'Failed',
    'settings.credential.status.none': 'Not configured',

    // ── Backend keys · POST /api/config message_key ──────────────────
    'config.save.saved': 'Saved {count} item(s) to {path}.',
    'config.save.noop': 'Nothing to save — no changes.',
    'config.save.unsupported_key': 'These settings are not supported by the current backend and were skipped: {keys}.',
    'config.save.unsupported_provider': 'Unsupported provider "{provider}". Pick another preset or use custom.',
    'config.save.invalid_value': 'Invalid value for "{name}"; nothing was written.',
    'config.save.invalid_value_options': 'Invalid value for "{name}". Allowed: {options}.',
    'config.save.verify_failed': 'Pre-save validation failed. Problem fields: {fields}.',

    // ── Backend keys · GET /api/credentials label/detail/fix_hint ────
    'credentials.github': 'GitHub',
    'credentials.provider': 'Model provider',
    'credentials.github.missing': 'GitHub token is not configured yet.',
    'credentials.github.unprobed': 'Configured (connectivity not probed yet).',
    'credentials.github.ok': 'Credential is working. Signed in as {login}.',
    'credentials.github.invalid': 'The GitHub token is invalid or has expired.',
    'credentials.github.forbidden': 'The GitHub token lacks permission to read this repository.',
    'credentials.github.other': 'GitHub credential check did not pass (HTTP {status}).',
    'credentials.provider.missing': 'The model API key is not configured yet.',
    'credentials.provider.unprobed': 'Configured (connectivity not probed yet).',
    'credentials.provider.unprobed_model': 'Configured (connectivity not probed yet), model {model}.',
    'credentials.provider.ok': 'The model endpoint is reachable.',
    'credentials.provider.ok_named': 'Connected to {endpoint}.',
    'credentials.provider.ok_models': 'The model endpoint is reachable · {count} model(s) available.',
    'credentials.provider.ok_named_models': 'Connected to {endpoint} · {count} model(s) available.',
    'credentials.provider.model_missing':
      'The key is valid, but the endpoint does not serve `{model}`. Available models: {models}',
    'credentials.provider.invalid': 'The endpoint rejected the key (401 Invalid API Key).',
    'credentials.provider.invalid_mismatch':
      'The endpoint rejected the key (401 Invalid API Key); the key looks like it belongs to a different provider.',
    'credentials.provider.not_found': 'Endpoint not found (404): {url}',
    'credentials.provider.unreachable': 'Cannot reach the endpoint: {reason}',
    'credentials.provider.error': 'The endpoint returned HTTP {status}.',
    'credentials.github.fix_token': 'Set a valid GitHub token in Settings (repo scope required).',
    'credentials.github.fix_reissue': 'Reissue a GitHub token, then update it in Settings.',
    'credentials.github.fix_retry': 'Click "Re-probe" again in a moment.',
    'credentials.github.fix_network': 'Check your network or proxy settings, then re-probe.',
    'credentials.provider.fix_key': 'Set the model API key in Settings.',
    'credentials.provider.fix_model':
      'Change the model name in Settings to one the endpoint actually serves.',
    'credentials.provider.fix_mismatch':
      'Check that base_url and the API key come from the same provider (e.g. a DeepSeek key with https://api.deepseek.com/v1).',
    'credentials.provider.fix_endpoint':
      'Check that base_url is an OpenAI-compatible endpoint (usually ending in /v1).',
    'credentials.provider.fix_network':
      'Make sure base_url is reachable and allowed by your local network.',

    // ── Settings · provider & credentials ────────────────────────────
    'settings.provider.title': 'Model provider & credentials',
    'settings.provider.desc':
      'Runtime profile (CLI assistant 1/6) is read-only here; use the CLI assistant to change slot routing.',
    'settings.provider.connection': 'Connection',
    'settings.provider.runtime': 'Runtime · {profile}',
    'settings.provider.presetLabel': 'Provider preset',
    'settings.provider.customOption': 'custom (custom endpoint)',
    'settings.provider.presetOption': '{display} ({name})',
    'settings.provider.presetHint': 'Default endpoint for this preset: {url}',
    'settings.provider.baseUrlLabel': 'Base URL (OpenAI-compatible endpoint, usually ending in /v1)',
    'settings.provider.modelLabel': 'Model name',
    'settings.provider.formatLabel': 'API format',
    'settings.provider.apiKeyLabel': 'Model API Key',
    'settings.provider.configuredNote': ' — configured ({masked}); leave blank to keep it',
    'settings.provider.apiKeyKeep': 'Leave blank to keep the current key',
    'settings.provider.tokenKeep': 'Leave blank to keep the current token',
    'settings.provider.tokenHint': 'repo scope only; used to read PR metadata and the diff.',

    // ── Settings · cost & concurrency ────────────────────────────────
    'settings.cost.title': 'Cost & concurrency',
    'settings.cost.desc':
      'The CLI config wizard has none of these 8 items; they are Web-only (the backend allowlist already supports them).',
    'settings.cost.range': '(allowed range {min} ~ {max})',

    // ── Settings · save ──────────────────────────────────────────────
    'settings.save.title': 'Save',
    'settings.save.desc': 'Corresponds to step 6 of the CLI assistant ("confirm & save").',
    'settings.save.body':
      'Saving writes your secrets in plain text to the config file above (this is a local tool, no extra encryption). "Validate & save" first calls GitHub and the model endpoint for real; if either is unreachable nothing is written, so a broken config never reaches disk. The interface preferences and the other changes above are submitted together.',
    'settings.save.validate': 'Validate & save',
    'settings.save.direct': 'Save now',
    'settings.save.discard': 'Discard changes',

    // ── API page · groups & shell ────────────────────────────────────
    'api.hero.title': 'APIs & commands',
    'api.hero.lead':
      'The workbench is a frontend on top of a Python standard-library server and local HTTP APIs. All 18 API and static-asset routes can be driven straight from the command line or HTTP, with no UI at all. Full contract: ',
    'api.hero.leadTail': '.',
    'api.group.review': 'Review',
    'api.group.report': 'Reports & history',
    'api.group.config': 'Config & credentials',
    'api.group.demo': 'Demo',
    'api.group.publish': 'Publish',

    // ── API page · field labels ──────────────────────────────────────
    'api.field.input': 'Input',
    'api.field.body': 'Request body',
    'api.field.response': 'Response',
    'api.field.errors': 'Errors',

    // ── API page · inputs ────────────────────────────────────────────
    'api.input.pathParamId': 'Path parameter id = job_id',
    'api.input.queryRunId': 'query: run_id',
    'api.input.queryExport': 'query: run_id, format=markdown|json',
    'api.input.queryLimit': 'query: limit (optional)',
    'api.input.queryStrategy': 'query: strategy=static|ast|combined|all',
    'api.input.queryProbe': 'query: probe=0|1',
    'api.input.queryCase': 'query: case',

    // ── API page · endpoint descriptions ─────────────────────────────
    'api.endpoint.plan.desc': 'Fetch the PR, filter the files and build a review plan — no model calls.',
    'api.endpoint.plan.errors': '400 missing pr_url · 415 cross-site or non-JSON',
    'api.endpoint.review.desc':
      'Run a full review synchronously; with async_job:true it becomes a job and returns job_id right away.',
    'api.endpoint.review.errors': '400 missing pr_url · 415 cross-site or non-JSON',
    'api.endpoint.review.response':
      'sync: { pr, filter, plan, validation, review, interface_impacts, run }\nasync: 202 { job_id, status, total_files, ... }',
    'api.endpoint.jobs.desc': 'Most recent jobs (fixed at 10).',
    'api.endpoint.job.desc': 'Job snapshot: status, file progress, errors and elapsed time.',
    'api.endpoint.job.errors': '404 job not found',
    'api.endpoint.jobEvents.desc': 'SSE progress stream (text/event-stream), one progress event per file.',
    'api.endpoint.jobEvents.errors': '404 job not found',
    'api.endpoint.jobCancel.desc': 'A real server-side cancel, taking effect at file boundaries.',
    'api.endpoint.jobCancel.errors': '404 job missing or already finished · 415 cross-site or non-JSON',
    'api.endpoint.jobCancel.response': '{ "ok": true, "job_id": "...", "message": "Stop requested." }',
    'api.endpoint.feedback.desc': 'Record a human verdict on a finding and persist it.',
    'api.endpoint.feedback.errors': '400 missing fields · 404 run/finding not found · 415 cross-site or non-JSON',
    'api.endpoint.report.desc':
      'Full report for one run: review, plan, evidence validation, interface impacts and human feedback.',
    'api.endpoint.report.errors': '400 missing run_id · 404 run not found',
    'api.endpoint.reportExport.desc':
      'Export the report. markdown is served as text/markdown with attachment filename pr<N>-<run8>.md; json has the same shape as /api/report.',
    'api.endpoint.reportExport.errors': '400 missing parameter or bad format · 404 run not found',
    'api.endpoint.reportExport.response':
      'markdown: body + Content-Disposition: attachment; filename="pr<N>-<run8>.md"\njson: same as /api/report',
    'api.endpoint.history.desc': 'Past runs plus aggregate statistics. limit ranges 1–200.',
    'api.endpoint.benchmark.desc':
      'Benchmark accuracy: precision / recall / F1 / line accuracy, with a per-case breakdown.',
    'api.endpoint.config.desc':
      'GET reads the config view; POST saves it. Masked or blank = leave unchanged; unknown keys are rejected.',
    'api.endpoint.config.errors': '415 cross-site or non-JSON · unknown key in POST → ok=false',
    'api.endpoint.config.response':
      'GET: { provider, base_url, model, api_format, api_key(masked), available_providers }\nPOST: { ok, changed, rejected? }',
    'api.endpoint.credentials.desc':
      'Credential health check. Only masked values are ever returned, never plain text; probe=1 runs one connectivity probe.',
    'api.endpoint.meta.desc':
      'Runtime environment: rule count, provider count, tree-sitter, cross-file switch, static-analysis switch, model.',
    'api.endpoint.health.desc': 'Liveness probe to confirm the local service is ready.',
    'api.endpoint.demoCases.desc': 'List of offline demo cases.',
    'api.endpoint.demoRun.desc': 'Offline demo result — no token or API key required.',
    'api.endpoint.demoRun.errors': '404 case not found',
    'api.endpoint.publish.desc':
      'Publish review comments to the GitHub PR. confirm=false only previews and never touches GitHub; confirm=true actually publishes.',
    'api.endpoint.publish.errors':
      '400 missing run_id · 404 run not found · 409 no GitHub PR link · 415 cross-site or non-JSON · 502 GitHub-side failure · 503 token not configured',
    'api.endpoint.publish.response':
      'preview: { status: "preview", comment_chars, ... }\npublished: { status: "published"|"already_published", comment_url, comment_id }',
    'api.endpoint.chat.desc':
      'Ask a follow-up about a completed review (stateless). With run_id the summary and findings of that run are injected; without it, it answers as a normal chat.',
    'api.endpoint.chat.errors':
      '400 missing text · 404 run not found · 415 cross-site or non-JSON · 502 upstream model failure · 503 model API key not configured',
    'api.endpoint.chat.body': '{ "run_id": "<run_id, optional>", "text": "<question>" }',
    'api.endpoint.chat.curl':
      'curl -X POST http://127.0.0.1:8787/api/chat \\\n  -H "Content-Type: application/json" \\\n  -d \'{"run_id":"<run_id>","text":"How many findings are there in this review?"}\'',

    // ── API page · static assets ─────────────────────────────────────
    'api.static.title': 'Static assets',
    'api.static.body1': 'The frontend build is served from ',
    'api.static.body2': '(',
    'api.static.body3': ') — including SPA fallback: unmatched non-',
    'api.static.body4': ' paths fall back to the entry page.',

    // ── API page · CLI equivalents ───────────────────────────────────
    'api.cli.title': 'CLI equivalents',
    'api.cli.col.command': 'Command',
    'api.cli.col.desc': 'Description',
    'api.cli.run': 'Run a full review on a given PR',
    'api.cli.plan': 'Generate a review plan only, no model calls',
    'api.cli.benchmark': 'Run the benchmark (--strategy all to compare them side by side)',
    'api.cli.demo': 'Offline demo of planning, static rules and evidence validation',
    'api.cli.feedback': 'Record human feedback for a finding',
    'api.cli.history': 'Show past runs',
    'api.cli.stats': 'Show aggregate statistics',
    'api.cli.serve': 'Start this workbench',

    // ── API page · runtime boundaries ────────────────────────────────
    'api.boundary.title': 'Runtime boundaries',
    'api.boundary.local.title': 'Listens on this machine only',
    'api.boundary.local.body': 'The service binds to 127.0.0.1 and is not exposed to the LAN or the public internet.',
    'api.boundary.limit.title': '64 KB request-body limit',
    'api.boundary.limit.body': 'Requests over the limit are rejected before the body is read, and the connection is closed.',
    'api.boundary.cors.title': 'Same-origin guard on write endpoints',
    'api.boundary.cors.body':
      'Every POST requires Content-Type: application/json and the same origin, otherwise 415; OPTIONS → 405, and no Access-Control-* headers are ever returned.',
    'api.boundary.secrets.title': 'Credentials never leave',
    'api.boundary.secrets.body':
      'The GitHub token and the model API key are read only from the local config; neither the UI nor the API ever shows them in plain text.',
    'api.boundary.cost.title': 'Model usage is what costs money',
    'api.boundary.cost.body':
      'Plan mode is free; a full review is billed by the provider you configured and is bounded by the per-run and 24-hour budgets.',
  },
}

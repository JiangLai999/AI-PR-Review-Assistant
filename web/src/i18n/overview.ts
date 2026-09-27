/**
 * 命名空间：概览页 / 准确率页 / 离线演示面板（由 claude 填充）。
 *
 * key 命名：`overview.<区域>.<名称>` / `benchmark.<区域>.<名称>`（小写点分）。
 * - 概览页里的「基准测试结果」预览块展示的就是 benchmark 报告的指标，
 *   因此直接复用 `benchmark.metric.*` / `benchmark.matrix.*`，避免同一术语两份文案。
 * - 复数走 `tn('key', count)`：词典里写 `key.one` / `key.other`。
 * - 插值写法 `{name}`，调用 `t('key', { name })`。
 */
import type { Namespace } from './shell'

export const overview: Namespace = {
  'zh-CN': {
    // 概览页 · 首屏
    'overview.hero.eyebrow': 'AI PR REVIEW AGENT · 本地工作台',
    'overview.hero.titleLine1': '把 GitHub PR 审查',
    'overview.hero.titleLine2': '做成可解释、可复盘的智能工作流',
    'overview.hero.lead':
      '不是一次性的模型调用，而是一条带规划、规则、证据校验与跨文件接口分析的审查流水线。所有结论都可追溯到具体的文件与变更行。',
    'overview.hero.ctaReview': '开始一次审查',
    'overview.hero.ctaBenchmark': '查看准确率',
    'overview.hero.consoleAria': '最近一次审查',
    'overview.hero.console.findings.one': '{count} 条 · {duration}',
    'overview.hero.console.findings.other': '{count} 条 · {duration}',
    'overview.hero.console.empty': '还没有审查记录',

    // 概览页 · 信任条
    'overview.trust.aria': '产品工作流承诺',
    'overview.trust.title': '不是黑盒结论，而是可验证的工程证据。',
    'overview.trust.p1.title': '先规划',
    'overview.trust.p1.body': '先生成风险与审查范围，再调用模型。',
    'overview.trust.p2.title': '有证据',
    'overview.trust.p2.body': '文件、行号、Diff 关联逐条校验。',
    'overview.trust.p3.title': '可复盘',
    'overview.trust.p3.body': '结果、成本、反馈全部保存在本机。',
    'overview.trust.p4.title': '可演示',
    'overview.trust.p4.body': '离线 Demo 与 Benchmark 随时可用。',

    // 概览页 · 流水线
    'overview.pipeline.title': '从 PR 链接到审查报告',
    'overview.pipeline.1.title': '获取 PR',
    'overview.pipeline.1.body': '解析 GitHub PR URL，抓取元数据、diff、文件列表与文件内容。',
    'overview.pipeline.2.title': '智能过滤',
    'overview.pipeline.2.body': '跳过纯删除、超大与不相关文件，支持 force include 白名单。',
    'overview.pipeline.3.title': '构建上下文',
    'overview.pipeline.3.body':
      'tree-sitter 语法树 → 正则提取 → diff 窗口，三级降级保证不崩。',
    'overview.pipeline.4.title': '生成计划',
    'overview.pipeline.4.body': '按 PR 意图与变更特征计算风险等级、优先文件与审查策略。',
    'overview.pipeline.5.title': '逐文件审查',
    'overview.pipeline.5.body':
      '并发调用模型输出结构化 findings，受单次与 24 小时预算双重约束。',
    'overview.pipeline.6.title': '规则与证据',
    'overview.pipeline.6.body': '合并确定性规则命中，再逐条校验证据是否对应真实变更行。',
    'overview.pipeline.7.title': '跨文件影响',
    'overview.pipeline.7.body': '对比 base 签名，定位会被破坏的外部调用方。',
    'overview.pipeline.8.title': '报告与落库',
    'overview.pipeline.8.body':
      '渲染 terminal / markdown / json / GitHub 评论，并写入 SQLite 支持复盘。',

    // 概览页 · 关键能力
    'overview.capabilities.title': '关键能力',
    'overview.capabilities.1.title': '智能审查规划',
    'overview.capabilities.1.body':
      '在调用模型之前先生成确定性的 ReviewPlan：风险等级、风险类别、优先文件、审查策略与是否需要跨文件分析。',
    'overview.capabilities.2.title': '规则 + AI 双路分析',
    'overview.capabilities.2.body':
      '15 条确定性规则（逐行安全规则 + Python AST 语法级规则）与模型结论合并去重，规则命中带来源标记。',
    'overview.capabilities.3.title': '证据链校验',
    'overview.capabilities.3.body':
      '每条结论都校验文件、行号、是否落在变更行、代码片段是否真实存在，标记 valid / needs_review / invalid。',
    'overview.capabilities.4.title': '跨文件接口影响',
    'overview.capabilities.4.body':
      '建立符号索引，与 PR base 版本对比签名（参数、返回类型、async、基类），并定位真实外部调用方。',
    'overview.capabilities.5.title': '语法级上下文',
    'overview.capabilities.5.body':
      'tree-sitter 解析 Python / JavaScript / TypeScript，提取 imports、函数签名、类与继承；未安装时自动降级到正则。',
    'overview.capabilities.6.title': '可量化的准确率',
    'overview.capabilities.6.body':
      '内置已知缺陷样例库，输出精确率、召回率、F1、误报率与行号准确率，用于防止策略退化。',

    // 概览页 · 当前状态
    'overview.snapshot.title': '当前状态',
    'overview.snapshot.error': '部分数据未能载入：{detail}',
    'overview.snapshot.runs': '历史审查',
    'overview.snapshot.runsHint': '累计 {count} 次运行',
    'overview.snapshot.prs': '覆盖 PR',
    'overview.snapshot.findings': '发现问题',
    'overview.snapshot.precision': '规则准确率',
    'overview.snapshot.precisionHint': '召回率 {recall}',
    'overview.snapshot.notLoaded': '未载入',
    'overview.snapshot.rules': '确定性规则',
    'overview.snapshot.rulesHint': '逐行规则 + AST 规则（去重）',
    'overview.snapshot.providers': '支持供应商',
    'overview.snapshot.providersHint': 'OpenAI 兼容 + Anthropic',

    // 概览页 · 准确率预览（复用 benchmark.metric.*）
    'overview.accuracy.title': '基准测试结果',
    'overview.accuracy.description':
      '精选已知缺陷样例集上的实测成绩，用于防止规则退化与误报增加。',
    'overview.accuracy.detail': '查看明细 →',
    'overview.accuracy.strategy': '{strategy} 策略',
    'overview.accuracy.cases.one': '{count} 个样例',
    'overview.accuracy.cases.other': '{count} 个样例',
    'overview.accuracy.note':
      '这是精选回归样例集的成绩，代表规则在该集合上的表现，不等同于真实 PR 上的泛化准确率。',

    // 概览页 · CLI / HTTP 对照
    'overview.cli.title': '同一个引擎，两种用法',
    'overview.cli.terminal': '命令行',
    'overview.cli.http': '本地 HTTP 接口',
    'overview.cli.endpoints':
      'POST /api/plan       生成审查计划\n' +
      'POST /api/review     执行完整审查\n' +
      'GET  /api/history    历史与统计\n' +
      'GET  /api/report     按 run_id 取报告\n' +
      'GET  /api/benchmark  准确率报告\n' +
      'POST /api/feedback   记录人工反馈',

    // 离线演示面板
    'overview.demo.aria': '离线演示',
    'overview.demo.title': '不用配置 Token，直接看完整审查链路',
    'overview.demo.body':
      '使用与 CLI 共用的 Demo 数据，展示 ReviewPlan、确定性规则和 Evidence 验证。适合现场演示，也适合快速理解系统的核心差异。',
    'overview.demo.run': '运行离线演示',
    'overview.demo.running': '运行中…',
    'overview.demo.emptyTitle': '选择案例并运行',
    'overview.demo.emptyBody': '结果会在这里展示',

    // 准确率页
    'benchmark.hero.title': '准确率基准',
    'benchmark.hero.lead':
      '内置的已知缺陷样例库。每个样例都预埋了缺陷及其准确行号，用同一套指标衡量不同分析策略，用于防止规则退化与误报增加。',
    'benchmark.empty.title': '未能载入基准报告',
    'benchmark.empty.body': '请确认本地服务正在运行。',
    'benchmark.strategy.title': '策略对比',
    'benchmark.strategy.static.name': '逐行规则',
    'benchmark.strategy.static.desc':
      '按行匹配的安全规则：动态执行、硬编码凭证、SQL 插值、危险反序列化等。',
    'benchmark.strategy.ast.name': 'AST 规则',
    'benchmark.strategy.ast.desc':
      '基于 Python 语法树：可变默认参数、裸 except、资源泄漏、弱哈希、异常链丢失等。',
    'benchmark.strategy.combined.name': '合并策略',
    'benchmark.strategy.combined.desc':
      '逐行规则与 AST 规则合并去重，对应真实审查链路的默认行为。',
    'benchmark.strategy.current': '当前',
    'benchmark.metric.precision': '精确率',
    'benchmark.metric.recall': '召回率',
    'benchmark.metric.f1': 'F1',
    'benchmark.metric.fpr': '误报率',
    'benchmark.metric.lineAccuracy': '行号准确率',
    'benchmark.metric.cases': '样例数',
    'benchmark.metric.precisionHint': '报出的问题里有多少是真缺陷',
    'benchmark.metric.recallHint': '预埋缺陷有多少被找到',
    'benchmark.metrics.title': '{strategy} · 指标',
    'benchmark.matrix.title': '混淆矩阵计数',
    'benchmark.matrix.cases.one': '{count} 个样例合计',
    'benchmark.matrix.cases.other': '{count} 个样例合计',
    'benchmark.matrix.tp': '命中 (TP)',
    'benchmark.matrix.fp': '误报 (FP)',
    'benchmark.matrix.fn': '漏报 (FN)',
    'benchmark.cases.title': '逐样例结果',
    'benchmark.cases.caseId': '样例',
    'benchmark.cases.control': '对照组',
    'benchmark.note.body':
      '样例库共有 4 个文件样例：3 个预埋缺陷（共 12 处）与 1 个零缺陷对照组。对照组用于衡量误报。这些数字代表规则在该精选集合上的表现，',
    'benchmark.note.emphasis': '不等同于在真实 PR 上的泛化准确率',
    'benchmark.note.tail': '。',
  },
  'en-US': {
    // Overview · hero
    'overview.hero.eyebrow': 'AI PR REVIEW AGENT · LOCAL WORKBENCH',
    'overview.hero.titleLine1': 'Turn GitHub PR review into',
    'overview.hero.titleLine2': 'an explainable, reviewable workflow',
    'overview.hero.lead':
      'Not a one-shot model call, but a review pipeline with planning, rules, evidence validation and cross-file interface analysis. Every conclusion traces back to a concrete file and changed line.',
    'overview.hero.ctaReview': 'Start a review',
    'overview.hero.ctaBenchmark': 'View accuracy',
    'overview.hero.consoleAria': 'Latest review',
    'overview.hero.console.findings.one': '{count} finding · {duration}',
    'overview.hero.console.findings.other': '{count} findings · {duration}',
    'overview.hero.console.empty': 'No review runs yet',

    // Overview · trust strip
    'overview.trust.aria': 'Product workflow commitments',
    'overview.trust.title': 'Not a black-box verdict — verifiable engineering evidence.',
    'overview.trust.p1.title': 'Plan first',
    'overview.trust.p1.body': 'Risk and review scope are computed before any model call.',
    'overview.trust.p2.title': 'Evidence-backed',
    'overview.trust.p2.body': 'File, line and diff linkage validated finding by finding.',
    'overview.trust.p3.title': 'Reproducible',
    'overview.trust.p3.body': 'Results, cost and feedback all stay on this machine.',
    'overview.trust.p4.title': 'Demo-ready',
    'overview.trust.p4.body': 'Offline demo and benchmark are always available.',

    // Overview · pipeline
    'overview.pipeline.title': 'From PR link to review report',
    'overview.pipeline.1.title': 'Fetch PR',
    'overview.pipeline.1.body':
      'Parse the GitHub PR URL and pull metadata, diff, file list and file contents.',
    'overview.pipeline.2.title': 'Smart filtering',
    'overview.pipeline.2.body':
      'Skip pure deletions, oversized and irrelevant files; a force-include allowlist is supported.',
    'overview.pipeline.3.title': 'Build context',
    'overview.pipeline.3.body':
      'tree-sitter syntax tree → regex extraction → diff window: three fallback levels so it never crashes.',
    'overview.pipeline.4.title': 'Generate plan',
    'overview.pipeline.4.body':
      'Derive risk level, priority files and review strategy from the PR intent and change characteristics.',
    'overview.pipeline.5.title': 'Per-file review',
    'overview.pipeline.5.body':
      'Call the model concurrently for structured findings, bounded by both per-run and 24-hour budgets.',
    'overview.pipeline.6.title': 'Rules & evidence',
    'overview.pipeline.6.body':
      'Merge deterministic rule hits, then validate each piece of evidence against real changed lines.',
    'overview.pipeline.7.title': 'Cross-file impact',
    'overview.pipeline.7.body':
      'Diff base signatures and locate external callers that would break.',
    'overview.pipeline.8.title': 'Report & persist',
    'overview.pipeline.8.body':
      'Render terminal / markdown / json / GitHub comments and write to SQLite for later review.',

    // Overview · capabilities
    'overview.capabilities.title': 'Key capabilities',
    'overview.capabilities.1.title': 'Intelligent review planning',
    'overview.capabilities.1.body':
      'A deterministic ReviewPlan is produced before any model call: risk level, risk categories, priority files, review strategy and whether cross-file analysis is needed.',
    'overview.capabilities.2.title': 'Rules + AI dual-path analysis',
    'overview.capabilities.2.body':
      '15 deterministic rules (line-level security rules + Python AST-level rules) merged and de-duplicated with model findings; rule hits carry a source marker.',
    'overview.capabilities.3.title': 'Evidence chain validation',
    'overview.capabilities.3.body':
      'Every finding is checked for file, line number, whether it lands on a changed line and whether the snippet really exists — marked valid / needs_review / invalid.',
    'overview.capabilities.4.title': 'Cross-file interface impact',
    'overview.capabilities.4.body':
      'Build a symbol index, diff signatures against the PR base (parameters, return types, async, base classes) and locate the real external callers.',
    'overview.capabilities.5.title': 'Syntax-level context',
    'overview.capabilities.5.body':
      'tree-sitter parses Python / JavaScript / TypeScript to extract imports, function signatures, classes and inheritance; it falls back to regex when not installed.',
    'overview.capabilities.6.title': 'Quantifiable accuracy',
    'overview.capabilities.6.body':
      'A built-in library of known-defect samples reports precision, recall, F1, false-positive rate and line accuracy to prevent strategy regressions.',

    // Overview · snapshot
    'overview.snapshot.title': 'Current status',
    'overview.snapshot.error': 'Some data failed to load: {detail}',
    'overview.snapshot.runs': 'Review runs',
    'overview.snapshot.runsHint': '{count} runs in total',
    'overview.snapshot.prs': 'PRs covered',
    'overview.snapshot.findings': 'Findings',
    'overview.snapshot.precision': 'Rule precision',
    'overview.snapshot.precisionHint': 'Recall {recall}',
    'overview.snapshot.notLoaded': 'Not loaded',
    'overview.snapshot.rules': 'Deterministic rules',
    'overview.snapshot.rulesHint': 'Line rules + AST rules (de-duplicated)',
    'overview.snapshot.providers': 'Supported providers',
    'overview.snapshot.providersHint': 'OpenAI-compatible + Anthropic',

    // Overview · accuracy preview (reuses benchmark.metric.*)
    'overview.accuracy.title': 'Benchmark results',
    'overview.accuracy.description':
      'Measured results on a curated set of known-defect samples, used to prevent rule regressions and rising false positives.',
    'overview.accuracy.detail': 'View details →',
    'overview.accuracy.strategy': '{strategy} strategy',
    'overview.accuracy.cases.one': '{count} sample',
    'overview.accuracy.cases.other': '{count} samples',
    'overview.accuracy.note':
      'These are results on a curated regression sample set: they describe how the rules perform on that set, not the generalization accuracy on real PRs.',

    // Overview · CLI / HTTP
    'overview.cli.title': 'One engine, two ways to use it',
    'overview.cli.terminal': 'Command line',
    'overview.cli.http': 'Local HTTP API',
    'overview.cli.endpoints':
      'POST /api/plan       Generate a review plan\n' +
      'POST /api/review     Run a full review\n' +
      'GET  /api/history    History and statistics\n' +
      'GET  /api/report     Fetch a report by run_id\n' +
      'GET  /api/benchmark  Accuracy report\n' +
      'POST /api/feedback   Record human feedback',

    // Offline demo panel
    'overview.demo.aria': 'Offline demo',
    'overview.demo.title': 'See the whole review pipeline without configuring a token',
    'overview.demo.body':
      'Uses the same demo data as the CLI to show the ReviewPlan, deterministic rules and Evidence validation. Great for live demos and for quickly grasping what makes the system different.',
    'overview.demo.run': 'Run offline demo',
    'overview.demo.running': 'Running…',
    'overview.demo.emptyTitle': 'Pick a case and run it',
    'overview.demo.emptyBody': 'Results will appear here',

    // Benchmark page
    'benchmark.hero.title': 'Accuracy benchmark',
    'benchmark.hero.lead':
      'A built-in library of known-defect samples. Each sample has planted defects with their exact line numbers, so one set of metrics can compare analysis strategies and guard against rule regressions and rising false positives.',
    'benchmark.empty.title': 'Could not load the benchmark report',
    'benchmark.empty.body': 'Make sure the local service is running.',
    'benchmark.strategy.title': 'Strategy comparison',
    'benchmark.strategy.static.name': 'Line rules',
    'benchmark.strategy.static.desc':
      'Line-matching security rules: dynamic execution, hard-coded credentials, SQL interpolation, unsafe deserialization and more.',
    'benchmark.strategy.ast.name': 'AST rules',
    'benchmark.strategy.ast.desc':
      'Based on the Python syntax tree: mutable default arguments, bare except, resource leaks, weak hashes, lost exception chains and more.',
    'benchmark.strategy.combined.name': 'Combined strategy',
    'benchmark.strategy.combined.desc':
      'Line rules and AST rules merged and de-duplicated — the default behaviour of the real review pipeline.',
    'benchmark.strategy.current': 'Current',
    'benchmark.metric.precision': 'Precision',
    'benchmark.metric.recall': 'Recall',
    'benchmark.metric.f1': 'F1',
    'benchmark.metric.fpr': 'False-positive rate',
    'benchmark.metric.lineAccuracy': 'Line accuracy',
    'benchmark.metric.cases': 'Samples',
    'benchmark.metric.precisionHint': 'How many reported issues are real defects',
    'benchmark.metric.recallHint': 'How many planted defects were found',
    'benchmark.metrics.title': '{strategy} · Metrics',
    'benchmark.matrix.title': 'Confusion matrix counts',
    'benchmark.matrix.cases.one': '{count} sample in total',
    'benchmark.matrix.cases.other': '{count} samples in total',
    'benchmark.matrix.tp': 'True positive (TP)',
    'benchmark.matrix.fp': 'False positive (FP)',
    'benchmark.matrix.fn': 'False negative (FN)',
    'benchmark.cases.title': 'Per-sample results',
    'benchmark.cases.caseId': 'Sample',
    'benchmark.cases.control': 'Control',
    'benchmark.note.body':
      'The sample library has 4 file samples: 3 with planted defects (12 in total) and 1 zero-defect control. The control measures false positives. These numbers describe how the rules perform on this curated set, ',
    'benchmark.note.emphasis': 'not the generalization accuracy on real PRs',
    'benchmark.note.tail': '.',
  },
}

# AI PR Review Assistant — 前端展示页面参考文档

> 📅 创建日期：2026-05-31
> 🎨 设计风格：像素卡通 (Pixel Art) 主题
> 🛠️ 技术栈：HTML + CSS + GSAP (ScrollTrigger) + Canvas 粒子系统

---

## 一、项目概述

本项目为 AI PR Review Assistant 创建了一个现代化的前端展示页面，用于展示项目功能、特性和使用方式。

### 设计灵感

- **像素卡通风格**：8-bit 像素字体、方块边框、像素阴影
- **Canvas 粒子系统**：浮动像素粒子背景
- **像素机器人吉祥物**：CSS 绘制，跟随鼠标眨眼

### 技术选型

| 技术 | 用途 | 说明 |
|------|------|------|
| HTML5 | 结构 | 语义化标签，无障碍访问 |
| CSS3 | 样式 | CSS 变量、Grid、Flexbox |
| GSAP 3.x | 动画 | ScrollTrigger、Timeline、Tween |
| 无框架 | 轻量 | 纯原生 JS，CDN 加载 GSAP |

---

## 二、文件结构

```
website/
├── index.html          # 主页面 (约 400 行)
├── css/
│   └── style.css       # 样式文件 (约 600 行)
├── js/
│   └── main.js         # GSAP 动画 + 交互 (约 200 行)
└── assets/
    └── (预留 SVG 图标目录)
```

---

## 三、页面分区详解

### 1. 导航栏 (Nav)

**功能**：
- 固定顶部，毛玻璃背景效果
- Logo + 导航链接 + GitHub 按钮
- 移动端汉堡菜单

**GSAP 动画**：
- 入场淡入
- 滚动时边框变化

**代码**：
```javascript
// Nav 背景变化
ScrollTrigger.create({
  trigger: document.body,
  start: 'top -80px',
  onEnter: () => nav.style.borderBottomColor = '#333',
  onLeaveBack: () => nav.style.borderBottomColor = 'var(--border)',
});
```

---

### 2. Hero 区域

**功能**：
- 项目标题 + 渐变文字
- 副标题描述
- 终端风格安装命令 (Tab 切换)
- CTA 按钮

**GSAP 动画**：
```javascript
const heroTl = gsap.timeline({ defaults: { ease: 'power3.out' } });
heroTl
  .from('.hero-badge', { opacity: 0, y: 20, duration: 0.6 })
  .from('.hero-title', { opacity: 0, y: 40, duration: 0.8 }, '-=0.3')
  .from('.hero-subtitle', { opacity: 0, y: 30, duration: 0.6 }, '-=0.4')
  .from('.hero-install', { opacity: 0, y: 30, duration: 0.6 }, '-=0.3')
  .from('.hero-actions', { opacity: 0, y: 20, duration: 0.5 }, '-=0.3');
```

**安装命令 Tab 切换**：
- pipx (推荐)
- pip
- curl (Linux/macOS)

---

### 3. 统计数据 (Stats)

**展示内容**：
- 175 Tests Passing
- 14 Core Modules
- 18 Model Providers
- 88% Code Coverage

**GSAP 动画 — 数字滚动**：
```javascript
statNumbers.forEach(el => {
  const target = parseInt(el.dataset.target);
  ScrollTrigger.create({
    trigger: el,
    start: 'top 85%',
    once: true,
    onEnter: () => {
      gsap.to(el, {
        duration: 1.5,
        ease: 'power2.out',
        onUpdate: function () {
          el.textContent = Math.round(this.progress() * target);
        },
      });
    },
  });
});
```

---

### 4. 流水线 (Pipeline)

**展示内容**：
8 步审查流水线可视化：
1. PR Fetcher — 获取 PR 数据
2. Filter — 智能过滤
3. Context — 构建上下文
4. Prompt — 组装 Prompt
5. AI Review — AI 审查
6. Post-Process — 后处理
7. Store — 持久化
8. Report — 输出报告

**GSAP 动画 — 逐步展现**：
```javascript
pipelineSteps.forEach((step, i) => {
  gsap.to(step, {
    opacity: 1,
    y: 0,
    duration: 0.5,
    ease: 'power2.out',
    scrollTrigger: {
      trigger: step,
      start: 'top 85%',
      once: true,
    },
  });
});
```

---

### 5. 特性展示 (Features)

**展示内容** (6 个卡片)：
1. Multi-Model Support — 18+ 供应商
2. Cost Control — 成本控制
3. Smart Filtering — 智能过滤
4. Rich Terminal UI — 终端 UI
5. Multiple Outputs — 多格式输出
6. Chat Workspace — 聊天工作区

**GSAP 动画 — 批量入场**：
```javascript
featureCards.forEach((card, i) => {
  gsap.to(card, {
    opacity: 1,
    y: 0,
    duration: 0.6,
    delay: i * 0.1,
    ease: 'power2.out',
    scrollTrigger: {
      trigger: card,
      start: 'top 85%',
      once: true,
    },
  });
});
```

---

### 6. 代码演示 (Demo)

**展示内容**：
- 左侧：终端命令示例
- 右侧：审查输出示例

**GSAP 动画 — 逐行打字效果**：
```javascript
demoCodeLines.forEach((line, i) => {
  gsap.from(line, {
    opacity: 0,
    x: -10,
    duration: 0.3,
    delay: i * 0.12,
    ease: 'power2.out',
  });
});
```

---

### 7. 模型供应商 (Providers)

**展示内容**：
18 个供应商标签：OpenAI, Anthropic, DeepSeek, Qwen, SiliconFlow, Moonshot, Zhipu, Baichuan, Minimax, Stepfun, Doubao, Hunyuan, Yi, OpenRouter, API2D, CloseAI, OhMyGPT, Custom

**GSAP 动画 — 弹性缩放**：
```javascript
providerTags.forEach((tag, i) => {
  gsap.to(tag, {
    opacity: 1,
    scale: 1,
    duration: 0.4,
    delay: i * 0.04,
    ease: 'back.out(1.7)',
    scrollTrigger: {
      trigger: '.providers-grid',
      start: 'top 80%',
      once: true,
    },
  });
});
```

---

### 8. 安装指南 (Install)

**展示内容** (6 种安装方式)：
1. pipx (推荐)
2. pip
3. GitHub
4. Linux / macOS (curl)
5. Windows PowerShell
6. From Source

---

### 9. FAQ

**展示内容**：
5 个常见问题手风琴：
1. 需要付费吗？
2. 支持哪些编程语言？
3. 如何保护代码隐私？
4. 可以集成到 CI/CD 吗？
5. 与 GitHub Copilot Code Review 有什么区别？

**交互逻辑**：
```javascript
document.querySelectorAll('.faq-question').forEach(btn => {
  btn.addEventListener('click', () => {
    const item = btn.parentElement;
    const isOpen = item.classList.contains('open');
    document.querySelectorAll('.faq-item').forEach(i => i.classList.remove('open'));
    if (!isOpen) item.classList.add('open');
  });
});
```

---

### 10. CTA + Footer

- CTA：安装命令 + GitHub Star 按钮
- Footer：Logo + 链接 + 版权

---

## 四、设计规范

### 配色方案

```css
:root {
  --bg-primary: #0a0a0a;      /* 主背景 */
  --bg-secondary: #111111;     /* 次背景 */
  --bg-card: #161616;          /* 卡片背景 */
  --bg-code: #1a1a2e;          /* 代码块背景 */
  --text-primary: #f1ecec;     /* 主文字 */
  --text-secondary: #cfcecd;   /* 次文字 */
  --text-dim: #656363;         /* 弱化文字 */
  --accent: #6366f1;           /* 主强调色 (紫蓝) */
  --accent-light: #818cf8;     /* 浅强调色 */
  --cyan: #22d3ee;             /* 青色 (代码高亮) */
  --green: #34d399;            /* 绿色 (成功) */
  --yellow: #fbbf24;           /* 黄色 (警告) */
  --red: #f87171;              /* 红色 (错误) */
}
```

### 字体

```css
--font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
--font-mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
```

### 间距

- Section padding: `100px 0`
- Container max-width: `1200px`
- Card padding: `32px`
- Border radius: `12px` (大) / `8px` (小)

---

## 五、GSAP 技术要点

### 使用的 GSAP 功能

| 功能 | 用途 | 代码 |
|------|------|------|
| `gsap.timeline()` | Hero 序列入场 | 时间轴串联多个动画 |
| `ScrollTrigger` | 滚动触发 | `start: 'top 85%'` |
| `gsap.from()` | 入场动画 | 初始状态 → 当前状态 |
| `gsap.to()` | 变化动画 | 当前状态 → 目标状态 |
| `stagger` | 交错效果 | 延迟递增 |
| `once: true` | 单次触发 | 只播放一次 |
| `onUpdate` | 数字滚动 | 逐帧更新数字 |
| `back.out(1.7)` | 弹性缓动 | 供应商标签弹入 |

### 性能优化

1. `once: true` — 避免重复触发
2. `transform` 属性优先 — GPU 加速
3. `will-change` 自动管理 — GSAP 自动处理
4. 避免 `width/height` 动画 — 使用 `scale` 替代

### 无障碍支持

- `prefers-reduced-motion` — 可通过 `gsap.matchMedia()` 支持
- 语义化 HTML 标签
- 键盘可访问的交互元素

---

## 六、响应式设计

### 断点

| 断点 | 布局变化 |
|------|----------|
| `> 900px` | 桌面：3 列特性、2 列 Demo |
| `600-900px` | 平板：2 列特性、1 列 Demo |
| `< 480px` | 手机：1 列、缩小字体 |

### 移动端适配

```css
@media (max-width: 900px) {
  .nav-links { display: none; }
  .nav-toggle { display: flex; }
  .features-grid { grid-template-columns: 1fr; }
  .pipeline-flow { flex-direction: column; }
}
```

---

## 七、本地运行

```bash
cd G:/Project/qiniuyun/AI-PR-Review-Assistant/website
python -m http.server 8080
# 浏览器打开 http://localhost:8080
```

---

## 八、后续优化建议

| 优先级 | 优化项 | 说明 |
|--------|--------|------|
| P0 | 字体加载 | 添加 Google Fonts (Inter, JetBrains Mono) |
| P0 | favicon | 添加网站图标 |
| P1 | 暗/亮主题切换 | 添加主题切换按钮 |
| P1 | 搜索引擎优化 | 添加 meta 标签、结构化数据 |
| P2 | 性能优化 | 图片懒加载、CSS 压缩 |
| P2 | 国际化 | 添加英文版本 |
| P3 | 动画增强 | 添加更多 GSAP 动画效果 |
| P3 | 部署 | 部署到 GitHub Pages |

---

## 九、参考资料

- [GSAP 官方文档](https://gsap.com/docs/v3/)
- [ScrollTrigger 文档](https://gsap.com/docs/v3/Plugins/ScrollTrigger/)
- [OpenCode 官网](https://opencode.ai) — 设计参考
- [Claude Code 官网](https://claude.ai/code) — 设计参考

---

*文档创建时间：2026-05-31*
*维护者：AI PR Review Assistant 团队*

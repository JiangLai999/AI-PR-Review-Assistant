# AI PR Review Assistant

> AI 椹卞姩鐨?GitHub Pull Request 浠ｇ爜瀹℃煡 CLI 宸ュ叿

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-175%20Passed-brightgreen.svg)]()
[![Coverage](https://img.shields.io/badge/Coverage-88%25-green.svg)]()

馃寪 **[鍦ㄧ嚎婕旂ず](https://jianglai999.github.io/AI-PR-Review-Assistant/)** | 馃摉 **[瀹屾暣鏂囨。](docs/PROJECT_DESIGN.md)** | 馃挕 **[鍒涙柊鐐筣(docs/INNOVATION.md)**

---

## 椤圭洰绠€浠?
AI PR Review Assistant 鏄竴涓熀浜?AI 鐨勪唬鐮佸鏌ュ伐鍏凤紝閫氳繃鏅鸿兘鍒嗘瀽 GitHub Pull Request 鍙樻洿锛岃嚜鍔ㄥ彂鐜版綔鍦ㄩ棶棰橈紝甯姪寮€鍙戣€呮彁鍗囦唬鐮佸鏌ユ晥鐜囦笌璐ㄩ噺銆?
### 鏍稿績鐗规€?
- 馃 **澶氭ā鍨嬫敮鎸?* 鈥?鏀寔 18+ 妯″瀷渚涘簲鍟嗭紙OpenAI銆丄nthropic銆丏eepSeek銆丵wen 绛夛級
- 馃幆 **鏅鸿兘杩囨护** 鈥?鑷姩璺宠繃娴嬭瘯銆佹枃妗ｃ€侀厤缃瓑涓嶇浉鍏虫枃浠?- 馃搳 **缁撴瀯鍖栬緭鍑?* 鈥?缁堢褰╄壊銆丮arkdown銆丣SON銆丟itHub PR 璇勮
- 馃挵 **鎴愭湰鎺у埗** 鈥?鍗曟杩愯鍜?24 灏忔椂绐楀彛鍙岄噸棰勭畻闄愬埗
- 馃挰 **鑱婂ぉ宸ヤ綔鍖?* 鈥?浜や簰寮忕粓绔亰澶╋紝鏀寔鏂滄潬鍛戒护
- 馃摝 **涓€閿畨瑁?* 鈥?pipx / pip / curl 澶氱瀹夎鏂瑰紡

---

## 蹇€熷紑濮?
### 瀹夎

```bash
# 鏂瑰紡 1锛歱ipx 瀹夎锛堟帹鑽愶級
pipx install ai-pr-review

# 鏂瑰紡 2锛歱ip 瀹夎
pip install ai-pr-review

# 鏂瑰紡 3锛氫竴琛屽懡浠ゅ畨瑁咃紙Linux/macOS锛?curl -fsSL https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-Assistant/main/install.sh | sh

# 鏂瑰紡 4锛氫竴琛屽懡浠ゅ畨瑁咃紙Windows PowerShell锛?irm https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-Assistant/main/install.ps1 | iex

# 鏂瑰紡 5锛氫粠 GitHub 瀹夎
pipx install "git+https://github.com/JiangLai999/AI-PR-Review-Assistant.git"

# 鏂瑰紡 6锛氫粠婧愮爜瀹夎
git clone https://github.com/JiangLai999/AI-PR-Review-Assistant.git
cd AI-PR-Review-Assistant
pip install -e .
```

### 閰嶇疆

```bash
# 鍚姩浜や簰寮忛厤缃悜瀵?pr-review config

# 蹇€熼厤缃?pr-review config --quick

# 鏌ョ湅褰撳墠閰嶇疆
pr-review config show

# 娴嬭瘯閰嶇疆鏈夋晥鎬?pr-review config test

# 妫€鏌ヤ緵搴斿晢鍋ュ悍鐘舵€?pr-review config health

# 鍙戠幇鍙敤妯″瀷
pr-review config models

# 鍒囨崲榛樿妯″瀷
pr-review config model --name "妯″瀷鍚嶇О"
```

### 浣跨敤

```bash
# 瀹℃煡 PR
pr-review https://github.com/owner/repo/pull/123

# 鎸囧畾妯″瀷瀹℃煡
pr-review https://github.com/owner/repo/pull/123 --model gpt-4

# 杈撳嚭涓?Markdown 鏂囦欢
pr-review https://github.com/owner/repo/pull/123 --format markdown --output report.md

# 鍙戝竷涓?GitHub PR 璇勮
pr-review https://github.com/owner/repo/pull/123 --publish-comment

# 骞茶繍琛岋紙涓嶈皟鐢?AI锛?pr-review https://github.com/owner/repo/pull/123 --dry-run

# 鏌ョ湅鍘嗗彶璁板綍
pr-review history

# 鏌ョ湅缁熻淇℃伅
pr-review stats
```

---

## 瀹℃煡娴佹按绾?
```
PR URL
  鈹?  鈻?鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?   鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?   鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹? PR Fetcher  鈹傗攢鈹€鈹€鈻垛攤    Filter    鈹傗攢鈹€鈹€鈻垛攤   Context    鈹?鈹? 鑾峰彇 PR 鏁版嵁 鈹?   鈹? 鏅鸿兘杩囨护    鈹?   鈹? 鏋勫缓涓婁笅鏂? 鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?   鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?   鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                                               鈹?                                               鈻?鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?   鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?   鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹?   Post      鈹傗梹鈹€鈹€鈹€鈹? AI Client   鈹傗梹鈹€鈹€鈹€鈹?  Prompt     鈹?鈹? Processor   鈹?   鈹? 璋冪敤 AI 妯″瀷 鈹?   鈹? 缁勮 Prompt 鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?   鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?   鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?       鈹?       鈻?鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?   鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹?Result Store 鈹?   鈹?  Report     鈹?鈹? 鎸佷箙鍖栧瓨鍌?  鈹?   鈹? 娓叉煋鎶ュ憡    鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?   鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?```

---

## Chat 宸ヤ綔鍖?
```bash
# 杩涘叆鑱婂ぉ妯″紡
pr-review chat

# 鍗曟潯娑堟伅
pr-review chat --message "甯垜鎬荤粨杩欎釜 PR 鐨勫鏌ラ噸鐐?

# 涓存椂鍒囨崲妯″瀷
pr-review chat --model "gpt-4" --message "浣犲ソ"
```

### 鏂滄潬鍛戒护

| 鍛戒护 | 璇存槑 |
|------|------|
| `/help` | 鏄剧ず甯姪淇℃伅 |
| `/status` | 鏄剧ず浼氳瘽鐘舵€?|
| `/usage` | 鏄剧ず娑堟伅缁熻 |
| `/model <ID>` | 鍒囨崲妯″瀷 |
| `/review <URL>` | 鎵ц PR 瀹℃煡 |
| `/history` | 鏌ョ湅瀹℃煡鍘嗗彶 |
| `/stats` | 鏌ョ湅缁熻鏁版嵁 |
| `/compact` | 鍘嬬缉浼氳瘽鍘嗗彶 |
| `/restore` | 鎭㈠鍘嗗彶浼氳瘽 |
| `/clear` | 娓呯┖褰撳墠浼氳瘽 |
| `/exit` | 閫€鍑鸿亰澶?|

---

## 閰嶇疆鏂囦欢

閰嶇疆鏂囦欢浣嶇疆锛歚~/.ai_pr_review/config.json`

```json
{
  "provider": {
    "name": "custom",
    "display_name": "Custom Endpoint",
    "api_key": "sk-xxx",
    "base_url": "https://api.example.com/v1",
    "api_format": "openai",
    "default_model": "model-name"
  },
  "github_token": "ghp_xxx",
  "preferences": {
    "output_format": "terminal",
    "language": "zh-CN"
  },
  "ai_client": {
    "max_cost_per_run": 5.0,
    "max_cost_per_24h": 50.0
  }
}
```

### 閰嶇疆浼樺厛绾?
1. CLI 鍙傛暟 `--config <path>`
2. 鐜鍙橀噺 `AI_PR_REVIEW_*`
3. 鐢ㄦ埛绾ч厤缃?`~/.ai_pr_review/config.json`
4. 椤圭洰绾ч厤缃?`.ai_pr_review/config.json`
5. 椤圭洰鏈湴閰嶇疆 `.ai_pr_review/config.local.json`

---

## 鏀寔鐨勬ā鍨嬩緵搴斿晢

| 渚涘簲鍟?| API 鏍煎紡 | 璇存槑 |
|--------|----------|------|
| OpenAI | openai | GPT 绯诲垪妯″瀷 |
| Anthropic | anthropic | Claude 绯诲垪妯″瀷 |
| DeepSeek | openai | DeepSeek 绯诲垪妯″瀷 |
| Qwen | openai | 閫氫箟鍗冮棶绯诲垪 |
| SiliconFlow | openai | 纭呭熀娴佸姩 |
| Moonshot | openai | 鏈堜箣鏆楅潰 |
| Zhipu | openai | 鏅鸿氨 AI |
| Baichuan | openai | 鐧惧窛鏅鸿兘 |
| Minimax | openai | MiniMax |
| Stepfun | openai | 闃惰穬鏄熻景 |
| Doubao | openai | 璞嗗寘 |
| Hunyuan | openai | 娣峰厓 |
| Yi | openai | 闆朵竴涓囩墿 |
| OpenRouter | openai | 澶氭ā鍨嬩唬鐞?|
| API2D | openai | 绗笁鏂逛唬鐞?|
| CloseAI | openai | 绗笁鏂逛唬鐞?|
| OhMyGPT | openai | 绗笁鏂逛唬鐞?|
| Custom | openai | 鑷畾涔夌鐐?|

---

## 鎶€鏈爤

| 鎶€鏈?| 鐢ㄩ€?|
|------|------|
| Python 3.12+ | 涓昏瑷€ |
| Click | CLI 妗嗘灦 |
| Rich | 缁堢 UI |
| Pydantic | 鏁版嵁楠岃瘉 |
| PyGithub | GitHub API |
| Anthropic SDK | AI 妯″瀷璋冪敤 |
| tree-sitter | AST 瑙ｆ瀽锛堝彲閫夛級 |
| SQLite | 鏈湴瀛樺偍 |
| GSAP | 鍓嶇鍔ㄧ敾 |

---

## 椤圭洰缁撴瀯

```
AI-PR-Review-Assistant/
鈹溾攢鈹€ src/ai_pr_review/
鈹?  鈹溾攢鈹€ cli.py                    # CLI 鍏ュ彛
鈹?  鈹溾攢鈹€ config.py                 # 閰嶇疆绠＄悊
鈹?  鈹溾攢鈹€ config_wizard.py          # 閰嶇疆鍚戝
鈹?  鈹溾攢鈹€ chat_commands.py          # 鑱婂ぉ鍛戒护
鈹?  鈹溾攢鈹€ chat_runtime.py           # 鑱婂ぉ寮曟搸
鈹?  鈹溾攢鈹€ models/
鈹?  鈹?  鈹斺攢鈹€ pr_data.py            # 鏁版嵁妯″瀷
鈹?  鈹溾攢鈹€ services/
鈹?  鈹?  鈹溾攢鈹€ pr_fetcher.py         # PR 鑾峰彇
鈹?  鈹?  鈹溾攢鈹€ filter_pipeline.py    # 鏂囦欢杩囨护
鈹?  鈹?  鈹溾攢鈹€ context_builder.py    # 涓婁笅鏂囨瀯寤?鈹?  鈹?  鈹溾攢鈹€ prompt_assembler.py   # Prompt 缁勮
鈹?  鈹?  鈹溾攢鈹€ ai_client.py          # AI 璋冪敤
鈹?  鈹?  鈹溾攢鈹€ post_processor.py     # 鍚庡鐞?鈹?  鈹?  鈹溾攢鈹€ report_renderer.py    # 鎶ュ憡娓叉煋
鈹?  鈹?  鈹溾攢鈹€ result_store.py       # 缁撴灉瀛樺偍
鈹?  鈹?  鈹溾攢鈹€ review_orchestrator.py# 缂栨帓灞?鈹?  鈹?  鈹溾攢鈹€ cost_controller.py    # 鎴愭湰鎺у埗
鈹?  鈹?  鈹斺攢鈹€ model_providers/      # 澶氫緵搴斿晢閫傞厤
鈹?  鈹斺攢鈹€ utils/
鈹?      鈹斺攢鈹€ github_url_parser.py  # URL 瑙ｆ瀽
鈹溾攢鈹€ tests/                        # 娴嬭瘯濂椾欢 (175 tests)
鈹溾攢鈹€ docs/                         # 鏂囨。
鈹?  鈹溾攢鈹€ PROJECT_DESIGN.md         # 椤圭洰璁捐涔?鈹?  鈹溾攢鈹€ INNOVATION.md             # 鍒涙柊鐐规枃妗?鈹?  鈹溾攢鈹€ API.md                    # API 鏂囨。
鈹?  鈹斺攢鈹€ WEBSITE.md                # 鍓嶇灞曠ず鏂囨。
鈹溾攢鈹€ website/                      # 鍓嶇灞曠ず椤甸潰
鈹?  鈹溾攢鈹€ index.html
鈹?  鈹溾攢鈹€ css/style.css
鈹?  鈹斺攢鈹€ js/main.js
鈹溾攢鈹€ pyproject.toml                # 鍖呴厤缃?鈹溾攢鈹€ README.md                     # 鏈枃浠?鈹溾攢鈹€ CHANGELOG.md                  # 鍙樻洿鏃ュ織
鈹溾攢鈹€ CONTRIBUTING.md               # 璐＄尞鎸囧崡
鈹斺攢鈹€ LICENSE                       # MIT 璁稿彲璇?```

---

## 娴嬭瘯涓庤川閲?
```bash
# 杩愯娴嬭瘯
pytest

# 浠ｇ爜鏍煎紡鍖栨鏌?black --check src tests

# 瀵煎叆鎺掑簭妫€鏌?isort --check-only src tests

# 绫诲瀷妫€鏌?mypy src
```

### 娴嬭瘯瑕嗙洊鐜?
| 妯″潡 | 娴嬭瘯鏁?| 瑕嗙洊鐜?|
|------|--------|--------|
| CLI | 54 | 85% |
| PR Fetcher | 48 | 87% |
| Filter Pipeline | 14 | 96% |
| Context Builder | 5 | 94% |
| Prompt Assembler | 6 | 95% |
| AI Client | 12 | 77% |
| Post Processor | 5 | 100% |
| Cost Controller | 6 | 93% |
| Result Store | 6 | 91% |
| Report Renderer | 6 | 97% |
| Model Providers | 8 | 82% |
| Review Orchestrator | 1 | 97% |
| **鎬昏** | **175** | **88%** |

---

## 鍒涙柊鐐?
鏈」鐩噰鐢?**AI 澶氭ā鍨嬪崗浣滃喅绛?* 妯″紡锛屽叿鏈変互涓嬪垱鏂帮細

| 鍒涙柊鐐?| 鎻忚堪 |
|--------|------|
| 涓夋柟浼氳皥鍐崇瓥 | Claude Code + DeepSeek + 鐢ㄦ埛澶氳疆璁ㄨ |
| 鍙屾ā鍨嬪苟琛屽晢璁?| DeepSeek + GPT 5.4 浜掕ˉ鍗忎綔 |
| 鍙屽眰 Prompt 缁撴瀯 | 650 tokens锛屽噺灏?65% |
| 涓夌骇 Fallback | tree-sitter 鈫?姝ｅ垯 鈫?diff context |
| 澶氫緵搴斿晢閫傞厤 | 18+ 妯″瀷渚涘簲鍟嗙粺涓€鎺ュ彛 |
| 鍓嶇浜у搧灞曠ず | GSAP 鍔ㄧ敾 + 瀹屾暣鏂囨。宓屽叆 |

璇﹁ [鍒涙柊鐐规枃妗(docs/INNOVATION.md)銆?
---

## 鐩稿叧鏂囨。

| 鏂囨。 | 璇存槑 |
|------|------|
| [PROJECT_DESIGN.md](docs/PROJECT_DESIGN.md) | 瀹屾暣椤圭洰璁捐涔?|
| [INNOVATION.md](docs/INNOVATION.md) | 鍒涙柊鐐规枃妗?|
| [API.md](docs/API.md) | API 鏂囨。 |
| [WEBSITE.md](docs/WEBSITE.md) | 鍓嶇灞曠ず鏂囨。 |
| [CHANGELOG.md](CHANGELOG.md) | 鍙樻洿鏃ュ織 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 璐＄尞鎸囧崡 |
| [RELEASE.md](docs/RELEASE.md) | 鍙戝竷鎸囧崡 |

---

## 璐＄尞

娆㈣繋鎻愪氦 Issue 鎴?Pull Request锛?
1. Fork 鏈粨搴?2. 鍒涘缓鍔熻兘鍒嗘敮 (`git checkout -b feature/xxx`)
3. 鎻愪氦鏇存敼 (`git commit -m 'feat: add xxx'`)
4. 鎺ㄩ€佸埌鍒嗘敮 (`git push origin feature/xxx`)
5. 鍒涘缓 Pull Request

璇风‘淇濓細
- 鎵€鏈夋祴璇曢€氳繃 (`pytest`)
- 浠ｇ爜鏍煎紡姝ｇ‘ (`black --check src tests`)
- 瀵煎叆鎺掑簭姝ｇ‘ (`isort --check-only src tests`)
- 绫诲瀷妫€鏌ラ€氳繃 (`mypy src`)

---

## 璁稿彲璇?
鏈」鐩噰鐢?[MIT 璁稿彲璇乚(LICENSE)銆?
---

## 鑷磋阿

- [PyGithub](https://github.com/PyGithub/PyGithub) 鈥?GitHub API 璁块棶
- [Rich](https://github.com/Textualize/rich) 鈥?缁堢 UI
- [Click](https://github.com/pallets/click) 鈥?CLI 妗嗘灦
- [Anthropic](https://www.anthropic.com/) 鈥?AI 妯″瀷鏀寔
- [GSAP](https://greensock.com/gsap/) 鈥?鍓嶇鍔ㄧ敾


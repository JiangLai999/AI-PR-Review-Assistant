"""后端文案双语化的测试（B 类生成时本地化 + A 类结构化键）。

覆盖三件事：

1. 生成时本地化（``services/i18n_text.py``）：摘要与过滤说明按语言出双语，
   拿不到语言时回落中文；
2. ``SaveResult`` 携带 ``message_key`` / ``message_params``，且 ``message`` 原文不变；
3. ``CredentialStatus`` 携带 ``label_key`` / ``detail_key`` / ``fix_hint_key`` / ``params``，
   且 ``label`` / ``detail`` / ``fix_hint`` 原文不变。

契约与 key 清单见 docs/opencode-backend-i18n.md。
"""

from __future__ import annotations

import re
from pathlib import Path

from ai_pr_review.config import AIClientConfig, AppConfig, FilterPipelineConfig, ResultStoreConfig
from ai_pr_review.credentials import check_github, check_model, collect_status
from ai_pr_review.models.pr_data import FileDiff, FileStatus
from ai_pr_review.services.filter_pipeline import FileFilter, FilterPipeline, FilterReasonCode
from ai_pr_review.services.i18n_text import (
    filter_included_by_default,
    is_english,
    review_summary,
)
from ai_pr_review.web_config import apply_config_update

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SETTINGS_TS = _REPO_ROOT / "web" / "src" / "i18n" / "settings.ts"
# 词条按命名空间分成多个文件（components / settings / overview / review / shell）。
# 守卫必须扫**全部**命名空间：只看 settings.ts 会漏掉 ask.* / panels.* 这类词条，
# 后端一旦把 key 挪到另一命名空间，守卫就会静默失效。
_I18N_DIR = _REPO_ROOT / "web" / "src" / "i18n"
# 后端会把这些前缀的 key 交给前端渲染：key 必须能在词典里查到。
_I18N_KEY_PATTERN = re.compile(r'"((?:credentials|config\.save)\.[A-Za-z0-9_.]+)"')


def _app_config() -> AppConfig:
    config = AppConfig()
    config.result_store = ResultStoreConfig(db_path=":memory:")
    config.ai_client = AIClientConfig(api_key="sk-existing", model="old-model")
    return config


def _plain_file(filename: str = "src/core/service.py") -> FileDiff:
    return FileDiff(
        filename=filename,
        status=FileStatus.MODIFIED,
        additions=1,
        deletions=0,
        changes=1,
    )


# ------------------------------------------------------- B 类：生成时本地化


def test_review_summary_zh_and_en():
    assert review_summary("zh-CN", 3) == "审查完成，发现 3 个问题"
    assert review_summary("en-US", 3) == "Review complete — 3 finding(s)."
    assert review_summary("en", 1) != review_summary("zh-CN", 1)
    # 拿不到语言（None / 空串）必须回落中文，而不是抛错或出英文。
    assert review_summary(None, 0) == "审查完成，发现 0 个问题"
    assert review_summary("", 2) == "审查完成，发现 2 个问题"
    assert is_english("en") is True
    assert is_english("en-GB") is True
    assert is_english("zh-CN") is False


def test_filter_default_included_message_zh_and_en():
    assert filter_included_by_default("zh-CN") == "文件未命中过滤规则，默认纳入审查。"
    assert (
        filter_included_by_default("en-US")
        == "File did not match any filter rule; included by default."
    )
    assert filter_included_by_default(None) == "文件未命中过滤规则，默认纳入审查。"

    # 接线验证：FileFilter / FilterPipeline 的默认纳入说明跟随注入的语言。
    zh_result = FileFilter(FilterPipelineConfig(exclude_patterns=[]), language="zh-CN").evaluate(
        _plain_file()
    )
    en_result = FileFilter(FilterPipelineConfig(exclude_patterns=[]), language="en-US").evaluate(
        _plain_file()
    )
    assert zh_result.primary_reason is not None
    assert zh_result.primary_reason.code == FilterReasonCode.INCLUDED_BY_DEFAULT
    assert zh_result.primary_reason.message == "文件未命中过滤规则，默认纳入审查。"
    assert en_result.primary_reason is not None
    assert en_result.primary_reason.message == (
        "File did not match any filter rule; included by default."
    )

    # 不传 language 的旧调用方保持中文（既有契约不回归）。
    default_result = FilterPipeline(FilterPipelineConfig(exclude_patterns=[])).run([_plain_file()])
    assert default_result.results[0].primary_reason is not None
    assert default_result.results[0].primary_reason.message == "文件未命中过滤规则，默认纳入审查。"


# ------------------------------------------------------- A1 类：SaveResult 键


def test_save_result_carries_message_key_and_params(tmp_path: Path, monkeypatch):
    config = _app_config()
    monkeypatch.setattr("ai_pr_review.web_config.DEFAULT_CONFIG_PATH", tmp_path / "config.json")

    # 成功
    saved = apply_config_update(config, {"model": "new-model"})
    assert saved.ok is True
    assert saved.message_key == "config.save.saved"
    assert saved.message_params == {"count": 1, "path": "config.json"}
    assert saved.message, "message 原文必须保留（CLI / 旧前端仍消费它）"

    # 未知键
    unsupported = apply_config_update(config, {"bogus_key": 1})
    assert unsupported.ok is False
    assert unsupported.message_key == "config.save.unsupported_key"
    assert unsupported.message_params == {"keys": "bogus_key"}
    assert "unsupported key" in unsupported.message

    # 非法值
    invalid = apply_config_update(config, {"review_concurrency": "abc"})
    assert invalid.ok is False
    assert invalid.message_key == "config.save.invalid_value"
    assert invalid.message_params == {"name": "review_concurrency"}
    assert invalid.message, "非法值分支的原文同样保留"

    # 没有改动
    noop = apply_config_update(config, {})
    assert noop.ok is True
    assert noop.message_key == "config.save.noop"
    assert noop.message_params == {}


# --------------------------------------------------- A2 类：CredentialStatus 键


def test_credential_status_carries_i18n_keys():
    github = check_github("")
    assert github.label_key == "credentials.github"
    assert github.detail_key == "credentials.github.missing"
    assert github.fix_hint_key == "credentials.github.fix_token"
    assert github.label == "GitHub"
    assert "未配置" in github.detail and github.fix_hint
    github_payload = github.to_dict()
    assert github_payload["detail_key"] == "credentials.github.missing"
    assert github_payload["params"] == {}

    provider = check_model("https://api.deepseek.com/v1", "", "some-model")
    assert provider.label_key == "credentials.provider"
    assert provider.detail_key == "credentials.provider.missing"
    assert provider.fix_hint_key == "credentials.provider.fix_key"
    assert provider.label == "模型供应商"
    assert "未配置" in provider.detail and provider.fix_hint
    provider_payload = provider.to_dict()
    assert provider_payload["label_key"] == "credentials.provider"
    assert provider_payload["params"] == {}


# ------------------------------------------- A3 类：后端 key ↔ 前端词典 漂移守卫
#
# 这一组用例存在的原因是一次真机验收：后端 12 条结构化 key（`credentials.provider.ok`
# 等）根本没进前端词典，`hasDictKey` 全部判假 → 英文界面静默回落到中文原文。
# 单测当时全绿，因为没人校验"后端给的 key，词典里到底有没有"。


def _frontend_dict() -> dict[str, dict[str, str]]:
    """把 `web/src/i18n/*.ts` 的语言块合并成 `{lang: {key: 原文模板}}`。

    只做词法级解析（不引 TS 运行时）：key 是 `'a.b.c':`，值是该行或紧随其后的
    第一个单引号字面量。对"值换行写"的条目（本项目常见）同样成立。
    合并所有命名空间，避免"后端 key 与词条不在同一个文件"时守卫失效。
    """
    parsed: dict[str, dict[str, str]] = {"zh-CN": {}, "en-US": {}}
    for path in sorted(_I18N_DIR.glob("*.ts")):
        if path.name == "index.ts":
            continue  # 合并器，本身不含词条
        text = path.read_text(encoding="utf-8")
        if "'en-US': {" not in text:
            continue
        zh_block, _, en_block = text.partition("'en-US': {")
        for lang, block in (("zh-CN", zh_block), ("en-US", en_block)):
            matches = list(re.finditer(r"'([A-Za-z][\w.]*)':", block))
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
                value = re.search(r"'((?:[^'\\]|\\.)*)'", block[match.end() : end])
                if value is not None:
                    parsed[lang][match.group(1)] = value.group(1)
    return parsed


def _placeholders(template: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", template))


def _backend_i18n_keys() -> list[str]:
    keys: set[str] = set()
    for name in ("credentials.py", "web_config.py", "web_server.py"):
        source = (_REPO_ROOT / "src" / "ai_pr_review" / name).read_text(encoding="utf-8")
        keys.update(_I18N_KEY_PATTERN.findall(source))
    return sorted(keys)


def test_every_backend_key_exists_in_the_frontend_dictionary():
    dictionary = _frontend_dict()
    keys = _backend_i18n_keys()

    # 守住用例本身：正则失效（比如源码改用单引号）时会变成空集，那是静默失效。
    assert "credentials.provider.ok_named_models" in keys
    assert "config.save.saved" in keys

    missing = {
        lang: sorted(key for key in keys if key not in dictionary[lang])
        for lang in ("zh-CN", "en-US")
    }
    assert missing == {"zh-CN": [], "en-US": []}, missing


def test_all_i18n_namespaces_keep_identical_language_key_sets():
    """中英两侧的 key 集合必须逐字一致（跨 components/settings/overview/review/shell）。

    "中英文各自统一"的前提是两边**同构**：少一条英文词条，英文界面就会回落到中文
    （`t()` 找不到 key 时按 shell.ts 的规则回落）。这条用例把整个词典的对称性锁住，
    不再只盯后端发出来的那几个 key。
    """
    dictionary = _frontend_dict()
    zh, en = set(dictionary["zh-CN"]), set(dictionary["en-US"])

    # 守住用例本身：解析器若因文件结构变化而扫不到词条，会变成"空集等于空集"。
    assert len(zh) > 500, f"词典解析疑似失效，只读到 {len(zh)} 条"
    assert zh == en, {
        "only_in_zh": sorted(zh - en)[:10],
        "only_in_en": sorted(en - zh)[:10],
    }


def test_severity_labels_are_not_hardcoded_in_components():
    """严重度文案必须走词典：写死英文大写会让中文界面的徽标一直显示 MEDIUM。

    回归点：`components/ui.tsx:SeverityBadge` 与 `pages/ReviewPage.tsx` 曾各存一份
    `SEVERITY_LABEL/SEVERITY_TEXT`（'CRITICAL' / 'HIGH' / …），中文界面里徽标、筛选
    chips、下拉三处都是英文大写。注意**大小写敏感**：`Severity[]` 这类小写枚举值
    是合法的规范 id，不算违规。
    """
    offenders: list[str] = []
    for relative in ("components/ui.tsx", "pages/ReviewPage.tsx"):
        text = (_REPO_ROOT / "web" / "src" / relative).read_text(encoding="utf-8")
        for label in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
            if f"'{label}'" in text or f'"{label}"' in text:
                offenders.append(f"{relative}: {label}")
    assert not offenders, offenders


def test_provider_placeholder_values_match_the_branches(monkeypatch):
    """词条里的每个 `{占位符}` 都必须真有值，且中英词条占位符一致。

    `interpolate` 只在 param 存在时替换，缺一个就会把 `{models}` 原样显示在页面上。
    """

    def fake_http(response):
        def _call(*_args, **_kwargs):
            return response

        return _call

    cases = [
        # 未配置密钥 → 缺 key 分支
        ("https://api.deepseek.com/v1", "", "m", None, "credentials.provider.missing"),
        # 200 但模型不在清单里
        (
            "https://api.deepseek.com/v1",
            "sk-ok",
            "gpt-4o",
            (200, {"data": [{"id": "deepseek-flash"}]}),
            "credentials.provider.model_missing",
        ),
        # 200：端点归属已知 / 未知 × 有模型 / 无模型 → 四条不同词条
        (
            "https://api.deepseek.com/v1",
            "sk-ok",
            "deepseek-flash",
            (200, {"data": [{"id": "deepseek-flash"}]}),
            "credentials.provider.ok_named_models",
        ),
        (
            "https://api.deepseek.com/v1",
            "sk-ok",
            "deepseek-flash",
            (200, {"data": []}),
            "credentials.provider.ok_named",
        ),
        (
            "https://relay.example/v1",
            "sk-ok",
            "m",
            (200, {"data": [{"id": "m"}]}),
            "credentials.provider.ok_models",
        ),
        ("https://relay.example/v1", "sk-ok", "m", (200, {"data": []}), "credentials.provider.ok"),
        # 401：密钥前缀与端点对不上 → 换一条更具体的词条
        ("https://api.deepseek.com/v1", "sk-ok", "m", (401, {}), "credentials.provider.invalid"),
        (
            "https://api.deepseek.com/v1",
            "ghu-mismatch",
            "m",
            (401, {}),
            "credentials.provider.invalid_mismatch",
        ),
        ("https://api.deepseek.com/v1", "sk-ok", "m", (404, {}), "credentials.provider.not_found"),
        (
            "https://api.deepseek.com/v1",
            "sk-ok",
            "m",
            (None, {"error": "timeout"}),
            "credentials.provider.unreachable",
        ),
        ("https://api.deepseek.com/v1", "sk-ok", "m", (500, {"boom": 1}), "credentials.provider.error"),
    ]

    dictionary = _frontend_dict()
    seen: list[tuple[str, dict[str, object]]] = []
    for base_url, api_key, model, response, expected_key in cases:
        monkeypatch.setattr("ai_pr_review.credentials._http_json", fake_http(response))
        status = check_model(base_url, api_key, model)
        assert status.detail_key == expected_key, (base_url, api_key, response)
        seen.append((status.detail_key, status.params))
        seen.append((status.fix_hint_key, status.params))

    for response, expected_key in [
        (None, "credentials.github.missing"),
        ((200, {"login": "octocat"}), "credentials.github.ok"),
        ((401, {}), "credentials.github.invalid"),
        ((403, {}), "credentials.github.forbidden"),
        ((503, {"message": "nope"}), "credentials.github.other"),
    ]:
        monkeypatch.setattr("ai_pr_review.credentials._http_json", fake_http(response))
        token = "" if response is None else "ghp_whatever"
        status = check_github(token)
        assert status.detail_key == expected_key, response
        seen.append((status.detail_key, status.params))
        seen.append((status.fix_hint_key, status.params))

    # probe=0 的"尚未探测"分支（页面首屏走的就是这条）。模型名有没有配 → 两条不同词条。
    config = _app_config()
    config.github_token = "ghp_unprobed"
    report = collect_status(config, probe=False)
    assert {item.detail_key for item in report.items} == {
        "credentials.github.unprobed",
        "credentials.provider.unprobed_model",
    }
    for item in report.items:
        seen.append((item.detail_key, item.params))

    empty_model = _app_config()
    empty_model.ai_client.model = ""
    unprobed = collect_status(empty_model, probe=False)
    provider_item = next(item for item in unprobed.items if item.key == "model")
    assert provider_item.detail_key == "credentials.provider.unprobed"
    seen.append((provider_item.detail_key, provider_item.params))

    for key, params in seen:
        if not key:
            # 空 key = 前端回落原文（如 GitHub 探测通过时没有修复建议）。
            continue
        for lang in ("zh-CN", "en-US"):
            template = dictionary[lang].get(key)
            assert template is not None, (lang, key)
            holes = _placeholders(template)
            assert holes <= set(params), (lang, key, holes, params)
        assert _placeholders(dictionary["zh-CN"][key]) == _placeholders(
            dictionary["en-US"][key]
        ), key

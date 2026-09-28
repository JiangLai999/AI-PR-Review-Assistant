"""凭证诊断：判断 GitHub 与模型供应商是否真的可用。

设计原则：

1. **只报告状态，不返回明文密钥。** 输出里最多出现掩码。
2. **区分"密钥缺失"与"密钥/端点错配"。** 前者是没填，后者是填了但配错，
   两者的修复动作完全不同，不能都报成"缺少 API Key"。
3. **探测失败不抛异常。** 诊断本身不应该让调用方崩掉。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

PROBE_TIMEOUT = 20

# 常见供应商官方端点，用于识别"密钥与端点错配"
KNOWN_ENDPOINTS = {
    "api.deepseek.com": "DeepSeek",
    "api.openai.com": "OpenAI",
    "api.anthropic.com": "Anthropic",
    "dashscope.aliyuncs.com": "Qwen / 阿里云",
    "api.moonshot.cn": "Moonshot",
    "open.bigmodel.cn": "Zhipu",
    "api.siliconflow.cn": "SiliconFlow",
    "openrouter.ai": "OpenRouter",
    "token-plan-cn.xiaomimimo.com": "小米 MiMo",
}


def mask_secret(value: str | None) -> str:
    """把密钥压成可安全展示的掩码。"""
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "•" * len(text)
    return f"{text[:4]}…{text[-4:]}"


def detect_endpoint_owner(base_url: str | None) -> str | None:
    """从 base_url 推断端点归属，用于错配提示。"""
    url = (base_url or "").lower()
    for host, owner in KNOWN_ENDPOINTS.items():
        if host in url:
            return owner
    return None


@dataclass(slots=True)
class CredentialStatus:
    """单项凭证的健康状态。

    ``label`` / ``detail`` / ``fix_hint`` 是**原文**（中文），供 CLI 与旧前端使用；
    ``*_key`` + ``params`` 是结构化键（契约见 docs/DEV_RECORD.md），
    前端按当前语言渲染，``to_dict()`` 一并输出；key 为空串时前端回落原文。
    """

    key: str
    label: str
    ok: bool
    detail: str
    fix_hint: str = ""
    configured: bool = True
    label_key: str = ""
    detail_key: str = ""
    fix_hint_key: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CredentialReport:
    """整体凭证报告。"""

    items: list[CredentialStatus] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(item.ok for item in self.items)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "items": [item.to_dict() for item in self.items]}


def _http_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    method: str = "GET",
) -> tuple[int | None, dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, {"raw": raw[:200]}
    except Exception as exc:  # 网络不可达等
        return None, {"error": f"{type(exc).__name__}: {exc}"}


def check_github(token: str | None) -> CredentialStatus:
    """探测 GitHub token。"""
    value = (token or "").strip()
    if not value:
        return CredentialStatus(
            key="github",
            label="GitHub",
            ok=False,
            configured=False,
            detail="未配置 GitHub Token，无法读取 PR。",
            fix_hint="在设置页填入具有 repo 权限的 Token。",
            label_key="credentials.github",
            detail_key="credentials.github.missing",
            fix_hint_key="credentials.github.fix_token",
        )

    status, data = _http_json(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {value}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "ai-pr-review-credential-probe",
        },
    )
    if status == 200:
        login = str(data.get("login", "未知账号"))
        return CredentialStatus(
            key="github",
            label="GitHub",
            ok=True,
            detail=f"已认证为 {login}。",
            label_key="credentials.github",
            detail_key="credentials.github.ok",
            params={"login": login},
        )
    if status == 401:
        return CredentialStatus(
            key="github",
            label="GitHub",
            ok=False,
            detail="Token 无效或已被撤销（401 Bad credentials）。",
            fix_hint="到 GitHub Settings → Developer settings 重新签发，并更新设置页。",
            label_key="credentials.github",
            detail_key="credentials.github.invalid",
            fix_hint_key="credentials.github.fix_reissue",
        )
    if status == 403:
        return CredentialStatus(
            key="github",
            label="GitHub",
            ok=False,
            detail="GitHub 拒绝访问（403），可能是配额耗尽或权限不足。",
            fix_hint="稍后重试，或确认 Token 具备 repo 权限。",
            label_key="credentials.github",
            detail_key="credentials.github.forbidden",
            fix_hint_key="credentials.github.fix_retry",
        )
    body = str(data)[:120]
    return CredentialStatus(
        key="github",
        label="GitHub",
        ok=False,
        detail=f"无法确认 Token 状态（HTTP {status}）：{body}",
        fix_hint="检查网络连通性后重试。",
        label_key="credentials.github",
        detail_key="credentials.github.other",
        fix_hint_key="credentials.github.fix_network",
        params={"status": status, "body": body},
    )


def check_model(base_url: str | None, api_key: str | None, model: str | None) -> CredentialStatus:
    """探测模型供应商：先看密钥是否存在，再区分端点错配。"""
    key = (api_key or "").strip()
    url = (base_url or "").strip() or "https://api.openai.com/v1"
    model_name = (model or "").strip()
    owner = detect_endpoint_owner(url)

    if not key:
        return CredentialStatus(
            key="model",
            label="模型供应商",
            ok=False,
            configured=False,
            detail="未配置模型 API Key，完整审查无法执行。",
            fix_hint="在设置页选择供应商并填入 API Key；计划模式不需要密钥。",
            label_key="credentials.provider",
            detail_key="credentials.provider.missing",
            fix_hint_key="credentials.provider.fix_key",
        )

    status, data = _http_json(
        url.rstrip("/") + "/models",
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "User-Agent": "ai-pr-review-credential-probe",
        },
    )

    if status == 200:
        available = [str(m.get("id")) for m in data.get("data", [])][:40]
        if model_name and available and model_name not in available:
            return CredentialStatus(
                key="model",
                label="模型供应商",
                ok=False,
                detail=(
                    f"密钥有效，但端点不提供模型 `{model_name}`。"
                    f"该端点可用模型：{', '.join(available[:6])}"
                ),
                fix_hint="在设置页把模型名改成该端点实际提供的名称。",
                label_key="credentials.provider",
                detail_key="credentials.provider.model_missing",
                fix_hint_key="credentials.provider.fix_model",
                # 词典条目里两个占位符都必须有值：前端 `interpolate` 只在 param 存在时
                # 替换，缺一个就会把 `{models}` 原样显示在页面上。
                params={"model": model_name, "models": ", ".join(available[:6])},
            )
        suffix = f"，可用模型 {len(available)} 个" if available else ""
        return CredentialStatus(
            key="model",
            label="模型供应商",
            ok=True,
            detail=f"已连接 {owner or '自定义端点'}{suffix}。",
            label_key="credentials.provider",
            # 端点归属（owner）与可用模型数都可能为空，4 种组合各有一条词条：
            # 宁可多几条词条，也不让英文界面出现「Connected to .」这种半截句子。
            detail_key=_provider_ok_key(owner, available),
            params=_provider_ok_params(owner, available),
        )

    if status == 401:
        # 关键分支：密钥存在但被端点拒绝 —— 常见于 base_url 配错供应商。
        mismatched = owner and not _key_looks_like(url, key)
        detail = f"密钥被 {owner or '该端点'} 拒绝（401 Invalid API Key）。"
        if mismatched:
            detail += " 看起来密钥与端点不属于同一家供应商。"
        return CredentialStatus(
            key="model",
            label="模型供应商",
            ok=False,
            detail=detail,
            fix_hint=(
                "核对 base_url 与 API Key 是否来自同一供应商。"
                "例如 DeepSeek 的密钥应配 https://api.deepseek.com/v1。"
            ),
            label_key="credentials.provider",
            detail_key=(
                "credentials.provider.invalid_mismatch"
                if mismatched
                else "credentials.provider.invalid"
            ),
            fix_hint_key="credentials.provider.fix_mismatch",
        )
    if status == 404:
        return CredentialStatus(
            key="model",
            label="模型供应商",
            ok=False,
            detail=f"端点不存在（404）：{url}",
            fix_hint="检查 base_url 是否为 OpenAI 兼容端点（通常以 /v1 结尾）。",
            label_key="credentials.provider",
            detail_key="credentials.provider.not_found",
            fix_hint_key="credentials.provider.fix_endpoint",
            params={"url": url},
        )
    if status is None:
        return CredentialStatus(
            key="model",
            label="模型供应商",
            ok=False,
            detail=f"无法连接端点：{data.get('error', '未知网络错误')}",
            fix_hint="确认 base_url 可达，且本机网络允许访问。",
            label_key="credentials.provider",
            detail_key="credentials.provider.unreachable",
            fix_hint_key="credentials.provider.fix_network",
            # 拿不到 error 时给一个语言无关的占位，避免英文词条里剩 `{reason}`。
            params={"reason": str(data.get("error") or "—")},
        )
    return CredentialStatus(
        key="model",
        label="模型供应商",
        ok=False,
        detail=f"端点返回 HTTP {status}：{str(data)[:140]}",
        fix_hint="根据报错核对端点地址与密钥。",
        label_key="credentials.provider",
        detail_key="credentials.provider.error",
        fix_hint_key="credentials.provider.fix_endpoint",
        params={"status": status},
    )


def _provider_ok_key(owner: str | None, available: list[str]) -> str:
    """200 分支的词条选择：端点归属与可用模型数各自可能为空。

    四种组合各有一条词条，这样中英文都不会拼出「已连接 。」/「Connected to .」。
    """
    if available:
        return "credentials.provider.ok_named_models" if owner else "credentials.provider.ok_models"
    return "credentials.provider.ok_named" if owner else "credentials.provider.ok"


def _provider_ok_params(owner: str | None, available: list[str]) -> dict[str, object]:
    """`_provider_ok_key` 选出的词条**必须**拿到的占位符值（缺一个就会露出 `{...}`）。"""
    params: dict[str, object] = {}
    if owner:
        params["endpoint"] = owner
    if available:
        params["count"] = len(available)
    return params


def _key_looks_like(base_url: str, key: str) -> bool:
    """粗略判断密钥前缀是否与端点归属一致（仅用于提示，不做拦截）。"""
    lowered = base_url.lower()
    if "deepseek" in lowered:
        return key.startswith("sk-")
    if "anthropic" in lowered:
        return key.startswith("sk-ant-")
    return True


def collect_status(config: Any, *, probe: bool = True) -> CredentialReport:
    """汇总当前配置下的凭证健康状态。

    `probe=False` 时**不发任何网络请求**，只判断是否填写 —— 供界面首屏快速渲染。
    刻意在调用探测函数之前分支，否则"本地模式"仍会去打网络。
    """
    ai = config.ai_client

    if probe:
        return CredentialReport(
            items=[
                check_github(config.github_token),
                check_model(ai.base_url, ai.api_key, ai.model),
            ]
        )

    has_github = bool((config.github_token or "").strip())
    has_key = bool((ai.api_key or "").strip())
    return CredentialReport(
        items=[
            CredentialStatus(
                key="github",
                label="GitHub",
                ok=has_github,
                configured=has_github,
                detail="已配置（尚未探测连通性）。" if has_github else "未配置 GitHub Token。",
                fix_hint="" if has_github else "在设置页填入具有 repo 权限的 Token。",
                label_key="credentials.github",
                detail_key=(
                    "credentials.github.unprobed" if has_github else "credentials.github.missing"
                ),
                fix_hint_key="" if has_github else "credentials.github.fix_token",
            ),
            CredentialStatus(
                key="model",
                label="模型供应商",
                ok=has_key,
                configured=has_key,
                detail=(
                    f"已配置（尚未探测连通性），模型 {ai.model or '未指定'}。"
                    if has_key
                    else "未配置模型 API Key，完整审查无法执行。"
                ),
                fix_hint="" if has_key else "在设置页填入 API Key；计划模式不需要密钥。",
                label_key="credentials.provider",
                detail_key=(
                    # 模型名可能没配：有名字才用带 `{model}` 的词条，否则用无占位符那条。
                    (
                        "credentials.provider.unprobed_model"
                        if str(ai.model or "").strip()
                        else "credentials.provider.unprobed"
                    )
                    if has_key
                    else "credentials.provider.missing"
                ),
                fix_hint_key="" if has_key else "credentials.provider.fix_key",
                params=(
                    {"model": str(ai.model).strip()}
                    if has_key and str(ai.model or "").strip()
                    else {}
                ),
            ),
        ]
    )

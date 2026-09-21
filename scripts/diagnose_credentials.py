"""诊断凭证配置：只报告"是否可用"，不打印任何密钥明文。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_pr_review.config import DEFAULT_CONFIG_PATH, AppConfig  # noqa: E402


def mask(value: str | None) -> str:
    v = (value or "").strip()
    if not v:
        return "**缺失**"
    if len(v) <= 12:
        return f"{v[:2]}…(len={len(v)})"
    return f"{v[:6]}…{v[-4:]} (len={len(v)})"


cfg = AppConfig.load()
print("配置文件:", DEFAULT_CONFIG_PATH)
print()
print("=== 面向用户的字段 ===")
print("  provider.name        :", cfg.provider.name or "(空)")
print("  provider.display_name:", cfg.provider.display_name or "(空)")
print("  provider.api_key     :", mask(cfg.provider.api_key))
print("  provider.base_url    :", cfg.provider.base_url or "(空)")
print("  provider.api_format  :", cfg.provider.api_format or "(空)")
print("  provider.default_model:", cfg.provider.default_model or "(空)")
print()
print("=== 面向内部调用的字段（AIClient 实际读取）===")
print("  ai_client.api_key    :", mask(cfg.ai_client.api_key))
print("  ai_client.provider   :", cfg.ai_client.provider or "(空)")
print("  ai_client.base_url   :", cfg.ai_client.base_url or "(空)")
print("  ai_client.api_format :", cfg.ai_client.api_format or "(空)")
print("  ai_client.model      :", cfg.ai_client.model or "(空)")
print()
print("=== github ===")
print("  github_token         :", mask(cfg.github_token))
print()
print("=== 关键判断 ===")
key_user = (cfg.provider.api_key or "").strip()
key_client = (cfg.ai_client.api_key or "").strip()
print("  用户侧有 Key :", bool(key_user))
print("  调用侧有 Key :", bool(key_client))
if key_user and not key_client:
    print("  → 用户侧配了 Key，但 AIClient 读的 ai_client.api_key 为空：同步链路断裂")
elif not key_user and not key_client:
    print("  → 两处都为空：需要配置模型供应商密钥")
else:
    print("  → 调用侧可读到 Key")

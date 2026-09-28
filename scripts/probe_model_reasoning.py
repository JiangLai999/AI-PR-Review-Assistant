"""探测某个供应商/模型是否**真的**支持思考（reasoning）控制，再决定要不要开放思考档位。

产品化自 `_p5_verify/p6proto/` 下的一次性脚本（``probe_reasoning_effort.py`` /
``probe_ollama_reasoning.py`` / ``probe_model_metadata_sources.py``）：以后每接一个供应商，
跑一条命令就能知道"该不该给它开放思考档位"。

用法::

    # DeepSeek（密钥只从环境变量读，绝不接受命令行明文密钥）
    DEEPSEEK_API_KEY=sk-... python scripts/probe_model_reasoning.py \
        --provider deepseek --model deepseek-flash

    # 本机 Ollama（无需密钥）
    python scripts/probe_model_reasoning.py --provider ollama --model qwen3.5:4b \
        --base-url http://127.0.0.1:11434/v1

    # 顺带对照 Ollama 原生端点（区分"模型不支持"还是"端点不支持"）
    python scripts/probe_model_reasoning.py --provider ollama --model qwen3.5:4b --also-native

探测四件事（打印成表 + 结论行）：

    1. 关闭思考（thinking disabled / think=false）能否真的让 reasoning 为空
    2. 低到高的 reasoning 长度是否单调（均值 + 极差，信号必须盖过噪声与效应量门槛）
    3. 每次调用的 completion tokens 与答案字符数（暴露"思考吃掉预算导致答案为空"）
    4. 结论行 SUPPORTED / NOT-SUPPORTED / INCONCLUSIVE

判定规则与解读方式见 ``docs/DEV_RECORD.md``。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

MIN_TRIALS = 3
DEFAULT_MAX_TOKENS = 2000
DEFAULT_ANSWER_FLOOR = 50
EFFECT_RATIO = 1.5  # 档位效应量门槛：最高档均值 / 最低档均值

MAIN_QUESTION = (
    "三个箱子，一个全是金币、一个全是银币、一个金银混合，标签全部贴错。"
    "你只能从一个箱子里取出一枚硬币查看。请完整说明如何确定三个箱子的真实内容，"
    "并解释为什么只看标签无法完成、为什么你的方案必然正确。"
)
CONTROL_QUESTION = "1+1 等于几？只输出算式和结果，不要解释。"

VERDICT_SUPPORTED = "SUPPORTED"
VERDICT_NOT_SUPPORTED = "NOT-SUPPORTED"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"

PASS = "PASS"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class Preset:
    """每个供应商一组固定探测参数（levels 顺序即由低到高）。"""

    name: str
    base_url: str
    effort_param: str
    levels: tuple[str, ...]
    off_params: dict[str, Any] | None
    off_label: str
    key_envs: tuple[str, ...]


PROVIDERS: dict[str, Preset] = {
    "deepseek": Preset(
        name="deepseek",
        base_url="https://api.deepseek.com/v1",
        effort_param="reasoning_effort",
        levels=("low", "high", "max"),
        off_params={"thinking": {"type": "disabled"}},
        off_label="thinking=disabled",
        key_envs=("DEEPSEEK_API_KEY", "DEEPSEEK_PROBE_KEY"),
    ),
    "ollama": Preset(
        name="ollama",
        base_url="http://127.0.0.1:11434/v1",
        effort_param="reasoning_effort",
        levels=("low", "medium", "high"),
        off_params={"think": False},
        off_label="think=false",
        key_envs=(),
    ),
    "openai": Preset(
        name="openai",
        base_url="https://api.openai.com/v1",
        effort_param="reasoning_effort",
        levels=("low", "medium", "high"),
        off_params=None,  # 推理系没有"关闭思考"开关 → R1 只能判 INCONCLUSIVE
        off_label="(no-off-switch)",
        key_envs=("OPENAI_API_KEY",),
    ),
}


@dataclass
class Trial:
    """单次调用结果；失败/超时也是一条记录，绝不抛栈。"""

    label: str
    index: int
    kind: str  # "main" | "control"
    ok: bool
    reason_chars: int = 0
    completion_tokens: int | None = None
    answer_chars: int = 0
    elapsed: float = 0.0
    error: str = ""
    truncated: bool = False


@dataclass
class LevelStat:
    label: str
    kind: str
    n_ok: int
    n_err: int
    reason_mean: float | None
    reason_range: float | None
    ctok_mean: float | None
    ctok_range: float | None
    answer_mean: float | None
    answer_range: float | None
    truncated: int
    starved: int
    status: str


@dataclass
class RuleResult:
    name: str
    status: str
    detail: str


@dataclass
class ProbeReport:
    provider: str
    model: str
    endpoint: str
    max_tokens: int
    trials: int
    control_trials: int
    main_stats: list[LevelStat] = field(default_factory=list)
    control_stats: list[LevelStat] = field(default_factory=list)
    rules: list[RuleResult] = field(default_factory=list)
    verdict: str = VERDICT_INCONCLUSIVE
    scope: str = ""
    notes: list[str] = field(default_factory=list)
    native: list[dict[str, Any]] = field(default_factory=list)


class Out:
    """`--json` 模式下静默人类可读输出，只留一份干净的 JSON。"""

    def __init__(self, json_mode: bool) -> None:
        self.json_mode = json_mode

    def line(self, text: str = "") -> None:
        if not self.json_mode:
            print(text, flush=True)

    def fatal(self, text: str) -> None:
        print(text, file=sys.stderr, flush=True)


def chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def native_root(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return base[:-3]
    return base


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):  # content-parts 形态
        return "".join(p.get("text", "") for p in value if isinstance(p, dict))
    return "" if value is None else str(value)


def post_json(
    url: str, body: dict[str, Any], timeout: float, key: str = ""
) -> tuple[bool, Any, str]:
    """POST 一次，返回 (ok, payload, error)。任何异常都降级成一行错误文本。"""
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST", headers=headers
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").replace("\n", " ")[:160]
        return False, None, f"HTTP {exc.code}: {detail}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, None, f"{type(exc).__name__}: {exc}"[:160]
    except Exception as exc:  # noqa: BLE001 - 探测脚本不允许抛栈
        return False, None, f"{type(exc).__name__}: {exc}"[:160]
    elapsed = time.perf_counter() - started
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return False, None, f"bad JSON response: {exc}"[:160]
    return True, (payload, round(elapsed, 1)), ""


def parse_chat_payload(payload: dict[str, Any], max_tokens: int) -> Trial:
    """从 OpenAI 兼容响应里取出 reasoning / 答案 / tokens。"""
    choices = payload.get("choices") or [{}]
    message = choices[0].get("message") or {}
    reasoning = _text(
        message.get("reasoning_content") or message.get("reasoning") or message.get("thinking")
    )
    answer = _text(message.get("content"))
    usage = payload.get("usage") or {}
    ctok = usage.get("completion_tokens")
    ctok = int(ctok) if isinstance(ctok, (int, float)) else None
    return Trial(
        label="",
        index=0,
        kind="main",
        ok=True,
        reason_chars=len(reasoning),
        completion_tokens=ctok,
        answer_chars=len(answer),
        truncated=bool(ctok is not None and ctok >= max_tokens),
    )


def run_trial(
    url: str,
    base_body: dict[str, Any],
    level_params: dict[str, Any],
    label: str,
    index: int,
    kind: str,
    timeout: float,
    key: str,
    max_tokens: int,
    out: Out,
) -> Trial:
    body = {**base_body, **level_params}
    ok, payload, error = post_json(url, body, timeout, key)
    if not ok:
        trial = Trial(label=label, index=index, kind=kind, ok=False, error=error)
        out.line(f"  {kind:<7} {label:<24} #{index}  ERROR {error}")
        return trial
    assert isinstance(payload, tuple)
    data, elapsed = payload
    trial = parse_chat_payload(data, max_tokens)
    trial.label = label
    trial.index = index
    trial.kind = kind
    trial.elapsed = elapsed
    out.line(
        f"  {kind:<7} {label:<24} #{index}  reason={trial.reason_chars:<6} "
        f"ctok={str(trial.completion_tokens):<6} answer={trial.answer_chars:<6} "
        f"{trial.elapsed}s{'  TRUNC' if trial.truncated else ''}"
    )
    return trial


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _rng(values: list[float]) -> float | None:
    return max(values) - min(values) if values else None


def summarize(label: str, kind: str, trials: list[Trial], answer_floor: int) -> LevelStat:
    ok = [t for t in trials if t.ok]
    err = [t for t in trials if not t.ok]
    reasons = [float(t.reason_chars) for t in ok]
    ctoks = [float(t.completion_tokens) for t in ok if t.completion_tokens is not None]
    answers = [float(t.answer_chars) for t in ok]
    if not ok:
        status = "ERROR"
    elif err:
        status = "PARTIAL"
    else:
        status = "OK"
    starved = sum(1 for t in ok if t.answer_chars < (1 if kind == "control" else answer_floor))
    return LevelStat(
        label=label,
        kind=kind,
        n_ok=len(ok),
        n_err=len(err),
        reason_mean=_mean(reasons),
        reason_range=_rng(reasons),
        ctok_mean=_mean(ctoks),
        ctok_range=_rng(ctoks),
        answer_mean=_mean(answers),
        answer_range=_rng(answers),
        truncated=sum(1 for t in ok if t.truncated),
        starved=starved,
        status=status,
    )


def fmt_pair(mean: float | None, spread: float | None) -> str:
    if mean is None or spread is None:
        return "-"
    return f"{mean:.0f}/{spread:.0f}"


def print_table(out: Out, stats: list[LevelStat]) -> None:
    out.line(
        f"{'level':<24} {'n':>3} {'reason mean/range':<18} {'ctok mean/range':<17} "
        f"{'answer mean/range':<19} status"
    )
    for s in stats:
        out.line(
            f"{s.label:<24} {s.n_ok:>3} {fmt_pair(s.reason_mean, s.reason_range):<18} "
            f"{fmt_pair(s.ctok_mean, s.ctok_range):<17} "
            f"{fmt_pair(s.answer_mean, s.answer_range):<19} "
            f"{s.status}{'  trunc=' + str(s.truncated) if s.truncated else ''}"
        )


def short_label(label: str) -> str:
    """表格里用 `reasoning_effort=low`，规则详情里用 `low` 更易读。"""
    return label.split("=", 1)[1] if label.count("=") == 1 else label


def rule_off(off_stats: LevelStat | None) -> RuleResult:
    """R1: 关闭思考是否真的让 reasoning 为空。"""
    if off_stats is None:
        return RuleResult("R1 off", INCONCLUSIVE, "该供应商没有关闭思考的开关（无对照组）")
    if off_stats.n_ok == 0:
        return RuleResult("R1 off", INCONCLUSIVE, "关闭档位全部 ERROR，样本不足")
    if off_stats.reason_mean is not None and off_stats.reason_mean == 0:
        return RuleResult(
            "R1 off",
            PASS,
            f"关闭后 reasoning 全为 0（{off_stats.n_ok}/{off_stats.n_ok + off_stats.n_err} 次成功）",
        )
    return RuleResult(
        "R1 off",
        FAIL,
        f"关闭参数被忽略：{off_stats.label} 档 reasoning 均值 "
        f"{off_stats.reason_mean:.0f} 字符（应为 0）",
    )


def rule_mono(level_stats: list[LevelStat], trials: int) -> RuleResult:
    """R2: 由低到高的 reasoning 长度是否单调，且信号盖过噪声与效应量门槛。"""
    usable = [s for s in level_stats if s.n_ok > 0 and s.reason_mean is not None]
    labels = " -> ".join(f"{short_label(s.label)}={s.reason_mean:.0f}" for s in usable)
    if trials < MIN_TRIALS:
        return RuleResult(
            "R2 mono", INCONCLUSIVE, f"每档仅 {trials} 次，样本不足（要求 ≥{MIN_TRIALS}）"
        )
    if len(usable) < 2:
        errs = [s.label for s in level_stats if s.n_ok == 0]
        extra = f"；ERROR 档位: {', '.join(errs)}" if errs else ""
        return RuleResult("R2 mono", INCONCLUSIVE, f"有效档位不足 2 个{extra}")
    means = [s.reason_mean for s in usable if s.reason_mean is not None]
    if any(means[i + 1] <= means[i] for i in range(len(means) - 1)):
        return RuleResult("R2 mono", FAIL, f"均值非严格递增：{labels}")
    signal = means[-1] - means[0]
    noise = max((s.reason_range or 0.0) for s in usable)
    ratio = means[-1] / means[0] if means[0] > 0 else float("inf")
    # 先看效应量：最高档不到最低档的 1.5 倍，无论噪声多小都不构成"有效档位"。
    if ratio < EFFECT_RATIO:
        return RuleResult(
            "R2 mono",
            FAIL,
            f"均值递增但效应量不足：最高/最低 = {ratio:.2f} < {EFFECT_RATIO}（{labels}）",
        )
    # 再看噪声：效应量够大，但差异被档内波动淹没 → 只能说"测不准"。
    if signal <= noise:
        return RuleResult(
            "R2 mono",
            INCONCLUSIVE,
            f"效应量达标但波动过大：信号 {signal:.0f} ≤ 档内极差 {noise:.0f}（{labels}）",
        )
    return RuleResult(
        "R2 mono",
        PASS,
        f"单调且信号盖过噪声：{labels}；信号 {signal:.0f} > 极差 {noise:.0f}，比值 {ratio:.2f}",
    )


def rule_budget(all_stats: list[LevelStat], max_tokens: int, floor: int) -> RuleResult:
    """R3: 思考是否吃掉 token 预算导致答案为空（告警规则，不参与投票）。"""
    samples = [s for s in all_stats if s.n_ok]
    truncated = sum(s.truncated for s in samples)
    starved = sum(s.starved for s in samples)
    total = sum(s.n_ok for s in samples)
    if truncated or starved:
        return RuleResult(
            "R3 budget",
            "HIT",
            f"{truncated}/{total} 次 completion 顶满 max_tokens={max_tokens}，"
            f"{starved}/{total} 次答案字符低于门槛 → 需按档位预留思考预算"
            "（max_tokens = 答案预算 + 思考预算）",
        )
    return RuleResult("R3 budget", "OK", f"{total} 次调用均未触顶，答案字符正常")


def decide_verdict(rules: list[RuleResult], trials: int, notes: list[str]) -> tuple[str, str]:
    """R4: 由 R1/R2 投票出三选一结论。"""
    r1 = next(r for r in rules if r.name.startswith("R1"))
    r2 = next(r for r in rules if r.name.startswith("R2"))
    if trials < MIN_TRIALS:
        notes.append(f"每档仅 {trials} 次调用，低于 {MIN_TRIALS} 次下限 → 结论强制 INCONCLUSIVE")
        return VERDICT_INCONCLUSIVE, "insufficient-samples"
    positive = [r for r in (r1, r2) if r.status == PASS]
    if positive:
        if r1.status == PASS and r2.status == PASS:
            notes.append("开关与档位都实测有效：可开放 off + 全部档位")
            return VERDICT_SUPPORTED, "levels"
        if r1.status == PASS and r2.status == FAIL:
            notes.append("只有关闭开关实测有效，档位无单调差异：UI 只暴露开关，不暴露档位")
            return VERDICT_SUPPORTED, "toggle-only"
        if r1.status == PASS:
            notes.append(
                "关闭开关实测有效；档位判定 INCONCLUSIVE（样本不足或波动过大）→ 加大 --trials 再测"
            )
            return VERDICT_SUPPORTED, "off-only"
        if r1.status == FAIL:
            notes.append("档位单调有效但关闭开关无效：可开放档位，但没有可靠的 off")
        else:
            notes.append("该供应商没有关闭思考的对照组（或对照组样本不足）→ 仅凭档位单调性判定")
        return VERDICT_SUPPORTED, "levels-no-off"
    if r1.status == FAIL and r2.status == FAIL:
        notes.append("关闭无效且档位无差异：该端点很可能收下参数但忽略 → 不要开放思考档位")
        return VERDICT_NOT_SUPPORTED, "none"
    notes.append(
        "既无阳性信号也无双阴性证据（存在 INCONCLUSIVE 规则）→ 样本不足或波动过大；"
        "产品含义与 NOT-SUPPORTED 相同：证据不足就不开放档位，可加大 --trials 复测"
    )
    return VERDICT_INCONCLUSIVE, "uncertain"


def resolve_key(preset: Preset, key_env_arg: str | None, out: Out) -> str:
    """密钥只从环境变量读；命令行明文密钥一律拒绝。"""
    names = (key_env_arg,) if key_env_arg else preset.key_envs
    for name in names:
        value = os.environ.get(name, "")
        if value:
            return value
    if preset.key_envs or key_env_arg:
        wanted = key_env_arg or " 或 ".join(preset.key_envs)
        out.fatal(f"错误：环境变量 {wanted} 未设置（密钥只从环境变量读，不接受命令行明文密钥）。")
        raise SystemExit(2)
    return ""


def native_probe(base_url: str, model: str, timeout: float, out: Out) -> list[dict[str, Any]]:
    """可选：Ollama 原生 /api/chat 对照，区分"模型不支持"与"端点不支持"。"""
    url = f"{native_root(base_url)}/api/chat"
    rows: list[dict[str, Any]] = []
    for label, extra in (("baseline", {}), ("think=false", {"think": False})):
        body = {
            "model": model,
            "stream": False,
            "messages": [{"role": "user", "content": MAIN_QUESTION}],
            "options": {"num_predict": 600},
            **extra,
        }
        ok, payload, error = post_json(url, body, timeout)
        if not ok:
            out.line(f"  native {label:<22} ERROR {error}")
            rows.append({"case": label, "ok": False, "error": error})
            continue
        assert isinstance(payload, tuple)
        data, elapsed = payload
        message = data.get("message") or {}
        row = {
            "case": label,
            "ok": True,
            "thinking_chars": len(_text(message.get("thinking"))),
            "answer_chars": len(_text(message.get("content"))),
            "tokens": data.get("eval_count"),
            "elapsed": elapsed,
        }
        rows.append(row)
        out.line(
            f"  native {label:<22} thinking={row['thinking_chars']:<6} "
            f"answer={row['answer_chars']:<6} tokens={row['tokens']}  {elapsed}s"
        )
    return rows


def build_levels(preset: Preset, args: argparse.Namespace) -> list[tuple[str, dict[str, Any]]]:
    levels: list[tuple[str, dict[str, Any]]] = []
    off_params: dict[str, Any] | None = preset.off_params
    if args.off_json:
        try:
            parsed = json.loads(args.off_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--off-json 不是合法 JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise SystemExit("--off-json 必须是 JSON 对象")
        off_params = parsed
    if args.no_off:
        off_params = None
    if off_params is not None:
        levels.append((preset.off_label if not args.off_json else "off(custom)", dict(off_params)))
    values = [v.strip() for v in args.levels.split(",")] if args.levels else list(preset.levels)
    values = [v for v in values if v]
    if not values:
        raise SystemExit("没有任何待测档位（--levels 为空且 preset 也没有档位）")
    param = args.effort_param or preset.effort_param
    for value in values:
        levels.append((f"{param}={value}", {param: value}))
    return levels


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="probe_model_reasoning.py",
        description=(
            "实测某供应商/模型的思考控制是否真的生效，输出 SUPPORTED / NOT-SUPPORTED / "
            "INCONCLUSIVE。密钥只从环境变量读，绝不接受命令行明文密钥。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  DEEPSEEK_API_KEY=... python scripts/probe_model_reasoning.py "
            "--provider deepseek --model deepseek-flash\n"
            "  python scripts/probe_model_reasoning.py --provider ollama --model qwen3.5:4b\n"
            "  python scripts/probe_model_reasoning.py --provider ollama --model qwen3.5:4b "
            "--also-native\n\n"
            "判定规则见 docs/DEV_RECORD.md"
        ),
    )
    parser.add_argument("--provider", required=True, choices=sorted(PROVIDERS))
    parser.add_argument("--model", required=True, help="模型名，如 deepseek-flash / qwen3.5:4b")
    parser.add_argument("--base-url", default=None, help="API 根地址（默认按 provider 预设）")
    parser.add_argument(
        "--key",
        dest="key_arg",
        default=None,
        metavar="KEY",
        help="仅用于报错：不接受命令行明文密钥，请改用环境变量 + --key-env",
    )
    parser.add_argument(
        "--key-env",
        default=None,
        metavar="NAME",
        help="密钥所在的环境变量名（默认按 provider 预设，如 DEEPSEEK_API_KEY）",
    )
    parser.add_argument("--levels", default=None, help="覆盖档位列表，逗号分隔，由低到高")
    parser.add_argument(
        "--effort-param", default=None, help="覆盖档位参数名（默认按 provider 预设）"
    )
    parser.add_argument("--off-json", default=None, help="覆盖关闭思考的参数（JSON 对象）")
    parser.add_argument("--no-off", action="store_true", help='跳过"关闭思考"对照组')
    parser.add_argument(
        "--trials", type=int, default=MIN_TRIALS, help="主问题每档调用次数（≥3 才可能判 SUPPORTED）"
    )
    parser.add_argument("--control-trials", type=int, default=1, help="对照题每档调用次数")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, help="必须 ≥2000")
    parser.add_argument("--timeout", type=float, default=180.0, help="单次调用超时秒数")
    parser.add_argument(
        "--answer-floor", type=int, default=DEFAULT_ANSWER_FLOOR, help="主问题答案字符数门槛"
    )
    parser.add_argument("--also-native", action="store_true", help="额外对照 Ollama 原生 /api/chat")
    parser.add_argument("--json", action="store_true", help="只输出机器可读 JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    out = Out(args.json)

    if args.key_arg is not None:
        out.fatal(
            "错误：不接受命令行明文密钥。密钥只从环境变量读取"
            "（默认 DEEPSEEK_API_KEY 等，可用 --key-env 指定变量名），"
            "例如：DEEPSEEK_API_KEY=... python scripts/probe_model_reasoning.py --provider deepseek ..."
        )
        return 2
    if args.max_tokens < DEFAULT_MAX_TOKENS:
        out.fatal(
            f"错误：--max-tokens 必须 ≥ {DEFAULT_MAX_TOKENS}"
            "（预算太小会让高档位思考被截断，第一版就是这么判错的）"
        )
        return 2
    if args.trials < 1 or args.control_trials < 1:
        out.fatal("错误：--trials / --control-trials 必须 ≥ 1")
        return 2

    preset = PROVIDERS[args.provider]
    base_url = args.base_url or preset.base_url
    url = chat_url(base_url)
    key = resolve_key(preset, args.key_env, out)
    levels = build_levels(preset, args)
    off_entry = next((e for e in levels if e[0] in {preset.off_label, "off(custom)"}), None)

    report = ProbeReport(
        provider=preset.name,
        model=args.model,
        endpoint=url,
        max_tokens=args.max_tokens,
        trials=args.trials,
        control_trials=args.control_trials,
    )
    if args.trials < MIN_TRIALS:
        report.notes.append(f"--trials={args.trials} < {MIN_TRIALS}，结论会被强制为 INCONCLUSIVE")

    out.line("probe_model_reasoning · 思考档位实测")
    out.line(f"  provider = {preset.name}   model = {args.model}")
    out.line(f"  endpoint = POST {url}")
    out.line(
        f"  max_tokens = {args.max_tokens}   trials = {args.trials}   "
        f"control_trials = {args.control_trials}   timeout = {args.timeout:.0f}s   "
        f"key_env = {'/'.join((args.key_env,) if args.key_env else preset.key_envs) or '(none)'}"
    )
    out.line(f"  levels = {', '.join(label for label, _ in levels)}")
    out.line()

    base_body: dict[str, Any] = {
        "model": args.model,
        "max_tokens": args.max_tokens,
        "messages": [{"role": "user", "content": MAIN_QUESTION}],
    }
    all_trials: list[Trial] = []
    for label, params in levels:
        out.line(f"[main] {label}  需长链推理的对照题")
        for index in range(1, args.trials + 1):
            trial = run_trial(
                url,
                base_body,
                params,
                label,
                index,
                "main",
                args.timeout,
                key,
                args.max_tokens,
                out,
            )
            all_trials.append(trial)
    control_body: dict[str, Any] = {
        "model": args.model,
        "max_tokens": args.max_tokens,
        "messages": [{"role": "user", "content": CONTROL_QUESTION}],
    }
    out.line()
    for label, params in levels:
        out.line(f"[control] {label}  简单题（不应需要思考）")
        for index in range(1, args.control_trials + 1):
            trial = run_trial(
                url,
                control_body,
                params,
                label,
                index,
                "control",
                args.timeout,
                key,
                args.max_tokens,
                out,
            )
            all_trials.append(trial)
    out.line()

    for kind, bucket in (("main", "main_stats"), ("control", "control_stats")):
        for label, _ in levels:
            subset = [t for t in all_trials if t.kind == kind and t.label == label]
            getattr(report, bucket).append(summarize(label, kind, subset, args.answer_floor))

    out.line(f"--- 主问题结果（{args.trials} 次/档，值为 均值/极差）---")
    print_table(out, report.main_stats)
    out.line()
    out.line(f"--- 对照题结果（{args.control_trials} 次/档）---")
    print_table(out, report.control_stats)
    out.line()

    off_stat = None
    if off_entry is not None:
        off_stat = next((s for s in report.main_stats if s.label == off_entry[0]), None)
    level_stats = [s for s in report.main_stats if off_stat is None or s.label != off_stat.label]
    rules = [
        rule_off(off_stat),
        rule_mono(level_stats, args.trials),
        rule_budget(report.main_stats + report.control_stats, args.max_tokens, args.answer_floor),
    ]
    verdict, scope = decide_verdict(rules, args.trials, report.notes)
    report.rules = rules
    report.verdict = verdict
    report.scope = scope
    if any(s.n_err for s in report.main_stats):
        report.notes.append("存在 ERROR 档位/样本，见上表 n 列")
    if any(s.truncated for s in report.main_stats):
        report.notes.append(
            f"高档位出现 completion 顶满 max_tokens={args.max_tokens}，长度可比性受限，"
            "且用户会看到空答案 → 按档位预留思考预算"
        )

    out.line("--- 判定规则 ---")
    for rule in rules:
        out.line(f"  {rule.name:<12} {rule.status:<13} {rule.detail}")
    out.line()
    out.line(f"VERDICT: {verdict}   scope = {scope or '-'}")
    for note in report.notes:
        out.line(f"  - {note}")

    if args.also_native:
        if preset.name != "ollama":
            report.notes.append("--also-native 仅支持 --provider ollama，已跳过原生端点对照")
            out.line()
            out.line("[native] 仅 --provider ollama 支持 --also-native，已跳过")
        else:
            out.line()
            out.line(f"--- 原生端点对照 {native_root(base_url)}/api/chat（不参与判定）---")
            report.native = native_probe(base_url, args.model, args.timeout, out)
            out.line(
                "  说明：原生端点生效不代表产品走的 OpenAI 兼容端点生效，"
                "判定仍以上表（兼容端点）为准"
            )

    ok_calls = sum(1 for t in all_trials if t.ok)
    if ok_calls == 0:
        out.fatal("错误：所有调用都失败（端点不可达或认证失败），无法给出结论。")
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "provider": report.provider,
                    "model": report.model,
                    "endpoint": report.endpoint,
                    "max_tokens": report.max_tokens,
                    "trials": report.trials,
                    "control_trials": report.control_trials,
                    "levels": [s.__dict__ for s in report.main_stats],
                    "control_levels": [s.__dict__ for s in report.control_stats],
                    "rules": [r.__dict__ for r in report.rules],
                    "verdict": report.verdict,
                    "scope": report.scope,
                    "notes": report.notes,
                    "native": report.native,
                    "calls": {"ok": ok_calls, "total": len(all_trials)},
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

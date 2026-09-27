#!/usr/bin/env python
"""多会话 + 压缩改造的**端到端验收**（独立于单元测试，走真实 `JsonlBackend`）。

为什么单独存在：`tests/test_chat_session.py` / `test_jsonl_backend.py` 覆盖的是单元级
断言；本脚本按用户操作路径把整套流程串起来跑（create → list → switch → rename →
delete → 重启 → 迁移 → 压缩），作为"契约 v1 是否真的连通"的独立证据。
模型调用全部走进程内 stub（真实后端 + 假模型），**不发网络请求、不需要密钥**。

对应任务：`.agent-bus/tasks/codex-sessions-verify.json`（原派 codex，其两轮均因
长时间探索 + 远端 compaction 崩溃而未落盘——本脚本由主控接手实现，2026-09-27）。

用法::

    python scripts/verify_sessions.py          # 人类可读
    python scripts/verify_sessions.py --json   # 机器可读

退出码：0 = 全部用例通过；1 = 有失败；2 = 环境不可用（后端方法缺失等）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ai_pr_review.backend.jsonl_server as server_module  # noqa: E402
from ai_pr_review.backend.jsonl_server import JsonlBackend  # noqa: E402
from ai_pr_review.services.model_providers.base import ProviderResponse  # noqa: E402

ANSWER = "stub 回答：先看 src/app.py 的改动。"


class _StubProvider:
    """真实后端 + 假模型：不联网，固定回复（含一个文件路径，供压缩文件清单断言）。"""

    async def stream_chat(self, messages, on_delta, **kwargs):  # noqa: ANN001
        await on_delta(ANSWER)
        return ProviderResponse(text=ANSWER)

    async def chat(self, messages, **kwargs):  # noqa: ANN001 - 压缩摘要路径用
        return ProviderResponse(text="（stub 摘要）早前讨论了 src/app.py 的改动。")


class Result:
    def __init__(self, name: str) -> None:
        self.name = name
        self.checks: list[tuple[bool, str]] = []

    def check(self, ok: bool, detail: str) -> None:
        self.checks.append((bool(ok), detail))

    @property
    def passed(self) -> bool:
        return all(ok for ok, _ in self.checks)

    def to_json(self) -> dict[str, Any]:
        return {
            "case": self.name,
            "passed": self.passed,
            "checks": [{"ok": ok, "detail": detail} for ok, detail in self.checks],
        }


async def call(backend: JsonlBackend, method: str, **params: Any) -> dict[str, Any]:
    """调一个 JSONL 方法，返回最后一个 reply（result 或 error）。"""
    reply = await backend.handle({"id": method, "method": method, "params": params})
    return reply[-1] if reply else {}


def chat_ready(backend: JsonlBackend) -> JsonlBackend:
    """`_chat` 在拿到 stub provider **之前**会校验非本地槽的 API Key——
    这里补一个 dummy key（stub provider 不会真的用它；对照 `tests/test_jsonl_backend.py`
    的 `_chat_ready_backend`）。"""
    backend.config.provider.api_key = "verify-sessions-key"
    backend.config.ai_client.api_key = "verify-sessions-key"
    return backend


def start_backend(config_path: Path) -> JsonlBackend:
    """构造后端并**模拟 `serve()` 的启动动作**：迁移旧 `chat_session.json`。

    （真实入口是 `serve()`（jsonl_server.py:4859），它构造完 backend 就调
    `session_store.migrate_legacy()`；验收脚本直连后端，需要把这步补上，
    否则 legacy 迁移用例会假失败。）
    """
    backend = chat_ready(JsonlBackend(config_path))
    backend.session_store.migrate_legacy()
    return backend


async def chat(backend: JsonlBackend, session_id: str, text: str) -> dict[str, Any]:
    return await call(backend, "chat.send", session_id=session_id, text=text)


async def compact(backend: JsonlBackend, session_id: str, *args: str) -> dict[str, Any]:
    """`/compact` 是命令（`command.execute` name=compact），不是顶层方法。"""
    return await call(
        backend, "command.execute", name="compact", args=list(args), session_id=session_id
    )


def _install_stub() -> Callable[[], None]:
    """把 `create_model_provider` 换成本地 stub，返回恢复函数。"""
    original = server_module.create_model_provider
    server_module.create_model_provider = lambda config: _StubProvider()  # noqa: ARG005

    def restore() -> None:
        server_module.create_model_provider = original

    return restore


# ---------------------------------------------------------------------------
# 用例 1：会话生命周期
# ---------------------------------------------------------------------------


async def case_lifecycle(tmp: Path) -> Result:
    r = Result("1 会话生命周期（create/list/switch/rename/delete）")
    backend = start_backend(tmp / "config.json")

    created = []
    for index in range(3):
        reply = await call(backend, "session.create")
        if not reply.get("ok"):
            r.check(False, f"session.create #{index + 1} 失败: {reply.get('error')}")
            return r
        sid = reply["result"]["session"]["id"]
        created.append(sid)
        await chat(backend, sid, f"第 {index} 个会话的问题")

    listing = await call(backend, "session.list")
    sessions = listing.get("result", {}).get("sessions", [])
    r.check(len(sessions) == 3, f"list 返回 3 个会话（实际 {len(sessions)}）")
    r.check(
        listing.get("result", {}).get("current") == created[-1],
        "current 指向最后创建/激活的会话",
    )
    r.check(
        all(s.get("message_count", 0) >= 1 for s in sessions),
        "每个会话记录了消息数",
    )
    updated = [s.get("updated_at", "") for s in sessions]
    r.check(updated == sorted(updated, reverse=True), "按 updated_at 降序")

    # switch 回第 1 个：消息与切走前一致
    switched = await call(backend, "session.switch", session_id=created[0])
    messages = switched.get("result", {}).get("messages", [])
    r.check(
        any("第 0 个会话的问题" in str(m.get("content", "")) for m in messages),
        "切换后取回第 1 个会话的消息",
    )

    # rename
    renamed = await call(backend, "session.rename", session_id=created[0], title="改过的标题")
    r.check(renamed.get("result", {}).get("title") == "改过的标题", "rename 返回新标题")
    after_rename = await call(backend, "session.list")
    titles = {s["id"]: s["title"] for s in after_rename.get("result", {}).get("sessions", [])}
    r.check(titles.get(created[0]) == "改过的标题", "list 反映新标题")

    # delete 非当前：next 不变
    deleted_other = await call(backend, "session.delete", session_id=created[1])
    r.check(deleted_other.get("result", {}).get("deleted") == created[1], "delete 返回被删 id")
    r.check(
        deleted_other.get("result", {}).get("next") == created[0],
        "删除非当前会话，next 保持当前会话",
    )

    # delete 当前：自动切到最近一个
    deleted_current = await call(backend, "session.delete", session_id=created[0])
    r.check(
        deleted_current.get("result", {}).get("next") == created[2],
        "删除当前会话后自动切到最近的一个",
    )
    final = await call(backend, "session.list")
    r.check(len(final.get("result", {}).get("sessions", [])) == 1, "删除后只剩 1 个会话")

    # 再 create：id 不与历史冲突
    fresh = await call(backend, "session.create")
    fresh_id = fresh.get("result", {}).get("session", {}).get("id")
    r.check(fresh_id not in created, f"新会话 id 不与历史冲突（{fresh_id}）")
    return r


# ---------------------------------------------------------------------------
# 用例 2：持久化与迁移
# ---------------------------------------------------------------------------


async def case_migration(tmp: Path) -> Result:
    r = Result("2 旧单会话数据迁移为 legacy + 重启保持")
    legacy_messages = [
        {"role": "user", "content": "老版本里问过的问题", "timestamp": "2026-01-01T00:00:00+00:00"},
        {"role": "assistant", "content": "老版本里的回答", "timestamp": "2026-01-01T00:00:01+00:00"},
    ]
    (tmp / "chat_session.json").write_text(
        json.dumps(legacy_messages, ensure_ascii=False), encoding="utf-8"
    )

    backend = start_backend(tmp / "config.json")
    listing = await call(backend, "session.list")
    sessions = listing.get("result", {}).get("sessions", [])
    r.check(len(sessions) >= 1, "启动后 list 至少含迁移进来的会话")
    legacy = sessions[0] if sessions else {}
    r.check(legacy.get("title") == "legacy", f"迁移会话标题为 legacy（实际 {legacy.get('title')!r}）")
    r.check(legacy.get("message_count") == 2, "迁移会话保留 2 条消息")

    # 重启：会话与 current 保持
    backend2 = start_backend(tmp / "config.json")
    listing2 = await call(backend2, "session.list")
    sessions2 = listing2.get("result", {}).get("sessions", [])
    r.check(
        [s["id"] for s in sessions2] == [s["id"] for s in sessions],
        "重启后会话集合保持一致",
    )
    switched = await call(backend2, "session.switch", session_id=sessions[0]["id"])
    messages = switched.get("result", {}).get("messages", [])
    r.check(
        [m.get("content") for m in messages] == [m["content"] for m in legacy_messages],
        "重启后能取回 legacy 会话的完整消息",
    )
    return r


# ---------------------------------------------------------------------------
# 用例 3：索引自愈
# ---------------------------------------------------------------------------


async def case_self_heal(tmp: Path) -> Result:
    r = Result("3 索引自愈（删 index.json / 删会话文件）")
    backend = start_backend(tmp / "config.json")
    first = await call(backend, "session.create")
    sid = first.get("result", {}).get("session", {}).get("id")
    await chat(backend, sid, "自愈用例的消息")

    sessions_dir = tmp / "sessions"
    index_path = sessions_dir / "index.json"
    r.check(index_path.exists(), "索引文件已生成")

    # 删索引 → 重启 → 按目录扫描修复
    index_path.unlink()
    backend2 = start_backend(tmp / "config.json")
    listing = await call(backend2, "session.list")
    ids = [s["id"] for s in listing.get("result", {}).get("sessions", [])]
    r.check(sid in ids, "删掉 index.json 后重启仍能列出会话（扫描修复）")

    # 删会话文件（索引仍引用）→ 重启 → 不崩、该条被剔除
    (sessions_dir / f"{sid}.json").unlink()
    backend3 = start_backend(tmp / "config.json")
    listing3 = await call(backend3, "session.list")
    ids3 = [s["id"] for s in listing3.get("result", {}).get("sessions", [])]
    r.check(sid not in ids3, "会话文件缺失时该条被剔除（不崩）")
    return r


# ---------------------------------------------------------------------------
# 用例 4：压缩边界
# ---------------------------------------------------------------------------


async def case_compaction(tmp: Path) -> Result:
    r = Result("4 压缩（token×整轮 / XML / 文件清单 / 至少 1 轮）")
    backend = start_backend(tmp / "config.json")
    created = await call(backend, "session.create")
    sid = created.get("result", {}).get("session", {}).get("id")

    # 预算设到范围下限（4000）以确保**真的触发压缩**：默认 40000 下，本用例这种
    # 规格的会话会"装得下 → 不调模型"（产品的正确优化），那样摘要断言就是假失败。
    backend.config.preferences.compaction_tail_tokens = 4000
    long_text = "请分析 src/app.py 的改动。" + "细节" * 1500
    for index in range(6):
        await chat(backend, sid, f"{long_text}（第 {index} 轮）")

    compacted = await compact(backend, sid)
    result = compacted.get("result", {})
    r.check(compacted.get("ok") is True, f"compact 成功（{compacted.get('error')}）")
    r.check(result.get("kind") == "compact", "返回 kind=compact")
    kept_turns = result.get("kept_turns")
    r.check(isinstance(kept_turns, int) and kept_turns >= 1, f"至少保留 1 轮（{kept_turns}）")
    replaced = result.get("replaced_messages")
    r.check(isinstance(replaced, int) and replaced >= 0, "返回 replaced_messages")

    summary_reply = await call(backend, "session.get", session_id=sid)
    messages = summary_reply.get("result", {}).get("messages", [])
    r.check(len(messages) >= 1, "压缩后会话仍有消息")
    first = str(messages[0].get("content", "")) if messages else ""
    r.check("<conversation-summary" in first, "摘要使用 XML 结构（<conversation-summary>）")
    r.check("trigger=" in first, "摘要含 trigger 属性")
    r.check("已压缩对话涉及的文件" in first, "摘要含文件清单段落")
    r.check("src/app.py" in first, "文件清单包含讨论过的路径")
    if messages and isinstance(messages[-1], dict):
        tail = [m for m in messages[1:] if m.get("role") == "user"]
        r.check(all("请分析" in str(m.get("content", "")) for m in tail), "保留段是完整轮（user 开头）")

    # 极小预算：至少保 1 轮（预算已是下限；此处复核二次压缩仍成立）
    tiny = await compact(backend, sid)
    r.check(tiny.get("ok") is True, "极小 tail 预算下 compact 仍成功（至少保 1 轮）")
    tiny_kept = tiny.get("result", {}).get("kept_turns")
    r.check(isinstance(tiny_kept, int) and tiny_kept >= 1, f"极小预算至少保留 1 轮（{tiny_kept}）")
    return r


# ---------------------------------------------------------------------------
# 用例 5：压力分级
# ---------------------------------------------------------------------------


async def case_pressure(tmp: Path) -> Result:
    r = Result("5 pressure 五档（low/medium/high/critical/null）")
    backend = start_backend(tmp / "config.json")

    def pressure_for(percent: float) -> str | None:
        # 直接查询分级函数：构造 used_percent 对应的 payload 不现实（依赖真实 token），
        # 因此调用内部 helper（它只做阈值映射，是纯函数）。
        return backend._pressure_level(percent)  # noqa: SLF001 - 验收脚本直达纯函数

    r.check(pressure_for(10) == "low", "10% → low")
    r.check(pressure_for(65) == "medium", "65% → medium")
    r.check(pressure_for(85) == "high", "85% → high")
    r.check(pressure_for(120) == "critical", "120% → critical")
    r.check(pressure_for(None) is None, "None → null（算不出与 low 是两件事）")

    # 端到端：一轮 chat 后 finished.context 含第七键
    created = await call(backend, "session.create")
    sid = created.get("result", {}).get("session", {}).get("id")
    events: list[dict[str, Any]] = []
    backend.event_sink = events.append
    await chat(backend, sid, "压力键端到端检查")
    finished = next((e for e in events if e.get("event") == "assistant.finished"), None)
    context = (finished or {}).get("context") or {}
    r.check("pressure" in context, "assistant.finished.context 含 pressure 键")
    return r


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


async def run_all() -> list[Result]:
    restore = _install_stub()
    try:
        results: list[Result] = []
        with tempfile.TemporaryDirectory(prefix="verify-sessions-") as tmpdir:
            base = Path(tmpdir)
            for index, case in enumerate(
                (case_lifecycle, case_migration, case_self_heal, case_compaction, case_pressure),
                start=1,
            ):
                case_dir = base / f"case{index}"
                case_dir.mkdir(parents=True, exist_ok=True)
                try:
                    results.append(await case(case_dir))
                except AttributeError as exc:
                    res = Result(case.__name__)
                    res.check(False, f"NOT IMPLEMENTED: {exc}")
                    results.append(res)
                except Exception as exc:  # noqa: BLE001 - 验收脚本要如实报告任何异常
                    res = Result(case.__name__)
                    res.check(False, f"{exc.__class__.__name__}: {exc}")
                    results.append(res)
        return results
    finally:
        restore()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="只输出机器可读 JSON")
    args = parser.parse_args(argv)

    results = asyncio.run(run_all())
    passed = sum(1 for item in results if item.passed)
    payload = {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "cases": [item.to_json() for item in results],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for item in results:
            mark = "PASS" if item.passed else "FAIL"
            print(f"[{mark}] {item.name}")
            for ok, detail in item.checks:
                print(f"    {'ok ' if ok else 'ERR'} {detail}")
        print(f"\n{passed}/{len(results)} cases passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""多会话存储（契约 v1 §A）的单元测试：CRUD / 迁移 / 索引自愈 / 标题生成。

后端协议层（`session.list` 等五个方法）在 tests/test_jsonl_backend.py；这里只测
`ChatSessionStore` 本身——它是真相，协议层只是它的投影，两边分开测才能一眼看出
"是存储坏了还是接线坏了"。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ai_pr_review.chat_session import (
    LEGACY_SESSION_TITLE,
    SESSION_TITLE_LIMIT,
    ChatSessionStore,
    chat_session_path,
    default_session_title,
    session_file_path,
    sessions_index_path,
)


def _store(tmp_path: Path) -> ChatSessionStore:
    return ChatSessionStore(tmp_path / "config.json")


def _messages(*texts: str) -> list[dict[str, Any]]:
    """一轮 = user + assistant；`texts` 按对话依次生成（奇数条时最后一条是 user）。"""
    payload: list[dict[str, Any]] = []
    for index, text in enumerate(texts):
        payload.append(
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "content": text,
                "timestamp": f"2026-01-01T00:00:{index:02d}+00:00",
            }
        )
    return payload


# ---------------------------------------------------------------------------
# 基本 CRUD
# ---------------------------------------------------------------------------


def test_create_switch_rename_delete_round_trip(tmp_path: Path) -> None:
    """五个方法的存储侧语义：新建即切换、重命名覆盖标题、删除返回接任者。"""
    store = _store(tmp_path)
    first = store.create()
    assert first["id"] == "s1"
    assert store.current_id() == "s1"

    second = store.create()
    assert second["id"] == "s2", "id 必须单调递增（s1、s2…），不暴露 UUID"
    assert store.current_id() == "s2"

    # 切换：current 指向目标，消息按会话各归各
    store.save("s1", _messages("第一个会话的问题", "第一个会话的回答"))
    store.switch("s1")
    assert store.current_id() == "s1"
    assert store.get("s1")["messages"][0]["content"] == "第一个会话的问题"
    assert len(store.get("s2")["messages"]) == 0

    renamed = store.rename("s1", "改过的标题")
    assert renamed == {"id": "s1", "title": "改过的标题"}
    assert store.get("s1")["title"] == "改过的标题"
    assert [record["title"] for record in store.records() if record["id"] == "s1"] == ["改过的标题"]

    deleted = store.delete("s1")
    assert deleted == ("s1", "s2"), "删当前会话 → 自动切到最近一个（契约 v1）"
    assert not session_file_path(tmp_path / "config.json", "s1").exists()
    assert store.get("s1") is None
    assert store.current_id() == "s2"
    assert store.delete("s1") is None, "删不存在的会话返回 None（协议层翻成 not_found）"


def test_delete_last_session_leaves_no_current(tmp_path: Path) -> None:
    """删到一条不剩：`current` 置空而不是留下悬空 id（否则 chat.send 全是 not_found）。"""
    store = _store(tmp_path)
    store.create()
    assert store.delete("s1") == ("s1", None)
    assert store.current_id() == ""
    assert store.records() == []


def test_records_are_sorted_by_updated_at_descending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """契约 v1：列表按 `updated_at` 降序；同一秒再按 id 序号降序（新的排前面）。

    时钟是**手工**的：真实时间戳只到秒，同一秒内建的会话排不出先后，而"谁在前"正是
    这条契约要钉住的东西——用真实时钟测它等于在测运气。
    """
    import ai_pr_review.chat_session as module

    clock = {"now": "2026-01-01T00:00:01+00:00"}
    monkeypatch.setattr(module, "_session_now", lambda: clock["now"])
    store = _store(tmp_path)

    store.create()
    assert [record["id"] for record in store.records()] == ["s1"]
    clock["now"] = "2026-01-01T00:00:02+00:00"
    store.create()
    assert [record["id"] for record in store.records()] == ["s2", "s1"], "新的在前"

    clock["now"] = "2026-01-01T00:00:03+00:00"
    store.save("s1", _messages("又聊了一句"))
    assert [record["id"] for record in store.records()] == ["s1", "s2"], "刚写过的会话排最前"


def test_same_second_sessions_fall_back_to_the_id_order(tmp_path: Path) -> None:
    """同一秒内建的多个会话：按 id 序号降序（`s3, s2, s1`），排序必须**稳定**。"""
    store = _store(tmp_path)
    for _ in range(3):
        store.create()
    assert [record["id"] for record in store.records()] == ["s3", "s2", "s1"]


def test_save_keeps_the_user_title_and_the_message_count_fresh(tmp_path: Path) -> None:
    """落盘之后索引必须立刻反映**文件**里的新标题/新消息数。

    这是一条回归用例：索引是缓存，`_load_records` 只对"索引里没有的文件"做扫描——
    一条已在索引里的会话改了标题之后，不重读就还是旧值，`session.list` 会永远显示旧标题。
    """
    store = _store(tmp_path)
    store.create()
    store.save("s1", _messages("第一条用户消息"))
    record = next(item for item in store.records() if item["id"] == "s1")
    assert record["title"] == "第一条用户消息", "空标题的会话在第一条用户消息落盘后要补上标题"
    assert record["message_count"] == 1

    store.rename("s1", "用户改的标题")
    store.save("s1", _messages("后来又说了一句", "回答"))
    record = next(item for item in store.records() if item["id"] == "s1")
    assert record["title"] == "用户改的标题", "用户改过的标题不被自动标题覆盖"
    assert record["message_count"] == 2
    assert store.get("s1")["title_source"] == "user"


# ---------------------------------------------------------------------------
# 标题生成
# ---------------------------------------------------------------------------


def test_default_title_is_the_first_user_message_truncated_to_40() -> None:
    messages = _messages("  多行\n标题\n  也要折叠 " + "长" * 60, "回答")
    title = default_session_title(messages)
    assert title == ("多行 标题 也要折叠 " + "长" * 60)[:SESSION_TITLE_LIMIT]
    assert len(title) == SESSION_TITLE_LIMIT
    assert "\n" not in title, "换行会撑破列表行"


def test_default_title_ignores_assistant_and_empty_messages() -> None:
    assert default_session_title([{"role": "assistant", "content": "我先说话"}]) == ""
    assert default_session_title([{"role": "user", "content": "   "}]) == ""
    assert default_session_title([]) == ""


# ---------------------------------------------------------------------------
# 索引自愈（契约 v1：索引写失败时下轮按目录扫描自愈）
# ---------------------------------------------------------------------------


def test_index_missing_is_rebuilt_from_the_sessions_directory(tmp_path: Path) -> None:
    """自愈分支 1：索引没了/坏了 → 全量扫描重建。"""
    store = _store(tmp_path)
    store.create()
    store.save("s1", _messages("存过的话"))
    sessions_index_path(tmp_path / "config.json").unlink()

    records = store.records()
    assert [record["id"] for record in records] == ["s1"]
    assert records[0]["title"] == "存过的话"
    assert sessions_index_path(tmp_path / "config.json").exists(), "扫描之后要把索引写回去"
    assert store.current_id() == "s1", "索引没了也要能挑出当前会话"


def test_index_lagging_behind_the_directory_is_repaired(tmp_path: Path) -> None:
    """自愈分支 2：目录里有、索引里没有（索引写失败/被外部改过）→ 扫描补进来。"""
    store = _store(tmp_path)
    store.create()
    index = json.loads(sessions_index_path(tmp_path / "config.json").read_text(encoding="utf-8"))
    index["sessions"] = []
    sessions_index_path(tmp_path / "config.json").write_text(
        json.dumps(index, ensure_ascii=False), encoding="utf-8"
    )

    records = store.records()
    assert [record["id"] for record in records] == ["s1"], "落单的会话文件必须被扫回来"
    repaired = json.loads(sessions_index_path(tmp_path / "config.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in repaired["sessions"]] == ["s1"]


def test_index_pointing_at_a_missing_file_drops_it_and_fixes_current(tmp_path: Path) -> None:
    """自愈分支 3：索引超前（文件被手删了）→ 剔除该条，`current` 不留悬空 id。"""
    store = _store(tmp_path)
    store.create()
    store.create()
    store.switch("s2")
    session_file_path(tmp_path / "config.json", "s2").unlink()

    records = store.records()
    assert [record["id"] for record in records] == ["s1"]
    assert store.current_id() == "s1", "被删掉的会话不能继续当 current"


def test_corrupt_session_file_never_breaks_the_other_sessions(tmp_path: Path) -> None:
    """坏文件读路径绝不抛：打开它得到 `None`，其余会话照常可用。

    注意索引**不会**因此剔除它：验证"索引里的每条都还能解析"要读遍所有会话文件，
    而索引存在的意义正是不读它们（见 `_load_records`）。坏会话在 `session.switch`
    时会被发现（not_found），删掉索引后重建才会从列表里消失——这是已知的取舍。
    """
    store = _store(tmp_path)
    store.create()
    store.create()
    session_file_path(tmp_path / "config.json", "s2").write_text("{ 不是 JSON", encoding="utf-8")

    assert store.get("s2") is None
    assert store.get("s1") is not None
    assert store.current_id() == "s2"  # 索引里的 current 不变（那是"用户的意图"，不是文件状态）
    assert [record["id"] for record in store.records()] == ["s2", "s1"]  # 同一秒 → id 序号降序


def test_corrupt_file_not_in_the_index_is_dropped(tmp_path: Path) -> None:
    """扫描路径（索引里没有的落单文件）读不动 → 直接剔除，列表里看不到。"""
    store = _store(tmp_path)
    store.create()
    sessions_index_path(tmp_path / "config.json").unlink()
    session_file_path(tmp_path / "config.json", "s9").write_text("{ 坏文件", encoding="utf-8")

    assert [record["id"] for record in store.records()] == ["s1"]


def test_index_write_failure_does_not_lose_the_session_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """索引写失败只告警：会话文件已经落盘，下一轮扫描会把它补进索引。"""
    store = _store(tmp_path)
    store.create()
    import ai_pr_review.chat_session as module

    real_write = module._atomic_write_json

    def explode_for_the_index(path: Path, payload: Any) -> None:
        # 只让**索引**写失败：会话文件那条路径必须照常成功（那才是"数据不丢"的关键）。
        if path.name == "index.json":
            raise OSError("disk full")
        real_write(path, payload)

    monkeypatch.setattr(module, "_atomic_write_json", explode_for_the_index)
    assert store.save("s1", _messages("照常落盘")) is not None, "索引失败不该让保存失败"
    monkeypatch.undo()
    assert store.get("s1")["messages"][0]["content"] == "照常落盘"
    assert [record["id"] for record in store.records()] == ["s1"]


def test_atomic_write_leaves_no_temporary_files(tmp_path: Path) -> None:
    """tempfile + `os.replace`：目录里不能留下半截临时文件（扫描会把它们当会话）。"""
    store = _store(tmp_path)
    store.create()
    store.save("s1", _messages("写完就换名"))
    leftovers = [path.name for path in store.directory.iterdir() if path.suffix == ".tmp"]
    assert leftovers == []


def test_session_file_path_rejects_traversal_ids(tmp_path: Path) -> None:
    """id 会被拼进文件名：手改过的 index.json 不能把写入引到目录外。"""
    for bad in ("../escape", "a/b", "s1.json", "", "会话"):
        with pytest.raises(ValueError):
            session_file_path(tmp_path / "config.json", bad)


# ---------------------------------------------------------------------------
# 迁移（旧 chat_session.json → legacy 会话）
# ---------------------------------------------------------------------------


def test_migrate_legacy_imports_the_old_file_once(tmp_path: Path) -> None:
    """旧文件迁移为 legacy 会话：只读旧文件、只导一次、之后再启动不重复导入。"""
    legacy_path = chat_session_path(tmp_path / "config.json")
    legacy_path.write_text(
        json.dumps(_messages("迁移前的第一句", "迁移前的回答"), ensure_ascii=False),
        encoding="utf-8",
    )
    store = _store(tmp_path)
    created = store.migrate_legacy()
    assert created is not None
    assert created["id"] == "s1"
    assert created["title"] == LEGACY_SESSION_TITLE
    assert created["source"] == "legacy"
    assert store.current_id() == "s1", "第一次迁移要把 legacy 设为当前会话"
    assert len(store.get("s1")["messages"]) == 2

    # 旧文件是 CLI 的存储：迁移只读，绝不改它、更不删它
    assert legacy_path.exists()
    assert json.loads(legacy_path.read_text(encoding="utf-8"))[0]["content"] == "迁移前的第一句"

    assert store.migrate_legacy() is None, "第二次启动不该再长出一个 legacy 会话"
    assert len([record for record in store.records() if record["source"] == "legacy"]) == 1


def test_migrate_legacy_skips_corrupt_file_without_blocking_startup(tmp_path: Path) -> None:
    """迁移失败只告警：坏文件不该让 TUI 起不来（方案 §A6）。"""
    chat_session_path(tmp_path / "config.json").write_text("{ 坏文件", encoding="utf-8")
    store = _store(tmp_path)
    assert store.migrate_legacy() is None
    assert store.records() == []


def test_migrate_legacy_skips_empty_history(tmp_path: Path) -> None:
    """空历史不值得造一个空会话（用户会看到一个永远没内容的 legacy）。"""
    chat_session_path(tmp_path / "config.json").write_text("[]", encoding="utf-8")
    store = _store(tmp_path)
    assert store.migrate_legacy() is None
    assert store.records() == []


def test_migrate_legacy_does_not_steal_the_current_session(tmp_path: Path) -> None:
    """已有当前会话时，迁移只把 legacy 加进列表，不把用户正在聊的会话顶掉。"""
    store = _store(tmp_path)
    store.create()
    store.save("s1", _messages("正在聊的会话"))
    chat_session_path(tmp_path / "config.json").write_text(
        json.dumps(_messages("很久以前的旧文件"), ensure_ascii=False), encoding="utf-8"
    )
    created = store.migrate_legacy()
    assert created is not None and created["id"] == "s2"
    assert store.current_id() == "s1", "迁移不该改变当前会话"


def test_delete_then_restart_does_not_resurrect_the_legacy_session(tmp_path: Path) -> None:
    """删掉 legacy 之后再启动：不能又长回来（`legacy_imported` 标记的用处）。"""
    chat_session_path(tmp_path / "config.json").write_text(
        json.dumps(_messages("旧文件的话"), ensure_ascii=False), encoding="utf-8"
    )
    store = _store(tmp_path)
    store.migrate_legacy()
    assert store.delete("s1") == ("s1", None)

    assert _store(tmp_path).migrate_legacy() is None
    assert _store(tmp_path).records() == []

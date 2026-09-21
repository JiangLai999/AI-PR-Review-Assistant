"""跨文件接口影响分析测试。"""

from __future__ import annotations

from ai_pr_review.models.pr_data import FileDiff, FileStatus
from ai_pr_review.services.analyzers.cross_file_interface import (
    CrossFileInterfaceAnalyzer,
    InterfaceImpact,
)
from ai_pr_review.services.analyzers.symbol_index import SymbolIndex
from ai_pr_review.services.context_builder import ContextBuilder

SERVICE_BEFORE = """def fetch_user(user_id):
    return {"id": user_id}
"""

SERVICE_AFTER = """def fetch_user(user_id, include_roles=False):
    return {"id": user_id}
"""

SERVICE_ASYNC = """async def fetch_user(user_id):
    return {"id": user_id}
"""

SERVICE_SAME = """def fetch_user(user_id):
    return {"id": user_id, "name": "x"}
"""

CALLER = """from service import fetch_user


def handler(request):
    return fetch_user(request.user_id)
"""

CALLER_UNRELATED = """def handler(request):
    return request.body
"""


def build(filename: str, content: str):
    lines = content.splitlines()
    patch = f"@@ -0,0 +1,{len(lines)} @@\n" + "".join(f"+{line}\n" for line in lines)
    file_diff = FileDiff(
        filename=filename,
        status=FileStatus.MODIFIED,
        additions=len(lines),
        changes=len(lines),
        patch=patch,
    )
    return file_diff, ContextBuilder().build_context(filename, patch, content)


def signature_map_for(contexts) -> dict:
    return SymbolIndex(contexts).signature_map()


class TestSymbolIndex:
    def test_indexes_function_signatures(self):
        contexts = [build("src/service.py", SERVICE_AFTER)]

        definitions = SymbolIndex(contexts).definitions()

        assert [d.name for d in definitions] == ["fetch_user"]
        assert definitions[0].signature() == "fetch_user(user_id, include_roles)"

    def test_indexes_classes_with_bases_and_methods(self):
        source = "class Repo(Base):\n    def get(self, key):\n        return key\n"
        contexts = [build("src/repo.py", source)]

        definitions = {d.name: d for d in SymbolIndex(contexts).definitions()}

        assert definitions["Repo"].kind == "class"
        assert definitions["Repo"].signature() == "Repo(Base)"
        assert definitions["get"].kind == "method"

    def test_marks_async_functions(self):
        contexts = [build("src/service.py", SERVICE_ASYNC)]

        definition = SymbolIndex(contexts).definitions()[0]

        assert definition.is_async is True
        assert definition.signature().startswith("async fetch_user")

    def test_detects_cross_file_references(self):
        contexts = [build("src/service.py", SERVICE_AFTER), build("src/handler.py", CALLER)]

        references = SymbolIndex(contexts).cross_file_references()

        assert any(
            r.symbol == "fetch_user" and r.referencing_file == "src/handler.py" for r in references
        )

    def test_import_line_is_not_counted_as_reference(self):
        contexts = [build("src/service.py", SERVICE_AFTER), build("src/handler.py", CALLER)]

        references = SymbolIndex(contexts).cross_file_references()

        # CALLER 的第 1 行是 import，不应被视为调用点；第 5 行才是真实调用。
        assert [r.line for r in references if r.symbol == "fetch_user"] == [5]

    def test_no_reference_when_caller_is_unrelated(self):
        contexts = [
            build("src/service.py", SERVICE_AFTER),
            build("src/handler.py", CALLER_UNRELATED),
        ]

        assert SymbolIndex(contexts).cross_file_references() == []


class TestInterfaceImpact:
    def test_reports_breaking_parameter_change(self):
        contexts = [build("src/service.py", SERVICE_AFTER), build("src/handler.py", CALLER)]
        base = signature_map_for([build("src/service.py", SERVICE_BEFORE)])

        impacts = CrossFileInterfaceAnalyzer().analyze(contexts, base_signatures=base)

        assert len(impacts) == 1
        impact = impacts[0]
        assert impact.change.change == "parameters_changed"
        assert impact.change.symbol == "fetch_user"
        assert impact.affected_files == ["src/handler.py"]
        assert impact.is_breaking is True

    def test_reports_async_change(self):
        contexts = [build("src/service.py", SERVICE_ASYNC), build("src/handler.py", CALLER)]
        base = signature_map_for([build("src/service.py", SERVICE_BEFORE)])

        impacts = CrossFileInterfaceAnalyzer().analyze(contexts, base_signatures=base)

        assert impacts[0].change.change == "became_async"

    def test_no_impact_when_signature_is_unchanged(self):
        contexts = [build("src/service.py", SERVICE_SAME), build("src/handler.py", CALLER)]
        base = signature_map_for([build("src/service.py", SERVICE_BEFORE)])

        assert CrossFileInterfaceAnalyzer().analyze(contexts, base_signatures=base) == []

    def test_no_impact_without_base_signatures(self):
        contexts = [build("src/service.py", SERVICE_AFTER), build("src/handler.py", CALLER)]

        assert CrossFileInterfaceAnalyzer().analyze(contexts) == []

    def test_single_file_pr_has_no_cross_file_impact(self):
        contexts = [build("src/service.py", SERVICE_AFTER)]
        base = signature_map_for([build("src/service.py", SERVICE_BEFORE)])

        assert CrossFileInterfaceAnalyzer().analyze(contexts, base_signatures=base) == []

    def test_change_without_external_caller_is_not_breaking(self):
        contexts = [
            build("src/service.py", SERVICE_AFTER),
            build("src/handler.py", CALLER_UNRELATED),
        ]
        base = signature_map_for([build("src/service.py", SERVICE_BEFORE)])

        impacts = CrossFileInterfaceAnalyzer().analyze(contexts, base_signatures=base)

        assert len(impacts) == 1
        assert impacts[0].affected_files == []
        assert impacts[0].is_breaking is False

    def test_removed_symbol_is_reported(self):
        contexts = [build("src/service.py", "x = 1\n"), build("src/handler.py", CALLER)]
        base = signature_map_for([build("src/service.py", SERVICE_BEFORE)])

        impacts = CrossFileInterfaceAnalyzer().analyze(contexts, base_signatures=base)

        assert any(impact.change.after == "<removed>" for impact in impacts)

    def test_impact_serialises(self):
        contexts = [build("src/service.py", SERVICE_AFTER), build("src/handler.py", CALLER)]
        base = signature_map_for([build("src/service.py", SERVICE_BEFORE)])
        impact = CrossFileInterfaceAnalyzer().analyze(contexts, base_signatures=base)[0]

        payload = impact.to_dict()

        assert payload["symbol"] == "fetch_user"
        assert payload["is_breaking"] is True
        assert payload["affected_files"] == ["src/handler.py"]
        assert payload["references"] == [{"file": "src/handler.py", "line": 5}]
        assert payload["label"]

    def test_describe_mentions_symbol_and_caller(self):
        contexts = [build("src/service.py", SERVICE_AFTER), build("src/handler.py", CALLER)]
        base = signature_map_for([build("src/service.py", SERVICE_BEFORE)])
        impact: InterfaceImpact = CrossFileInterfaceAnalyzer().analyze(
            contexts, base_signatures=base
        )[0]

        description = impact.describe()

        assert "fetch_user" in description
        assert "src/handler.py" in description


class TestRelationshipMap:
    def test_builds_relationship_from_symbol_reference(self):
        contexts = [build("src/service.py", SERVICE_AFTER), build("src/handler.py", CALLER)]

        impacts, references = CrossFileInterfaceAnalyzer().build_relationship_map(contexts)

        service_impact = next(i for i in impacts if i.source_file == "src/service.py")
        assert service_impact.related_files == ["src/handler.py"]
        assert service_impact.requires_review is True
        assert any(signal.startswith("symbol-referenced:") for signal in service_impact.signals)
        assert references

    def test_unrelated_files_produce_no_relationship(self):
        contexts = [
            build("src/service.py", SERVICE_AFTER),
            build("src/handler.py", CALLER_UNRELATED),
        ]

        impacts, references = CrossFileInterfaceAnalyzer().build_relationship_map(contexts)

        assert impacts == []
        assert references == []

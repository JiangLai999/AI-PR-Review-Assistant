from __future__ import annotations

import json
from pathlib import Path

import ai_pr_review.config as config_module
from ai_pr_review.config import (
    PROJECT_CONFIG_DIRNAME,
    PROJECT_CONFIG_FILENAME,
    PROJECT_LOCAL_CONFIG_FILENAME,
    AppConfig,
)


def test_personal_save_overrides_project_shared_config(tmp_path: Path, monkeypatch) -> None:
    """Chat settings must persist above a project-shared default.

    Loading order puts the project shared file above the user file. Saving the
    user file therefore used to look successful in the running process and then
    silently revert on the next launch. Personal edits now land in the
    highest-precedence project-local file whenever a project config exists.
    """
    user_config = tmp_path / "user" / "config.json"
    user_config.parent.mkdir()
    user_config.write_text(
        json.dumps({"preferences": {"hybrid_strategy": "remote_only"}}),
        encoding="utf-8",
    )

    project_root = tmp_path / "workspace"
    project_root.mkdir()
    (project_root / ".git").mkdir()
    project_config_dir = project_root / PROJECT_CONFIG_DIRNAME
    project_config_dir.mkdir()
    (project_config_dir / PROJECT_CONFIG_FILENAME).write_text(
        json.dumps(
            {
                "provider": {
                    "name": "deepseek",
                    "display_name": "DeepSeek",
                    "base_url": "https://api.deepseek.com/v1",
                    "api_format": "openai",
                    "default_model": "deepseek-chat",
                    "models": {
                        "deepseek-chat": {
                            "name": "deepseek-chat",
                            "context_window": 32768,
                            "max_output": 4096,
                        }
                    },
                },
                "preferences": {"hybrid_strategy": "balanced"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", user_config)
    monkeypatch.setattr(config_module, "_default_config_path", lambda: user_config)
    monkeypatch.chdir(project_root)

    config = AppConfig.load()
    # The project shared default wins over the user file, as documented.
    assert config.preferences.hybrid_strategy == "balanced"

    config.preferences.hybrid_strategy = "local_only"
    saved_to = config.save(save_key=True)

    assert saved_to == project_config_dir / PROJECT_LOCAL_CONFIG_FILENAME
    reloaded = AppConfig.load()
    assert reloaded.preferences.hybrid_strategy == "local_only"
    assert reloaded._active_provider_config().name == "ollama"


def test_explicit_config_path_still_receives_explicit_save(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit.json"
    config = AppConfig.load(explicit)
    config.preferences.hybrid_strategy = "local_only"

    saved_to = config.save()

    assert saved_to == explicit
    assert AppConfig.load(explicit).preferences.hybrid_strategy == "local_only"

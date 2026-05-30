# Contributing

感谢你为 AI PR Review 助手做贡献。

## 开发环境

```bash
git clone https://github.com/JiangLai999/AI-PR-Review-.git
cd AI-PR-Review-
pip install -e .[dev]
```

推荐使用 Python 3.12。

## 提交前检查

请在提交前至少运行以下命令：

```bash
pytest
black --check src tests
isort --check-only src tests
mypy src
```

如果你修改了文档、CLI 参数或发布流程，也请同步更新：

- `README.md`
- `docs/API.md`
- `CHANGELOG.md`

## 代码规范

- 优先做最小正确改动。
- 不要在文档中把规划能力写成已完成能力。
- 新增 CLI 行为时补充测试。
- 新增配置项时同步更新默认值、验证逻辑和文档。
- 保持类型注解与现有代码风格一致。

## 提交流程

1. 创建分支。
2. 完成修改并补充测试。
3. 运行本地检查。
4. 更新相关文档。
5. 提交 Pull Request。

## Pull Request 建议

- 标题清晰说明变更目的。
- 描述中包含背景、实现方式和验证结果。
- 如果修改输出格式，附上示例输出。
- 如果修改过滤规则或提示词，说明可能的行为变化。

## Issue 与反馈

- Bug 请提供复现步骤、期望行为和实际行为。
- 功能建议请说明使用场景和收益。
- 一般反馈可使用仓库中的 feedback issue 模板。

## 文档真实性要求

更新 README 或其他对外文档时，请遵循：

- 只描述代码中真实存在且可验证的能力。
- 对需要额外配置才能启用的能力单独标注。
- 对尚未落地的能力明确标记为 roadmap。

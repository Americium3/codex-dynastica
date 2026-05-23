# 贡献指南

[English](CONTRIBUTING.md) · **简体中文**

Phase 0 是个范围明确的小型 Python 包。目前最有价值的贡献是：

1. **存档结构覆盖**。`rakaly` 输出的 JSON 在 CK3 版本之间会变，模组下也可能不同。`src/chronicler/parsers/save_import.py` 已经做了容错抽取，但仍可能漏掉某些键。如果你的存档明显事件被漏掉，请附上脱敏后的 JSON 片段，我们补上对应的键。

2. **Prompt 质量**。`src/chronicler/agents/court_historian.py` 与 `src/chronicler/agents/peasant_ballad.py` 中的两种声音都是初稿，中英文皆然。同一事件 prompt 修改前后的模型输出对照（以 HTML 形式保存）是讨论修改最直接的方式。

3. **新的叙事声音**。Phase 2 需要敌国史官与教会编年史。提前想做的话，新建 `src/chronicler/agents/<voice>.py` 继承 `Agent` 即可，欢迎提 PR。

4. **本地化**。所有用户可见字符串都必须中英双语同步。新增 CLI 提示或 HTML chrome 文案时，请同时更新 `src/chronicler/i18n/en.json` 与 `src/chronicler/i18n/zh.json`。绝不允许"先英文，以后再补中文"。

## 工作流

```bash
git clone https://github.com/Americium3/codex-dynastica.git
cd codex-dynastica
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check src tests
```

请尽早开 draft PR，参考 [docs/ROADMAP.zh-CN.md](ROADMAP.zh-CN.md) 以免与其他人撞活。

## 代码风格

- 全量类型注解。
- 任何跨边界的数据用 Pydantic 模型。
- 运行时依赖只允许 `pydantic` + `anthropic`。开发/测试依赖放在 `dev` extras。
- public 函数一行 docstring 即可；棘手的内部逻辑写一小段注释，重点说"为什么"而不是"做了什么"。

## 测试

`tests/test_smoke.py` 用 `DryRunClient` 对样例数据跑完整管线。新增测试加在同文件，超过 200 行再拆。

# Codex Dynastica

[English](README.md) · **简体中文**

> 一款由 AI 驱动、为《十字军之王 3》提供多视角史书生成的伴侣工具。

《十字军之王 3》最大的叙事空白，在于玩家玩了三百年，却**没有真正的"历史"留下**。游戏内事件文本来回复用，王朝没有被记住的过往。**Codex Dynastica** 用大语言模型生成鲜活、立场各异、彼此矛盾的多版本编年史——同一场战争，宫廷史官称之为"圣战大捷"，敌国史官记作"北方暴君焚毁圣城"，乡野歌者只记得"国王征走了最后一袋麦"。

本仓库即第 **Phase 0**：MVP 数据管线。读取 CK3 存档（或实时事件日志），用 Claude API 生成两种声音的编年史，输出羊皮纸风格的 HTML 史书。后续阶段加入游戏内 UI、更多叙事视角、代际漂移、以及反向影响游戏机制的钩子。

## 当前状态

- **Phase 0 — 宫廷史官 + 农民歌谣** ✅ MVP 完成
- **Phase 1 — 游戏内王室图书馆（原生风格 UI）** 🚧 未开始
- **Phase 2 — 敌国 + 教会视角** 🚧 未开始
- **Phase 3 — 历史漂移 + 物理载体 + Gameplay 反向钩子** 🚧 未开始

完整路线图见 [docs/ROADMAP.zh-CN.md](docs/ROADMAP.zh-CN.md)。

## Phase 0 已有功能

- **存档导入** —— 通过 [rakaly](https://github.com/rakaly) 把 `.ck3` 存档转为 JSON，再抽取死亡、战争、加冕、婚姻等事件
- **实时 JSONL 摄取** —— 监听 CK3 模组端写出的事件流（Phase 1 上线模组端）
- **双语叙事声音** —— 拉丁化的宫廷史官 + 国风民谣体的农民歌者，每种声音都有长系统提示词驱动
- **提示词缓存** —— 系统提示标记 `cache_control: ephemeral`，5 分钟内复用降本约 10 倍
- **费用核算** —— 每条编年史记录输入/输出/缓存命中词元与美元估算
- **幂等存储** —— 重复导入同一存档不会重复事件；重跑 `generate` 自动跳过已生成的 (事件, 视角, 语言) 三元组（除非 `--force`）
- **静态 HTML 输出** —— 羊皮纸风格双栏阅读器，浏览器直接打开，零 Web 框架依赖
- **干跑模式** —— 用零开销的模拟 LLM 跑通全管线，便于开发与 CI
- **中英双语生成** —— 同一事件可同时生成英文与中文版本；输出语言可逐次切换

## 快速上手

```bash
git clone https://github.com/Americium3/codex-dynastica.git
cd codex-dynastica
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 用内置的样例存档零成本验证管线：
chronicler import-json tests/fixtures/sample_save.json --db demo.db
chronicler generate --db demo.db --dry-run --lang en,zh
chronicler render --db demo.db --out demo_zh.html --lang zh
# 在浏览器中打开 demo_zh.html

# 接入真实 Claude API：
export ANTHROPIC_API_KEY=sk-ant-...
chronicler generate --db demo.db --force --lang zh
chronicler render --db demo.db --out demo_zh.html --lang zh
```

### 处理真实存档

```bash
# 需 PATH 中有 rakaly：https://github.com/rakaly
chronicler import "~/Documents/Paradox Interactive/Crusader Kings III/save games/MyCampaign.ck3" --db campaign.db
chronicler generate --db campaign.db --from 1066 --to 1200 --lang zh
chronicler render --db campaign.db --out campaign.html --lang zh --title "韦塞克斯王朝编年史"
```

不想装 rakaly？先把存档手工转 JSON：

```bash
rakaly json MyCampaign.ck3 > MyCampaign.json
chronicler import-json MyCampaign.json --db campaign.db
```

### 监听实时游戏

Phase 1 模组端落地后将自动写 `events.jsonl`。当前可用样例文件验证：

```bash
chronicler watch tests/fixtures/sample_events.jsonl --db live.db
# 另开一个终端：
chronicler generate --db live.db --lang en,zh
```

## 架构

```
.ck3 存档  ┐
           ├─[rakaly]→ parsed.json ─[抽取]──┐
events.jsonl (实时) ──[校验]──────────────────┤
                                              ↓
                                           SQLite（events）
                                              │
                                  [generator + agents]
                                              │
                                           SQLite（chronicles，含 language）
                                              │
                                         [renderers]
                                              │
                                    HTML  /  (Phase 1: CK3 GUI)
```

- **[`schemas/event.schema.json`](schemas/event.schema.json)** —— 存档导入与实时钩子的共用 JSON Schema，事件接口的事实标准。`src/chronicler/schema.py` 中的 Pydantic 模型与之 1:1 对应。
- **`src/chronicler/parsers/`** —— `save_import.py` 与 `live_hook.py`，两条管线都产出 `ChronicleEvent`。
- **`src/chronicler/storage.py`** —— SQLite，`events` / `chronicles` / `import_log` 三张表，幂等 upsert。`chronicles` 表的唯一键为 `(event_id, agent, language)`。
- **`src/chronicler/agents/`** —— 每种叙事声音一个模块。`base.py` 持有 Claude 客户端封装、干跑模拟器与计价表。每个 agent 同时维护英文与中文两套 system prompt。
- **`src/chronicler/i18n/`** —— 极简多语言层，CLI 与 HTML 表层字符串走 `_(key)` 查表。
- **`src/chronicler/generator.py`** —— 调度器；迭代 events × agents × languages，调 LLM、持久化结果。
- **`src/chronicler/render/html.py`** —— 纯 Python 输出 HTML，根据 `--lang` 切换页面 chrome 与正文语言。

## 配置

环境变量见 `.env.example`：

| 变量 | 说明 |
|---|---|
| `ANTHROPIC_API_KEY` | 非 dry-run 调用必需 |
| `CHRONICLER_LOCALE` | CLI 提示与 HTML chrome 默认语言（`en` 或 `zh`） |

事件级模型选择当前是 `Agent.model_for` 中的启发式：战争/死亡/加冕用 `claude-opus-4-7`，其他用 `claude-haiku-4-5-20251001`。Anthropic 改价时同步更新 `agents/base.py` 中的 `PRICING`。

## 开发

```bash
pip install -e ".[dev]"
pytest                       # 跑 smoke test
ruff check src tests
```

`tests/test_smoke.py` 包含 6 个端到端测试（含双语生成、迁移兼容、i18n 查表），全部使用 `DryRunClient`，无需 API key，可在 CI 中直接跑通。

## 兼容性与边界

- 主要针对 CK3 1.12.x 系列存档；更老或更新的存档 JSON 结构可能略有差异，解析器有意保持容错，遇到陌生段会跳过而不报错。
- Ironman 二进制存档需要 rakaly（其内置 token 表）。
- Phase 0 暂未读取 schemes / artifacts / struggles / activities，这些将随 prompt 语料完善而加入。

## 路线图

完整版见 [docs/ROADMAP.zh-CN.md](docs/ROADMAP.zh-CN.md)。简版：

- **Phase 1**：与原生 CK3 GUI 视觉等同的"王室图书馆"窗口。本地化驱动，复用 vanilla `.gfx` 与模板。
- **Phase 2**：敌国史官 + 教会编年史。借助旅人/使节角色实现跨国流通。
- **Phase 3**：50 年转抄漂移、图书馆建筑作为可摧毁的物理载体、合法性 / 民意 / 王朝光环等反向 gameplay 钩子。

## 贡献

欢迎提 issue 与 PR，尤其是：存档结构覆盖（rakaly JSON 在 CK3 版本间会变）、两种现有声音的 prompt 质量调优。详见 [docs/CONTRIBUTING.zh-CN.md](docs/CONTRIBUTING.zh-CN.md)。

## 协议

MIT —— 见 [LICENSE](LICENSE)。

本项目与 Paradox Interactive 无任何关联。《十字军之王 III》是 Paradox Interactive AB 的商标。

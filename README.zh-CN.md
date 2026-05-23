# Vox Dynastica

[English](README.md) · **简体中文**

> 王朝之声 — 为《十字军之王 3》生成**王朝史**的 AI 配套工具。

《十字军之王 3》最大的叙事空白，在于玩家玩了三百年，却**没有真正的"历史"留下**。游戏内事件文本来回复用，王朝没有被记住的过往。**Vox Dynastica** 用大语言模型生成鲜活、立场各异、彼此矛盾的多版本编年史——同一场战争，宫廷史官称之为"圣战大捷"，敌国史官记作"北方暴君焚毁圣城"，乡野歌者只记得"国王征走了最后一袋麦"。

## 当前状态

- **Phase 0 — 宫廷史官 + 农民歌谣 MVP** ✅ 完成
- **Phase 0.1 — 王朝主头衔范围 + 本地 Ollama 后端** ✅ 完成（本次提交）
- **Phase 0.2 — 玩家可选作用域：narrow / middle / wide** 🚧 计划中
- **Phase 1 — 游戏内王室图书馆 GUI（原生风格）+ 云端 API 选择器（RimTalk 模式）** 🚧 未开始
- **Phase 2 — 敌国 + 教会视角** 🚧 未开始
- **Phase 3 — 历史漂移 + 物理载体 + Gameplay 反向钩子** 🚧 未开始

完整路线图见 [docs/ROADMAP.zh-CN.md](docs/ROADMAP.zh-CN.md)。

## 当前能力（Phase 0 + 0.1）

- **存档导入** —— 通过 [rakaly](https://github.com/rakaly) 把 `.ck3` 转 JSON，再抽取死亡、战争、加冕、婚姻、出生、特质等事件
- **王朝范围抽取器** —— `scripts/import_dynasty.py` 沿着**玩家主头衔**（`landed_data.domain[0]`）的脊柱走：历任持有者的崩逝、第一继承人的生卒、王座主人的婚事、为本头衔打过的战、以及当代持有者的重大健康 / 衰老特质
- **实时 JSONL 摄取** —— Phase 1 模组端会写出事件流；当前可用样例文件验证
- **双语叙事声音** —— 宫廷史官（仿 Bede 现代英文译本 / 半文言史笔）与农民歌者（民谣体 /《诗经·国风》四言），每种声音都有长系统提示词驱动
- **三种 LLM 后端** —— Anthropic Claude（云端）、**Ollama 本地模型**（如 `gemma3:27b`，无需 API key）、或 DryRun 模拟（离线）
- **提示词缓存（Claude）** —— 系统提示标记 `cache_control: ephemeral`，5 分钟内复用降本约 10 倍
- **费用核算** —— 每条编年史记录输入/输出/缓存命中词元与美元估算；本地模型记为 \$0
- **幂等存储** —— 重导入不会重复事件；重跑 `generate` 自动跳过已生成的 `(event, agent, language)` 三元组（除非 `--force`）
- **全面双语** —— CLI / HTML chrome / LLM 输出三层皆同时支持 EN + zh-CN
- **静态 HTML 输出** —— 羊皮纸风格双栏阅读器，浏览器直接打开

## 快速上手

```bash
git clone https://github.com/Americium3/vox-dynastica.git
cd vox-dynastica
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 内置样例存档零成本验证管线：
chronicler import-json tests/fixtures/sample_save.json --db demo.db
chronicler generate --db demo.db --dry-run --lang en,zh
chronicler render --db demo.db --out demo_zh.html --lang zh

# 本地模型（Ollama 跑 gemma3:27b）：
ollama pull gemma3:27b
chronicler generate --db demo.db --backend ollama --ollama-model gemma3:27b --lang en,zh
chronicler render --db demo.db --out demo_en.html --lang en
chronicler render --db demo.db --out demo_zh.html --lang zh

# 走 Anthropic 云端：
export ANTHROPIC_API_KEY=sk-ant-...
chronicler generate --db demo.db --backend claude --force --lang en,zh
```

### 处理真实存档（王朝范围）

```bash
# 仓库内已自带 bin/rakaly.exe（Windows），无须装系统 PATH
python scripts/import_dynasty.py \
    --save "C:/.../save games/MyCampaign.ck3" \
    --db campaign.db \
    --from-year 1000 --to-year 1066 \
    --max-per-type 6

chronicler generate --db campaign.db --backend ollama --ollama-model gemma3:27b --lang en,zh
chronicler render --db campaign.db --out campaign_zh.html --lang zh \
    --title "韦塞克斯王朝编年"
chronicler render --db campaign.db --out campaign_en.html --lang en \
    --title "Chronicle of the House of Wessex"
```

### 监听实时游戏

Phase 1 模组端落地后将自动写 `events.jsonl`。当前可用样例文件验证：

```bash
chronicler watch tests/fixtures/sample_events.jsonl --db live.db
# 另开一终端：
chronicler generate --db live.db --backend ollama --ollama-model gemma3:27b --lang en,zh
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

- **[`schemas/event.schema.json`](schemas/event.schema.json)** —— 存档导入与实时钩子的共用 JSON Schema。`src/chronicler/schema.py` 中的 Pydantic 模型与之 1:1 对应。
- **`src/chronicler/parsers/`** —— `save_import.py` 与 `live_hook.py`，两条管线都产出 `ChronicleEvent`。
- **`scripts/import_dynasty.py`** —— Phase 0.1 的真实存档王朝范围导入脚本。
- **`src/chronicler/storage.py`** —— SQLite，`events` / `chronicles` / `import_log` 三张表，幂等 upsert。`chronicles` 表的唯一键为 `(event_id, agent, language)`。
- **`src/chronicler/agents/`** —— 每种叙事声音一个模块。`base.py` 含 Claude 客户端、**Ollama 本地客户端**、dry-run 模拟器与计价表。
- **`src/chronicler/i18n/`** —— 极简多语言层。
- **`src/chronicler/generator.py`** —— 调度器。
- **`src/chronicler/render/html.py`** —— 纯 Python 输出 HTML，根据 `--lang` 切换语言。

## 配置

| 变量 | 说明 |
|---|---|
| `ANTHROPIC_API_KEY` | 当 `--backend claude` 时必需 |
| `CHRONICLER_LOCALE` | CLI 提示与 HTML chrome 默认语言（`en` 或 `zh`），命令行 `--locale` 覆盖 |
| `CHRONICLER_RAKALY` | 覆盖 rakaly 二进制路径，否则按 `<repo>/bin/rakaly[.exe]` → `$PATH` 顺序查找 |

事件级模型选择当前是 `Agent.model_for` 中的启发式：战争/死亡/加冕用主模型，其他用副模型。Ollama 后端忽略这套，统一用配置的单一本地模型。

## 开发

```bash
pip install -e ".[dev]"
pytest                       # 跑 smoke test
ruff check src tests
```

## 兼容性与边界

- 主要针对 CK3 1.12.x 系列存档；亦验证过若干中文风味 mod 存档（`celestial_government`，1006 与 1034 两个游戏内日期）
- Ironman 二进制存档需要 rakaly
- Phase 0 暂未读取 schemes / artifacts / struggles / activities
- 王朝范围抽取器假定 `landed_data.domain[0]` 是主头衔（CK3 的优先级约定）

## 路线图

完整版见 [docs/ROADMAP.zh-CN.md](docs/ROADMAP.zh-CN.md)。简版：

- **Phase 0.2**：玩家可选作用域 —— **narrow**（仅本王朝家族）、**middle**（landless adventurer 玩法专用：途经的诸王列侯）、**wide**（已知世界一切显赫君主）
- **Phase 1**：与原生 CK3 GUI 视觉等同的"王室图书馆"窗口；模组设置里 RimTalk 风格的 provider / key / model 选择器
- **Phase 2**：敌国史官 + 教会编年史。旅人/使节作为信息载体跨界流通
- **Phase 3**：50 年转抄漂移、图书馆建筑作为可摧毁的物理载体、合法性 / 民意 / 王朝光环等反向 gameplay 钩子

## 贡献

欢迎提 issue 与 PR，尤其是：存档结构覆盖（rakaly JSON 在 CK3 版本间会变）、两种现有声音的 prompt 质量调优。详见 [docs/CONTRIBUTING.zh-CN.md](docs/CONTRIBUTING.zh-CN.md)。

## 协议

MIT —— 见 [LICENSE](LICENSE)。

本项目与 Paradox Interactive 无任何关联。《十字军之王 III》是 Paradox Interactive AB 的商标。

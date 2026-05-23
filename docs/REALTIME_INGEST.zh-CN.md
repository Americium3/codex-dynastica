# 实时事件采集

[English](REALTIME_INGEST.md) · **简体中文**

## 缘起

Phase 0–0.3 走的是存档路：玩家手动存档 → Python 用 rakaly 解析 `.ck3` → 抽取事件 → LLM 叙述。这种方式做战后回顾还行，但是行进中的游戏不友好——它强迫玩家「停下来存档再说」，并且一次性把一大批事件丢给 LLM。

Phase 0.4 加上另一条路：游戏跑着的时候，mod 把每条值得记录的事件写一行 JSON 到日志文件，Python 监听这个文件，事件到达即处理。不分批、不需要手动存档、`--max-events` 上限也用不到了——每个事件都是一次独立的、小开销的 LLM 调用。

## 架构

```
┌────────────────────┐       ┌───────────────────┐       ┌─────────────────────┐
│   CK3 (运行中)     │       │  script.log /     │       │  Python 监听器      │
│                    │       │  events.jsonl     │       │  (chronicler watch) │
│  on_ruler_death,   │  →    │                   │  →    │                     │
│  on_battle_won,    │  via  │  {…JSON 一行…}    │  tail │  校验 → 入库 →     │
│  on_marriage, …    │ debug │  {…JSON 一行…}    │  poll │  （可选）LLM       │
│                    │  _log │  …                │       │                     │
└────────────────────┘       └───────────────────┘       └─────────────────────┘
```

三段，由 JSONL 行界划开：

1. **CK3 mod 侧** —— `on_action` 钩子触发 `scripted_effect`，拼出一行 JSON，调用 `debug_log` 写入。`debug_log` 是 CK3 内置的调试输出指令，会追加到 `Documents/Paradox Interactive/Crusader Kings III/logs/script.log`。
2. **JSONL 文件** —— 契约边界。Schema 与 Phase 0 存档导入路径同源（`schemas/event.schema.json`），`source = "live_hook"`。这一层让整条管线可端到端测试——不开 CK3、手写一行 JSONL 就能验证。
3. **Python 监听器** —— `chronicler watch <jsonl> --db chronicle.db` 轮询文件、按 `ChronicleEvent` 校验、入 SQLite，若开 `--generate` 还会立刻喂给 agent。

## 为何选 `debug_log`（而非轮询自动存档）

CK3 没有官方事件导出 API。我们评估过三条路：

| 方案 | 结论 |
|---|---|
| 轮询自动存档 → 每次 `chronicler import` | ❌ 玩家明确否决：延迟大、大量重复工作、依然分批 |
| 读 CK3 进程内存 | ❌ 跨补丁脆弱、反作弊敏感、扛不住 Steam 更新 |
| **从 scripted effect 调 `debug_log`** | ✅ 官方接口、跨补丁稳定、只在 mod 上下文、产物即可监听 |

`debug_log` 本意是给 modder 做诊断输出的，但它写出的字符串可以是任何内容——包括一行 JSON 信封。许多大型 Total Conversion 模组已经用它做遥测。性能开销可忽略（每个真实事件一行，不是每 tick 一行）。

## CK3 侧契约

mod 在 `events/` 或 `common/on_action/` 注册我们关心的钩子。每个钩子拼一段 JSON 串调 `debug_log`。示例（示意，实际 `.txt` 文件在 Phase 1 随 mod 包发布）：

```paradox
# common/on_action/vox_dynastica_on_actions.txt
on_ruler_death = {
    effect = {
        vox_dynastica_log_event = {
            EVENT_TYPE = ruler_death
            ACTOR = root
            CAUSE = "[root.GetDeathReasonKey]"
        }
    }
}
```

```paradox
# common/scripted_effects/vox_dynastica_log_event.txt
vox_dynastica_log_event = {
    debug_log = "VD_EVENT|{\"event_id\":\"live_hook:$EVENT_TYPE$:[GetGameYear]:[$ACTOR$.GetID]\",\"source\":\"live_hook\",\"type\":\"$EVENT_TYPE$\",\"year\":[GetGameYear],\"month\":[GetGameMonth],\"day\":[GetGameDay],\"primary_actors\":[{\"character_id\":\"[$ACTOR$.GetID]\",\"name\":\"[$ACTOR$.GetFirstNameNoTooltip]\",\"dynasty\":\"[$ACTOR$.GetDynasty.GetName]\",\"culture\":\"[$ACTOR$.GetCulture.GetName]\",\"religion\":\"[$ACTOR$.GetReligion.GetName]\"}],\"tags\":[\"$CAUSE$\"]}"
}
```

`VD_EVENT|` 前缀是 sentinel，让监听器能从 `script.log`（也会收集别的 mod 的杂讯）里 grep 出我们的行。监听器在 `json.loads` 前剥掉这个前缀。

两段轮换：

* mod 对每个值得记录的事件调一次 `debug_log`
* 随 mod 附带的小型 Python 桥（`scripts/extract_vd_events.py`）周期性扫 `script.log` 找 `VD_EVENT|` 行，把 JSON 尾巴写到 `events.jsonl`。Python 监听器看的是 `events.jsonl`，不是 `script.log` 本身——这样 CK3 的诊断噪音就和我们的事件流分开了

## 计划挂的 on_action 列表

Phase 0.4 仅写文档；Phase 1 再交付 `.txt` 实文件。

| on_action | EventType | 默认 min_significance |
|---|---|---|
| `on_ruler_death` | `ruler_death` / `murder` | 95 ——必叙 |
| `on_birth`（仅继承人） | `birth` | 64 ——叙（heir 标签加权后 76） |
| `on_marriage` | `marriage` | 60 ——叙 |
| `on_war_won` / `on_war_lost` | `war_end` | 92 ——必叙 |
| `on_battle_won` / `on_battle_lost` | `battle` | 82 ——叙 |
| `on_title_gain_inheritance` | `coronation` | 88 ——必叙 |
| `on_great_holy_war_*` | `great_holy_war` | 92 ——必叙 |
| `on_faith_created` | `religion_change` / `heresy_outbreak` | 74–78 ——叙 |
| `on_county_culture_change` | （只入库，不叙） | 30 ——仅 DB |
| `on_artifact_claimed`（限稀世） | `artifact_acquired` | 55 + rarity 加权 |

`min_significance` 低于监听器阈值的事件仍入 DB（日后回顾要用），只是跳过 LLM 调用以省 token。

## 端到端冒烟测试（不需要 CK3）

```bash
# 终端 1：监听
chronicler watch ./events.jsonl --db chronicle.db --generate \
    --backend ollama --lang en,zh

# 终端 2：假装是游戏
cat >> ./events.jsonl <<'EOF'
{"event_id":"live_hook:ruler_death:1066:abc123","source":"live_hook","type":"ruler_death","year":1066,"primary_actors":[{"character_id":"42","name":"Harold","dynasty":"Godwin"}],"tags":["death_battle"]}
EOF
```

监听器应打印接受的事件，随后逐条输出 `[court_historian/en]`、`[court_historian/zh]`、`[peasant_ballad/en]`、`[peasant_ballad/zh]`。

## 各 Phase 分工

* **Phase 0.4**（本期）：
  * Python `watch --generate` 管线 ✅
  * `--min-significance` 节流 LLM 开销 ✅
  * 本规范文档 ✅
  * 按 scope 的严格度预设（`narrow=6 / medium=12 / wide=24`）✅
* **Phase 1**（计划中）：
  * CK3 mod `.txt` 实文件（`on_action`、`scripted_effects`）
  * `scripts/extract_vd_events.py` —— script.log → events.jsonl 桥
  * 游戏内 LLM 提供方设置 + min-significance 滑杆
* **Phase 2+**：
  * 多声部（敌国 / 教会）的实时采集 —— 复用同一 JSONL 管线，只是多挂 agent

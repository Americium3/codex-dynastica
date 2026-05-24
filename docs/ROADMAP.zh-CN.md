# 路线图

[English](ROADMAP.md) · **简体中文**

Vox Dynastica 专注于**王朝 / 主头衔史**。**家族史**（堂表姊妹的婚事、姑奶奶的丧事）将拆分为另一个姊妹项目，让本项目保持锋利。

各阶段独立可交付、独立有价值。

## Phase 0 — 宫廷史官 + 农民歌谣 MVP ✅

端到端管线。**支持存档文件导入**，不仅是实时事件钩子。暂无游戏内 UI，输出为浏览器 HTML。

- [x] 事件 JSON Schema，存档导入与实时钩子的共用接口
- [x] Pydantic 模型
- [x] SQLite 存储，幂等 upsert
- [x] 存档导入器（rakaly 子进程封装 + 容错抽取器）
- [x] 实时 JSONL 监听器（一次性 + 持续跟随）
- [x] Claude API 客户端，含 prompt caching 与费用核算
- [x] 干跑模拟客户端
- [x] 两种叙事声音的 system prompt（宫廷史官、农民歌谣），中英双语版本
- [x] 调度器
- [x] 静态 HTML 渲染器（羊皮纸双栏）
- [x] CLI（`import` / `import-json` / `ingest` / `watch` / `generate` / `render` / `stats`），支持 `--lang en,zh`
- [x] i18n 层：CLI 提示与 HTML chrome 走 `_(key)` 查表
- [x] 样例数据 + 端到端 smoke test（6/6 通过）

## Phase 0.1 — 王朝主头衔范围 + 本地模型后端 ✅

真实存档把宽泛的抽取器顶崩了（一份较晚期的存档常带 9 万以上死亡角色）。Phase 0.1 把视线收窄到**玩家的主头衔**，并增加一条离线 LLM 通路。

- [x] **Ollama 本地模型客户端**（`agents/base.py` 中的 `OllamaClient`）——实现 `LLMClient` 协议；剥离 Anthropic 特有的 `cache_control`；用 stdlib `urllib` 直连 `http://localhost:11434/api/chat`；默认 `gemma3:27b`；本地跑费用记为 \$0
- [x] **CLI 增加** `--backend {claude,ollama,dry-run}`、`--ollama-model`、`--ollama-url`、`--agent` 子集过滤
- [x] **项目内置 rakaly**：`parsers/save_import.py` 按 `<repo>/bin/rakaly[.exe]` → `$CHRONICLER_RAKALY` → `$PATH` 顺序查找，不污染系统
- [x] **`scripts/import_dynasty.py`** —— 主头衔范围真实存档导入器：
  - 沿着 `landed_titles.landed_titles[primary_id].history` 走，枚举主头衔的历任持有者
  - 每位持有者抓：**驾崩** / **第一继承人的生卒** / **大婚**
  - 当代持有者参与的 **active wars**：发出 "ongoing war" 事件，含 casus belli 与对手首领
  - 当代持有者的**重大特质**（重病 / 残疾 / 衰老）抽出来作为 state-of-the-realm 条目，日期记为存档当日
- [x] **title_id → holder_char_id 反查表** —— wars.active_wars 的参与者是角色 id，但把战争挂回*主头衔本身*需要这层映射
- [x] **brief 注入玩家上下文** —— 每条 prompt 都带在位君主名 + 主头衔 + 家名，避免 LLM 凭空捏造 "King Alaric"
- [x] **`--max-per-type` 子配额上限** —— 防止某一类事件淹没整部编年史
- [x] **CK3 汉字名解码器** —— `Zihua_5B50_534E` → `Zihua 子华`，`Wenju_6587_4E3E` → `Wenju 文举`
- [x] **重写宫廷史官英文 prompt** —— 禁用未翻译拉丁；改为可读古朴英文（仿 Bede *现代英译本*）
- [ ] 3–5 个多样化真实存档上的费用曲线基准
- [ ] 从新版 `landed_titles[*].history` 形态的存档里恢复 wars / coronations / marriages（Phase 0 默认抽取器目前漏抓）

## Phase 0.2 — 玩家可选作用域 + 缩短编年史 ✅

在 `scripts/import_dynasty.py` 上加 `--scope` 参数（Phase 1 再做游戏内设置），让玩家挑「编年史的镜头开多大」。所有 scope 走同一 CLI；旧的独立原型脚本 `import_narrow.py` / `import_real_save.py` 仅作历史参考保留。

- [x] **dynastic**（默认）—— 主头衔主线：持有者更迭、继承人、战争、特质、阴谋、故事、神器、活动、婚事。
- [x] **narrow** —— 仅本王朝家族。窗口内的家族成员生卒。适合（一）想看家史的有地领主；（二）landless adventurer——血脉仍是单元。
- [x] **middle** —— narrow + dynastic 叠加。家族生卒附于主头衔主线之上。不确定时的默认甜蜜点。
- [x] **wide** —— middle + 已知世界一切有地君主之死（受 `--max-per-type` 严控；存档常带 9 万以上死亡 NPC）。
- [x] **缩短编年史** —— 宫廷史官目标改为 1–2 段 / 约 70–130 字（原为 2–5 段 / 150–280 字）。民间歌谣改为 4–10 句 / 约 30–70 字（原为 8–20 句 / 60–140 字）。`max_tokens` 默认值从 800 降至 350。在线玩家不会等得起每条事件都是中篇小说。
- [ ] 按玩家 lifestyle 自动挑 scope（landed → dynastic、wandering → middle、ironman → narrow）。推迟到 Phase 1 与游戏内 UI 一起做。

## Phase 0.3 — 事件精选 / era_mood 调色 / 意象库 ×20 ✅

前两次跑出来 24、27 条事件，一坐难读完；民间歌谣依旧偏哀调、五个意象（麦雪老胡子牛羊铁手）反复用。Phase 0.3 一并解决：

- [x] **按显赫度筛事件** —— `scripts/import_dynasty.py` 新增 `SIGNIFICANCE` 评分表：murder/ruler_death/war/coronation 居首，trait/activity/story 居末，配合 tag 微调（`heir` +12、`title:` +6、`notable_ruler` −15、不带 `heir` 的 `house_member` −8、稀世神器 +10）。先按类别裁，再取分数最高的 N 条；同分按时间靠后优先。
- [x] **默认上限下调** —— `--max-per-type` 由 6 降为 **3**；新增全局 `--max-events` 上限，默认 **12**（原为不限）；artifact 抽取器由 6 降为 4。默认单页可读完。
- [x] **逐事件 era_mood** —— 抽取器对每条入选事件计算 ±15 年窗内的「暗事件」密度（死亡 / 凶死 / 战争 / 战役 / 灾害 / 异端 / 圣战），与本卷均值比较，盖上 `era_mood = turbulent | ordinary | peaceful` 章。`ChronicleEvent` 与 JSON Schema 新增此可选字段，并在 `event_brief()` 中渲染，使各 agent 都能读到。
- [x] **民间歌谣读 era_mood** —— 中英双语 prompt 现并用两层信号：事件本身底色 + era 大势。`turbulent` 之世添丁也带钟声、缺席的兄弟；`peaceful` 之世崩薨更显沉痛（「二十秋未失一子」）；`ordinary` 依事件本色。系统性偏哀调的毛病由此根除。
- [x] **意象库 ×20** —— 中英双语 prompt 的八大类（天时／五谷／禽兽／草木／器物／家宅／人物／节令）词库均大幅扩张：英文从约 90 词扩至约 1200，中文从约 90 词扩至约 900。每大类内分小组，便于按「早春」「深冬」择取。反复用同一词的禁令保留并加强。
- [ ] 宫廷史官同样应按 era_mood 微调（目前仅歌谣读）。推迟做：史官本就当措辞克制，偏移更细，需另一轮专门调试。

## Phase 0.4 — 实时事件采集 + 分层严格度 ✅

存档导入做战后回顾很合适，但行进中的游戏要求玩家「停下来存档再说」，并且一次性把一大批事件丢给 LLM。Phase 0.4 把管线重心转向 Phase 0 就铺好的 live-hook 通路，并把 `--scope` 重新校准——每个预设自带严格度。

- [x] **按 scope 的严格度预设** —— `--scope` 同时承担「拉什么」与「卡多严」。Phase 0.3 的设置成为 **medium** 一档（`dynastic` / `middle`）；`narrow` 收紧（max_per_type=2、max_events=6、min_live_significance=70）；`wide` 放宽（max_per_type=5、max_events=24、min_live_significance=40）。`--max-per-type` / `--max-events` 仍可手动覆盖。
- [x] **显赫度评分提到 `chronicler.scoring`** —— Phase 0.3 的 `SIGNIFICANCE` 表与带标签的 `significance()` 函数迁入公共模块，存档导入器和 live-hook 监听器对事件用同一套排序。
- [x] **`chronicler watch --generate`** —— 事件到达即叙述，一条事件一次 LLM 调用，不再批处理。后端可选 `claude` / `ollama` / `dry-run`，语言与 agent 子集同 `generate`。
- [x] **`--min-significance` LLM 节流** —— 分数低于阈值的事件仍入库（日后回顾要用），跳过 LLM 调用。默认 55，与 medium scope 对齐。
- [x] **架构规范文档**（`docs/REALTIME_INGEST.md`，中英双语）—— 说明 CK3 侧契约（`scripted_effect` 调 `debug_log`）、`VD_EVENT|` sentinel、`script.log` → `events.jsonl` 的桥、计划挂的 `on_action` 列表、各 phase 分工。
- [ ] **CK3 mod `.txt` 实文件** —— 实际的 `on_action` 与 `scripted_effect` 定义。推迟到 Phase 1，与游戏内 UI 一起做。监听器今日已可用手写 JSONL 完整测试。
- [ ] **`scripts/extract_vd_events.py`** —— 配套的 `script.log` → `events.jsonl` 提取器。推迟到 Phase 1。

## Phase 0.5 — CI 自动化 + 测试补齐 ✅

Phase 0.3 与 0.4 合计交付了几百行代码（`scoring.py`、`ScopePreset`、era_mood 计算、`watch --generate`），却一行测试也没补。Phase 0.5 在 Phase 1 模组工作开始前先把这个缺口堵上，让后续 PR 自动捕获回归。

- [x] **GitHub Actions CI**（`.github/workflows/ci.yml`）—— 两个 job：
  - `lint` 跑 `ruff check src tests scripts`
  - `test` 在 Python 3.11 + 3.12 上跑 `pytest -q`（3.11 为下限，3.12 廉价捕获前向兼容漂移）
  - 任何分支的 push + 任何针对 `main` 的 PR 都触发
  - 同 ref 新提交到达即取消旧运行（rebase 风暴省时间）
- [x] **分支保护后续**（GitHub ruleset 手动开）—— 应启用「Require status checks: lint, test (3.11), test (3.12)」，让红了的 PR 没法合 main
- [x] **ruff 基线扫一遍** —— 修了 96 个自动修复项 + 6 处手工修（循环变量改 `_`、`zip(strict=True)`、删死变量、删未用 import）。`UP042`（StrEnum 迁移）与 `scripts/import_dynasty.py` 的 `E402`（sys.path 操作）加入 ignore，附原因注释
- [x] **`tests/test_scoring.py`**（26 测）—— 钉住 SIGNIFICANCE 校准、标签加权（heir +12、title +6、notable_ruler −15、house_member −8、rarity +10）、SCOPE_PRESETS 结构、`resolve_scope()` 回退行为
- [x] **`tests/test_era_mood.py`**（15 测）—— 覆盖 `stamp_era_mood()` 三档（turbulent / peaceful / ordinary）行为、边界情形（不足三条、无暗事件、空输入）、阈值钉死（1.4× / 0.6×）、`DARK_EVENT_TYPES` 成员
- [x] **`tests/test_watch_generate.py`**（12 测）—— JSONL 接入校验（合法行 / 坏 JSON / schema 不匹配）、`--min-significance` 节流（低分入库不喂 LLM；高分双 agent × 双语言生成）、CLI argparse 接口表面
- [x] **把 `stamp_era_mood` + `DARK_EVENT_TYPES` 抬到 `chronicler.scoring`** —— 原先埋在 `scripts/import_dynasty.py` 里，测试无法 import。导入器现转调公共模块
- 结果：pytest 由 6 测增至 **59 测**，约 10 倍覆盖。全绿，ruff 全清

## Phase 1 v0.1 — 游戏内王室图书馆 UI（仅 GUI）✅

mod 首个可交付物。朝廷窗口新增第五个页签——*王室图书馆*——点开后弹出羊皮纸样式的浮层，按时间倒序最多展示 30 条王朝编年。从第一天起即 EN + zh-CN 双语。已通过 PR [#6](https://github.com/Americium3/vox-dynastica/pull/6) 合并。

- [x] `mod/vox-dynastica/` mod 骨架（mod 内 `descriptor.mod` + 玩家端 `vox_dynastica.mod`）
- [x] `gui/window_royal_court.gui` —— 完整拷贝的 vanilla 文件 + 王室图书馆 tab 按钮（用 `VariableSystem` toggle，绕开硬编码的 `SetActiveTab` enum）
- [x] `gui/window_royal_library.gui` —— 羊皮纸浮层：分层背景、贴时代的 `MapFont`、上下卷轴边、每条卡片中央花纹分隔线、30 槽 scrollbox
- [x] `gui/preload/vd_textformatting.gui` —— 四个墨色行内 color 标签（`color_vd_ink` / `_body` / `_subtitle` / `color_vd_cinnabar`）
- [x] 双语样例 loc（精选 6 条，槽位 07–30 留空）
- [x] 占位 tab 图标（`roco_library.dds`，目前是 `roco_grandeur` 的拷贝）
- [x] 在 `mod/README.md` 记录了 8 条引擎限制（不存在局部 GUI patch、MapFont fallback chain、只能用行内 color 标签、loc 必须 UTF-8 BOM 等）
- [ ] 自绘 tab 图标替换占位（推后到美术 pass）
- [ ] `on_game_start` 读 `vd_entry_count` 隐藏空槽位（Phase 1.2）

## Phase 1.1 —— `emit-loc` CLI（LLM → CK3 loc 写入器）✅

LLM 流水线 → 王室图书馆 30 硬编码槽位之间的"写"端。纯 Python，尚未引入游戏端伴随程序。

- [x] **`chronicler emit-loc --mod-dir <path>` 子命令** —— 从 DB 拉编年，按所选 agent/语言每个事件取一行，按年份倒序排，写入 `localization/<folder>/vox_dynastica_l_<folder>.yml`，强制带 UTF-8 BOM
- [x] **纯函数 `render_loc_yaml()`** —— "格式化字节"与"选择渲染什么"分离，测试可在零文件 I/O 下钉住引擎契约
- [x] **`LocEntry` dataclass + `collect_entries_from_store()`** —— 定义 event-keyed / chronicle-keyed `Store` 行到 entry-keyed 库槽位的投影；将来投影演进只改这一处
- [x] **行内 color 标签接好** —— 年份 → `#color_vd_cinnabar`，标题 → `#color_vd_ink`，正文 → `#color_vd_ink_body`，对齐 Phase 1 GUI 契约
- [x] **导出 `vd_entry_count` key** —— 给 Phase 1.2 的"隐藏空槽位"绑定提供单一整数
- [x] **新增 28 条测试**（`tests/test_emit_loc.py`）—— 引擎契约（BOM、key 形状、不准 tab、倒序、CJK round-trip、空槽位渲染、idempotency）+ Store 投影覆盖（agent 过滤、语言过滤、年份窗口、`max_entries` 截断、空 chronicle 跳过）。总测试数 59 → **87**
- [x] **`vox-companion` 托盘程序** —— 已在 Phase 1.2 落地（详见下方）

## Phase 1.2 —— `vox-companion` 存档监听托盘程序 ✅

闭合 Tier-2 自动化回路。玩家启动一次伴随程序后，CK3 每写 autosave 都会触发流水线，刷新游戏内王室图书馆。

- [x] **`chronicler.companion` 核心模块** —— `CompanionConfig`（构造函数注入，零全局变量）、`SaveWatcher`（stdlib polling，size+mtime 防抖；文件还在写时重置、稳定签名只 fire 一次、启动前已存在的文件不会被当作新事件触发）、`run_pipeline_once()`（解析 → store → 生成 → emit-loc）返回 frozen `RunReport`（错误进 report，不抛出）、`run_headless()` 控制台循环
- [x] **`chronicler.tray` 可选 UI** —— pystray + Pillow 包装。托盘菜单：状态行（只读）、Pause toggle、"对最新存档手动重跑"、打开 mod loc 目录、打开存档目录、退出。跨平台打开目录助手（Windows `os.startfile` / macOS `open` / Linux `xdg-open`）。watcher 跑在 daemon 线程，菜单始终响应
- [x] **`chronicler companion` CLI 子命令** —— `--mod-dir`、`--db`、`--save-dir`（按 OS 自动猜 Paradox 布局）、`--lang`、`--agent`、`--max-slots`、`--poll-interval`、`--stable-polls`、`--backend`（默认 `dry-run` —— 伴随程序**绝不**默默烧 API token）、`--no-tray` 无头模式
- [x] **可选依赖组** —— `pip install 'vox-dynastica[companion]'` 拉 pystray + Pillow。核心安装保持轻量，CI 无需显示器
- [x] **Ironman 安全** —— 进程只*读*存档文件，只*写* mod 的 `localization/` 目录，从不以写模式触碰存档目录
- [x] **新增 17 条测试**（`tests/test_companion.py`）—— 手动驱动 tick 测 watcher 防抖（priming 行为、stable-polls 阈值、同签名不重 fire、改写后重 fire、写入中不 fire、暂停、glob 过滤、回调异常不杀循环、目录缺失、fired-paths 返回值）、pipeline runner（写 loc + 返回 report、捕获 parse 错误、无新事件时跳过 LLM 调用）、config 默认值（Windows USERPROFILE 分支、POSIX 后备）、`RunReport` immutable。总测试数 87 → **104**
- [ ] **Tier 1 keypress 注入** —— 通过 SendInput / xdotool 向运行中的 CK3 进程发 `reload localization`。推后到 Phase 1.5；目前玩家在托盘通知后手动跑一次控制台命令
- [ ] **服务化 / 开机自启** —— Windows 任务计划程序 / systemd user unit 打包。推后到云端 API 选择器落地之后，因为有 `--backend claude` 配好以后自启才有意义

## Phase 1.x —— 游戏内打磨 + 云端 API 选择器

硬性要求：**与原生 CK3 视觉无法区分**。应该让玩家感觉这就是 Paradox 自己出的 DLC。同时在模组设置里加入 RimTalk 风格的 provider/key/model 选择器，玩家可自选云端 LLM（或继续用本地 Ollama）。

原生级原则（不可妥协）：
- 不画新的边框/按钮/分隔线——只引用 `gfx/interface/...` 的 vanilla 贴图
- 基底布局参考 vanilla 范本：`window_encyclopedia.gui`、`window_struggle.gui`、`window_decisions.gui`
- 复用 vanilla 模板：`window_background` / `scrollbox` / `scrollbar_vertical` / `button_standard` / `background_paper` / `tooltip_widget`
- 仅用 vanilla SFX（`event:/SFX/UI/...`）、vanilla 字体（`cg_16b` / `cg_24b`）、vanilla 颜色标签（`#H` / `#italic` / `#weak`）
- 入口按钮置于已有的 vanilla 按钮带中——不允许凭空浮动新按钮
- ESC / 右键 / 拖动 / 固定的行为完全对齐 vanilla

任务：
- [ ] Vanilla UI 考古：选定范本窗口，枚举可复用模板
- [ ] 王室图书馆窗口的 `.gui`：书架视图、单本阅读、并排对比
- [ ] 入口按钮挂在角色窗口动作带
- [ ] 注入管线：Python 把生成内容写入 mod 的 `localization/replace/` YAML
- [ ] localization key 命名：`chronicle_<year>_<agent>_<event_id>`
- [ ] 热重载（save/load 或 console 命令）
- [ ] 战争结束 event："你的史官完成了一卷新编年史"——批准 / 退回修改 / 处决（钩子先做，效果在 Phase 3）
- [ ] LLM 生成卷名与章节装饰文字
- [ ] CK3 模组本地化：`localization/english/` + `localization/simp_chinese/` 双语
- [ ] 质量门槛：盲测——把图书馆截图和 vanilla 截图混在一起，第三方无法分辨
- [ ] UI 缩放 50% / 100% / 150% 下都正确
- [ ] **模组设置内的云端 API 选择器** —— RimTalk 模式：下拉选 provider（Anthropic / OpenAI / OpenRouter / 本地 Ollama），密钥与模型名输入框，合理默认值，提交前显示延迟与费用预估

## Phase 2 — 敌国 + 教会视角

从单一声音到多声音对照——沉浸感最大跃迁点。

- [ ] 敌国史官 prompt（反向极性、对方为主语）
- [ ] 教会编年史 prompt（神学框架、引经文）
- [ ] 代理人格库：每个 agent 背后是一个真实的 CK3 角色（带 traits）
- [ ] 事件 schema 扩展：`factions_involved`、`religions_involved`、`witnesses` 决定哪些代理知情
- [ ] 跨国流通：旅人/使节作为信息载体；event："一位拜占庭旅人献上一卷书，里面记录了……"
- [ ] 教会版本通过主教/教皇身份角色注入
- [ ] 图书馆 UI："按事件查找"模式：横向列出所有视角；高亮分歧点（伤亡数、罪魁、动机）

## Phase 3 — 历史漂移 + 物理载体 + Gameplay 反向钩子

从 flavor 层升级到系统层——历史开始反向影响 gameplay。

- [ ] **漂移**：每 50 年触发"转抄"——LLM 拿旧版本输入，加入有意的神化、人物合并、政治染色、记忆错误，输出新版本；保留所有版本可对比
- [ ] **物理载体**：每卷史书绑定到某个 holding 的图书馆建筑；围攻/洗劫/异端入侵/火灾可销毁该副本；"副本"机制允许把重要史书抄送修道院/外国宫廷；当本国孤本销毁、仅存外国副本时打上"流落他乡"标签
- [ ] **考古**：decision"翻修王室图书馆"（有概率发现遗失旧版本）、"派学者赴拜占庭"（有概率获取外国视角）；玩家首次看到外人视角时触发特殊情感冲击 event
- [ ] **Gameplay 反向钩子**：
  - 后代读祖先英雄事迹 → stress relief / 获得 inspired 修饰符
  - 敌国版本流入宫廷 → legitimacy 下降 event
  - 农民歌谣传播率高 → popular opinion debuff、起义概率上升
  - 教会"封圣"君主 → 王朝获得 permanent holy modifier
  - 处决史官 → 下一任史官更谄媚（更夸张但合法性加成更多）
  - 异端秘录被发现 → 触发宗教审判 event
- [ ] **不可靠史官系统化**：史官 traits 显式驱动 prompt 偏置参数（谄媚度 / 虔诚度 / 博学度滑块）；宫廷职位 UI 显示对未来书写风格的预览

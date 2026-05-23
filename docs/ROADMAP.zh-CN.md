# 路线图

[English](ROADMAP.md) · **简体中文**

本项目分四个阶段。每个阶段独立可交付、独立有价值。

## Phase 0 — 宫廷史官 + 农民歌谣（当前 MVP）

端到端管线。**必须支持存档文件导入**，不仅是实时事件钩子。暂无游戏内 UI，输出为浏览器 HTML。

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
- [ ] 3–5 个多样化存档（短局/长局/不同文化/不同宗教）上的费用曲线基准
- [ ] 主观输出质量评审（无出戏、无现代词）

## Phase 1 — 游戏内王室图书馆 UI

硬性要求：**与原生 CK3 视觉无法区分**。应该让玩家感觉这就是 Paradox 自己出的 DLC。

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

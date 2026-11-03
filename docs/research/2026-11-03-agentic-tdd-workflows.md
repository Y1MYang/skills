# Agentic coding 中的 TDD 工作流：证据、替代组织方式与 v3 的取舍

调研日期与所有在线来源访问日期：**2026-11-03**。范围：比较 TDD 的执行组织方式，帮助判断 `implement-spec-v3` 的细粒度交接是否值得保留。本文只读当前 skill，没有修改工作流，也没有实测其运行速度。

## 核心判断

**应当分别决定“行为例子多小”与“agent 交接多频繁”。** 保留逐例 Red → Green → Refactor，并不必然要求每个阶段经过主协调者、测试作者、Runner、实现者的多次交接。现有可读原始工作流中，Superpowers 让一个实现 agent 在任务内完成实现和测试，再在任务边界审查；其 TDD skill 仍要求一次一个行为并实际观察失败。[Superpowers：任务组织](https://github.com/obra/superpowers/blob/main/skills/subagent-driven-development/SKILL.md)、[TDD 循环](https://github.com/obra/superpowers/blob/main/skills/test-driven-development/SKILL.md)

**本文建议优先评估“一个 agent 持续执行局部 TDD，独立验收在外层”的双循环。** 这是基于下列资料作出的设计建议，并非已被实验证明比 v3 更快。若“所有测试及其依赖都必须由实现盲测一侧维护”不可放宽，则采用持续存活的测试作者／实现者配对，加自动执行器；不能把允许实现者编写内层测试的方案说成保持了原约束。

## 先明确什么仍然是 TDD

Kent Beck 的 canonical TDD 是先列行为场景，再把**恰好一个**场景变成可运行测试，修改实现直至该测试和已有测试通过，按需重构，再选下一个。他明确区分“列出测试清单”与“一次写完所有具体测试”，并指出不能把实现的实际输出复制成测试期望。[Kent Beck：Canon TDD](https://newsletter.kentbeck.com/p/canon-tdd)

Fowler 也把测试列表、逐项 Red–Green–Refactor 和接口思考联系起来；重构是循环的重要部分。[Martin Fowler：Test Driven Development](https://martinfowler.com/bliki/TestDrivenDevelopment.html)

据此，本文使用以下区分：

- **逐例 TDD**：每个新行为先有可运行的失败测试，再有实现；选择下一例之前恢复 Green。
- **测试先行但整批编写**：先写完整验收套件，再实现。这可以有价值，但不同于 Beck 的逐例过程。
- **测试后补／反馈修复**：先实现，再运行或生成测试并修复。它也可形成有效验证回路，不能仅因用了测试就称作逐例 TDD。
- **测试预期独立**：预期结果来自需求、公开契约或独立参考模型，不是被测实现的当前输出。
- **上下文隔离**：测试作者看不到实现。这是额外的防偏差机制；canonical TDD 本身没有规定测试与实现必须由不同的人或不同上下文编写。它与“预期独立”有关，但不是同一个条件。最后一点是对 Beck 过程与 v3 约束的比较判断。

## 四种可选组织方式

| 方式 | 一个循环由谁完成 | 独立性与质量控制 | 协调成本与适用条件 |
| --- | --- | --- | --- |
| 单 agent 局部 TDD | 同一个 agent 选例、写测试、确认 Red、实现、确认 Green、重构 | 测试期望依据需求；任务完成后可独立审查。没有作者与实现者的上下文隔离 | 交接最少；适合边界明确、可快速运行测试的任务。风险是同一理解错误同时进入代码和测试 |
| 外层验收 + 内层 TDD | 外层定义一个可验收行为；开发 agent 内部用多个小例子推进，最后外层变 Green | 外层验收可由独立作者维护；内层测试由开发 agent 维护 | 保留快速局部反馈，把独立验收放在行为／功能边界；必须允许部分测试不再实现盲测 |
| 持续测试作者 + 持续实现者 + 自动执行器 | 测试作者逐例产出，执行器记录 Red，持续实现者修改，执行器记录 Green | 测试文件及依赖仍由独立作者拥有；期望来源、版本与运行证据保留 | 可保持较强隔离；省去每次重建角色上下文和人工转述日志，但测试侧和实现侧仍串行交接 |
| TDD + 属性测试／定向 mutation | 基本 TDD 循环不变，在合适边界增加探索和测试敏感性检查 | 属性由领域规律推导；mutation 检查测试能否发现故意引入的错误 | 是补充，不是用例数越多越好；适合复杂输入空间、边界条件和高风险规则，可限制到改动范围 |

第一种有 Superpowers 的直接工作流参照。第二种的“内外双循环”来自 Harry Percival：外层功能测试保持 Red 时，内层单元测试进行多轮 Red–Green–Refactor，最终让功能测试通过；书中并未要求两个独立 agent，独立验收作者是本文的 agentic 改造。[Percival：Double-loop TDD 与工作流](https://www.obeythetestinggoat.com/book/appendix_IX_cheat_sheet.html)

第三种是本文面向 v3 的组合建议，**没有找到足以证明“持续双 agent 配对比其他方案更快”的直接比较实验**。DORA 的测试自动化指导支持开发者承担测试维护并让测试人员与开发者配对，强调缩短反馈等待；这是对人类团队的研究与指导，不能直接当作 agent 配对的效果证据。[DORA：Test automation](https://dora.dev/capabilities/test-automation/)

第四种已有成熟工具机制：Hypothesis 从策略生成输入，用属性或参考结果检查输出，官方明确其通常是单元测试的补充；Stryker 改变生产代码并观察测试是否失败，帮助发现断言薄弱处。[Hypothesis 官方教程](https://hypothesis.readthedocs.io/en/latest/tutorial/introduction.html)、[Stryker 官方说明](https://stryker-mutator.io/docs/)

## 官方指导、可用实现与实验结果分别说明什么

### 官方指导：把反馈和强制规则放入工具，留意新上下文的成本

Anthropic 当前 best-practices 文档强调给 agent 一个能够执行并返回结果的检查；需要必定执行的规则用 hooks／harness 实施。它也明确说明 subagent 的价值包括并行、隔离大输出和独立审查，但新 agent 重新收集上下文可能反而更慢。它没有证明每个 TDD 阶段都应该拆成 agent。[Anthropic 当前 best practices](https://code.claude.com/docs/en/best-practices)

访问时，常被引用的 2025 年 `anthropic.com/engineering/claude-code-best-practices` 已重定向到以上当前文档。因此这里没有把搜索摘要中的旧版 “write tests, commit; code, iterate, commit” 当作当前页面逐条核实后的建议。

### 可读取的原始实现：有不同粒度，源码存在不等于效果证明

Superpowers 把 TDD 指令和任务级 subagent 组织分开；任务内的实现者执行开发／测试，任务后审查，最后再做整分支审查。它在任务组织文档中承认新上下文和审查有成本。可借鉴的是**任务粒度与测试粒度分开**，不能据项目自述就声称其质量或速度优于 v3。[任务组织源码](https://github.com/obra/superpowers/blob/main/skills/subagent-driven-development/SKILL.md)

TDD Guard 使用 hooks 拦截不符合其 TDD 规则的写入，并有测试报告器及可选择的验证模型；其 README 现在建议新项目考虑后继 Probity。这证明流程约束可以移入工具，但不证明其语义判断绝无误判，也不代表所有判断是确定性的。本次仅核实原始文档，未安装运行。[TDD Guard 原始项目](https://github.com/nizos/tdd-guard)、[hook 配置](https://github.com/nizos/tdd-guard/blob/main/docs/installation.md)

### 原始研究：确有反例和收益，但任务定义不同

| 原始来源 | 观察到什么 | 本任务应保留的限制 |
| --- | --- | --- |
| [Böckeler：TDD inside the agent loop](https://martinfowler.com/articles/exploring-gen-ai/tdd-in-the-agent-loop.html) | 对少量 greenfield Python 任务比较 TDD、test-first 和没有 TDD 指令；没有看到清楚稳定的质量优势，TDD 过程产生更多回合／累计 token | 探索性小样本；Sonnet 4.6 生成，Opus 4.8 评判，部分基线复用。累计 token 含重复 cache-read，不能当美元成本或 v3 加速倍率；不能概括为“TDD 无效” |
| [TDAD，v1](https://arxiv.org/html/2603.17973v1) | 在其设定下，给出代码—测试影响关系比单独强化 TDD 程序指令更有帮助 | 两个较小本地模型、Python、100／25 个实例，无正式显著性检验。测试级回归和实例级回归方向并不相同，分母也受非空 patch 数影响。适合提出“先改善反馈定位”的假设，不能搬用宣传百分比 |
| [TDDev，v1](https://arxiv.org/html/2605.17242v1) | 比较整项目、逐功能、agent 自主反馈循环与无基础设施基线；结果依赖模型与协议匹配，浏览器验收及结构化失败反馈有价值 | §3.4 的逐功能协议是预给验收套件，再实现、部署、测试、修复；不是 Beck 的“逐例先观察 Red 再实现”。测试 agent 判断也可能有误。不能以其成本或质量数字证明 v3 应取消严格 TDD |
| [TDFlow，v2](https://arxiv.org/abs/2510.23761v2) | 将仓库修复定义为给定测试的求解，拆分提案、调试、修订及可选测试生成；体现独立测试输入对求解的价值 | 主要成功结果建立在人类编写测试已提供的条件上，不是一般 spec-to-code 的端到端结果，也不是一次一个新测试的 canonical TDD。公开仓库访问时仅见 README，不能称为已复现的完整开源实现：[仓库状态](https://github.com/AegisIK/TDFlow) |

这些研究没有直接比较“当前 v3”与表中的四种方案。本文没有复现其结果；不同模型、任务、测量口径和验收方式也不适合合并成一个提速结论。

## 对当前 v3 的具体含义

只依据本次读取的 [v3 主文档](../../skills/engineering/implement-spec-v3/SKILL.md) 与 [TDD loop](../../skills/engineering/implement-spec-v3/references/tdd-loop.md)，当前约束包括十种职责的显式模型选择、主 agent 仅派发、所有测试及其依赖由实现盲测一侧修改、逐例先经 Runner 确认 Red，再交实现者，最后绑定版本与回归证据。这些都可能产生协调开销，但没有运行时间分解时，不能认定哪个已是主要瓶颈。

runtime 的具体状态操作、锁和工作副本约束另见本次并行完成的 [本地反馈循环审查](../reviews/2026-11-03-implement-spec-v3-feedback-loop.md)。状态事件次数不等于模型唤醒次数；不能把必须记录的事件直接当成必须新派发一次 agent。

值得保留的目标是：明确行为、真实失败原因、需求导出的预期、实现不得擅改独立验收、当前版本的实际 Green、覆盖与最终交付一致。可以单独评估的机制是：每次角色切换、人工日志转述、全部文件访问都经主协调者委派，以及把每个例子结束都做成多方交接。

本文建议评估两条路径，不能混称为同一权限模型：

1. **允许放宽全部测试盲测：默认双循环。** 一个独立验收作者维护少量外部可观察行为及关键反例；每个独立工作流给一个持续开发 agent，在内部自主执行逐例 TDD。外层测试的变更仍回到验收作者，内层测试由开发 agent 维护。在可验收切片、接口变更及最终候选上审查，最终跑完整验收。不是把所有验收测试一次写完，也不是开发 agent 自行修改外层判卷标准。
2. **必须保留全部测试盲测：持续配对。** 每条依赖链保留一个测试作者、一个实现者；作者仍一次只写当前例子。用执行器自动运行、采集输出、绑定版本和回报状态，减少主协调者搬运。测试作者只接收获准的需求／公共契约／中性失败事实；不得因为“持续”而累积实现细节。需要判断失败性质、契约争议、测试有效性时再升级给相应角色。

两条路径都应避免把“一个测试”偷换成“一条断言”或“一次 agent 调用”。一个行为可以需要多个断言；多个未来行为也不应为了省交接而全部提前写进同一个测试。任务粒度可以是一段可验收切片，而切片内部仍逐例推进。

对于属性测试和 mutation，建议只在输入空间复杂或测试敏感性存疑处加入。Google 的工业研究采用只变异本次改动、过滤低价值 mutant、限制每行和每次审查的数量，说明补充验证也可按风险和改动范围控制成本。[Google：Practical Mutation Testing at Scale](https://research.google/pubs/practical-mutation-testing-at-scale-a-view-from-google/)

## 如何验证是否值得改

以下是建议的本地比较设计，不是已完成的实验：选择一组代表性任务，固定规格、基线、模型和最终独立验收，分别运行当前 v3 与候选流程，重复执行并交错顺序。把总耗时拆成模型生成／排队、上下文准备、agent 交接、测试运行、问题修复、最终验收；同时记录验收通过、真实回归、测试修改、漏测行为及用户介入。

报告中应同时保留 wall-clock、输入／输出／缓存 token 和实际费用口径；区分测试本身慢、环境不稳定、协调慢和需求返工。只在相同验收强度下比较完成时间，失败或跳过验收的运行不能作为“提速成功”。结果出来前，最稳妥的表述是：**有充分理由试着缩短协调路径，但仍需测量是否减少了总完成时间，并确认独立验收没有退化。**

## 检索与验证限制

- 只引用作者、官方文档、原始项目及原始论文；搜索中出现的博客转述、聚合站和社交帖未作为证据。
- GitHub `main` 与官方在线文档会更新；以上是访问日所见，不是固定版本审计。TDAD／TDDev 明确引用已读的 v1，TDFlow 引用 v2。
- 没有安装工具、运行外部示例或复现实验；“可用实现”表示存在可检查的原始工作流或工具，不等于已在本仓库验证兼容性。
- 当前 v3 只读主文档与 TDD loop，未审计完整 runtime／全部恢复协议；本笔记对潜在开销的判断是结构分析，不是性能剖析。

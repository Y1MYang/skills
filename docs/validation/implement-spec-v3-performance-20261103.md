# implement-spec-v3 执行优化验证记录

日期：2026-11-03。状态：本轮验证完成。两个本地 CLI 场景的逐对中位耗时分别缩短 17.20% 和 20.55%，经独立核算；候选多代理演练在隔离边界事件处理后完成，不描述为无例外的全流程独立性通过。

本轮分别验证公开运行工具的执行成本与真实多代理流程的正确性。命令级计时不包含模型推理、队列或代理交接时间，不能据此宣称完整任务提速。旧多代理基线受到用量限制中断，暂停边界未知，也不能用于计算端到端加速比。

## 变更与版本依据

依据[执行优化公共契约 Revision 1](../plans/implement-spec-v3-performance-contract.md)，本轮增加保留逐项历史的 `batch`、准备/执行/记录单次尝试的 `execute`，并将 `extend`、`include`、`revise` 的活动边界缩小到运行时计算的受影响闭包。持续职责上下文按逐例循环推进，主代理仍只调度；所有测试、helper、fixture 和配置修改仍属于实现盲侧。语义 Red 判断、独立测试资格、同一冻结候选的完整验收与双轴代码审查保持独立。

Revision 1 仅澄清已绑定的执行记录 ID 不能被其他事件占用，以及后续有效回归、待完成正式执行的准备快照属于修订影响分析的适用基线；API 形状不变。初稿与 Revision 1 均按原始字节另存，保留每阶段依据。

共同快照根目录限制仍在；本轮没有实现每个 worktree 独立绑定开发证据。每个事件边界及外部执行前后仍审计完整历史，未引入基于时间戳或跨命令的历史信任缓存。

| 已固定材料 | SHA-256 |
| --- | --- |
| [初始冻结契约归档](implement-spec-v3-performance-20261103/contracts/initial-performance-contract.md) | `3a9516c7f60df024b3696aaafc2afac373bce63871815546ca9d08f7d3a98ecd` |
| [当前 Revision 1 契约归档](implement-spec-v3-performance-20261103/contracts/performance-contract-revision-1.md) | `b6ede11f51d5c3a0f509d97e9026a0caadcb2900fb8cc14d10c223c5d2a48d0b` |
| [基线源码归档](implement-spec-v3-performance-20261103/baseline-source.zip) | `40a13fbd61f3e2af1a4bcc0a2a05a4ba6e6a61efe20ccb39a79312a0d8174cfb` |
| [基线逐文件清单](implement-spec-v3-performance-20261103/baseline-sha256.json) | `0070d9776344c32fd3aaa8db60a5f98326f215b70ce5cb0658df32598becc714` |
| [基线多代理完成记录](implement-spec-v3-performance-20261103/agent-eval/baseline/baseline-completion.json) | `97fe3df93b2062df79022603923659eb32405275e906aaec1b877cbaaa1d6fd3` |
| [候选源码归档](implement-spec-v3-performance-20261103/candidate-source.zip) | `6ecf887b34885875170efddf2fb80dd63cef8c7e7cf9cbd3a7c233316ed5aa3d` |
| [候选逐文件清单](implement-spec-v3-performance-20261103/candidate-sha256.json) | `af56002356909f1305fd630560704e41658dc3b6309c613033e2a70c5d20975c` |
| 候选 `scripts/cycle.py`，见上述归档 | `ad858e5bc5dd9458fc93ecd2865ae36004ddcba06e657c1fc131cfcd98d317b5` |
| [37 项独立测试历史版本](implement-spec-v3-performance-20261103/independent-tests/37-case-test-cycle-performance.py) | `f23993b2dabc2c907b2d5b461fe95674b280df66a8014c426a12fa146c841dda` |
| [43 项独立测试最终版本](implement-spec-v3-performance-20261103/independent-tests/43-case-test-cycle-performance.py) | `5b726580139693d62bd0ee2021473a2e14e0e30d6d19d42dbeb6ea0e294c22f1` |
| [最终双轴测试资格与完整核对](implement-spec-v3-performance-20261103/test-review/qualification-final.md) | `fd2419a486c7fbe01a56d4efc4ebf872c01ddebb41aa1033f379c906418820ff` |
| [冻结配对原始结果](implement-spec-v3-performance-20261103/matched-results.json) | `f43caafdd92c584435a8b50f23fb95fee1e459710b8d37b52703281b9a811675` |
| [测量分析与剖析摘要](implement-spec-v3-performance-20261103/analysis.json) | `3ed69229932b5832b8c9ca60dc6131a24cb03a9beb64cbdb25ce2b4747313937` |
| [独立统计与证据核算](implement-spec-v3-performance-20261103/independent-statistics-audit.json) | `15f7fcfed9514318a9a44048e88ebb0b54cdfecbce6368ecc264bccfab6b13e7` |
| [候选演练完成清单](implement-spec-v3-performance-20261103/agent-eval/candidate/completion-manifest.json) | `5c6bd871e2d175a5d5db9d1775db76977f4cdaa30b84f2f0b3b2c06d26bdacf8` |
| [候选演练完成时钟](implement-spec-v3-performance-20261103/agent-eval/candidate/completion-clock.json) | `fd5e366e865a3f29993213c124bd90f6acd95a59f42954773eeb5b0b9d75f1b8` |
| [候选完成证据独立核验](implement-spec-v3-performance-20261103/agent-eval/candidate/independent-completion-check.json) | `8e74c23fb99334f695694fb0736e025949cd485137c39423e8bd1e7f1e567b03` |
| [演练后纯文档修订清单](implement-spec-v3-performance-20261103/post-eval-docs/manifest.json) | `b356b9e7270e75c586eb3822348a13da82219ac9667d429312337965eb16b84a` |

本轮证据目录使用窄范围 Git `-text` 规则，保证存档、日志与摘要材料的字节不因检出时的换行转换改变；该规则不更改普通技能文件的换行策略。基准的源码 ZIP 归档是准确执行代码版本的依据，不以可能经过换行转换的工作区副本替代。

候选归档内 25 项源码与实际清单逐项核对通过。[冻结记录](implement-spec-v3-performance-20261103/candidate-freeze.json)绑定源码、测试及契约。ZIP 固定的是技能源码和测试；本报告及后续仓库验证文档的纯文档编辑在归档之外，不声称它们已包含于 ZIP，也未改变被测运行源码。首次冻结元数据误记了写入前 LF 文本的摘要，而磁盘清单使用 CRLF；已改为实际字节摘要，源码及 ZIP 未变，该修正发生在性能计时前。[修正记录](implement-spec-v3-performance-20261103/candidate-freeze-metadata-correction.json)保留旧值、实际值、原因和重建来源，不伪称旧元数据当时已另行存档。

2026-11-01 和 2026-11-02 的原始 manifest、日志及失败历史保持原样；它们不自动证明本轮改动。演练后补充的消息路由说明另存版本，不改写已经测量的候选归档。

## 公开 CLI 的配对性能验证

测量规程及复现命令见[性能证据说明](implement-spec-v3-performance-20261103/README.md)，执行工具为 [benchmark.py](implement-spec-v3-performance-20261103/benchmark.py)。实测环境为 Windows 11 10.0.26200、Python 3.12.10，机器报告 32 个逻辑 CPU；两侧使用冻结源码副本。每个场景、每侧先运行一次不计入统计的预热，再运行六个配对，顺序为 AB、BA、AB、BA、AB、BA。A 为基线，B 为候选。共 24 个正式测量试次与 4 个预热试次，没有测量试次失败或工作量不匹配。

| 场景 | 两侧必须完成的相同工作 |
| --- | --- |
| `small` | 两个串行行为例；一次真实失败 Green、诊断和修复；共享测试数据依赖补录与重构；刷新独立资格夹具、完整正式执行和最终账本核验。 |
| `history_logs` | 十二个串行行为例、累计回归和不断增长的历史；每个测试输出 32 KiB 确定性日志；完整正式执行和最终核验。该场景是合成压力案例。 |

基线分别调用 prepare → runner → record，候选使用 `execute` 完成相同机械步骤。两侧的原始事件 ID/顺序、真实结果、测试/契约/产品快照及最终源码必须匹配；不人为制造 `batch` 机会，不添加模拟代理延迟。外层墙钟包括项目夹具、Git、账本、真实命令、正式执行及核验；目标测试体时间、运行器管理时间和外层进程启动次数另列。剖析运行不混入计时样本。

| 场景（每侧 n=6） | 基线中位秒数（最小–最大） | 候选中位秒数（最小–最大） | 逐对缩短秒数的中位数 | 逐对缩短比例的中位数 |
| --- | --- | --- | --- | --- |
| `small` | 5.215（5.162–5.294） | 4.339（4.265–4.421） | 0.899 秒 | 17.20% |
| `history_logs` | 18.174（18.078–18.553） | 14.472（14.331–14.633） | 3.729 秒 | 20.55% |

逐对统计先对同一配对计算 `A_i − B_i` 和 `100 × (1 − B_i/A_i)`，再各取中位数；它们不等于直接相减或相除表中双方中位数。若直接用双方中位数计算缩短比例，则分别为 16.793979% 和 20.367922%，不是上表的逐对指标。以上是本机两个 CLI 夹具场景的墙钟观察。

[独立核算](implement-spec-v3-performance-20261103/independent-statistics-audit.json)从原始试次重新计算全部中位数、范围和配对比率，确认 24 个测量试次、4 个排除的预热、每场景六对 AB/BA 和零失败，输入文件核算前后摘要不变。它还核对全部 14 对的完整规范化事件载荷、结果、失败历史、最终源码以及 434 份 receipt 的请求和日志绑定，未发现差异；没有重新运行目标或重新计时。

实际外层进程启动数分别为 `37 → 25`、`120 → 70`，以每次 `commands.jsonl` 的实际启动记录核对，未推断后代进程数。两侧保留相同的原始事件数（24、88）、目标运行数（6、25）和累计断言案例数（10、168）。[完整载荷等价核验](implement-spec-v3-performance-20261103/equivalence-audit.json)对包括预热在内的全部 14 对比较原始事件载荷，仅规范化独立临时根路径、最终 Git SHA 和按准备顺序生成的 attempt ID；实际 argv、结果、快照及最终夹具源码另行比较。每份原始 receipt 重新核对摘要；计时、PID/归属 token 和日志摘要不是跨侧相等条件。候选额外保留执行绑定，因此不声称两个完整账本逐字节相同。

分段计时把主要节省定位到执行流水线的凭据管理区间之外：`small` 该区间中位数约 `1.640 → 0.740` 秒，`history_logs` 约 `7.076 → 3.464` 秒；目标测试体和凭据管理时长接近。另行剖析的 history 场景中，完整历史审计两侧均为 90 次、receipt 校验均为 1171 次，持久化次数也未减少；导入累计时间约 `4.270 → 2.747` 秒，受监管等待与状态持久化仍占明显成本。剖析累计时间包含嵌套调用，不能相加充当墙钟，也不混入上表样本。这些观测支持减少机械进程交接的局部收益，不支持删除审计或模型交接耗时已经下降的结论。

既有 `baseline-diagnostic-*.json` 与 `baseline-profile-*.json` 保留为诊断材料，未替代配对结果。[诊断失败记录](implement-spec-v3-performance-20261103/diagnostic-failures.json)保留早期 cProfile 包装器未传递目标退出码的问题和修正；它发生在正式测量前，不隐去为成功样本。每个场景只有六对本机样本，目标较短、history 日志量为合成负载，尚未验证其他机器、平台或大型真实项目。

`principle-explain-the-number` 指向的 `benchmark-checklist` 在仓库、已安装 skills 及扩展搜索中均未找到。未声称执行该缺失技能；本轮按上述已记录的匹配、交替顺序、预热、离散范围、剖析及等量工作核验规程执行。

此 CLI 基准的测试编写、产品修改、资格和代码审查输入均为明确标注的机械夹具，用于验证运行状态转换；它们不构成独立代理的真实审查。

## 真实多代理流程验证

### 已完成的基线

[完成记录](implement-spec-v3-performance-20261103/agent-eval/baseline/baseline-completion.json)记载：最终状态 `ready`，序号 25，干净候选 `412a10d159577f2b05b0acfc4641a4639b0258e6`；三个新行为均经历实际 Red → Green，累计七次尝试，正式执行四个测试通过。两个独立盲测审查轴、两个新建的实现可见代码审查轴均通过；额外原生 Windows 进程归属检查为 2/2。pending 与未解决失败均为零。完整记录保留原始事件、请求、凭据、日志和审查来源。

基线十职责使用此次明确选择的 `gpt-6.1-sol`，不形成后续调用的默认模型。首例测试作者曾读取最初派发允许、随后撤回的 `architect-report.json`；该读取与撤回顺序来自[作者报告](implement-spec-v3-performance-20261103/agent-eval/baseline/example1-author-report.json)。本轮实际检查[被读取的材料](implement-spec-v3-performance-20261103/agent-eval/baseline/architect-report.json)：内容是职责/模型元数据、基线 SHA、规格来源的依赖图、写入归属、预算和后续步骤，未发现产品源码、差异、算法、运行输出或实现行为观察。其自身要求向盲侧仅转交另行整理的安全包，因此保留为输入路由例外。

补救记录为撤回该指针并沿用安全包和 README；首例预期 `10000 → 0` 有规格依据，首例测试摘要与最终版本相同。未找到该作者被替换或首例被重写的记录。最终 Coverage、Spec 和 Standards 使用全新盲侧上下文，明确未读架构报告，仅从安全包、README 和四份测试独立评估预期、有效性及覆盖并通过。[最终资格](implement-spec-v3-performance-20261103/agent-eval/baseline/test-review-full.json)不追认先前路由和作者时间顺序；它将流程时间顺序明确留给流程所有者。因此本轮不将该基线描述为毫无例外的全流程独立性通过。

完成记录的 `1689.2540185` 秒为首个实际 Red 凭据开始至最终交付时钟的毛墙钟，排除了准备与首例测试编写，但包含用量限制中断。中断起点及净暂停时长未知，因此既不扣除估算暂停，也不与候选时长计算加速比。最初因时间解析截断产生的完成文件以 `baseline-completion-initial-timeparse.json` 保留，修正版保留实际交付时钟和原始时间来源。

### 候选

候选实际完成三个串行 Red → Green 循环，持久 Test author、Implementer 和 Runner 跨例复用；账本最终 `ready`、序号 25，第七次尝试在干净候选 `aa2aad4be8bd51fb6b8d0739f0b6ef8a2f221375` 上正式执行 4/4 通过。全新 Spec 与 Standards 代码审查绑定同一 HEAD 并通过；最终测试资格采用下述替换协调者的独立核对。十个职责的显式模型选择及实际派发报告保留在[完成清单](implement-spec-v3-performance-20261103/agent-eval/candidate/completion-manifest.json)引用的记录中，均为本次选择的 `gpt-6.1-sol`。

原 Coverage coordinator 为寻找缺失的 Integrator 地址调用全局 `list_agents`，接触了允许清单之外的实现侧完成摘要。原协调者退出，其 [test-full-review.json](implement-spec-v3-performance-20261103/agent-eval/candidate/test-full-review.json)保持未验证，未用于正式资格。两个轴报告的完成时间早于协调者事件记录；同轴上下文后来分别声明没有收到实现/全局状态转发。新的 `fork_turns="none"` 协调者仅接收安全包和原有清洁轴报告，重新完成[完整盲侧核对](implement-spec-v3-performance-20261103/agent-eval/candidate/test-review-full.json)，该报告才进入正式资格事件。

[来源审计](implement-spec-v3-performance-20261103/agent-eval/candidate/coverage-boundary-provenance-audit.json)保留明确限制：缺少逐工具时间戳转录，精确事件时刻与无转发顺序不能由文件独立严格证明；轴报告摘要是在后续审计时测得，不能充当历史时间戳证明。新协调者的独立资格不恢复原协调者资格，也不抹去本次边界事件。

独立完成核验逐项确认清单中的 93 份材料摘要与长度、25 个事件的完整 hash chain 和状态摘要、七份 receipt/request/log 绑定、同版本正式执行与实际 Git HEAD/干净状态，未重新运行目标。pending 为零，三个历史 Red 均有解决证据，原始失败与事件保留。

候选窗口为实际时钟 `08:18:40 → 08:32:11 UTC`，秒精度 **811 秒**，包含准备、全部等待、边界事件、替换协调者、来源审计和材料组装；完成时钟之后的独立核验、最终沟通及仓库文档修订不在该窗口内。协调者与 Integrator 报告的计数为 **12 个新上下文、9 次已知 followup**，包含此次修复；没有审计完整 wait/send 总数，不据此推断总模型唤醒数。基线既有中断且窗口排除了准备/首例编写，与此窗口定义也不同，因此不计算两者速度比。

演练揭示的文档执行细节已作窄范围澄清：安全派发包必须给出完整收件人标识、返回路线和已知非盲协调者；盲侧缺地址时向该协调者报告，不枚举全局 agent/chat 状态。规则集中在 dispatch 文档，recovery 仅增加内部引用。两份[修订快照及前后摘要](implement-spec-v3-performance-20261103/post-eval-docs/manifest.json)保留，原候选 ZIP 不变；运行源码、独立测试及公共契约未变。[独立文档复核](implement-spec-v3-performance-20261103/post-eval-docs/review.json)为 PASS，补充技能包装检查通过。此修订只约束后续执行，不作为原演练已遵循新措辞的证据。

## 回归、修复与历史保留

实际运行分开绑定，不能相加后宣称在最终源码上运行了同一套完整回归：

| 运行及源码绑定 | 实际结果 | 原始日志 |
| --- | --- | --- |
| 完整回归：`cycle.py` 为 `ceb0623f341e9565ddfe5a6db31bcc71b1d1f25c6b237ed8e54979eba201e113`，新增测试为 37 项历史版本 | 127 项，126 通过、1 项 POSIX 专属跳过、0 失败；172.031 秒 | [完整回归](implement-spec-v3-performance-20261103/runtime-tests/full-suite-before-alias-fix.log) |
| 最终路径等价修复：`cycle.py` 为最终 `ad858e5b…` | 6 项受影响检查通过；14.673 秒 | [修复后回归](implement-spec-v3-performance-20261103/runtime-tests/final-alias-regressions.log) |
| 最终新增测试组：`cycle.py` 为最终 `ad858e5b…`，测试为最终 `5b726580…` | 43/43 通过，0 跳过/错误/失败；78.799 秒，日志记录运行前后相同源码与测试摘要 | [最终 43 项](implement-spec-v3-performance-20261103/runtime-tests/final-43-tests.log) |

三个日志按实际字节归档，SHA-256 分别为 `f00ee4b72d8440e8f98657c3ad1f54f1cd4c6fea5cc1c44b68f752b5da9e2513`、`3e38a71bd2bc9cf87b656a4a1aa6c8170b97701744b83e85372b1f529dcfd25d`、`91ccf2f8547b0ce656f794bb2b6f7e96fd45776bdbd7459e2936e69e826e51ea`。完整回归的源码绑定由执行所有者报告；最终 43 项日志直接包含运行前后摘要。

完整回归后唯一运行实现变化是在深度/包含关系投影前检查实际路径等价。独立 S15 对硬链接等价测试路径观察到实际 Red → Green；Spec 审查者的独立公开 CLI [初始失败复现](implement-spec-v3-performance-20261103/code-review/spec-initial-alias-failure.json)与[最终通过复现](implement-spec-v3-performance-20261103/code-review/spec-final-alias-proof.json)分别保留。后者确认无关修订获准、原 pending 请求字节不变、原命令随后实际执行并记录，最终核验通过。它是审查者复现证据，不冒充独立作者的 S15 测试日志。

Spec 与 Standards 最终均向协调者报告 PASS，绑定最终 `ad858e5b…`，没有未解决的实质发现。Standards 通过字节比较确认逆转这一窄谓词变化即可得到此前完整回归版本。两个最终审查结论来自具名审查代理的结构化会话报告，未另存完整审查报告文件；上述 Spec CLI 复现是另外保存的实际运行材料。

[37 项初始独立资格](implement-spec-v3-performance-20261103/test-review/qualification-v1.md)对判据忠实性和有效性通过，但完整新增契约覆盖因缺失观察而失败。随后盲侧补齐未知 execute 字段、真实超时记录、执行后重新审计、重复混合依赖闭包和不改字节时的旧 gate 失效，另加入 S15；最终为 43 项。作者与最终审查的 test-only diff 核对确认原 37 项测试、helper、import 和 alias 未变。

[最终资格](implement-spec-v3-performance-20261103/test-review/qualification-final.md)对 37 → 43 的六项增量及依赖闭包分别完成盲侧 Spec/coverage 与 Validity/standards 审查，再核对完整新增运行契约，结论均为 PASS。其范围是新增运行正确性契约及继承兼容性依赖，不声称穷举原运行契约全部路径。未单独覆盖的分支、平台组合、无 claim 的特定重放路径和 batch 项间确定性篡改注入明确列为代表性覆盖限制；它们不是本轮未解决的实质发现。流程独立性与比较速度仍是另外的证据门槛。

E07 的先前失败保留为测试缺陷，而非产品 Red。作者的结构化会话记录说明：初稿把实际 claim 的 `controller.birth_token` 设为 null 后，未经 `recover` 就期待 `inspect` 返回 `ownership-unknown`；Runner 实际观察仍为 `prepared`。盲侧依据原运行契约纠正为先记录 resume invocation、调用 `recover` 并断言 `blocked/ownership-unknown`，再检查 execute 不重启及保留预约，最后恢复原 claim。纠正后首次有效运行 Green，未改运行实现。没有另存修订前 E07 源文件或该逐步日志，归档的 37/43 项均为纠正后版本；因此上述历史明确标记为作者/Runner 会话证据。

作者按同类逐例会话反馈汇总为 18 个真实 Red → Green、25 个首次有效 Green；该计数不冒充独立文件日志审计。另一次提出的 E06“被终止控制进程仍返回最终 JSON”增强要求经双轴重新裁定撤回，因为公共契约未承诺控制进程与 execute 是不同进程；原 E06 未变，已有正式预检失败夹具承担初始无凭据错误路径的覆盖。初始结论与纠正依据均在[持续资格记录](implement-spec-v3-performance-20261103/test-review/review-state.md)中保留。

包装检查中，v3 与 tdd 均通过 `python -X utf8 .../quick_validate.py <skill>`。首次使用 Windows 默认 GBK 读取 tdd 时出现 `UnicodeDecodeError`，改为解释器 UTF-8 模式后通过，没有修改技能内容。直接扫描 35 份未跟踪的活动文本与 107 个本地链接/锚点，未发现尾随空格、缺失路径或锚点；134 份保留原始字节的证据文本不参与内容重写，按存档摘要核验。独立工作流文档核对和独立安装包说明核对均未发现实质问题。

实际执行 `npx --yes skills add . --list` 发现本地 7 项技能，包括 v3 与 tdd。仓库要求的 `npx --yes skills add Y1MYang/skills --list` 也执行成功，但远端仅列出原有 5 项；本地未提交/发布的 v3 与 tdd 不能由远端列表证明可安装。这些发现与包装检查不替代运行测试或候选演练。

## 结论边界

- 运行源码、代表性测试资格、分版本执行、局部性能核算与候选演练均已完成；候选包含已处理并保留的隔离边界事件。
- 最终源码上的新增 43 项和六项受影响检查已通过；127 项完整回归属于此前源码，不能改写成最终源码上的新一轮完整运行。
- 运行工具的配对墙钟只能支持其已测场景的机械执行成本结论，不能外推模型耗时、所有项目吞吐量或完整开发任务加速。
- 用量中断使旧多代理基线不具备端到端速度比较资格；仍保留其正确性与审计证据。
- 基线首例的输入路由例外、E07 测试缺陷和 E06 审查纠正保持可见；未保存的逐例会话证据不伪装成独立日志。
- 候选旧协调者资格仍为未验证；最终采用新上下文的核对，精确事件顺序与全部上下文输入没有逐工具转录证明，不声称零例外的流程独立性。
- 当前平台验证为原生 Windows；不据此声称其他平台已经验证。
- 临时本地项目的完成不代表远端发布或真实 PR 交付；旧报告和旧 manifest 不被本轮覆盖。

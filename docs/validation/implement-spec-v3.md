# implement-spec-v3 与 tdd 验证记录

日期：2026-11-01。环境：Windows、Python 3.12.10、Git 2.56.0。

状态：实施与验证完成。机器可读结果见 [results.json](implement-spec-v3/results.json)，最终技能、工具和测试版本见 [manifest.json](implement-spec-v3/manifest.json)。

本报告及摘要固定于 2026-11-01 的实现版本。2026-11-02 的局部诊断预算策略修订另见[修订验证记录](implement-spec-v3-local-diagnostics-20261102.md)；原始摘要和执行证据不覆盖改写。

2026-11-03 执行优化的独立验证、配对测量与多代理演练另见[本轮记录](implement-spec-v3-performance-20261103.md)，包含明确的版本及隔离边界限制；本报告的历史结论与 manifest 不变。

## 范围

实现依据是[已定稿方案](../plans/implement-spec-v3.md)和[公共运行契约](../plans/implement-spec-v3-runtime-contract.md)。新增技能保留单向测试隔离、逐例 Red → Green → Refactor、关键契约关卡、每次显式选择十个职责模型、主代理只调度及完整规格同版本交付。v2 文件保持原样。

运行工具负责真实执行凭据、版本关系、预算、幂等事件和资源归属。它们不能机械证明需求解释、上下文独立性或模型实际派发；这些仍需审查与派发记录。

## tdd 实际演练与本地同步

独立代理在临时库存项目实际使用仓库版 tdd，完成 30 个逐例测试：15 个实际 Red → Green、15 个首次 Green、2 次 Green 后重构。48 份运行记录及文件快照的审计通过；最终 30 个测试通过，并由主任务另行复跑确认。

演练记录位于本机 `C:/Users/admin/AppData/Local/Temp/tdd-inventory-forward-86373322d53f405a9cfd78924f61ef33/`，包含 `REPORT.md`、`audit.json`、`runs.jsonl` 及逐次证据。复跑命令：在该目录执行 `python -B -m unittest -v`。

限制：可读的 Markdown 覆盖结果表在末尾汇总，逐例结果实际即时写入日志；原库存题目没有明确规定的数值类型边界记录为演练解释，不当作已确认需求。该演练验证通用 TDD 指令，不代替 v3 多代理流程演练。

仓库版 tdd 的四个文件已同步到 `C:/Users/admin/.codex/skills/tdd/`，逐文件 SHA-256 与仓库相符。同步前原稿保留在 `C:/Users/admin/.codex/skill-backups/tdd-before-v3-20261101-1cd5acb3/`；`manifest.json` 记录原稿，`sync-result.json` 记录同步结果。保留安装目录中的其他文件。

## v3 隔离流程演练

本次演练十个职责均使用用户明确选择的 `gpt-6.1-sol`；该选择仅属于这次演练，不成为技能默认值。实际多代理派发使用明确模型参数，测试侧从无继承历史的新上下文开始，演练主代理只调度。

临时项目位于 `C:/Users/admin/AppData/Local/Temp/implement-spec-v3-forward-e0__fzkv/`。规格包含运费四例、依赖运费关卡的结算两例、独立收据标签两例。各工具版本先复制为不可变快照，再对原有运行记录验证；升级保留旧工具、旧证据与预算。

演练实际发现并处理的流程问题包括：

- 测试发现命令缺少正确的顶层目录，导致环境失败。保留失败和消耗，仅修复命令，不能称为业务 Red。
- 初始权威规格转录添加了原文没有的精确类型限制。独立审查拒绝授予资格，Architect 按原文纠正，并刷新受影响证明。
- 快照清单遗漏实际共享测试初始化依赖。新增经过独立 Red → Green 验证的 `include` 操作，在同一运行内追加依赖、使旧当前证明失效，同时保留六个历史完成记录和已用预算。

最终八例全部完成，其中五例实际 Red → Green、三例首次 Green。关键关卡正式放行后才启动两个结算消费者；完整独立测试资格和两个全新代码审查上下文均通过。正式执行在同一干净候选 `a9cf2350f11bd715254412c714d22a4ec81ecfbb` 上通过 8/8，运行前后 HEAD 和快照稳定，资源清理完成。

原运行经 `record72 → finish73` 达到 `ready`。最后工具修订另存不可变快照后，再次核验原状态通过；state 字节、73 个事件、20 次尝试、模型选择、预算和正式 receipt 均未改变。主任务也直接用仓库最终 `cycle.py` 执行 `verify`，得到 `valid:true,last_seq:73`，并核对实际 receipt、日志摘要、候选 HEAD 和干净状态。pending 为空，历史失败均已有解释和解决证明。

最终使用 20/40 次尝试、0/2 次正式失败额度、4.249/1200 秒执行预算。这里的秒数是受监管命令时长，不是整个多代理开发的墙钟耗时。正式 receipt SHA-256 为 `31d144370f49428a339b42a6b8d055848bfe6810d0c03ff57d969cdd87ae4efd`。

最终本机交付指针是该临时根目录下的 `preparation/final-handoff-manifest-v2.json`；实际派发记录见 `evidence/dispatch-registry.json`，最终工具核验命令见 `evidence/final-delta-verify-commands.json`。三个临时开发流 worktree 已逐文件归档并核验后释放；集成候选、分支、原状态、历史失败和全部工具版本保留。没有发布远端或创建真实 PR。

## 运行工具与包装验证

主任务在冻结文件上统一执行：

```powershell
python -B -m unittest discover -s skills/engineering/implement-spec-v3/tests -p 'test_*.py' -v
```

结果为 **90 项，89 通过、1 跳过，116.041 秒**，原始输出见 [runtime-tests.txt](implement-spec-v3/runtime-tests.txt)。覆盖真实进程树和 Git 辅助进程的有限清理、不可变日志/快照、当前行为先 Red 后实现、既有能力出口、关键关卡、过期证据、并发预算、恢复、依赖追加、最终失败门槛和 Windows 路径身份。

这轮完整回归后，仅 `cycle.py` 的正式范围路径并集合并又做了一处调整：跨例子的同一文件别名须去重。该调整通过真实公共 CLI Red → Green、12 项受影响正式流程回归以及最终原状态核验；没有把之前的 90 项冒充为修改后的又一次完整运行。实现侧补充复现明确区别于独立测试资格，证据见 [scope-union-delta.json](implement-spec-v3/scope-union-delta.json)。

独立 Spec 和 Standards 代码审查均通过，绑定最终四个脚本的摘要。测试侧分别记录主循环、恢复、安全边界、九项证明规则和运行器修复范围的双轴局部资格；它们不声称穷尽整个公共契约。测试修改、运行事实和正式资格各自保留来源。

两项技能的 `quick_validate.py` 校验通过，技能内文件与锚点链接、marketplace、依赖安装路径及最终文档增量审查通过。`npx --yes skills add . --list` 实际发现七项技能，包括 v3 与 tdd；仓库要求的远端发现命令也运行成功，远端仍是未发布本次修改前的五项技能。v3 需要同时安装 tdd、test-review 和 pstack-principles；运行工具使用 Python 3.12+，正式候选需要 Git。

## 验证边界

- Windows 的进程归属、超时、中断恢复和无关进程存活使用真实进程验证。
- POSIX 适配代码存在；本机没有可用的 Linux 执行环境，对应平台专属场景跳过，不能声称已在 Linux 验证。
- 独立测试审查按文件和契约范围记录局部资格，不把部分覆盖称为整个公共契约的完整证明。
- 测试隔离边界曾两次触发恢复：运行器测试作者，以及后来已完成八项证明测试的作者，收到不应进入盲侧的实现信息后立即停止后续编写，固定此前测试版本，并把余下修改转交未接触实现的新上下文。正式审查者保持干净；不把替换前后的资格无条件互相沿用。
- 演练使用本地临时仓库，不发布远端；本仓库尚未提交或发布本次修改。

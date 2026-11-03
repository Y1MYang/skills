# implement-spec-v3 最小运行契约

状态：首版实施的公开契约，2026-11-01。第 1、2 节及第 3 节 init/inspect schema 已发布为 stable，后续扩展保持这些字段兼容。依据[已接受设计](implement-spec-v3.md)。测试作者与实现者分别读取本文件；本文不描述内部算法。首版只做下面两个 Python 标准库脚本，不建立通用调度框架。命令中的路径以调用进程 cwd 为基准转成绝对路径；清单内路径另按 `root` 解析。

2026-11-03 补充：[性能运行契约](implement-spec-v3-performance-contract.md)新增 `batch --events FILE` 与 `execute --request FILE`，保留原始事件、完整审计及既有命令。其第 4 节明确取代本文 `extend`、`include` 要求全部 flow inactive/全部 attempt settled，以及 `revise` 要求全部 attempt settled 的全局活动屏障：改为保守计算受影响依赖闭包，只阻塞受影响活动/未结算工作和 pending final。其余验证、历史、预算、独立测试与同候选交付要求不变；每流独立 workcopy 的证据绑定仍未引入。

## 1. 公共入口与通用 JSON 规则

```text
python scripts/run_command.py --receipt FILE --cwd DIR --timeout SECONDS [--snapshot FILE] [--formal] -- ARGV...
python scripts/cycle.py --state DIR init --plan FILE
python scripts/cycle.py --state DIR apply --event FILE
python scripts/cycle.py --state DIR inspect
python scripts/cycle.py --state DIR verify
```

脚本所在目录为 `skills/engineering/implement-spec-v3/`。两模块可导入，公开 `main(argv: list[str] | None = None) -> int`；导入无执行副作用。不承诺其他 Python API。所有命令 stdout 最后一行是 JSON 对象；诊断和进度写 stderr。cycle 成功退出 0，输入、证据或状态拒绝退出 2，返回 `{"ok":false,"error":{"code":"...","message":"..."}}`。错误不得把流程推进成功。

下文 shape 即首版 schema：字段除标明可选外均必填；未知字段拒绝；非空字符串不得只含空白；数字必须有限，布尔不是整数。所有文件为 UTF-8 JSON；schema 固定为整数 `1`；ID 区分大小写。SHA-256 为 64 位小写十六进制。稳定摘要使用 UTF-8 编码、对象键排序、无额外空格、`ensure_ascii=False` 的 JSON；数组顺序显式规定。状态和凭据是可信本地工具产生的审计材料，不是带签名的防恶意篡改系统。

路径身份与业务 ID 不同：scope 归属、路径重复及 write_paths 的相同/父子包含判断必须遵循实际文件系统的路径等价关系，不能只比较原始拼写。在大小写不敏感的 Windows 目录中，指向同一对象的 `Spec.md`/`spec.md` 属于同一 scope 来源，`src`/`SRC/module.py` 仍是重叠写入范围，不能借大小写、盘符或分隔符的等价拼写绕过。大小写敏感的文件系统保留其实际区别；缺失路径以最近存在的祖先及其适用的目录命名语义判断，不能因为对象尚未创建就把等价拼写视为隔离；无法可靠判断时拒绝该计划。显示路径和业务 ID 无须为此统一大小写。

## 2. run_command：有界、拥有归属的执行

`timeout` 是正数秒，覆盖预检（包括 Git 与初始快照）、启动和执行，不能对每个子步骤重新发放完整 timeout；另允许最多 5 秒终止及收尾。ARGV 至少一个元素，直接创建进程，默认不经 shell。stdout/stderr 分别写二进制日志。运行期间每 1 秒尽力向 stderr 实时发布下述进度事件，不在结束时集中补发；不得输出目标原始日志。工具自身退出码：目标退出 0 为 0，目标非零为 1，超时为 124，其他无法建立归属、启动或有效凭据的错误为 2。预检阶段已经耗尽总时限时，目标不得启动；可以退出 124 并输出 `ok:false` 的结构化超时错误而不发布缺少真实归属的 receipt。目标原始退出码只在 receipt 中保存。

每条进度为独占一行的 JSON 对象：`{"event":"progress","elapsed_seconds":1.5,"receipt_path":"absolute"}`。这三个字段必填；elapsed_seconds 是有限、非负的 JSON number（不是布尔），表示该事件生成时自本次运行预检开始的累计秒数，包含预检、启动和执行。允许整数截断，不要求特定小数位数；报告值与事件生成时实际累计值的表示误差须小于 1 秒。此精度规则不把接收端调度或传输延迟算作表示误差，也不新增项目业务 SLA。1 秒是尽力发布的目标周期，不保证相邻事件的严格最大间隔；持续超过一个周期的命令应在结束前让调用方读到进度，不足一个周期的命令允许没有进度。stderr 允许同时有其他诊断行；消费者仅将可解析且 event 为 progress 的 JSON 对象识别为进度，不能从其他文本的任意数字推断计时。进度对象允许追加字段，消费者按上述公开字段解析。

预检超时但尚无 receipt 时，错误对象为 `{"ok":false,"error":{"code":"timeout","message":"..."}}`；如能发布超时 receipt，则 outcome 为 timeout、exit_code 为 null。超时之后所有终止和收尾共享最多 5 秒，不为每个收尾步骤重新计时。

已发布 receipt 时，stdout 最后一行为 `{"ok":true,"receipt_path":"absolute","outcome":"exited","exit_code":0}`，后三个值来自实际结果；即使目标非零，`ok:true` 仍仅表示凭据已生成。无法发布凭据时使用第 1 节的错误对象。目标输出只进入日志。

receipt 路径及其 `.stdout.log`、`.stderr.log`、`.claim.json` 伴随路径必须尚不存在；原子独占 claim 后才可启动目标。相同路径第二次调用拒绝且不执行目标；失败也不能覆盖旧材料。所有路径应放在待测工作树外。结束凭据先写临时文件、同步后原子发布；日志在发布前关闭。保留原始日志且记录实际字节摘要。

claim 的公开 stable shape 为 `{"schema":1,"receipt_path":"absolute","token":"unique-id","controller":{"platform":"windows|posix","pid":123,"birth_token":"native-token-or-null"},"created_at":"UTC ISO-8601"}`。birth_token 是字符串或 JSON null；Windows 必须为控制进程 `GetProcessTimes` 创建 FILETIME 的十进制字符串；POSIX 有可核验的本机进程出生标识时记录，否则为 null。token 与 receipt.owner.token 相同，controller.pid 指运行器自身而非目标。恢复须重新读取平台事实核对 PID 和 birth_token，不能把存档 claim 本身当作存活证明。claim 仅证明控制进程连续身份，不授予裸 PID 终止权；POSIX 缺少出生标识或无法确认后代归属时返回 ownership-unknown。Windows 控制进程已终止且身份可确认时，Job 的 kill-on-close 允许将无结束凭据的 attempt 判为 interrupted。

另有仅由 recover 创建的取消变体：`{"schema":1,"receipt_path":"absolute","cancelled_attempt":"attempt-id","created_at":"UTC ISO-8601"}`。该文件同样占据 `.claim.json`，与正常 claim 互斥；执行器遇到任意已存在 claim 都拒绝启动，因此不必理解 cycle 状态。

执行器为本次运行启动的辅助进程（包括 formal 预检和收尾的 Git 命令）及其后代，与 ARGV 目标同受本节既有所有权、总 timeout 和共享最多 5 秒终止及收尾时限约束。

Windows 必须使用带 `KILL_ON_JOB_CLOSE` 的 Job Object：先创建等待 stdin 授权的 bootstrap，把 bootstrap 加入 Job，成功后才发送启动目标的授权。归属建立失败或授权前父进程死亡，目标不得启动。Job 包含目标后代；超时或监督进程退出时只终止本次 Job。POSIX 使用独立 session/process group，超时先终止本次组，有限宽限后强制终止；禁止以名字或复用裸 PID 清理。首版 POSIX 不承诺管住主动逃离 session 的敌意程序，也不承诺 SIGKILL 监督器后的自动清理；恢复必须拒绝无归属证明的杀进程操作。主目标退出后终止仍存活的本次后代；如果无法确认清理，receipt 不得标记为可接受的成功。

可选 snapshot 输入：

```json
{"schema":1,"root":"/absolute/worktree","tests":["tests"],"contract":["spec.md"],"product":["src"],"binding":null}
```

三个数组各非空，元素为 root 内唯一的相对文件或目录路径，不支持 glob、`..`、绝对路径或符号链接/目录联接。目录递归枚举普通文件，目录清单自身也入摘要，故增加、删除和空目录变化可检测；缺失的声明路径显式记录为 `missing`，不能静默跳过。排序使用规范化 `/` 相对路径的 Unicode 字典序。tests 必须显式包含其 helper、fixture、配置等依赖；依赖完整性由代理审查。无 snapshot 的命令可运行，但不能用于 cycle 推进。

实际 capture shape：`{"entries":[{"path":"src/a.py","kind":"file","sha256":"...","size":42},...],"sha256":"..."}`。目录项为 `{"path":"src","kind":"directory"}`，缺失项为 `{"path":"src/a.py","kind":"missing"}`；组摘要只计算排序后的 entries 数组。工具从文件字节计算，拒绝只采用调用者提供的摘要。执行前后分别 capture 三组；任何组在运行期间变化，凭据可记录结果，但不具备 cycle 接受资格。

receipt shape（对象内字段均固定，`snapshot` 可为 null）：

```json
{
  "schema":1,"receipt_id":"unique-id","argv":["python","-m","pytest"],
  "cwd":"/absolute/worktree","started_at":"UTC ISO-8601","ended_at":"UTC ISO-8601",
  "duration_seconds":0.5,"timeout_seconds":20,
  "outcome":"exited","exit_code":1,
  "owner":{"platform":"windows","kind":"job","token":"unique-id","pid":123},
  "cleanup_complete":true,
  "logs":{"stdout":{"path":"absolute","sha256":"...","size":0},"stderr":{"path":"absolute","sha256":"...","size":0}},
  "snapshot":{"request_sha256":"...","binding":null,"before":{"tests":{},"contract":{},"product":{}},"after":{"tests":{},"contract":{},"product":{}}},
  "formal":{"requested":false,"head_before":null,"head_after":null,"clean_before":null,"clean_after":null}
}
```

`outcome` 为 `exited|timeout|launch_error|ownership_error|interrupted`；非 exited 的 `exit_code` 为 null；POSIX owner 为 `platform:"posix",kind:"session"`。capture 占位 `{}` 使用上文 shape。实际快照请求文件完整字节的 SHA-256 为 `request_sha256`。cycle 重新计算 receipt 文件、日志、请求文件的摘要，不相信调用者传入的结果。内容摘要证明材料一致性，不证明记录作者身份。

必须取得目标自身的完整结果才可记录 `exited`，不能使用 bootstrap 或其他监督层的退出码替代。监督层提前退出而目标没有完成结果时，CLI 退出 2；可以返回 `ok:false` 的结构化错误而不发布 receipt，也可以发布非 `exited`、`exit_code:null` 的可审计中断 receipt 并返回相应 `ok:true` 结果。两种路径都保留可用日志和归属清理事实，均不构成目标执行成功。

`--formal` 要求 cwd 位于 Git 工作树。执行前、后均读取真实 HEAD，检查 `git status --porcelain --untracked-files=all` 为空；两端 HEAD 必须相同，snapshot 三组必须稳定。运行前脏树直接拒绝启动；运行后变脏或 HEAD 改变时保留凭据但无正式资格。运行前后检查不能证明中途曾改动后恢复的文件；候选冻结仍是流程责任。

## 3. cycle：计划、稳定身份与证据事件

init plan：

```json
{
  "schema":1,"run_id":"run-1","workspace":"/absolute/worktree","spec_sources":["spec.md"],
  "models":{"exploration":"MODEL","architect":"MODEL","test_author":"MODEL","implementer":"MODEL","runner":"MODEL","integrator":"MODEL","coverage_audit":"MODEL","spec_reviewer":"MODEL","standards_reviewer":"MODEL","expert":"MODEL"},
  "budget":{"max_attempts":20,"max_formal_failures":2,"max_seconds":600},
  "flows":[{"id":"main","write_paths":["src"]}],
  "examples":[{"id":"fee-99","flow":"main","requirement":"REQ-1/example-99","depends_on":[],"snapshot":{"schema":1,"root":"/absolute/worktree","tests":["tests"],"contract":["spec.md"],"product":["src"],"binding":null}}],
  "gates":[{"id":"fee-contract","prerequisites":["fee-99"],"consumers":[]}]
}
```

十个 models 值必须在本次 init 明确完整给出，无默认或从旧运行补齐；新的技能调用包括恢复必须按下文 invocation 事件再次明确记录全部十个选择，旧表仅作为历史保留。三个 budget 均大于零，前两项为整数。spec_sources、flows、examples 非空，gates 可为空。flow/example/gate ID 各自唯一，requirement 例子身份在计划内唯一。行为清单允许通过下文 extend 事件追加遗漏例子，通过 include 事件补充既有例子的快照依赖；除此之外既有条目固定，不提供删除失败例子或改稳定 ID 的 API，显示标题可写在审查文字内。并行 flow 的 write_paths 不得相同或存在父子包含关系；Git worktree 和合并由代理管理，工具不自动合并。

首版所有 example.snapshot.root 规范化后必须等于 plan.workspace；formal 并集使用这个共同 root。外部 worktree 的合并先落到此权威 workspace 后取证，不把不同目录的摘要直接合成为集成证明。gate ID 保留字符串 `final`，计划使用它时拒绝。

init 成功输出 `{"ok":true,"run_id":"run-1","state_dir":"absolute","created":true}`。对同一 state 和完全相同的规范化 plan 重复 init，返回同样对象但 `created:false`，保留全部状态和计数；不同 plan、损坏状态或其他 run 已占用的 scope 返回错误且不覆盖材料。缺角色和无效预算必须在创建成功状态之前拒绝。首次 inspect 中 status 为 active、last_seq 为 0，models 为完整原表，budget 四项均为 0，pending_attempts/failures 为空数组，active_by_flow 把每个 flow ID 映射为 null；examples 把每个例子 ID 映射为 `{"state":"planned","mode":null,"attempt_ids":[]}`；gates 把每个 gate ID 映射为 `{"state":"pending","attempt_ids":[]}`。后续条目可追加字段。

同一仓库、同一规范化 spec_sources 路径集合形成 scope 身份，不依赖 run_id、state 目录或切片标题。init 在 Git common-dir 的 `implement-spec-v3/` 下（非 Git 则 workspace 的 `.implement-spec-v3/` 下）保存 scope → run_id/state 的独占锚点，以及实际 spec_sources 内容摘要。活跃 scope 已存在时，换 run_id 或 state 目录不能重建预算；原状态丢失则 fail closed，恢复原材料。旧 run 的历史 finish、固定 HEAD 和审计材料可核验完整，spec_sources 内容确已变化且显式给出新 run_id 时，可 init 新需求运行；这里核验的是旧 run 曾完成的历史，不要求旧资格在新规格文件上仍当前有效。锚点保留旧 run/state/摘要历史，不能覆盖旧失败记录。首版不提供活跃运行的预算重置。复制整个仓库、改写 spec_sources 来冒充新需求属于代理审查边界。

apply 事件公共字段为 `{"schema":1,"op_id":"unique-id","op":"...",...}`。只记忆已成功落盘的事件：同 op_id、同事件内容重放返回原结果，不追加记录、扣预算或启动命令；已成功落盘的 op_id 再配不同内容时拒绝。busy、输入/证据验证拒绝和前置门槛拒绝不消耗 op_id、不追加成功事件、不推进序号或预算，因此同 ID 同内容可以在条件修复后重试。记录完整 ineligible 结果及返回 blocked/running 的 recover 仍是成功落盘的事实事件，适用重放规则；重新观察须使用新 op_id。状态目录单一写入者；并发 apply 要么串行成功，要么明确 busy，不能丢更新。成功事件持久化后才响应；事件序号严格递增，含前事件摘要与本事件摘要。对已有记录缺失、重排或内容修改，verify/recover 必须拒绝，不能静默重建为干净状态。

`extend` 只追加独立覆盖审查发现的遗漏例子及其必要 flow/gate，事件 shape 为 `{"schema":1,"op_id":"...","op":"extend","source":"需求依据","reason":"补充覆盖的原因","examples":[...],"flows":[],"gates":[]}`。source/reason 均为非空字符串；三个数组均显式提供，examples 非空，条目复用 init 中对应 shape。所有 flow 均无活动例子、没有未结算 attempt，且本 run 仍拥有 scope 锚点时才可接受；尚未开始的 planned 例子不阻止追加。对旧清单做纯追加后，重新验证完整计划的 ID/requirement 唯一性、路径范围及写入隔离、引用存在性和全图无环；任何一项失败则整次拒绝，不能部分追加。

extend 不能提供已有 ID，即使内容相同也拒绝；新例子可引用已有或本次新增的 flow/依赖。新 gate 可引用已有或新增例子，但其 consumers 必须全部尚未 open，不能事后给已开始行为补检查点。旧条目（包括既有 gate 成员）、run_id、workspace、spec_sources、models、预算上限和已用/预约计数均不改变；原始 init plan 保留，重复 init 仍与该原稿比较，当前有效清单由原稿与已接受 extend 事件累计得到。旧 close、失败、执行与资格历史继续可审计。预算不足仍会阻止后续 prepare，追加不能恢复额度。

成功输出 `{"ok":true,"op_id":"...","added":{"examples":["new-id"],"flows":[],"gates":[]},"status":"active"}`，added 数组按事件输入顺序列出新 ID。inspect 中新增例子为初始 planned 条目、新 gate 为 pending、新 flow 映射 null。由于 final scope 成员扩大，旧 final 资格、正式运行及 ready 的当前效力一律失效，即使文件摘要尚未变化；重新完成全范围审查和正式运行后才能 finish。finish 采用的 final qualify 和 prepare-formal 事件序号必须都晚于最近一次成功 extend，旧 attempt 不能经重复 record 或 finish 恢复当前资格。已有例子的历史 close 保留，未受文件变化影响的既有 gate 资格可继续使用。资格和正式 attempt 在状态中同时绑定当时的 scope 例子 ID 集合与内容摘要；成员变化不能仅凭相同文件 hash 复用旧范围结论。

`include` 仅补充遗漏的快照依赖，事件 shape 为 `{"schema":1,"op_id":"...","op":"include","source":"依赖依据","reason":"补充原因","items":[{"example":"existing-id","tests":["tests/__init__.py"],"contract":[],"product":[]}]}`。source/reason 非空；items 非空且 example 不重复，必须引用已有例子；每项三个路径数组都显式提供，可各自为空，但每项至少新增一条路径。路径按原 snapshot 规则验证，并且不能与该组已有声明或本事件同组路径规范化后重复。只向对应数组追加，root、requirement、ID、flow、depends_on 及其他字段不变；不能删除、替换旧依赖或借此修订行为语义。

include 只在全部 flow 无活动例子、没有 pending attempt、且本 run 仍拥有 scope 锚点时接受；先验证全部 items，再原子追加事件。已 closed 的例子保持历史完成，所有原始执行、失败、预算上限及已用/预约计数保留。原始 init plan 保留，当前声明由 init、extend、include 事件累计得到。成功输出 `{"ok":true,"op_id":"...","included_examples":["existing-id"],"status":"active"}`，included_examples 按 items 输入顺序排列。

include 使所列例子的当前运行证明过期，并使 scope 含任一所列例子的测试资格、gate release 和正式运行过期；final 的 ready 当前效力同时撤销。历史材料继续保留，未受影响的 gate 可继续使用。即使新声明没有改变文件内容摘要，也必须重新取得受影响范围的双轴资格和运行证据；相关 qualify、prepare-formal 必须晚于该范围最近一次 include。所列 closed 例子用回归或覆盖它们的正式运行刷新证明，不重新制造 Red。依赖范围补全的充分性由独立测试侧审查；include 不授予额外预算。

### 3.1 最小逐例循环

| op 与额外字段 | 机械门槛和结果 |
| --- | --- |
| `open`: `example`, `light_check:{source,observation,expected_failure,independent_context}` | 四个值为非空字符串。依赖例子已 close，依赖 gate 已当前有效；同 flow 无其他活动例子。记录当前三组实际 capture。 |
| `prepare`: `example`, `purpose`, `timeout_seconds` | purpose 为 `probe|green|regression`。持久化唯一 attempt、序号、时间、预算预约，再输出 `attempt_id,request_path,receipt_path`；只创建请求，不启动命令。每 flow 至多一个未结算 attempt。probe 从 open 开始；green 要求当前有效 Red；regression 要求 green/existing 或历史 closed，可刷新已完成例子的当前证据而不重新制造 Red。 |
| `record`: `attempt_id` | 只从 prepare 给定的 receipt_path 读执行器凭据；核验文件/日志/request 摘要、binding、起始时间晚于 prepare、timeout 一致、cleanup 完成，再判定 snapshot 稳定性及推进资格。记录原始执行事实，不能由事件提供 exit code/hash 替代；完整但 snapshot 不稳定的结果按下文 ineligible 路径结算。 |
| `judge`: `attempt_id`, `classification`, `reason`, `evidence` | classification 为 `valid-red|existing|implementation|test-defect|environment|business-decision|unknown`；reason 非空，evidence 为非空材料标识数组。只有 probe 的真实 exited 非零可被判定 valid-red；只有首个有效 probe 的真实 exited 0 可被判定 existing。其余失败分类不解锁实现。 |
| `diagnose`: `attempt_id`, `reason`, `evidence`, `next_action` | 为失败或中断追加新诊断，三个文字/数组非空，evidence 至少有一个该失败此前诊断未使用的标识。没有诊断的非正常失败阻止下一 prepare；unknown/business-decision 保持阻塞，需后来明确分类。 |
| `close`: `example`, `regression_attempt_id` | 当前 green 或 existing 存在；回归 receipt 为 exited 0 且与当前实际三组摘要相同。green 与回归可以是同一 attempt，但需其 purpose 为 green，且 close 增加非空 `regression_scope` 说明命令覆盖范围；否则需独立 regression attempt。释放 flow。 |

prepare 请求沿用该例 snapshot，binding 固定为 `{"run_id":"...","example":"...","gate":null,"attempt_id":"...","purpose":"probe","prepared_seq":3,"prepared_at":"UTC ISO-8601"}`；在请求根对象增加必填 `timeout_seconds`，与 schema/root/tests/contract/product/binding 并列，不放在 binding 内。runner 接受此扩展 shape，验证其 timeout 与 CLI 一致；receipt.snapshot.binding 原样保留 binding，receipt 根字段 timeout_seconds 保存时限。无 binding 或未知 attempt 的旧凭据不能推进。receipt 实际开始时间及不可重排的 prepare/record/judge 顺序共同约束证据；调用者补写 timestamp 不改变序号。

若真实 receipt、日志和 request 完整且其摘要、binding、时限、顺序及归属清理均可核验，唯有 snapshot.before 与 after 任一组不相同，record 必须保留这些已知执行事实并清除该 attempt 的 pending，按 receipt.duration_seconds 结算及释放预约；不能把它改写为 interrupted。该 attempt 永久不具推进资格，追加 `classification:"ineligible",reason:"snapshot-changed",resolved:false` 的失败条目。record 此分支退出 0，返回 `{"ok":true,"attempt_id":"...","eligible":false,"reason":"snapshot-changed"}`；原 receipt/outcome/exit_code/快照及日志原样保留。hash、binding 或审计链损坏仍以退出 2 拒绝，不得混入此分支取得结算资格。

ineligible 无论目标退出码为何，都不能形成有效 Red、existing、Green、回归、gate 或 final 证据，judge 不能将该 attempt 改判为有效。它按实际时长消耗预算；如果来自正式 attempt，再消耗一次正式失败额度。后续 diagnose 可以追加修复依据，然后按原有 revise 或重新 probe 规则继续；仍须满足当前基线和独立测试判据要求，不能重用该不合格 attempt。清除 pending 不抹去原失败，也不自动取消当前活动切片。

第一次 probe 的三组 before 必须等于 open。valid-red 记录落盘后才能 prepare green；green 的 tests/contract 必须与该 Red 完全相同，product 可变化。green 必须实际 exited 0；有效 Red 本身是正常开发结果，不能被记为正式失败。existing 保留单独完成模式 `existing`，并要求 judge.reason 说明测试有效性；close 输出模式只可能 `red-green|existing`。工具只证明运行顺序和版本对应，不证明代理未在 Red 之前偷偷编辑后恢复实现。

任何后续 op 使用旧证据前，都重新 capture 相关当前文件；test/helper/fixture/config/contract 的变化使依赖该摘要的当前 Red→Green 配对、Green、资格、gate 证明过期。product 变化使旧 Green/正式运行不能冒充当前结果。**closed 是历史完成事实**：添加下一例测试、正常产品演进或共享文件摘要变化均不自动撤销历史 close，不强迫完成例子重新 Red。已 closed 例子可 prepare regression，在 record 成功后刷新当前证据；当前 flow 有其他活动例子时先完成该例再刷新历史例子。受影响判据资格仍须独立重新 qualify。

需要撤销当前尝试/完成资格（行为语义变化，或有诊断依据的测试、依赖修复）时使用 `revise`，字段为 `examples:[id,...],source,reason`，要求已无未结算 attempt；重取所列例子的 snapshot，将其当前状态置为 planned 并释放对应 active flow，撤销其当前完成资格，重新 open/probe，保留全部历史 close、失败、attempt 与预算。活动例子发现漏列依赖时，可先 diagnose/revise 回到安全边界，再 include 并重新 open/probe；不能删除旧失败或恢复额度。工具对所有声明 snapshot 重新求值，自动将共享依赖命中的证明标为过期，不能只相信调用者自选的受影响列表；哪些变化属于语义修订由代理审查。产品合并后，必须对集成版本重跑回归及所需正式运行。

### 3.2 依赖、正式资格和最终候选

依赖图使用 `前置例子 → 依赖例子`、`gate.prerequisites → gate → gate.consumers` 的有向边。init 和 extend 合并后的完整计划均拒绝缺失引用、自环或任意间接环；不能让 gate 前置例子通过其他节点依赖其消费者。gate 前置例子之间只按普通 close 推进，未通过 gate 仅阻塞 consumers。

gate scope 的验收集合严格是其显式 prerequisites；传递依赖负责调度，不隐式扩大验收范围。需要一并验收的祖先例子应显式列入 prerequisites。final scope 是全部 examples。路径并集去重并按规范化相对路径排序。

`qualify` 事件：`scope` 为 `{"gate":"id"}` 或 `{"final":true}`；另有 `spec_review,standards_review`，每个为 `{"review_id":"...","source":"...","independent_context":"...","verdict":"pass"}`。工具存储该 scope 内例子当前 tests/contract capture；任一轴缺失或不通过不能授予资格。qualify 不要求例子已 close：revise 撤销完成后，仍可先对新版测试取得资格，但 prepare-formal 独立核验完成门槛并拒绝未重新 close 的例子。测试资格不等于产品完成。两轴的忠实性、可靠性与隔离由审查代理负责，字符串本身不能证明这些语义。

`prepare-formal` 事件字段为 `scope,timeout_seconds`；要求 scope 例子全部历史 close 且未经 revise 撤销、资格当前有效，使用所含例子 snapshot 的路径集合并集，并输出与 prepare 相同的三个路径/ID。binding 的 example 为 null，gate 为 gate ID 或字符串 `final`，purpose 为 `formal`。运行必须加 `--formal`。`record` 以实际 receipt 结算；成功且当前有效的正式运行也为该 scope 全部例子刷新累计回归证据，不要求为旧例子重造 Red。`release` 事件字段 `gate,attempt_id`，要求该 gate 的正式 receipt 成功、Git clean 前后为 true、HEAD 相同、当前真实 HEAD 和快照仍一致，才放行 consumer。新提交使旧 release 无当前资格；consumer 再 open 时重验。

`finish` 事件字段 `attempt_id,code_reviews`；code_reviews 为 `{"spec":{"head":"...","review_id":"...","verdict":"pass"},"standards":{"head":"...","review_id":"...","verdict":"pass"}}`。要求 final scope 的有效双轴测试资格、全部例子历史 close 且未经 revise 撤销、完整范围正式运行提供当前候选的累计回归通过证据，两个代码审查与正式运行及当前 clean HEAD 完全一致。此外，所有 flow/scope 的 pending_attempts 必须为空，且不得存在未解释或未解决的失败；此条件不限于 final attempt。成功输出 `status:"ready",head:"..."`。最终覆盖充分性和实际代码审查由代理证明，工具仅核验已记录覆盖集合、两个通过结论和相同候选。

旧成功不能覆盖其后的实际失败。diagnose 只补充解释和修复依据，不自动刷新成功证明或把失败设为已解决；除正常 valid-red 外，每个失败必须有诊断，并由该诊断之后准备的合格正式运行覆盖其失败范围，才可在 finish 门槛中视为已解决。例子 attempt 的失败范围为该例，正式 attempt 的失败范围为其当时完整 scope；后续正式 scope 必须包含该范围。原失败条目、原因与计费保留，resolved 可据新证明变为 true；ineligible attempt 本身仍永久不具资格。所选 final 成功不能早于任何需要它证明已解决的失败，后续出现的 pending 或未解决失败会阻止复用旧 final。只有与当前交付候选版本一致、资格当前有效且 snapshot 稳定的真实成功正式运行才能刷新该范围的证明。

消费者 `open` 重新核验 gate 的 HEAD 与声明的快照依赖，但不要求整个开发工作树保持 clean。为消费者新增、尚未提交的测试或其他不在 gate 依赖范围内的文件，不应仅因工作树 dirty 而撤销 release；若改变 gate 的实际依赖或 HEAD，则仍按过期规则重新验证。clean 要求用于正式执行、release 和最终 finish，不能阻止先写消费者测试再实现的正常开发循环。

gate.release 也保留历史与当前效力的区别：H1 的 release 已合法放行消费者，消费者完成后提交 H2，不撤销该历史放行；H1 证明不能再用于 H2 上新的 consumer.open。verify 核验旧 release 的历史材料完整性，不因其不再匹配当前 HEAD 而单独失败；当前 final 候选由自身的完整资格和正式运行证明，不要求仅为历史审计重发所有 gate。对实际正在采用的当前证明仍执行版本核验。

### 3.3 预算、恢复和审计

每次 prepare（含 formal）先消耗一次 max_attempts 额度，预约 timeout_seconds，预约总和不得超过剩余 max_seconds；record 按真实 duration 结算，包括完整但 ineligible 的结果。无可核验结束凭据的中断 attempt 保守消耗全部预约秒数。正式非零、超时、中断或 ineligible 各消耗一次 max_formal_failures，同一 attempt 即使符合多个失败条件也只扣一次；预期开发 Red 只豁免该项，不豁免 attempts/seconds。达到任一限额后拒绝新 prepare；诊断、核验、恢复和读状态仍可执行。超预算的结果不能补造成功。

`invocation` 事件字段为 `kind:"resume",models:{十角色完整表}`：每次新技能调用恢复旧 run 前显式提交，不从历史补齐，不改变 run_id、预算、失败或旧角色选择历史。其 op_id 同时作为 invocation_id；成功后 inspect.models 读回本次表。每个命令进程不等于一次技能调用；正常逐例命令继续使用本次表。运行时真实模型支持及派发一致性由代理审查。

`recover` 事件字段为 `invocation_id`：必须引用最近一次完整 invocation；同 recover op_id 重放仍幂等，同一次技能调用可以用新的 recover op_id 再次观察变化，继续引用该 invocation。重验锚点、历史、请求、已发布 receipt、claim 和日志。可核验完整 receipt 的未结算 attempt 按 record 规则结算一次，包括 snapshot 不稳定的 ineligible 路径；该 attempt 出现在 reconciled_attempts，inspect.failures 呈现相同 ineligible 条目。存在可靠归属且仍在运行时输出 blocked/running，不重启；归属已终止而没有可核验完整 receipt 时追加 interrupted 失败并按上文计费。已存在但 hash、binding 或审计链损坏的材料仍拒绝，不能通过 recover 降格为 interrupted。无法判断存活或所有权时输出 blocked/ownership-unknown，保留预约，不猜测 PID、不自动释放预算。recover 重复调用不得重复扣款。后续 diagnose 保留原失败与原因，重新尝试必须使用新 attempt。

prepare 已提交但 claim 尚不存在时，recover 以原子独占创建上文取消 claim；创建成功则延迟 runner 不再能启动，按 interrupted 保守结算预约一次。独占失败表示 runner 或其他恢复者已抢先创建，必须重读并按对应正常/取消 claim 处理，不能先检查不存在再无条件写入。部分写入、损坏或身份不足的 claim 返回 ownership-unknown。

recover 在未决归属情况下退出 0，输出 `{"ok":true,"status":"blocked","reason":"running|ownership-unknown","attempt_ids":["..."]}`；其中 reason 为两个枚举值之一，多个未决 attempt 中有 unknown 时优先 ownership-unknown。无未决归属时输出 `{"ok":true,"status":"active|ready","reconciled_attempts":["..."]}`，status 为恢复后的运行状态；interrupted 已结算但仍需 diagnose 的运行可为 active，prepare 的失败门槛仍独立生效。损坏审计链等拒绝使用通用错误对象和退出 2。

`inspect` 返回 `{"ok":true,"run_id":"...","status":"active|blocked|ready","models":{},"active_by_flow":{},"examples":{},"gates":{},"budget":{"attempts_used":0,"formal_failures_used":0,"seconds_used":0,"seconds_reserved":0},"pending_attempts":[],"failures":[],"last_seq":0}`；集合条目必须公开稳定 ID、当前状态及其证据 attempt ID。`verify` 返回 `{"ok":true,"valid":true,"last_seq":N}` 或通用错误，实际重验所有历史文件摘要和当前被采用的资格，不能只读取自报 status。

pending_attempts 按准备序号排序，条目为 `{"attempt_id":"...","example":"id-or-null","gate":"id-or-null","purpose":"...","state":"prepared|running|ownership-unknown","timeout_seconds":20,"receipt_path":"absolute"}`，example/gate 使用真实字符串或 JSON null。failures 按发生序号排序，条目为 `{"attempt_id":"...","classification":"unclassified|valid-red|implementation|test-defect|environment|business-decision|unknown|interrupted|ineligible","resolved":false,"diagnoses":[{"reason":"...","evidence":["..."],"next_action":"..."}]}`；classification 使用一个枚举值；ineligible 条目另有必填 `reason:"snapshot-changed"`。valid-red 保留为已 resolved 的原始非零轨迹，属于正常开发结果；其他失败原始条目也不得因诊断、改名或恢复删除。集合条目允许后续增加可选审计字段，测试不应假定恰好只有这些键。

## 4. 明确不由工具证明的事项

工具证明真实有界执行的本地记录、文件/日志摘要、事件顺序、依赖无环、版本和预算关系。代理审查证明：需求来源权威、一个切片只有一个新例子、有效 Red 的业务原因、测试完整依赖/覆盖范围、上下文未污染、真实派发模型与表一致、内部重构保持业务语义以及冻结期间的操作纪律。十角色配置核验不能冒充运行时派发或物理访问隔离。所有正式材料必须明确区分这两类证明。

实施可按三批独立验证：① runner + open/probe/Red/Green/existing/close 与摘要；② 无环 gate、资格、clean HEAD 和 finish；③ 中断恢复、重复事件、失败连续性与限额。每批只先实现当前例子的黑盒测试，再实现产品；没有实际运行的平台或场景标为未验证。

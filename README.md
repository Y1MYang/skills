# Y1MYang/skills

个人技能仓库。每个技能是一个文件夹，其中至少包含一个 `SKILL.md`，用于指示编程助手如何执行一类固定的工作。

## 仓库结构

```
.
├── .claude-plugin/
│   └── marketplace.json        # 技能清单：按插件（分类）分组，供安装界面分组勾选
├── skills/
│   └── engineering/
│       ├── implement-spec-v2/  # 每个技能一个文件夹
│       │   └── SKILL.md
│       └── cleanup-spec-v2/
│           └── SKILL.md
├── CONTEXT.md
├── LICENSE
└── README.md
```

规则：

- 技能必须位于 `skills/<分类>/<技能名>/SKILL.md`；`SKILL.md` 若直接放在仓库根目录或 `skills/` 下，会遮蔽更深层的技能。
- 每个技能的 `SKILL.md` 头部必须包含字符串类型的 `name` 与 `description` 字段，否则安装器检测不到。
- 新增技能后，需把技能文件夹追加到 `.claude-plugin/marketplace.json` 中对应插件的 `skills` 列表；新增分类则需新增一个插件条目（`name` 用英文 kebab-case）。

## 安装

使用 npx 安装：

```bash
npx skills add Y1MYang/skills            # 交互式选择并安装
npx skills add Y1MYang/skills --list     # 仅列出可用技能
npx skills update                        # 更新已安装的技能
```

或者使用 Claude Code 插件市场（两种方式二选一，不要同时使用）：

```
/plugin marketplace add Y1MYang/skills
/plugin install engineering@Y1MYang-skills
```

## 当前技能

| 技能 | 说明 |
| --- | --- |
| `implement-spec-v2` | 按 spec 实现：架构先行 + 独立测试神谕，任务图驱动并行子代理，最终产出单个 PR。 |
| `cleanup-spec-v2` | PR 合并后显式调用 `cleanup-spec-v2 <PR 编号>`，确认完整清单后清理本次开发的本地资源、远端分支和记录。需同时安装 `implement-spec-v2`。 |

## 许可

原创内容以 [MIT](./LICENSE) 许可发布。

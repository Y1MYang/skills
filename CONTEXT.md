# CONTEXT

本仓库的维护约定（供协作者与未来的自己参考）：

- 布局仿照技能仓库的通用约定：技能位于 `skills/<分类>/<技能名>/SKILL.md`。
- `.claude-plugin/marketplace.json` 是安装器与插件市场的清单：
  - `name` 为 `<owner>-skills`，与安装命令中的 marketplace 名一致。
  - 每个插件对应 `skills/` 下一个分类目录（`source`），其 `skills` 数组列出该分类下的技能文件夹。
  - 新增技能：建文件夹 + 写 `SKILL.md`（头部必须有 `name`、`description`），再追加到对应插件的 `skills`。
  - 新增分类：在 `skills/` 下建目录，并在 `plugins` 中新增条目（`name` 英文 kebab-case）。
- 改动后用 `npx skills add Y1MYang/skills --list` 验证技能能被检测到。

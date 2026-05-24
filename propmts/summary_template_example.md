# 文献分类总结模板

这个文件控制 AI agent 对文献分类时要遵循的总结逻辑，以及 `literature_summary.md` 的 Markdown 输出格式。

注意：文件名按当前项目约定保留为 `sunmary_templete.md`。你可以修改下面区块里的 prompt 和 Markdown 模板。

<!-- SUMMARY_PROMPT_START -->
请把文献按照研究方向从“大方向 → 小方向”分类。

总结文件的目标：

1. 不是简单按年份排序，而是按研究脉络组织。
2. 分类原则：请按照“从大到小”的层级结构分类：
   - 一级分类：研究大方向，例如材料体系、制备方法、应用场景、机理问题等。
   - 二级分类：具体研究主题，例如薄膜生长、界面反应、氧空位、致密性、离子传输、力学性能等。
   - 三级分类：更具体的研究问题，例如室温沉积、偏压调控、氧压影响、退火效应、晶粒长大、表面粗糙化、气密性评价等。
   分类时要注意：
   1）不要机械按照文献题目分类，而要根据文献真正研究的问题分类。
   2）一篇文献可以同时属于多个类别，但请说明其主要归属和次要关联。
   3）如果某些文献之间研究对象不同，但关注的是同一个科学问题，可以归为同一类。
   4）如果某些文献表面上相似，但核心问题不同，要分开。
   5）如果有些类别文献数量很少，也要单独列出，但要说明“目前文献较少”。
3. 每篇文献必须能通过 Obsidian 链接跳转到 `literature_cards.md` 中对应卡片。
4. 每个分类下的文献用 DataviewJS 表格展示。
<!-- SUMMARY_PROMPT_END -->

<!-- SUMMARY_HEADER_TEMPLATE_START -->
# 文献分类总览

> 生成时间：{{generated_at}}
> 文献数量：{{record_count}}

本文件按“研究大方向 → 小方向”组织文献。每个分类下的表格由 Obsidian DataviewJS 构建，文献标题链接到 `{{cards_file}}` 中对应卡片。
<!-- SUMMARY_HEADER_TEMPLATE_END -->

<!-- DATAVIEW_TABLE_TEMPLATE_START -->
```dataviewjs
const rows = [{{rows}}];
dv.table(
  ["文献", "年份", "作者", "期刊", "DOI"],
  rows.map(row => [dv.parse(row.link), row.year, row.authors, row.journal, row.doi])
);
```
<!-- DATAVIEW_TABLE_TEMPLATE_END -->

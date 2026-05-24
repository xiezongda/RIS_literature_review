# 文献逐篇阅读整理模板

这个文件控制 AI agent 阅读每篇 RIS 文献后的整理要求，以及 `literature_cards.md` 中每篇文献卡片的 Markdown 输出格式。

你可以改下面三个块里的文字和 Markdown 顺序。请尽量保留 `{{...}}` 占位符名称；如果要新增全新字段，需要同步修改下方 CARD_TEMPLETE和AI_USER_PROMPT的json字段

<!-- AI_READING_PROMPT_START -->
(填入希望Ai
<!-- AI_READING_PROMPT_END -->

<!-- CARD_TEMPLATE_START -->
## {{index}}. {{title}}

literature_id:: {{literature_id}}
title:: {{title_inline}}
year:: {{year}}
doi:: {{doi}}
broad_direction:: {{broad_direction}}
medium_direction:: {{medium_direction}}

- 年份：{{year}}
- 作者：{{authors}}
- 期刊：{{journal}}
- DOI：{{doi}}
- 关键词：{{keywords}}
- 摘要概括：{{abstract_summary}}
- 研究对象：{{study_object}}
- 研究方法：{{methods}}
- 核心结果：{{core_result}}
- “常温 FCVA 制备 YSZ 薄膜”可以结合的点：{{fcva_connection}}
- 实验复杂性和可实现性：{{complexity}}
- 可用于论文综述的句子：{{review_sentence}}
<!-- CARD_TEMPLATE_END -->

<!-- AI_USER_PROMPT_START -->
文献序号：{{index}}
标题：{{title}}
作者：{{authors}}
年份：{{year}}
期刊：{{journal}}
DOI：{{doi}}
关键词：{{keywords}}
摘要：{{abstract}}

文献卡片最终会按 review_templete.md 中的 CARD_TEMPLATE 渲染，请生成能填入该模板的内容。

请输出以下字段：
broad_direction：研究大方向，适合综述目录一级分类。
medium_direction：中等方向，适合综述目录二级分类。
small_direction: 小方向，适合目录三级分类
abstract_summary：1 句话概括摘要。
study_object：研究对象。
methods：研究方法。
core_result：核心结果。
fcva_connection：和"常温 FCVA 制备 YSZ 薄膜"可结合的点。
complexity：实验复杂性和可实现性。
review_sentence：可直接放入论文综述的一句话。
<!-- AI_USER_PROMPT_END -->

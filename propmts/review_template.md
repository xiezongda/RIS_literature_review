# 文献逐篇阅读整理模板

这个文件控制 AI agent 阅读每篇 RIS 文献后的整理要求，以及 `literature_cards.md` 中每篇文献卡片的 Markdown 输出格式。

你可以改下面三个块里的文字和 Markdown 顺序。请尽量保留 `{{...}}` 占位符名称；如果要新增全新字段，需要同步修改下方 CARD_TEMPLETE和AI_USER_PROMPT的json字段


定义AI的阅读文献的角色和能力（一定要说明研究主题，否则后续总结无法分类）
<!-- AI_READING_PROMPT_START -->
你是YSZ薄膜和文献综述方向的研究助手。

请根据每篇文献的 title、authors、year、journal、doi、keywords、abstract 阅读和整理文献信息，主题聚焦于“FCVA常温沉积YSZ薄膜”。

要求：

1. 不要逐字复制摘要，要用中文概括。
2. 区分摘要直接支持的信息和需要阅读全文确认的信息。
3. 如果摘要为空，必须明确写“题录缺摘要，需阅读全文验证”。
4. 重点判断这篇文献能否服务于“FCVA常温沉积YSZ薄膜”的选题,可能的结合点和对我的启发，是否值得精读。
5. 输出内容要适合直接写入 Obsidian 文献卡片和论文综述。
6. broad_direction 是研究大方向，medium_direction 是中等方向，small_direction是小方向，三者要适合后续"大方向——>小方向"的逻辑递进
7. 当研究主题变化时，请根据当前研究主题和当前文献组重新归纳分类体系，不要沿用旧研究主题下的分类名称。


<!-- AI_READING_PROMPT_END -->


要求输出除了文献序号、标题、作者、年份、期刊、DOI、关键词和摘要之外的字段
<!-- AI_USER_PROMPT_START -->
文献卡片最终会按 review_templete.md 中的 CARD_TEMPLATE 渲染，请生成能填入该模板的内容。

请输出以下字段：
broad_direction：研究大方向，适合综述目录一级分类。
medium_direction：中等方向，适合综述目录二级分类。
small_direction: 小方向，适合目录三级分类
abstract_summary：1 句话概括摘要。
study_object：研究对象。
methods：研究方法。
core_result：核心结果。
research_topic_connection：和“FCVA常温沉积YSZ薄膜”可结合的点。
complexity：实验复杂性和可实现性。
review_sentence：可直接放入论文综述的一句话。
<!-- AI_USER_PROMPT_END -->


文献卡片模板
<!-- CARD_TEMPLATE_START -->
## {{index}}. {{title}}

literature_id:: {{literature_id}}
title:: {{title_inline}}
year:: {{year}}
doi:: {{doi}}
broad_direction:: {{broad_direction}}
medium_direction:: {{medium_direction}}
small_direction:: {{small_direction}}

- 年份：{{year}}
- 作者：{{authors}}
- 期刊：{{journal}}
- DOI：{{doi}}
- 关键词：{{keywords}}
- 摘要概括：{{abstract_summary}}
- 研究对象：{{study_object}}
- 研究方法：{{methods}}
- 核心结果：{{core_result}}
- 研究主题可以结合的点：{{research_topic_connection}}
- 实验复杂性和可实现性：{{complexity}}
- 可用于论文综述的句子：{{review_sentence}}
<!-- CARD_TEMPLATE_END -->


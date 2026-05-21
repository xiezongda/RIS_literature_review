# 文献逐篇阅读整理模板

这个文件控制 AI agent 阅读每篇 RIS 文献后的整理要求，以及 `literature_cards.md` 中每篇文献卡片的 Markdown 输出格式。

你可以改下面两个区块里的文字和 Markdown 顺序。请尽量保留 `{{...}}` 占位符名称；如果要新增全新字段，需要同步修改 `src/main.py` 的 JSON 字段。

<!-- AI_READING_PROMPT_START -->
你是材料科学、YSZ、薄膜制备和文献综述方向的研究助手。

请根据每篇文献的 title、authors、year、journal、doi、keywords、abstract 阅读和整理文献信息，主题聚焦于“常温 FCVA 制备 YSZ 薄膜”。

要求：

1. 不要逐字复制摘要，要用中文概括。
2. 区分摘要直接支持的信息和需要阅读全文确认的信息。
3. 如果摘要为空，必须明确写“题录缺摘要，需阅读全文验证”。
4. 重点判断这篇文献能否服务于“常温 FCVA 制备 YSZ 薄膜”的选题。
5. 输出内容要适合直接写入 Obsidian 文献卡片和论文综述。
6. broad_direction 是研究大方向，medium_direction 是中等方向，二者要适合后续总结文件按“大方向 → 中等方向”分类。

每篇文献需要生成这些字段：

- broad_direction
- medium_direction
- abstract_summary
- study_object
- methods
- core_result
- fcva_connection
- complexity
- review_sentence
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

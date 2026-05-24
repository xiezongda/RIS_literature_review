# RIS_literature_review

一个用于读取 EndNote、Web of Science、Zotero 等工具导出的 RIS 文献文件，并借助 AI agent 生成文献卡片、分类总结 Markdown 和清洗 Excel 的 Python 项目。

## 功能

- 读取 `data/raw/` 中的 `.ris` 文件。
- 解析 `title`、`authors`、`year`、`journal`、`doi`、`keywords`、`abstract`。
- 兼容 RIS 摘要字段 `AB` 和 `N2`，也兼容 EndNote `%0/%A/%T/%X` 导出格式。
- 优先按 DOI 去重；无 DOI 时按标题近似去重。
- 调用配置的 AI agent 阅读每篇文献，生成结构化整理字段。
- 输出 Excel：`output/excel/literature_records.xlsx`。
- 输出文献卡片：`output/markdown/literature_cards.md`。
- 输出 Obsidian + Dataview 分类总结：`output/markdown/literature_summary.md`。
- 可通过模板文件调整 AI 阅读 prompt、文献卡片格式和总结文件格式。

## 项目结构

```text
.
├── config/
│   ├── deepseek_v4pro.example.json
│   ├── chatgpt.example.json
│   └── claude.example.json
├── data/
│   └── raw/
├── output/
│   ├── cache/
│   ├── excel/
│   └── markdown/
├── propmts/
│   ├── review_templete.md
│   └── sunmary_templete.md
├── src/
│   ├── main.py
│   ├── RIS_analysis.py
│   ├── remove_duplicates.py
│   ├── read_templete.py
│   ├── AI_cache_annotation.py
│   └── output_module.py
├── .env.example
├── requirements.txt
└── README.md
```

## 安装

建议使用 Python 3.10+。如果本机没有现成虚拟环境，请在项目根目录创建一个新的 `.venv`，然后安装 `requirements.txt` 中的依赖。

Windows / PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

macOS / Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

如果习惯使用 Conda，也可以创建独立环境：

```powershell
conda create -n literature_review python=3.11
conda activate literature_review
pip install -r requirements.txt
```

目前 `requirements.txt` 中的 `openpyxl` 和 `requests` 就能支持主程序运行：`openpyxl` 用于生成 Excel，`requests` 用于调用 AI API。

## 配置 AI Agent

默认使用 DeepSeek 配置。复制示例文件后填入自己的 API key：

```powershell
Copy-Item config/deepseek_v4pro.example.json config/deepseek_v4pro.json
```

`config/deepseek_v4pro.example.json` 已启用高思考配置：

```json
{
  "thinking": {
    "type": "enabled"
  },
  "reasoning_effort": "high"
}
```

也可以通过环境变量填写 key：

```powershell
$env:DEEPSEEK_API_KEY="sk-your-deepseek-api-key"
```

### 切换 ChatGPT

```powershell
Copy-Item config/chatgpt.example.json config/chatgpt.json
$env:LITERATURE_AGENT="chatgpt"
python src/main.py
```

也可以用环境变量：

```powershell
$env:OPENAI_API_KEY="sk-your-openai-api-key"
```

### 切换 Claude

```powershell
Copy-Item config/claude.example.json config/claude.json
$env:LITERATURE_AGENT="claude"
python src/main.py
```

也可以用环境变量：

```powershell
$env:ANTHROPIC_API_KEY="sk-ant-your-claude-api-key"
```

## 使用

1. 将 `.ris` 文件放入：

```text
data/raw/
```

2. 运行主程序：

```powershell
python src/main.py
```

3. 查看输出：

```text
output/excel/literature_records.xlsx
output/markdown/literature_cards.md
output/markdown/literature_summary.md
```

如果没有配置 API key，程序仍会运行，并用规则兜底生成基础整理内容；配置 API key 后会调用 AI agent 阅读文献。

## 修改 AI 阅读模板

逐篇文献整理模板：

```text
propmts/review_templete.md
```

分类总结模板：

```text
propmts/sunmary_templete.md
```

`review_templete.md` 里有三个主要区域：

- `AI_READING_PROMPT`：控制 AI 阅读文献时的角色、研究主题和判断重点。
- `AI_USER_PROMPT`：控制 AI 需要输出除了文献序号、标题、作者、年份、期刊、DOI、关键词和摘要这些固定字段之外的其他结构化字段。
- `CARD_TEMPLATE`：控制 `literature_cards.md` 中每篇文献卡片的 Markdown 样式。

如果只想改变 AI 输出字段，请修改 `AI_USER_PROMPT` 中的字段列表，并在 `CARD_TEMPLATE` 中使用同名 `{{field_name}}` 占位符。程序会自动把这些字段同步到 AI 输出要求、Excel 表头和文献卡片渲染中。

修改模板后重新运行即可。若想让已有缓存文献重新调用 AI 阅读：

```powershell
$env:LITERATURE_REFRESH_AI="1"
python src/main.py
```

## 缓存说明

AI 阅读结果会缓存到：

```text
output/cache/literature_ai_annotations.json
```

缓存可以减少重复调用 API。缓存签名包含 `review_templete.md` 的关键内容，修改字段或 prompt 后，新的模板会生成新的缓存记录。

## GitHub 上传注意

默认 `.gitignore` 会忽略：

- 原始 RIS 文件：`data/raw/*.ris`
- 输出结果：`output/`
- API 配置：`config/deepseek_v4pro.json`、`config/chatgpt.json`、`config/claude.json`
- `.env`
- Python 缓存和虚拟环境

上传前建议确认没有 API key、未公开文献数据或临时输出被加入暂存区。

# RIS_literature_review

一个用于读取 EndNote、Web of Science 和 Zotero 导出的 RIS 格式文献组，并借助 DeepSeek V4 Pro / OpenAI-compatible LLM 自动生成文献卡片、分类总结 Markdown 和文献整理 Excel 的 Python 项目。

## 功能

- 读取 `data/raw/` 中的 `.ris` 文件。
- 解析题名、作者、年份、期刊、DOI、关键词、摘要等字段。
- 兼容标准 RIS 格式和 EndNote `%0/%A/%T/%X` 导出格式。
- 按 DOI 去重；没有 DOI 时按标题近似去重。
- 调用配置的 LLM 阅读每篇文献摘要，生成结构化综述字段。
- 输出 Excel：`output/excel/literature_records.xlsx`。
- 输出文献卡片：`output/markdown/literature_cards.md`。
- 输出 Obsidian + Dataview 分类总览：`output/markdown/literature_summary.md`。
- 支持通过模板文件调整文献卡片和总结文件的 prompt/格式。

## 项目结构

```text
.
├── config/
│   └── deepseek_v4pro.example.json
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
│   └── main.py
├── .env.example
├── requirements.txt
└── README.md
```

## 安装

建议使用 Python 3.10+。如果本机还没有虚拟环境，可以在项目根目录创建一个新的 `.venv`。

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

如果你习惯使用 Conda，也可以创建独立环境：

```powershell
conda create -n literature_review python=3.11
conda activate literature_review
pip install -r requirements.txt
```

## 配置 DeepSeek

复制示例配置：

```powershell
Copy-Item config/deepseek_v4pro.example.json config/deepseek_v4pro.json
```

然后编辑 `config/deepseek_v4pro.json`，填写你的 API key：

```json
{
  "api_key": "sk-your-deepseek-api-key"
}
```

也可以不写入配置文件，改用环境变量：

```powershell
$env:DEEPSEEK_API_KEY="sk-your-deepseek-api-key"
```

## 使用

1. 将 EndNote 导出的 `.ris` 文件放入：

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

## 修改 AI 阅读模板

文献逐篇整理模板：

```text
propmts/review_templete.md
```

分类总结模板：

```text
propmts/sunmary_templete.md
```

修改模板后重新运行 `python src/main.py` 即可。如果想让已经缓存的文献重新调用 AI 阅读，设置：

```powershell
$env:LITERATURE_REFRESH_AI="1"
python src/main.py
```

## 缓存说明

AI 阅读结果会缓存到：

```text
output/cache/literature_ai_annotations.json
```

缓存可以减少重复调用 API。该文件默认不会上传 GitHub。

## GitHub 上传注意

默认 `.gitignore` 会忽略：

- 原始 RIS 文件：`data/raw/*.ris`
- 输出结果：`output/`
- API 配置：`config/deepseek_v4pro.json`
- `.env`
- Python 缓存和虚拟环境

上传前建议确认没有 API key、未公开文献数据或临时输出被加入暂存区。

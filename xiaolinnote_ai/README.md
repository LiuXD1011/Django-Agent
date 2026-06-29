# Xiaolinnote AI Interview Archive

本目录由 `scripts/scrape_xiaolinnote_ai.py` 生成，用于本地学习、检索和 LLM/RAG 解析。

## 目录结构

```text
xiaolinnote_ai/
  raw_html/          # 原始 HTML 归档，含首页/专题页/题目页
  markdown/          # 每道题一个 Markdown 文件，按专题分目录
  data/
    questions.jsonl  # 主数据文件，一题一行 JSON
    index.json       # 抓取清单、分类统计、文件路径索引
```

## questions.jsonl 字段

- `id`: 稳定题目 ID，由 URL 路径生成。
- `source_site`: 来源站点域名。
- `category_slug`: 专题 slug，例如 `agent`、`rag`、`tools`、`llm`。
- `category`: 专题中文名。
- `order`: 题目序号。
- `title`: 题目标题。
- `url`: 原始页面 URL。
- `fetched_at`: 抓取/解析时间。
- `raw_html_path`: 对应原始 HTML 文件路径。
- `markdown_path`: 对应 Markdown 文件路径。
- `content_sha256`: Markdown 正文哈希。
- `content_chars`: Markdown 正文字符数。
- `content_markdown`: 清洗后的完整 Markdown 正文。
- `sections`: 按 Markdown 标题切分的章节数组。
- `images`: 正文图片链接数组。

## 重新抓取

```bash
python3 scripts/scrape_xiaolinnote_ai.py --output-dir xiaolinnote_ai --force
```

如果只想用已归档 HTML 重新生成 Markdown/JSONL，可省略 `--force`。

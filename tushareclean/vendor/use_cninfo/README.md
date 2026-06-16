# cninfo-cli

> A 股上市公司公告按需抓取 — 巨潮资讯网(cninfo.com.cn)`hisAnnouncement/query` 接口的 Python CLI 包装,顺便给 Claude Code 提供一个 skill 入口。

[![ci](https://github.com/rollysys/use_cninfo/actions/workflows/ci.yml/badge.svg)](https://github.com/rollysys/use_cninfo/actions/workflows/ci.yml)

cninfo 是中国证监会指定的 A 股法定信息披露平台。本工具直接从 cninfo 拉**任何**已公开公告(年报/季报/中报/三季报/临时公告/减持/重组/股东大会/...),下载 PDF + 用 PyMuPDF 提取全文 Markdown,**纯按需**,命中本地缓存秒级返回。

## 这是啥

- **CLI**: `cninfo` 命令,6 个子命令 — `fetch-report` / `fetch-stock` / `list` / `search` / `cache` / `orgid`
- **Claude Code skill**: `skill/SKILL.md`,让 agent 直接说"拿茅台 2024 年报"就能落盘
- **缓存**: `~/.cache/cninfo/`,PDF + md + metadata 三件套,二次访问秒级
- **可选分类**: 集成 [rollysys/announcement_filter](https://github.com/rollysys/announcement_filter)(11 大类 / 82 子类 ontology),`search` 子命令支持 `--type shareholder --sub-type reduce_plan` 这种**精准类目**过滤

## 安装

```bash
git clone https://github.com/rollysys/use_cninfo.git
cd use_cninfo

# 推荐:uv tool install,装到独立 venv 并暴露全局 `cninfo` 命令
uv tool install -e .

# 或 pip 直装
pip install -e .
```

可选:装 `announcement_filter` 启用标签搜索

```bash
git clone https://github.com/rollysys/announcement_filter.git
cd announcement_filter && pip install -e .
```

不装也能用,只是 `cninfo search --type ...` 会报错并给提示。

## 60 秒上手

```bash
# 1. 拿茅台 2024 年报
cninfo fetch-report 600519 --year 2024 --kind annual

# 输出:
# {
#   "ann_id": "...",
#   "ts_code": "600519.SH",
#   "ann_date": "20240412",
#   "title": "贵州茅台2024年年度报告",
#   "pdf_path": "/Users/x/.cache/cninfo/pdf/600519.SH/20240412__xxx.pdf",
#   "md_path":  "/Users/x/.cache/cninfo/md/600519.SH/20240412__xxx.md",
#   "total_pages": 286,
#   "extracted_pages": 286,
#   "text_chars": 412580,
#   "cache_hit": false
# }

# 2. 看正文(YAML frontmatter + 全文)
less ~/.cache/cninfo/md/600519.SH/*.md

# 3. 二次执行命中缓存(< 1s)
cninfo fetch-report 600519 --year 2024 --kind annual

# 4. 查贵州茅台 2024 4 月所有公告
cninfo fetch-stock 600519 --since 2024-04-01 --until 2024-04-30

# 5. 4/29 当天 sz 板块所有年报
cninfo list --plate sz --category annual --date 2024-04-29 --limit 20

# 6. 标签搜索:茅台 2024 年的减持计划公告(需 announcement_filter)
cninfo search --stock 600519 --since 2024-01-01 --until 2024-12-31 \
              --type shareholder --sub-type reduce_plan
```

## 6 个子命令一览

| 子命令 | 用途 |
|---|---|
| `fetch-report <code> --year Y --kind annual\|q1\|h1\|q3` | 单股指定定期报告本体(自动跳过摘要/审计/内控) |
| `fetch-stock <code> --since D --until D [--download]` | 单股时间窗全公告(默认列表,加 --download 才落盘) |
| `list --plate sz\|sh\|bj [--category ... --date ... --keyword ... --download --limit N]` | 全市场切片 |
| `search [--stock ... \| --plate ... + --date/--since/--until] [--type T --sub-type ST] [--keyword K] [--download]` | 标签 / 关键词搜索 |
| `cache stats\|verify\|prune --older-than 365d` | 缓存管理 |
| `orgid <code> [--refresh\|--cache-only]` | 查/反查 secCode→orgId 映射 |

`cninfo <cmd> --help` 看全部参数。

## 缓存布局

```
~/.cache/cninfo/                            # $CNINFO_CACHE_DIR 可覆盖
├── orgid_map.json                          # secCode → orgId 映射
├── pdf/<ts_code>/<ann_date>__<ann_id>.pdf
├── md/<ts_code>/<ann_date>__<ann_id>.md    # 含 YAML frontmatter + PyMuPDF 全文
└── meta/<ann_id>.json                      # cninfo 原始返回 + 派生字段
```

YAML frontmatter 字段:`ann_id / ts_code / sec_code / sec_name / ann_date / title / category / source / total_pages / extracted_pages / text_chars`。

## Claude Code skill 集成

```bash
# 把 skill 链到 ~/.claude/skills/
mkdir -p ~/.claude/skills
ln -s "$(pwd)/skill" ~/.claude/skills/cninfo
```

之后在 Claude Code 里说"拿茅台 2024 年报"或"4/29 全市场所有年报",agent 会自动调 `cninfo` CLI。详见 [`skill/SKILL.md`](skill/SKILL.md)。

## 已知限制

继承自 cninfo 接口本身(详见 [`docs/gotchas.md`](docs/gotchas.md)):

- **pageSize 服务端硬限 30**,翻页是必须的
- **stock 参数必须 `<6位>,<orgId>`**,本工具自动通过 `topSearch` 拉 orgId 并缓存
- **同一公告可能有 2 条记录**(announcementId 不同 PDF 内容相同),按 `(secCode, ann_date, title)` 去重
- **部分老 PDF URL 可能 404**(2024-06 前迁移过)
- **部分 PDF 是扫描件**(主要是律所/会计师审计意见),`extracted_pages=0`,本工具不内置 OCR

## 项目结构

```
src/cninfo/         # Python 包
  api.py            # cninfo `hisAnnouncement/query` 接口客户端
  parser.py         # PyMuPDF 解析
  cache.py          # 本地缓存层
  orgid.py          # secCode→orgId(走 cninfo topSearch)
  fetcher.py        # api+parser+cache 协调
  classify.py       # announcement_filter 薄包装
  cli.py            # argparse CLI
docs/               # 接口知识沉淀(实测笔记,新项目起点)
  api_reference.md  capabilities.md  gotchas.md  cookbook.py
skill/SKILL.md      # Claude Code skill 入口
tests/              # pytest + 离线 fixture
```

## 开发

```bash
uv venv --python 3.10
uv pip install -e ".[dev]"
uv run pytest                  # 32 个离线测试
uv run ruff check src tests
```

## License

MIT — see [LICENSE](LICENSE).

致谢:接口知识沉淀基于 2026-05-04 实测会话。分类 ontology 由 [rollysys/announcement_filter](https://github.com/rollysys/announcement_filter) 提供。

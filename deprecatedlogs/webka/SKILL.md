---
name: webka
description: 旧版 /ka 网页端打包兼容入口：把生成核心假设.md 所需源文件（含核心假设生成修改器 skill）打包到 WEBCLAUDE/核心假设部分/。当前推荐的网页端重活入口是 /webload；只有明确要把普通 /ka 放到网页端跑时才使用 /webka。
argument-hint: [公司名或代码，如 新乳业 / 002946]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /webka — 旧版网页端核心假设打包器

`/webka` 只保留为普通 `/ka` 网页端打包的兼容入口。当前真正推荐放到网页端跑的是 `/webload`，因为 `/load` 要保存旧模型 vintage、解释模型时间轴、先讲 overview 再分段确认。

把生成本公司 `核心假设.md` 所需的源文件，以及网页端执行所需的**核心假设生成修改器 skill**，一键汇总到 `companies\{公司名}_{代码}\WEBCLAUDE\核心假设部分\`，供 Claude.ai 网页端拖拽上传使用。

若你的目标是“按旧 Excel 模型自身时间轴保存模型，不让 2025A 等后验事实污染 2025E”，不要用 `/webka`，改用：

```bash
py -m src.webload 公司 --overwrite
```

**重要纪律：本 skill 及所有关联 skill 均不读取 PDF。** 年报只打包已生成的 Markdown（`.md`）。若本地仅有 PDF，请先使用 `python -m src.report_downloader --ticker {ticker} --force-markdown` 生成年报 Markdown。

## 执行动作

1. **解析公司目录**：接受完整 ticker / 裸代码 / 中文公司名。
2. **清空 `WEBCLAUDE/核心假设部分/` 文件夹**：防止过时文件污染。
3. **复制源文件与执行 skill**（加序号前缀，便于网页端按顺序查看）：
   - `00_公司判断和最新观点.md`（**必须存在**，否则报错停止）
   - `01_核心假设_现有底稿.md`（`companies/{公司}/*核心假设*.md` 最新一份；init 模式无则跳过）
   - `02_活跃素材_xxx`（`active_vore/` 中时间最新文件）
   - `03_最新年报_202X_年度报告.md`（只打包 `.md`，**不读/不打包 PDF**）
   - `04_核心假设生成修改器_skill_vN.md`（`D:\MKA\skills\` 中最新版核心假设生成修改器 skill，网页端执行时需要）
4. **打印打包报告**，列清放了哪些文件。输出目录：`companies\{公司}\WEBCLAUDE\核心假设部分\`。

## CLI

```bash
python -m src.webka 新乳业
python -m src.webka 002946
python -m src.webka 002946.SZ
```

## 退出码

- `0`：成功
- `2`：输入无法解析为唯一公司目录
- `3`：缺少 `公司判断和最新观点.md`
- `1`：其他 IO 异常

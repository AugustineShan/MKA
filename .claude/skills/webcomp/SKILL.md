---
name: webcomp
description: "[DEPRECATED 已废弃] 旧版网页端 yaml1 compiler 打包器，不再使用。改用 /comp 本地编译。请勿调用。"
argument-hint: [公司名或代码，如 新乳业 / 002946]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /webcomp — ⚠️ 已废弃（DEPRECATED）

> **此技能已废弃，不再维护，请勿调用。**
>
> 网页端打包流程已下线。yaml1 编译统一走本地 `/comp`（`py -m src.forecast --ticker ...`）。
> 保留本文件仅为历史参考，后续可能删除。

## 历史用途（仅供参考）

把 `/comp` 编译 yaml1 所需的四份输入材料，以及网页端执行所需的 **yaml1compiler skill**，一键汇总到 `companies\{公司名}_{代码}\WEBCLAUDE\yaml1编译部分\`，供 Claude.ai 网页端上传后执行 compiler。

把 `/comp` 编译 yaml1 所需的四份输入材料，以及网页端执行所需的 **yaml1compiler skill**，一键汇总到 `companies\{公司名}_{代码}\WEBCLAUDE\yaml1编译部分\`，供 Claude.ai 网页端上传后执行 compiler。

## 执行动作

1. **解析公司目录**：接受完整 ticker / 裸代码 / 中文公司名。
2. **清空 `WEBCLAUDE/yaml1编译部分/` 文件夹**：防止过时文件污染。
3. **复制四份输入材料与执行 skill**（加序号前缀，便于网页端按顺序查看）：
   - `00_核心假设.md`（`companies/{公司}/*核心假设*.md` 最新一份，**必须存在**）
   - `01_defaults.yaml`（`companies/{公司}/Agent/defaults.yaml`，**必须存在**）
   - `02_数据格式参考.md`（`D:\MKA\docs\数据格式参考.md`）
   - `03_yaml1算法模板契约.md`（`D:\MKA\docs\yaml1算法模板契约.md`）
   - `04_yaml1compiler_skill_vN.md`（`D:\MKA\skills\` 中最新版 yaml1compiler skill，网页端执行时需要）
4. **打印打包报告**，列清放了哪些文件。

## 重要纪律

- 所有 skill（包括 `/comp`、`/webcomp` 及 yaml1compiler）**均不读取 PDF**。
- `defaults.yaml` 是目标命名空间，compiler 只把 `核心假设.md` 的覆盖项落到 `defaults.yaml` 已有的真实路径上。
- `docs/数据格式参考.md` 和 `docs/yaml1算法模板契约.md` 是只读契约，compiler 不能改写。

## CLI

```bash
python -m src.webcomp 新乳业
python -m src.webcomp 002946
python -m src.webcomp 002946.SZ
```

## 退出码

- `0`：成功
- `2`：输入无法解析为唯一公司目录
- `3`：缺少 `核心假设*.md` 或 `defaults.yaml`
- `1`：其他 IO 异常

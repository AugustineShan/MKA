---
name: brkd
description: 启动业务预理解器。读 active_vore/业务理解器（研报和纪要放在这里）/ 下的大量研报/纪要，消化成 Agent业务讨论.md，作为 /ka 的业务预理解参考。当用户说 "brkd 新乳业"、"业务预理解 某公司"、"拆一下某公司业务" 时使用。
argument-hint: [公司名或代码，如 新乳业 / 002946]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /brkd — 业务预理解启动器

把 `active_vore/业务理解器（研报和纪要放在这里）/` 下的一大堆研报/纪要消化成一份 `Agent业务讨论.md`，作为 `/ka` 开会时的"业务预理解"参考。

## 管线位置（三站三种认知模式）

```
研报/纪要 → /brkd → Agent业务讨论.md → /ka → 核心假设.md → /comp → yaml1
            读懂        记全              译准
         discernment   fidelity         翻译
```

本 skill 是最前站，美德 = **discernment（鉴别）**，不是完备。怕的是被海量、有立场、互相抄的研报带偏。

## 执行顺序

1. **解析公司目录**：接受完整 ticker / 裸代码 / 中文公司名（同 /ka 第一动作：精确匹配 `companies\{参数}` → 代码 `companies\*_{参数}` → 公司名 `companies\{参数}_*` → 多候选问用户 → 未命中问用户）。
2. **读定调**：`companies\{公司}\公司判断和最新观点.md`——**只当背景锚点读，不挂框架、不覆写**。若不存在 → 报错停止（缺定调材料，和 /ka 同要求）。
3. **PDF→MD 前置转换**：研报几乎都是 PDF，本 skill 不读 PDF。先跑 `py -m src.research_pdf2md --ticker {ticker}`（或 `--folder <业务理解器子文件夹路径>`），把 `active_vore\业务理解器（研报和纪要放在这里）\` 下所有 `.pdf` 抽成同名 `.md`（PyMuPDF，幂等跳过已转的；`--force` 重抽）。转换后再读 `.md`。`.doc/.docx` 纪要暂不支持自动转换，需手动转成 `.md` 放入。
4. **读材料**：扫描 `companies\{公司}\active_vore\业务理解器（研报和纪要放在这里）\`，**全读不交互选**（读 `.md`，不读 `.pdf`）。若该文件夹不存在或为空（无 `.md` 也无 `.pdf`）→ 报错停止："业务理解器子文件夹为空，请把研报/纪要放进 `active_vore\业务理解器（研报和纪要放在这里）\` 再跑 /brkd"。
5. **动态加载最新版业务预理解器 skill**：扫描 `D:\MKA\skills\`，匹配 `业务预理解器_skill_v*.md`，取版本号最大的那份。**必须先加载 skill，再开始讨论**（防注意力涣散）。
6. **按加载到的 skill 执行分段讨论**：先押再问、拍板才落盘（ka 式）。
7. **收口**：出 `companies\{公司}\Agent业务讨论.md`（公司根目录，与 `公司判断和最新观点.md` 并列）。

## 重要纪律

- **不读 PDF**。第 3 步自动把 PDF 转成 .md（`src.research_pdf2md`，复用年报同款 PyMuPDF）；本 skill 只读已转成文本的（.md/.txt/.doc/.docx/.xls/.xlsx/.xlsm），不直接读 .pdf。
- **碰旋钮给建议值，但不拍板**：建议值进 Agent业务讨论.md，ka 会议老板拍板。brief 分析师，不 replace 分析师观点。
- **范围只收入分线**：费用/below-OP/税/中期/BS 由 ka 处理，本 skill 不碰。
- **研报是线索不是权威**：每条数据/判断带四级可信度标注，ka 搬时用年报/clean_annual 校验。
- 产物按 ka 消费方式组织（按业务线排），不写成文献综述。

## CLI

```
/brkd 新乳业
/brkd 002946
/brkd 002946.SZ
```

## 退出码

- `0`：Agent业务讨论.md 生成成功（公司根目录）
- `2`：输入无法解析为唯一公司目录
- `3`：缺 `公司判断和最新观点.md`，或 `业务理解器（研报和纪要放在这里）\` 子文件夹不存在/为空
- `1`：其他 IO 异常
```

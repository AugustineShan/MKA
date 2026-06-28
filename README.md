# MKA · A股财务数据取数与建模工作台

> TuShare 三表取数 → 严格配平校验 → 业务拆分 → DCF 建模，一套本地跑通的投资研究流水线。

MKA 把"A 股财务数据从原始 API 到可用的 DCF 模型"之间的脏活全包了：拉取三表、标准化入库、严格会计配平校验、年报智能核对补缺、业务拆分、核心假设编译、DCF 预测。配上本地 Web 工作台，一家公司一页，可视化查看与一键重算。

---

## ✨ 核心能力

- **两阶段数据流水线**：TuShare Pro 拉三表 → 标准化入库 SQLite → EAV 转宽表 + 严格配平校验 → 写 clean 表
- **年报智能核对（reconciler）**：年度硬校验失败时自动去年报 Markdown 找证据、LLM 高置信确认后生成 approved override 补缺，raw 永不被改
- **建模三站管线**：`/brkd`（读懂研报纪要）→ `/ka`（裁决核心假设）→ `/comp`（编译为 yaml1）→ DCF
- **本地 Web 工作台**：FastAPI + React，一家公司一页，展示三表/核心指标/预测，一键重算
- **通用性优先**：不把任何一家的形状焊进代码，行名/业务线/公式族/科目全由声明驱动

## 🏗️ 架构一瞥

```
TuShare API
  │  data_fetcher.py（拉取 + 标准化 + 入库）
  ▼
data.db: raw_tushare / meta
  │  clean.py（EAV→宽表 + 严格配平校验 + 年报核对补缺）
  ▼
data.db: clean_annual / clean_quarterly
  │  defaults_gen.py（机器平推底座）
  ▼
Agent/defaults.yaml  ── + yaml1*.yaml（人的判断覆盖层）
  │  forecast.py
  ▼
Agent/forecast/（唯一正式 DCF 输出）
```

建模三站：

```
研报/纪要 → /brkd → Agent业务讨论.md → /ka → 核心假设.md → /comp → yaml1 → DCF
            读懂(discernment)   记全(fidelity)      译准(翻译)
```

## 🚀 快速开始

### 前置准备（每台电脑一次）
- **Python 3.11+**（安装时勾选 `Add python.exe to PATH` 和 `py launcher`）
- **Node.js LTS**
- **TuShare token**（[注册](https://tushare.pro/register)后获取）+ **智谱 GLM API Key**（[注册](https://open.bigmodel.cn/)后获取，用于年报核对 LLM 补全）

### Windows 用户（推荐）
1. `git clone` 本仓库
2. 双击 `入口.cmd`——首次自动装依赖、创建 `.env` 并用记事本打开让你填 token
3. 填好 token 保存关闭记事本，再双击一次即启动工作台：http://127.0.0.1:8765

> 详细图文说明见 [`分发说明.md`](分发说明.md)。

### 手动启动
```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
npm install && npm run build
# 配置 .env（从 .env.example 复制并填 token）
python -m src.data_fetcher --ticker 002946.SZ --force   # 拉取
python -m src.clean --ticker 002946.SZ                   # 清洗+校验
python -m src.forecast --ticker 002946.SZ                # DCF
python -m src.workbench                                   # 启动工作台
```

## 🛠️ 技术栈

| 层 | 技术 |
|----|------|
| 取数/校验/建模 | Python 3.11+，TuShare Pro，pandas，PyMuPDF |
| 年报核对 LLM | 智谱 GLM-5.2（可选，不填走 rule-based） |
| 后端 | FastAPI + uvicorn |
| 前端 | React 19 + Vite + TypeScript |
| 存储 | SQLite（每公司一个 `data.db`） |

## 📁 项目结构

```
MKA/
├── src/                    # 数据流水线 + 建模 + workbench 后端
│   ├── data_fetcher.py     #   ① TuShare 拉取+标准化+入库
│   ├── clean.py            #   ② 宽表+配平校验+写 clean 表
│   ├── annual_report_reconciler.py  # 年度硬校验失败→年报核对补缺
│   ├── defaults_gen.py     #   生成 defaults.yaml（机器平推底座）
│   ├── forecast.py         #   正式 DCF 入口
│   └── workbench.py        #   FastAPI 本地工作台
├── app/                    # React 前端
├── skills/                 # /brkd /ka /comp /load 等 skill 定义
├── docs/                   # ARCHITECTURE / 数据流水线 / 前端设计规范 …
├── companies/{公司}_{代码}/ # 运行时输出（不入库，本地生成）
└── 入口.cmd                # Windows 一键启动
```

## 📚 文档

- [**CLAUDE.md**](CLAUDE.md) — 项目总览、三条铁律、数据流水线、校验层级（开发者必读）
- [**docs/ARCHITECTURE.md**](docs/ARCHITECTURE.md) — 当前架构状态
- [**docs/数据流水线.md**](docs/数据流水线.md) — 端到端数据流
- [**docs/技能简要分类.md**](docs/技能简要分类.md) — skill 路由分流
- [**分发说明.md**](分发说明.md) — 首次使用图文说明

## ⚠️ 项目边界

- 只做 A 股（沪深）工商业企业，不拉港股/美股/金融企业
- 取数侧不做预测数据、不做行情 K 线
- `companies/` 为运行时生成，不入库；部署时凭 `.env` 重新生成

## 📄 License

本项目当前未声明开源协议。如需使用、复制或二次开发，请先联系作者。

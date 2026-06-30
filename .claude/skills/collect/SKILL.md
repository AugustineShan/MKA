---
name: collect
description: Alphapai 下载物一键幂等收集。把 C:\Users\Sheld\Downloads 里从 Alphapai 下载的 markdown 按文件名关键字送到对应公司的 Skills素材包 子目录（核心假设参考→KA；外部信息预收集/一页纸→KA+PJBG，二者同类等价、互删旧稿），幂等、保留最新删除之前同类旧文件、move 语义清空源。当用户说 "/collect"、"收集 Alphapai 下载"、"把下载的 Alphapai 文件归位" 时使用。
---

# /collect - Alphapai 下载物一键幂等收集

`/collect` 只做一件事：扫描 `C:\Users\Sheld\Downloads`，把从 Alphapai 下载的 markdown 按文件名关键字送到对应公司的 `Skills素材包` 子目录。不改判断、不读内容、不进建模管线，纯文件归位。

## 入口命令

```bash
py -m scripts.alphapai_collect                 # 全量收集（move 语义）
py -m scripts.alphapai_collect --dry-run       # 只打印将做什么，不落盘
py -m scripts.alphapai_collect -v              # 详细日志
py -m scripts.alphapai_collect --downloads <path> --companies <path>   # 自定义路径
```

> Windows 路径注意：bash 里若 `py`/`python` 指向 WindowsApps 占位，用完整路径
> `/c/Users/Sheld/AppData/Local/Programs/Python/Python311/python.exe -m scripts.alphapai_collect`。

## 路由规则（文件名关键字驱动，不由公司形状驱动）

| 文件名含 | 目标（Skills素材包/） | 例 |
|---|---|---|
| `核心假设参考` | `KA（ALPHAPAI拆出来的东西放在这里）` | `燕京啤酒-核心假设参考.md` |
| `外部信息预收集` **或** `一页纸` | `KA…` + `PJBG评级报告素材区`（双投递） | `燕京啤酒_外部信息预收集_Alphapai参考.md`、`妙可蓝多_一页纸.md` |

> `一页纸` 是 Alphapai 新版格式，与 `外部信息预收集` **同类等价**：都双投递到 KA+PJBG；同公司下两种格式的旧稿互删，只留最新一份（不并存）。

- **公司解析**：从文件名前缀匹配 `companies/{公司名}_{代码}` 目录的公司名段（如 `燕京啤酒` → `燕京啤酒_000729`）。
- **幂等**：再跑一次若无新下载则什么都不做。
- **保留最新删除之前**：每个目标目录里，"公司名前缀 + 同类关键字"的旧 markdown 先删后放，只留本次新投递。范围限定到公司前缀，**不动** `核心假设参考brkd_*`/`核心假设参考load_*`/`核心假设参考alphapai_*` 等无公司前缀的参考稿。
- **move 语义**：所有目标投递成功并大小校验通过后，才删 Downloads 源文件；无公司/无类别匹配的文件原样留在 Downloads；任一目标投递失败则不删旧、不删源，整体回退。

## 边界

- 只处理 `.md`；只认上面两类关键字；找不到公司目录或缺目标子目录的文件跳过并告警，不静默丢弃。
- 不读文件内容、不改 `核心假设.md`/yaml1/forecast；纯归位到 `Skills素材包` 输入区，供 `/ka`、`/pjbg` 后续读取。
- 不向下覆盖：投递前不删目标目录里非同公司前缀的任何文件。

## 验收

```bash
py -m py_compile scripts/alphapai_collect.py
py -m scripts.alphapai_collect --dry-run -v
```

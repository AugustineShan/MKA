#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Alphapai 下载物一键幂等收集器。

把 C:\\Users\\Sheld\\Downloads 里从 Alphapai 下载的 markdown 按文件名关键字送到
对应公司的 Skills素材包 子目录，幂等 + 保留最新删除之前同类旧文件。

路由规则（按文件名关键字判定，不由样本公司形状驱动）：
  - 含 "核心假设参考"          -> KA 目录
  - 含 "外部信息预收集" 或 "一页纸"  -> KA 目录 + PJBG 目录  （双投递）
    （"一页纸" 是 Alphapai 新版格式，与 "外部信息预收集" 同类等价：
     同公司下新旧两种格式互删旧稿，只留最新一份。）
  其余文件一律不动，留在 Downloads。

公司解析：从文件名前缀匹配 companies/{公司名}_{代码} 目录的"公司名"段。
替换范围：每个目标目录里，"公司名前缀 + 同类关键字"的旧文件（不含本次新投递的）
         先删后放，保护 brkd/load/alphapai 等无公司前缀的参考稿不被误删。

源文件处理：move 语义——所有目标投递成功并校验后，才删 Downloads 原文件。
         无公司/无类别匹配的文件原样留在 Downloads。
         任何目标投递失败则不删旧、不删源，整体回退到该文件未处理状态。

用法：
  py -m scripts.alphapai_collect                 # 默认全量
  py -m scripts.alphapai_collect --dry-run       # 只打印不落盘
  py -m scripts.alphapai_collect --verbose       # 详细日志
  py -m scripts.alphapai_collect --downloads <path> --companies <path>
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from dataclasses import dataclass, field

# 中文 stdout 兜底（旧会话未继承 PYTHONUTF8 时）
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

DEFAULT_DOWNLOADS = r"C:\Users\Sheld\Downloads"
DEFAULT_COMPANIES = r"D:\MKA\companies"

# 类别 -> 关键字 + 目标子目录前缀（素材包内目录名按前缀匹配，兼容中文括号后缀）
@dataclass(frozen=True)
class Category:
    key: str          # 类别标识
    keywords: tuple   # 文件名含其中任一关键字即归此类（OR 语义；同类的旧文件互删）
    dest_prefixes: tuple  # 目标子目录名前缀（在 Skills素材包/ 下按 startswith 匹配）

CATEGORIES = (
    Category("核心假设参考", ("核心假设参考",), ("KA",)),
    # "一页纸" 是 Alphapai 新版格式，与 "外部信息预收集" 同类等价、双投递 KA+PJBG。
    Category("外部信息预收集", ("外部信息预收集", "一页纸"), ("KA", "PJBG")),
)


@dataclass
class Match:
    source: str            # Downloads 源文件全路径
    filename: str          # 源文件名
    company_dir: str       # companies/{公司}_{代码} 全路径
    company_name: str      # 公司名段
    category: Category
    dest_dirs: list = field(default_factory=list)  # 解析到的目标目录全路径


def log(msg: str, verbose: bool = False):
    if verbose:
        print(msg, flush=True)


_BROWSER_DUP_RE = re.compile(r" \(\d+\)(?=\.md$)")


def canonical_name(filename: str) -> str:
    """去掉浏览器重复下载后缀 ` (N)`（如 `x (1).md` -> `x.md`），保留其余。"""
    return _BROWSER_DUP_RE.sub("", filename)


def find_company(filename: str, companies_root: str) -> tuple[str, str] | None:
    """文件名前缀匹配公司目录。返回 (company_dir, company_name) 或 None。"""
    if not os.path.isdir(companies_root):
        return None
    candidates = []
    for entry in os.listdir(companies_root):
        full = os.path.join(companies_root, entry)
        if not os.path.isdir(full):
            continue
        # 目录形如 {公司名}_{代码}，按最后一个 _ 拆出公司名
        if "_" not in entry:
            continue
        name, _, code = entry.rpartition("_")
        if not name or not code:
            continue
        if filename.startswith(name):
            candidates.append((name, full))
    if not candidates:
        return None
    # 取最长公司名，避免前缀歧义（如"伊利" vs"伊利股份"）
    name, full = max(candidates, key=lambda c: len(c[0]))
    return (full, name)


def match_category(filename: str) -> Category | None:
    for cat in CATEGORIES:
        if any(kw in filename for kw in cat.keywords):
            return cat
    return None


def resolve_dest_dir(company_dir: str, prefix: str) -> str | None:
    """在 Skills素材包/ 下找以 prefix 开头的子目录。"""
    pack = os.path.join(company_dir, "Skills素材包")
    if not os.path.isdir(pack):
        return None
    for entry in os.listdir(pack):
        if entry.startswith(prefix):
            return os.path.join(pack, entry)
    return None


def scan(downloads: str, companies: str, verbose: bool = False) -> list[Match]:
    matches: list[Match] = []
    if not os.path.isdir(downloads):
        print(f"[ERR] Downloads 目录不存在: {downloads}", flush=True)
        return matches
    for filename in sorted(os.listdir(downloads)):
        if not filename.lower().endswith(".md"):
            continue
        cat = match_category(filename)
        if cat is None:
            log(f"[SKIP] 无类别匹配，留在 Downloads: {filename}", verbose)
            continue
        found = find_company(filename, companies)
        if found is None:
            log(f"[WARN] 找不到对应公司目录，留在 Downloads: {filename}", verbose)
            continue
        company_dir, company_name = found
        dest_dirs = []
        for prefix in cat.dest_prefixes:
            d = resolve_dest_dir(company_dir, prefix)
            if d is None:
                print(f"[ERR] 缺目标目录 {prefix}* in {company_dir}\\Skills素材包，跳过: {filename}", flush=True)
                dest_dirs = []
                break
            dest_dirs.append(d)
        if not dest_dirs:
            continue
        m = Match(
            source=os.path.join(downloads, filename),
            filename=filename,
            company_dir=company_dir,
            company_name=company_name,
            category=cat,
            dest_dirs=dest_dirs,
        )
        matches.append(m)
        log(f"[MATCH] {filename} -> {company_name} | {cat.key} -> {[os.path.basename(d) for d in dest_dirs]}", verbose)
    return matches


def same_scope_files(dest_dir: str, company_name: str, category: Category, exclude_name: str) -> list[str]:
    """列出目标目录里同公司前缀+同类关键字的旧文件（排除本次新文件名）。"""
    out = []
    if not os.path.isdir(dest_dir):
        return out
    for entry in os.listdir(dest_dir):
        if not entry.lower().endswith(".md"):
            continue
        if entry == exclude_name:
            continue
        if not entry.startswith(company_name):
            continue
        if any(kw in entry for kw in category.keywords):
            out.append(os.path.join(dest_dir, entry))
    return out


def deliver(winner: Match, losers: list[Match], dry_run: bool, verbose: bool) -> bool:
    """投递一个 (公司,类别) 分组的胜者：先复制胜者到全部目标，再删目标同类旧文件，
    最后删源（含胜者源 + 落败重复下载源）。任一目标失败则回退（不删旧/不删源）。
    落败者 = 同组里较旧的重复下载，直接从 Downloads 丢弃。"""
    # 0. 胜者落地名（去掉浏览器 (N) 重复后缀，保持目标目录整洁）
    dest_filename = canonical_name(winner.filename)
    if dest_filename != winner.filename:
        log(f"[RENAME] {winner.filename} -> {dest_filename}", verbose)

    # 1. 复制胜者到全部目标并校验
    copied: list[str] = []
    for dest_dir in winner.dest_dirs:
        target = os.path.join(dest_dir, dest_filename)
        if dry_run:
            print(f"[DRY] COPY {winner.filename} -> {target}", flush=True)
            copied.append(target)
            continue
        try:
            shutil.copy2(winner.source, target)
        except Exception as e:
            print(f"[ERR] 复制失败 {winner.source} -> {target}: {e}", flush=True)
            for t in copied:
                try:
                    os.remove(t)
                except Exception:
                    pass
            return False
        if os.path.getsize(target) != os.path.getsize(winner.source):
            print(f"[ERR] 大小校验失败，目标可能损坏: {target}", flush=True)
            try:
                os.remove(target)
            except Exception:
                pass
            return False
        copied.append(target)
        log(f"[COPY] {dest_filename} -> {os.path.basename(dest_dir)}", verbose)

    # 2. 删除目标目录里同类旧文件（保留本次胜者新投递）
    for dest_dir in winner.dest_dirs:
        for old in same_scope_files(dest_dir, winner.company_name, winner.category, dest_filename):
            if dry_run:
                print(f"[DRY] DEL 旧文件 {old}", flush=True)
                continue
            try:
                os.remove(old)
                log(f"[DEL] 旧文件 {os.path.basename(old)} @ {os.path.basename(dest_dir)}", verbose)
            except Exception as e:
                print(f"[WARN] 删旧失败（不影响新文件）{old}: {e}", flush=True)

    # 3. 删除 Downloads 源文件（move 语义）：胜者 + 落败重复下载
    for m in [winner, *losers]:
        if dry_run:
            tag = "源(胜者)" if m is winner else "源(落败重复)"
            print(f"[DRY] DEL  {tag} {m.source}", flush=True)
            continue
        try:
            os.remove(m.source)
            log(f"[MOVE] 删除源 {m.filename} @ Downloads", verbose)
        except Exception as e:
            print(f"[WARN] 删源失败（目标已投递成功，源残留）{m.source}: {e}", flush=True)
    return True


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Alphapai 下载物一键幂等收集")
    p.add_argument("--downloads", default=DEFAULT_DOWNLOADS, help=f"下载目录 (默认 {DEFAULT_DOWNLOADS})")
    p.add_argument("--companies", default=DEFAULT_COMPANIES, help=f"公司根目录 (默认 {DEFAULT_COMPANIES})")
    p.add_argument("--dry-run", action="store_true", help="只打印不落盘")
    p.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    args = p.parse_args(argv)

    matches = scan(args.downloads, args.companies, args.verbose)
    if not matches:
        print("无 Alphapai 下载物待收集（Downloads 内无可识别的 .md）。", flush=True)
        return 0

    # 按 (公司目录, 类别) 分组；组内按源文件 mtime 降序，最新者为胜者，余为落败重复下载。
    groups: dict[tuple[str, str], list[Match]] = {}
    for m in matches:
        groups.setdefault((m.company_dir, m.category.key), []).append(m)

    winners: list[tuple[Match, list[Match]]] = []
    for key in sorted(groups.keys()):
        members = sorted(groups[key], key=lambda x: os.path.getmtime(x.source), reverse=True)
        winners.append((members[0], members[1:]))

    print(f"待投递 {len(winners)} 组（{len(matches)} 个源文件）：", flush=True)
    for winner, losers in winners:
        dests = " + ".join(os.path.basename(d) for d in winner.dest_dirs)
        extra = f"  (丢弃 {len(losers)} 个较旧重复下载)" if losers else ""
        print(f"  - {winner.filename}  ->  {winner.company_name} | {winner.category.key} -> {dests}{extra}", flush=True)
    print("", flush=True)

    ok = 0
    for winner, losers in winners:
        if deliver(winner, losers, args.dry_run, args.verbose):
            ok += 1

    print(f"\n完成：{ok}/{len(winners)} 组成功投递{'（dry-run，未实际落盘）' if args.dry_run else ''}。", flush=True)
    return 0 if ok == len(winners) else 1


if __name__ == "__main__":
    sys.exit(main())

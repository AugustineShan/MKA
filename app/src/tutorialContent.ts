// 静态教程内容：skills 数据 + 管线 + 新手路线。
// 文案与各 SKILL.md / CLAUDE.md 对齐；skill 增删只改本文件。

export type SkillCard = {
  key: string;
  name: string;
  tag: "主线" | "支线";
  when: string;
  command: string;
  input: string;
  output: string;
  next: string;
  discipline: string[];
};

export const pipelineMain: string[] = [
  "研报/纪要",
  "/brkd",
  "Agent业务讨论.md",
  "/ka",
  "核心假设.md",
  "/comp",
  "yaml1",
  "DCF",
];

export const pipelineSide: { label: string; desc: string }[] = [
  { label: "/init", desc: "刷数据到 clean_annual（全链路前置）" },
  { label: "/annual-update", desc: "出年报后把旧核心假设滚到最新" },
  { label: "/webka · /webcomp", desc: "打包素材到 Claude.ai 网页端跑" },
];

export const quickstart: { step: number; cmd: string; desc: string }[] = [
  { step: 1, cmd: "/init 公司", desc: "刷数据：TuShare 取数 → clean 配平 → 年报补全" },
  { step: 2, cmd: "/brkd 公司", desc: "业务预理解：读研报 → Agent业务讨论.md" },
  { step: 3, cmd: "/ka 公司", desc: "核心假设生成：和老板分段议假设 → 核心假设.md" },
  { step: 4, cmd: "/comp 公司", desc: "编译 yaml1 + 自动跑 DCF → forecast/" },
];

export const skills: SkillCard[] = [
  {
    key: "init",
    name: "/init",
    tag: "支线",
    when: "新公司入库、或日常更新数据。说\"init 美的集团\"、\"init 000333\"。",
    command: "/init 美的集团",
    input: "公司名 / 裸代码 / 完整 ticker（如 000333.SZ）。",
    output: "companies/{公司}/Agent/data.db（raw_tushare + clean_annual + clean_quarterly）+ 年报 PDF/MD。",
    next: "数据干净后 → /brkd 做业务预理解，或直接 /ka。",
    discipline: ["退出码 3（年报补全后仍硬失败）绝不改判成功", "raw_tushare 永不被修改"],
  },
  {
    key: "brkd",
    name: "/brkd",
    tag: "主线",
    when: "已有一堆研报/纪要，要先读懂业务再建模。说\"brkd 新乳业\"、\"拆一下某公司业务\"。",
    command: "/brkd 新乳业",
    input: "研报/纪要放进 active_vore/业务理解器（研报和纪要放在这里）/（PDF 自动转 MD）+ 公司判断和最新观点.md。",
    output: "companies/{公司}/Agent业务讨论.md（按业务线排 + 四级可信度 + partial knobs 块）。",
    next: "→ /ka：作业务预理解参考，ka 收入段直接搬历史/骨架、议旋钮。",
    discipline: ["碰旋钮给建议值但不拍板——拍板在 ka", "只收入分线；研报是线索不是权威"],
  },
  {
    key: "ka",
    name: "/ka",
    tag: "主线",
    when: "要生成或修改核心假设。说\"ka 新乳业\"。先读公司判断和最新观点.md 定调。",
    command: "/ka 新乳业",
    input: "公司判断和最新观点.md（定调）+ active_vore/核心假设生成（模型放在这里）/ 活跃素材 + 最新年报 + Agent业务讨论.md（若有）。",
    output: "companies/{公司}/{公司}-YYYYMMDD-核心假设.md（完整利润表建模 + knobs 块）。",
    next: "→ /comp：把核心假设编译成 yaml1 出 DCF。",
    discipline: ["只认公司根目录的核心假设*.md（非递归）", "产物必须落公司根目录，禁止写进子目录"],
  },
  {
    key: "comp",
    name: "/comp",
    tag: "主线",
    when: "核心假设.md 写好，要编译出 DCF。说\"comp 新乳业\"。",
    command: "/comp 新乳业",
    input: "核心假设.md + Agent/defaults.yaml + docs/数据格式参考.md + docs/yaml1算法模板契约.md。",
    output: "Agent/yaml1_公司_YYYYMMDD.yaml + Agent/forecast/（DCF，每次先清空再生成）。",
    next: "→ 工作台 DCF tab 看结果；不满意改核心假设重跑 /comp。",
    discipline: ["不读 PDF", "先动态加载最新版 yaml1compiler skill 再读材料"],
  },
  {
    key: "annual-update",
    name: "/annual-update",
    tag: "支线",
    when: "公司出年报了，把旧核心假设滚到最新。说\"annual-update 新乳业\"。",
    command: "/annual-update 新乳业",
    input: "旧 *-核心假设.md（公司根目录）+ 新年报（init 自动刷数据）。",
    output: "新日期的核心假设.md（旧稿原样留存）+ 新 DCF。",
    next: "→ /comp 收口；旧稿作复盘基准。",
    discipline: ["不在脏数据上滚（init exit 3 未闭合就停）", "旧稿只读、绝不覆写；拿不到的值标\"待校准\"不编数"],
  },
  {
    key: "webka",
    name: "/webka",
    tag: "支线",
    when: "本地上下文不够，要把核心假设素材搬到 Claude.ai 网页端跑。",
    command: "python -m src.webka 新乳业",
    input: "公司判断和最新观点.md + 活跃素材 + 最新年报 MD + 核心假设生成修改器 skill。",
    output: "companies/{公司}/WEBCLAUDE/核心假设部分/（打包素材，清空旧文件夹再放）。",
    next: "上传到 Claude.ai 网页端，配合核心假设生成修改器 skill 跑。",
    discipline: ["不读 PDF（只打包年报 .md）", "缺 MD 先 report_downloader --force-markdown 生成"],
  },
  {
    key: "webcomp",
    name: "/webcomp",
    tag: "支线",
    when: "要把 yaml1 编译素材搬到 Claude.ai 网页端跑。",
    command: "python -m src.webcomp 新乳业",
    input: "核心假设.md + defaults.yaml + 数据格式参考.md + yaml1算法模板契约.md + yaml1compiler skill。",
    output: "companies/{公司}/WEBCLAUDE/yaml1编译部分/（打包素材）。",
    next: "上传到 Claude.ai 网页端，配合 yaml1compiler skill 跑。",
    discipline: ["不读 PDF", "defaults.yaml 是目标命名空间，不是输入假设"],
  },
];
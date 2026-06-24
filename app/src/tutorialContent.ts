// 静态教程内容：skills 数据 + 管线 + 新手路线。
// 配置项走 /api/settings；教程内容保持前端静态，方便发布版离线使用。
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
  { label: "/init", desc: "刷新数据到 clean_annual / clean_quarterly，是全链路前置动作。" },
  { label: "/annual-update", desc: "年报发布后，把旧核心假设滚动到最新年份。" },
  { label: "/webka / /webcomp", desc: "把素材打包到 WEBCLAUDE，交给网页端模型跑。" },
];

export const quickstart: { step: number; cmd: string; desc: string }[] = [
  { step: 1, cmd: "/init 公司", desc: "拉 TuShare 数据、清洗、补年报，生成 Agent/data.db。" },
  { step: 2, cmd: "/brkd 公司", desc: "读研报和纪要，生成业务预理解。" },
  { step: 3, cmd: "/ka 公司", desc: "结合观点、年报和业务讨论，生成核心假设。" },
  { step: 4, cmd: "/comp 公司", desc: "编译 yaml1 并生成 DCF，回到工作台查看。" },
];

export const skills: SkillCard[] = [
  {
    key: "init",
    name: "/init",
    tag: "支线",
    when: "新公司入库，或日常刷新数据。",
    command: "/init 美的集团",
    input: "公司名、股票代码或完整 ticker，例如 000333.SZ。",
    output: "companies/{公司}/Agent/data.db，以及年报 PDF/MD。",
    next: "数据干净后跑 /brkd 做业务预理解，或直接进入 /ka。",
    discipline: ["硬失败不要强行继续。", "raw_tushare 永不手改。"],
  },
  {
    key: "brkd",
    name: "/brkd",
    tag: "主线",
    when: "已有研报、纪要，要先读懂业务再建模。",
    command: "/brkd 新乳业",
    input: "把研报/纪要放进 active_vore/业务理解器（研报和纪要放在这里）/。",
    output: "companies/{公司}/Agent业务讨论.md。",
    next: "进入 /ka，作为收入段和业务线判断的参考。",
    discipline: ["只做业务线理解，不拍最终旋钮。", "研报是线索，不是权威。"],
  },
  {
    key: "ka",
    name: "/ka",
    tag: "主线",
    when: "生成或修改核心假设。",
    command: "/ka 新乳业",
    input: "公司判断和最新观点.md、活跃素材、最新年报、Agent业务讨论.md。",
    output: "companies/{公司}/{公司}-YYYYMMDD-核心假设.md。",
    next: "进入 /comp，把核心假设编译成 yaml1 并生成 DCF。",
    discipline: ["核心假设产物必须落公司根目录。", "先读定调文件，再写假设。"],
  },
  {
    key: "comp",
    name: "/comp",
    tag: "主线",
    when: "核心假设写好后，编译出可计算模型。",
    command: "/comp 新乳业",
    input: "核心假设.md、Agent/defaults.yaml、数据格式参考、yaml1 算法模板契约。",
    output: "Agent/yaml1_公司_YYYYMMDD.yaml 和 Agent/forecast/。",
    next: "在工作台 DCF tab 看结果，不满意再改核心假设重跑。",
    discipline: ["不读 PDF。", "先加载最新 yaml1 compiler skill。"],
  },
  {
    key: "annual-update",
    name: "/annual-update",
    tag: "支线",
    when: "年报发布后，把旧核心假设滚到最新年份。",
    command: "/annual-update 新乳业",
    input: "旧核心假设.md 和新年报。",
    output: "新日期核心假设.md，以及新的 DCF 输出。",
    next: "用 /comp 收口；旧稿保留作复盘基准。",
    discipline: ["数据硬失败未闭合就停。", "旧稿只读，不覆盖。"],
  },
  {
    key: "webka",
    name: "/webka",
    tag: "支线",
    when: "需要把核心假设素材打包到 Claude.ai 网页端运行。",
    command: "python -m src.webka 新乳业",
    input: "观点文件、活跃素材、年报 MD、核心假设生成修改器 skill。",
    output: "WEBCLAUDE/核心假设部分/。",
    next: "上传到网页端配合 skill 跑。",
    discipline: ["不读 PDF，只打包 MD。", "缺 MD 先生成。"],
  },
  {
    key: "webcomp",
    name: "/webcomp",
    tag: "支线",
    when: "需要把 yaml1 编译素材打包到 Claude.ai 网页端运行。",
    command: "python -m src.webcomp 新乳业",
    input: "核心假设、defaults.yaml、数据格式参考、yaml1 compiler skill。",
    output: "WEBCLAUDE/yaml1编译部分/。",
    next: "上传到网页端配合 yaml1compiler 跑。",
    discipline: ["不读 PDF。", "defaults.yaml 是目标命名空间，不是输入假设。"],
  },
];

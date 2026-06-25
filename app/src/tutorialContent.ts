// 静态教程内容：skills 数据 + 管线 + 新手路线。
// 配置项走 /api/settings；教程内容保持前端静态，方便发布版离线使用。
export type SkillCard = {
  key: string;
  name: string;
  tag: "数据层" | "主线" | "滚续" | "增强" | "强烈推荐";
  headline: string;
  when: string;
  command: string;
  reads: string[];
  writes: string[];
  next: string;
  guardrails: string[];
  mentalModel: string;
  notFor?: string;
};

export type SkillPrinciple = {
  key: string;
  name: string;
  role: string;
  principle: string;
  why: string;
  orchestration: string[];
  stops: string[];
  handoff: string;
};

export type PipelineStage = {
  key: string;
  cmd: string;
  analystJob: string;
  title: string;
  feature: string;
  output: string;
  area: "init" | "load" | "brkd" | "paipai" | "ka" | "comp" | "da";
  tone: "foundation" | "source" | "decision" | "engine" | "addon";
  badge?: string;
};

export const pipelineStages: PipelineStage[] = [
  {
    key: "init",
    cmd: "/init",
    analystJob: "准备历史底稿",
    title: "取数、核对、形成历史底稿",
    feature: "自动整理财务历史、关键指标和年报口径，给后续预测准备一份可以直接使用的分析底稿。",
    output: "历史财务底稿 + 指标速览",
    area: "init",
    tone: "foundation",
    badge: "基础工作",
  },
  {
    key: "load",
    cmd: "/load",
    analystJob: "拆外部模型",
    title: "提炼 Excel 模型的关键假设",
    feature: "读取券商或自建模型中的收入、利润率、费用、资本开支等判断，整理成后续可讨论的假设稿。",
    output: "外部模型假设稿",
    area: "load",
    tone: "source",
    badge: "新增",
  },
  {
    key: "brkd",
    cmd: "/brkd",
    analystJob: "整理业务材料",
    title: "把研报纪要变成讨论提纲",
    feature: "把业务线索、管理层表述和市场预期整理到收入、毛利、费用、税率等议题下。",
    output: "业务讨论稿",
    area: "brkd",
    tone: "source",
    badge: "新增",
  },
  {
    key: "paipai",
    cmd: "/paipai",
    analystJob: "读取 Alphapai",
    title: "从 Alphapai 获取业务理解",
    feature: "用专业提示词让 Alphapai 检索自有金融数据库，输出最新进展、业务理解和关键假设，作为待 /ka 裁决的候选来源。",
    output: "Alphapai 候选假设稿",
    area: "paipai",
    tone: "source",
    badge: "规划中",
  },
  {
    key: "ka",
    cmd: "/ka",
    analystJob: "确认核心假设",
    title: "形成正式投资假设",
    feature: "把分析师观点、外部模型和材料线索合并审阅，逐项确认未来收入、利润率和关键参数。",
    output: "正式核心假设",
    area: "ka",
    tone: "decision",
    badge: "中枢",
  },
  {
    key: "da",
    cmd: "/da",
    analystJob: "重资产排程",
    title: "重资产公司专项排程",
    feature: "适用于产能扩张、固定资产和折旧对估值影响较大的公司，单独管理 Capex 与折旧节奏。",
    output: "DA 排程",
    area: "da",
    tone: "addon",
    badge: "可选",
  },
  {
    key: "comp",
    cmd: "/comp",
    analystJob: "生成估值结果",
    title: "生成三表与 DCF",
    feature: "把已经确认的假设转成利润表、资产负债表、现金流量表和 DCF 输出。",
    output: "三表 + DCF 结果",
    area: "comp",
    tone: "engine",
  },
];

export type PipelineAuxGroup = {
  title: string;
  items: { cmd: string; analystJob: string; note: string; output: string; recommended?: boolean }[];
};

export const pipelineAux: PipelineAuxGroup[] = [
  {
    title: "后续维护和更新",
    items: [
      {
        cmd: "/adj quick",
        analystJob: "快速试算",
        note: "只调整已开放的小幅参数，确认后立即刷新估值结果。",
        output: "更新后的 DCF",
      },
      {
        cmd: "/adj incremental",
        analystJob: "吸收新增信息",
        note: "读新增材料，先判断影响哪些假设，再更新正式假设和结果。",
        output: "更新后的核心假设",
      },
      {
        cmd: "/annual-update",
        analystJob: "年度更新",
        note: "新年报披露后，先更新历史数据，再把旧预测向前滚续。",
        output: "新版核心假设",
      },
      {
        cmd: "/webload",
        analystJob: "网页端读模型",
        note: "Excel 模型很长或结构复杂时，用网页端入口打包读取。",
        output: "模型读取包",
        recommended: true,
      },
    ],
  },
];

// 入口路由：根据手头是否有外部模型和 /brkd 产物，决定从哪一站开始。
export const entryRoutes: { n: number; title: string; route: string; desc: string }[] = [
  {
    n: 1,
    title: "从 Alphapai 获得建模所需核心假设",
    route: "/paipai -> /ka -> /comp",
    desc: "让 Alphapai 检索自有金融数据库，先吐出业务理解和关键假设，再进入正式确认。",
  },
  {
    n: 2,
    title: "已有 Excel 完整模型",
    route: "/load -> /ka -> /comp",
    desc: "上传券商或自建模型，先提炼其中的收入、毛利、费用等假设，再进入正式确认。",
  },
  {
    n: 3,
    title: "只有研报、纪要或年报",
    route: "/brkd -> /ka -> /comp",
    desc: "先整理业务线索和利润表关注点，再进入核心假设确认。",
  },
  {
    n: 4,
    title: "已有模型，只想调一版",
    route: "/adj 或 /annual-update",
    desc: "小幅试算用 /adj quick；有新材料用 /adj incremental；新年报披露后用 /annual-update。",
  },
];

export type WorkspaceDropzone = {
  path: string;
  skill: string;
  title: string;
  body: string;
  output: string;
  badge?: string;
};

export const workspaceDropzones: WorkspaceDropzone[] = [
  {
    path: "Skills素材包/LOAD外部EXCEL模型理解器（一次最多一个）/",
    skill: "/load",
    title: "放完整 Excel 模型",
    body: "正式跑 /load 前，把唯一一份券商或自建模型放在这里。系统会读模型当时的预测口径，提炼成待讨论的核心假设稿。",
    output: "{原Excel文件名}_核心假设.md",
    badge: "一次一个",
  },
  {
    path: "Skills素材包/BRKD业务理解器（研报和纪要放在这里）/",
    skill: "/brkd",
    title: "放需要阅读的研报、纪要",
    body: "把真正希望 Agent 阅读的业务材料放这里。/brkd 会先转成 markdown 存储区，再整理成收入、毛利、费用、税率等讨论提纲。",
    output: "Agent业务讨论.md",
  },
  {
    path: "Skills素材包/最高权重材料-放Agent最应对齐的材料/",
    skill: "/ka",
    title: "放最应该对齐的材料",
    body: "这里是 /ka 的最高权重来源。适合放你最认可的内部判断、会议纪要或必须优先采用的观点材料。",
    output: "正式核心假设的重要依据",
    badge: "最高权重",
  },
  {
    path: "Skills素材包/ADJ增量信息（用来改模型的边际信息）/",
    skill: "/adj incremental",
    title: "放新增边际信息",
    body: "已有核心假设后，如果出现新经营信息、新公告或新纪要，放这里让 /adj incremental 先判断影响哪些假设，再更新模型。",
    output: "更新后的核心假设与结果",
  },
];

export type WorkspaceFolder = {
  path: string;
  title: string;
  body: string;
  note: string;
};

export const workspaceArchiveFolders: WorkspaceFolder[] = [
  {
    path: "研报/、纪要/、收集/",
    title: "普通资料仓",
    body: "适合给人归档、查阅和留痕。Agent 默认不会主动扫这些文件夹。",
    note: "需要让 /brkd 阅读时，把选定材料复制到 BRKD 素材包。",
  },
  {
    path: "内部报告/、重要文件/",
    title: "人工保留区",
    body: "适合放内部报告、原始文件和你暂时不想进入模型链路的材料。",
    note: "需要让 /ka 强制对齐时，放到最高权重材料，或整理成 公司判断和最新观点.md。",
  },
  {
    path: "公告/年报/、公告/季报/",
    title: "公告事实区",
    body: "这是普通资料区里的例外。/init 会读取或下载年报、季报，用于历史核对和口径查证。",
    note: "临时公告通常给人查阅；要进模型更新，请复制到 ADJ 或 BRKD 素材包。",
  },
];

export const workspaceRootFiles: WorkspaceFolder[] = [
  {
    path: "核心假设.md / 新日期-核心假设.md",
    title: "正式判断稿",
    body: "这是人话判断权威层，/comp 会把它编译成机器可读假设，再生成三表和 DCF。",
    note: "不要把 LOAD、BRKD 的草稿当正式稿；它们要经过 /ka 拍板。",
  },
  {
    path: "公司判断和最新观点.md",
    title: "分析师当前观点",
    body: "如果存在，它会被视为最高权重材料之一，和最高权重材料文件夹一起进入 /ka。",
    note: "适合写你当前最想让模型体现的投资判断。",
  },
  {
    path: "根目录 Excel 文件",
    title: "临时存放可以，正式投喂要搬走",
    body: "根目录里看到 Excel 不代表 /load 会自动读取。正式跑 /load 前，应放进 LOAD 素材包。",
    note: "一次只放一个模型，避免混读不同版本。",
  },
];

export const workspaceAgentAreas: WorkspaceFolder[] = [
  {
    path: "Agent/data.db、Agent/recon/",
    title: "历史数据与核对痕迹",
    body: "/init 和清洗链路的产物，负责保存可信历史和对账结果。",
    note: "不要手工改，历史问题回到 /init 或数据清洗链路解决。",
  },
  {
    path: "Agent/Load/、Agent/forecast/",
    title: "技能沙箱与正式输出",
    body: "/load 的候选假设源文、/comp 的三表和 DCF 结果会落在 Agent 工作区。",
    note: "看结果可以进来，投喂材料不要放这里。",
  },
  {
    path: "Agent/yaml1*.yaml、Agent/.modelking/forecast_params.yaml",
    title: "编译产物",
    body: "/comp 把核心假设转成 yaml1，再编译成模型可运行的 forecast_params。",
    note: "普通用户不用手改；小幅试算走 /adj quick。",
  },
  {
    path: "Agent/KAhistory、DAhistory、Logs、OfficialBreakdowns",
    title: "版本、日志和拆分依据",
    body: "保存核心假设历史稿、DA 排程历史、运行日志和官方拆分表。",
    note: "用于复盘和审计，不作为材料投喂入口。",
  },
];

export type WorkspaceFolderTreeGroup = {
  title: string;
  tag: string;
  tone: "root" | "archive" | "input" | "agent";
  rows: { name: string; purpose: string; action: string; hot?: boolean }[];
};

export const workspaceFolderTree: WorkspaceFolderTreeGroup[] = [
  {
    title: "根目录",
    tag: "正式稿和少量人工文件",
    tone: "root",
    rows: [
      { name: "核心假设.md", purpose: "正式判断稿", action: "/comp 读取", hot: true },
      { name: "公司判断和最新观点.md", purpose: "分析师当前观点", action: "/ka 最高权重" },
      { name: "*.xlsx", purpose: "临时存放", action: "跑 /load 前移到 LOAD" },
    ],
  },
  {
    title: "普通资料区",
    tag: "给人放东西",
    tone: "archive",
    rows: [
      { name: "内部报告/", purpose: "人工归档", action: "Agent 不读" },
      { name: "研报/", purpose: "人工归档", action: "Agent 不读" },
      { name: "纪要/", purpose: "人工归档", action: "Agent 不读" },
      { name: "收集/", purpose: "人工归档", action: "Agent 不读" },
      { name: "重要文件/", purpose: "人工归档", action: "Agent 不读" },
      { name: "公告/年报、季报/", purpose: "历史核对", action: "/init 会读", hot: true },
      { name: "公告/临时公告/", purpose: "公告归档", action: "要用就复制到素材包" },
    ],
  },
  {
    title: "Skills素材包",
    tag: "Agent 投喂入口",
    tone: "input",
    rows: [
      { name: "LOAD外部EXCEL模型理解器/", purpose: "完整 Excel 模型", action: "/load · 一次一个", hot: true },
      { name: "BRKD业务理解器/", purpose: "研报、纪要、年报材料", action: "/brkd", hot: true },
      { name: "最高权重材料/", purpose: "最该对齐的材料", action: "/ka", hot: true },
      { name: "ADJ增量信息/", purpose: "新增边际信息", action: "/adj incremental" },
    ],
  },
  {
    title: "Agent",
    tag: "程序产物区",
    tone: "agent",
    rows: [
      { name: "forecast/", purpose: "三表和 DCF", action: "看结果", hot: true },
      { name: "Load/", purpose: "外部模型读取沙箱", action: "看草稿" },
      { name: "data.db、recon/", purpose: "历史数据和核对", action: "不要手改" },
      { name: "yaml1*.yaml、.modelking/", purpose: "编译产物", action: "不要手改" },
      { name: "KAhistory、Logs/", purpose: "历史稿和日志", action: "复盘用" },
    ],
  },
];

export const workspacePlacementTips: { material: string; put: string; run: string }[] = [
  { material: "完整 Excel 模型", put: "Skills素材包 / LOAD外部EXCEL模型理解器", run: "/load" },
  { material: "希望 Agent 读的研报、纪要", put: "Skills素材包 / BRKD业务理解器", run: "/brkd" },
  { material: "必须优先采用的观点材料", put: "最高权重材料 或 公司判断和最新观点.md", run: "/ka" },
  { material: "新增信息，想改已有模型", put: "Skills素材包 / ADJ增量信息", run: "/adj incremental" },
  { material: "只是想存档", put: "内部报告 / 研报 / 纪要 / 收集 / 重要文件", run: "不用跑" },
];

// 新手路线：按手头是否有完整 Excel 模型拆成两条，中间一站不同，首尾相同。
export type QuickstartRoute = {
  key: string;
  title: string;
  when: string;
  steps: { cmd: string; desc: string }[];
};

export const quickstartRoutes: QuickstartRoute[] = [
  {
    key: "have-model",
    title: "有模型",
    when: "手头已有券商或自建 Excel 完整模型。",
    steps: [
      { cmd: "/init 公司", desc: "准备历史财务底稿和指标速览。" },
      { cmd: "放 Excel", desc: "把唯一模型放进 LOAD 素材包。" },
      { cmd: "/load 公司", desc: "提炼外部模型里的关键预测假设。" },
      { cmd: "/ka 公司", desc: "结合最高权重材料和分析师观点，确认正式假设。" },
      { cmd: "/comp 公司", desc: "生成正式三表和 DCF，回工作台看结果。" },
    ],
  },
  {
    key: "no-model",
    title: "无模型",
    when: "没有完整 Excel 模型，但有研报、纪要或年报材料。",
    steps: [
      { cmd: "/init 公司", desc: "准备历史财务底稿和指标速览。" },
      { cmd: "放材料", desc: "把研报、纪要或年报放进 BRKD 素材包。" },
      { cmd: "/brkd 公司", desc: "整理业务线索和利润表讨论点。" },
      { cmd: "/ka 公司", desc: "确认收入、毛利、费用和税率等核心假设。" },
      { cmd: "/comp 公司", desc: "生成正式三表和 DCF，回工作台看结果。" },
    ],
  },
  {
    key: "adjust-existing",
    title: "调已有模型",
    when: "公司已有正式假设和估值结果，只想试算或纳入新信息。",
    steps: [
      { cmd: "/adj 公司 把毛利率稍微提一提", desc: "小幅调整已开放参数，确认后立即刷新 DCF。" },
      { cmd: "放增量材料", desc: "如果是新经营信息，把材料放进 ADJ 素材包。" },
      { cmd: "/adj 公司 增量", desc: "先讨论影响哪些假设，再更新正式假设和新结果。" },
      { cmd: "/annual-update 公司", desc: "如果是新年报真实数据披露，走年度更新，不走普通调参。" },
    ],
  },
];

export const codexGuideFlow: { title: string; body: string }[] = [
  {
    title: "1. 新线程先贴开场",
    body: "不管要做什么，先让 Codex 读取 D:\\MKA\\Codex.md。读完只允许汇报理解，不要立刻改文件。",
  },
  {
    title: "2. 再贴任务模板",
    body: "把【公司名】换成目标公司。要跑哪个技能，就复制对应模板；模板已经写好它该读哪个 skill、该停在哪里。",
  },
  {
    title: "3. 最后要求交付清单",
    body: "让 Codex 说清楚产物路径、改了哪些文件、跑了什么验证、还有没有阻塞。这样你不用猜它到底做完没有。",
  },
];

export const codexGuidePrompts: { label: string; command: string; when: string; prompt: string }[] = [
  {
    label: "每个新线程第一条",
    command: "万能开场",
    when: "新开 Codex 线程时先复制这条。",
    prompt: "请先完整读取 D:\\MKA\\Codex.md，理解 MKA 的项目结构和工作纪律。读完后不要改文件，先用 5 行以内告诉我：1）你理解的主线是什么；2）当前任务通常应该先看哪些目录；3）你准备怎么执行我接下来的指令。",
  },
  {
    label: "已有 Excel 模型",
    command: "/load",
    when: "Excel 已放进 LOAD 素材包，一次只有一个模型。",
    prompt: "公司【公司名】要跑 /load。请先读 D:\\MKA\\Codex.md，再读 D:\\MKA\\.claude\\skills\\load\\SKILL.md。然后检查公司目录下 Skills素材包\\LOAD外部EXCEL模型理解器（一次最多一个），确认里面只有一个 Excel。按 /load 规则执行，只在 Agent/Load 沙箱生成 {原Excel文件名}_核心假设.md，不要写正式 核心假设.md。完成后告诉我产物路径、模型时间边界、提炼出的收入/毛利/费用/资本开支关键假设。",
  },
  {
    label: "只有研报纪要",
    command: "/brkd",
    when: "研报、纪要或年报材料已放进 BRKD 素材包。",
    prompt: "公司【公司名】要跑 /brkd。请先读 D:\\MKA\\Codex.md，再读 D:\\MKA\\.claude\\skills\\brkd\\SKILL.md。先执行 brkd_prepare：把 Skills素材包\\BRKD业务理解器（研报和纪要放在这里）里的文件幂等转成 markdown 存储区。然后让 AI 阅读这些 markdown，生成 Agent业务讨论.md。不要写正式 核心假设.md。完成后告诉我 markdown 存储区、Agent业务讨论.md 路径，以及收入/毛利/费用/税率的主要讨论点。",
  },
  {
    label: "确认正式假设",
    command: "/ka",
    when: "已有 LOAD 产物或 Agent业务讨论.md，要生成正式核心假设。",
    prompt: "公司【公司名】要跑 /ka。请先读 D:\\MKA\\Codex.md，再读 D:\\MKA\\.claude\\skills\\ka\\SKILL.md。先检查是否至少有一个 LOAD 产物或 Agent业务讨论.md；如果两个都没有，停止并建议先跑 /load 或 /brkd。然后按权重读取：最高权重材料和 公司判断和最新观点.md、BRKD 产物、LOAD 产物、必要时年报查证。先对齐时间边界，再进入收入/毛利/费用/below-OP/中期假设裁决。最后写正式 核心假设.md，并告诉我产物路径和仍有争议的假设。",
  },
  {
    label: "生成三表 DCF",
    command: "/comp",
    when: "已经有正式 核心假设.md。",
    prompt: "公司【公司名】要跑 /comp。请先读 D:\\MKA\\Codex.md，再读 D:\\MKA\\.claude\\skills\\comp\\SKILL.md。读取最新正式 核心假设.md，忠实编译成 Agent/yaml1_*.yaml，跑 yaml1 fidelity check，然后生成 Agent/.modelking/forecast_params.yaml 和 Agent/forecast/ 三表与 DCF。完成后告诉我 yaml1 路径、forecast 路径、每股价值、warnings 数量和验证结果。",
  },
  {
    label: "快速调一版",
    command: "/adj quick",
    when: "只想小幅拨已有 knob，比如毛利率略调。",
    prompt: "公司【公司名】要做 /adj quick：『【把这里换成你的调整要求，例如：把毛利率稍微提一提】』。请先读 D:\\MKA\\Codex.md，再读 D:\\MKA\\.claude\\skills\\adj\\SKILL.md。先判断这个要求是不是在已有 knobs 内；如果不是，停止并建议可调整的已有 knobs。若可以，先给我 patch plan 并等待确认；确认后再改 核心假设.md 和当前 yaml1，跑 fidelity check 和新的 DCF。完成后告诉我改动行、yaml1 patch、每股价值变化和 forecast 路径。",
  },
  {
    label: "读新增材料改模型",
    command: "/adj incremental",
    when: "有新纪要、新公告、新研报，需要系统性改假设。",
    prompt: "公司【公司名】要做 /adj incremental。请先读 D:\\MKA\\Codex.md，再读 D:\\MKA\\.claude\\skills\\adj\\SKILL.md。先把 Skills素材包\\ADJ增量信息（用来改模型的边际信息）里的文件幂等转成 markdown，再阅读新增信息。先和我讨论哪些核心假设受影响，不要直接改 yaml1；确认后更新 核心假设.md，再走 /comp 重新编译并跑 DCF。完成后告诉我新增材料摘要、受影响假设、核心假设路径和新 forecast 路径。",
  },
  {
    label: "新年报滚续",
    command: "/annual-update",
    when: "新真实年份出来，需要用年报覆盖旧预测。",
    prompt: "公司【公司名】出了新年报，要做 /annual-update。请先读 D:\\MKA\\Codex.md，再读 D:\\MKA\\.claude\\skills\\annual-update\\SKILL.md。先确认 /init 已更新可信历史数据；然后按 annual-update 规则把旧核心假设向前滚续，不要当成普通调参。完成后再走 /comp 跑 DCF，并告诉我新核心假设路径、新 yaml1 路径、新 forecast 路径和主要滚续变化。",
  },
  {
    label: "改工作台前端",
    command: "前端改版",
    when: "要改教程页、工作台展示、交互或样式。",
    prompt: "请先读 D:\\MKA\\Codex.md，理解项目结构。然后修改工作台前端：任务是【把这里换成你的需求】。改动前先看 app/src/Tutorial.tsx、app/src/tutorialContent.ts、app/src/styles.css 和相关组件；改完必须跑 npm run build。如果涉及界面布局，请用浏览器预览桌面和窄屏，最后告诉我改了哪些文件、构建是否通过、预览发现了什么。",
  },
];

export const codexGuideRules: { title: string; body: string }[] = [
  {
    title: "不要直接说“跑一下 /ka”",
    body: "Codex 不一定知道 Claude slash command 的内部规则。最好复制模板，让它先读 D:\\MKA\\.claude\\skills\\ka\\SKILL.md 再执行。",
  },
  {
    title: "公司名一定要写清楚",
    body: "模板里的【公司名】要替换成工作台里的公司名，例如 新乳业。路径不确定时，让 Codex 先列 companies 目录再选。",
  },
  {
    title: "让它先汇报再落盘",
    body: "/ka、/adj quick、/annual-update 这种会改正式判断的任务，要让 Codex 先说明计划或 patch plan，再确认写入。",
  },
  {
    title: "结果必须报路径",
    body: "每次结束都要求它给出核心假设、yaml1、forecast、markdown 存储区等实际路径，否则你很难判断它是否真的完成。",
  },
  {
    title: "不能跳过验证",
    body: "前端改动必须 npm run build；/comp 和 /adj quick 必须有 fidelity check 或 DCF 运行结果；失败就让它停下来说明原因。",
  },
];

export const skillPrincipleStack: { title: string; body: string }[] = [
  {
    title: "启动器层",
    body: "D:\\MKA\\.claude\\skills 里的 SKILL.md 是可用入口，负责解析公司、判断模式、做门禁、选择最新版动态 skill。废弃入口移到 D:\\MKA\\deprecatedlogs，不再出现在教程主线里。",
  },
  {
    title: "动态细则层",
    body: "D:\\MKA\\skills 里的 *_skill_vN.md 才是每个复杂技能的 runbook。版本号最大的文件生效，方便不断升级 /ka、/comp、annual-update、/da 的规则。",
  },
  {
    title: "确定性脚本层",
    body: "取数、清洗、编译后展开、forecast、DCF 都尽量交给 Python。LLM 负责读懂、翻译、提出候选；真正写库、验闭合、算 DCF 的地方由代码守门。",
  },
  {
    title: "人类拍板层",
    body: "凡是未来判断、参数化选择、估算口径，都必须回到人话权威层 核心假设.md。yaml1 是机器可读覆盖层，forecast_params.yaml 是内部编译产物，都不是让人绕过去直接改的源头。",
  },
];

export const skillSystemInvariants: { code: string; title: string; body: string }[] = [
  {
    code: "I-01",
    title: "raw_tushare 不可变",
    body: "TuShare 原始返回只做镜像留存。任何补数、重分类、豁免和人工判断都不能回写 raw，只能进入 clean 调整层或 approved overrides。",
  },
  {
    code: "I-02",
    title: "clean 是历史事实层",
    body: "clean_annual / clean_quarterly 通过配平、桥接和年报核对后，才允许成为预测起点。clean 失败必须显性停机。",
  },
  {
    code: "I-03",
    title: "核心假设.md 是判断源头",
    body: "收入、毛利、费用、税率、terminal 和所有旋钮的主观判断，只能以人话形式沉淀在核心假设层。",
  },
  {
    code: "I-04",
    title: "yaml1 只是机器覆盖层",
    body: "/comp 负责忠实翻译核心假设，不替分析师重算判断。yaml1 可以稀疏覆盖 defaults，但不能变成新的研究结论源。",
  },
  {
    code: "I-05",
    title: "forecast_params 与 calc 输出只读",
    body: "forecast_params.yaml、三表和 DCF 明细都是派生产物。修正必须回到核心假设或数据源，不能直接 patch 派生结果。",
  },
  {
    code: "I-06",
    title: "门禁先于落盘",
    body: "时间轴、staleness、骨架门、同源核对、年度闭合和沙箱边界，必须在写入或覆盖正式产物前完成。",
  },
];

export const skillArtifactContracts: { artifact: string; owner: string; writeBoundary: string; contract: string }[] = [
  {
    artifact: "raw_tushare",
    owner: "/init",
    writeBoundary: "只增量镜像",
    contract: "原始数据留痕，不做主观修正，不作为预测判断层。",
  },
  {
    artifact: "clean_annual / clean_quarterly",
    owner: "/init + clean.py",
    writeBoundary: "通过 hard check 后写入",
    contract: "可信历史宽表，是 /brkd、/ka、/comp 的事实校验层。",
  },
  {
    artifact: "defaults.yaml",
    owner: "/init / forecast",
    writeBoundary: "由 clean 历史生成",
    contract: "机器平推底座，不代表分析师观点，只提供目标命名空间。",
  },
  {
    artifact: "LOAD / BRKD 产物",
    owner: "/load / /brkd",
    writeBoundary: "各自沙箱或讨论稿",
    contract: "候选理解层，不自动成为正式核心假设。",
  },
  {
    artifact: "核心假设.md",
    owner: "/ka / /adj / /annual-update / /frontend-edit",
    writeBoundary: "分析师拍板后写入",
    contract: "人话权威层，是所有主观预测和估值判断的唯一源头。",
  },
  {
    artifact: "yaml1*.yaml",
    owner: "/comp 或 /adj quick / /frontend-edit",
    writeBoundary: "由核心假设翻译或定点 patch",
    contract: "机器可读覆盖层，忠实承接人话判断，不独立做研究。",
  },
  {
    artifact: "forecast_params.yaml",
    owner: "yaml1_cleaner",
    writeBoundary: "内部编译生成",
    contract: "calc.py 可执行参数，只读，不作为人工编辑入口。",
  },
  {
    artifact: "Agent/forecast/",
    owner: "src.forecast / calc.py",
    writeBoundary: "正式运行输出",
    contract: "工作台展示的正式结果；LOAD 沙箱和前端试算不覆盖这里。",
  },
];

export const skillPrincipleFlow: string[] = [
  "TuShare 原始数据：/init 调 data_fetcher 拉取三表和公告，原始返回先进入 raw_tushare，不在这里做主观修正。",
  "raw_tushare 不可变镜像：所有补数、重分类、豁免都进入 clean_adjustments / clean_warnings / approved overrides，不能手改 raw。",
  "clean_annual / clean_quarterly 可信历史宽表：clean.py 与 reconciler/bridge 负责配平、查年报和硬门禁，失败就停止。",
  "defaults.yaml 机器平推底座：从 clean 历史生成无主观判断的默认预测命名空间，是 /comp 和 forecast 的机器底板。",
  "核心假设.md 人话判断：/ka 裁决最高权重材料、BRKD 与 LOAD；/adj、/annual-update、/frontend-edit 也必须回到这一层改判断。",
  "yaml1*.yaml 机器可读覆盖层：/comp 忠实把核心假设翻译成稀疏覆盖；/adj quick 和 /frontend-edit 只允许在已有 knob 纯数值小改时定点 patch，不替分析师重新判断。",
  "forecast_params.yaml 内部编译产物：yaml1_cleaner 把 defaults + clean + yaml1 折成 calc.py 可吃的标准参数，禁止手工当源头改。",
  "calc.py 三表 + DCF：forecast.py 调 calc.py 生成完整 IS/BS/CF、DCF 明细和摘要。",
  "Agent/forecast/ 正式输出：工作台只展示这里的正式结果；LOAD 沙箱和前端试算不是正式 forecast。",
];

export const skillPrinciples: SkillPrinciple[] = [
  {
    key: "init",
    name: "/init",
    role: "数据地基和可信历史宽表的生产线。",
    principle: "先保 raw_tushare 不变，再把它清洗成可被估值信任的 clean_annual / clean_quarterly，并在 clean 后生成后续 Agent 可直接读的核心指标速览。",
    why: "DCF 最怕在脏历史上讨论未来。/init 的价值不是多拉几个接口，而是让数据失败显性化，并把利润表主链路整理成 /brkd 和 /ka 能消费的事实底稿。",
    orchestration: [
      "解析公司名、裸代码或完整 ticker，交给 src.init 做确定性编排。",
      "TuShare 增量取三表，年报/季报下载并生成 Markdown。",
      "clean.py 生成 clean 宽表并做年度/季度 hard check。",
      "年度失败时先走 reconciler；复杂残差再用 subagent 读年报提案，由 bridge 验闭合后写 approved override。",
      "clean 成功后生成 Agent/core_metrics_overview.md/json/csv，供后续 Agent 快速理解收入、毛利率、费用率、利润率和税率趋势。",
      "生成 financial_expense.yaml、OfficialBreakdowns 和数据拉取报告。",
    ],
    stops: [
      "exit 3 代表 clean 数据仍不可信，不能改判成功。",
      "raw_tushare 永不手改；补数只进 clean_adjustments / clean_warnings。",
      "2010 前历史可降级入库，但要明确这是闸门规则，不是已被年报核对。",
    ],
    handoff: "交给 /brkd、/ka、/comp、/annual-update 和工作台作为历史事实底座；其中核心指标速览是 /brkd 无外部材料时的关键输入。",
  },
  {
    key: "brkd",
    name: "/brkd",
    role: "业务与利润表预讨论，不是最终模型。",
    principle: "它的美德是 discernment：把业务线、毛利/成本、费用率、below-OP、所得税和净利率先整理成可讨论的地图，但不替 /ka 拍最终旋钮。",
    why: "没有完整 Excel 模型时，/ka 不能凭空硬写。/brkd 先用 BRKD 素材包里的研报纪要增强；没有研报纪要时，也能用年报 + /init 历史财务事实生成保守版 Agent业务讨论.md。",
    orchestration: [
      "定位公司目录，最先读 公司判断和最新观点.md 作为背景锚。",
      "检查 Skills素材包/BRKD业务理解器（研报和纪要放在这里）：有材料就先跑 src.brkd_prepare，幂等转换到 markdown存储区；没有材料不失败。",
      "读取 /init 核心指标速览；没有速览时读取 Agent/data.db 的 clean_annual。缺 clean 历史事实则停，提示先 /init。",
      "读取最新年报 Markdown，用于查分部、成本毛利、费用、税收优惠和一次性项目。",
      "动态加载最新版 业务预理解器 skill_vN，AI 只读 markdown存储区和 manifest。",
      "按收入、毛利/成本、费用、below-OP 与税、净利率/待确认项分段整理建议和证据。",
      "输出公司根目录 Agent业务讨论.md，可带 draft knobs 供 /ka 接手。",
    ],
    stops: [
      "缺定调文件就停；BRKD 素材包为空不再停。",
      "无外部材料时若缺 /init 历史事实或最新年报 Markdown，则停。",
      "不读 PDF 原文，只读转换后的 Markdown。",
      "不生成核心假设、不写 yaml1、不跑 DCF；建议值只是 /ka 的起点。",
    ],
    handoff: "交给 /ka 当正式输入；/ka 仍需用年报和 clean_annual 校验 headline，并让分析师拍板。",
  },
  {
    key: "ka",
    name: "/ka",
    role: "全量裁决器：把最高权重材料、BRKD、LOAD 和 /init 校验层收口成 核心假设.md。",
    principle: "KA 不再读原始 Excel、研报或纪要，也不做旧稿 modify。它专职裁决：先对齐时间边界和骨架，再把多源候选压成可读、可追责、可被 /comp 翻译的人话判断。",
    why: "/ka 是业务理解层的中枢，因为它要同时处理分析师 thesis、BRKD 草稿、LOAD vintage 模型、/init 历史 headline、年报按需查证和下游可编译性。",
    orchestration: [
      "解析公司目录；若根目录已有正式核心假设且用户未明确重建，停止并提示改走 /adj 或 /annual-update。",
      "先加载共享核心纪律、核心假设源语言和最新版 核心假设编辑器 skill。",
      "运行 src.ka_prepare，把 公司判断和最新观点.md 与 Skills素材包/最高权重材料-放Agent最应对齐的材料 幂等 markdown 化。",
      "读取 Agent业务讨论.md，并扫描 Agent/Load/*/*_核心假设.md 中已经完成的 LOAD 产物。",
      "执行启动门槛：已完成 LOAD 产物和 Agent业务讨论.md 至少有一个；两者都没有则停止并建议先 /load 或 /brkd。",
      "读取 /init 核心指标速览或 clean_annual，再读取最新年报 Markdown。",
      "独立锁定历史末年、显式期、衰减期、永续增长点，解释官方 history_end 与 LOAD vintage 边界的差异。",
      "先做接缝总账和骨架门，再按收入、毛利、费用、below-OP 与税、中期/terminal 进入数值门。",
      "写盘前做收口核对；聊透写正式 核心假设.md，有悬项只写参考稿并标明不可直接 /comp。",
    ],
    stops: [
      "无已完成 LOAD 且无 Agent业务讨论.md 时不启动。",
      "不产 yaml1，不算 DCF，不直接改 clean 数据。",
      "不做局部 modify；小改走 /adj quick，增量材料走 /adj incremental，年报滚动走 /annual-update。",
      "派生预测不手算；旋钮必须精确、逐年、可机读，并同步 knobs 块。",
    ],
    handoff: "交给 /comp 翻译成 yaml1；没聊透时只能输出参考稿，不应伪装正式核心假设。",
  },
  {
    key: "load",
    name: "/load",
    role: "把旧 Excel 模型按它当时的时间轴装进 vintage 沙箱。",
    principle: "/load 是开了时间沙箱的 /ka：工作流尽量继承 /ka 的 overview、分段停止、先押再问，但模型时间轴拥有最高权威。",
    why: "旧模型最怕后验污染。若模型历史止于 2024A、从 2025E 开始预测，2025 年报和 clean_annual 的 2025 行即使已经存在，也不能拿来修正这份旧模型。",
    orchestration: [
      "解析公司并定位 Skills素材包/LOAD外部EXCEL模型理解器（一次最多一个）里的唯一 Excel。",
      "先运行 model_load prepare，用公式层锁 history_end_year、forecast_start_year 和 forecast_years。",
      "创建 Agent/Load/{load_id}/ 沙箱，生成 data_cutoff.db、defaults.yaml、model_boundary、forbidden_materials 和 {原Excel文件名}_核心假设.md 脚手架。",
      "加载最新版 KA 生成器和 模型装载器 覆盖层。",
      "先给模型理解 overview，用户确认后才按收入、毛利、费用、below-OP 与税、中期分段装载。",
      "确认完成后编译 yaml1_load 并用 model_load dcf 跑沙箱 DCF。",
    ],
    stops: [
      "时间轴冲突就停，不能先看年报补判断。",
      "用户未确认 overview 前，不补完核心假设、不编译、不跑 DCF。",
      "产物只落 Agent/Load/{load_id}/，不覆盖公司根目录核心假设和正式 forecast。",
    ],
    handoff: "load 结果只是 vintage 沙箱，不是当前正式 forecast；若要转正式模型，应另走 annual-update 或显式 promote 流程。",
  },
  {
    key: "webload",
    name: "/webload",
    role: "把 /load 沙箱和安全材料打包给网页版模型。",
    principle: "它是 /load 的网页搬运箱。先本地 prepare 锁时间边界，再把 allowed_materials、禁读清单、KA 生成器和 load 覆盖层复制到 WEBCLAUDE/模型装载部分。",
    why: "真正需要网页端跑的是 /load：它既要理解 Excel 公式层，又要避免未来材料泄漏，还要先讲模型理解让用户确认。网页版长上下文和强模型更适合承担这段会话。",
    orchestration: [
      "运行 py -m src.webload 公司 --overwrite。",
      "内部先调用 src.model_load.prepare 创建 Agent/Load/{load_id}/。",
      "清空 WEBCLAUDE/模型装载部分，防止旧包污染。",
      "复制 00_webload_网页端执行说明、load 启动器、model_boundary、forbidden_materials、{原Excel文件名}_核心假设.md 脚手架。",
      "复制最新版 核心假设生成修改器 skill 和 模型装载器 skill。",
      "复制 allowed_materials，网页端只看这些允许材料。",
    ],
    stops: [
      "prepare 失败或边界冲突就停。",
      "网页端不得读取 forbidden_materials 列出的正文。",
      "不生成、不修改、不编译；网页端生成的 {原Excel文件名}_核心假设.md 放回沙箱后，本地再跑 yaml1_load 和 DCF。",
    ],
    handoff: "网页端产出的 {原Excel文件名}_核心假设.md 放回 Agent/Load/{load_id}/ 后，继续本地编译 yaml1_load 并跑 src.model_load dcf。",
  },
  {
    key: "adj",
    name: "/adj",
    role: "已有正式核心假设的调整器，分 quick 和 incremental 两种模式。",
    principle: "quick 只拨已有 knobs，追求快但不越权；incremental 读 ADJ 增量材料，先理解业务影响，只改 核心假设.md，再让 /comp 重新生成 yaml1。",
    why: "/ka 删除 modify 后，需要一个专门处理正式稿改动的入口。小幅数值调整不该重开全量 KA，系统性新信息也不该直接手改 yaml1。",
    orchestration: [
      "解析公司和模式；包含“增量/读材料/边际信息”走 incremental，否则走 quick。",
      "共同定位公司根目录最新正式 核心假设.md、Agent 最新 yaml1、defaults、data.db 和当前 DCF。",
      "quick：读取 knobs 与 yaml1，判断用户请求是否对应已有 knobs；不是已有 knobs 就停止并列出可拨旋钮。",
      "quick：生成 patch plan，用户确认后归档旧稿、写新核心假设、定点 patch 今日 yaml1、跑 forecast。",
      "incremental：先运行 src.adj_prepare，把 Skills素材包/ADJ增量信息（用来改模型的边际信息）幂等转到 markdown存储区。",
      "incremental：加载 核心假设调整器 skill，讨论受影响假设清单；拍板后只改核心假设源文，再走 /comp。",
    ],
    stops: [
      "缺正式核心假设或最新 yaml1 时停止，因为 /adj 不负责从零生成。",
      "quick 不能新增/删除结构、改 compiler family、改显式期或 terminal。",
      "incremental 若推翻模型骨架或 thesis 基础，应弹回 /ka 重建，不硬补丁。",
      "增量材料的 unsupported/error 必须进入缺口区，不能静默忽略。",
    ],
    handoff: "quick 直接交给 forecast 输出新 DCF；incremental 交给 /comp 编译新 yaml1，再进入正式 Agent/forecast/。",
  },
  {
    key: "comp",
    name: "/comp",
    role: "把人话核心假设忠实翻译成机器话 yaml1，并立即跑 DCF。",
    principle: "compiler 是翻译器，不是研究员。它弥合业务线语言和机器路径语言的差异：能翻就翻，翻不了举旗，绝不猜。",
    why: "核心假设.md 按业务线讲判断，calc.py 只能吃逐年标准参数。/comp 负责把判断变成 yaml1，再交给 yaml1_cleaner 展开成 forecast_params.yaml。",
    orchestration: [
      "先跑 assumption_staleness 年份门禁；若 clean 实际年覆盖预测起点，立即停止并提示 /annual-update。",
      "动态加载最新版 yaml1compiler skill。",
      "读取最新核心假设.md、Agent/defaults.yaml、数据格式参考、yaml1算法模板契约、knobs块契约。",
      "盘点源文，逐句翻成 knob / decomposition / formula / stash 等结构。",
      "写 Agent/yaml1_公司_YYYYMMDD.yaml，随后跑 fidelity check。",
      "yaml1 落盘后立即 py -m src.forecast --yaml1，生成 Agent/forecast/。",
    ],
    stops: [
      "不读 PDF，不重新判断业务，不替原文改数。",
      "defaults.yaml 是目标命名空间，不是预测意见。",
      "yaml1 落盘是主成功；DCF 失败要明示，但不回滚 yaml1。",
    ],
    handoff: "交给 yaml1_cleaner -> forecast_params.yaml -> calc.py -> Agent/forecast/。",
  },
  {
    key: "annual-update",
    name: "/annual-update",
    role: "把放旧的核心假设滚到最新年报版本。",
    principle: "它不是从零 /ka，而是时间迁移：旧稿只读、数据先刷新、历史填或旗、未来再重定，最后用 /comp 收口。",
    why: "公司出了新年报后，旧预测的一部分变成真实历史。直接 /comp 会被年份门禁拦住，直接 /ka 又会丢掉旧稿复盘价值。",
    orchestration: [
      "读旧核心假设和定调文件，提取 H、显式期、衰减期、永续点，并建立总账。",
      "调用 /init 刷新数据和公告，再重建 defaults.yaml。",
      "调用 annual_update_fetcher 从 clean_annual 取 (H, A] 的标准事实线和偏离诊断。",
      "动态加载最新版 年度更新器 skill，自动平移时间轴、补真实历史、重吐 knobs。",
      "估算拿不到的非标原子时标明 估算·待校准，未来重定按年度更新器纪律先押再问。",
      "新稿另存，旧稿和旧 yaml1 留存；最后 /comp 生成新 DCF。",
    ],
    stops: [
      "init exit 3 未闭合就停，不在脏数据上滚。",
      "clean_annual 缺核心字段时停，不能用 0 或残差硬填。",
      "拿不到的事实只能估算带旗或待补，不能冒充真实历史。",
    ],
    handoff: "收口后交给 /comp；收口报告要列清自动填、估算、挂旗、重定和新旧 DCF 差异。",
  },
  {
    key: "da",
    name: "/da",
    role: "重资产公司专用的折旧摊销与 capex 排程外挂。",
    principle: "事实和假设分离。LLM 只扒年报事实和参与商议，未来排程必须拍板后写 da_schedule.yaml；真正滚 cohort、对齐 BS/CF/FCFF 的是 Python da_roll。",
    why: "默认 capex_pct + depr_rate 对重资产公司太粗，容易让固定资产、在建工程、折旧和自由现金流互相打架。",
    orchestration: [
      "解析公司目录，第一时间读 公司判断和最新观点.md，可参考 Agent业务讨论.md 的产能线索。",
      "判断是否已有 Agent/da_schedule.yaml，并动态加载最新版 da 执行细则。",
      "并行抽取年报固定资产、在建工程、PP&E 折旧等事实，写 Agent/recon/da_facts_latest.json。",
      "按 capex 六点商议未来扩张、维持、转固、年限、残值和终值稳态。",
      "拍板后写 Agent/da_schedule.yaml；enabled: true 时 forecast 自动注入 da_series。",
      "forecast 中 da_roll 负责 capex 单一来源、PP&E 折旧、fix_assets / cip 和 FCFF 对齐。",
    ],
    stops: [
      "轻资产或稳态公司不要用，避免把简单模型复杂化。",
      "da_schedule.base_year 必须等于 defaults.base_period，否则 DaAlignError。",
      "无形资产、使用权资产、长摊不进 da_schedule，仍由 yaml1/defaults 管。",
    ],
    handoff: "落盘后重跑 forecast；重资产模式下 yaml1 的 capex_pct 被禁用并告警。",
  },
  {
    key: "frontend-edit",
    name: "/frontend-edit",
    role: "把前端试算结果安全回写到人话权威层。",
    principle: "它是一把手术刀，不是研究员。前端已经完成试算和拍板，技能只做定点 patch：改核心假设正文和 knobs 块，并在 A4 白名单内 patch 当前 yaml1 后跑 forecast。",
    why: "工作台里的 assumption-preview 只是内存试算。要让正式 DCF 生效，必须回到 核心假设.md；已有 knob 纯数值小改可按核心纪律 A4 定点更新 yaml1 派生缓存，结构性改动仍回 /adj incremental + /comp。",
    orchestration: [
      "从 prompt 解析核心假设路径、当前 yaml1 路径和前端变更列表。",
      "读取核心假设.md，定位 knobs 块、horizon、抬头和中期三段式。",
      "按 path 映射到 anchor/sub，改正文预测行和 knobs values；百分比做单位转换。",
      "做正文与 knobs 同源核对。",
      "先归档旧稿到 Agent/KAhistory，再写今日新稿。",
      "定点 patch 当前 yaml1 对应旋钮值，通过 fidelity check 后覆盖 Agent/forecast/。",
    ],
    stops: [
      "映射不到的 path 立即停，不猜。",
      "terminal.explicit_end / fade.to_year 属结构性改动，停并提示走 /adj incremental 或 /ka 重建。",
      "不读定调、活跃素材、年报或业务讨论；不把 yaml1 当判断源头。",
    ],
    handoff: "交给 forecast；汇报每条变更、同源核对、最新每股价值和 forecast 路径。",
  },
];

export const skills: SkillCard[] = [
  {
    key: "init",
    name: "/init",
    tag: "数据层",
    headline: "把一家公司从 TuShare 原始三表拉到可信 clean 数据，并生成 Agent 可读的核心指标速览。",
    when: "新公司第一次入库、年报/季报更新后刷新数据，或 DCF 前发现 data.db/defaults 过旧。",
    command: "/init 新乳业",
    reads: [
      "公司名、裸代码或完整 ticker，例如 002946 / 002946.SZ。",
      "TuShare 接口、公告下载目录、已有 approved override 和财务费用档案。",
    ],
    writes: [
      "Agent/data.db：raw_tushare、clean_annual、clean_quarterly、clean_adjustments、clean_warnings。",
      "Agent/core_metrics_overview.md/json/csv：clean 后的利润表核心指标速览。",
      "公告/年报 与 公告/季报 的 PDF/Markdown；Agent/financial_expense.yaml；Agent/OfficialBreakdowns/。",
    ],
    next: "clean 成功后，已有 Excel 先 /load；没有模型先 /brkd；具备 LOAD 或 BRKD 产物后再 /ka。",
    guardrails: ["raw_tushare 永不手改。", "年度 hard check 失败不能手工 plug；exit 3 不能假装成功。"],
    mentalModel: "这是数据地基，不负责写核心假设，也不替分析师判断未来。",
    notFor: "不用于修改核心假设、编译 yaml1 或解释估值结果。",
  },
  {
    key: "brkd",
    name: "/brkd",
    tag: "主线",
    headline: "先把业务和利润表大部分问题整理成 Agent业务讨论.md，给 /ka 接手。",
    when: "没有完整 Excel 模型、BRKD 素材包材料很多，或没有外部材料但需要用年报和历史财务事实先做业务讨论。",
    command: "/brkd 新乳业",
    reads: [
      "公司判断和最新观点.md，作为唯一判断锚点。",
      "Agent/core_metrics_overview.* 或 Agent/data.db: clean_annual，作为历史利润表事实。",
      "最新年报 Markdown，用于查分部、毛利/成本、费用、税收优惠、一次性项目。",
      "Skills素材包/BRKD业务理解器（研报和纪要放在这里）/markdown存储区；源材料必须先由 brkd_prepare 转换。",
    ],
    writes: ["公司根目录/Agent业务讨论.md：收入、毛利/成本、费用、below-OP、税率、净利率的讨论底稿和待拍板清单。"],
    next: "进入 /ka。无外部模型时，Agent业务讨论.md 是 /ka 的必需入口材料。",
    guardrails: ["BRKD 素材包为空不是失败；缺 /init 历史事实才停。", "给建议值但不拍最终旋钮；研报是线索，clean_annual 和年报是事实。"],
    mentalModel: "这是 /ka 的会前讨论底稿，不是最终核心假设。它先把能讨论的利润表框架摆上桌。",
    notFor: "不生成核心假设，不写 yaml1，不跑 DCF；中期三段式和正式 knobs 终稿留给 /ka。",
  },
  {
    key: "ka",
    name: "/ka",
    tag: "主线",
    headline: "把最高权重材料、LOAD 和 BRKD 裁决成一份人能读的正式核心假设.md。",
    when: "需要全量生成或重建正式核心假设；必须至少有已完成 LOAD 产物或 Agent业务讨论.md。已有正式稿的小改不要用 /ka。",
    command: "/ka 新乳业",
    reads: [
      "公司判断和最新观点.md 与 Skills素材包/最高权重材料-放Agent最应对齐的材料/markdown存储区。",
      "Agent业务讨论.md：由 /brkd 生成的业务层草稿。",
      "Agent/Load/*/*_核心假设.md：由 /load 生成的旧模型假设源文。",
      "Agent/core_metrics_overview.* 或 clean_annual，作为标准历史事实。",
      "最新年报 Markdown，只在裁决期按需查证，不通读升格。",
    ],
    writes: [
      "公司根目录/{公司}-YYYYMMDD-核心假设.md，或没聊透时写核心假设参考.md。",
    ],
    next: "进入 /comp，把人话判断翻译成 yaml1 并跑 DCF。",
    guardrails: ["无已完成 LOAD 且无 Agent业务讨论.md 时停止，提示先 /load 或 /brkd。", "不做旧稿 modify；小改走 /adj，年报滚动走 /annual-update。", "先押再问，关键旋钮拍板后再落盘。"],
    mentalModel: "这是分析师会议纪要，不是 YAML；按业务线组织，保全历史、识别旋钮、写清判断。",
    notFor: "不直接算 DCF，不生成 yaml1，不修 clean 数据，不做局部小改。",
  },
  {
    key: "load",
    name: "/load",
    tag: "主线",
    headline: "按旧 Excel 模型自己的时间轴保存 vintage 假设，并在沙箱里跑 DCF。",
    when: "已有旧模型，模型历史止于过去年份、预测从后来已经变成实际的年份开始；需要保存原模型而不是被最新年报覆盖。",
    command: "/load 影石创新",
    reads: [
      "Skills素材包/LOAD外部EXCEL模型理解器（一次最多一个）/ 下的唯一 Excel 模型。",
      "Agent/Load/{load_id}/allowed_materials/，只含模型和未越过边界的材料。",
      "最新版核心假设生成修改器 skill 与 模型装载器 skill。",
    ],
    writes: [
      "Agent/Load/{load_id}/{原Excel文件名}_核心假设.md。",
      "Agent/Load/{load_id}/yaml1_load_*.yaml 和 forecast/。",
    ],
    next: "load 结果只代表旧模型 vintage。要变成当前正式 forecast，需要另走 annual-update 或显式 promote。",
    guardrails: ["模型时间轴最高权威。", "用户确认 overview 前不能补完假设、编译或跑 DCF。", "禁止读取预测起点及之后的实际材料。"],
    mentalModel: "这是开了时间沙箱的 /ka：工作流像 /ka，但材料边界和输出都在 Agent/Load 里。",
    notFor: "不用于当前正式假设更新；当前模型应走 /ka 或 /annual-update。",
  },
  {
    key: "webload",
    name: "/webload",
    tag: "强烈推荐",
    headline: "强烈推荐：把 /load 沙箱和安全材料复制成网页端上传包。",
    when: "准备按旧模型跑 /load 前优先使用。真正需要网页端理解力的是 /load：即使用 GLM5.2 也建议开 MAX 模式；原生 Claude Code 配 Opus 4.8 high/xhigh 或直接上 Fable 效果最好，网页版完全可平替。",
    command: "py -m src.webload 影石创新 --overwrite",
    reads: [
      "Skills素材包/LOAD外部EXCEL模型理解器（一次最多一个）里的唯一 Excel 模型。",
      "model_load prepare 生成的 model_boundary、forbidden_materials、allowed_materials 和 {原Excel文件名}_核心假设.md 脚手架。",
      "D:/MKA/skills 里的最新版核心假设生成修改器 skill 和 模型装载器 skill。",
    ],
    writes: ["WEBCLAUDE/模型装载部分/，每次先清空再重建。", "同时创建或覆盖 Agent/Load/{load_id}/ 沙箱。"],
    next: "把打包目录上传到网页端，按 /load 逻辑先讲模型理解 overview；网页端产出的 {原Excel文件名}_核心假设.md 放回沙箱后，本地编译 yaml1_load 并跑 DCF。",
    guardrails: ["纯打包，不替用户确认模型理解。", "网页端只读 allowed_materials，不能打开 forbidden 材料正文。", "不要把 load 结果写进公司根目录或正式 forecast。"],
    mentalModel: "这是 /load 的推荐入口和搬运箱。它先把时间边界钉死，再把网页端需要的上下文按顺序备齐。",
    notFor: "不负责普通 /ka 网页端打包；旧 /webka 已废弃并移入 deprecatedlogs。",
  },
  {
    key: "adj",
    name: "/adj",
    tag: "增强",
    headline: "已有正式核心假设后的调整入口：quick 快拨已有 knobs，incremental 读增量材料再走 /comp。",
    when: "已经有正式 核心假设.md 和 yaml1；用户想小幅改数，或读 ADJ 增量材料后系统性更新假设。",
    command: "/adj 新乳业 把毛利率稍微提一提",
    reads: [
      "公司根目录最新正式 核心假设.md。",
      "Agent/ 最新 yaml1_*.yaml、defaults.yaml、data.db 和当前 forecast 摘要。",
      "incremental 模式会读 Skills素材包/ADJ增量信息（用来改模型的边际信息）/markdown存储区。",
    ],
    writes: [
      "quick：归档旧核心假设，写新核心假设，定点 patch 今日 yaml1，覆盖 Agent/forecast/。",
      "incremental：写新核心假设，再由 /comp 生成新 yaml1 和 forecast。",
    ],
    next: "quick 看最新 DCF；incremental 拍板后走 /comp。",
    guardrails: ["quick 只能拨已有 knobs，不能新增结构或改 terminal。", "非已有 knobs 的请求要列出可拨旋钮并建议走 incremental。", "incremental 不直接改 yaml1。"],
    mentalModel: "这是正式稿后的调参和边际信息处理层。它接走旧 KA modify 的工作，但把快改和系统性改动分开。",
    notFor: "不用于从零生成核心假设；新模型/新公司仍走 /load、/brkd、/ka。",
  },
  {
    key: "comp",
    name: "/comp",
    tag: "主线",
    headline: "把核心假设.md 忠实翻译成机器可读 yaml1，并立即跑 DCF。",
    when: "核心假设已经完成或修改后，需要生成新的 DCF 结果。",
    command: "/comp 新乳业",
    reads: [
      "公司根目录最新 *核心假设*.md。",
      "Agent/defaults.yaml：目标命名空间，不是预测意见。",
      "docs/数据格式参考.md、docs/yaml1算法模板契约.md、docs/knobs块契约.md：字段字典、算法边界和 knobs 真源。",
    ],
    writes: [
      "Agent/yaml1_公司_YYYYMMDD.yaml：人的判断覆盖层。",
      "Agent/.modelking/forecast_params.yaml 与 yaml1_clean_report.json。",
      "Agent/forecast/：forecast_is/bs/cf、full_is/bs/cf、dcf_summary、dcf_detail。",
    ],
    next: "看工作台 DCF 和完整三表；不满意就回 /adj 或 /ka 重建改判断，再 /comp。",
    guardrails: ["compiler 是翻译器，形变照翻、歧义举旗，不替人重算判断。", "yaml1 落盘即主成功；DCF 失败要明示但不回滚 yaml1。"],
    mentalModel: "这是人话到机器话的接缝。它不做投资判断，只保证判断能被引擎读懂。",
    notFor: "不用于从零读研报，不用于修数据配平，不用于绕过 yaml1_cleaner。",
  },
  {
    key: "annual-update",
    name: "/annual-update",
    tag: "滚续",
    headline: "公司出了新年报后，把旧核心假设从历史末年滚到最新年。",
    when: "已有旧核心假设.md，且 clean 数据更新到了新年报，需要保留旧稿逻辑但补入新真实年份。",
    command: "/annual-update 新乳业",
    reads: [
      "旧核心假设.md：提取历史末年 H、显式期、旋钮和所有历史行总账。",
      "公司判断和最新观点.md、Agent/data.db、Agent/financial_expense.yaml、最新年报 Markdown。",
      "annual_update_fetcher 输出的标准事实线和偏离诊断。",
    ],
    writes: [
      "新日期核心假设.md：旧稿只读，另存新稿。",
      "Agent/Logs/annual_update_deviation_*.md：旧预测 vs 新真实偏离诊断。",
      "收口后通常继续生成新 yaml1 和新 Agent/forecast/。",
    ],
    next: "第 4 步起和用户商议估算/重定；拍板后 /comp 收口。",
    guardrails: ["init exit 3 未闭合就停，不在脏数据上滚。", "拿不到的历史事实只能标估算待校准或待补旗，不能静默捏造。"],
    mentalModel: "这是年度滚续，不是从零 /ka；它尊重旧稿、补真实、重拨未来。",
    notFor: "没有旧核心假设时不要用它；那应该先 /ka。",
  },
  {
    key: "da",
    name: "/da",
    tag: "增强",
    headline: "重资产公司专用：把固定资产、在建工程和 PP&E 折旧变成可滚动排程。",
    when: "公司固定资产/在建工程/产能扩张决定估值，默认 capex_pct + depr_rate 太粗。",
    command: "/da 新乳业",
    reads: [
      "公司判断和最新观点.md，必须最先读。",
      "公告/年报/*.md 里的固定资产、在建工程、折旧政策等附注。",
      "可选 Agent业务讨论.md，作为扩张性 capex 的业务线索。",
    ],
    writes: [
      "Agent/recon/da_facts_latest.json：事实层，只抽年报事实。",
      "Agent/da_schedule.yaml：假设层，用户拍板后落盘。",
    ],
    next: "重跑 py -m src.forecast --ticker 公司；enabled: true 时 forecast 注入 da_series。",
    guardrails: ["轻资产或稳态公司不要用，别把简单模型复杂化。", "事实和假设分离；未经拍板不能写 da_schedule.yaml。"],
    mentalModel: "这是 DCF 的重资产外挂。它不改变 /ka 的常规毛利率语义，只在 forecast 阶段注入 PP&E 折旧和 capex。",
    notFor: "不处理无形资产、使用权资产、长摊三类摊销；这些仍由 yaml1/defaults 管。",
  },
  {
    key: "frontend-edit",
    name: "/frontend-edit",
    tag: "增强",
    headline: "把前端试算的旋钮变更定点回写核心假设.md + patch yaml1，再跑 forecast。",
    when: "工作台前端已完成 assumption-preview 试算并拍板，只想改几个旋钮值刷新 DCF；普通文字请求优先走 /adj quick。",
    command: "/frontend-edit 进入前端编辑模式 ...",
    reads: [
      "前端 prompt：核心假设路径、当前 yaml1 路径、变更列表（label/path/year/old->new）。",
      "公司根目录最新 核心假设.md：定位 knobs 块、horizon、抬头、中期三段式。",
      "Agent/ 下最新 yaml1_*.yaml：定位对应旋钮 values 数组。",
    ],
    writes: [
      "归档旧 核心假设.md 到 Agent/KAhistory/，再写今日新稿到公司根目录。",
      "定点 patch yaml1 对应旋钮值（保留格式/注释，不跑 compiler）。",
      "覆盖 Agent/forecast/：py -m src.forecast --yaml1 <新 yaml1>。",
    ],
    next: "汇报每条变更、md 正文&knobs&yaml1 三处同源核对、最新每股价值和 forecast 路径。",
    guardrails: [
      "旋钮值小改不跑 compiler；结构性变更（新增/删旋钮、改 terminal 长度）走 /adj incremental 或 /ka 重建 + /comp。",
      "映射不到的 path 立即停，不猜；md 正文与 knobs、yaml1 三处不同源立即停。",
      "不读定调/活跃素材/年报/业务讨论；不改历史段；派生行不动。",
    ],
    mentalModel: "这是一把手术刀，不是研究员。前端已替用户拍板，它只做安全定点 patch 和同源核对。",
    notFor: "不用于重新做业务判断、不用于结构性改假设、不绕过 核心假设.md 直接改 yaml1 当源头。",
  },
];

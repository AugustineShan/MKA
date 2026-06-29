import { useEffect, useMemo, useState } from "react";
import {
  codexGuideFlow,
  codexGuidePrompts,
  codexGuideRules,
  entryRoutes,
  pipelineAux,
  pipelineStages,
  quickstartRoutes,
  skillArtifactContracts,
  skillSystemInvariants,
  skillPrincipleFlow,
  skillPrincipleStack,
  skillPrinciples,
  skills,
  workspaceFolderTree,
  workspacePlacementTips,
} from "./tutorialContent";
import type { AppSettings, SettingsField, SettingsValidation } from "./types";

type TutorialProps = {
  onClose: () => void;
  onSaved?: () => void;
};

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

function sectionTitle(section: string): string {
  if (section === "output") return "输出配置";
  if (section === "workspace") return "工作台";
  if (section === "data") return "数据源";
  if (section === "llm") return "大模型";
  if (section === "excel") return "Excel交付";
  return section;
}

function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return <span className={`config-status-dot ${ok ? "ok" : "warn"}`}>{label}</span>;
}

function validationReady(validation?: SettingsValidation): boolean {
  return Boolean(validation?.exists && validation?.is_dir && validation?.writable);
}

export function Tutorial({ onClose, onSaved }: TutorialProps) {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [companiesDir, setCompaniesDir] = useState("");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [createDir, setCreateDir] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [activeTab, setActiveTab] = useState<"config" | "guide" | "workspace" | "codex" | "principles">("config");
  const [copiedPrompt, setCopiedPrompt] = useState<string | null>(null);

  const loadSettings = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchJson<AppSettings>("/api/settings");
      setSettings(result);
      setCompaniesDir(result.companies_dir);
      setDrafts(Object.fromEntries(result.fields.map((field) => [field.key, field.secret ? "" : field.value ?? ""])));
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadSettings();
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const fieldsBySection = useMemo(() => {
    const groups = new Map<string, SettingsField[]>();
    for (const field of settings?.fields ?? []) {
      if (field.key === "MKA_COMPANIES_DIR") continue;
      if (field.section === "output") continue;
      groups.set(field.section, [...(groups.get(field.section) ?? []), field]);
    }
    return [...groups.entries()];
  }, [settings]);

  const outputFields = useMemo(() => (settings?.fields ?? []).filter((field) => field.section === "output"), [settings]);

  const skillCardsByKey = useMemo(() => new Map(skills.map((skill) => [skill.key, skill])), []);

  const dataConfigured = settings?.fields.some((field) => field.key === "TUSHARE_TOKEN" && field.configured) ?? false;
  const llmConfigured = settings?.fields.some((field) => ["GLM_API_KEY", "KIMI_API_KEY", "LLM_API_KEY"].includes(field.key) && field.configured) ?? false;
  const ratingReport = settings?.rating_report;

  const saveSettings = async (forceCreate = false) => {
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const env: Record<string, string> = {};
      for (const field of settings?.fields ?? []) {
        if (field.key === "MKA_COMPANIES_DIR") continue;
        const draft = drafts[field.key] ?? "";
        if (field.secret) {
          if (draft.trim()) env[field.key] = draft.trim();
        } else {
          env[field.key] = draft.trim();
        }
      }
      const result = await fetchJson<AppSettings>("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          companies_dir: companiesDir.trim(),
          env,
          create_companies_dir: forceCreate || createDir,
        }),
      });
      setSettings(result);
      setCompaniesDir(result.companies_dir);
      setDrafts(Object.fromEntries(result.fields.map((field) => [field.key, field.secret ? "" : field.value ?? ""])));
      setSaved(true);
      onSaved?.();
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  };

  const validatePath = async () => {
    setValidating(true);
    setError(null);
    try {
      const validation = await fetchJson<SettingsValidation>("/api/settings/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ companies_dir: companiesDir.trim() }),
      });
      setSettings((current) => (current ? { ...current, validation, companies_dir: companiesDir.trim() } : current));
    } catch (err) {
      setError(String(err));
    } finally {
      setValidating(false);
    }
  };

  const copyPrompt = async (label: string, prompt: string) => {
    const fallbackCopy = () => {
      const textarea = document.createElement("textarea");
      textarea.value = prompt;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
    };

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(prompt);
      } else {
        fallbackCopy();
      }
    } catch {
      fallbackCopy();
    }
    setCopiedPrompt(label);
    window.setTimeout(() => setCopiedPrompt((current) => (current === label ? null : current)), 1400);
  };

  const starterPrompt = codexGuidePrompts[0];
  const taskPrompts = codexGuidePrompts.slice(1);

  return (
    <div className="tutorial-overlay" role="dialog" aria-modal="true" aria-label="配置和教程">
      <div className="tutorial-page config-page">
        <header className="tutorial-header">
          <div>
            <div className="eyebrow">Workbench</div>
            <h1>配置和教程</h1>
          </div>
          <button className="tutorial-close" onClick={onClose} type="button" aria-label="关闭">×</button>
        </header>

        {loading ? <div className="activity">Loading settings</div> : null}
        {error ? <div className="error-banner">{error}</div> : null}

        <nav className="tutorial-subtabs" aria-label="配置和教程">
          <button
            aria-selected={activeTab === "config"}
            className={activeTab === "config" ? "active" : ""}
            onClick={() => setActiveTab("config")}
            role="tab"
            type="button"
          >
            配置
          </button>
          <button
            aria-selected={activeTab === "guide"}
            className={activeTab === "guide" ? "active" : ""}
            onClick={() => setActiveTab("guide")}
            role="tab"
            type="button"
          >
            教程
          </button>
          <button
            aria-selected={activeTab === "workspace"}
            className={activeTab === "workspace" ? "active" : ""}
            onClick={() => setActiveTab("workspace")}
            role="tab"
            type="button"
          >
            工作台指南
          </button>
          <button
            aria-selected={activeTab === "codex"}
            className={activeTab === "codex" ? "active" : ""}
            onClick={() => setActiveTab("codex")}
            role="tab"
            type="button"
          >
            给 Codex 的使用指南
          </button>
          <button
            aria-selected={activeTab === "principles"}
            className={activeTab === "principles" ? "active" : ""}
            onClick={() => setActiveTab("principles")}
            role="tab"
            type="button"
          >
            技能原理
          </button>
        </nav>

        {activeTab === "config" ? (
          <>
            {settings ? (
              <section className="config-status-bar">
                <StatusDot ok={validationReady(settings.validation)} label={validationReady(settings.validation) ? "路径可用" : "路径待检查"} />
                <StatusDot ok={dataConfigured} label={dataConfigured ? "TuShare 已配置" : "TuShare 未配置"} />
                <StatusDot ok={llmConfigured} label={llmConfigured ? "大模型已配置" : "大模型未配置"} />
                <span className="config-status-count">{settings.validation.company_count} 家公司</span>
              </section>
            ) : null}

            {settings ? (
              <section className="tutorial-section config-section">
                {outputFields.length ? (
                  <div className="config-output-card">
                    <div className="config-output-copy">
                      <span>输出配置</span>
                      <h2>交付文件里的署名</h2>
                      <p>这里会写进导出的模型 Excel。未填写时导出为空，不再使用任何模板里的默认个人信息。</p>
                    </div>
                    <div className="config-output-fields">
                      {outputFields.map((field) => (
                        <label className="config-field" key={field.key}>
                          <span>{field.label}</span>
                          <input
                            autoComplete="off"
                            onChange={(event) => {
                              setSaved(false);
                              setDrafts((current) => ({ ...current, [field.key]: event.currentTarget.value }));
                            }}
                            placeholder={field.placeholder}
                            type="text"
                            value={drafts[field.key] ?? ""}
                          />
                        </label>
                      ))}
                    </div>
                  </div>
                ) : null}
                <div className="config-section-head">
                  <div>
                    <h2>基础配置</h2>
                    <p>这些配置写入本地 .env；密钥不会在前端回显。</p>
                  </div>
                  <code>{settings.env_path}</code>
                </div>

                <div className="config-field wide">
                  <label htmlFor="companies-dir">工作台路径</label>
                  <div className="config-input-row">
                    <input
                      id="companies-dir"
                      onChange={(event) => {
                        setSaved(false);
                        setCompaniesDir(event.currentTarget.value);
                      }}
                      value={companiesDir}
                    />
                    <button className="secondary-button" disabled={validating} onClick={validatePath} type="button">
                      {validating ? "检查中" : "检查"}
                    </button>
                  </div>
                  <div className="config-help">
                    默认是 {settings.default_companies_dir}。当前路径
                    {settings.validation.exists ? " 已存在" : " 不存在"}，
                    {settings.validation.is_dir ? " 是文件夹" : " 不是可用文件夹"}，
                    {settings.validation.writable ? " 可写" : " 写入状态待确认"}。
                  </div>
                  {!settings.validation.exists ? (
                    <label className="config-checkbox">
                      <input checked={createDir} onChange={(event) => setCreateDir(event.currentTarget.checked)} type="checkbox" />
                      保存时创建这个文件夹
                    </label>
                  ) : null}
                </div>

                <div className="config-grid">
                  {fieldsBySection.map(([section, fields]) => (
                    <div className="config-card" key={section}>
                      <h3>{sectionTitle(section)}</h3>
                      {fields.map((field) => (
                        <label className="config-field" key={field.key}>
                          <span>
                            {field.label}
                            {field.secret && field.masked ? <small>{field.masked}</small> : null}
                          </span>
                          <input
                            autoComplete="off"
                            onChange={(event) => {
                              setSaved(false);
                              setDrafts((current) => ({ ...current, [field.key]: event.currentTarget.value }));
                            }}
                            placeholder={field.secret ? "留空不修改" : field.placeholder}
                            type={field.secret ? "password" : "text"}
                            value={drafts[field.key] ?? ""}
                          />
                        </label>
                      ))}
                    </div>
                  ))}
                </div>

                {ratingReport ? (
                  <div className="config-note-strip">
                    评级报告模板默认展示 {ratingReport.data_start_year}-{ratingReport.data_end_year} 年取数区间，
                    {ratingReport.forecast_start_year}-{ratingReport.forecast_end_year} 年预测区间；预测区间会自动加 E。
                  </div>
                ) : null}

                <div className="config-actions">
                  <button className="primary-button" disabled={saving} onClick={() => saveSettings(false)} type="button">
                    {saving ? "保存中" : "保存配置"}
                  </button>
                  {!settings.validation.exists ? (
                    <button className="secondary-button" disabled={saving} onClick={() => saveSettings(true)} type="button">
                      创建并保存
                    </button>
                  ) : null}
                  {saved ? <span className="config-saved">已保存，公司列表已刷新。</span> : null}
                </div>
              </section>
            ) : null}
          </>
        ) : activeTab === "guide" ? (
          <div className="tutorial-guide">
            <section className="tutorial-section tutorial-user-hero">
              <div className="tutorial-user-hero-copy">
                <span>普通用户教程</span>
                <h2>从材料到 DCF，按手头资料选择路线。</h2>
                <p>
                  先判断你手上是 Excel 模型、研报纪要，还是只想更新已有模型。系统会把取数、阅读、假设确认和估值输出拆成几步；
                  你只需要准备材料、确认判断、查看结果。
                </p>
              </div>
              <div className="tutorial-promise-grid">
                <div>
                  <strong>1</strong>
                  <span>准备历史财务底稿</span>
                </div>
                <div>
                  <strong>2</strong>
                  <span>整理模型和材料线索</span>
                </div>
                <div>
                  <strong>3</strong>
                  <span>确认假设，输出估值</span>
                </div>
              </div>
            </section>

            <section className="tutorial-section">
              <div className="tutorial-section-intro">
                <h2>我现在该从哪开始</h2>
                <p>历史底稿默认会先准备。这里按你手上的材料选路线，再按卡片下方命令往下跑。</p>
              </div>
              <div className="entry-routes">
                {entryRoutes.map((r) => (
                  <div className="entry-route" key={r.n}>
                    <span className="entry-route-num">{r.n}</span>
                    <div className="entry-route-body">
                      <strong className="entry-route-title">{r.title}</strong>
                      <p className="entry-route-desc">{r.desc}</p>
                      <code className="entry-route-cmd">{r.route}</code>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="tutorial-section">
              <div className="analyst-map-head">
                <div>
                  <h2>每个功能在替你完成哪一步投研工作</h2>
                  <p>这张图用分析师工作语言描述日常流程；底层文件和工程链路放在“技能原理”。</p>
                </div>
                <button className="text-link-button" onClick={() => setActiveTab("principles")} type="button">
                  查看技能原理
                </button>
              </div>
              <div className="analyst-map" aria-label="分析师工作流全景">
                <div className="analyst-map-grid">
                  {pipelineStages.map((stage) => (
                    <article className={`analyst-node analyst-node-${stage.area} analyst-node-${stage.tone}`} key={stage.key}>
                      <header>
                        <span className="analyst-job">{stage.analystJob}</span>
                        <code>{stage.cmd}</code>
                        {stage.badge ? <em>{stage.badge}</em> : null}
                      </header>
                      <h3>{stage.title}</h3>
                      <p>{stage.feature}</p>
                      <footer>
                        <span>交付</span>
                        <strong>{stage.output}</strong>
                      </footer>
                    </article>
                  ))}
                </div>
                <div className="analyst-system-line">
                  <span>记住这条就够</span>
                  <strong>历史底稿</strong>
                  <b>→</b>
                  <strong>材料阅读</strong>
                  <b>→</b>
                  <strong>假设确认</strong>
                  <b>→</b>
                  <strong>估值输出</strong>
                </div>
                <div className="tutorial-plain-note">
                  <strong>普通用户不用处理底层文件。</strong>
                  <span>你负责材料、判断和结果复核；文件转换和模型运行会在后台完成。</span>
                </div>
                {pipelineAux.map((group) => (
                  <div className="analyst-support" key={group.title}>
                    <span className="analyst-support-title">{group.title}</span>
                    <div className="analyst-support-grid">
                      {group.items.map((item) => (
                        <article className="analyst-support-card" key={item.cmd}>
                          <header>
                            <code>{item.cmd}</code>
                            {item.recommended ? <em>推荐</em> : null}
                          </header>
                          <strong>{item.analystJob}</strong>
                          <p>{item.note}</p>
                          <span>{item.output}</span>
                        </article>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="tutorial-section">
              <div className="tutorial-section-intro">
                <h2>照着做</h2>
                <p>三条最常见路线。第一次用的时候，照顺序走就行。</p>
              </div>
              <div className="quickstart-routes">
                {quickstartRoutes.map((route) => (
                  <div className="quickstart-route" key={route.key}>
                    <header className="quickstart-route-head">
                      <strong>{route.title}</strong>
                      <span className="quickstart-route-when">{route.when}</span>
                    </header>
                    <ol className="quickstart">
                      {route.steps.map((item, idx) => (
                        <li key={route.key + "-" + idx}>
                          <span className="quickstart-step">{idx + 1}</span>
                          <code>{item.cmd}</code>
                          <span className="quickstart-desc">{item.desc}</span>
                        </li>
                      ))}
                    </ol>
                  </div>
                ))}
              </div>
            </section>
          </div>
        ) : activeTab === "workspace" ? (
          <div className="tutorial-guide workspace-guide">
            <section className="tutorial-section workspace-folder-map">
              <header className="workspace-map-head">
                <div>
                  <span>工作台指南</span>
                  <h2>一家公司文件夹，就看这四块。</h2>
                </div>
                <div className="workspace-map-root">
                  <span className="folder-mark" />
                  <code>companies/新乳业_002946/</code>
                </div>
              </header>

              <div className="workspace-map-legend">
                <span className="legend-archive">普通资料区：给人放，Agent 默认不读</span>
                <span className="legend-input">Skills素材包：给 Agent 读</span>
                <span className="legend-agent">Agent：结果和程序产物</span>
              </div>

              <div className="workspace-tree-grid">
                {workspaceFolderTree.map((group) => (
                  <article className={`workspace-tree-card ${group.tone}`} key={group.title}>
                    <header>
                      <span className="folder-mark" />
                      <div>
                        <strong>{group.title}</strong>
                        <em>{group.tag}</em>
                      </div>
                    </header>
                    <ul>
                      {group.rows.map((row) => (
                        <li className={row.hot ? "hot" : ""} key={row.name}>
                          <code>{row.name}</code>
                          <span>{row.purpose}</span>
                          <b>{row.action}</b>
                        </li>
                      ))}
                    </ul>
                  </article>
                ))}
              </div>

              <div className="workspace-map-note">
                <strong>记住：</strong>
                <span><code>内部报告</code>、<code>研报</code>、<code>纪要</code>、<code>收集</code> 是普通资料仓；<code>重要文件</code> 是外部最高权重材料入口，建议只放 1-3 份最新、最可靠的纪要。</span>
              </div>
            </section>

            <section className="tutorial-section workspace-placement">
              <h2>我手上有材料，放哪儿</h2>
              <div className="workspace-placement-table">
                {workspacePlacementTips.map((item) => (
                  <div className="workspace-placement-row" key={item.material}>
                    <strong>{item.material}</strong>
                    <code>{item.put}</code>
                    <span>{item.run}</span>
                  </div>
                ))}
              </div>
            </section>
          </div>
        ) : activeTab === "codex" ? (
          <div className="tutorial-guide codex-guide">
            <section className="tutorial-section codex-copy-hero">
              <div className="codex-copy-hero-copy">
                <span>给 Codex 的使用指南</span>
                <h2>现在可以直接用 MKA 路由下任务。</h2>
                <p>
                  新线程先贴一次工作协议；之后直接说 /init、/ka、/comp 这类任务。Codex 会先尊重人工筛选入口；已入场材料有价值但未入模时，进收纳区/stash。
                </p>
              </div>
              {starterPrompt ? (
                <article className="codex-starter-card">
                  <header>
                    <div>
                      <strong>{starterPrompt.label}</strong>
                      <span>{starterPrompt.when}</span>
                    </div>
                    <button
                      className="codex-copy-button"
                      onClick={() => copyPrompt(starterPrompt.label, starterPrompt.prompt)}
                      type="button"
                    >
                      {copiedPrompt === starterPrompt.label ? "已复制" : "复制"}
                    </button>
                  </header>
                  <code>{starterPrompt.prompt}</code>
                </article>
              ) : null}
            </section>

            <section className="tutorial-section">
              <h2>三步用法</h2>
              <div className="codex-guide-grid compact">
                {codexGuideFlow.map((item) => (
                  <article className="codex-guide-card" key={item.title}>
                    <h3>{item.title}</h3>
                    <p>{item.body}</p>
                  </article>
                ))}
              </div>
            </section>

            <section className="tutorial-section">
              <h2>按任务复制</h2>
              <div className="codex-prompt-list">
                {taskPrompts.map((item) => (
                  <article className="codex-prompt-card" key={item.label}>
                    <header>
                      <div>
                        <span>{item.label}</span>
                        <strong>{item.command}</strong>
                        <p>{item.when}</p>
                      </div>
                      <button
                        className="codex-copy-button"
                        onClick={() => copyPrompt(item.label, item.prompt)}
                        type="button"
                      >
                        {copiedPrompt === item.label ? "已复制" : "复制"}
                      </button>
                    </header>
                    <code>{item.prompt}</code>
                  </article>
                ))}
              </div>
            </section>

            <section className="tutorial-section">
              <h2>做完后这样检查</h2>
              <div className="codex-guide-grid">
                {codexGuideRules.map((item) => (
                  <article className="codex-guide-card" key={item.title}>
                    <h3>{item.title}</h3>
                    <p>{item.body}</p>
                  </article>
                ))}
              </div>
            </section>

            <section className="tutorial-section codex-old-note">
              <h2>只记住这一句</h2>
              <div className="codex-guide-hero">
                <div>
                  <strong>斜杠词是 MKA 的任务路由，Codex 负责从本地协议恢复执行状态。</strong>
                  <p>
                    所以你可以直接下令；它每次执行前都要读取 <code>D:\MKA\Codex.md</code>、对应 <code>.claude/skills</code> 和最新版动态 runbook。规则边界不清楚时，先看 <code>D:\MKA\docs\MKA规则导航图.md</code>。
                  </p>
                </div>
                <code>D:\MKA\Codex.md</code>
              </div>
            </section>
          </div>
        ) : (
          <div className="tutorial-guide skill-principles">
            <section className="tutorial-section">
              <h2>技能原理：运行时契约</h2>
              <div className="principle-hero">
                <div>
                  <strong>这里不是使用教程，是 MKA 的 source-of-truth 架构图。</strong>
                  <p>
                    每个 skill 都必须回答三件事：读什么、写什么、在哪些门禁前必须停。
                    启动器负责定位和守门，动态 skill 负责复杂判断的 runbook，Python 负责确定性校验和计算，核心假设.md 负责承载人的判断。
                  </p>
                  <div className="principle-hero-meta">
                    <span>source: 核心假设.md</span>
                    <span>compiler: yaml1 -&gt; forecast_params</span>
                    <span>runtime: calc.py -&gt; Agent/forecast</span>
                  </div>
                </div>
                <code>{".claude/skills -> D:\\MKA\\skills -> src/* -> Agent/forecast"}</code>
              </div>
            </section>

            <section className="tutorial-section">
              <h2>系统不变量</h2>
              <div className="principle-invariant-grid">
                {skillSystemInvariants.map((item) => (
                  <article className="principle-invariant-card" key={item.code}>
                    <code>{item.code}</code>
                    <h3>{item.title}</h3>
                    <p>{item.body}</p>
                  </article>
                ))}
              </div>
            </section>

            <section className="tutorial-section">
              <h2>产物契约</h2>
              <div className="artifact-contract-table">
                <div className="artifact-contract-row artifact-contract-head">
                  <span>Artifact</span>
                  <span>Owner</span>
                  <span>Write Boundary</span>
                  <span>Contract</span>
                </div>
                {skillArtifactContracts.map((item) => (
                  <div className="artifact-contract-row" key={item.artifact}>
                    <code>{item.artifact}</code>
                    <strong>{item.owner}</strong>
                    <span>{item.writeBoundary}</span>
                    <p>{item.contract}</p>
                  </div>
                ))}
              </div>
            </section>

            <section className="tutorial-section">
              <h2>Runtime 四层</h2>
              <div className="principle-stack">
                {skillPrincipleStack.map((item) => (
                  <article className="principle-stack-card" key={item.title}>
                    <h3>{item.title}</h3>
                    <p>{item.body}</p>
                  </article>
                ))}
              </div>
            </section>

            <section className="tutorial-section">
              <h2>Canonical Artifact Chain</h2>
              <ol className="principle-flow">
                {skillPrincipleFlow.map((item, index) => (
                  <li key={item}>
                    <span>{index + 1}</span>
                    <p>{item}</p>
                  </li>
                ))}
              </ol>
            </section>

            <section className="tutorial-section">
              <h2>Skill Runbook Contracts</h2>
              <div className="principle-skill-list">
                {skillPrinciples.map((skill) => {
                  const skillCard = skillCardsByKey.get(skill.key);
                  return (
                    <article className="principle-skill-card" key={skill.key}>
                      <header>
                        <div>
                          <code>{skill.name}</code>
                          <h3>{skill.role}</h3>
                        </div>
                        <span>{skill.key}</span>
                      </header>
                      <div className="principle-skill-body">
                        <div className="principle-skill-summary">
                          <h4>核心原理</h4>
                          <p>{skill.principle}</p>
                          <h4>为什么存在</h4>
                          <p>{skill.why}</p>
                          <h4>交给谁</h4>
                          <p>{skill.handoff}</p>
                        </div>
                        <div className="principle-skill-steps">
                          {skillCard ? (
                            <div className="principle-skill-io">
                              <div>
                                <h4>读取</h4>
                                <ul>
                                  {skillCard.reads.map((item) => (
                                    <li key={item}>{item}</li>
                                  ))}
                                </ul>
                              </div>
                              <div>
                                <h4>写入</h4>
                                <ul>
                                  {skillCard.writes.map((item) => (
                                    <li key={item}>{item}</li>
                                  ))}
                                </ul>
                              </div>
                            </div>
                          ) : null}
                          <h4>编排</h4>
                          <ol>
                            {skill.orchestration.map((item) => (
                              <li key={item}>{item}</li>
                            ))}
                          </ol>
                          <h4>硬停</h4>
                          <ul>
                            {skill.stops.map((item) => (
                              <li key={item}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

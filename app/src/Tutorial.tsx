import { useEffect, useMemo, useState } from "react";
import {
  codexGuideFlow,
  codexGuidePrompts,
  codexGuideRules,
  entryRoutes,
  pipelineAux,
  pipelineStages,
  quickstartRoutes,
  skillPrincipleFlow,
  skillPrincipleStack,
  skillPrinciples,
  skills,
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
  const [activeTab, setActiveTab] = useState<"config" | "guide" | "codex" | "principles">("config");

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
      groups.set(field.section, [...(groups.get(field.section) ?? []), field]);
    }
    return [...groups.entries()];
  }, [settings]);

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
            <section className="tutorial-section">
              <h2>从哪开始</h2>
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
                  <h2>分析师工作流全景</h2>
                  <p>把传统投研动作拆成事实底座、材料理解、假设拍板和机器估值四块；每一步都有明确的智能增强和落盘产物。</p>
                </div>
                <code>{"raw -> clean -> defaults -> 核心假设 -> yaml1 -> forecast_params -> calc"}</code>
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
                  <span>机器底层链路</span>
                  <strong>TuShare 原始数据</strong>
                  <b>→</b>
                  <strong>raw_tushare 镜像</strong>
                  <b>→</b>
                  <strong>clean 宽表</strong>
                  <b>→</b>
                  <strong>defaults.yaml</strong>
                  <b>→</b>
                  <strong>yaml1 覆盖</strong>
                  <b>→</b>
                  <strong>Agent/forecast</strong>
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
              <h2>新手路线</h2>
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

            <section className="tutorial-section">
              <h2>Skills 速查</h2>
              <div className="skill-grid skill-grid-expanded">
                {skills.map((skill) => (
                  <article className={`skill-card skill-tag-${skill.tag}`} key={skill.key}>
                    <header className="skill-card-head">
                      <div>
                        <code className="skill-name">{skill.name}</code>
                        <p className="skill-headline">{skill.headline}</p>
                      </div>
                      <span className="skill-tag">{skill.tag}</span>
                    </header>
                    <dl className="skill-fields skill-fields-expanded">
                      <dt>何时用</dt><dd>{skill.when}</dd>
                      <dt>命令</dt><dd><code>{skill.command}</code></dd>
                      <dt>会读取</dt>
                      <dd>
                        <ul className="skill-list">
                          {skill.reads.map((item) => <li key={item}>{item}</li>)}
                        </ul>
                      </dd>
                      <dt>会产出</dt>
                      <dd>
                        <ul className="skill-list">
                          {skill.writes.map((item) => <li key={item}>{item}</li>)}
                        </ul>
                      </dd>
                      <dt>下一步</dt><dd>{skill.next}</dd>
                      <dt>边界</dt>
                      <dd>
                        <ul className="skill-list">
                          {skill.guardrails.map((item) => <li key={item}>{item}</li>)}
                        </ul>
                      </dd>
                      <dt>理解</dt><dd>{skill.mentalModel}</dd>
                      {skill.notFor ? <dt>不是</dt> : null}
                      {skill.notFor ? <dd>{skill.notFor}</dd> : null}
                    </dl>
                  </article>
                ))}
              </div>
            </section>
          </div>
        ) : activeTab === "codex" ? (
          <div className="tutorial-guide codex-guide">
            <section className="tutorial-section">
              <h2>给 Codex 的使用指南</h2>
              <div className="codex-guide-hero">
                <div>
                  <strong>先读 Codex.md，再读对应 skill。</strong>
                  <p>
                    Codex 可以执行这个项目的技能，但它需要把这些技能当成本地操作手册加载。
                    新开线程时先把项目地图交给它，具体任务再让它读对应的
                    <code>.claude/skills</code> 入口和 <code>D:\MKA\skills</code> 里的动态细则。
                  </p>
                </div>
                <code>D:\MKA\Codex.md</code>
              </div>
            </section>

            <section className="tutorial-section">
              <h2>推荐加载顺序</h2>
              <div className="codex-guide-grid">
                {codexGuideFlow.map((item) => (
                  <article className="codex-guide-card" key={item.title}>
                    <h3>{item.title}</h3>
                    <p>{item.body}</p>
                  </article>
                ))}
              </div>
            </section>

            <section className="tutorial-section">
              <h2>可直接复制的提示词</h2>
              <div className="codex-prompt-list">
                {codexGuidePrompts.map((item) => (
                  <article className="codex-prompt-card" key={item.label}>
                    <span>{item.label}</span>
                    <code>{item.prompt}</code>
                  </article>
                ))}
              </div>
            </section>

            <section className="tutorial-section">
              <h2>边界提醒</h2>
              <div className="codex-guide-grid">
                {codexGuideRules.map((item) => (
                  <article className="codex-guide-card" key={item.title}>
                    <h3>{item.title}</h3>
                    <p>{item.body}</p>
                  </article>
                ))}
              </div>
            </section>
          </div>
        ) : (
          <div className="tutorial-guide skill-principles">
            <section className="tutorial-section">
              <h2>技能原理</h2>
              <div className="principle-hero">
                <div>
                  <strong>这些 skill 不是一组命令，是一套分层编排系统。</strong>
                  <p>
                    启动器负责定位和守门，动态 skill 负责复杂判断的 runbook，Python 负责确定性校验和计算，
                    人类拍板永远回到 核心假设.md。理解这四层，才知道什么时候该自动跑，什么时候必须停下来问。
                  </p>
                </div>
                <code>{".claude/skills -> D:\\MKA\\skills -> src/* -> Agent/forecast"}</code>
              </div>
            </section>

            <section className="tutorial-section">
              <h2>四层机制</h2>
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
              <h2>主线编排</h2>
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
              <h2>每个技能怎么工作</h2>
              <div className="principle-skill-list">
                {skillPrinciples.map((skill) => (
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
                ))}
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import { entryRoutes, pipelineMain, pipelineSide, quickstart, skills } from "./tutorialContent";
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

        {settings ? (
          <section className="config-status-bar">
            <StatusDot ok={validationReady(settings.validation)} label={validationReady(settings.validation) ? "路径可用" : "路径待检查"} />
            <StatusDot ok={dataConfigured} label={dataConfigured ? "TuShare 已配置" : "TuShare 未配置"} />
            <StatusDot ok={llmConfigured} label={llmConfigured ? "大模型已配置" : "大模型未配置"} />
            <span className="config-status-count">{settings.validation.company_count} 家公司</span>
          </section>
        ) : null}

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
          <h2>管线全景</h2>
          <div className="pipeline-main">
            {pipelineMain.map((node, index) => (
              <span className="pipeline-node-wrap" key={node}>
                <span className={index % 2 === 1 ? "pipeline-node pipeline-cmd" : "pipeline-node"}>{node}</span>
                {index < pipelineMain.length - 1 ? <span className="pipeline-arrow">→</span> : null}
              </span>
            ))}
          </div>
          <div className="pipeline-side">
            {pipelineSide.map((item) => (
              <div className="pipeline-side-item" key={item.label}>
                <code>{item.label}</code>
                <span>{item.desc}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="tutorial-section">
          <h2>新手 4 步</h2>
          <ol className="quickstart">
            {quickstart.map((item) => (
              <li key={item.step}>
                <span className="quickstart-step">{item.step}</span>
                <code>{item.cmd}</code>
                <span className="quickstart-desc">{item.desc}</span>
              </li>
            ))}
          </ol>
        </section>

        <section className="tutorial-section">
          <h2>Skills 速查</h2>
          <div className="skill-grid">
            {skills.map((skill) => (
              <article className={`skill-card skill-tag-${skill.tag}`} key={skill.key}>
                <header className="skill-card-head">
                  <code className="skill-name">{skill.name}</code>
                  <span className="skill-tag">{skill.tag}</span>
                </header>
                <dl className="skill-fields">
                  <dt>何时用</dt><dd>{skill.when}</dd>
                  <dt>命令</dt><dd><code>{skill.command}</code></dd>
                  <dt>输入</dt><dd>{skill.input}</dd>
                  <dt>输出</dt><dd>{skill.output}</dd>
                  <dt>下一步</dt><dd>{skill.next}</dd>
                  <dt>纪律</dt>
                  <dd>
                    <ul className="skill-discipline">
                      {skill.discipline.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  </dd>
                </dl>
              </article>
            ))}
          </div>
        </section>

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
      </div>
    </div>
  );
}

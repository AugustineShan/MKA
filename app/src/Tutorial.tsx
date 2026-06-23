import { useEffect } from "react";
import { pipelineMain, pipelineSide, quickstart, skills } from "./tutorialContent";

export function Tutorial({ onClose }: { onClose: () => void }) {
  // Esc 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="tutorial-overlay" role="dialog" aria-modal="true" aria-label="使用教程">
      <div className="tutorial-page">
        <header className="tutorial-header">
          <div>
            <div className="eyebrow">Workbench</div>
            <h1>使用教程</h1>
          </div>
          <button className="tutorial-close" onClick={onClose} type="button" aria-label="关闭">✕</button>
        </header>

        <section className="tutorial-section">
          <h2>管线全景</h2>
          <div className="pipeline-main">
            {pipelineMain.map((node, i) => (
              <span className="pipeline-node-wrap" key={node}>
                <span className={i % 2 === 1 ? "pipeline-node pipeline-cmd" : "pipeline-node"}>{node}</span>
                {i < pipelineMain.length - 1 ? <span className="pipeline-arrow">→</span> : null}
              </span>
            ))}
          </div>
          <div className="pipeline-side">
            {pipelineSide.map((s) => (
              <div className="pipeline-side-item" key={s.label}>
                <code>{s.label}</code>
                <span>{s.desc}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="tutorial-section">
          <h2>新手 4 步</h2>
          <ol className="quickstart">
            {quickstart.map((q) => (
              <li key={q.step}>
                <span className="quickstart-step">{q.step}</span>
                <code>{q.cmd}</code>
                <span className="quickstart-desc">{q.desc}</span>
              </li>
            ))}
          </ol>
        </section>

        <section className="tutorial-section">
          <h2>Skills 速查</h2>
          <div className="skill-grid">
            {skills.map((s) => (
              <article className={`skill-card skill-tag-${s.tag}`} key={s.key}>
                <header className="skill-card-head">
                  <code className="skill-name">{s.name}</code>
                  <span className="skill-tag">{s.tag}</span>
                </header>
                <dl className="skill-fields">
                  <dt>何时用</dt><dd>{s.when}</dd>
                  <dt>命令</dt><dd><code>{s.command}</code></dd>
                  <dt>输入</dt><dd>{s.input}</dd>
                  <dt>输出</dt><dd>{s.output}</dd>
                  <dt>下一步</dt><dd>{s.next}</dd>
                  <dt>纪律</dt>
                  <dd>
                    <ul className="skill-discipline">
                      {s.discipline.map((d) => <li key={d}>{d}</li>)}
                    </ul>
                  </dd>
                </dl>
              </article>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { APP_VERSION } from '../version';
import { useAnalytics } from '../hooks/useAnalytics';
import { CATALOG } from '../features/workflow/exampleCatalog';
import { INTRO_VIDEO } from '../links';
import { VideoEmbed } from '../components/VideoEmbed';
import editorShot from '../../../docs/user-guide/images/04-editor-example.png';
import suggestShot from '../../../docs/user-guide/images/14-suggest.png';
import safetyShot from '../../../docs/user-guide/images/07-safety.png';
import compareShot from '../../../docs/user-guide/images/12-compare-runs.png';

const GITHUB_URL = 'https://github.com/fuvito/aiflow';

const WORKFLOW_STEPS = [
  { icon: '💬', label: 'Describe', desc: 'Describe a workflow in plain language and let AI draw it, or start from one of twelve examples' },
  { icon: '✏️', label: 'Design', desc: 'Edit steps, connections, settings and data contracts on a canvas, with undo' },
  { icon: '✅', label: 'Check & fix', desc: 'Design checks, one-click fixes, safety checks and a failure drill' },
  { icon: '🧪', label: 'Test & compare', desc: 'Simulate with a full trace, run test suites, and see exactly what a change broke' },
  { icon: '🔗', label: 'Share & export', desc: 'Versions, read-only share links, and runnable Python, LangGraph or MCP code' },
];

const NODE_TYPES = [
  { type: 'LLM', color: '#7c6af7', desc: 'Language model calls' },
  { type: 'TOOL', color: '#f7a24a', desc: 'External tool integrations' },
  { type: 'API', color: '#4af7c4', desc: 'HTTP API calls' },
  { type: 'RAG', color: '#f74a8a', desc: 'Retrieval-augmented generation' },
  { type: 'CONDITION', color: '#f7e24a', desc: 'Branching logic' },
  { type: 'HITL', color: '#4a8af7', desc: 'Human-in-the-loop review' },
  { type: 'DATABASE', color: '#a24af7', desc: 'Database queries' },
  { type: 'TRANSFORM', color: '#4af74a', desc: 'Data transformation' },
];

const SHOTS = [
  { src: editorShot, title: 'Design on a canvas', alt: 'The AiFlow editor with the Supply Chain Monitor example: steps, connections and a settings panel.',
    text: 'A ready-made workflow loaded in the editor: every step, connection and setting in one view.' },
  { src: suggestShot, title: 'Check, then fix', alt: 'The Suggested changes dialog listing fixes for design findings, each with an Apply button.',
    text: 'Design findings turn into suggested fixes, applied as one undoable edit.' },
  { src: safetyShot, title: 'Safety checks', alt: 'The Safety checks dialog showing prompt-injection exposure and the results of a failure drill.',
    text: 'Where planted text could reach an action, and which failures nobody would notice.' },
  { src: compareShot, title: 'Know what a change broke', alt: 'A comparison of two test runs: a regression, the case that broke, and the edit that caused it.',
    text: 'Run a test suite again and see which cases regressed, and the edit that caused it.' },
];

/** First sentence of a description, for a card. */
const firstSentence = (text: string) => {
  const end = text.indexOf('. ');
  return end === -1 ? text : text.slice(0, end + 1);
};

const TECH_STACK = [
  { layer: 'Frontend', items: ['React 19', 'TypeScript', 'Vite', 'React Flow'] },
  { layer: 'Backend', items: ['Python', 'FastAPI', 'Pydantic', 'LangChain'] },
  { layer: 'AI / LLM', items: ['OpenAI models', 'Provider-agnostic interface', 'Structured output'] },
  { layer: 'Infra', items: ['AWS Lambda', 'AWS Amplify', 'Supabase', 'PostgreSQL + RLS'] },
];

export default function LandingPage() {
  const [isDark, setIsDark] = useState(() => localStorage.getItem('aiflow-theme') !== 'light');
  const { track } = useAnalytics();

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
  }, [isDark]);

  useEffect(() => {
    document.title = 'AiFlow — Visual AI Workflow Designer';
    return () => { document.title = 'AiFlow'; };
  }, []);

  useEffect(() => {
    track('page_view', 'landing');
  }, [track]);

  function toggleTheme() {
    setIsDark(d => {
      const next = !d;
      localStorage.setItem('aiflow-theme', next ? 'dark' : 'light');
      return next;
    });
  }

  return (
    <div className="landing">
      {/* ── Nav ── */}
      <nav className="landing-nav">
        <div className="landing-nav-brand">
          <span className="landing-logo-icon">⬡</span>
          <span>AiFlow</span>
        </div>
        <div className="landing-nav-links">
          <Link to="/guide">User guide</Link>
          <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer">GitHub</a>
          <button className="landing-nav-theme" onClick={toggleTheme} title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}>
            {isDark ? '☀' : '☾'}
          </button>
          <Link to="/login" className="landing-nav-login">Sign in</Link>
          <Link to="/request-access" className="landing-nav-cta">Request access</Link>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section className="landing-hero">
        <div className="landing-hero-content">
          <div className="landing-badge">Private access · Portfolio project</div>
          <h1 className="landing-hero-title">
            Visual tooling for<br />
            <span className="landing-hero-accent">agentic AI workflows</span>
          </h1>
          <p className="landing-hero-sub">
            AiFlow is a developer environment for designing, checking, testing and sharing
            multi-step AI workflows — built as an exploration of developer tooling for agentic systems.
          </p>
          <div className="landing-hero-actions">
            <Link to="/request-access" className="landing-btn-primary">
              Request demo access
            </Link>
            <Link to="/guide" className="landing-btn-secondary">
              Read the user guide
            </Link>
            <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="landing-btn-secondary">
              View on GitHub
            </a>
          </div>
        </div>
        <div className="landing-hero-visual">
          <WorkflowVisual />
        </div>
      </section>

      {/* ── Introduction video ── */}
      <section className="landing-section" id="introduction">
        <div className="landing-container landing-video-section">
          <h2>Watch the app introduction</h2>
          <p className="landing-section-sub">A short walkthrough of AiFlow, from idea to code (about 7 minutes).</p>
          <VideoEmbed embedUrl={INTRO_VIDEO.embedUrl} watchUrl={INTRO_VIDEO.watchUrl} title={INTRO_VIDEO.title} />
        </div>
      </section>

      {/* ── Problem ── */}
      <section className="landing-section landing-section-alt">
        <div className="landing-container">
          <h2>The problem with agentic AI development</h2>
          <div className="landing-problem-grid">
            <div className="landing-problem-card">
              <span className="landing-problem-icon">👁</span>
              <h3>No visibility</h3>
              <p>Agentic systems are hard to reason about. You write code, run it, and hope it does what you think it does.</p>
            </div>
            <div className="landing-problem-card">
              <span className="landing-problem-icon">🔁</span>
              <h3>Slow iteration</h3>
              <p>Changing a single node means re-running the entire chain. Every small change is expensive to test.</p>
            </div>
            <div className="landing-problem-card">
              <span className="landing-problem-icon">📄</span>
              <h3>Locked in code</h3>
              <p>The workflow structure lives only in code. You can't quickly share it, explain it, or review it visually.</p>
            </div>
          </div>
        </div>
      </section>

      {/* ── How it works ── */}
      <section className="landing-section">
        <div className="landing-container">
          <h2>How AiFlow works</h2>
          <p className="landing-section-sub">Five stages from idea to a tested, shareable workflow.</p>
          <div className="landing-pipeline">
            {WORKFLOW_STEPS.map((step, i) => (
              <div key={step.label} className="landing-pipeline-step">
                <div className="landing-pipeline-icon">{step.icon}</div>
                <div className="landing-pipeline-label">{step.label}</div>
                <div className="landing-pipeline-desc">{step.desc}</div>
                {i < WORKFLOW_STEPS.length - 1 && <div className="landing-pipeline-arrow">→</div>}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── See it in action ── */}
      <section className="landing-section landing-section-alt">
        <div className="landing-container">
          <h2>See it in action</h2>
          <p className="landing-section-sub">Screenshots from the real application, taken from the user guide.</p>
          <div className="landing-shots">
            {SHOTS.map((shot) => (
              <figure key={shot.title} className="landing-shot">
                <img src={shot.src} alt={shot.alt} loading="lazy" />
                <figcaption><strong>{shot.title}.</strong> {shot.text}</figcaption>
              </figure>
            ))}
          </div>
        </div>
      </section>

      {/* ── Node types ── */}
      <section className="landing-section">
        <div className="landing-container">
          <h2>Built for real agentic patterns</h2>
          <p className="landing-section-sub">
            AiFlow understands the building blocks of modern AI systems.
          </p>
          <div className="landing-nodes-grid">
            {NODE_TYPES.map(n => (
              <div key={n.type} className="landing-node-chip" style={{ borderColor: n.color }}>
                <span className="landing-node-dot" style={{ background: n.color }} />
                <span className="landing-node-type">{n.type}</span>
                <span className="landing-node-desc">{n.desc}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Example workflows ── */}
      <section className="landing-section landing-section-alt">
        <div className="landing-container">
          <h2>{CATALOG.length} example workflows</h2>
          <p className="landing-section-sub">
            Ready to open, run and copy (File, then Examples). Most show good practice: outside steps are checked,
            failures are handled, and a person reviews what a model wrote before anything changes. One is flawed on
            purpose, so you can try the checks on it.
          </p>
          <div className="landing-examples-grid">
            {CATALOG.map((entry) => {
              const wf = entry.json as { id: string; name: string; description: string };
              return (
                <div key={wf.id} className="landing-example-card" data-testid="landing-example">
                  <div className="landing-example-meta">
                    <span className={`landing-level landing-level--${entry.difficulty}`}>{entry.difficulty}</span>
                    <span>{entry.nodeCount} steps</span>
                  </div>
                  <h3>{wf.name}</h3>
                  <p className="landing-example-desc">{firstSentence(wf.description)}</p>
                  <div className="landing-example-industry">{entry.industry}</div>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── Tech stack ── */}
      <section className="landing-section">
        <div className="landing-container">
          <h2>Technology</h2>
          <div className="landing-tech-grid">
            {TECH_STACK.map(t => (
              <div key={t.layer} className="landing-tech-card">
                <div className="landing-tech-layer">{t.layer}</div>
                <ul>
                  {t.items.map(item => <li key={item}>{item}</li>)}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <section className="landing-section landing-cta-section">
        <div className="landing-container landing-cta-container">
          <h2>Request access</h2>
          <p>
            AiFlow is in private access. Submit a request and I'll review it personally.
          </p>
          <div className="landing-hero-actions">
            <Link to="/request-access" className="landing-btn-primary">
              Request demo access
            </Link>
            <Link to="/guide" className="landing-btn-secondary">
              Read the user guide
            </Link>
            <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="landing-btn-secondary">
              Browse the code
            </a>
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="landing-footer">
        <div className="landing-container landing-footer-inner">
          <span>
            <span className="landing-logo-icon">⬡</span> AiFlow — built by Fuat Yazar
          </span>
          <div className="landing-footer-links">
            <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer">GitHub</a>
            <Link to="/guide">User guide</Link>
            <Link to="/request-access">Request access</Link>
            <Link to="/login">Sign in</Link>
            <a href="mailto:fuatyazar@gmail.com">Contact</a>
            <span className="landing-version" data-testid="landing-version">v{APP_VERSION}</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

function WorkflowVisual() {
  const nodes = [
    { id: 'start', label: 'START', x: 140, y: 10, color: '#4af7c4' },
    { id: 'llm', label: 'LLM', x: 60, y: 90, color: '#7c6af7' },
    { id: 'cond', label: 'CONDITION', x: 220, y: 90, color: '#f7e24a' },
    { id: 'tool', label: 'TOOL', x: 140, y: 170, color: '#f7a24a' },
    { id: 'end', label: 'END', x: 140, y: 250, color: '#f74a8a' },
  ];
  const edges = [
    { from: 'start', to: 'llm' },
    { from: 'start', to: 'cond' },
    { from: 'llm', to: 'tool' },
    { from: 'cond', to: 'tool' },
    { from: 'tool', to: 'end' },
  ];
  const nodeMap: Record<string, { x: number; y: number }> = {};
  nodes.forEach(n => { nodeMap[n.id] = { x: n.x + 44, y: n.y + 16 }; });

  return (
    <div className="landing-hero-diagram">
      <svg viewBox="0 0 320 300" width="320" height="300">
        {edges.map((e, i) => (
          <line
            key={i}
            x1={nodeMap[e.from].x} y1={nodeMap[e.from].y}
            x2={nodeMap[e.to].x} y2={nodeMap[e.to].y}
            stroke="var(--border-md)" strokeWidth="2"
          />
        ))}
        {nodes.map(n => (
          <g key={n.id} transform={`translate(${n.x},${n.y})`}>
            <rect
              width="88" height="32" rx="6"
              fill="var(--bg-raised)"
              stroke={n.color}
              strokeWidth="1.5"
            />
            <text
              x="44" y="21"
              textAnchor="middle"
              fill={n.color}
              fontSize="11"
              fontFamily="monospace"
              fontWeight="600"
            >
              {n.label}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

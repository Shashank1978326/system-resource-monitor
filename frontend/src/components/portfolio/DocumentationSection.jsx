import Icon from "../layout/Icons";
import { portfolioData } from "../../data/portfolioData";

export default function DocumentationSection() {
  const { documentation, meta } = portfolioData;

  return (
    <section className="portfolio-section" id="documentation">
      <div className="portfolio-section-header">
        <span className="section-eyebrow">Developer Resources & Guides</span>
        <h2 className="section-title">Documentation & Quick Start</h2>
        <p className="section-subtitle">
          Comprehensive guides for setup, code extension, architectural patterns, and vulnerability reporting.
        </p>
      </div>

      <div className="docs-grid">
        {documentation.map((doc, idx) => (
          <div key={idx} className="doc-card">
            <div className="doc-card-icon">
              <Icon name="reports" size={18} />
            </div>
            <div className="doc-card-content">
              <h3 className="doc-card-title">{doc.title}</h3>
              <p className="doc-card-desc">{doc.desc}</p>
              <div className="doc-card-path">
                <code>{doc.path}</code>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="quickstart-box">
        <div className="quickstart-header">
          <Icon name="terminal" size={18} />
          <h3 className="quickstart-title">Run Locally in 2 Minutes</h3>
        </div>
        <div className="quickstart-code-blocks">
          <div className="code-block">
            <div className="code-block-label">1. Clone & Setup Backend</div>
            <pre>
{`git clone ${meta.githubRepoUrl}.git
cd system-resource-monitor/backend
python -m venv .venv
# On Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`}
            </pre>
          </div>
          <div className="code-block">
            <div className="code-block-label">2. Setup & Launch Frontend</div>
            <pre>
{`cd ../frontend
npm install
npm run dev
# Open browser at http://localhost:5173`}
            </pre>
          </div>
        </div>
      </div>
    </section>
  );
}


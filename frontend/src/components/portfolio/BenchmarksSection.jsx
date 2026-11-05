import Icon from "../layout/Icons";
import { portfolioData } from "../../data/portfolioData";

export default function BenchmarksSection() {
  const { benchmarks, securityHighlights } = portfolioData;

  return (
    <section className="portfolio-section" id="benchmarks">
      <div className="portfolio-section-header">
        <span className="section-eyebrow">Empirical Verification</span>
        <h2 className="section-title">Performance Benchmarks & Security Guarantees</h2>
        <p className="section-subtitle">
          Measured in local benchmark suites across 27,000+ snapshots and verified against strict security benchmarks.
        </p>
      </div>

      <div className="benchmarks-container">
        <div className="benchmarks-grid">
          {benchmarks.map((b, idx) => (
            <div key={idx} className="benchmark-card">
              <div className="benchmark-value">{b.value}</div>
              <div className="benchmark-label">{b.label}</div>
              <div className="benchmark-detail">{b.detail}</div>
            </div>
          ))}
        </div>

        <div className="security-highlights-panel">
          <div className="security-panel-header">
            <Icon name="shield" size={20} />
            <h3 className="security-panel-title">Production Security & Privacy Hardening</h3>
          </div>
          <p className="security-panel-desc">
            Engineered defensively for public GitHub showcase and safe multi-user workstation deployment:
          </p>
          <ul className="security-list">
            {securityHighlights.map((highlight, idx) => (
              <li key={idx} className="security-list-item">
                <span className="security-check-icon">
                  <Icon name="check" size={14} />
                </span>
                <span>{highlight}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}


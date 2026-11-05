import { portfolioData } from "../../data/portfolioData";

export default function TechStackSection() {
  const { technologies } = portfolioData;

  return (
    <section className="portfolio-section" id="tech-stack">
      <div className="portfolio-section-header">
        <span className="section-eyebrow">Modern Software Engineering</span>
        <h2 className="section-title">Technology Stack</h2>
        <p className="section-subtitle">
          Chosen for speed, memory efficiency, concurrency, and cross-platform reliability.
        </p>
      </div>

      <div className="tech-stack-grid">
        {technologies.map((group, idx) => (
          <div key={idx} className="tech-group-card">
            <h3 className="tech-group-title">{group.category}</h3>
            <div className="tech-items-list">
              {group.items.map((item, i) => (
                <div key={i} className="tech-item">
                  <span className="tech-name">{item.name}</span>
                  <span className="tech-desc">{item.desc}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}


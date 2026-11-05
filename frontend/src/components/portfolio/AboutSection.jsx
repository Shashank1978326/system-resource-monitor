import Icon from "../layout/Icons";
import { portfolioData } from "../../data/portfolioData";

export default function AboutSection() {
  const { about } = portfolioData;

  const conceptIcons = ["processes", "memory", "disk", "network", "system", "history"];

  return (
    <section className="portfolio-section" id="about">
      <div className="portfolio-section-header">
        <span className="section-eyebrow">Operating Systems Engineering</span>
        <h2 className="section-title">{about.heading}</h2>
        <p className="section-subtitle">{about.subheading}</p>
      </div>

      <div className="portfolio-about-grid">
        <div className="about-text-panel">
          <div className="about-block">
            <h3 className="about-subheading">Project Purpose</h3>
            <p className="about-paragraph">{about.purpose}</p>
          </div>

          <div className="about-block">
            <h3 className="about-subheading">The Problem Solved</h3>
            <p className="about-paragraph">{about.problemStatement}</p>
          </div>
        </div>

        <div className="about-concepts-grid">
          {about.osConcepts.map((c, i) => (
            <div key={i} className="concept-card">
              <div className="concept-icon-wrap">
                <Icon name={conceptIcons[i % conceptIcons.length]} size={20} />
              </div>
              <div className="concept-body">
                <h4 className="concept-title">{c.title}</h4>
                <p className="concept-desc">{c.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}


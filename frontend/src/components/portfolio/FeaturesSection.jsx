import { useState } from "react";
import { Link } from "react-router-dom";
import Icon from "../layout/Icons";
import { portfolioData } from "../../data/portfolioData";

export default function FeaturesSection() {
  const { features } = portfolioData;
  const [activeCategory, setActiveCategory] = useState("All");

  const categories = ["All", ...new Set(features.map((f) => f.category))];

  const filteredFeatures =
    activeCategory === "All"
      ? features
      : features.filter((f) => f.category === activeCategory);

  return (
    <section className="portfolio-section" id="features">
      <div className="portfolio-section-header">
        <span className="section-eyebrow">Production-Grade Capabilities</span>
        <h2 className="section-title">13 Core Features & Diagnostic Modules</h2>
        <p className="section-subtitle">
          Engineered with genuine OS telemetry, statistical models, SQLite timeseries caching, and reactive UI charts.
        </p>
      </div>

      <div className="portfolio-filter-tabs">
        {categories.map((cat) => (
          <button
            key={cat}
            type="button"
            className={`portfolio-tab ${activeCategory === cat ? "portfolio-tab-active" : ""}`}
            onClick={() => setActiveCategory(cat)}
          >
            {cat}
          </button>
        ))}
      </div>

      <div className="features-grid">
        {filteredFeatures.map((f) => (
          <div key={f.id} className="feature-card">
            <div className="feature-card-header">
              <div className="feature-icon-badge">
                <Icon name={f.icon || "dashboard"} size={20} />
              </div>
              <span className="feature-category-pill">{f.category}</span>
            </div>

            <h3 className="feature-card-title">{f.title}</h3>
            <p className="feature-card-desc">{f.desc}</p>

            <div className="feature-card-details">
              <strong>Technical Implementation:</strong>
              <p>{f.details}</p>
            </div>

            <div className="feature-card-footer">
              <Link to={f.route} className="feature-live-link">
                <span>Open in App</span>
                <Icon name="arrowRight" size={14} />
              </Link>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}


import { Link } from "react-router-dom";
import Icon from "../layout/Icons";
import { portfolioData } from "../../data/portfolioData";

export default function HeroSection() {
  const { hero, meta, benchmarks } = portfolioData;

  const scrollTo = (id) => {
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: "smooth" });
    }
  };

  return (
    <section className="portfolio-hero" id="hero">
      <div className="portfolio-hero-glow" aria-hidden="true" />
      <div className="portfolio-hero-content">
        <div className="portfolio-badge">
          <span className="badge-pulse" />
          <span>{hero.badge}</span>
        </div>

        <h1 className="portfolio-hero-title">
          {hero.headline}
        </h1>

        <p className="portfolio-hero-description">
          {hero.description}
        </p>

        <div className="portfolio-hero-cta-group">
          <Link to="/" className="portfolio-btn portfolio-btn-lg portfolio-btn-primary">
            <Icon name="dashboard" size={18} />
            <span>{hero.primaryCta.label}</span>
          </Link>

          <a
            href={hero.secondaryCta.url}
            target="_blank"
            rel="noopener noreferrer"
            className="portfolio-btn portfolio-btn-lg portfolio-btn-secondary"
          >
            <Icon name="github" size={18} />
            <span>{hero.secondaryCta.label}</span>
          </a>

          <button
            type="button"
            onClick={() => scrollTo("architecture")}
            className="portfolio-btn portfolio-btn-lg portfolio-btn-ghost"
          >
            <span>{hero.tertiaryCta.label}</span>
            <Icon name="arrowRight" size={16} />
          </button>
        </div>

        <div className="portfolio-hero-metrics">
          {benchmarks.slice(0, 4).map((b, i) => (
            <div key={i} className="portfolio-metric-card">
              <span className="metric-val">{b.value}</span>
              <span className="metric-lbl">{b.label}</span>
              <span className="metric-desc">{b.subtext}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}


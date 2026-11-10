import { Link } from "react-router-dom";
import Icon from "../layout/Icons";
import useTheme from "../../hooks/useTheme";
import { portfolioData } from "../../data/portfolioData";

export default function PortfolioHeader() {
  const { theme, toggleTheme } = useTheme();
  const { meta } = portfolioData;

  const scrollTo = (id) => {
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: "smooth" });
    }
  };

  return (
    <header className="portfolio-header">
      <div className="portfolio-header-inner">
        <Link to="/showcase" className="portfolio-brand">
          <span className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
          </span>
          <div className="portfolio-brand-text">
            <span className="portfolio-brand-name">{meta.title}</span>
            <span className="portfolio-brand-badge">Academic Project</span>
          </div>
        </Link>

        <nav className="portfolio-nav" aria-label="Showcase navigation">
          <button type="button" onClick={() => scrollTo("about")} className="portfolio-nav-link">About</button>
          <button type="button" onClick={() => scrollTo("features")} className="portfolio-nav-link">Features</button>
          <button type="button" onClick={() => scrollTo("architecture")} className="portfolio-nav-link">Architecture</button>
          <button type="button" onClick={() => scrollTo("tech-stack")} className="portfolio-nav-link">Tech Stack</button>
          <button type="button" onClick={() => scrollTo("benchmarks")} className="portfolio-nav-link">Benchmarks</button>
          <button type="button" onClick={() => scrollTo("documentation")} className="portfolio-nav-link">Docs</button>
        </nav>

        <div className="portfolio-header-actions">
          <button
            type="button"
            className="icon-button theme-toggle"
            onClick={toggleTheme}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            title="Toggle theme"
          >
            <Icon name={theme === "dark" ? "sun" : "moon"} size={17} />
          </button>

          <a
            href={meta.githubRepoUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="portfolio-btn portfolio-btn-secondary"
            title="View on GitHub"
          >
            <Icon name="github" size={16} />
            <span>GitHub</span>
          </a>

          <Link to="/dashboard" className="portfolio-btn portfolio-btn-primary">
            <Icon name="dashboard" size={16} />
            <span>Live Dashboard</span>
          </Link>
        </div>
      </div>
    </header>
  );
}


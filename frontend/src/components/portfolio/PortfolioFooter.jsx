import { Link } from "react-router-dom";
import Icon from "../layout/Icons";
import { portfolioData } from "../../data/portfolioData";

export default function PortfolioFooter() {
  const { meta } = portfolioData;

  const scrollTo = (id) => {
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: "smooth" });
    }
  };

  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <footer className="portfolio-footer">
      <div className="portfolio-footer-inner">
        <div className="footer-top">
          <div className="footer-brand-col">
            <div className="portfolio-brand">
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
            </div>
            <p className="footer-tagline">{meta.tagline}</p>
            <p className="footer-author">
              Engineered by{" "}
              <a
                href={meta.githubProfileUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="footer-author-link"
              >
                {meta.author} ({meta.githubUsername})
              </a>
            </p>
          </div>

          <div className="footer-links-col">
            <h4 className="footer-heading">Navigation</h4>
            <ul className="footer-links">
              <li><Link to="/dashboard">Live Dashboard</Link></li>
              <li><a href="#about" onClick={(e) => { e.preventDefault(); scrollTo("about"); }}>About Project</a></li>
              <li><a href="#features" onClick={(e) => { e.preventDefault(); scrollTo("features"); }}>13 Core Features</a></li>
              <li><a href="#architecture" onClick={(e) => { e.preventDefault(); scrollTo("architecture"); }}>Architecture</a></li>
              <li><a href="#tech-stack" onClick={(e) => { e.preventDefault(); scrollTo("tech-stack"); }}>Tech Stack</a></li>
              <li><a href="#benchmarks" onClick={(e) => { e.preventDefault(); scrollTo("benchmarks"); }}>Benchmarks & Security</a></li>
            </ul>
          </div>

          <div className="footer-links-col">
            <h4 className="footer-heading">Resources</h4>
            <ul className="footer-links">
              <li>
                <a href={meta.githubRepoUrl} target="_blank" rel="noopener noreferrer">
                  GitHub Repository
                </a>
              </li>
              <li>
                <a href={`${meta.githubRepoUrl}/blob/main/DEVELOPMENT_GUIDE.md`} target="_blank" rel="noopener noreferrer">
                  Developer Guide
                </a>
              </li>
              <li>
                <a href={`${meta.githubRepoUrl}/blob/main/SECURITY.md`} target="_blank" rel="noopener noreferrer">
                  Security Policy
                </a>
              </li>
              <li>
                <a href={`${meta.githubRepoUrl}/blob/main/CONTRIBUTING.md`} target="_blank" rel="noopener noreferrer">
                  Contributing
                </a>
              </li>
            </ul>
          </div>
        </div>

        <div className="footer-bottom">
          <p className="footer-copy">
            © {new Date().getFullYear()} {meta.title} • Operating Systems Engineering Project. Released under MIT License.
          </p>
          <button type="button" onClick={scrollToTop} className="footer-back-to-top">
            <span>Back to top</span>
            <Icon name="arrowRight" size={14} />
          </button>
        </div>
      </div>
    </footer>
  );
}


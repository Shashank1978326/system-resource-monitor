import PortfolioHeader from "../components/portfolio/PortfolioHeader";
import HeroSection from "../components/portfolio/HeroSection";
import AboutSection from "../components/portfolio/AboutSection";
import FeaturesSection from "../components/portfolio/FeaturesSection";
import ArchitectureSection from "../components/portfolio/ArchitectureSection";
import TechStackSection from "../components/portfolio/TechStackSection";
import BenchmarksSection from "../components/portfolio/BenchmarksSection";
import DocumentationSection from "../components/portfolio/DocumentationSection";
import PortfolioFooter from "../components/portfolio/PortfolioFooter";

export default function PortfolioShowcase() {
  return (
    <div className="portfolio-showcase-page">
      <PortfolioHeader />
      <main className="portfolio-main">
        <HeroSection />
        <AboutSection />
        <FeaturesSection />
        <ArchitectureSection />
        <TechStackSection />
        <BenchmarksSection />
        <DocumentationSection />
      </main>
      <PortfolioFooter />
    </div>
  );
}


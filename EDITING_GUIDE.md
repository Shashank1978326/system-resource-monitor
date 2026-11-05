# System Resource Monitor – Portfolio & Website Editing Guide

This guide explains how you, your teammates, or your professor can easily edit, update, or expand the **System Resource Monitor** portfolio showcase website.

The website has been architected with **centralized content configuration**, meaning **90% of content modifications can be made by editing a single JavaScript data file without modifying React JSX components**.

---

## 📁 Key File Locations

| Purpose | File Path |
| :--- | :--- |
| **All Website Text & Data** | `frontend/src/data/portfolioData.js` |
| **Showcase Page Root** | `frontend/src/pages/PortfolioShowcase.jsx` |
| **Modular Showcase Components** | `frontend/src/components/portfolio/` |
| **Global & Showcase Styling** | `frontend/src/index.css` |
| **Application Routing** | `frontend/src/App.jsx` |
| **Icons Library** | `frontend/src/components/layout/Icons.jsx` |

---

## 1. Updating Project Title, Tagline & Author Information

Open `frontend/src/data/portfolioData.js`. The `meta` object contains the core project metadata:

```javascript
export const portfolioData = {
  meta: {
    title: "System Resource Monitor",
    subtitle: "A Real-Time Operating System Resource Monitoring and Analytics Platform",
    tagline: "Academic Operating Systems Project & Production-Grade Workstation Diagnostic Suite",
    author: "Shashank",
    githubUsername: "Shashank1978326",
    githubRepoUrl: "https://github.com/Shashank1978326/system-resource-monitor",
    githubProfileUrl: "https://github.com/Shashank1978326",
    liveDashboardPath: "/",
    docsAnchor: "#documentation",
  },
  // ...
};
```

Simply change any string value (such as your name, profile link, or repository URL) and save the file. The changes will automatically reflect across the Header, Hero, and Footer.

---

## 2. Modifying the Hero Section

In `frontend/src/data/portfolioData.js`, locate the `hero` object:

```javascript
hero: {
  badge: "100% Tested & Verified • 356 Automated Tests Passed",
  headline: "Real-Time Hardware Telemetry, Statistical Anomaly Detection & ML Forecasting",
  description: "A complete full-stack diagnostic platform engineered...",
  primaryCta: { label: "Explore Live Dashboard", path: "/" },
  secondaryCta: { label: "View on GitHub", url: "https://github.com/Shashank1978326/system-resource-monitor" },
  tertiaryCta: { label: "System Architecture", anchor: "#architecture" },
},
```

- Update `badge` for new test counts, certifications, or release versions.
- Update `headline` or `description` to emphasize different OS concepts.
- Update CTA labels or target paths.

---

## 3. Adding, Editing, or Removing Features

Features shown in the interactive 13-feature grid are defined in `portfolioData.features`:

```javascript
{
  id: "cpu",
  icon: "cpu",                         // Icon name from Icons.jsx
  category: "Hardware",                // Filter category (Hardware, Storage, Network, etc.)
  route: "/cpu",                       // Destination in live dashboard
  title: "CPU Multi-Core Telemetry",
  desc: "Per-core load distribution, clock frequencies, logical and physical topologies.",
  details: "Samples psutil.cpu_percent(percpu=True) every second with non-blocking intervals.",
}
```

### To Edit an Existing Feature:
Edit the `title`, `desc`, or `details` strings in `portfolioData.features`.

### To Add a New Feature:
Add a new object to the `features` array:
```javascript
{
  id: "disk-health",
  icon: "disk",
  category: "Storage",
  route: "/disk",
  title: "S.M.A.R.T. Drive Health",
  desc: "Hard drive self-monitoring, temperature checks, and reallocated sector counts.",
  details: "Invokes platform drive utilities to predict drive failure states.",
}
```

### To Remove a Feature:
Delete or comment out the corresponding object from the `features` array. The filter tabs and grid cards will automatically update.

---

## 4. Updating the Technology Stack

In `portfolioData.technologies`, technologies are grouped by layer:

```javascript
technologies: [
  {
    category: "Backend Engine",
    items: [
      { name: "Python 3.14", desc: "Core language & native typing" },
      { name: "FastAPI", desc: "High-performance ASGI framework" },
      // Add or edit technologies here
    ],
  },
  // ...
]
```

To add a technology (e.g. Docker, Redis, Kubernetes), add an item to the appropriate category.

---

## 5. Updating Benchmarks & Security Highlights

### Benchmarks:
Modify the `benchmarks` array in `portfolioData.js`:
```javascript
benchmarks: [
  { label: "Backend Test Suite", value: "356 / 356 Passed", detail: "100% test pass rate" },
  { label: "Collector Cycle Time", value: "20.84 ms", detail: "< 2.2% of 1s sampling window" },
  // ...
]
```

### Security Highlights:
Add or edit bullet points in the `securityHighlights` array in `portfolioData.js`:
```javascript
securityHighlights: [
  "Defensive HTTP Security Headers (X-Content-Type-Options: nosniff, X-Frame-Options: DENY, Referrer-Policy)",
  "Strict Browser Origin Whitelist (CORS wildcards explicitly disallowed at application startup)",
  // ...
]
```

---

## 6. Updating Documentation Links

In `portfolioData.documentation`, add or edit guide cards:
```javascript
documentation: [
  {
    title: "Final Verification Report",
    path: "FINAL_PROJECT_VERIFICATION_REPORT.md",
    desc: "Comprehensive 14-section validation audit covering performance, security, and multi-platform support.",
  },
  // ...
]
```

---

## 7. Adding New SVG Icons

All SVG icons are centralized in `frontend/src/components/layout/Icons.jsx`.

To add a new icon:
1. Open `frontend/src/components/layout/Icons.jsx`.
2. Add a new key to the `paths` dictionary with standard SVG JSX elements:
   ```javascript
   myIcon: <path d="..." />,
   ```
3. Use it anywhere with `<Icon name="myIcon" size={18} />`.

---

## 8. Customizing Colors & Themes

The showcase website automatically adapts to both **Light** and **Dark** modes using CSS design tokens defined at the top of `frontend/src/index.css`:

```css
:root {
  --page: #f5f7fb;
  --surface: #ffffff;
  --accent: #5577ec;    /* Primary brand color */
  --green: #2b9c84;     /* Success & benchmarks */
  --red: #d65b64;       /* Alerts & errors */
}

:root[data-theme="dark"] {
  --page: #111722;
  --surface: #1a2230;
  --accent: #8098ff;
  --green: #57c8a9;
  --red: #fa858c;
}
```

Changing `--accent` changes the primary color throughout buttons, links, icons, and hero glow.

---

## 9. Setting the Showcase as the Default Landing Page

By default:
- `/` renders the **Live Diagnostic Dashboard**.
- `/showcase` renders the **Project Portfolio Showcase**.

If you wish to deploy the showcase as the root `/` page (for example on a public portfolio domain or Vercel):
1. In `frontend/.env` (or environment variables in Vercel/Netlify):
   ```bash
   VITE_LANDING_PAGE=showcase
   ```
2. When this variable is set:
   - `/` displays the **Portfolio Showcase**.
   - `/dashboard` displays the **Live Diagnostic Dashboard**.

---

## 10. Building and Deploying Updates

Whenever modifications are made, test and build locally:

```powershell
# 1. Navigate to frontend directory
cd frontend

# 2. Verify compilation
npm run build

# 3. Test locally
npm run dev
```

Then commit and push your changes to GitHub:
```bash
git add frontend/src/data/portfolioData.js
git commit -m "docs: update portfolio showcase content"
git push origin main
```


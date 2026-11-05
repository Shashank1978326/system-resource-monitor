# Contributing to System Resource Monitor

Thank you for contributing to the **System Resource Monitor** project! This guide explains our team workflow, code standards, branching recommendations, and verification requirements to keep contributions clean and maintainable.

---

## 1. Development Setup

1. **Fork or Clone the Repository:**
   ```bash
   git clone https://github.com/Shashank1978326/system-resource-monitor.git
   cd system-resource-monitor
   ```

2. **Backend Setup:**
   ```bash
   cd backend
   python -m venv .venv
   # Windows:
   .\.venv\Scripts\Activate.ps1
   # Linux/macOS:
   source .venv/bin/activate

   pip install -r requirements.txt
   cp .env.example .env
   ```

3. **Frontend Setup:**
   ```bash
   cd ../frontend
   npm install
   cp .env.example .env
   ```

---

## 2. Branching Strategy

To keep the `main` branch production-ready at all times:
* **`main`**: Protected branch. Always deployable and passing all tests.
* **`feature/<feature-name>`**: For new telemetry sensors, algorithms, or dashboard views.
* **`fix/<issue-name>`**: For bug fixes and security remediations.
* **`docs/<topic>`**: For documentation updates.

Example:
```bash
git checkout -b feature/disk-io-breakdown
```

---

## 3. Coding Conventions

### Python (Backend)
* Follow **PEP 8** style guidelines.
* Use strict type annotations (`def get_metric(...) -> float | None:`).
* All database queries must use **SQLAlchemy ORM expressions**; never concatenate raw SQL strings.
* Catch hardware collection exceptions gracefully with `psutil.AccessDenied` and `psutil.NoSuchProcess` handling.
* Do not log sensitive credentials, memory dumps, or command-line parameters.

### JavaScript / React (Frontend)
* Use functional components with standard React hooks (`useState`, `useEffect`, `useMemo`, `useCallback`).
* All async Axios requests in `src/services/api.js` must accept an `AbortSignal`.
* Maintain WCAG 2.1 AA accessible contrast ratios for both Dark and Light themes.
* Use CSS tokens defined in `src/index.css` for consistent spacing and palette.

---

## 4. Commit Message Guidelines

Use clear, imperative commit messages:
* `feat: add per-core thermal tracking endpoint`
* `fix: prevent duplicate deque clear in alert restoration`
* `refactor: extract portfolio showcase into modular components`
* `docs: update development guide with prediction horizon steps`
* `test: add unit test for websocket frame ceiling`

---

## 5. Verification Checklist Before Submitting a Pull Request

Before pushing your branch or opening a Pull Request:

1. **Verify Backend Tests Pass:**
   ```bash
   cd backend
   python -m pytest -q
   ```
   *All 356 baseline tests must pass.*

2. **Verify Frontend Compiles Cleanly:**
   ```bash
   cd ../frontend
   npm run build
   ```
   *Must compile with 0 errors and 0 warnings.*

3. **Check Staged Files for Secrets:**
   ```bash
   git status
   ```
   *Ensure no `.env`, `history.sqlite3`, or credentials are staged.*

4. **Submit Pull Request:**
   Push your branch and submit a PR to `main` with a clear description of your changes and test verification results.


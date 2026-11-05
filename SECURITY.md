# Security Policy & Private File Protection

This security policy defines strict data protection rules, private configuration exclusion practices, and vulnerability reporting procedures for the **System Resource Monitor** project.

---

## 1. Public Repository Security Guidelines

Because this repository is **publicly hosted on GitHub**, all contributors (students, teammates, and maintainers) must strictly adhere to the following file protection mandates:

### A. Environment Files & Secrets (Never Commit)
Under **no circumstances** should live `.env` files be committed or tracked:
- `.env`
- `.env.local`, `.env.development`, `.env.production`, `.env.test`
- Any `.env.*` file containing non-default local variables

Instead, commit **only** template files:
- `backend/.env.example`
- `frontend/.env.example`

### B. Credentials & Private Keys
Never commit:
- API tokens, passwords, session secrets, or personal access tokens (PATs)
- SSH private keys (`id_rsa`, `id_ed25519`)
- SSL/TLS private keys or certificates (`*.pem`, `*.key`, `*.pfx`)
- Cloud service provider credentials or IAM service account JSON files

### C. Personal Hardware & Telemetry Data
The SQLite database stores real telemetry from the host machine (process names, CPU/RAM utilization curves, disk partition serials, hostname):
- `history.sqlite3`, `*.db`, `*.sqlite`, `*.sqlite3`
- Operating system crash dumps, memory dumps, or debug logs (`*.log`)
- These files are strictly ignored via `.gitignore`.

### D. Development & Cache Directories
- Python virtual environments (`.venv/`, `venv/`, `env/`)
- Python bytecode and testing caches (`__pycache__/`, `.pytest_cache/`)
- Node.js dependencies and bundles (`node_modules/`, `dist/`, `build/`)

---

## 2. Safe Local Environment Setup

Developers cloning this project must configure their local instances securely:

1. **Backend Configuration:**
   ```bash
   cd backend
   cp .env.example .env
   ```
   Modify `.env` locally as required. Git will ignore this file automatically.

2. **Frontend Configuration:**
   ```bash
   cd frontend
   cp .env.example .env
   ```
   Specify `VITE_API_BASE_URL` pointing to your local or private backend.

---

## 3. Pre-Commit Verification Checklist

Before staging, committing, or pushing any changes to GitHub, execute the following checks:

```bash
# 1. Review status of untracked and staged files
git status

# 2. Verify that no .env or database files are staged
git status | grep -E "\.env|\.sqlite|\.db|\.log"

# 3. Perform a quick test to ensure tests still pass
pytest -q
npm run build
```

If an accidental credential or private `.env` file is staged:
```bash
git reset HEAD <file>
git rm --cached <file>
```

---

## 4. Reporting a Security Vulnerability

If you discover a security vulnerability or accidental credential leakage:
1. **Do not create a public GitHub issue.**
2. Send an email to the project maintainer: `shashank.academic.project@gmail.com` (or submit a private GitHub Security Advisory).
3. Include the affected file, commit hash, and steps to reproduce.
4. If a credential was accidentally exposed, revoke and rotate the secret immediately before updating the repository.


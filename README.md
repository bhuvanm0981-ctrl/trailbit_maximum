# 🌱 Trailbit
### Find your first open-source contribution.

**Trailbit** is an open-source discovery and onboarding platform designed to help beginner developers find meaningful issues, understand unfamiliar repositories, and take their first steps into open-source contribution.

Instead of spending hours searching GitHub and figuring out where to begin, Trailbit brings beginner-friendly issues, issue health insights, and actionable contribution guidance together in one place.

<p align="center">
  <a href="https://trailbit.onrender.com">🚀 Live Demo</a> •
  <a href="https://github.com/bhuvanm0981-ctrl/trailbit_maximum">📂 Source Code</a>
</p>

---

## 🚀 Live Application

**Try Trailbit:** https://trailbit.onrender.com

> Note: The application is hosted on Render's free tier. It may take some time to wake up after a period of inactivity.

---

## 💡 The Problem

Getting started with open source can be intimidating, especially for beginners.

- Finding genuine beginner-friendly issues is difficult.
- Issues may already be closed, locked, or actively assigned.
- Understanding an unfamiliar codebase takes time.
- Contribution guidelines can be difficult to navigate.
- Beginners often don't know what steps to take after finding an issue.

## 💡 Our Solution

Trailbit simplifies the journey from discovering an issue to preparing a contribution.

It helps developers discover relevant GitHub issues, understand their activity and status, and follow a structured checklist to get started.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🔍 Issue Discovery | Discover open GitHub issues labelled `good first issue`. |
| 🎯 Skills-based Ranking | Tick the languages and areas you know and the list is ordered by how well each issue matches you (Python, JavaScript, TypeScript, Go and Rust). |
| 🔃 Order and Load More | Order by recently updated, newest, most or least discussed, and page through more results. |
| 🔎 Issue Verification | Examine issue status, activity, comments, assignees and repository information, plus open pull requests that mention the issue and people who said they are already working on it. |
| 📊 Issue Health | Generate an issue health score and explanatory badges. |
| 🗺️ Contribution Roadmap | Get a structured, beginner-friendly checklist, with the repository's own CONTRIBUTING rules quoted when a TinyFish key is set. |
| ⭐ Bookmarks | Save interesting issues and revisit them later. Bookmarks are private to your browser. |

---

## 🔄 How Trailbit Works

1. **Your skills:** Tick the languages and areas you know, or skip.
2. **Pick an issue:** Browse live GitHub issues ranked by how well they match you. Search, reorder and load more.
3. **The problem:** Read what the issue says, a typical approach, and a live health check of its status and activity.
4. **Resolve it:** Follow a step-by-step checklist from fork to pull request.
5. **Save:** Bookmark issues you want to come back to.

---

## 🛠️ Tech Stack

### Frontend
- HTML5
- CSS3 and Tailwind CSS (built locally, no CDN)
- JavaScript (ES modules, no framework)
- Self-hosted fonts

### Backend
- Python 3.11+
- FastAPI
- Uvicorn
- Pydantic

### Data and Integration
- GitHub REST API
- HTTPX (asynchronous HTTP client)
- SQLAlchemy (async)
- SQLite
- aiosqlite

### Deployment
- Render
- GitHub

### Quality
- pytest and ruff (backend)
- Playwright, ESLint and axe-core (frontend, in a real browser)
- GitHub Actions

---

## 🏗️ Architecture

```text
Trailbit
│
├── frontend/
│   ├── index.html
│   ├── style.css
│   ├── tailwind.css            (built from the classes used in the page)
│   ├── fonts/                  (self-hosted)
│   └── js/                     (ES modules: state, api, dom, ui, progress, bookmarks,
│                                skills, issues, problem, plan, select, layers, footer, main)
│
├── backend/
│   ├── main.py                 (app setup: middleware, routers, static files)
│   ├── config.py               (every environment variable, validated)
│   ├── database.py             (SQLite models and versioned migrations)
│   ├── security.py             (request ids, security headers, body limit, rate limiting)
│   ├── visitor.py              (the anonymous cookie that owns a visitor's bookmarks)
│   ├── text.py                 (summaries, file paths, topics, claims, guide rules)
│   ├── scoring.py              (difficulty, the checklist, the health check)
│   ├── utils.py
│   ├── models/
│   │   ├── request.py
│   │   └── response.py
│   ├── routes/
│   │   ├── discover.py
│   │   ├── verify.py
│   │   ├── contribution_plan.py
│   │   ├── bookmarks.py
│   │   └── meta.py             (/health and /ready)
│   └── services/
│       ├── engine.py           (GitHub search, one issue, the CONTRIBUTING guide)
│       ├── github.py           (GitHub client with plain-language errors)
│       ├── cache.py            (async cache that survives GitHub outages, request budget)
│       ├── tinyfish_api.py     (optional TinyFish Fetch client)
│       └── tinyfish.py         (compatibility import path)
│
├── tests/                      (pytest suite, Playwright browser tests, load test)
├── tools/                      (font download, Tailwind input)
├── .github/workflows/ci.yml
├── .env.example
├── .python-version
├── requirements.txt
├── requirements-dev.txt
├── render.yaml
└── README.md
```

---

## ⚙️ Getting Started

Follow these instructions to run Trailbit locally.

### Prerequisites

- Python 3.11 or newer
- Git
- A GitHub account

### 1. Clone the repository

```bash
git clone https://github.com/bhuvanm0981-ctrl/trailbit_maximum.git
```

### 2. Navigate to the project

```bash
cd trailbit_maximum
```

### 3. Create a virtual environment

**Windows:**

```powershell
python -m venv .venv
.venv\Scripts\activate
```

**Linux / macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure environment variables (optional)

Create a `.env` file in the project root. Every setting is optional; see `.env.example` for the full list.

```env
GITHUB_TOKEN=your_github_token
TINYFISH_API_KEY=your_tinyfish_key
```

A GitHub token raises the rate limits (10 to 30 searches a minute, 60 to 5,000 other requests an hour). A token without additional repository scopes is sufficient for the public repository data used by Trailbit. A TinyFish key lets plans quote each repository's CONTRIBUTING rules; without it everything else works.

Never commit your actual tokens to GitHub. `.env` is already in `.gitignore`.

### 6. Run the application

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

### 7. Open Trailbit

Visit:

```text
http://127.0.0.1:8000
```

API health check:

```text
http://127.0.0.1:8000/health
```

### 8. Run the tests

```bash
pip install -r requirements-dev.txt
pytest                    # backend tests; GitHub and TinyFish are faked
ruff check backend tests

npm ci
npm run lint
npx playwright install chromium
npm run test:e2e          # the real frontend in a real browser
python tests/loadtest.py  # optional: load and rate-limiter test
```

---

## 🔌 API Endpoints

Trailbit exposes its backend functionality through FastAPI.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Liveness check for the platform |
| GET | `/ready` | Checks the database and reports the GitHub quota last seen |
| GET | `/api/issues` | Discover GitHub issues (`q`, `sort`, `page`; see the `X-Has-More` header) |
| GET | `/api/facets` | Get the options the page starts from |
| POST | `/api/verify` | Verify an issue: health score, open pull requests, claims |
| POST | `/api/plan` | Generate a contribution plan |
| GET | `/api/checklist` | The steps for an issue, with no GitHub call |
| POST | `/api/guide` | Rules quoted from the repository's CONTRIBUTING guide |
| POST | `/api/bookmarks` | Save an issue (send only its GitHub URL) |
| GET | `/api/bookmarks` | Retrieve your saved issues |
| DELETE | `/api/bookmarks/{issue_id}` | Remove a bookmark |

Interactive API documentation is available locally at the address below. It is switched off on Render (set `ENABLE_DOCS=true` to turn it on).

```text
http://127.0.0.1:8000/docs
```

---

## 🌐 Deployment

Trailbit is deployed using Render.

The repository includes a `render.yaml` Blueprint configuration.

### Deployment configuration

- Runtime: Python
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
- Health check: `/health` (`/ready` also checks the database)
- Python version: pinned to 3.12 by `.python-version`
- Optional environment variables: `GITHUB_TOKEN`, `TINYFISH_API_KEY`, `DATA_DIR` (see `render.yaml`)

Live deployment: https://trailbit.onrender.com

**Important:** The Render Free instance does not include a persistent disk. SQLite bookmarks may be lost after a restart or redeployment. Persistent bookmark storage requires an appropriately configured persistent disk.

---

## 🛡️ Safeguards

- **Bookmarks are per visitor.** An httpOnly cookie identifies your browser, and the server stores what GitHub says about the issue, never what the browser sends.
- **GitHub's quota is protected.** Results are cached, an expired result is still served if GitHub fails, searches are budgeted per minute, and each visitor and the site as a whole are rate limited.
- **No third parties in the browser.** Scripts, styles and fonts are served from this site, so a strict Content-Security-Policy applies.
- **Honest freshness.** Search results show when GitHub last touched an issue (bots and labels count); the health check reads the real last comment.

---

## 🔮 Future Improvements

- More advanced issue recommendations based on developer skills.
- Better repository difficulty analysis.
- Personalized contribution roadmaps.
- Additional programming languages and topic filters.
- Improved contribution progress tracking.
- More detailed repository insights.

---

## 🤝 Contributing

Contributions, suggestions and feedback are welcome!

1. Fork this repository.
2. Create a new branch.

```bash
git checkout -b feature/your-feature
```

3. Make your changes.
4. Commit your changes.

```bash
git commit -m "Add: your feature"
```

5. Push your branch.

```bash
git push origin feature/your-feature
```

6. Open a Pull Request.

---

## 👨‍💻 Built With

Trailbit was built as a project for the **Swim with TinyFish: Scaler School of Technology Hackathon**.

Created with the goal of making open-source contribution more accessible to beginners.

**Repository:** https://github.com/bhuvanm0981-ctrl/trailbit_maximum

**Live Demo:** https://trailbit.onrender.com

---

## License

Trailbit is licensed under the **Apache License 2.0**.

You are free to use, modify, and distribute this project under the terms of the license.

See the [LICENSE](LICENSE) file for details.
<p align="center">
  <b>🌱 Your first open-source contribution starts here.</b>
  <br>
  <i>Discover. Understand. Contribute.</i>
</p>

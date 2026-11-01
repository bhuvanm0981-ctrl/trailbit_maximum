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
| 🧰 Language Filters | Explore issues across Python, JavaScript, TypeScript, Go and Rust. |
| 🏷️ Topic Filters | Narrow down issues by topics such as testing, documentation, UI and bugs. |
| 🔎 Issue Verification | Examine issue status, activity, comments, assignees and repository information. |
| 📊 Issue Health | Generate an issue health score and explanatory badges. |
| 🗺️ Contribution Roadmap | Get a structured, beginner-friendly contribution checklist. |
| ⭐ Bookmarks | Save interesting issues and revisit them later. |

---

## 🔄 How Trailbit Works

1. **Discover:** Browse beginner-friendly GitHub issues using language and topic filters.
2. **Explore:** Select an issue that matches your interests and skills.
3. **Verify:** Check its current status, activity and issue health information.
4. **Plan:** Generate a contribution checklist with repository context and relevant guidelines.
5. **Save:** Bookmark issues you want to work on later.

---

## 🛠️ Tech Stack

### Frontend
- HTML5
- CSS3
- JavaScript

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

---

## 🏗️ Architecture

```text
Trailbit
│
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
│
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   │   ├── request.py
│   │   └── response.py
│   │
│   ├── routes/
│   │   ├── discover.py
│   │   ├── verify.py
│   │   ├── contribution_plan.py
│   │   └── bookmarks.py
│   │
│   ├── services/
│   │   └── tinyfish.py
│   │
│   └── utils.py
│
├── .env.example
├── .gitignore
├── requirements.txt
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

### 5. Configure environment variables

Create a `.env` file in the project root.

```env
GITHUB_TOKEN=your_github_token
```

A GitHub token is optional, but recommended to increase API rate limits. A token without additional repository scopes is sufficient for the public repository data used by Trailbit.

Never commit your actual token to GitHub.

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

---

## 🔌 API Endpoints

Trailbit exposes its backend functionality through FastAPI.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Check server health |
| GET | `/api/issues` | Discover GitHub issues |
| GET | `/api/facets` | Get available filters |
| POST | `/api/verify` | Verify an issue |
| POST | `/api/plan` | Generate a contribution plan |
| POST | `/api/bookmarks` | Save an issue |
| GET | `/api/bookmarks` | Retrieve saved issues |
| DELETE | `/api/bookmarks/{issue_id}` | Remove a bookmark |

Interactive API documentation is available at:

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
- Health check: `/health`

Live deployment: https://trailbit.onrender.com

**Important:** The Render Free instance does not include a persistent disk. SQLite bookmarks may be lost after a restart or redeployment. Persistent bookmark storage requires an appropriately configured persistent disk.

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

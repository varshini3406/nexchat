# NexChat 💬

A real-time messaging web app built with **Python (FastAPI)** + **WebSockets** + **SQLite**.

## Features
- 📧 Email-based login & registration
- ⚡ Real-time messaging via WebSockets
- 🗑️ True message delete — no "this message was deleted" trace
- 🎨 Dark, modern UI (not WhatsApp)
- 🔐 JWT authentication

## Tech Stack
| Layer | Tech |
|-------|------|
| Backend | Python, FastAPI |
| Real-time | WebSockets |
| Database | SQLite |
| Auth | JWT (PyJWT) |
| Frontend | HTML/CSS/JS (single-file, no framework) |
| Deploy | Railway / Render |

---

## Run Locally

```bash
# 1. Clone / download this folder
cd chatapp

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start the server
uvicorn main:app --reload --port 8000

# 4. Open http://localhost:8000
```

---

## Deploy on Railway (Recommended — Free tier, public URL)

1. **Create account** at [railway.app](https://railway.app)
2. **New Project → Deploy from GitHub repo**
   - Push this folder to a GitHub repo first, or use Railway CLI
3. Railway auto-detects the `Procfile` and starts your app
4. Click **"Generate Domain"** in Settings → you get a public HTTPS URL!
5. Set environment variable: `SECRET_KEY` = any long random string

### Using Railway CLI (fastest):
```bash
npm install -g @railway/cli
railway login
railway init
railway up
railway domain   # get your public URL
```

---

## Deploy on Render (Alternative — also free)

1. Go to [render.com](https://render.com) → New Web Service
2. Connect your GitHub repo
3. Settings:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add env var: `SECRET_KEY` = random string
5. Deploy → you get a `.onrender.com` URL

---

## Project Structure

```
chatapp/
├── main.py            # FastAPI backend (API + WebSocket)
├── templates/
│   └── index.html     # Full frontend (auth + chat UI)
├── requirements.txt
├── Procfile           # For Railway/Heroku deployment
└── README.md
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/register` | Create account |
| POST | `/api/login` | Login, get JWT |
| GET | `/api/conversations` | List your conversations |
| POST | `/api/conversations` | Start new conversation |
| GET | `/api/conversations/{id}/messages` | Load messages |
| DELETE | `/api/messages/{id}` | Delete your message (true delete) |
| WS | `/ws/{token}` | Real-time connection |

---

Built by [Your Name] · Python + FastAPI + WebSockets

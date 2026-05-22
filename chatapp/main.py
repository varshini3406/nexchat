from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from typing import Optional
import sqlite3, hashlib, jwt, json, uuid, asyncio
from datetime import datetime, timedelta
import os

app = FastAPI(title="NexChat API")
SECRET_KEY = os.environ.get("SECRET_KEY", "nexchat-secret-key-change-in-prod")
ALGORITHM = "HS256"

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─── Database ──────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect("chat.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            username TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            avatar_color TEXT DEFAULT '#6C63FF',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS conversation_members (
            conversation_id TEXT,
            user_id TEXT,
            PRIMARY KEY (conversation_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            sender_id TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (sender_id) REFERENCES users(id)
        );
    """)
    db.commit()
    db.close()

init_db()

# ─── Auth helpers ──────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def create_token(user_id: str) -> str:
    payload = {"sub": user_id, "exp": datetime.utcnow() + timedelta(days=7)}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except:
        return None

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    user_id = verify_token(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    db.close()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return dict(user)

# ─── Pydantic models ───────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str
    username: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class SendMessageRequest(BaseModel):
    conversation_id: str
    content: str

class StartConversationRequest(BaseModel):
    email: str  # email of the other person

# ─── WebSocket Manager ─────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = {}  # user_id -> [ws]

    async def connect(self, user_id: str, ws: WebSocket):
        await ws.accept()
        self.connections.setdefault(user_id, []).append(ws)

    def disconnect(self, user_id: str, ws: WebSocket):
        if user_id in self.connections:
            self.connections[user_id].remove(ws)
            if not self.connections[user_id]:
                del self.connections[user_id]

    async def send_to_user(self, user_id: str, data: dict):
        for ws in self.connections.get(user_id, []):
            try:
                await ws.send_json(data)
            except:
                pass

manager = ConnectionManager()

# ─── Auth Routes ───────────────────────────────────────────────────────────────

AVATAR_COLORS = ["#6C63FF", "#FF6584", "#43B97F", "#F7A440", "#4ECDC4", "#FF6B6B", "#A29BFE"]

@app.post("/api/register")
def register(req: RegisterRequest):
    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE email = ?", (req.email,)).fetchone()
    if existing:
        db.close()
        raise HTTPException(status_code=400, detail="Email already registered")
    uid = str(uuid.uuid4())
    color = AVATAR_COLORS[hash(req.email) % len(AVATAR_COLORS)]
    db.execute(
        "INSERT INTO users (id, email, username, password_hash, avatar_color) VALUES (?, ?, ?, ?, ?)",
        (uid, req.email.lower(), req.username, hash_password(req.password), color)
    )
    db.commit()
    db.close()
    return {"token": create_token(uid), "user_id": uid, "username": req.username, "email": req.email.lower()}

@app.post("/api/login")
def login(req: LoginRequest):
    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE email = ? AND password_hash = ?",
        (req.email.lower(), hash_password(req.password))
    ).fetchone()
    db.close()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    user = dict(user)
    return {"token": create_token(user["id"]), "user_id": user["id"], "username": user["username"], "email": user["email"]}

@app.get("/api/me")
def me(current_user=Depends(get_current_user)):
    return {k: current_user[k] for k in ["id", "email", "username", "avatar_color"]}

# ─── Conversation Routes ────────────────────────────────────────────────────────

@app.post("/api/conversations")
def start_conversation(req: StartConversationRequest, current_user=Depends(get_current_user)):
    db = get_db()
    other = db.execute("SELECT * FROM users WHERE email = ?", (req.email.lower(),)).fetchone()
    if not other:
        db.close()
        raise HTTPException(status_code=404, detail="User not found")
    other = dict(other)
    if other["id"] == current_user["id"]:
        db.close()
        raise HTTPException(status_code=400, detail="Can't message yourself")

    # Check if conversation already exists
    existing = db.execute("""
        SELECT cm1.conversation_id FROM conversation_members cm1
        JOIN conversation_members cm2 ON cm1.conversation_id = cm2.conversation_id
        WHERE cm1.user_id = ? AND cm2.user_id = ?
    """, (current_user["id"], other["id"])).fetchone()

    if existing:
        db.close()
        return {"conversation_id": existing["conversation_id"], "other_user": other}

    cid = str(uuid.uuid4())
    db.execute("INSERT INTO conversations (id) VALUES (?)", (cid,))
    db.execute("INSERT INTO conversation_members VALUES (?, ?)", (cid, current_user["id"]))
    db.execute("INSERT INTO conversation_members VALUES (?, ?)", (cid, other["id"]))
    db.commit()
    db.close()
    return {"conversation_id": cid, "other_user": other}

@app.get("/api/conversations")
def list_conversations(current_user=Depends(get_current_user)):
    db = get_db()
    rows = db.execute("""
        SELECT c.id, u.username, u.email, u.avatar_color,
               (SELECT content FROM messages WHERE conversation_id = c.id ORDER BY created_at DESC LIMIT 1) as last_msg,
               (SELECT created_at FROM messages WHERE conversation_id = c.id ORDER BY created_at DESC LIMIT 1) as last_time
        FROM conversations c
        JOIN conversation_members cm ON c.id = cm.conversation_id
        JOIN conversation_members cm2 ON c.id = cm2.conversation_id AND cm2.user_id != cm.user_id
        JOIN users u ON cm2.user_id = u.id
        WHERE cm.user_id = ?
        ORDER BY last_time DESC
    """, (current_user["id"],)).fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.get("/api/conversations/{conv_id}/messages")
def get_messages(conv_id: str, current_user=Depends(get_current_user)):
    db = get_db()
    # Verify membership
    member = db.execute(
        "SELECT 1 FROM conversation_members WHERE conversation_id = ? AND user_id = ?",
        (conv_id, current_user["id"])
    ).fetchone()
    if not member:
        db.close()
        raise HTTPException(status_code=403, detail="Not a member")
    msgs = db.execute("""
        SELECT m.id, m.content, m.created_at, m.sender_id,
               u.username as sender_name, u.avatar_color
        FROM messages m JOIN users u ON m.sender_id = u.id
        WHERE m.conversation_id = ?
        ORDER BY m.created_at ASC
    """, (conv_id,)).fetchall()
    db.close()
    return [dict(m) for m in msgs]

@app.delete("/api/messages/{msg_id}")
async def delete_message(msg_id: str, current_user=Depends(get_current_user)):
    db = get_db()
    msg = db.execute("SELECT * FROM messages WHERE id = ? AND sender_id = ?",
                     (msg_id, current_user["id"])).fetchone()
    if not msg:
        db.close()
        raise HTTPException(status_code=404, detail="Message not found or not yours")
    msg = dict(msg)
    conv_id = msg["conversation_id"]

    # Get all members to notify
    members = db.execute(
        "SELECT user_id FROM conversation_members WHERE conversation_id = ?", (conv_id,)
    ).fetchall()

    db.execute("DELETE FROM messages WHERE id = ?", (msg_id,))
    db.commit()
    db.close()

    # Notify all members in real-time — true delete, no trace
    for m in members:
        await manager.send_to_user(m["user_id"], {
            "type": "message_deleted",
            "message_id": msg_id,
            "conversation_id": conv_id
        })

    return {"ok": True}

# ─── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str):
    user_id = verify_token(token)
    if not user_id:
        await websocket.close(code=4001)
        return

    await manager.connect(user_id, websocket)
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    db.close()
    if not user:
        await websocket.close(code=4001)
        return
    user = dict(user)

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "send_message":
                conv_id = data.get("conversation_id")
                content = data.get("content", "").strip()
                if not conv_id or not content:
                    continue

                # Verify membership
                db = get_db()
                member = db.execute(
                    "SELECT 1 FROM conversation_members WHERE conversation_id = ? AND user_id = ?",
                    (conv_id, user_id)
                ).fetchone()
                if not member:
                    db.close()
                    continue

                msg_id = str(uuid.uuid4())
                now = datetime.utcnow().isoformat()
                db.execute(
                    "INSERT INTO messages (id, conversation_id, sender_id, content, created_at) VALUES (?, ?, ?, ?, ?)",
                    (msg_id, conv_id, user_id, content, now)
                )
                db.commit()

                members = db.execute(
                    "SELECT user_id FROM conversation_members WHERE conversation_id = ?", (conv_id,)
                ).fetchall()
                db.close()

                msg_payload = {
                    "type": "new_message",
                    "message": {
                        "id": msg_id,
                        "conversation_id": conv_id,
                        "sender_id": user_id,
                        "sender_name": user["username"],
                        "avatar_color": user["avatar_color"],
                        "content": content,
                        "created_at": now
                    }
                }
                for m in members:
                    await manager.send_to_user(m["user_id"], msg_payload)

    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)

# ─── Serve frontend ────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    with open("templates/index.html") as f:
        return f.read()

@app.get("/health")
def health():
    return {"status": "ok"}

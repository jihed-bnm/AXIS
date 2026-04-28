# ERP AI Agent

A natural language interface for ERP/CRM operations powered by LangChain agents.

## Quick Start

### 1. Setup environment
```bash
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

### 2. Start with Docker
```bash
docker-compose up --build
```

### 3. Seed the database with fake data
```bash
docker-compose exec api python -m backend.seed.seed_jbm
```

### 4. Open the frontend
Open `frontend/index.html` in your browser (or serve with `python -m http.server 3000` inside the frontend folder).

### 5. Try it out
- "What's the total sales this month?"
- "Show me all companies in the Technology sector"
- "Add a new company called Acme Corp in Alger"
- "Create a deal with Sonatrach worth 2,000,000 TND"

---

## Running without Docker (local dev)

```bash
# Install Python dependencies
pip install -r requirements.txt

# Start PostgreSQL locally (or update DATABASE_URL in .env)
# Then run:
uvicorn backend.main:app --reload

# Seed data
python -m backend.seed.seed_jbm
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /chat | Send a message to the agent |
| GET | /session/{id}/history | Get conversation history |
| DELETE | /session/{id} | Clear a session |
| GET | /health | Health check |

## Architecture

```
User → Chat UI → FastAPI → LangChain Agent → CRM Tools → PostgreSQL
```

See the architecture document for full details.

## Default Logins (after seeding)

| Username | Password | Role |
|----------|----------|------|
| admin | admin123 | Admin |
| manager1 | pass123 | Manager |
| agent1 | pass123 | Agent |

# miam — your personal food intelligence app

A food recommendation system powered by RAG (Retrieval-Augmented Generation), combining personal taste profiles with recipe knowledge graphs.

## Stack

- **Frontend:** React + Vite + TypeScript + Tailwind (Vercel)
- **Backend:** FastAPI + Python (Railway)
- **Database:** Supabase (PostgreSQL + pgvector)
- **AI:** Mistral AI (query understanding, recipe generation, profile compilation)

## Local Development

### Prerequisites
- Node.js 20+
- Python 3.11+
- A Supabase project (free tier works)
- A Mistral AI API key

### Setup

1. Clone and install:
   ```bash
   git clone https://github.com/pjpauwelyn/miam.git
   cd miam
   npm install                          # frontend deps
   cd backend && pip install -r requirements.txt  # backend deps
   ```

2. Configure environment:
   ```bash
   cp .env.example .env                 # frontend env
   cp backend/.env.example backend/.env # backend env
   # Fill in your API keys and Supabase credentials
   ```

3. Run:
   ```bash
   # Terminal 1 — frontend
   npm run dev

   # Terminal 2 — backend
   cd backend && uvicorn main:app --reload
   ```

4. Open http://localhost:5173

### Git LFS
Recipe data files use Git LFS. After cloning:
```bash
git lfs pull
```

## Architecture

```
frontend/          React SPA (Vercel)
  ├── src/pages/   Login, Onboarding, Chat, Discover, Library, Create
  ├── src/lib/     API client, Supabase client, scoring engine
  └── src/components/  Shared UI components

backend/           FastAPI API (Railway)
  ├── routes/      API endpoints
  ├── services/    Business logic + RAG pipeline
  │   ├── pipeline/  6-stage eat-in pipeline
  │   └── adapters/  Data source adapters
  ├── models/      Pydantic schemas
  ├── db/          Database connection
  └── data/        Recipe datasets
```

## Environment Variables

See `.env.example` and `backend/.env.example` for all variables with descriptions.

## Deployment

- Frontend auto-deploys to Vercel on push to `main`
- Backend auto-deploys to Railway on push to `main`

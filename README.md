# Lexon - Legal Knowledge Graph Platform

This is a [Next.js](https://nextjs.org) project with AI-powered legal document search and analysis.

## 🚀 Quick Start

### Frontend (Next.js)
```bash
npm install
npm run dev
```

### Backend (FastAPI)
```bash
cd ai-backend
poetry install
poetry run uvicorn app.main:app --reload
```

## 🔧 Configuration

### Required Environment Variables

**Frontend (.env.local):**
```env
JWT_SECRET="your-secure-jwt-secret"
AI_BACKEND_URL="https://your-backend.fly.dev"
NEXTAUTH_SECRET="your-nextauth-secret"
FASTAPI_API_KEY="your-api-key"
# Comma/semicolon/newline-separated list of emails that can access admin pages/routes
NEXT_PUBLIC_ADMIN_EMAILS="admin1@example.com,admin2@example.com"
# Legacy single-admin setting (still supported, but prefer NEXT_PUBLIC_ADMIN_EMAILS)
# NEXT_PUBLIC_ADMIN_EMAIL="admin1@example.com"
```

**Backend (.env):**
```env
JWT_SECRET="your-secure-jwt-secret"  # Must match frontend
FASTAPI_API_KEY="your-api-key"
REDIS_URL="redis://localhost:6379"
NEO4J_URI="bolt://localhost:7687"
OPENAI_API_KEY="your-openai-key"
```

## 📡 Streaming Architecture

This project uses a secure JWT-based streaming system with Redis job queue that bypasses Vercel's 60-second timeout limitations:

- **Redis Queue (RQ)** for background job processing
- **Direct backend connections** for unlimited streaming duration  
- **JWT token authentication** for secure streaming access
- **Redis pub/sub** for real-time progress updates
- **No exposed credentials** in the frontend

See [SETUP_STREAMING.md](./SETUP_STREAMING.md) for setup instructions and [ARCHITECTURE.md](./ARCHITECTURE.md) for detailed system design.

## 🏗️ Architecture

- **Frontend**: Next.js with TypeScript, Tailwind CSS
- **Backend**: FastAPI with CrewAI agents
- **Database**: Neo4j knowledge graph + PostgreSQL
- **Queue**: Redis with RQ for background jobs
- **Authentication**: NextAuth.js with JWT tokens
- **Deployment**: Vercel (frontend) + Fly.io (backend)

## 📚 Learn More

- [Next.js Documentation](https://nextjs.org/docs)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [CrewAI Documentation](https://docs.crewai.com/)
- [Neo4j Documentation](https://neo4j.com/docs/)

## 🚀 Deploy

### Frontend (Vercel)
The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new).

### Backend (Fly.io)
```bash
cd ai-backend
fly deploy
```

Note: Fly.io will automatically detect and use your `pyproject.toml` for Poetry projects.

Make sure to set the required environment variables in both platforms.

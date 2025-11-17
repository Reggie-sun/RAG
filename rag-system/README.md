# RAG System Deployment

## Prerequisites
- Node.js 20+
- npm 9+
- Docker 24+
- Python 3.11+ (optional for local development)

## Build Frontend Assets
```bash
cd rag-system
npm install
npm run build
```
The compiled frontend files are written to `frontend/dist/`.

## Run Locally Without Docker
```bash
cd rag-system
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

## Docker Build & Run
```bash
cd rag-system
docker build -f backend/Dockerfile -t rag-system .
docker run -p 8000:8000 rag-system
```

## Environment Variables
Create a `.env` file in the repository root or alongside the Docker container with:
```
OPENAI_API_KEY=your-openai-key
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_CHAT_MODEL=gpt-4o-mini
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5-coder:14b
```

## API Endpoints
- `POST /api/upload`
- `POST /api/search`
- `GET /api/stream`
- `GET /api/status`
- `GET /api/health`

The FastAPI app serves the built frontend at the root path `/` after `npm run build` has produced `frontend/dist/`.

# High-Level Architecture Diagram

## Entities to Draw
1. **Client / User** (Actor icon)
2. **FastAPI Application** (API Server icon)
3. **Redis** (In-memory datastore icon)
4. **Celery Worker** (Gear / Worker icon)
5. **PostgreSQL** (Database icon)
6. **Gemini LLM** (AI / Brain icon)

## Flow & Connections
1. **Client ➔ FastAPI App**: `POST /jobs/upload` (Uploads CSV)
2. **FastAPI App ➔ PostgreSQL**: Creates `Job` record (Status: pending)
3. **FastAPI App ➔ Redis**: Enqueues background task with `job_id`
4. **FastAPI App ➔ Client**: Returns `job_id` instantly
5. **Celery Worker ➔ Redis**: Dequeues the job task
6. **Celery Worker ➔ PostgreSQL**: Updates Job to `processing`
7. **Celery Worker ➔ Celery Worker**: Data cleaning & Anomaly detection
8. **Celery Worker ➔ Gemini LLM**: Sends uncategorized transactions (Batch)
9. **Gemini LLM ➔ Celery Worker**: Returns Categories
10. **Celery Worker ➔ Gemini LLM**: Sends aggregated stats
11. **Gemini LLM ➔ Celery Worker**: Returns Narrative & Risk level
12. **Celery Worker ➔ PostgreSQL**: Saves all `Transactions`, `JobSummary` and sets Job to `completed`
13. **Client ➔ FastAPI App**: `GET /jobs/{job_id}/results` (Polling)
14. **FastAPI App ➔ PostgreSQL**: Fetches results
15. **FastAPI App ➔ Client**: Returns final structured JSON

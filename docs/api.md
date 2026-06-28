# API Documentation & Testing Guide

This guide explains how to properly test the API endpoints using tools like `curl`, Postman, or Thunder Client.

## Prerequisites
Ensure the docker containers are running (`docker compose up -d`). The API is accessible at `http://localhost:8000`.
A dummy file `transactions.csv` is provided in the root directory for testing.

---

### 1. Upload a CSV File
Uploads the transactions and enqueues the processing job.

**Endpoint**: `POST /jobs/upload`

**Curl Command**:
```bash
curl -X 'POST' \
  'http://localhost:8000/jobs/upload' \
  -H 'accept: application/json' \
  -H 'Content-Type: multipart/form-data' \
  -F 'file=@transactions.csv'
```

**Expected Response**:
```json
{
  "job_id": "0eedf371-79c2-49a7-96da-6d5efc41cdb2",
  "status": "pending"
}
```
*(Copy the `job_id` from the response to use in the next steps)*

---

### 2. Check Job Status
Poll this endpoint to check if the job has finished processing.

**Endpoint**: `GET /jobs/{job_id}/status`

**Curl Command** (Replace `<your_job_id>` with the ID from step 1):
```bash
curl -X 'GET' \
  'http://localhost:8000/jobs/<your_job_id>/status' \
  -H 'accept: application/json'
```

**Expected Responses**:
- When still running: `{"job_id": "...", "status": "processing", "summary": null}`
- When done: `{"job_id": "...", "status": "completed", "summary": {...}}`

---

### 3. Fetch Full Job Results
Once the status is `completed`, use this endpoint to fetch the cleaned transactions, identified anomalies, and the LLM narrative.

**Endpoint**: `GET /jobs/{job_id}/results`

**Curl Command**:
```bash
curl -X 'GET' \
  'http://localhost:8000/jobs/<your_job_id>/results' \
  -H 'accept: application/json'
```

**Expected Response**:
A large JSON object containing:
- `transactions`: The list of all cleaned and LLM-categorized transactions.
- `anomalies`: Transactions flagged for violating rules.
- `spend_by_category`: Aggregated totals for each category.
- `summary`: The LLM-generated narrative and risk level.

---

### 4. List All Jobs
Useful to see a history of all uploaded files and their current status.

**Endpoint**: `GET /jobs`
*(Optional Query Param: `?status=completed` or `?status=failed`)*

**Curl Command**:
```bash
curl -X 'GET' \
  'http://localhost:8000/jobs?status=completed' \
  -H 'accept: application/json'
```

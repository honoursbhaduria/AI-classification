import os
import uuid
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from .database import engine, Base, get_db
from . import models, schemas
from .worker import process_csv_job
from typing import List, Optional
import json

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI-Powered Transaction Processing Pipeline")

UPLOAD_DIR = "/tmp/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/jobs/upload", response_model=schemas.JobResponse)
async def upload_job(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed")
    
    job_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{job_id}.csv")
    
    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
        
    job = models.Job(
        id=job_id,
        filename=file.filename,
        status="pending"
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    
    process_csv_job.delay(job_id, file_path)
    
    return {"job_id": job_id, "status": "pending"}


@app.get("/jobs/{job_id}/status", response_model=schemas.JobStatusResponse)
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    response = {"job_id": job_id, "status": job.status}
    
    if job.status == "completed":
        summary = db.query(models.JobSummary).filter(models.JobSummary.job_id == job_id).first()
        if summary:
            response["summary"] = {
                "total_spend_inr": summary.total_spend_inr,
                "total_spend_usd": summary.total_spend_usd,
                "top_merchants": json.loads(summary.top_merchants) if summary.top_merchants else [],
                "anomaly_count": summary.anomaly_count,
                "narrative": summary.narrative,
                "risk_level": summary.risk_level
            }
            
    return response

@app.get("/jobs/{job_id}/results", response_model=schemas.JobResultResponse)
def get_job_results(job_id: str, db: Session = Depends(get_db)):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    if job.status != "completed":
        raise HTTPException(status_code=400, detail=f"Job is {job.status}, not completed yet.")
        
    transactions = db.query(models.Transaction).filter(models.Transaction.job_id == job_id).all()
    
    anomalies = [t for t in transactions if t.is_anomaly]
    
    spend_by_category = {}
    for t in transactions:
        cat = t.category or "Uncategorised"
        spend_by_category[cat] = spend_by_category.get(cat, 0) + (t.amount or 0)
        
    summary = db.query(models.JobSummary).filter(models.JobSummary.job_id == job_id).first()
    summary_dict = None
    if summary:
        summary_dict = {
            "narrative": summary.narrative,
            "risk_level": summary.risk_level,
            "total_spend_inr": summary.total_spend_inr,
            "total_spend_usd": summary.total_spend_usd,
            "anomaly_count": summary.anomaly_count
        }
        
    return {
        "job_id": job_id,
        "status": job.status,
        "transactions": transactions,
        "anomalies": anomalies,
        "spend_by_category": spend_by_category,
        "summary": summary_dict
    }

@app.get("/jobs", response_model=List[schemas.JobListResponse])
def list_jobs(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.Job)
    if status:
        query = query.filter(models.Job.status == status)
    return query.all()

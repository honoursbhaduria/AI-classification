from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class JobBase(BaseModel):
    filename: str

class JobResponse(BaseModel):
    job_id: str
    status: str

class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    summary: Optional[dict] = None

class TransactionSchema(BaseModel):
    txn_id: Optional[str]
    date: Optional[str]
    merchant: Optional[str]
    amount: Optional[float]
    currency: Optional[str]
    status: Optional[str]
    category: Optional[str]
    account_id: Optional[str]
    is_anomaly: Optional[bool]
    anomaly_reason: Optional[str]
    llm_category: Optional[str]

    class Config:
        from_attributes = True

class JobResultResponse(BaseModel):
    job_id: str
    status: str
    transactions: List[TransactionSchema]
    anomalies: List[TransactionSchema]
    spend_by_category: dict
    summary: Optional[dict]

class JobListResponse(BaseModel):
    id: str
    status: str
    filename: str
    row_count_raw: int
    created_at: datetime

    class Config:
        from_attributes = True

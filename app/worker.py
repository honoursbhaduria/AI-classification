import os
import json
import pandas as pd
import numpy as np
from datetime import datetime
from celery import Celery
from google import genai
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
import time
from .config import settings
from .models import Job, Transaction, JobSummary

celery_app = Celery("worker", broker=settings.REDIS_URL, backend=settings.REDIS_URL)

engine = create_engine(settings.DATABASE_URL)

client = genai.Client(api_key=settings.GEMINI_API_KEY)

DOMESTIC_MERCHANTS = ['swiggy', 'ola', 'irctc', 'zomato', 'flipkart']

def safe_float(val):
    try:
        if pd.isna(val):
            return 0.0
        val_str = str(val).replace('$', '').replace(',', '').strip()
        return float(val_str)
    except:
        return 0.0

def process_date(d):
    if pd.isna(d):
        return None
    d_str = str(d).strip()
    try:
        if '-' in d_str:
            return pd.to_datetime(d_str, format='%d-%m-%Y').strftime('%Y-%m-%dT%H:%M:%SZ')
        elif '/' in d_str:
            return pd.to_datetime(d_str, format='%Y/%m/%d').strftime('%Y-%m-%dT%H:%M:%SZ')
    except:
        pass
    try:
        return pd.to_datetime(d_str).strftime('%Y-%m-%dT%H:%M:%SZ')
    except:
        return d_str

def call_llm_with_retry(prompt, max_retries=3):
    for attempt in range(max_retries):
        try:
            interaction = client.interactions.create(
                model="gemini-3.5-flash",
                input=prompt
            )
            return interaction.output_text
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"LLM call failed after {max_retries} attempts: {e}")
                return None
            time.sleep(2 ** attempt)
    return None

@celery_app.task(bind=True, name="process_csv_job")
def process_csv_job(self, job_id, file_path):
    with Session(engine) as session:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            return
        
        try:
            job.status = "processing"
            session.commit()
            
            # Read CSV
            df = pd.read_csv(file_path)
            job.row_count_raw = len(df)
            
            # Data Cleaning
            df = df.dropna(how='all')
            df = df.drop_duplicates()
            
            job.row_count_clean = len(df)
            
            df['amount_clean'] = df['amount'].apply(safe_float)
            df['date_clean'] = df['date'].apply(process_date)
            df['currency'] = df['currency'].astype(str).str.upper().str.strip()
            # Handle nan string
            df['currency'] = df['currency'].replace('NAN', 'UNKNOWN')
            df['status'] = df['status'].astype(str).str.upper().str.strip()
            df['category'] = df['category'].fillna('Uncategorised')
            # Handle explicit nan string
            df.loc[df['category'].astype(str).str.upper() == 'NAN', 'category'] = 'Uncategorised'
            df['merchant'] = df['merchant'].astype(str).str.strip()
            df['account_id'] = df['account_id'].astype(str).str.strip()
            
            # Anomaly Detection
            account_medians = df.groupby('account_id')['amount_clean'].median().to_dict()
            
            transactions = []
            
            for index, row in df.iterrows():
                account_id = row['account_id']
                amount = row['amount_clean']
                currency = row['currency']
                merchant_lower = row['merchant'].lower() if pd.notna(row['merchant']) and row['merchant'].lower() != 'nan' else ""
                
                is_anomaly = False
                reasons = []
                
                median = account_medians.get(account_id, 0)
                if median > 0 and amount > 3 * median:
                    is_anomaly = True
                    reasons.append("Amount exceeds 3x account median")
                    
                if currency == 'USD' and any(dm in merchant_lower for dm in DOMESTIC_MERCHANTS):
                    is_anomaly = True
                    reasons.append("USD used for domestic merchant")
                    
                anomaly_reason = "; ".join(reasons) if is_anomaly else None
                
                txn = Transaction(
                    job_id=job_id,
                    txn_id=str(row['txn_id']) if pd.notna(row['txn_id']) and str(row['txn_id']).lower() != 'nan' else None,
                    date=row['date_clean'],
                    merchant=row['merchant'] if row['merchant'].lower() != 'nan' else None,
                    amount=amount,
                    currency=currency,
                    status=row['status'],
                    category=row['category'],
                    account_id=account_id if account_id.lower() != 'nan' else None,
                    is_anomaly=is_anomaly,
                    anomaly_reason=anomaly_reason
                )
                transactions.append(txn)
                
            session.add_all(transactions)
            session.commit()
            
            # LLM Classification
            uncategorised_txns = session.query(Transaction).filter(
                Transaction.job_id == job_id,
                Transaction.category.in_(['Uncategorised'])
            ).all()
            
            if uncategorised_txns and settings.GEMINI_API_KEY:
                batch_size = 20
                for i in range(0, len(uncategorised_txns), batch_size):
                    batch = uncategorised_txns[i:i+batch_size]
                    
                    prompt = "Classify the following transactions into exactly one of these categories: Food, Shopping, Travel, Transport, Utilities, Cash Withdrawal, Entertainment, Other. Return ONLY a JSON list of strings representing the categories in the exact same order as the transactions provided.\n\nTransactions:\n"
                    for t in batch:
                        prompt += f"- Merchant: {t.merchant}, Amount: {t.amount}, Currency: {t.currency}, Notes: {t.txn_id}\n"
                        
                    llm_resp = call_llm_with_retry(prompt)
                    
                    if llm_resp:
                        try:
                            import re
                            json_str = re.search(r'\[.*\]', llm_resp, re.DOTALL)
                            if json_str:
                                categories = json.loads(json_str.group())
                                for idx, t in enumerate(batch):
                                    if idx < len(categories):
                                        t.llm_category = categories[idx]
                                        t.category = categories[idx]
                            else:
                                for t in batch:
                                    t.llm_failed = True
                                    t.llm_raw_response = llm_resp
                        except:
                            for t in batch:
                                t.llm_failed = True
                                t.llm_raw_response = llm_resp
                    else:
                        for t in batch:
                            t.llm_failed = True
                            
                session.commit()
            
            # Generate Summary
            all_txns = session.query(Transaction).filter(Transaction.job_id == job_id).all()
            total_inr = sum(t.amount for t in all_txns if t.currency == 'INR' and t.amount)
            total_usd = sum(t.amount for t in all_txns if t.currency == 'USD' and t.amount)
            anomaly_count = sum(1 for t in all_txns if t.is_anomaly)
            
            merchant_totals = {}
            for t in all_txns:
                if t.merchant:
                    merchant_totals[t.merchant] = merchant_totals.get(t.merchant, 0) + (t.amount or 0)
            
            top_merchants = sorted(merchant_totals.items(), key=lambda x: x[1], reverse=True)[:3]
            top_merchants_dict = [{"merchant": m, "total": a} for m, a in top_merchants]
            
            narrative = ""
            risk_level = "low"
            
            if settings.GEMINI_API_KEY:
                prompt = f"""
                Analyze these transaction stats and provide a JSON summary with:
                - "narrative": A 2-3 sentence spending narrative.
                - "risk_level": "low", "medium", or "high" based on anomaly count relative to total transactions.
                
                Stats:
                - Total INR: {total_inr}
                - Total USD: {total_usd}
                - Anomaly Count: {anomaly_count} / {len(all_txns)} total transactions
                - Top Merchants: {json.dumps(top_merchants_dict)}
                
                Output ONLY valid JSON like {{"narrative": "...", "risk_level": "..."}}
                """
                
                summary_resp = call_llm_with_retry(prompt)
                
                if summary_resp:
                    try:
                        import re
                        json_str = re.search(r'\{.*\}', summary_resp, re.DOTALL)
                        if json_str:
                            summary_data = json.loads(json_str.group())
                            narrative = summary_data.get('narrative', '')
                            risk_level = summary_data.get('risk_level', 'low')
                    except:
                        pass
            else:
                narrative = "LLM API Key not provided, narrative skipped."
                if anomaly_count > len(all_txns) * 0.1:
                    risk_level = "high"
                elif anomaly_count > 0:
                    risk_level = "medium"
            
            job_summary = JobSummary(
                job_id=job_id,
                total_spend_inr=total_inr,
                total_spend_usd=total_usd,
                top_merchants=json.dumps(top_merchants_dict),
                anomaly_count=anomaly_count,
                narrative=narrative,
                risk_level=risk_level
            )
            session.add(job_summary)
            
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            session.commit()
            
        except Exception as e:
            session.rollback()
            job.status = "failed"
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()
            session.commit()
        finally:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass

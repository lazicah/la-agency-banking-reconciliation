"""
main.py — FastAPI Reconciliation Service
Liberty Assured Group

ARCHITECTURE:
1. Make.com sends ONLY bank statement + date range
2. API fetches backend data from the Postgres DB (via VPN)
3. Runs reconciliation
4. Returns AI analysis
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
import pandas as pd
import numpy as np
import uuid
from datetime import datetime
from dateutil.relativedelta import relativedelta
import anthropic
import os
import traceback
import requests
from dotenv import load_dotenv
load_dotenv()


app = FastAPI(
    title="Agency Banking Reconciliation API",
    description="Liberty Assured — Fetches backend from API, receives bank statement from Make",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────
# CONFIG — Set as environment variables in Railway/Render
# ─────────────────────────────────────────────────────────────────

# AI
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Agency Banking Backend API
BACKEND_API_BASE = os.getenv("BACKEND_API_BASE", "")
BACKEND_API_TOKEN = os.getenv("BACKEND_API_KEY", "")


# ─────────────────────────────────────────────────────────────────
# REQUEST/RESPONSE MODELS
# ─────────────────────────────────────────────────────────────────

class ReconcileRequest(BaseModel):
    start_date: str  # "2026-01-01"
    end_date: str  # "2026-01-31"
    bank_data: List[Dict]  # Bank statement from Make.com
    run_ai_analysis: bool = True


class ReconcileResponse(BaseModel):
    run_id: str
    start_date: str
    end_date: str
    status: str
    summary: Dict
    ai_analysis: Optional[str] = None
    backend_count: int
    bank_count: int
    unmatched: Optional[Dict[str, List[Dict]]] = None


# ─────────────────────────────────────────────────────────────────
# FETCH BACKEND DATA FROM BACKEND API
# ─────────────────────────────────────────────────────────────────

BACKEND_TRANSACTION_TYPES = [
    "SEND_BANK_TRANSFER",
    "SEND_LIBERTY_COMMISSION",
    "REVERSAL_BANK_TRANSFER",
    "FUND_BANK_TRANSFER",
    "ELECTRONIC_TRANSFER_LEVY",
]


def get_backend_data_from_api(start_date: str, end_date: str) -> pd.DataFrame:
    """
    Fetches backend transactions via backend API.
    """

    url = f"{BACKEND_API_BASE.rstrip('/')}/agency/transaction-data-for-analyst"
    params = {
        "transaction_type": ",".join(BACKEND_TRANSACTION_TYPES),
        "start_date": start_date,
        "end_date": end_date,
    }
    headers = {"Accept": "application/json"}
    if BACKEND_API_TOKEN:
        headers["X-API-KEY"] = f"{BACKEND_API_TOKEN}"

    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
        transactions = payload.get("transactions", [])
        df = pd.DataFrame(transactions)

        print(f"✅ Fetched {len(df)} backend transactions for {start_date} to {end_date}")
        return df

    except requests.Timeout as e:
        raise HTTPException(
            status_code=504,
            detail=f"Backend API timeout. Check your Internet: {str(e)}"
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Backend API error: {str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=502, detail=f"Backend API invalid JSON: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backend API unexpected error: {str(e)}")


# ─────────────────────────────────────────────────────────────────
# RECONCILIATION ENGINE
# ─────────────────────────────────────────────────────────────────

class ReconciliationEngine:
    
    def __init__(self, backend_df: pd.DataFrame, bank_df: pd.DataFrame):
        self.backend = backend_df.copy()
        self.bank = bank_df.copy()
        self.results = {}
        
    def prepare_backend(self):
        trans = self.backend.copy()
        
        # Dates
        trans['date_created'] = pd.to_datetime(trans.get('date_created'), errors='coerce')
        
        # Commissions & stamp duty
        trans['commissions'] = 0
        trans['stamp_duty'] = 0
        trans.loc[trans['transaction_type'] == 'SEND_LIBERTY_COMMISSION', 'commissions'] = trans['amount']
        trans.loc[trans['transaction_type'] == 'ELECTRONIC_TRANSFER_LEVY', 'stamp_duty'] = trans['amount']
        
        # Normalize identifiers
        mask = trans['transaction_type'].isin(['SEND_BANK_TRANSFER', 'SEND_LIBERTY_COMMISSION'])
        trans.loc[mask, 'ref_1'] = trans.loc[mask, 'unique_reference'].astype(str).str[:9]
        trans.loc[mask, 'ref_2'] = trans.loc[mask, 'unique_reference'].astype(str).str[10:]
        trans['session_id'] = trans.get('session_id', '').fillna('').astype(str)
        trans['transaction_id'] = trans.get('transaction_id', '').fillna('').astype(str)
        trans['escrow_id'] = trans.get('escrow_id', '').fillna('').astype(str)
        
        # Fill NaN
        for col in ['provider_fee', 'commissions', 'stamp_duty', 'balance_before', 'balance_after', 'amount']:
            if col in trans.columns:
                trans[col] = trans[col].fillna(0)
        
        self.backend_prepared = trans
        return trans
    
    def prepare_bank(self):
        bank = self.bank.copy()
        
        # Standardize columns
        bank.columns = bank.columns.str.strip()
        
        # Rename date
        if 'created_date' in bank.columns:
            bank = bank.rename(columns={'created_date': 'transaction_date'})
        elif 'created_at' in bank.columns:
            bank = bank.rename(columns={'created_at': 'transaction_date'})
        
        # Convert dates
        bank['transaction_date'] = pd.to_datetime(bank.get('transaction_date'), errors='coerce')

        # Normalize identifiers
        bank['transaction_id'] = bank.get('transaction_id', '').fillna('').astype(str)
        bank['session_id'] = bank.get('session_id', '').fillna('').astype(str)
        bank['narration'] = bank.get('narration', '').fillna('').astype(str)

        # Extract a fallback transaction id from narration for reversals
        bank['narration_txn_id'] = bank['narration'].str.extract(r"\b([A-Z0-9]{10,})\b", expand=False)
        bank['narration_txn_id'] = bank['narration_txn_id'].fillna('')
        
        # Normalize amounts
        if 'debit' in bank.columns:
            bank['debit'] = pd.to_numeric(bank['debit'], errors='coerce').fillna(0)
        else:
            bank['debit'] = 0
        if 'credit' in bank.columns:
            bank['credit'] = pd.to_numeric(bank['credit'], errors='coerce').fillna(0)
        else:
            bank['credit'] = 0

        # Extract charges & stamp duty
        if 'debit' in bank.columns and 'narration' in bank.columns:
            bank['charges'] = bank['debit'].where(
                bank['narration'].astype(str).str.startswith('CHRG/', na=False), 0
            )
            bank['bank_stamp'] = bank['debit'].where(
                bank['narration'].astype(str).str.startswith('Stamp Duty', na=False), 0
            )
        
        self.bank_prepared = bank
        return bank
    
    def reconcile_send_bank_transfers(self):
        trans = self.backend_prepared
        bank = self.bank_prepared
        
        # Convert to string
        trans['ref_1'] = trans.get('ref_1', '').astype(str)
        trans['ref_2'] = trans.get('ref_2', '').astype(str)
        bank['transaction_id'] = bank.get('transaction_id', '').astype(str)
        
        # Merge ref_1
        m1 = pd.merge(trans, bank, how='left', left_on='ref_1', right_on='transaction_id', suffixes=('', '_bank'))
        
        # Merge ref_2
        m2 = pd.merge(trans, bank, how='left', left_on='ref_2', right_on='transaction_id', suffixes=('', '_bank'))
        
        # Combine
        m1['charges'] = m1.get('charges', 0).replace(0, np.nan)
        m2['charges'] = m2.get('charges', 0).replace(0, np.nan)
        merged = m1.combine_first(m2)
        
        # Filter SEND_BANK_TRANSFER
        send_bank = merged[
            ~merged['transaction_type'].isin([
                'SEND_LIBERTY_COMMISSION', 'REVERSAL_BANK_TRANSFER',
                'FUND_BANK_TRANSFER', 'ELECTRONIC_TRANSFER_LEVY'
            ])
        ].copy()
        
        # Match check
        send_bank['amount'] = pd.to_numeric(send_bank['amount'], errors='coerce')
        send_bank['debit'] = pd.to_numeric(send_bank.get('debit', 0), errors='coerce')
        send_bank['Match_bb'] = np.isclose(send_bank['amount'], send_bank['debit'], equal_nan=False)
        
        matched = send_bank[send_bank['Match_bb'] == True]
        unmatched = send_bank[send_bank['Match_bb'] == False]
        
        self.results['send_bank_matched'] = matched
        self.results['send_bank_unmatched'] = unmatched
        
        return matched, unmatched
    
    def reconcile_reversals(self):
        bank = self.bank_prepared
        reversals = self.backend_prepared[
            self.backend_prepared['transaction_type'] == 'REVERSAL_BANK_TRANSFER'
        ].copy()

        if reversals.empty:
            self.results['reversal_matched'] = pd.DataFrame()
            self.results['reversal_unmatched'] = pd.DataFrame()
            return pd.DataFrame()

        bank_deposits = bank[(bank.get('credit', 0) > 0)].copy()

        # Match by transaction id (bank column or narration fallback)
        bank_deposits['txn_match_id'] = bank_deposits['transaction_id']
        bank_deposits.loc[bank_deposits['txn_match_id'] == '', 'txn_match_id'] = bank_deposits['narration_txn_id']

        reversals['transaction_id'] = reversals.get('transaction_id', '').astype(str)
        merged = bank_deposits.merge(
            reversals,
            how='left',
            left_on='txn_match_id',
            right_on='transaction_id',
            suffixes=('_bank', '')
        )

        merged['match_reversal'] = merged['transaction_id'].ne('')
        matched = merged[merged['match_reversal'] == True]
        unmatched = merged[merged['match_reversal'] == False]

        self.results['reversal_matched'] = matched
        self.results['reversal_unmatched'] = unmatched
        return matched
    
    def reconcile_fund_transfers(self):
        trans = self.backend_prepared
        bank = self.bank_prepared
        
        fund = trans[trans['transaction_type'] == 'FUND_BANK_TRANSFER']
        if fund.empty:
            return pd.DataFrame(), pd.DataFrame()
        
        vfd = fund[fund.get('account_provider', '') == 'VFD'].copy()
        
        bank['session_id'] = bank.get('session_id', '').fillna('')
        vfd['session_id'] = vfd['session_id'].astype(str)
        bank['session_id'] = bank['session_id'].astype(str)
        
        # Prefer highest credit per session id for main transfer
        bank_credits = bank[bank.get('credit', 0) > 0].sort_values(
            by=['session_id', 'credit'], ascending=[True, False]
        ).drop_duplicates(subset=['session_id'], keep='first')
        
        combine = pd.merge(vfd, bank_credits, how='left', on='session_id', suffixes=('', '_bank'))
        
        combine['amount'] = pd.to_numeric(combine['amount'], errors='coerce')
        combine['credit'] = pd.to_numeric(combine.get('credit', 0), errors='coerce')
        combine['match_fb'] = np.isclose(combine['amount'], combine['credit'], equal_nan=False)
        
        matched = combine[combine['match_fb'] == True]
        unmatched = combine[combine['match_fb'] == False]
        
        self.results['fund_matched'] = matched
        self.results['fund_unmatched'] = unmatched
        
        return matched, unmatched

    def reconcile_failed_backend_transfers(self):
        trans = self.backend_prepared
        if trans.empty:
            self.results['failed_backend_matched'] = pd.DataFrame()
            return pd.DataFrame()

        send_no_session = trans[
            (trans['transaction_type'] == 'SEND_BANK_TRANSFER') &
            (trans['session_id'] == '')
        ].copy()

        reversals_no_session = trans[
            (trans['transaction_type'] == 'REVERSAL_BANK_TRANSFER') &
            (trans['session_id'] == '')
        ].copy()

        if send_no_session.empty or reversals_no_session.empty:
            self.results['failed_backend_matched'] = pd.DataFrame()
            return pd.DataFrame()

        mapped = send_no_session.merge(
            reversals_no_session[['escrow_id', 'amount', 'date_created']],
            how='left',
            on='escrow_id',
            suffixes=('', '_reversal')
        )

        self.results['failed_backend_matched'] = mapped
        return mapped
    
    def reconcile_bank_to_backend(self):
        trans = self.backend_prepared
        bank = self.bank_prepared
        
        # Merge ref_1
        bm1 = bank.merge(
            trans[['date_created', 'ref_1', 'ref_2', 'transaction_type', 'amount']],
            how='left', left_on='transaction_id', right_on='ref_1', suffixes=('', '_backend')
        )
        
        # Merge ref_2
        bm2 = bank.merge(
            trans[['date_created', 'ref_1', 'ref_2', 'transaction_type', 'amount']],
            how='left', left_on='transaction_id', right_on='ref_2', suffixes=('', '_backend')
        )
        
        merged = bm1.combine_first(bm2)
        
        merged['match_bt'] = (
            (merged['transaction_id'] == merged.get('ref_1', '')) |
            (merged['transaction_id'] == merged.get('ref_2', ''))
        )
        
        matched = merged[merged['match_bt'] == True]
        unmatched = merged[merged['match_bt'] == False]
        
        self.results['bank_matched'] = matched
        self.results['bank_unmatched'] = unmatched
        
        return matched, unmatched
    
    def run_full_reconciliation(self):
        self.prepare_backend()
        self.prepare_bank()
        self.reconcile_send_bank_transfers()
        self.reconcile_reversals()
        self.reconcile_fund_transfers()
        self.reconcile_failed_backend_transfers()
        self.reconcile_bank_to_backend()
        return self.build_summary()
    
    def build_summary(self):
        send_unmatched_amt = self.results.get('send_bank_unmatched', pd.DataFrame()).get('amount', pd.Series([0])).sum()
        fund_unmatched_amt = self.results.get('fund_unmatched', pd.DataFrame()).get('amount', pd.Series([0])).sum()
        bank_unmatched_amt = self.results.get('bank_unmatched', pd.DataFrame()).get('debit', pd.Series([0])).sum()
        reversal_unmatched_amt = self.results.get('reversal_unmatched', pd.DataFrame()).get('credit', pd.Series([0])).sum()
        
        return {
            'total_backend_transactions': len(self.backend),
            'total_bank_transactions': len(self.bank),
            'send_bank_matched': len(self.results.get('send_bank_matched', [])),
            'send_bank_unmatched': len(self.results.get('send_bank_unmatched', [])),
            'fund_matched': len(self.results.get('fund_matched', [])),
            'fund_unmatched': len(self.results.get('fund_unmatched', [])),
            'bank_to_backend_matched': len(self.results.get('bank_matched', [])),
            'bank_to_backend_unmatched': len(self.results.get('bank_unmatched', [])),
            'total_unmatched_backend_value': float(send_unmatched_amt + fund_unmatched_amt),
            'total_unmatched_bank_value': float(bank_unmatched_amt + reversal_unmatched_amt),
            'reversal_matched': len(self.results.get('reversal_matched', [])),
            'reversal_unmatched': len(self.results.get('reversal_unmatched', [])),
            'failed_backend_mapped': len(self.results.get('failed_backend_matched', []))
        }


# ─────────────────────────────────────────────────────────────────
# AI ANALYZER
# ─────────────────────────────────────────────────────────────────

def analyze_with_ai(engine: ReconciliationEngine, start_date: str, end_date: str) -> str:
    send_unmatched = engine.results.get('send_bank_unmatched', pd.DataFrame())
    fund_unmatched = engine.results.get('fund_unmatched', pd.DataFrame())
    bank_unmatched = engine.results.get('bank_unmatched', pd.DataFrame())
    range_label = f"{start_date} to {end_date}"
    
    prompt = f"""
Analyze bank reconciliation for Liberty Assured Agency Banking ({range_label}):

BACKEND NOT ON BANK:
- SEND_BANK_TRANSFER: {len(send_unmatched)} transactions
{send_unmatched[['transaction_type', 'amount', 'date_created', 'status']].head(10).to_string(index=False) if not send_unmatched.empty else "None"}

- FUND_BANK_TRANSFER: {len(fund_unmatched)} transactions
{fund_unmatched[['transaction_type', 'amount', 'session_id']].head(10).to_string(index=False) if not fund_unmatched.empty else "None"}

BANK NOT IN BACKEND: {len(bank_unmatched)} transactions
{bank_unmatched[['transaction_date', 'narration', 'debit', 'credit']].head(10).to_string(index=False) if not bank_unmatched.empty else "None"}

Provide:
1. Summary by type (counts & amounts in ₦)
2. Why backend→bank gaps exist
3. Why bank→backend gaps exist  
4. Top 3 actions

Keep concise.
"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text
    except Exception as e:
        return f"AI unavailable: {str(e)}"


# ─────────────────────────────────────────────────────────────────
# API ENDPOINTS
# ─────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "service": "Agency Banking Reconciliation API",
        "version": "1.0.0",
        "status": "online",
        "backend_api_configured": bool(BACKEND_API_BASE),
        "ai_configured": bool(ANTHROPIC_API_KEY),
        "endpoints": {
            "POST /reconcile": "Run reconciliation (fetches backend from API)",
            "GET /test-backend": "Test backend API connection",
            "GET /health": "Health check"
        }
    }


@app.get("/test-backend")
async def test_backend():
    """Test backend API connection"""
    try:
        start_date = datetime.now().strftime("%Y-%m-20")
        end_date = datetime.now().strftime("%Y-%m-%d")
        print(f"Testing backend API connection with date range {start_date} to {end_date}...")
        url = f"{BACKEND_API_BASE.rstrip('/')}/agency/transaction-data-for-analyst"
        params = {
            "transaction_type": ",".join(BACKEND_TRANSACTION_TYPES),
            "start_date": start_date,
            "end_date": end_date,
        }
        headers = {"Accept": "application/json"}
        if BACKEND_API_TOKEN:
            headers["X-API-KEY"] = f"{BACKEND_API_TOKEN}"

        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        payload = response.json()
        count = payload.get("count", 0)

        return {
            "status": "connected",
            "backend_api": BACKEND_API_BASE,
            "total_transactions": f"{count:,}"
        }
    except Exception as e:
        raise HTTPException(503, detail=f"Backend API connection failed: {str(e)}")


@app.post("/reconcile", response_model=ReconcileResponse)
async def reconcile(request: ReconcileRequest):
    """
    Main endpoint - Make.com sends ONLY bank statement.
    API fetches backend from API automatically.
    """

    run_id = (
        f"RUN_{request.start_date}_to_{request.end_date}_"
        f"{datetime.now().strftime('%H%M%S')}_{uuid.uuid4().hex[:6].upper()}"
    )
    
    try:
        # 1. Fetch backend from API
        print(f"🔄 Fetching backend from API for {request.start_date} to {request.end_date}...")
        backend_df = get_backend_data_from_api(request.start_date, request.end_date)
        
        if backend_df.empty:
            raise HTTPException(
                404,
                detail=f"No backend data for {request.start_date} to {request.end_date}"
            )
        
        # 2. Convert bank data from Make.com
        bank_df = pd.DataFrame(request.bank_data)
        
        if bank_df.empty:
            raise HTTPException(400, detail="Bank data empty")
        
        print(f"📊 Backend: {len(backend_df)}, Bank: {len(bank_df)}")
        
        # 3. Reconcile
        engine = ReconciliationEngine(backend_df, bank_df)
        summary = engine.run_full_reconciliation()
        
        # 4. AI analysis
        ai_analysis = None
        if request.run_ai_analysis and ANTHROPIC_API_KEY:
            print("🤖 Running AI...")
            ai_analysis = analyze_with_ai(engine, request.start_date, request.end_date)
        
        unmatched_payload = {
            "backend_only_send": engine.results.get("send_bank_unmatched", pd.DataFrame()).to_dict("records"),
            "backend_only_fund": engine.results.get("fund_unmatched", pd.DataFrame()).to_dict("records"),
            "bank_only": engine.results.get("bank_unmatched", pd.DataFrame()).to_dict("records"),
            "reversal_unmatched": engine.results.get("reversal_unmatched", pd.DataFrame()).to_dict("records"),
        }

        return ReconcileResponse(
            run_id=run_id,
            start_date=request.start_date,
            end_date=request.end_date,
            status="complete",
            summary=summary,
            ai_analysis=ai_analysis,
            backend_count=len(backend_df),
            bank_count=len(bank_df),
            unmatched=unmatched_payload
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(500, detail=f"Failed: {str(e)}")


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "backend_api_configured": bool(BACKEND_API_BASE),
        "ai_configured": bool(ANTHROPIC_API_KEY)
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

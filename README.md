# AI-Powered Bank Reconciliation API
**Liberty Assured Group — Agency Banking Automation**

Converts your Jupyter notebook reconciliation logic into a production API with AI-powered discrepancy analysis.

---

## What This Does

✅ **Converts your manual reconciliation to an API**
- Takes your existing pandas/Excel logic from Jupyter notebook
- Wraps it in FastAPI so Make.com can call it
- Returns structured JSON results

✅ **Adds AI layer for discrepancy analysis**
- Automatically groups unmatched transactions by type
- Explains WHY discrepancies exist (timing delays, reversals, external funds, errors)
- Prioritizes what needs investigation first
- Generates email-ready summaries

✅ **Integrates with Make.com**
- Pulls data from Google Sheets
- Runs reconciliation
- Saves results back to Sheets
- Sends email with AI analysis

---

## Architecture

```
Make.com Scenario
├─ Trigger: New month starts
├─ Get backend data from Google Sheets
├─ Get bank statement from Google Sheets
├─ POST to FastAPI → /reconcile
│  ├─ Your existing reconciliation logic
│  ├─ Match SEND_BANK_TRANSFER (ref_1, ref_2)
│  ├─ Match FUND_BANK_TRANSFER (session_id)
│  ├─ Map reversals to failed transactions
│  ├─ Bank-to-backend matching
│  └─ AI analyzes all unmatched
├─ Save summary to Google Sheets
└─ Email AI analysis to finance team
```

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set API Key

```bash
# Get from console.anthropic.com (free $5 credit)
export ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
```

### 3. Run Locally

```bash
uvicorn main:app --reload --port 8000
```

Visit: http://localhost:8000

### 4. Test It

```bash
curl -X POST http://localhost:8000/reconcile \
  -H "Content-Type: application/json" \
  -d @test_data.json
```

---

## API Endpoints

### POST `/reconcile`

Run full reconciliation with AI analysis.

**Request:**
```json
{
  "period": "2026-01",
  "backend_data": [
    {
      "transaction_id": "123",
      "transaction_type": "SEND_BANK_TRANSFER",
      "unique_reference": "ABC123456-XYZ789012",
      "amount": 50000,
      "date_created": "2026-01-15",
      "status": "SUCCESSFUL",
      "account_provider": "VFD",
      "escrow_id": "ESC001",
      "session_id": "SES001",
      "narration": "Transfer to customer"
    }
  ],
  "bank_data": [
    {
      "transaction_date": "2026-01-15",
      "transaction_id": "ABC123456",
      "session_id": "",
      "account_no": "1234567890",
      "transaction_type": "Debit",
      "beneficiary_account_no": "9876543210",
      "debit": 50000,
      "credit": 0,
      "balance": 100000,
      "reversed": "No",
      "narration": "Transfer to..."
    }
  ],
  "run_ai_analysis": true
}
```

**Response:**
```json
{
  "run_id": "RUN_2026-01_143022_A3F9B1",
  "period": "2026-01",
  "status": "complete",
  "summary": {
    "total_backend_transactions": 1245,
    "total_bank_transactions": 1198,
    "send_bank_matched": 1102,
    "send_bank_unmatched": 23,
    "fund_matched": 85,
    "fund_unmatched": 8,
    "bank_to_backend_matched": 1180,
    "bank_to_backend_unmatched": 18,
    "total_unmatched_backend_value": 2400000.50,
    "total_unmatched_bank_value": 600000.00
  },
  "ai_analysis": "DISCREPANCY SUMMARY BY TYPE\n\nBackend Not on Bank Statement (23 transactions, ₦2.4M):\n• SEND_BANK_TRANSFER: 15 transactions (₦1.8M)\n  - Likely timing delays: transactions initiated late Friday may appear on Monday's statement\n  - 3 show status='PENDING' - these haven't completed\n• REVERSAL_BANK_TRANSFER: 5 transactions (₦400K)\n  - These match failed SEND_BANK_TRANSFER on escrow_id\n  - Internal reversals that didn't reach bank\n• ELECTRONIC_TRANSFER_LEVY: 3 transactions (₦200K)\n  - Stamp duty charges likely batched differently\n\nBank → Backend Gaps (18 transactions, ₦600K):\n• External credits (12 txns, ₦550K)\n  - Narration shows 'WEMA', 'FIDELITY' - float funding\n  - Verify with Madam Funmi\n• Bank charges (6 txns, ₦50K)\n  - Standard processing fees not captured in backend\n\nTOP 3 ACTIONS:\n1. Check if 15 pending SEND_BANK_TRANSFER appear on next day's statement\n2. Confirm 12 external credits are authorized float deposits\n3. Set up automated capture of bank charges\n",
  "matched_file_url": "/download/RUN_2026-01_143022_A3F9B1_matched.xlsx",
  "unmatched_file_url": "/download/RUN_2026-01_143022_A3F9B1_unmatched.xlsx"
}
```

### GET `/health`

Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2026-02-17T14:30:22.123456"
}
```

---

## How AI Improves Your Reconciliation

### Before (Manual Process):

1. Run Python script
2. Get unmatched.xlsx
3. Open in Excel
4. Manually group by transaction_type
5. Manually analyze each group
6. Guess why discrepancies exist
7. Write email summary yourself
8. **Time: 30-45 minutes**

### After (With AI):

1. Run API call
2. Get instant analysis:
   - Grouped by type ✅
   - Root causes explained ✅
   - Action items prioritized ✅
   - Email summary ready ✅
3. **Time: 2 minutes**

### AI Understands Your Context:

The AI knows:
- SEND_BANK_TRANSFER with no ref → probably failed
- Reversals matching on escrow_id → internal cancellations
- Credits from WEMA/Fidelity → float funding
- FUND_BANK_TRANSFER mismatches → session_id timing issues
- Weekend transactions → appear on Monday statement

---

## Reconciliation Logic (From Your Notebook)

### 1. SEND_BANK_TRANSFER Matching

```
Backend unique_reference: "ABC123456-XYZ789012"
   ├─ ref_1 = "ABC123456" (first 9 chars)
   └─ ref_2 = "XYZ789012" (chars 10+)

Match rules:
1. Bank transaction_id == ref_1 → Match ✓
2. Bank transaction_id == ref_2 → Match ✓ (provider fees)
3. No match + status != SUCCESSFUL → Map to reversals
```

### 2. REVERSAL_BANK_TRANSFER Mapping

```
For unmatched SEND_BANK_TRANSFER:
   Match to REVERSAL_BANK_TRANSFER on escrow_id
   → These are internal cancellations
   → Won't appear on bank statement
```

### 3. FUND_BANK_TRANSFER Matching

```
Match on session_id:
   Backend session_id == Bank session_id
   Prefer bank credits over debits
   VFD provider only
```

### 4. Bank-to-Backend Matching

```
Reverse check:
   For each bank transaction:
      Does it match any backend ref_1 or ref_2?
      No → Flag as "in bank but not backend"
      → Likely external deposit or manual transaction
```

---

## Deployment

See [MAKE_INTEGRATION.md](MAKE_INTEGRATION.md) for full Make.com setup.

### Deploy to Railway:

```bash
railway login
railway init
railway up
railway domain
```

Add environment variable:
```
ANTHROPIC_API_KEY=sk-ant-api03-...
```

### Deploy to Render:

1. Connect GitHub repo
2. Build: `pip install -r requirements.txt`
3. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add env var: `ANTHROPIC_API_KEY`

---

## Cost

| Service | Usage | Cost |
|---------|-------|------|
| **Railway/Render** | API hosting | Free tier (500 hrs/month) |
| **Claude API** | AI analysis | ~$0.01 per reconciliation |
| **Make.com** | Workflow automation | Free tier (1000 operations/month) |

**Monthly total:** ~$3 for daily reconciliations

---

## File Structure

```
recon_api/
├── main.py                 # FastAPI service with reconciliation engine
├── requirements.txt        # Python dependencies
├── MAKE_INTEGRATION.md     # Make.com setup guide
├── README.md              # This file
└── test_data.json         # Sample test data
```

---

## Customization

### Add New Matching Rules

Edit `ReconciliationEngine` class in `main.py`:

```python
def reconcile_custom_type(self):
    """Your custom matching logic"""
    trans = self.backend_prepared
    bank = self.bank_prepared
    
    # Your matching logic here
    matched = ...
    unmatched = ...
    
    self.results['custom_matched'] = matched
    self.results['custom_unmatched'] = unmatched
    
    return matched, unmatched
```

Then call it in `run_full_reconciliation()`.

### Customize AI Prompts

Edit the AI prompt in `analyze_with_ai()` function (line 380):

```python
prompt = f"""
You are analyzing...

FOCUS ON:
- [Your specific concerns]
- [Industry-specific patterns]
- [Regulatory requirements]

...
"""
```

---

## Troubleshooting

**Q: API returns "AI analysis unavailable"**
A: Set `ANTHROPIC_API_KEY` environment variable

**Q: "KeyError: 'transaction_type'"**
A: Your data is missing required columns. Check column names match exactly.

**Q: Reconciliation takes too long**
A: Split large datasets into batches. Process one month at a time.

**Q: AI analysis quality is poor**
A: Include more sample rows in the prompt (edit line 360-370 in main.py)

**Q: Make.com can't reach my API**
A: Check Railway/Render deployment is live. Test with Postman first.

---

## Next Steps

1. ✅ Test API locally
2. ✅ Deploy to Railway/Render
3. ✅ Set up Make.com scenario
4. ✅ Run test reconciliation
5. ✅ Review AI output quality
6. ✅ Schedule daily automation

---

## Support

For issues or questions:
- Check [MAKE_INTEGRATION.md](MAKE_INTEGRATION.md)
- Review API endpoint documentation above
- Test with sample data in test_data.json

---

**Built for Liberty Assured Group | AI Productivity Challenge 2026**

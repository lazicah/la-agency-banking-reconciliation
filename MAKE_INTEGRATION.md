# Make.com Integration Guide
## AI-Powered Bank Reconciliation API

---

## Overview

Make.com workflow:
1. Downloads backend data (CSV) and bank statement (Google Sheets)
2. Sends to Python API
3. Gets back reconciliation results + AI analysis
4. Saves to Google Sheets
5. Sends email summary

---

## Step 1: Deploy the Python API

### Option A: Railway (Recommended - Free)

```bash
# 1. Install Railway CLI
npm install -g @railway/cli

# 2. Navigate to your project
cd recon_api

# 3. Login
railway login

# 4. Create new project
railway init

# 5. Deploy
railway up

# 6. Get your URL
railway domain
# Example: https://recon-api.up.railway.app
```

### Option B: Render

1. Go to render.com
2. New → Web Service
3. Connect GitHub repo
4. Build command: `pip install -r requirements.txt`
5. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Add environment variable: `ANTHROPIC_API_KEY=your-key`

---

## Step 2: Create Make.com Scenario

### Trigger: Google Sheets Watch Rows

**Module:** Google Sheets → Watch Rows
```
Spreadsheet: Your backend data sheet
Sheet: Agency Banking Data
```

### Action 1: Get Bank Statement

**Module:** Google Sheets → Get Range Values
```
Spreadsheet: Your bank statement
Sheet: Sheet 1
Range: A:M (all columns)
```

### Action 2: Transform to JSON

**Module:** Tools → Set Multiple Variables

Create two variables:

**backend_json:**
```javascript
{{map(GoogleSheets.values; "transaction_id"; value[0]; "transaction_type"; value[1]; "unique_reference"; value[2]; "session_id"; value[3]; "amount"; value[4]; "date_created"; value[5]; "status"; value[6]; "narration"; value[7]; "account_provider"; value[8]; "escrow_id"; value[9])}}
```

**bank_json:**
```javascript
{{map(GoogleSheets2.values; "transaction_date"; value[0]; "transaction_id"; value[1]; "session_id"; value[2]; "account_no"; value[3]; "transaction_type"; value[4]; "beneficiary_account_no"; value[5]; "debit"; value[6]; "credit"; value[7]; "balance"; value[8]; "reversed"; value[9]; "narration"; value[10])}}
```

### Action 3: Call Reconciliation API

**Module:** HTTP → Make a Request

```
URL: https://your-api.railway.app/reconcile
Method: POST
Headers:
  Content-Type: application/json

Body (JSON):
{
  "period": "{{formatDate(now; "YYYY-MM")}}",
  "backend_data": {{backend_json}},
  "bank_data": {{bank_json}},
  "run_ai_analysis": true
}
```

**Response will look like:**
```json
{
  "run_id": "RUN_2026-01_143022_A3F9B1",
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
  "ai_analysis": "DISCREPANCY SUMMARY BY TYPE\n\nBackend Not on Bank...",
  "matched_file_url": "/download/...",
  "unmatched_file_url": "/download/..."
}
```

### Action 4: Save Summary to Google Sheets

**Module:** Google Sheets → Add a Row

```
Spreadsheet: Reconciliation Log
Sheet: Monthly Summary

Columns:
A: {{formatDate(now; "YYYY-MM")}}
B: {{summary.total_backend_transactions}}
C: {{summary.total_bank_transactions}}
D: {{summary.send_bank_matched}}
E: {{summary.send_bank_unmatched}}
F: {{summary.total_unmatched_backend_value}}
G: {{summary.total_unmatched_bank_value}}
H: {{ai_analysis}}
I: {{formatDate(now; "YYYY-MM-DD HH:mm:ss")}}
```

### Action 5: Send Email with AI Analysis

**Module:** Gmail → Send an Email

```
To: finance-team@libertyassured.com
Subject: Bank Reconciliation {{formatDate(now; "YYYY-MM")}} — {{summary.send_bank_unmatched}} Discrepancies
Body:

AGENCY BANKING RECONCILIATION — {{formatDate(now; "MMMM YYYY")}}
═══════════════════════════════════════════════════════════════

SUMMARY
-------
✅ Total Matched:        {{summary.send_bank_matched}} / {{summary.total_backend_transactions}}
⚠️  Unmatched Backend:   {{summary.send_bank_unmatched}} (₦{{formatNumber(summary.total_unmatched_backend_value; 0; ","; ".")}})
⚠️  Unmatched Bank:      {{summary.bank_to_backend_unmatched}} (₦{{formatNumber(summary.total_unmatched_bank_value; 0; ","; ".")}})

AI ANALYSIS
-----------
{{ai_analysis}}

═══════════════════════════════════════════════════════════════
View full details in Google Sheets: [Link]
```

### Action 6: Slack Notification (Optional)

**Module:** Slack → Create a Message

```
Channel: #finance-reconciliation
Message:
*Reconciliation Complete — {{formatDate(now; "MMM YYYY")}}*

✅ Matched: {{summary.send_bank_matched}}
⚠️ Unmatched: {{summary.send_bank_unmatched}}
💰 Value at Risk: ₦{{formatNumber(summary.total_unmatched_backend_value; 0; ","; ".")}}

{{if(summary.send_bank_unmatched > 50; "🚨 HIGH ALERT: Unusual number of discrepancies"; "✓ Normal discrepancy levels")}}

<View Report>
```

---

## Step 3: AI Analysis Customization

The AI automatically:

✅ Groups discrepancies by transaction type
✅ Identifies timing delays vs. real errors
✅ Spots external transactions (float funding)
✅ Prioritizes what needs investigation first

### To customize AI prompts:

Edit `main.py` line 380 (the prompt template):

```python
prompt = f"""
You are analyzing... [your custom instructions]

Focus especially on:
- Reversed transactions that match on escrow_id
- VFD vs. other providers
- Weekend vs. weekday timing patterns

[etc]
"""
```

---

## Step 4: Where AI Adds Value

### Current Flow (Manual):
1. Run reconciliation → get unmatched
2. Open Excel files manually
3. Manually group by type
4. Manually analyze patterns
5. Write email summary yourself

### With AI Layer:
1. Run reconciliation → get unmatched
2. **AI instantly:**
   - Groups by type (SEND_BANK_TRANSFER, FUND_BANK_TRANSFER, etc.)
   - Explains WHY each category is unmatched
   - Identifies if it's timing, reversals, external funds, or errors
   - Prioritizes top 3 actions
3. Email + Sheets auto-populated with AI insights

**Time saved: 30-45 minutes per reconciliation**

---

## Step 5: Testing

### Test with Postman

```bash
POST https://your-api.railway.app/reconcile
Content-Type: application/json

{
  "period": "2026-01",
  "backend_data": [
    {
      "transaction_id": "1234",
      "transaction_type": "SEND_BANK_TRANSFER",
      "unique_reference": "ABC123456-XYZ789012",
      "amount": 50000,
      "date_created": "2026-01-15",
      "status": "SUCCESSFUL",
      "escrow_id": "ESC001"
    }
  ],
  "bank_data": [
    {
      "transaction_date": "2026-01-15",
      "transaction_id": "ABC123456",
      "debit": 50000,
      "credit": 0,
      "narration": "Transfer to..."
    }
  ],
  "run_ai_analysis": true
}
```

---

## Cost Breakdown

| Component | Cost |
|-----------|------|
| Railway hosting | Free (500 hrs/month) |
| Claude API | $0.01 per reconciliation |
| Make.com operations | ~100 ops per run (free tier: 1000/month) |

**Total: ~$3/month for daily reconciliations**

---

## Troubleshooting

**Problem:** "AI analysis unavailable"
**Fix:** Check `ANTHROPIC_API_KEY` environment variable in Railway

**Problem:** "Invalid JSON in request"
**Fix:** Check that your Google Sheets column mapping in Make matches your actual column order

**Problem:** "Reconciliation failed: KeyError"
**Fix:** Your backend/bank data is missing required columns. Check column names match exactly.

**Problem:** "Timeout after 30 seconds"
**Fix:** Increase Railway timeout or process data in batches

---

## Next Steps

1. Deploy API to Railway
2. Set up Make.com scenario
3. Run first test reconciliation
4. Review AI output quality
5. Customize email template
6. Schedule daily runs (Make scheduler)

Need help with any step? Check the main README or API documentation.

# Google Sheets Integration - Transfer Reconciliation

## Overview

Added Google Sheets parsing functionality to the Transfer Reconciliation form, allowing users to fetch bank statement data directly from publicly accessible Google Sheets URLs instead of manually entering JSON.

## What Was Implemented

### 1. Google Sheets Parsing Utilities

Added helper functions in [web/app/reconciliation/page.tsx](web/app/reconciliation/page.tsx):

- **`parseSheetUrl(url)`**: Extracts spreadsheet ID and GID from Google Sheets URL
- **`normalizeHeader(header)`**: Standardizes column headers for flexible matching
- **`mapRowToTransaction(row, headers)`**: Maps CSV rows to Transaction objects with fuzzy column matching
- **`fetchAndParseSheet(sheetUrl)`**: Fetches public sheet as CSV and parses into transactions

### 2. Transaction Interface

```typescript
interface Transaction {
  transaction_id: string;
  transaction_date: string;
  narration: string;
  debit: number;
  credit: number;
  session_id: string;
}
```

### 3. Updated Transfer Reconciliation Form

**New Features:**
- ✅ Google Sheets URL input field
- ✅ "Fetch Sheet" button to load data from URL
- ✅ Success indicator showing number of parsed transactions
- ✅ Auto-populated JSON preview after fetching
- ✅ Fallback to manual JSON entry if needed

**Form Flow:**
1. User pastes public Google Sheets URL
2. Clicks "Fetch Sheet" button
3. System fetches CSV export and parses transactions
4. Shows success message with transaction count
5. Auto-fills JSON textarea with parsed data
6. User can review and submit for reconciliation

### 4. Flexible Column Matching

The parser supports multiple column name variations:

| Field | Recognized Column Names |
|-------|------------------------|
| **Transaction ID** | transaction_id, transaction id, txn_id, txnid, id |
| **Date** | created_date, transaction_date, date, value_date |
| **Narration** | narration, description, remarks, particulars, details |
| **Debit** | debit, dr, debit_amount, withdrawal |
| **Credit** | credit, cr, credit_amount, deposit |
| **Session ID** | session_id, session id, sessionid, session_ref, reference |

This ensures compatibility with various bank statement formats.

## Technical Implementation

### Dependencies

- **papaparse** (^5.4.1): CSV parsing library
- **@types/papaparse** (^5.3.0): TypeScript type definitions

### URL Parsing

Supports standard Google Sheets URL formats:
```
https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={GID}
https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit?gid={GID}
```

### CSV Export

Converts Google Sheets to CSV using the public export endpoint:
```
https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={GID}
```

**Requirements:**
- Sheet must be publicly accessible (Share → Anyone with link can view)
- No authentication required

### Error Handling

- ✅ Invalid URL format detection
- ✅ HTTP error handling (404, 403, etc.)
- ✅ CSV parsing error detection
- ✅ Empty data validation
- ✅ Column header mismatch detection

## User Experience

### Before (Manual Entry)
```json
[
  {
    "transaction_id": "TXN001",
    "transaction_date": "2026-02-07",
    "narration": "Payment received",
    "debit": 0,
    "credit": 50000,
    "session_id": "SES123"
  }
]
```
*User had to manually format bank data as JSON*

### After (Google Sheets)
1. Paste URL: `https://docs.google.com/spreadsheets/d/ABC123/edit#gid=0`
2. Click "Fetch Sheet"
3. ✓ Successfully parsed 247 transactions
4. Review auto-generated JSON
5. Submit

## Example Google Sheets Format

The parser expects columns like:

| Transaction ID | Created Date | Narration | Debit | Credit | Session ID |
|---|---|---|---|---|---|
| TXN001 | 2026-02-07 | Payment received | 0 | 50,000 | SES123 |
| TXN002 | 2026-02-08 | Transfer out | 25,000 | 0 | SES124 |

**Column headers are flexible** - variations like "Transaction_ID", "txn_id", "id" all work.

## Backend Compatibility

The parsed transactions are converted to the same format expected by the backend API:

```typescript
POST /reconcile
{
  "start_date": "2026-02-07",
  "end_date": "2026-02-28",
  "bank_data": [
    {
      "transaction_id": "TXN001",
      "transaction_date": "2026-02-07",
      "narration": "Payment received",
      "debit": 0,
      "credit": 50000,
      "session_id": "SES123"
    }
  ],
  "run_ai_analysis": true
}
```

## Testing

### Build Status
✅ TypeScript compilation: PASSED
✅ Next.js build: PASSED  
✅ Bundle size: 163 kB (reconciliation page)

### Live Testing
- **Backend**: http://localhost:8000
- **Frontend**: http://localhost:3001
- **Reconciliation Page**: http://localhost:3001/reconciliation

## Future Enhancements

Potential improvements:
- [ ] Support for authenticated Google Sheets (OAuth)
- [ ] Preview first 10 rows before full parse
- [ ] Download template Google Sheet
- [ ] Validate date formats
- [ ] Support Excel file uploads
- [ ] Batch processing multiple sheets

## Error Messages

Common errors and solutions:

| Error | Cause | Solution |
|-------|-------|----------|
| Invalid Google Sheet URL | URL format incorrect | Use share link from Google Sheets |
| Failed to fetch (403) | Sheet not public | Share → Anyone with link can view |
| No valid transactions found | Column headers don't match | Check column names match expected format |
| Failed to parse CSV | Sheet empty or corrupted | Verify sheet has data |

---

## Quick Start

1. **Make sheet public**: Google Sheets → Share → Anyone with link → Viewer
2. **Copy URL**: Click "Copy link" from share dialog
3. **Open app**: Navigate to http://localhost:3001/reconciliation
4. **Paste URL**: In "Bank Statement (Google Sheets)" field
5. **Fetch**: Click "Fetch Sheet" button
6. **Submit**: Review parsed data and run reconciliation

**That's it!** No more manual JSON formatting needed.

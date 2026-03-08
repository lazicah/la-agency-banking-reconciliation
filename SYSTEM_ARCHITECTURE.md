# Liberty Pay Unified System - Architecture & Integration

## System Overview

Complete system consolidation: Two separate FastAPI services merged into one unified API, Two separate Next.js frontends merged into one unified web application.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                             │
│  http://localhost:3000 (Development) or https://app.yourdomain   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │           Next.js 14 App Router (Unified)                  │ │
│  │                                                            │ │
│  │  ┌──────────┬──────────────┬──────────┬──────────┐        │ │
│  │  │Dashboard │Reconciliation│ Metrics  │  Config  │        │ │
│  │  └──────────┴──────────────┴──────────┴──────────┘        │ │
│  │                      ↓                                    │ │
│  │          ┌─────────────────────────────┐                │ │
│  │          │   Unified API Client        │                │ │
│  │          │   (lib/api.ts)              │                │ │
│  │          │   - APIService class        │                │ │
│  │          │   - Full TypeScript types   │                │ │
│  │          │   - Request/response mgmt   │                │ │
│  │          └─────────────────────────────┘                │ │
│  └────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
                            ↓ (HTTP/REST)
┌────────────────────────────────────────────────────────────────┐
│                      BACKEND API LAYER                           │
│  http://localhost:8000 (Development) or https://api.yourdomain   │
│                                                                   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │         FastAPI 0.104+ (Unified Instance)                │  │
│  │                                                           │  │
│  │  ┌─────────────────────┐  ┌──────────────────────────┐  │  │
│  │  │ Transfer Services   │  │ Card-Reconciliation      │  │  │
│  │  │ (Root Routes: /)    │  │ (Prefixed Routes: /card) │  │  │
│  │  │                     │  │                          │  │  │
│  │  │ ✓ GET /health      │  │ ✓ GET /health           │  │  │
│  │  │ ✓ POST /reconcile  │  │ ✓ POST /reconciliation/ │  │  │
│  │  │                     │  │ ✓ GET /metrics/latest   │  │  │
│  │  │ Services:          │  │ ✓ GET /metrics/{date}   │  │  │
│  │  │ - reconciliation   │  │ ✓ GET /config           │  │  │
│  │  │ - google_sheets    │  │                          │  │  │
│  │  │ - ai_service       │  │ Services:                │  │  │
│  │  │                     │  │ - reconciliation         │  │  │
│  │  │                     │  │ - google_sheets         │  │  │
│  │  │                     │  │ - ai_service            │  │  │
│  │  └─────────────────────┘  └──────────────────────────┘  │  │
│  │           ↓                          ↓                    │  │
│  │     ┌─────────────┐          ┌──────────────┐            │  │
│  │     │Transfer DB  │          │Card DB       │            │  │
│  │     │(SQLalchemy) │          │(SQLalchemy)  │            │  │
│  │     └─────────────┘          └──────────────┘            │  │
│  └───────────────────────────────────────────────────────────┘  │
│           ↓ (OAuth2)                   ↓ (OAuth2)               │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │         Shared External Services                          │  │
│  │                                                           │  │
│  │  • Google Sheets API (Reconciliation data)              │  │
│  │  • OpenAI API (GPT-4 analysis)                          │  │
│  │  • Azure Blob Storage (Architecture agnostic)           │  │
│  │                                                           │  │
│  └───────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

## Request Flow Examples

### Example 1: Transfer Reconciliation

```
1. User Input (Frontend)
   └─ Form: start_date, end_date, bank_data[], run_ai_analysis
      ↓
2. Frontend Action (app/reconciliation/page.tsx)
   └─ const response = await apiService.runTransferReconciliation({...})
      ↓
3. API Client (lib/api.ts)
   └─ POST http://localhost:8000/reconcile
      └─ Headers: {'Content-Type': 'application/json'}
      └─ Body: {start_date, end_date, bank_data, run_ai_analysis}
      ↓
4. Backend Handler (main.py → reconciliation_service)
   └─ app.post('/reconcile')
   └─ Calls reconciliation_service.run_transfer_reconciliation()
   └─ Queries Google Sheets for transaction data
   └─ Performs data matching and reconciliation
   └─ Runs AI analysis if requested
      ↓
5. Response (TransferReconciliationResponse)
   └─ {
       run_id,
       start_date,
       end_date,
       status,
       summary: {matched, unmatched, ...},
       ai_analysis?: string (markdown),
       backend_count,
       bank_count,
       unmatched: {total_unmatched_backend_value, total_unmatched_bank_value}
     }
      ↓
6. Frontend Display (app/reconciliation/page.tsx)
   └─ Render summary table
   └─ Render AI analysis with markdown
   └─ Show counts and unmatched amounts
```

### Example 2: Card Reconciliation

```
1. User Input (Frontend)
   └─ Form: run_date (optional), days_offset (default: 18)
      ↓
2. Frontend Action (app/reconciliation/page.tsx)
   └─ const response = await apiService.runCardReconciliation({...})
      ↓
3. API Client (lib/api.ts)
   └─ POST http://localhost:8000/card-reconciliation/reconciliation/run
      └─ Headers: {'Content-Type': 'application/json'}
      └─ Body: {run_date: ISOString | null, days_offset: number}
      ↓
4. Backend Handler (main.py.include_router → card_main.py router)
   └─ @router.post('/reconciliation/run')
   └─ Calls card_reconciliation_service.run_reconciliation()
   └─ Fetches transaction data from backend API
   └─ Categorizes by channel (card networks)
   └─ Runs AI analysis on summary
      ↓
5. Response (CardReconciliationResponse)
   └─ {
       status,
       message,
       run_date: ISOString,
       metrics: {MetricsResponse},
       ai_summary?: string (markdown),
       metrics_file_path
     }
      ↓
6. Frontend Display (app/reconciliation/page.tsx)
   └─ Render MetricsCard grid from metrics
   └─ Render channel breakdown table
   └─ Render AI summary with markdown
```

### Example 3: Metrics Query

```
1. User Action (Frontend - Metrics page)
   └─ Click "Load Latest" or select date + "Load by Date"
      ↓
2. Frontend API Call (lib/api.ts)
   └─ apiService.getLatestMetrics()
      └─ GET http://localhost:8000/card-reconciliation/metrics/latest
      
      OR
      
      apiService.getMetricsByDate(selectedDate)
      └─ GET http://localhost:8000/card-reconciliation/metrics/2026-02-07
      ↓
3. Backend Handler (card_main.py router)
   └─ @router.get('/metrics/latest')
   └─ @router.get('/metrics/{date}')
   └─ Returns stored MetricsResponse from previous runs
      ↓
4. Response (MetricsResponse)
   └─ {
       run_date,
       total_revenue,
       total_settlement,
       channels: {
         channel_name: {revenue, settlement, charge_back, unsettled_claim},
         ...
       }
     }
      ↓
5. Frontend Display (app/metrics/page.tsx)
   └─ Render MetricsCard grid
   └─ Render Bar chart (revenue by channel)
   └─ Render detailed table
   └─ Enable CSV/JSON export
```

## Data Models

### Transfer Reconciliation Data
```
Request:
{
  start_date: "2026-02-07",
  end_date: "2026-02-28",
  bank_data: [
    {reference, amount, transaction_date, ...},
    ...
  ],
  run_ai_analysis: true
}

Response:
{
  run_id: "uuid",
  status: "completed",
  summary: {
    total_backend_transactions: number,
    total_bank_transactions: number,
    matched_transactions: number,
    unmatched_count: number,
    total_difference: number,
    ...
  },
  unmatched: {
    total_unmatched_backend_value: number,
    total_unmatched_bank_value: number,
    backend_unmatched: [...],
    bank_unmatched: [...]
  },
  ai_analysis: "# Reconciliation Analysis\n...",
  backend_count: number,
  bank_count: number
}
```

### Card Reconciliation Data
```
Request:
{
  run_date: "2026-02-07" | null,
  days_offset: 18
}

Response:
{
  status: "completed",
  run_date: "2026-02-07",
  metrics: {
    run_date: "2026-02-07",
    total_revenue: 5000000,
    total_settlement: 4800000,
    total_settlement_charge_back: 150000,
    total_settlement_unsettled_claims: 50000,
    channels: {
      "Verve": {revenue: 2000000, settlement: 1900000, ...},
      "Mastercard": {revenue: 2000000, settlement: 1900000, ...},
      "Visa": {revenue: 1000000, settlement: 1000000, ...}
    }
  },
  ai_summary: "# Card Reconciliation Summary\n..."
}
```

### Metrics Data Model
```
{
  run_date: "2026-02-07",
  total_revenue: number,
  total_settlement: number,
  total_settlement_charge_back: number,
  total_settlement_unsettled_claims: number,
  total_bank_isw_unsettled_claims: number,
  total_bank_isw_charge_back: number,
  channels: {
    [channelName]: {
      revenue?: number,
      settlement?: number,
      charge_back?: number,
      unsettled_claim?: number
    }
  }
}
```

## Frontend-Backend Mapping

| Frontend Route | Component | Backend Endpoint | Backend Service |
|---|---|---|---|
| `/` | Dashboard | `GET /health` | transfer health check |
| `/` | Dashboard | `GET /card-reconciliation/health` | card health check |
| `/` | Dashboard | `GET /card-reconciliation/metrics/latest` | card metrics |
| `/reconciliation` | Transfer Tab | `POST /reconcile` | transfer reconciliation |
| `/reconciliation` | Card Tab | `POST /card-reconciliation/reconciliation/run` | card reconciliation |
| `/metrics` | Metrics Page | `GET /card-reconciliation/metrics/latest` | card metrics (latest) |
| `/metrics` | Metrics Page | `GET /card-reconciliation/metrics/{date}` | card metrics (by date) |
| `/config` | Config Page | `GET /card-reconciliation/health` | card health (for dependencies) |
| `/config` | Config Page | `GET /card-reconciliation/config` | card config |

## Deployment Topology

### Development
```
Local Machine:
  Port 8000: FastAPI backend (python main.py)
  Port 3000: Next.js frontend (npm run dev)
  
Environment: .env.local
  NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

### Production (Azure/Cloud)
```
Azure Container Registry:
  - Backend image: liberty-pay-backend:latest
    └─ Contains: main.py + card_reconciliation/
    └─ Port: 8000
    └─ Deployment: Container Instance or App Service

  - Frontend image: liberty-pay-frontend:latest
    └─ Contains: Next.js build (npm run build)
    └─ Port: 3000
    └─ Deployment: Static Site Hosting (vercel.com) or Container Instance

Environment: .env.production
  NEXT_PUBLIC_API_BASE_URL=https://api.yourdomain.com
  
External Services:
  - Google Sheets API (OAuth2)
  - OpenAI API (API Key)
  - Azure Blob Storage (Connection String)
```

## Running the System

### Prerequisites
- Python 3.9+
- Node.js 18+
- Google Sheets API credentials
- OpenAI API key (optional for non-AI mode)

### Step 1: Backend Setup
```bash
# Install Python dependencies
pip install -r requirements.txt

# Run backend
python main.py
# Backend runs on http://localhost:8000
```

### Step 2: Frontend Setup
```bash
cd /web

# Install Node dependencies
npm install

# Run development server
npm run dev
# Frontend runs on http://localhost:3000
```

### Step 3: Access Application
1. Open browser to http://localhost:3000
2. Navigate through Dashboard → Reconciliation → Metrics → Config
3. Each page communicates with backend on http://localhost:8000

### Production Deployment
```bash
# Build frontend
cd /web
npm run build
npm start

# OR deploy to Vercel
vercel

# Set environment variable
# NEXT_PUBLIC_API_BASE_URL=https://your-backend-api.com
```

## Error Handling

### Frontend Error Handling
- **Network Errors**: Caught by axios interceptor, displayed in ErrorMessage component
- **Type Errors**: TypeScript strict mode prevents invalid data access
- **API Errors**: HTTP status codes checked, meaningful error messages shown
- **Timeout**: 150s timeout configured in axios client

### Backend Error Handling
- **Missing Credentials**: Returns 500 with error message
- **Invalid Requests**: Returns 422 with validation errors
- **Google Sheets Errors**: Logged and wrapped with helpful message
- **AI Service Errors**: Gracefully falls back to summary-only mode

## Monitoring & Logging

### Frontend
- Browser console logs (development mode)
- Network tab in DevTools shows all API calls
- Error boundary component (to be added) for crash handling

### Backend
- FastAPI OpenAPI docs at `http://localhost:8000/docs`
- Logging to console (development mode)
- Structured logging with request IDs (production recommendation)

## Performance Optimization

### Frontend
- **Code Splitting**: Each page bundled separately
- **Static Generation**: All pages prerendered
- **Image Optimization**: Next.js automatic image optimization
- **CSS**: Tailwind CSS tree-shaking removes unused styles

### Backend
- **Google Sheets Caching**: Results cached in memory
- **Database Indexing**: Indexes on frequently queried columns
- **Async Operations**: Card reconciliation runs asynchronously
- **Connection Pooling**: Database connections reused

## Security Considerations

### Frontend
- HTTPS enforced in production
- No credentials stored in localStorage
- CSRF protection (Next.js built-in)
- XSS protection (React escaping)

### Backend
- OAuth2 for Google Sheets
- API key validation for OpenAI
- CORS configured for specific domains
- Request validation with Pydantic models

### Data
- Sensitive data (API keys) stored in environment variables
- No hardcoded credentials
- Database connections use environment variables
- File exports cleared after timeout

## Troubleshooting

### Frontend can't reach backend
1. Check backend is running: `python main.py`
2. Verify port 8000 is accessible
3. Check `NEXT_PUBLIC_API_BASE_URL` in `.env.local`
4. Look at Network tab in browser DevTools

### Functions slower than expected
1. Check Google Sheets API quota
2. Check network latency (browser DevTools)
3. Review FastAPI logs for slow queries
4. Consider caching strategy

### Build fails with TypeScript errors
1. Run `npm run type-check` for full error details
2. Ensure all API response types match actual API
3. Check for valid field access patterns
4. Verify type imports are correct

---

## Documentation

- Backend: See [main.py](main.py) and [MAKE_INTEGRATION.md](MAKE_INTEGRATION.md)
- Frontend: See [web/README.md](web/README.md)
- Merge Summary: See [FRONTEND_MERGE_SUMMARY.md](FRONTEND_MERGE_SUMMARY.md)

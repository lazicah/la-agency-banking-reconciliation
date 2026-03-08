"""
Google Sheets service for data loading and writing.
"""
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from card_reconciliation.config import settings


class GoogleSheetsService:
    """Service for interacting with Google Sheets."""
    
    def __init__(self):
        """Initialize Google Sheets connection from environment credentials."""
        try:
            # Get credentials from environment variables
            credentials_dict = settings.get_google_credentials()
            
            # Create credentials object
            self.creds = Credentials.from_service_account_info(
                credentials_dict,
                scopes=settings.google_scopes
            )
            
            # Authorize and open workbook
            self.gc = gspread.authorize(self.creds)
            self.workbook = self.gc.open_by_key(settings.spreadsheet_id)
        except Exception as e:
            raise RuntimeError(
                f"Failed to initialize Google Sheets connection: {e}. "
                f"Ensure GOOGLE_CREDENTIALS_BASE64, GOOGLE_CREDENTIALS_JSON, or SERVICE_ACCOUNT_FILE is set."
            )
    
    def load_sheet_as_df(self, sheet_name: str) -> pd.DataFrame:
        """Load a sheet as a pandas DataFrame."""
        try:
            worksheet = self.workbook.worksheet(sheet_name)
            records = worksheet.get_all_records()
            return pd.DataFrame(records)
        except Exception as e:
            raise Exception(f"Error loading sheet '{sheet_name}': {str(e)}")
    
    def load_all_sheets(self) -> dict:
        """Load all required sheets."""
        sheets = {
            'card_df': self.load_sheet_as_df(settings.sheet_card_transaction),
            'nibss_unity_settlement_df': self.load_sheet_as_df(settings.sheet_nibss_settlement),
            'unity_settlement': self.load_sheet_as_df(settings.sheet_isw_settlement),
            'parallex_nibss': self.load_sheet_as_df(settings.sheet_parallex_nibss),
            'collection_account_unity': self.load_sheet_as_df(settings.sheet_bank_unity),
            'collection_account_parallex': self.load_sheet_as_df(settings.sheet_bank_parallex),
        }
        return sheets
    
    def get_or_create_worksheet(self, sheet_name: str, rows: int = 1000, cols: int = 50):
        """Get or create a worksheet."""
        try:
            return self.workbook.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            return self.workbook.add_worksheet(
                title=sheet_name,
                rows=rows,
                cols=cols
            )
    
    def append_df_to_sheet(self, worksheet, df: pd.DataFrame):
        """Append DataFrame to a worksheet."""
        if df.empty:
            print(f"⚠️ Skipping empty DataFrame for sheet: {worksheet.title}")
            return
        
        # Normalize dates and NaNs
        df = self._normalize_df_for_gsheets(df)
        
        values = df.values.tolist()
        existing_rows = len(worksheet.get_all_values())
        
        if existing_rows == 0:
            data = [df.columns.tolist()] + values
            worksheet.append_rows(data, value_input_option="USER_ENTERED")
        else:
            worksheet.append_rows(values, value_input_option="USER_ENTERED")
    
    def _normalize_df_for_gsheets(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize DataFrame for Google Sheets."""
        df = df.copy()
        
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M:%S")
            elif df[col].apply(lambda x: isinstance(x, pd.Timestamp)).any():
                df[col] = df[col].astype(str)
            elif df[col].apply(lambda x: hasattr(x, "isoformat")).any():
                df[col] = df[col].astype(str)
        
        return df.fillna("")
    
    def write_summary_to_sheet(self, summary_text: str, run_date):
        """Write AI summary to Google Sheets."""
        worksheet = self.get_or_create_worksheet(settings.sheet_ai_summary)
        
        if isinstance(run_date, (pd.Timestamp,)):
            run_date_str = run_date.isoformat()
        else:
            run_date_str = str(run_date)
        
        worksheet.append_row([run_date_str, summary_text[:5000]])

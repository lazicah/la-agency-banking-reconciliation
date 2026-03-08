"""
Configuration module for the Liberty Card Reconciliation API.
"""
import os
import json
import base64
from pydantic import ConfigDict
from pydantic_settings import BaseSettings
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()


class Settings(BaseSettings):
    """Application settings."""
    
    model_config = ConfigDict(
        extra='ignore',
        env_file='.env',
        case_sensitive=False
    )
    
    # OpenAI Configuration
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    ai_model: str = "gpt-4"
    
    # Google Credentials Configuration
    google_credentials_base64: str = os.getenv("GOOGLE_CREDENTIALS_BASE64", "")
    google_credentials_json: str = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
    service_account_file: str = os.getenv("SERVICE_ACCOUNT_FILE", "")
    spreadsheet_id: str = os.getenv("SPREADSHEET_ID", "1La0dpzzo2yZQTOe3DJk11uapbgF4kk2fqQ6fblck8TI")
    
    # Google Sheets Tab Names
    sheet_card_transaction: str = "CardTransaction"
    sheet_nibss_settlement: str = "NIBSS SETT FROM NIBSS"
    sheet_isw_settlement: str = "ISW SETT REPORT"
    sheet_parallex_nibss: str = "LIBERTYPAY_Pos_Acquired_Detail_"
    sheet_bank_unity: str = "BANK STMT UNITY"
    sheet_bank_parallex: str = "BANK STMT PARALLEX"
    sheet_ai_summary: str = "AI Summary"
    
    # Google Scopes
    google_scopes: list = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # API Configuration
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("API_PORT", "8000"))
    api_reload: bool = os.getenv("API_RELOAD", "true").lower() == "true"
    
    # Merchant IDs
    merchant_id_interswitch_unity: str = "2LBP87654321988"
    merchant_id_nibss_unity: str = "2215LA525653900"
    merchant_id_nibss_parallex: float = 210000000000000.0
    
    # Output paths
    output_dir: str = "outputs/metrics"
    
    def get_google_credentials(self) -> dict:
        """
        Load Google credentials from environment variables.
        
        Priority order:
        1. GOOGLE_CREDENTIALS_BASE64 (Base64 encoded JSON)
        2. GOOGLE_CREDENTIALS_JSON (Raw JSON string)
        3. SERVICE_ACCOUNT_FILE (File path)
        
        Returns:
            Dictionary containing service account credentials
            
        Raises:
            RuntimeError: If no valid credentials found
        """
        # Try Base64 encoded credentials
        if self.google_credentials_base64:
            try:
                credentials_json = base64.b64decode(self.google_credentials_base64).decode('utf-8')
                return json.loads(credentials_json)
            except Exception as e:
                raise RuntimeError(f"Failed to decode GOOGLE_CREDENTIALS_BASE64: {e}")
        
        # Try JSON string credentials
        if self.google_credentials_json:
            try:
                return json.loads(self.google_credentials_json)
            except Exception as e:
                raise RuntimeError(f"Failed to parse GOOGLE_CREDENTIALS_JSON: {e}")
        
        # Try file-based credentials (for local development)
        if self.service_account_file and Path(self.service_account_file).exists():
            try:
                with open(self.service_account_file) as f:
                    return json.load(f)
            except Exception as e:
                raise RuntimeError(f"Failed to load {self.service_account_file}: {e}")
        
        # No credentials found
        raise RuntimeError(
            "No Google credentials found. Set one of: "
            "GOOGLE_CREDENTIALS_BASE64, GOOGLE_CREDENTIALS_JSON, or SERVICE_ACCOUNT_FILE"
        )


settings = Settings()

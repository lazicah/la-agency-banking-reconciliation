"""
Utility functions for the application.
"""
from datetime import datetime, date
from typing import Any


def serialize_date(obj: Any) -> str:
    """
    Serialize date/datetime objects to ISO format strings.
    
    Args:
        obj: Object to serialize
        
    Returns:
        ISO format string
        
    Raises:
        TypeError: If object is not serializable
    """
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def parse_date_string(date_str: str) -> date:
    """
    Parse a date string in YYYY-MM-DD format.
    
    Args:
        date_str: Date string to parse
        
    Returns:
        date object
        
    Raises:
        ValueError: If date string is invalid
    """
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as e:
        raise ValueError(f"Invalid date format. Expected YYYY-MM-DD: {e}")


def format_currency(amount: float) -> str:
    """
    Format amount as currency.
    
    Args:
        amount: Amount to format
        
    Returns:
        Formatted currency string
    """
    return f"₦{amount:,.2f}"

"""
Core reconciliation service containing all business logic.
"""
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timedelta, date
from typing import Dict, Tuple
import warnings

from card_reconciliation.config import settings

warnings.filterwarnings('ignore')
pd.set_option('display.max_columns', 50)


class ReconciliationService:
    """Service for performing card transaction reconciliation."""
    
    def __init__(self, sheets_data: dict, run_date: date):
        """
        Initialize the reconciliation service.
        
        Args:
            sheets_data: Dictionary containing all loaded sheets
            run_date: The date to run reconciliation for
        """
        self.run_date = run_date
        
        # Copy datasets
        self.raw_card_df = sheets_data['card_df']
        self.raw_nibss_unity_settlement_df = sheets_data['nibss_unity_settlement_df']
        self.raw_unity_settlement = sheets_data['unity_settlement']
        self.raw_parallex_nibss = sheets_data['parallex_nibss']
        self.raw_collection_account_unity = sheets_data['collection_account_unity']
        self.raw_collection_account_parallex = sheets_data['collection_account_parallex']

        self.card_df = sheets_data['card_df'].copy()
        self.nibss_unity_settlement_df = sheets_data['nibss_unity_settlement_df'].copy()
        self.unity_settlement = sheets_data['unity_settlement'].copy()
        self.parallex_nibss = sheets_data['parallex_nibss'].copy()
        self.collection_account_unity = sheets_data['collection_account_unity'].copy()
        self.collection_account_parallex = sheets_data['collection_account_parallex'].copy()
        
        # Results storage
        self.results = {}
        self.metrics = {}
    
    def run_full_reconciliation(self) -> Dict:
        """Run the complete reconciliation process."""
        # Step 1: Prepare data
        self._prepare_data()
        
        # Step 2: Process card transactions
        self._process_card_transactions()
        
        # Step 3: Process settlements
        self._process_settlements()
        
        # Step 4: Process bank statements
        self._process_bank_statements()
        
        # Step 5: Generate metrics
        self._generate_metrics()
        
        # Step 6: Save results to datasets
        self._prepare_output_datasets()
        
        return {
            'metrics': self.metrics,
            'datasets': self.results
        }

    def _normalize_merchant_id_value(self, value) -> str:
        """Normalize merchant IDs for consistent comparisons."""
        text = str(value).strip()
        return text[:-2] if text.endswith(".0") else text

    def _normalize_merchant_id_series(self, series: pd.Series) -> pd.Series:
        """Normalize merchant ID series to string without trailing .0."""
        safe_series = self._safe_str_series(series)
        return safe_series.str.strip().str.replace(r"\.0$", "", regex=True)

    def _safe_str_series(self, series: pd.Series) -> pd.Series:
        """Return a string-typed series safe for .str operations."""
        safe = series.where(series.notna(), "")
        return safe.astype(str)

    def _coerce_numeric_columns(self, df: pd.DataFrame, columns: list) -> None:
        """Coerce known numeric columns to numeric types."""
        for col in columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
    
    def _prepare_data(self):
        """Prepare and convert date columns."""
        # Convert date columns
        self.card_df['date_created'] = pd.to_datetime(
            self.card_df['date_created'], errors='coerce'
        ).dt.date
        self.nibss_unity_settlement_df['Local_Date_Time'] = pd.to_datetime(
            self.nibss_unity_settlement_df['Local_Date_Time'], errors='coerce'
        )
        self.unity_settlement['Local_Date_Time'] = pd.to_datetime(
            self.unity_settlement['Local_Date_Time'], errors='coerce'
        )
        self.parallex_nibss['Local_Date_Time'] = pd.to_datetime(
            self.parallex_nibss['Local_Date_Time'], errors='coerce'
        )

        # Normalize identifiers and numeric fields
        self.merchant_id_interswitch_unity = self._normalize_merchant_id_value(
            settings.merchant_id_interswitch_unity
        )
        self.merchant_id_nibss_unity = self._normalize_merchant_id_value(
            settings.merchant_id_nibss_unity
        )
        self.merchant_id_nibss_parallex = self._normalize_merchant_id_value(
            settings.merchant_id_nibss_parallex
        )

        self.card_df['merchant_id'] = self._normalize_merchant_id_series(
            self.card_df['merchant_id']
        )
        self.nibss_unity_settlement_df['Merchant_ID'] = self._normalize_merchant_id_series(
            self.nibss_unity_settlement_df['Merchant_ID']
        )
        self.unity_settlement['Merchant_ID'] = self._normalize_merchant_id_series(
            self.unity_settlement['Merchant_ID']
        )
        self.parallex_nibss['Merchant_ID'] = self._normalize_merchant_id_series(
            self.parallex_nibss['Merchant_ID']
        )

        if 'host_resp_code' in self.card_df.columns:
            self.card_df['host_resp_code'] = pd.to_numeric(
                self.card_df['host_resp_code'], errors='coerce'
            )

        self._coerce_numeric_columns(self.card_df, [
            'amount', 'liberty_commission', 'final_liberty_rev',
            'ro_profit', 'liberty_profit'
        ])
        self._coerce_numeric_columns(self.nibss_unity_settlement_df, [
            'Tran_Amount_Req', 'Merchant_Receivable', 'Merchant_Discount'
        ])
        self._coerce_numeric_columns(self.unity_settlement, ['Tran_Amount_Req'])
        self._coerce_numeric_columns(self.parallex_nibss, [
            'Tran_Amount_Req', 'Merchant_Receivable', 'Merchant_Discount'
        ])

        if 'Transaction Narration' in self.collection_account_unity.columns:
            self.collection_account_unity['Transaction Narration'] = self._safe_str_series(
                self.collection_account_unity['Transaction Narration']
            )
        if 'Transaction Narration' in self.collection_account_parallex.columns:
            self.collection_account_parallex['Transaction Narration'] = self._safe_str_series(
                self.collection_account_parallex['Transaction Narration']
            )
        
        # Filter by run date
        self.card_df = self.card_df[self.card_df['date_created'] == self.run_date]
    
    def _process_card_transactions(self):
        """Process card transactions and separate by type."""
        # Filter successful transactions
        cashout_trans = self.card_df[self.card_df['host_resp_code'] == 0]
        self.cashout_trans = cashout_trans
        
        # PAYBOX transactions
        paybox_trans = cashout_trans[cashout_trans['type_of_user'] == 'MERCHANT']
        self.results['paybox_trans_df'] = paybox_trans.agg({
            'amount': 'sum',
            'id': 'count',
            'liberty_commission': 'sum',
            'final_liberty_rev': 'sum',
            'ro_profit': 'sum',
            'liberty_profit': 'sum'
        }).to_frame().T.round(2)
        
        # Separate by merchant ID
        self.interswitch_unity = cashout_trans[
            cashout_trans['merchant_id'] == self.merchant_id_interswitch_unity
        ]
        self.nibss_unity = cashout_trans[
            cashout_trans['merchant_id'] == self.merchant_id_nibss_unity
        ]
        self.nibss_parallex = cashout_trans[
            cashout_trans['merchant_id'] == self.merchant_id_nibss_parallex
        ]
        
        # Process Interswitch Unity
        self.interswitch_unity = self.interswitch_unity.copy()
        self.interswitch_unity['fee'] = self.interswitch_unity['liberty_commission']
        self.interswitch_unity['cost_of_acquisition'] = 17
        self.interswitch_unity['agent_commission'] = 3
        self.interswitch_unity['Gross'] = (
            self.interswitch_unity['fee'] 
            - self.interswitch_unity['cost_of_acquisition'] 
            - self.interswitch_unity['agent_commission']
        ).round(2)
        
        # Process NIBSS Unity
        self.nibss_unity = self.nibss_unity.copy()
        self.nibss_unity['fee'] = self.nibss_unity['liberty_commission']
        self.nibss_unity['cost_of_acquisition'] = self.nibss_unity['amount'] * 0.0022
        self.nibss_unity['agent_commission'] = self.nibss_unity['ro_profit']
        self.nibss_unity['Gross'] = (
            self.nibss_unity['fee'] 
            - self.nibss_unity['cost_of_acquisition'] 
            - self.nibss_unity['agent_commission']
        ).round(2)
        
        # Process NIBSS Parallex
        self.nibss_parallex = self.nibss_parallex.copy()
        self.nibss_parallex['fee'] = self.nibss_parallex['liberty_commission']
        self.nibss_parallex['cost_of_acquisition'] = self.nibss_parallex['amount'] * 0.0022
        self.nibss_parallex['agent_commission'] = self.nibss_parallex['ro_profit']
        self.nibss_parallex['Gross'] = (
            self.nibss_parallex['fee'] 
            - self.nibss_parallex['cost_of_acquisition'] 
            - self.nibss_parallex['agent_commission']
        ).round(2)
        
        # Aggregate results
        self.results['interswitch_unity_df'] = self.interswitch_unity.agg({
            'amount': 'sum',
            'id': 'count',
            'fee': 'sum',
            'cost_of_acquisition': 'sum',
            'agent_commission': 'sum',
            'Gross': 'sum'
        }).to_frame().T.round(2)
        
        self.results['nibss_unity_df'] = self.nibss_unity.agg({
            'amount': 'sum',
            'id': 'count',
            'fee': 'sum',
            'cost_of_acquisition': 'sum',
            'agent_commission': 'sum',
            'Gross': 'sum'
        }).to_frame().T.round(2)
        
        self.results['nibss_parallex_df'] = self.nibss_parallex.agg({
            'amount': 'sum',
            'id': 'count',
            'fee': 'sum',
            'cost_of_acquisition': 'sum',
            'agent_commission': 'sum',
            'Gross': 'sum'
        }).to_frame().T.round(2)
    
    def _process_settlements(self):
        """Process settlement reports."""
        # Unity NIBSS Settlement
        nibss_unity_sett = self.nibss_unity_settlement_df[
            self.nibss_unity_settlement_df['Local_Date_Time'].dt.date == self.run_date
        ]
        nibss_unity_sett = nibss_unity_sett[
            nibss_unity_sett['Merchant_ID'] == self.merchant_id_nibss_unity
        ]
        nibss_unity_sett = nibss_unity_sett.drop_duplicates()
        
        self.results['nibss_unity_settlement'] = nibss_unity_sett.agg({
            'Tran_Amount_Req': 'sum',
            'Merchant_ID': 'count',
            'Merchant_Receivable': 'sum',
            'Merchant_Discount': 'sum'
        }).to_frame().T.round(2)
        
        # NIBSS Unity Reconciliation
        recon_df = self.nibss_unity.merge(
            nibss_unity_sett,
            how='outer',
            left_on='reference_number',
            right_on='Retrieval_Reference_Nr',
            indicator=True
        )
        
        self.results['unsettled_claim'] = recon_df[recon_df['_merge'] == 'left_only'][[
            'date_created', 'reference_number', 'stan', 'amount', 'merchant_id', 'terminal_id', 'pan_number'
        ]]
        
        self.results['charge_back'] = recon_df[recon_df['_merge'] == 'right_only'][[
            'Local_Date_Time', 'Terminal_ID', 'Merchant_ID', 'STAN', 'PAN', 'Tran_Amount_Req', 'Retrieval_Reference_Nr'
        ]]
        
        # Unity Interswitch Settlement
        unity_isw = self.unity_settlement[
            self.unity_settlement['Local_Date_Time'].dt.date == self.run_date
        ].drop_duplicates()
        
        self.results['unity_isw_agg'] = unity_isw.agg({
            'Tran_Amount_Req': 'sum',
            'Merchant_ID': 'count'
        }).to_frame().T
        
        # ISW Reconciliation
        self.isw_recon = self.interswitch_unity.merge(
            unity_isw,
            how='inner',
            left_on='reference_number',
            right_on='Retrieval_Reference_Nr'
        )
        
        isw_recon_df = self.interswitch_unity.merge(
            unity_isw,
            how='outer',
            left_on='reference_number',
            right_on='Retrieval_Reference_Nr',
            indicator=True
        )
        
        self.results['isw_unsettled_claim'] = isw_recon_df[isw_recon_df['_merge'] == 'left_only'][[
            'date_created', 'reference_number', 'stan', 'amount', 'merchant_id', 'terminal_id', 'pan_number'
        ]]
        
        self.results['isw_charge_back'] = isw_recon_df[isw_recon_df['_merge'] == 'right_only'][[
            'Local_Date_Time', 'Terminal_ID', 'Merchant_ID', 'STAN', 'PAN', 'Tran_Amount_Req', 'Retrieval_Reference_Nr'
        ]]
        
        # Parallex NIBSS Settlement
        parallex_df = self.parallex_nibss[
            self.parallex_nibss['Local_Date_Time'].dt.date == self.run_date
        ]
        parallex_df = parallex_df[
            parallex_df['Merchant_ID'] == self.merchant_id_nibss_parallex
        ].drop_duplicates()
        
        self.results['parallex_nibss_df'] = parallex_df.agg({
            'Tran_Amount_Req': 'sum',
            'Merchant_ID': 'count',
            'Merchant_Receivable': 'sum',
            'Merchant_Discount': 'sum'
        }).to_frame().T.round(2)
        
        # Parallex Reconciliation
        parallex_recon_df = self.nibss_parallex.merge(
            parallex_df,
            how='outer',
            left_on='reference_number',
            right_on='Retrieval_Reference_Nr',
            indicator=True
        )
        
        self.results['parallex_unsettled_claim'] = parallex_recon_df[
            parallex_recon_df['_merge'] == 'left_only'
        ][['date_created', 'reference_number', 'stan', 'amount', 'merchant_id', 'terminal_id', 'pan_number']]
        
        self.results['parallex_charge_back'] = parallex_recon_df[
            parallex_recon_df['_merge'] == 'right_only'
        ][['Local_Date_Time', 'Terminal_ID', 'Merchant_ID', 'STAN', 'PAN', 'Tran_Amount_Req', 'Retrieval_Reference_Nr']]
        
        # Store unity_isw for later use
        self.unity_isw = unity_isw
    
    def _process_bank_statements(self):
        """Process bank statements."""
        # Unity Interswitch Account
        narration_series = self._safe_str_series(
            self.collection_account_unity['Transaction Narration']
        )
        isw_collection = self.collection_account_unity[
            narration_series.str.upper().str.startswith('2LBP')
        ]
        
        # Fix narration
        isw_narration = self._safe_str_series(isw_collection['Transaction Narration'])
        fixed_narration = isw_narration.str.replace(
            r'(\d{9,12})\s+(\d{2}\s+\d{2}\s+\d{4}-)',
            r'\1 - \2',
            regex=True
        )
        
        isw_collection[['tid', 'stans', 'pan', 'rrn', 't_date', 'narration']] = (
            fixed_narration.str.split(r'\s*-\s*', expand=True)
        )
        isw_collection['rrn'] = isw_collection['rrn'].astype('int')
        
        # ISW Bank Reconciliation
        isw_b_recon = self.isw_recon.merge(
            isw_collection,
            how='inner',
            left_on='reference_number',
            right_on='rrn'
        )
        
        not_isw_b_recon = self.isw_recon.merge(
            isw_collection,
            how='outer',
            left_on='reference_number',
            right_on='rrn',
            indicator=True
        )
        
        not_isw_b_recon['t_date'] = pd.to_datetime(
            not_isw_b_recon['t_date'],
            format='%d %m %Y',
            errors='coerce'
        )
        
        self.results['isw_b_unsettled_claim'] = not_isw_b_recon[
            not_isw_b_recon['_merge'] == 'left_only'
        ][['date_created', 'reference_number', 'stan', 'amount', 'merchant_id', 'terminal_id', 'pan_number']]
        
        isw_b_charge_back = not_isw_b_recon[not_isw_b_recon['_merge'] == 'right_only'][[
            'Date', 'Transaction Narration', 'Reference', 'Value Date', 'Debit', 'Credit', 'Balance', 'rrn', 't_date'
        ]]
        
        # Filter by unique date
        if self.unity_isw.empty or self.unity_isw['Local_Date_Time'].isna().all():
            self.results['isw_b_charge_back'] = pd.DataFrame()
            self.results['nerf_nibss_b_credit'] = pd.DataFrame()
            self.results['being_nibss_summary'] = pd.DataFrame()
            self.results['cb'] = pd.DataFrame()
            self.results['tof_df'] = pd.DataFrame()
            self.results['ds'] = pd.DataFrame()
            return

        unique_date = self.unity_isw['Local_Date_Time'].dt.date.iloc[0]
        isw_b_charge_back = isw_b_charge_back[
            isw_b_charge_back['t_date'].dt.date == unique_date
        ]
        self.results['isw_b_charge_back'] = isw_b_charge_back
        
        # Process NIBSS Unity Bank Statement
        self._process_nibss_unity_bank_statement(unique_date)
        
        # Process charge backs and other items
        self._process_additional_bank_items(unique_date)
    
    def _process_nibss_unity_bank_statement(self, unique_date):
        """Process NIBSS Unity bank statement."""
        # Extract dates from transaction narration
        collection_unity = self.collection_account_unity.copy()
        narration_series = self._safe_str_series(collection_unity['Transaction Narration'])
        raw_date_series = narration_series.str.split('#').str.get(-3)
        raw_date_series = self._safe_str_series(raw_date_series)
        collection_unity['raw_date'] = (
            raw_date_series
            .str.strip()
            .str.replace(r"\s+", "", regex=True)
            .str.replace(r"\D", "", regex=True)
            .str[-8:]
        )
        
        collection_unity['new_date'] = collection_unity['raw_date'].apply(self._parse_mixed_date)
        
        # NERF NIBSS transactions
        nerf_nibss = collection_unity[
            narration_series.str.strip().str.endswith('NEFT', na=False)
        ].reset_index()
        
        grouped_nerf = nerf_nibss.groupby(['new_date'])['Credit'].sum().reset_index()
        nerf_nibss_b_credit = grouped_nerf[grouped_nerf['new_date'].dt.date == unique_date]
        self.results['nerf_nibss_b_credit'] = nerf_nibss_b_credit
        
        # BEING NIBSS transactions
        being_nibss = collection_unity[
            narration_series.str.strip().str.startswith('BEING', na=False)
        ].reset_index()
        
        being_nibss_summary = being_nibss.drop(columns=['raw_date', 'new_date'])
        being_nibss_summary['Value Date'] = pd.to_datetime(
            being_nibss_summary['Value Date'], errors='coerce'
        )
        being_nibss_summary = being_nibss_summary[
            being_nibss_summary['Value Date'].dt.date == unique_date
        ]
        self.results['being_nibss_summary'] = being_nibss_summary
        
        # Store for later use
        self.collection_account_unity = collection_unity
    
    def _process_additional_bank_items(self, unique_date):
        """Process charge backs, terminal owner fees, and daily sweeps."""
        # Charge backs
        narration_series = self._safe_str_series(
            self.collection_account_unity['Transaction Narration']
        )
        cb = self.collection_account_unity[
            narration_series.str.startswith('RVSL', na=False)
        ]
        
        cb_narration = self._safe_str_series(cb['Transaction Narration'])
        cb['raw_date'] = (
            cb_narration
            .str.split('-')
            .str[-2]
            .str[-11:]
            .str.strip(" ")
            .str.replace(r"\s+", "", regex=True)
            .str.replace(r"\D", "", regex=True)
        )
        
        cb['raw_date'] = cb['raw_date'].astype(str).str.zfill(8)
        cb['new_date'] = cb['raw_date'].apply(self._parse_mixed_date)
        cb['Value Date'] = pd.to_datetime(cb['Value Date'], errors='coerce')
        cb = cb[cb['Value Date'].dt.date == unique_date]
        self.results['cb'] = cb
        
        # Terminal owner fee
        isw_collection = self.collection_account_unity[
            narration_series.str.upper().str.startswith('2LBP')
        ]
        
        being_nibss = self.collection_account_unity[
            narration_series.str.strip().str.startswith('BEING', na=False)
        ]
        
        tof_df = self.collection_account_unity[
            narration_series.str.endswith('TRANSACTION', na=False)
        ]
        
        exclude_narrations = pd.concat([
            isw_collection['Transaction Narration'],
            being_nibss['Transaction Narration'],
            cb['Transaction Narration']
        ]).drop_duplicates()
        
        tof_df = tof_df[~tof_df['Transaction Narration'].isin(exclude_narrations)]
        tof_df['Value Date'] = pd.to_datetime(tof_df['Value Date'], errors='coerce')
        tof_df = tof_df[tof_df['Value Date'].dt.date == unique_date]
        self.results['tof_df'] = tof_df
        
        # Daily sweep
        ds = tof_df[self._safe_str_series(tof_df['Transaction Narration']).str.startswith('DAILY', na=False)]
        self.results['ds'] = ds
    
    def _parse_mixed_date(self, x):
        """Parse date string in various formats."""
        if pd.isna(x):
            return pd.NaT
        
        x = str(x).strip()
        
        if len(x) != 8 or not x.isdigit():
            return pd.NaT
        
        # YYYYMMDD
        if x.startswith(("19", "20")):
            return pd.to_datetime(x, format="%Y%m%d", errors="coerce")
        
        # Try DDMMYYYY
        dt = pd.to_datetime(x, format="%d%m%Y", errors="coerce")
        if not pd.isna(dt):
            return dt
        
        # Try MMDDYYYY
        return pd.to_datetime(x, format="%m%d%Y", errors="coerce")

    def get_debug_info(self) -> Dict:
        """Return debug info to validate filters and date alignment."""
        def summarize_dates(df: pd.DataFrame, column: str) -> Dict:
            if column not in df.columns:
                return {"column": column, "rows": len(df), "min": None, "max": None}
            series = pd.to_datetime(df[column], errors="coerce")
            series = series.dropna()
            if series.empty:
                return {"column": column, "rows": len(df), "min": None, "max": None}
            return {
                "column": column,
                "rows": len(df),
                "min": series.min().date().isoformat(),
                "max": series.max().date().isoformat()
            }

        def count_for_date(df: pd.DataFrame, column: str) -> int:
            if column not in df.columns:
                return 0
            dates = pd.to_datetime(df[column], errors="coerce").dt.date
            return int((dates == self.run_date).sum())

        def summarize_non_string(df: pd.DataFrame, column: str) -> Dict:
            if column not in df.columns:
                return {"column": column, "rows": len(df), "non_string_count": 0, "type_counts": {}}
            series = df[column]
            non_string = series[~series.apply(lambda x: isinstance(x, str) or pd.isna(x))]
            type_counts = non_string.apply(lambda x: type(x).__name__).value_counts().to_dict()
            return {
                "column": column,
                "rows": len(df),
                "non_string_count": int(non_string.shape[0]),
                "type_counts": type_counts
            }

        debug = {
            "run_date": self.run_date.isoformat(),
            "rows": {
                "card_df": len(self.raw_card_df),
                "nibss_unity_settlement_df": len(self.raw_nibss_unity_settlement_df),
                "unity_settlement": len(self.raw_unity_settlement),
                "parallex_nibss": len(self.raw_parallex_nibss),
                "collection_account_unity": len(self.raw_collection_account_unity),
                "collection_account_parallex": len(self.raw_collection_account_parallex)
            },
            "dates": {
                "card_df": summarize_dates(self.raw_card_df, "date_created"),
                "nibss_unity_settlement_df": summarize_dates(self.raw_nibss_unity_settlement_df, "Local_Date_Time"),
                "unity_settlement": summarize_dates(self.raw_unity_settlement, "Local_Date_Time"),
                "parallex_nibss": summarize_dates(self.raw_parallex_nibss, "Local_Date_Time")
            },
            "run_date_counts": {
                "card_df": count_for_date(self.raw_card_df, "date_created"),
                "nibss_unity_settlement_df": count_for_date(self.raw_nibss_unity_settlement_df, "Local_Date_Time"),
                "unity_settlement": count_for_date(self.raw_unity_settlement, "Local_Date_Time"),
                "parallex_nibss": count_for_date(self.raw_parallex_nibss, "Local_Date_Time")
            },
            "card_filters": {
                "card_df_filtered": len(self.card_df),
                "cashout_trans": len(getattr(self, "cashout_trans", pd.DataFrame())),
                "interswitch_unity": len(getattr(self, "interswitch_unity", pd.DataFrame())),
                "nibss_unity": len(getattr(self, "nibss_unity", pd.DataFrame())),
                "nibss_parallex": len(getattr(self, "nibss_parallex", pd.DataFrame()))
            },
            "merchant_ids": {
                "interswitch_unity": self.merchant_id_interswitch_unity,
                "nibss_unity": self.merchant_id_nibss_unity,
                "nibss_parallex": self.merchant_id_nibss_parallex
            },
            "data_quality": {
                "collection_account_unity": summarize_non_string(
                    self.raw_collection_account_unity, "Transaction Narration"
                ),
                "collection_account_parallex": summarize_non_string(
                    self.raw_collection_account_parallex, "Transaction Narration"
                )
            }
        }

        return debug
    
    def _generate_metrics(self):
        """Generate comprehensive metrics."""
        nibss_unity_df = self.results['nibss_unity_df']
        interswitch_unity_df = self.results['interswitch_unity_df']
        nibss_parallex_df = self.results['nibss_parallex_df']
        nibss_unity_settlement = self.results['nibss_unity_settlement']
        unity_isw_agg = self.results['unity_isw_agg']
        parallex_nibss_df = self.results['parallex_nibss_df']
        
        charge_back = self.results['charge_back']
        isw_charge_back = self.results['isw_charge_back']
        parallex_charge_back = self.results['parallex_charge_back']
        
        unsettled_claim = self.results['unsettled_claim']
        isw_unsettled_claim = self.results['isw_unsettled_claim']
        parallex_unsettled_claim = self.results['parallex_unsettled_claim']
        
        isw_b_unsettled_claim = self.results['isw_b_unsettled_claim']
        isw_b_charge_back = self.results['isw_b_charge_back']
        
        # Calculate totals
        total_revenue = (
            float(nibss_unity_df['Gross'].values[0])
            + float(interswitch_unity_df['Gross'].values[0])
            + float(nibss_parallex_df['Gross'].values[0])
        )
        
        total_settlement = (
            float(nibss_unity_settlement['Tran_Amount_Req'].values[0])
            + float(unity_isw_agg['Tran_Amount_Req'].values[0])
            + float(parallex_nibss_df['Tran_Amount_Req'].values[0])
        )
        
        total_settlement_charge_back = (
            (charge_back['Tran_Amount_Req'].sum() if not charge_back.empty else 0)
            + (isw_charge_back['Tran_Amount_Req'].sum() if not isw_charge_back.empty else 0)
            + (parallex_charge_back['Tran_Amount_Req'].sum() if not parallex_charge_back.empty else 0)
        )
        
        total_settlement_unsettled_claims = (
            (unsettled_claim['amount'].sum() if not unsettled_claim.empty else 0)
            + (isw_unsettled_claim['amount'].sum() if not isw_unsettled_claim.empty else 0)
            + (parallex_unsettled_claim['amount'].sum() if not parallex_unsettled_claim.empty else 0)
        )
        
        total_bank_isw_unsettled_claims = (
            isw_b_unsettled_claim['amount'].sum() if not isw_b_unsettled_claim.empty else 0
        )
        
        total_bank_isw_charge_back = (
            isw_b_charge_back['Credit'].sum() if not isw_b_charge_back.empty else 0
        )
        
        self.metrics = {
            "run_date": str(self.run_date),
            "total_revenue": float(total_revenue),
            "total_settlement": float(total_settlement),
            "total_settlement_charge_back": float(total_settlement_charge_back),
            "total_settlement_unsettled_claims": float(total_settlement_unsettled_claims),
            "total_bank_isw_unsettled_claims": float(total_bank_isw_unsettled_claims),
            "total_bank_isw_charge_back": float(total_bank_isw_charge_back),
            "channels": {
                "NIBSS": {
                    "revenue": float(nibss_unity_df['Gross'].values[0]),
                    "settlement": float(nibss_unity_settlement['Tran_Amount_Req'].values[0]),
                    "charge_back": float(charge_back['Tran_Amount_Req'].sum() if not charge_back.empty else 0),
                    "unsettled_claim": float(unsettled_claim['amount'].sum() if not unsettled_claim.empty else 0)
                },
                "INTERSWITCH": {
                    "revenue": float(interswitch_unity_df['Gross'].values[0]),
                    "settlement": float(unity_isw_agg['Tran_Amount_Req'].values[0]),
                    "charge_back": float(isw_charge_back['Tran_Amount_Req'].sum() if not isw_charge_back.empty else 0),
                    "unsettled_claim": float(isw_unsettled_claim['amount'].sum() if not isw_unsettled_claim.empty else 0)
                },
                "PARALLEX": {
                    "revenue": float(nibss_parallex_df['Gross'].values[0]),
                    "settlement": float(parallex_nibss_df['Tran_Amount_Req'].values[0]),
                    "charge_back": float(parallex_charge_back['Tran_Amount_Req'].sum() if not parallex_charge_back.empty else 0),
                    "unsettled_claim": float(parallex_unsettled_claim['amount'].sum() if not parallex_unsettled_claim.empty else 0)
                },
                "ISW Bank": {
                    "charge_back": float(isw_b_unsettled_claim['amount'].sum() if not isw_b_unsettled_claim.empty else 0),
                    "unsettled_claim": float(isw_b_charge_back['Credit'].sum() if not isw_b_charge_back.empty else 0)
                }
            }
        }
    
    def _prepare_output_datasets(self):
        """Prepare datasets for output with run_date column."""
        # Join tables for output
        nibss_parallex = pd.concat([
            self.results['nibss_parallex_df'],
            self.results['parallex_nibss_df']
        ], axis=1)
        
        nibss_unity = pd.concat([
            self.results['nibss_unity_df'],
            self.results['nibss_unity_settlement']
        ], axis=1)
        
        isw_unity = pd.concat([
            self.results['interswitch_unity_df'],
            self.results['unity_isw_agg']
        ], axis=1)
        
        nibss_reconciliation = pd.concat([
            self.results['unsettled_claim'],
            self.results['charge_back']
        ], axis=1)
        
        isw_reconciliation = pd.concat([
            self.results['isw_unsettled_claim'],
            self.results['isw_charge_back']
        ], axis=1)
        
        parallex_reconciliation = pd.concat([
            self.results['parallex_unsettled_claim'],
            self.results['parallex_charge_back']
        ], axis=1)
        
        isw_bank_reconciliation = pd.concat([
            self.results['isw_b_unsettled_claim'],
            self.results['isw_b_charge_back']
        ], axis=1)
        
        # Store final datasets
        self.output_datasets = {
            "paybox_trans_df": self.results['paybox_trans_df'],
            "nibss_parallex": nibss_parallex,
            "nibss_unity": nibss_unity,
            "nibss_reconciliation": nibss_reconciliation,
            "isw_reconciliation": isw_reconciliation,
            "parallex_reconciliation": parallex_reconciliation,
            "isw_bank_reconciliation": isw_bank_reconciliation,
            "nerf_nibss_b_credit": self.results['nerf_nibss_b_credit'],
            "being_nibss_summary": self.results['being_nibss_summary'],
            "cb": self.results['cb'],
            "tof_df": self.results['tof_df'],
            "ds": self.results['ds']
        }
        
        # Add run_date to all datasets
        for df in self.output_datasets.values():
            if not df.empty and "run_date" not in df.columns:
                df.insert(0, "run_date", self.run_date)
    
    def save_metrics_to_file(self) -> str:
        """Save metrics to JSON file."""
        os.makedirs(settings.output_dir, exist_ok=True)
        
        run_date_str = self.run_date.isoformat()
        metrics_path = os.path.join(settings.output_dir, f"metrics_{run_date_str}.json")
        
        def default_serializer(obj):
            if isinstance(obj, (date, datetime)):
                return obj.isoformat()
            raise TypeError(f"Type {type(obj)} not serializable")
        
        with open(metrics_path, "w") as f:
            json.dump(self.metrics, f, indent=2, default=default_serializer)
        
        return metrics_path
    
    def get_output_datasets(self) -> Dict[str, pd.DataFrame]:
        """Get all output datasets."""
        return self.output_datasets

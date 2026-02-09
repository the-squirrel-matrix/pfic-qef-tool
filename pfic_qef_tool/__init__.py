"""
PFIC QEF Tax Tool

A tool to assist U.S. taxpayers in calculating QEF (Qualified Electing Fund)
income and basis adjustments for PFIC (Passive Foreign Investment Company)
holdings.

DISCLAIMER: This tool is for informational purposes only and does not
constitute tax advice. Consult a qualified tax professional for your
specific situation.
"""

from .models import (
    Config,
    Lot,
    Transaction,
    TransactionType,
    AISData,
    UnderlyingPFIC,
    Form8621Data,
    SaleRecord,
    BasisAdjustmentRecord,
    LotActivityReport,
    GainType,
    LotStatus,
)

from .lot_tracker import LotTracker, process_transactions
from .currency import CurrencyConverter, BankOfCanadaRates, OfflineCurrencyConverter
from .qef_calculator import (
    calculate_lot_qef_income,
    apply_qef_adjustments,
    generate_form_8621_data,
)
from .reports import (
    generate_sales_report,
    generate_lot_activity_report,
    generate_text_summary,
)
from .serialization import (
    load_config,
    load_lots,
    load_transactions,
    load_ais_data,
    save_lots,
    save_form_8621_data,
    save_sales_report,
    save_lot_activity_report,
)
from .main import run_interactive

__version__ = "0.1.0"
__all__ = [
    # Models
    "Config",
    "Lot",
    "Transaction",
    "TransactionType",
    "AISData",
    "UnderlyingPFIC",
    "Form8621Data",
    "SaleRecord",
    "BasisAdjustmentRecord",
    "LotActivityReport",
    "GainType",
    "LotStatus",
    # Lot tracking
    "LotTracker",
    "process_transactions",
    # Currency
    "CurrencyConverter",
    "BankOfCanadaRates",
    "OfflineCurrencyConverter",
    # QEF calculations
    "calculate_lot_qef_income",
    "apply_qef_adjustments",
    "generate_form_8621_data",
    # Reports
    "generate_sales_report",
    "generate_lot_activity_report",
    "generate_text_summary",
    # Serialization
    "load_config",
    "load_lots",
    "load_transactions",
    "load_ais_data",
    "save_lots",
    "save_form_8621_data",
    "save_sales_report",
    "save_lot_activity_report",
    # Main
    "run_interactive",
]

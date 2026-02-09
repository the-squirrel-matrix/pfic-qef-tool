"""
Serialization utilities for reading and writing data files.

Handles JSON and CSV formats for all input/output data.
"""

import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional, Union

from .models import (
    Config, Lot, Transaction, TransactionType, AISData, UnderlyingPFIC,
    Form8621Data, SaleRecord, BasisAdjustmentRecord, LotActivityReport,
    GainType, LotStatus, round_money, round_shares
)


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal and date types."""
    
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, (GainType, LotStatus, TransactionType)):
            return obj.value
        return super().default(obj)


def _parse_decimal(value: Any) -> Decimal:
    """Parse a value to Decimal."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _parse_date(value: Any) -> date:
    """Parse a value to date."""
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"Cannot parse date from {value}")


# ============================================================================
# Config
# ============================================================================

def load_config(path: Union[str, Path]) -> Config:
    """Load configuration from JSON file."""
    with open(path, 'r') as f:
        data = json.load(f)
    
    return Config(
        pfic_ticker=data["pfic_ticker"],
        pfic_name=data["pfic_name"],
        default_currency=data.get("default_currency", "CAD"),
        tax_year=int(data["tax_year"]) if "tax_year" in data else None,
    )


def save_config(config: Config, path: Union[str, Path]):
    """Save configuration to JSON file."""
    data = {
        "pfic_ticker": config.pfic_ticker,
        "pfic_name": config.pfic_name,
        "default_currency": config.default_currency,
    }
    if config.tax_year is not None:
        data["tax_year"] = config.tax_year
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


# ============================================================================
# Lots
# ============================================================================

def load_lots(path: Union[str, Path, None], filter_ticker: Optional[str] = None) -> list[Lot]:
    """
    Load lots from JSON or CSV file (auto-detects based on extension).
    
    Returns empty list if path is None or file doesn't exist.
    If filter_ticker is provided, only returns lots matching that ticker.
    
    CSV format: lot_id, purchase_date, quantity, cost_basis_usd, ticker, original_lot_id (optional)
    """
    if path is None:
        return []
    
    path = Path(path)
    if not path.exists():
        return []
    
    # Only CSV format supported
    if path.suffix.lower() != '.csv':
        raise ValueError(f"Lot files must be in CSV format. Got: {path.suffix}")
    
    return _load_lots_csv(path, filter_ticker)


def _load_lots_csv(path: Path, filter_ticker: Optional[str] = None) -> list[Lot]:
    """Load lots from CSV file."""
    lots = []
    
    with open(path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            # Normalize column names
            row = {k.lower().strip(): v.strip() for k, v in row.items()}
            
            # Skip empty rows
            if not row.get("lot_id") or not row.get("purchase_date"):
                continue
            
            ticker = row.get("ticker", "").upper()
            
            # Filter by ticker if specified
            if filter_ticker and ticker and ticker != filter_ticker.upper():
                continue
            
            # Accept both "quantity" and "shares"
            quantity_str = row.get("quantity") or row.get("shares", "0")
            
            lot = Lot(
                lot_id=row["lot_id"],
                ticker=ticker,
                purchase_date=_parse_date(row["purchase_date"]),
                shares=_parse_decimal(quantity_str),
                cost_basis_usd=_parse_decimal(row["cost_basis_usd"]),
                original_lot_id=row.get("original_lot_id") or None,
            )
            lots.append(lot)
    
    return lots


def save_lots(lots: list[Lot], path: Union[str, Path]):
    """Save lots to CSV file."""
    path = Path(path)
    
    # Ensure .csv extension
    if path.suffix.lower() != '.csv':
        path = path.with_suffix('.csv')
    
    _save_lots_csv(lots, path)


def _save_lots_csv(lots: list[Lot], path: Path):
    """Save lots to CSV file."""
    fieldnames = ["lot_id", "ticker", "purchase_date", "quantity", "cost_basis_usd", "original_lot_id"]
    
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for lot in lots:
            row = {
                "lot_id": lot.lot_id,
                "ticker": lot.ticker or "",
                "purchase_date": lot.purchase_date.isoformat(),
                "quantity": str(lot.shares),
                "cost_basis_usd": str(lot.cost_basis_usd),
                "original_lot_id": lot.original_lot_id or "",
            }
            writer.writerow(row)


# ============================================================================
# Transactions
# ============================================================================

def load_transactions(
    path: Union[str, Path, None], 
    default_currency: str = "CAD",
    filter_ticker: Optional[str] = None,
) -> list[Transaction]:
    """
    Load transactions from CSV file.
    
    Returns empty list if path is None or file doesn't exist.
    If filter_ticker is provided, only returns transactions matching that ticker.
    
    Expected columns: date, type, ticker, quantity, amount, fees, currency, exchange_rate (optional)
    Note: Also accepts legacy column names "shares" (for quantity) and "commission" (for fees).
    Date format: YYYY-MM-DD preferred, but other formats are accepted.
    """
    if path is None:
        return []
    
    path = Path(path)
    if not path.exists():
        return []
    
    transactions = []
    skipped_tickers = set()
    
    with open(path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            # Normalize column names (handle case variations)
            row = {k.lower().strip(): v.strip() for k, v in row.items()}
            
            # Skip empty rows or comment lines
            if not row.get("date") or not row.get("type"):
                continue
            if row.get("date", "").startswith("#"):
                continue
            
            ticker = row.get("ticker", "").upper()
            
            # Filter by ticker if specified, but warn about skipped tickers
            if filter_ticker and ticker and ticker != filter_ticker.upper():
                skipped_tickers.add(ticker)
                continue
            
            txn_type_str = row.get("type", "").upper()
            if txn_type_str == "BUY":
                txn_type = TransactionType.BUY
            elif txn_type_str == "SELL":
                txn_type = TransactionType.SELL
            else:
                # Skip unknown transaction types (e.g., DIST, DIV, etc.)
                continue
            
            currency = row.get("currency", default_currency).upper()
            
            # Parse quantity (accept both "quantity" and legacy "shares")
            quantity_str = row.get("quantity") or row.get("shares", "0")
            quantity = _parse_decimal(quantity_str)
            
            # Parse amount
            amount = _parse_decimal(row["amount"])
            
            # Parse fees (accept both "fees" and legacy "commission")
            fees_str = row.get("fees") or row.get("commission", "0")
            fees = _parse_decimal(fees_str)
            
            # Check for negative values and warn
            if quantity < 0:
                print(f"WARNING: Negative quantity {quantity} on {row['date']} - using absolute value")
                quantity = abs(quantity)
            if amount < 0:
                print(f"WARNING: Negative amount {amount} on {row['date']} - using absolute value")
                amount = abs(amount)
            if fees < 0:
                print(f"WARNING: Negative fees {fees} on {row['date']} - using absolute value")
                fees = abs(fees)
            
            # Parse optional exchange rate
            exchange_rate_str = row.get("exchange_rate", "").strip()
            if exchange_rate_str:
                exchange_rate = _parse_decimal(exchange_rate_str)
            else:
                exchange_rate = None
            
            txn = Transaction(
                date=_parse_date(row["date"]),
                transaction_type=txn_type,
                ticker=ticker,
                shares=quantity,
                amount=amount,
                commission=fees,
                currency=currency,
                exchange_rate=exchange_rate,
            )
            transactions.append(txn)
    
    # Warn about skipped tickers at the end
    if skipped_tickers:
        print(f"WARNING: Skipped transactions for ticker(s): {', '.join(sorted(skipped_tickers))}")
        print(f"         Only processing {filter_ticker}. Run separately for each PFIC.")
    
    return transactions


def save_transactions(transactions: list[Transaction], path: Union[str, Path]):
    """Save transactions to CSV file."""
    fieldnames = ["date", "type", "ticker", "quantity", "amount", "fees", "currency",
                  "amount_usd", "fees_usd", "exchange_rate"]
    
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for txn in transactions:
            row = {
                "date": txn.date.isoformat(),
                "type": txn.transaction_type.value,
                "ticker": txn.ticker,
                "quantity": str(txn.shares),
                "amount": str(txn.amount),
                "fees": str(txn.commission),
                "currency": txn.currency,
                "amount_usd": str(txn.amount_usd) if txn.amount_usd else "",
                "fees_usd": str(txn.commission_usd) if txn.commission_usd else "",
                "exchange_rate": str(txn.exchange_rate) if txn.exchange_rate else "",
            }
            writer.writerow(row)


# ============================================================================
# AIS Data
# ============================================================================

def load_ais_data(path: Union[str, Path]) -> AISData:
    """Load AIS data from JSON file."""
    with open(path, 'r') as f:
        data = json.load(f)
    
    underlying = []
    for u in data.get("underlying_pfics", []):
        underlying.append(UnderlyingPFIC(
            fund_ticker=u["fund_ticker"],
            fund_name=u["fund_name"],
            ordinary_earnings_per_day_per_share_usd=_parse_decimal(
                u["ordinary_earnings_per_day_per_share_usd"]
            ),
            net_capital_gains_per_day_per_share_usd=_parse_decimal(
                u["net_capital_gains_per_day_per_share_usd"]
            ),
        ))
    
    return AISData(
        tax_year=int(data["tax_year"]),
        fund_ticker=data["fund_ticker"],
        fund_name=data["fund_name"],
        ordinary_earnings_per_day_per_share_usd=_parse_decimal(
            data["ordinary_earnings_per_day_per_share_usd"]
        ),
        net_capital_gains_per_day_per_share_usd=_parse_decimal(
            data["net_capital_gains_per_day_per_share_usd"]
        ),
        total_distributions_per_share_usd=_parse_decimal(
            data["total_distributions_per_share_usd"]
        ),
        underlying_pfics=underlying,
    )


def save_ais_data(ais: AISData, path: Union[str, Path]):
    """Save AIS data to JSON file."""
    data = {
        "tax_year": ais.tax_year,
        "year_days": ais.year_days,
        "fund_ticker": ais.fund_ticker,
        "fund_name": ais.fund_name,
        "ordinary_earnings_per_day_per_share_usd": str(
            ais.ordinary_earnings_per_day_per_share_usd
        ),
        "net_capital_gains_per_day_per_share_usd": str(
            ais.net_capital_gains_per_day_per_share_usd
        ),
        "total_distributions_per_share_usd": str(
            ais.total_distributions_per_share_usd
        ),
        "underlying_pfics": [
            {
                "fund_ticker": u.fund_ticker,
                "fund_name": u.fund_name,
                "ordinary_earnings_per_day_per_share_usd": str(
                    u.ordinary_earnings_per_day_per_share_usd
                ),
                "net_capital_gains_per_day_per_share_usd": str(
                    u.net_capital_gains_per_day_per_share_usd
                ),
            }
            for u in ais.underlying_pfics
        ],
    }
    
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


# ============================================================================
# Form 8621 Data
# ============================================================================

def save_form_8621_data(data: list[Form8621Data], path: Union[str, Path]):
    """Save Form 8621 data to JSON file."""
    output = []
    for f in data:
        item = {
            "fund_ticker": f.fund_ticker,
            "fund_name": f.fund_name,
            "is_direct_holding": f.is_direct_holding,
            "line_6a_ordinary_earnings_usd": str(f.line_6a_ordinary_earnings_usd),
            "line_6b_portion_distributed_usd": str(f.line_6b_portion_distributed_usd),
            "line_6c_tax_on_6a_usd": str(f.line_6c_tax_on_6a_usd),
            "line_7a_net_capital_gains_usd": str(f.line_7a_net_capital_gains_usd),
            "line_7b_portion_distributed_usd": str(f.line_7b_portion_distributed_usd),
            "line_7c_tax_on_7a_usd": str(f.line_7c_tax_on_7a_usd),
        }
        output.append(item)
    
    with open(path, 'w') as f:
        json.dump(output, f, indent=2)


def save_form_8621_csv(data: list[Form8621Data], path: Union[str, Path]):
    """Save Form 8621 data to CSV file."""
    fieldnames = [
        "fund_ticker", "fund_name", "is_direct_holding",
        "line_6a_ordinary_earnings_usd", "line_6b_portion_distributed_usd",
        "line_6c_tax_on_6a_usd",
        "line_7a_net_capital_gains_usd", "line_7b_portion_distributed_usd",
        "line_7c_tax_on_7a_usd",
    ]
    
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for form in data:
            row = {
                "fund_ticker": form.fund_ticker,
                "fund_name": form.fund_name,
                "is_direct_holding": str(form.is_direct_holding),
                "line_6a_ordinary_earnings_usd": str(form.line_6a_ordinary_earnings_usd),
                "line_6b_portion_distributed_usd": str(form.line_6b_portion_distributed_usd),
                "line_6c_tax_on_6a_usd": str(form.line_6c_tax_on_6a_usd),
                "line_7a_net_capital_gains_usd": str(form.line_7a_net_capital_gains_usd),
                "line_7b_portion_distributed_usd": str(form.line_7b_portion_distributed_usd),
                "line_7c_tax_on_7a_usd": str(form.line_7c_tax_on_7a_usd),
            }
            writer.writerow(row)


# ============================================================================
# Sales Report
# ============================================================================

def save_sales_report(sales: list[SaleRecord], path: Union[str, Path]):
    """Save sales report to JSON file."""
    output = []
    for s in sales:
        item = {
            "lot_id": s.lot_id,
            "original_lot_id": s.original_lot_id,
            "purchase_date": s.purchase_date.isoformat(),
            "sale_date": s.sale_date.isoformat(),
            "shares_sold": str(s.shares_sold),
            "cost_basis_usd": str(s.cost_basis_usd),
            "cost_basis_adjusted_usd": str(s.cost_basis_adjusted_usd),
            "proceeds_usd": str(s.proceeds_usd),
            "gain_loss_usd": str(s.gain_loss_usd),
            "gain_type": s.gain_type.value,
            "holding_period_days": s.holding_period_days,
        }
        output.append(item)
    
    with open(path, 'w') as f:
        json.dump(output, f, indent=2)


def save_sales_csv(sales: list[SaleRecord], path: Union[str, Path]):
    """Save sales report to CSV file."""
    fieldnames = [
        "lot_id", "original_lot_id", "purchase_date", "sale_date",
        "shares_sold", "cost_basis_usd", "cost_basis_adjusted_usd",
        "proceeds_usd", "gain_loss_usd", "gain_type", "holding_period_days"
    ]
    
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for s in sales:
            row = {
                "lot_id": s.lot_id,
                "original_lot_id": s.original_lot_id or "",
                "purchase_date": s.purchase_date.isoformat(),
                "sale_date": s.sale_date.isoformat(),
                "shares_sold": str(s.shares_sold),
                "cost_basis_usd": str(s.cost_basis_usd),
                "cost_basis_adjusted_usd": str(s.cost_basis_adjusted_usd),
                "proceeds_usd": str(s.proceeds_usd),
                "gain_loss_usd": str(s.gain_loss_usd),
                "gain_type": s.gain_type.value,
                "holding_period_days": s.holding_period_days,
            }
            writer.writerow(row)


# ============================================================================
# Basis Adjustments
# ============================================================================

def save_basis_adjustments(adjustments: list[BasisAdjustmentRecord], 
                          path: Union[str, Path]):
    """Save basis adjustments to JSON file."""
    output = []
    for a in adjustments:
        item = {
            "lot_id": a.lot_id,
            "shares": str(a.shares),
            "days_held_in_year": a.days_held_in_year,
            "ordinary_earnings_usd": str(a.ordinary_earnings_usd),
            "capital_gains_usd": str(a.capital_gains_usd),
            "distributions_usd": str(a.distributions_usd),
            "net_adjustment_usd": str(a.net_adjustment_usd),
            "basis_before_usd": str(a.basis_before_usd),
            "basis_after_usd": str(a.basis_after_usd),
            "earnings_by_pfic": {k: str(v) for k, v in a.earnings_by_pfic.items()},
            "gains_by_pfic": {k: str(v) for k, v in a.gains_by_pfic.items()},
        }
        output.append(item)
    
    with open(path, 'w') as f:
        json.dump(output, f, indent=2)


# ============================================================================
# Full Report
# ============================================================================

def save_lot_activity_report(report: LotActivityReport, path: Union[str, Path]):
    """Save complete lot activity report to JSON file."""
    data = {
        "tax_year": report.tax_year,
        "pfic_ticker": report.pfic_ticker,
        "pfic_name": report.pfic_name,
        "beginning_lots": [
            {
                "lot_id": lot.lot_id,
                "purchase_date": lot.purchase_date.isoformat(),
                "shares": str(lot.shares),
                "cost_basis_usd": str(lot.cost_basis_usd),
                "original_lot_id": lot.original_lot_id,
            }
            for lot in report.beginning_lots
        ],
        "transactions_processed": [
            {
                "date": txn.date.isoformat(),
                "type": txn.transaction_type.value,
                "shares": str(txn.shares),
                "amount_usd": str(txn.amount_usd) if txn.amount_usd else None,
                "commission_usd": str(txn.commission_usd) if txn.commission_usd else None,
            }
            for txn in report.transactions_processed
        ],
        "lots_created": [
            {
                "lot_id": lot.lot_id,
                "purchase_date": lot.purchase_date.isoformat(),
                "shares": str(lot.shares),
                "cost_basis_usd": str(lot.cost_basis_usd),
                "original_lot_id": lot.original_lot_id,
            }
            for lot in report.lots_created
        ],
        "lots_sold": [
            {
                "lot_id": s.lot_id,
                "original_lot_id": s.original_lot_id,
                "purchase_date": s.purchase_date.isoformat(),
                "sale_date": s.sale_date.isoformat(),
                "shares_sold": str(s.shares_sold),
                "cost_basis_usd": str(s.cost_basis_usd),
                "cost_basis_adjusted_usd": str(s.cost_basis_adjusted_usd),
                "proceeds_usd": str(s.proceeds_usd),
                "gain_loss_usd": str(s.gain_loss_usd),
                "gain_type": s.gain_type.value,
                "holding_period_days": s.holding_period_days,
            }
            for s in report.lots_sold
        ],
        "basis_adjustments": [
            {
                "lot_id": a.lot_id,
                "shares": str(a.shares),
                "days_held_in_year": a.days_held_in_year,
                "ordinary_earnings_usd": str(a.ordinary_earnings_usd),
                "capital_gains_usd": str(a.capital_gains_usd),
                "distributions_usd": str(a.distributions_usd),
                "net_adjustment_usd": str(a.net_adjustment_usd),
                "basis_before_usd": str(a.basis_before_usd),
                "basis_after_usd": str(a.basis_after_usd),
            }
            for a in report.basis_adjustments
        ],
        "ending_lots": [
            {
                "lot_id": lot.lot_id,
                "purchase_date": lot.purchase_date.isoformat(),
                "shares": str(lot.shares),
                "cost_basis_usd": str(lot.cost_basis_usd),
                "original_lot_id": lot.original_lot_id,
            }
            for lot in report.ending_lots
        ],
        "form_8621_data": [
            {
                "fund_ticker": f.fund_ticker,
                "fund_name": f.fund_name,
                "is_direct_holding": f.is_direct_holding,
                "line_6a_ordinary_earnings_usd": str(f.line_6a_ordinary_earnings_usd),
                "line_6b_portion_distributed_usd": str(f.line_6b_portion_distributed_usd),
                "line_6c_tax_on_6a_usd": str(f.line_6c_tax_on_6a_usd),
                "line_7a_net_capital_gains_usd": str(f.line_7a_net_capital_gains_usd),
                "line_7b_portion_distributed_usd": str(f.line_7b_portion_distributed_usd),
                "line_7c_tax_on_7a_usd": str(f.line_7c_tax_on_7a_usd),
            }
            for f in report.form_8621_data
        ],
    }
    
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

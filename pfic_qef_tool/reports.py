"""
Report generation for PFIC QEF tax tool.

Generates structured report data that can be serialized to JSON/CSV
or formatted for human-readable output.
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from .models import (
    Lot, Transaction, AISData, Config,
    Form8621Data, SaleRecord, BasisAdjustmentRecord, LotActivityReport,
    GainType, LotStatus, round_money
)
from .lot_tracker import LotTracker, UNKNOWN_PURCHASE_DATE


def generate_sales_report(tracker: LotTracker) -> list[SaleRecord]:
    """
    Generate sales records for all sold lots.
    
    Each record contains all information needed for tax reporting.
    """
    records = []
    
    for lot in tracker.sold_lots:
        if lot.sale_date is None or lot.proceeds_usd is None:
            continue
        
        gain_type = lot.gain_type
        if gain_type is None:
            gain_type = GainType.SHORT_TERM  # Default
        
        holding_days = lot.holding_period_days
        if holding_days is None:
            holding_days = 0
        
        record = SaleRecord(
            lot_id=lot.lot_id,
            original_lot_id=lot.original_lot_id,
            purchase_date=lot.purchase_date,
            sale_date=lot.sale_date,
            shares_sold=lot.shares,
            cost_basis_usd=lot.cost_basis_usd,
            cost_basis_adjusted_usd=lot.adjusted_cost_basis_usd,
            proceeds_usd=lot.proceeds_usd,
            gain_loss_usd=lot.gain_loss_usd or Decimal("0"),
            gain_type=gain_type,
            holding_period_days=holding_days,
        )
        records.append(record)
    
    # Sort by sale date, then lot ID
    records.sort(key=lambda r: (r.sale_date, r.lot_id))
    
    return records


def generate_lot_activity_report(
    config: Config,
    beginning_lots: list[Lot],
    transactions: list[Transaction],
    tracker: LotTracker,
    adjustments: list[BasisAdjustmentRecord],
    form_8621_data: list[Form8621Data],
    tax_year: Optional[int] = None,
) -> LotActivityReport:
    """
    Generate comprehensive lot activity report for the year.
    
    Shows what happened to each lot: beginning state, transactions,
    basis adjustments, and ending state.
    """
    # Use provided tax_year or fall back to config
    year = tax_year if tax_year is not None else (config.tax_year if config.tax_year else 2024)
    
    # Identify lots created this year
    year_start = date(year, 1, 1)
    beginning_lot_ids = {lot.lot_id for lot in beginning_lots}
    
    lots_created = []
    for lot in tracker.all_lots:
        # A lot was "created" if:
        # - It wasn't in beginning_lots AND
        # - It was purchased this year OR it's a split remainder
        if lot.lot_id not in beginning_lot_ids:
            if lot.purchase_date >= year_start or lot.original_lot_id:
                lots_created.append(lot)
    
    # Generate sales records
    sales = generate_sales_report(tracker)
    
    # Get ending lots
    ending_lots = tracker.get_ending_lots()
    
    return LotActivityReport(
        tax_year=year,
        pfic_ticker=config.pfic_ticker,
        pfic_name=config.pfic_name,
        beginning_lots=beginning_lots,
        transactions_processed=transactions,
        lots_created=lots_created,
        lots_sold=sales,
        basis_adjustments=adjustments,
        ending_lots=ending_lots,
        form_8621_data=form_8621_data,
    )


def summarize_form_8621(form_data: list[Form8621Data]) -> dict:
    """
    Create a summary of all Form 8621 data.
    
    Returns dict with totals and per-PFIC breakdown.
    """
    total_ordinary = Decimal("0")
    total_gains = Decimal("0")
    direct_count = 0
    indirect_count = 0
    
    pfic_details = []
    
    for f in form_data:
        total_ordinary += f.line_6a_ordinary_earnings_usd
        total_gains += f.line_7a_net_capital_gains_usd
        
        if f.is_direct_holding:
            direct_count += 1
        else:
            indirect_count += 1
        
        pfic_details.append({
            "ticker": f.fund_ticker,
            "name": f.fund_name,
            "is_direct": f.is_direct_holding,
            "ordinary_earnings": str(f.line_6a_ordinary_earnings_usd),
            "capital_gains": str(f.line_7a_net_capital_gains_usd),
            "total_income": str(
                f.line_6a_ordinary_earnings_usd + f.line_7a_net_capital_gains_usd
            ),
        })
    
    return {
        "total_ordinary_earnings": str(round_money(total_ordinary)),
        "total_capital_gains": str(round_money(total_gains)),
        "total_qef_income": str(round_money(total_ordinary + total_gains)),
        "direct_pfic_count": direct_count,
        "indirect_pfic_count": indirect_count,
        "total_form_count": len(form_data),
        "pfics": pfic_details,
    }


def summarize_sales(sales: list[SaleRecord]) -> dict:
    """
    Create a summary of all sales.
    
    Returns dict with totals for short-term and long-term gains.
    """
    short_term_gains = Decimal("0")
    short_term_losses = Decimal("0")
    long_term_gains = Decimal("0")
    long_term_losses = Decimal("0")
    total_proceeds = Decimal("0")
    total_cost_basis = Decimal("0")
    
    for sale in sales:
        total_proceeds += sale.proceeds_usd
        total_cost_basis += sale.cost_basis_adjusted_usd
        
        if sale.gain_type == GainType.SHORT_TERM:
            if sale.gain_loss_usd >= 0:
                short_term_gains += sale.gain_loss_usd
            else:
                short_term_losses += abs(sale.gain_loss_usd)
        else:
            if sale.gain_loss_usd >= 0:
                long_term_gains += sale.gain_loss_usd
            else:
                long_term_losses += abs(sale.gain_loss_usd)
    
    net_short_term = short_term_gains - short_term_losses
    net_long_term = long_term_gains - long_term_losses
    
    return {
        "total_sales": len(sales),
        "total_proceeds": str(round_money(total_proceeds)),
        "total_cost_basis": str(round_money(total_cost_basis)),
        "short_term": {
            "gains": str(round_money(short_term_gains)),
            "losses": str(round_money(short_term_losses)),
            "net": str(round_money(net_short_term)),
        },
        "long_term": {
            "gains": str(round_money(long_term_gains)),
            "losses": str(round_money(long_term_losses)),
            "net": str(round_money(net_long_term)),
        },
        "net_gain_loss": str(round_money(net_short_term + net_long_term)),
    }


def summarize_lots(lots: list[Lot]) -> dict:
    """
    Create a summary of lot positions.
    """
    total_shares = Decimal("0")
    total_basis = Decimal("0")
    
    for lot in lots:
        total_shares += lot.shares
        total_basis += lot.cost_basis_usd
    
    return {
        "lot_count": len(lots),
        "total_shares": str(total_shares),
        "total_cost_basis": str(round_money(total_basis)),
    }


def _format_purchase_date(purchase_date: date) -> str:
    """Format a purchase date, handling unknown dates."""
    if purchase_date == UNKNOWN_PURCHASE_DATE:
        return "UNKNOWN"
    return str(purchase_date)


def generate_text_summary(report: LotActivityReport) -> str:
    """
    Generate a human-readable text summary of the year's activity.
    """
    lines = []
    lines.append("=" * 70)
    lines.append(f"PFIC QEF Tax Report - Tax Year {report.tax_year}")
    lines.append(f"Fund: {report.pfic_name} ({report.pfic_ticker})")
    lines.append("=" * 70)
    lines.append("")
    
    # Beginning position
    lines.append("BEGINNING OF YEAR POSITION")
    lines.append("-" * 40)
    if report.beginning_lots:
        total_shares = sum(lot.shares for lot in report.beginning_lots)
        total_basis = sum(lot.cost_basis_usd for lot in report.beginning_lots)
        lines.append(f"  Lots: {len(report.beginning_lots)}")
        lines.append(f"  Total Shares: {total_shares}")
        lines.append(f"  Total Cost Basis: ${total_basis:,.2f}")
    else:
        lines.append("  No lots at beginning of year")
    lines.append("")
    
    # Transactions
    lines.append("TRANSACTIONS")
    lines.append("-" * 40)
    if report.transactions_processed:
        for txn in sorted(report.transactions_processed, key=lambda t: t.date):
            lines.append(
                f"  {txn.date}: {txn.transaction_type.value} "
                f"{txn.shares} shares @ ${txn.amount_usd:,.2f} "
                f"(commission: ${txn.commission_usd:,.2f})"
            )
    else:
        lines.append("  No transactions")
    lines.append("")
    
    # QEF Income (Form 8621)
    lines.append("QEF INCOME (FORM 8621 DATA)")
    lines.append("-" * 40)
    total_ordinary = Decimal("0")
    total_gains = Decimal("0")
    for f in report.form_8621_data:
        holding_type = "Direct" if f.is_direct_holding else "Indirect"
        lines.append(f"  {f.fund_ticker} ({holding_type}):")
        lines.append(f"    Line 6a Ordinary Earnings: ${f.line_6a_ordinary_earnings_usd:,.2f}")
        lines.append(f"    Line 7a Net Capital Gains: ${f.line_7a_net_capital_gains_usd:,.2f}")
        total_ordinary += f.line_6a_ordinary_earnings_usd
        total_gains += f.line_7a_net_capital_gains_usd
    lines.append(f"  TOTAL Ordinary Earnings: ${total_ordinary:,.2f}")
    lines.append(f"  TOTAL Net Capital Gains: ${total_gains:,.2f}")
    lines.append(f"  TOTAL QEF Income: ${total_ordinary + total_gains:,.2f}")
    lines.append("")
    
    # Basis Adjustments
    lines.append("BASIS ADJUSTMENTS")
    lines.append("-" * 40)
    if report.basis_adjustments:
        for adj in report.basis_adjustments:
            lines.append(f"  {adj.lot_id} ({adj.shares} shares, {adj.days_held_in_year} days):")
            lines.append(f"    Ordinary Earnings: +${adj.ordinary_earnings_usd:,.2f}")
            lines.append(f"    Capital Gains:     +${adj.capital_gains_usd:,.2f}")
            lines.append(f"    Distributions:     -${adj.distributions_usd:,.2f}")
            lines.append(f"    Net Adjustment:     ${adj.net_adjustment_usd:+,.2f}")
            lines.append(f"    Basis: ${adj.basis_before_usd:,.2f} -> ${adj.basis_after_usd:,.2f}")
    else:
        lines.append("  No basis adjustments")
    lines.append("")
    
    # Sales
    lines.append("SALES")
    lines.append("-" * 40)
    if report.lots_sold:
        for sale in report.lots_sold:
            gain_type = "ST" if sale.gain_type == GainType.SHORT_TERM else "LT"
            purchase_str = _format_purchase_date(sale.purchase_date)
            lines.append(
                f"  {sale.lot_id}: Sold {sale.shares_sold} shares on {sale.sale_date}"
            )
            lines.append(
                f"    Purchased: {purchase_str} ({sale.holding_period_days} days held)"
            )
            if sale.purchase_date == UNKNOWN_PURCHASE_DATE:
                lines.append(f"    ⚠ WARNING: Unknown purchase date - using $0 original basis")
            lines.append(f"    Adjusted Basis: ${sale.cost_basis_adjusted_usd:,.2f}")
            lines.append(f"    Proceeds: ${sale.proceeds_usd:,.2f}")
            lines.append(f"    Gain/Loss: ${sale.gain_loss_usd:+,.2f} ({gain_type})")
    else:
        lines.append("  No sales")
    lines.append("")
    
    # Ending Position
    lines.append("END OF YEAR POSITION")
    lines.append("-" * 40)
    if report.ending_lots:
        total_shares = sum(lot.shares for lot in report.ending_lots)
        total_basis = sum(lot.cost_basis_usd for lot in report.ending_lots)
        lines.append(f"  Lots: {len(report.ending_lots)}")
        lines.append(f"  Total Shares: {total_shares}")
        lines.append(f"  Total Cost Basis (adjusted): ${total_basis:,.2f}")
        lines.append("")
        for lot in report.ending_lots:
            purchase_str = _format_purchase_date(lot.purchase_date)
            warning = " ⚠ UNKNOWN BASIS" if lot.purchase_date == UNKNOWN_PURCHASE_DATE else ""
            lines.append(
                f"  {lot.lot_id}: {lot.shares} shares, "
                f"purchased {purchase_str}, "
                f"basis ${lot.cost_basis_usd:,.2f}{warning}"
            )
    else:
        lines.append("  No lots at end of year")
    lines.append("")
    
    lines.append("=" * 70)
    lines.append("Note: This report is for informational purposes only.")
    lines.append("Consult a qualified tax advisor for your specific situation.")
    lines.append("=" * 70)
    
    return "\n".join(lines)

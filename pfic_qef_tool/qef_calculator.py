"""
QEF (Qualified Electing Fund) income and basis adjustment calculations.

Computes ordinary earnings, net capital gains, and distributions
for each lot based on AIS data.
"""

from decimal import Decimal
from datetime import date

from .models import (
    Lot, AISData, Form8621Data, BasisAdjustmentRecord,
    round_money, round_shares
)
from .lot_tracker import LotTracker


def calculate_lot_qef_income(
    lot: Lot,
    days_held: int,
    ais_data: AISData,
) -> BasisAdjustmentRecord:
    """
    Calculate QEF income and distributions for a single lot.
    
    Args:
        lot: The tax lot
        days_held: Number of days the lot was held during the tax year
        ais_data: AIS data with per-day-per-share rates
    
    Returns:
        BasisAdjustmentRecord with all calculated values
    """
    shares = lot.shares
    
    # Calculate income for each PFIC (top-level and underlying)
    earnings_by_pfic = {}
    gains_by_pfic = {}
    total_earnings = Decimal("0")
    total_gains = Decimal("0")
    
    for ticker, name, earnings_rate, gains_rate in ais_data.all_pfics():
        # Ordinary earnings = rate × shares × days
        earnings = earnings_rate * shares * Decimal(str(days_held))
        earnings = round_money(earnings)
        earnings_by_pfic[ticker] = earnings
        total_earnings += earnings
        
        # Net capital gains = rate × shares × days
        gains = gains_rate * shares * Decimal(str(days_held))
        gains = round_money(gains)
        gains_by_pfic[ticker] = gains
        total_gains += gains
    
    # Distributions (only from top-level PFIC)
    # Spread evenly across the year
    dist_rate = ais_data.distributions_per_day_per_share_usd
    distributions = dist_rate * shares * Decimal(str(days_held))
    distributions = round_money(distributions)
    
    # Net adjustment
    net_adjustment = total_earnings + total_gains - distributions
    
    # Basis values
    basis_before = lot.cost_basis_usd
    basis_after = round_money(basis_before + net_adjustment)
    
    # Floor at zero - basis cannot go negative
    if basis_after < Decimal("0"):
        basis_after = Decimal("0")
    
    return BasisAdjustmentRecord(
        lot_id=lot.lot_id,
        shares=shares,
        days_held_in_year=days_held,
        ordinary_earnings_usd=total_earnings,
        capital_gains_usd=total_gains,
        distributions_usd=distributions,
        net_adjustment_usd=round_money(net_adjustment),
        basis_before_usd=basis_before,
        basis_after_usd=basis_after,
        earnings_by_pfic=earnings_by_pfic,
        gains_by_pfic=gains_by_pfic,
    )


def apply_qef_adjustments(
    tracker: LotTracker,
    tax_year: int,
    ais_data: AISData,
) -> list[BasisAdjustmentRecord]:
    """
    Calculate and apply QEF adjustments to all lots in the tracker.
    
    Updates the lots in-place with QEF income values.
    
    Returns list of BasisAdjustmentRecord for reporting.
    """
    adjustments = []
    
    # Get all lots with days held
    lots_with_days = tracker.get_lots_for_qef_calculation(tax_year)
    
    for lot, days_held in lots_with_days:
        if days_held <= 0:
            continue
        
        # Calculate QEF income
        record = calculate_lot_qef_income(lot, days_held, ais_data)
        adjustments.append(record)
        
        # Apply to lot
        lot.qef_ordinary_earnings_usd = record.ordinary_earnings_usd
        lot.qef_capital_gains_usd = record.capital_gains_usd
        lot.qef_distributions_usd = record.distributions_usd
        lot.qef_earnings_by_pfic = record.earnings_by_pfic.copy()
        lot.qef_gains_by_pfic = record.gains_by_pfic.copy()
    
    return adjustments


def generate_form_8621_data(
    adjustments: list[BasisAdjustmentRecord],
    ais_data: AISData,
) -> list[Form8621Data]:
    """
    Generate Form 8621 Part III data for all PFICs.
    
    Aggregates income across all lots for each PFIC.
    
    Returns one Form8621Data per PFIC (top-level + underlying).
    """
    # Aggregate by PFIC ticker
    earnings_totals = {}
    gains_totals = {}
    
    for adj in adjustments:
        for ticker, earnings in adj.earnings_by_pfic.items():
            if ticker not in earnings_totals:
                earnings_totals[ticker] = Decimal("0")
            earnings_totals[ticker] += earnings
        
        for ticker, gains in adj.gains_by_pfic.items():
            if ticker not in gains_totals:
                gains_totals[ticker] = Decimal("0")
            gains_totals[ticker] += gains
    
    # Build Form 8621 data for each PFIC
    results = []
    
    # Top-level PFIC
    top_ticker = ais_data.fund_ticker
    results.append(Form8621Data(
        fund_ticker=top_ticker,
        fund_name=ais_data.fund_name,
        is_direct_holding=True,
        line_6a_ordinary_earnings_usd=round_money(
            earnings_totals.get(top_ticker, Decimal("0"))
        ),
        line_7a_net_capital_gains_usd=round_money(
            gains_totals.get(top_ticker, Decimal("0"))
        ),
    ))
    
    # Underlying PFICs
    for underlying in ais_data.underlying_pfics:
        ticker = underlying.fund_ticker
        results.append(Form8621Data(
            fund_ticker=ticker,
            fund_name=underlying.fund_name,
            is_direct_holding=False,
            line_6a_ordinary_earnings_usd=round_money(
                earnings_totals.get(ticker, Decimal("0"))
            ),
            line_7a_net_capital_gains_usd=round_money(
                gains_totals.get(ticker, Decimal("0"))
            ),
        ))
    
    return results


def calculate_total_qef_income(
    adjustments: list[BasisAdjustmentRecord],
) -> tuple[Decimal, Decimal, Decimal]:
    """
    Calculate total QEF income across all lots.
    
    Returns (total_ordinary_earnings, total_capital_gains, total_distributions).
    """
    total_earnings = sum(a.ordinary_earnings_usd for a in adjustments)
    total_gains = sum(a.capital_gains_usd for a in adjustments)
    total_dist = sum(a.distributions_usd for a in adjustments)
    
    return (
        round_money(total_earnings),
        round_money(total_gains),
        round_money(total_dist),
    )

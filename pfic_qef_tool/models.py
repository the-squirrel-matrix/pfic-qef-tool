"""
Data models for PFIC QEF tax tool.

All monetary amounts are stored in USD unless otherwise specified.
Shares are stored as Decimal with 4 decimal places precision.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional


# Precision constants
SHARES_PRECISION = Decimal("0.0001")
MONEY_PRECISION = Decimal("0.01")
RATE_PRECISION = Decimal("0.0000000001")  # For per-day-per-share rates


def round_shares(value: Decimal) -> Decimal:
    """Round shares to 4 decimal places."""
    return value.quantize(SHARES_PRECISION, rounding=ROUND_HALF_UP)


def round_money(value: Decimal) -> Decimal:
    """Round money to 2 decimal places."""
    return value.quantize(MONEY_PRECISION, rounding=ROUND_HALF_UP)


class TransactionType(Enum):
    BUY = "BUY"
    SELL = "SELL"


class GainType(Enum):
    SHORT_TERM = "SHORT_TERM"
    LONG_TERM = "LONG_TERM"


class LotStatus(Enum):
    HELD = "HELD"
    SOLD = "SOLD"
    SPLIT = "SPLIT"  # Original lot that was split (no longer active)


@dataclass
class Transaction:
    """A buy or sell transaction."""
    date: date
    transaction_type: TransactionType
    shares: Decimal
    amount: Decimal  # In original currency (total, not per-share)
    commission: Decimal  # In original currency
    currency: str
    ticker: str = ""  # PFIC ticker symbol (e.g., "XEQT")
    
    # Converted to USD
    amount_usd: Optional[Decimal] = None
    commission_usd: Optional[Decimal] = None
    exchange_rate: Optional[Decimal] = None
    
    def __post_init__(self):
        self.shares = round_shares(Decimal(str(self.shares)))
        self.amount = Decimal(str(self.amount))
        self.commission = Decimal(str(self.commission))
    
    @property
    def total_cost_usd(self) -> Optional[Decimal]:
        """For BUY: amount + commission. For SELL: N/A."""
        if self.amount_usd is None or self.commission_usd is None:
            return None
        if self.transaction_type == TransactionType.BUY:
            return round_money(self.amount_usd + self.commission_usd)
        return None
    
    @property
    def net_proceeds_usd(self) -> Optional[Decimal]:
        """For SELL: amount - commission. For BUY: N/A."""
        if self.amount_usd is None or self.commission_usd is None:
            return None
        if self.transaction_type == TransactionType.SELL:
            return round_money(self.amount_usd - self.commission_usd)
        return None


@dataclass
class Lot:
    """A tax lot of PFIC shares."""
    lot_id: str
    purchase_date: date
    shares: Decimal
    cost_basis_usd: Decimal
    ticker: str = ""  # PFIC ticker symbol (e.g., "XEQT")
    original_lot_id: Optional[str] = None  # For tracking split lots
    
    # Status tracking
    status: LotStatus = LotStatus.HELD
    sale_date: Optional[date] = None
    proceeds_usd: Optional[Decimal] = None
    
    # QEF adjustments (filled in by qef_calculator)
    qef_ordinary_earnings_usd: Decimal = Decimal("0")
    qef_capital_gains_usd: Decimal = Decimal("0")
    qef_distributions_usd: Decimal = Decimal("0")
    
    # Breakdown by PFIC (for 8621 reporting)
    qef_earnings_by_pfic: dict = field(default_factory=dict)
    qef_gains_by_pfic: dict = field(default_factory=dict)
    
    def __post_init__(self):
        self.shares = round_shares(Decimal(str(self.shares)))
        self.cost_basis_usd = round_money(Decimal(str(self.cost_basis_usd)))
        if self.proceeds_usd is not None:
            self.proceeds_usd = round_money(Decimal(str(self.proceeds_usd)))
    
    @property
    def adjusted_cost_basis_usd(self) -> Decimal:
        """Cost basis after QEF adjustments."""
        adjustment = (
            self.qef_ordinary_earnings_usd 
            + self.qef_capital_gains_usd 
            - self.qef_distributions_usd
        )
        return round_money(self.cost_basis_usd + adjustment)
    
    @property
    def gain_loss_usd(self) -> Optional[Decimal]:
        """Capital gain/loss if sold."""
        if self.proceeds_usd is None:
            return None
        return round_money(self.proceeds_usd - self.adjusted_cost_basis_usd)
    
    @property
    def gain_type(self) -> Optional[GainType]:
        """Short-term or long-term based on holding period."""
        if self.sale_date is None:
            return None
        holding_days = (self.sale_date - self.purchase_date).days
        # Long-term if held more than 1 year (365 days)
        if holding_days > 365:
            return GainType.LONG_TERM
        return GainType.SHORT_TERM
    
    @property
    def holding_period_days(self) -> Optional[int]:
        """Days held until sale."""
        if self.sale_date is None:
            return None
        return (self.sale_date - self.purchase_date).days
    
    def copy_for_split(self, new_lot_id: str, new_shares: Decimal, 
                       new_cost_basis: Decimal) -> "Lot":
        """Create a new lot from a split."""
        return Lot(
            lot_id=new_lot_id,
            purchase_date=self.purchase_date,
            shares=new_shares,
            cost_basis_usd=new_cost_basis,
            ticker=self.ticker,
            original_lot_id=self.original_lot_id or self.lot_id,
            status=LotStatus.HELD,
        )


@dataclass
class UnderlyingPFIC:
    """Data for an underlying PFIC from the AIS."""
    fund_ticker: str
    fund_name: str
    ordinary_earnings_per_day_per_share_usd: Decimal
    net_capital_gains_per_day_per_share_usd: Decimal
    
    def __post_init__(self):
        self.ordinary_earnings_per_day_per_share_usd = Decimal(
            str(self.ordinary_earnings_per_day_per_share_usd)
        )
        self.net_capital_gains_per_day_per_share_usd = Decimal(
            str(self.net_capital_gains_per_day_per_share_usd)
        )


@dataclass
class AISData:
    """Annual Information Statement data for a PFIC."""
    tax_year: int
    fund_ticker: str
    fund_name: str
    ordinary_earnings_per_day_per_share_usd: Decimal
    net_capital_gains_per_day_per_share_usd: Decimal
    total_distributions_per_share_usd: Decimal
    underlying_pfics: list[UnderlyingPFIC] = field(default_factory=list)
    
    def __post_init__(self):
        self.ordinary_earnings_per_day_per_share_usd = Decimal(
            str(self.ordinary_earnings_per_day_per_share_usd)
        )
        self.net_capital_gains_per_day_per_share_usd = Decimal(
            str(self.net_capital_gains_per_day_per_share_usd)
        )
        self.total_distributions_per_share_usd = Decimal(
            str(self.total_distributions_per_share_usd)
        )
    
    @property
    def year_days(self) -> int:
        """Calculate days in tax year (365 or 366 for leap year)."""
        year = self.tax_year
        if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
            return 366
        return 365
    
    @property
    def distributions_per_day_per_share_usd(self) -> Decimal:
        """Distributions spread evenly across the year."""
        return self.total_distributions_per_share_usd / Decimal(str(self.year_days))
    
    def all_pfics(self) -> list[tuple[str, str, Decimal, Decimal]]:
        """Return list of (ticker, name, ord_earnings_rate, cap_gains_rate) for all PFICs."""
        result = [(
            self.fund_ticker,
            self.fund_name,
            self.ordinary_earnings_per_day_per_share_usd,
            self.net_capital_gains_per_day_per_share_usd,
        )]
        for u in self.underlying_pfics:
            result.append((
                u.fund_ticker,
                u.fund_name,
                u.ordinary_earnings_per_day_per_share_usd,
                u.net_capital_gains_per_day_per_share_usd,
            ))
        return result


@dataclass
class Config:
    """Configuration for the tool."""
    pfic_ticker: str
    pfic_name: str
    default_currency: str = "CAD"
    tax_year: Optional[int] = None  # Optional - prefer CLI argument or Excel sheet


@dataclass 
class Form8621Data:
    """Data needed for Form 8621 Part III."""
    fund_ticker: str
    fund_name: str
    is_direct_holding: bool
    line_6a_ordinary_earnings_usd: Decimal
    line_6b_portion_distributed_usd: Decimal = Decimal("0")
    line_7a_net_capital_gains_usd: Decimal = Decimal("0")
    line_7b_portion_distributed_usd: Decimal = Decimal("0")
    
    @property
    def line_6c_tax_on_6a_usd(self) -> Decimal:
        """For no excess distribution regime, this equals 6a."""
        return self.line_6a_ordinary_earnings_usd
    
    @property
    def line_7c_tax_on_7a_usd(self) -> Decimal:
        """For no excess distribution regime, this equals 7a."""
        return self.line_7a_net_capital_gains_usd


@dataclass
class SaleRecord:
    """Record of a sold lot for sales report."""
    lot_id: str
    original_lot_id: Optional[str]
    purchase_date: date
    sale_date: date
    shares_sold: Decimal
    cost_basis_usd: Decimal
    cost_basis_adjusted_usd: Decimal
    proceeds_usd: Decimal
    gain_loss_usd: Decimal
    gain_type: GainType
    holding_period_days: int


@dataclass
class BasisAdjustmentRecord:
    """Record of basis adjustment for a lot."""
    lot_id: str
    shares: Decimal
    days_held_in_year: int
    ordinary_earnings_usd: Decimal
    capital_gains_usd: Decimal
    distributions_usd: Decimal
    net_adjustment_usd: Decimal
    basis_before_usd: Decimal
    basis_after_usd: Decimal
    # Breakdown by PFIC
    earnings_by_pfic: dict
    gains_by_pfic: dict


@dataclass
class LotActivityReport:
    """Comprehensive report of lot activity for the year."""
    tax_year: int
    pfic_ticker: str
    pfic_name: str
    beginning_lots: list[Lot]
    transactions_processed: list[Transaction]
    lots_created: list[Lot]
    lots_sold: list[SaleRecord]
    basis_adjustments: list[BasisAdjustmentRecord]
    ending_lots: list[Lot]
    form_8621_data: list[Form8621Data]

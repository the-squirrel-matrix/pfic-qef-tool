"""
Lot tracking with FIFO (First In, First Out) sale processing.

Handles buying new lots, selling with FIFO ordering, and lot splitting.
"""

from datetime import date
from decimal import Decimal
from typing import Optional
from collections import deque
import warnings

from .models import (
    Lot, Transaction, TransactionType, LotStatus,
    round_shares, round_money, SHARES_PRECISION
)


# Sentinel date for lots with unknown purchase date
UNKNOWN_PURCHASE_DATE = date(1900, 1, 1)


class LotTracker:
    """
    Tracks tax lots with FIFO processing for sales.
    
    Lots are identified by unique IDs. When lots are split during a sale,
    the sold portion keeps the original ID, and the remainder gets a new
    ID with a suffix (e.g., LOT-001 -> LOT-001.1).
    
    If a sale is attempted with insufficient shares, the tracker will
    create a synthetic "unknown" lot with zero cost basis and an unknown
    purchase date, and flag this as a warning.
    """
    
    def __init__(self, beginning_lots: Optional[list[Lot]] = None):
        """
        Initialize tracker with optional beginning-of-year lots.
        
        Lots should be provided in chronological order by purchase date.
        Pass None or empty list if this is the first year of ownership.
        """
        self._lots: deque[Lot] = deque()
        self._sold_lots: list[Lot] = []
        self._lot_counter: int = 0
        self._split_counters: dict[str, int] = {}  # Track splits per original lot
        self._warnings: list[str] = []  # Track warnings during processing
        self._unknown_lots: list[str] = []  # Track lots with unknown basis/date
        
        if beginning_lots:
            for lot in sorted(beginning_lots, key=lambda x: x.purchase_date):
                self._lots.append(lot)
                # Update counter to avoid ID collisions
                self._update_counter_from_lot_id(lot.lot_id)
    
    @property
    def warnings(self) -> list[str]:
        """Return list of warnings generated during processing."""
        return list(self._warnings)
    
    @property
    def unknown_lots(self) -> list[str]:
        """Return list of lot IDs with unknown purchase date/cost basis."""
        return list(self._unknown_lots)
    
    def _update_counter_from_lot_id(self, lot_id: str):
        """Update the lot counter based on existing lot IDs."""
        # Handle IDs like "LOT-001" or "LOT-001.1"
        base_id = lot_id.split('.')[0]
        if base_id.startswith("LOT-"):
            try:
                num = int(base_id[4:])
                self._lot_counter = max(self._lot_counter, num)
            except ValueError:
                pass
    
    def _generate_lot_id(self) -> str:
        """Generate a new unique lot ID."""
        self._lot_counter += 1
        return f"LOT-{self._lot_counter:03d}"
    
    def _generate_split_lot_id(self, original_lot_id: str) -> str:
        """Generate a lot ID for a split remainder."""
        # Extract base lot ID (handle already-split lots)
        base_id = original_lot_id.split('.')[0]
        
        if base_id not in self._split_counters:
            self._split_counters[base_id] = 0
        
        self._split_counters[base_id] += 1
        return f"{base_id}.{self._split_counters[base_id]}"
    
    @property
    def held_lots(self) -> list[Lot]:
        """Return list of currently held lots (not sold)."""
        return [lot for lot in self._lots if lot.status == LotStatus.HELD]
    
    @property
    def sold_lots(self) -> list[Lot]:
        """Return list of sold lots."""
        return list(self._sold_lots)
    
    @property
    def all_lots(self) -> list[Lot]:
        """Return all lots (held and sold) in order."""
        return list(self._lots) + self._sold_lots
    
    def total_shares(self) -> Decimal:
        """Total shares currently held."""
        return sum(lot.shares for lot in self.held_lots)
    
    def buy(self, transaction: Transaction) -> Lot:
        """
        Process a buy transaction, creating a new lot.
        
        Returns the created lot.
        """
        if transaction.transaction_type != TransactionType.BUY:
            raise ValueError("Expected BUY transaction")
        
        if transaction.total_cost_usd is None:
            raise ValueError("Transaction must have USD amounts calculated")
        
        lot_id = self._generate_lot_id()
        lot = Lot(
            lot_id=lot_id,
            purchase_date=transaction.date,
            shares=transaction.shares,
            cost_basis_usd=transaction.total_cost_usd,
            ticker=transaction.ticker,
        )
        
        # Insert in chronological order
        inserted = False
        for i, existing in enumerate(self._lots):
            if existing.purchase_date > lot.purchase_date:
                self._lots.insert(i, lot)
                inserted = True
                break
        
        if not inserted:
            self._lots.append(lot)
        
        return lot
    
    def sell(self, transaction: Transaction) -> list[Lot]:
        """
        Process a sell transaction using FIFO.
        
        Sells from the oldest lots first. If a lot must be split,
        the sold portion keeps the original ID and the remainder
        gets a new suffixed ID.
        
        If there are insufficient shares to cover the sale, synthetic
        lots with unknown purchase date (1900-01-01) and zero cost basis
        are created. This is flagged as a warning.
        
        Returns list of sold lots (may include partial lot sales).
        """
        if transaction.transaction_type != TransactionType.SELL:
            raise ValueError("Expected SELL transaction")
        
        if transaction.net_proceeds_usd is None:
            raise ValueError("Transaction must have USD amounts calculated")
        
        shares_to_sell = transaction.shares
        total_proceeds = transaction.net_proceeds_usd
        sold_lots = []
        
        # Check if we have enough shares
        available = self.total_shares()
        if shares_to_sell > available + SHARES_PRECISION / 2:
            shortfall = round_shares(shares_to_sell - available)
            warning_msg = (
                f"INSUFFICIENT SHARES: Sale of {shares_to_sell} shares on "
                f"{transaction.date} but only {available} available. "
                f"Creating synthetic lot for {shortfall} shares with "
                f"unknown purchase date and $0 cost basis."
            )
            self._warnings.append(warning_msg)
            
            # Create synthetic lot for the shortfall
            synthetic_lot = self._create_unknown_lot(shortfall, transaction.ticker)
            self._unknown_lots.append(synthetic_lot.lot_id)
            
            # Insert at the beginning (oldest) for FIFO
            self._lots.appendleft(synthetic_lot)
        
        # Process FIFO
        remaining_shares = shares_to_sell
        remaining_proceeds = total_proceeds
        
        while remaining_shares > SHARES_PRECISION / 2:
            # Find oldest held lot
            oldest_lot = None
            oldest_idx = None
            for i, lot in enumerate(self._lots):
                if lot.status == LotStatus.HELD:
                    oldest_lot = lot
                    oldest_idx = i
                    break
            
            if oldest_lot is None:
                # This shouldn't happen after we create synthetic lots, but just in case
                warning_msg = f"No lots available for remaining {remaining_shares} shares"
                self._warnings.append(warning_msg)
                break
            
            if oldest_lot.shares <= remaining_shares + SHARES_PRECISION / 2:
                # Sell entire lot
                proceeds_for_lot = round_money(
                    remaining_proceeds * oldest_lot.shares / remaining_shares
                )
                
                oldest_lot.status = LotStatus.SOLD
                oldest_lot.sale_date = transaction.date
                oldest_lot.proceeds_usd = proceeds_for_lot
                
                sold_lots.append(oldest_lot)
                self._sold_lots.append(oldest_lot)
                
                remaining_proceeds = round_money(remaining_proceeds - proceeds_for_lot)
                remaining_shares = round_shares(remaining_shares - oldest_lot.shares)
                
            else:
                # Split the lot
                sell_shares = remaining_shares
                keep_shares = round_shares(oldest_lot.shares - sell_shares)
                
                # Allocate cost basis proportionally
                basis_fraction = sell_shares / oldest_lot.shares
                sell_basis = round_money(oldest_lot.cost_basis_usd * basis_fraction)
                keep_basis = round_money(oldest_lot.cost_basis_usd - sell_basis)
                
                # Create remainder lot with new ID
                remainder_lot = oldest_lot.copy_for_split(
                    new_lot_id=self._generate_split_lot_id(oldest_lot.lot_id),
                    new_shares=keep_shares,
                    new_cost_basis=keep_basis,
                )
                
                # If original was unknown, remainder is also unknown
                if oldest_lot.lot_id in self._unknown_lots:
                    self._unknown_lots.append(remainder_lot.lot_id)
                
                # Update original lot as sold
                oldest_lot.shares = sell_shares
                oldest_lot.cost_basis_usd = sell_basis
                oldest_lot.status = LotStatus.SOLD
                oldest_lot.sale_date = transaction.date
                oldest_lot.proceeds_usd = remaining_proceeds  # All remaining proceeds
                
                sold_lots.append(oldest_lot)
                self._sold_lots.append(oldest_lot)
                
                # Insert remainder lot in place
                self._lots.insert(oldest_idx + 1, remainder_lot)
                
                remaining_shares = Decimal("0")
                remaining_proceeds = Decimal("0")
        
        return sold_lots
    
    def _create_unknown_lot(self, shares: Decimal, ticker: str) -> Lot:
        """
        Create a synthetic lot with unknown purchase date and zero cost basis.
        
        Used when a sale is attempted with insufficient shares.
        """
        lot_id = self._generate_lot_id()
        lot = Lot(
            lot_id=lot_id,
            purchase_date=UNKNOWN_PURCHASE_DATE,
            shares=shares,
            cost_basis_usd=Decimal("0"),
            original_lot_id=None,
            ticker=ticker
        )
        return lot
    
    def process_transaction(self, transaction: Transaction) -> list[Lot]:
        """
        Process a buy or sell transaction.
        
        Returns list of affected lots (1 for buy, 1+ for sell).
        """
        if transaction.transaction_type == TransactionType.BUY:
            return [self.buy(transaction)]
        else:  # SELL
            return self.sell(transaction)
    
    def get_lots_for_qef_calculation(self, tax_year: int) -> list[tuple[Lot, int]]:
        """
        Get lots that need QEF calculation for a tax year.
        
        Returns list of (lot, days_held_in_year) tuples.
        Days are counted from:
        - Jan 1 if lot was held at start of year
        - Purchase date if bought during year
        Until:
        - Dec 31 if lot is still held
        - Day before sale if sold during year
        """
        year_start = date(tax_year, 1, 1)
        year_end = date(tax_year, 12, 31)
        
        result = []
        
        for lot in self._lots:
            # Determine start date for counting
            if lot.purchase_date < year_start:
                count_start = year_start
            elif lot.purchase_date <= year_end:
                count_start = lot.purchase_date
            else:
                # Purchased after year end, skip
                continue
            
            # Determine end date for counting
            if lot.status == LotStatus.SOLD and lot.sale_date:
                if lot.sale_date < year_start:
                    # Sold before year started, skip
                    continue
                elif lot.sale_date <= year_end:
                    # Sold during year - count up to day before sale
                    count_end = lot.sale_date - date.resolution
                else:
                    # Sold after year end, count full year
                    count_end = year_end
            else:
                # Still held
                count_end = year_end
            
            # Calculate days (inclusive of both start and end)
            if count_end >= count_start:
                days = (count_end - count_start).days + 1
                result.append((lot, days))
        
        # Also check sold lots that were moved to _sold_lots
        for lot in self._sold_lots:
            if lot in [r[0] for r in result]:
                continue  # Already counted
            
            if lot.purchase_date < year_start:
                count_start = year_start
            elif lot.purchase_date <= year_end:
                count_start = lot.purchase_date
            else:
                continue
            
            if lot.sale_date and lot.sale_date <= year_end:
                if lot.sale_date < year_start:
                    continue
                count_end = lot.sale_date - date.resolution
            else:
                count_end = year_end
            
            if count_end >= count_start:
                days = (count_end - count_start).days + 1
                result.append((lot, days))
        
        return result
    
    def get_ending_lots(self) -> list[Lot]:
        """
        Get lots held at end of processing, ready for next year.
        
        Returns copies with adjusted basis incorporated into cost_basis.
        """
        ending = []
        for lot in self._lots:
            if lot.status == LotStatus.HELD:
                # Create new lot with adjusted basis as the new cost basis
                new_lot = Lot(
                    lot_id=lot.lot_id,
                    purchase_date=lot.purchase_date,
                    shares=lot.shares,
                    cost_basis_usd=lot.adjusted_cost_basis_usd,
                    original_lot_id=lot.original_lot_id,
                    ticker=lot.ticker,
                )
                ending.append(new_lot)
        
        return sorted(ending, key=lambda x: (x.purchase_date, x.lot_id))


def process_transactions(
    beginning_lots: list[Lot],
    transactions: list[Transaction],
) -> LotTracker:
    """
    Process all transactions for a year.
    
    Transactions should already have USD amounts calculated.
    Returns the LotTracker with all lots updated.
    """
    tracker = LotTracker(beginning_lots)
    
    # Sort transactions by date
    sorted_txns = sorted(transactions, key=lambda t: t.date)
    
    for txn in sorted_txns:
        tracker.process_transaction(txn)
    
    return tracker

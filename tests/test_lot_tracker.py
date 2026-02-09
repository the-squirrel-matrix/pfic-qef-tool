"""
Tests for lot_tracker module.
"""

import unittest
from datetime import date
from decimal import Decimal

import sys
sys.path.insert(0, '/home/claude/pfic_qef_tool_github')

from pfic_qef_tool.models import Lot, Transaction, TransactionType, LotStatus
from pfic_qef_tool.lot_tracker import LotTracker


class TestLotTracker(unittest.TestCase):
    """Tests for LotTracker class."""
    
    def test_buy_creates_lot(self):
        """Test that a buy transaction creates a new lot."""
        tracker = LotTracker()
        
        txn = Transaction(
            date=date(2024, 3, 15),
            transaction_type=TransactionType.BUY,
            shares=Decimal("100"),
            amount=Decimal("2500"),
            commission=Decimal("10"),
            currency="USD",
            amount_usd=Decimal("2500"),
            commission_usd=Decimal("10"),
        )
        
        lots = tracker.process_transaction(txn)
        
        self.assertEqual(len(lots), 1)
        self.assertEqual(lots[0].shares, Decimal("100"))
        self.assertEqual(lots[0].cost_basis_usd, Decimal("2510"))  # amount + commission
        self.assertEqual(lots[0].purchase_date, date(2024, 3, 15))
    
    def test_sell_fifo(self):
        """Test that sells use FIFO ordering."""
        # Set up two lots
        lot1 = Lot(
            lot_id="LOT-001",
            purchase_date=date(2023, 1, 1),
            shares=Decimal("50"),
            cost_basis_usd=Decimal("1000"),
        )
        lot2 = Lot(
            lot_id="LOT-002",
            purchase_date=date(2023, 6, 1),
            shares=Decimal("50"),
            cost_basis_usd=Decimal("1200"),
        )
        
        tracker = LotTracker([lot1, lot2])
        
        # Sell 50 shares - should sell oldest lot first
        txn = Transaction(
            date=date(2024, 9, 1),
            transaction_type=TransactionType.SELL,
            shares=Decimal("50"),
            amount=Decimal("1500"),
            commission=Decimal("10"),
            currency="USD",
            amount_usd=Decimal("1500"),
            commission_usd=Decimal("10"),
        )
        
        sold = tracker.process_transaction(txn)
        
        self.assertEqual(len(sold), 1)
        self.assertEqual(sold[0].lot_id, "LOT-001")  # Oldest lot
        self.assertEqual(sold[0].status, LotStatus.SOLD)
        self.assertEqual(sold[0].proceeds_usd, Decimal("1490"))  # amount - commission
        
        # Check remaining lots
        remaining = tracker.held_lots
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].lot_id, "LOT-002")
    
    def test_sell_splits_lot(self):
        """Test that selling partial lot splits it correctly."""
        lot = Lot(
            lot_id="LOT-001",
            purchase_date=date(2023, 1, 1),
            shares=Decimal("100"),
            cost_basis_usd=Decimal("2000"),
        )
        
        tracker = LotTracker([lot])
        
        # Sell 30 shares
        txn = Transaction(
            date=date(2024, 6, 1),
            transaction_type=TransactionType.SELL,
            shares=Decimal("30"),
            amount=Decimal("900"),
            commission=Decimal("10"),
            currency="USD",
            amount_usd=Decimal("900"),
            commission_usd=Decimal("10"),
        )
        
        sold = tracker.process_transaction(txn)
        
        # Check sold portion
        self.assertEqual(len(sold), 1)
        self.assertEqual(sold[0].lot_id, "LOT-001")  # Keeps original ID
        self.assertEqual(sold[0].shares, Decimal("30"))
        self.assertEqual(sold[0].cost_basis_usd, Decimal("600"))  # 30% of 2000
        self.assertEqual(sold[0].proceeds_usd, Decimal("890"))
        
        # Check remaining portion
        remaining = tracker.held_lots
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].lot_id, "LOT-001.1")  # New suffixed ID
        self.assertEqual(remaining[0].shares, Decimal("70"))
        self.assertEqual(remaining[0].cost_basis_usd, Decimal("1400"))  # 70% of 2000
        self.assertEqual(remaining[0].original_lot_id, "LOT-001")
    
    def test_sell_multiple_lots(self):
        """Test selling across multiple lots."""
        lot1 = Lot(
            lot_id="LOT-001",
            purchase_date=date(2023, 1, 1),
            shares=Decimal("30"),
            cost_basis_usd=Decimal("600"),
        )
        lot2 = Lot(
            lot_id="LOT-002",
            purchase_date=date(2023, 6, 1),
            shares=Decimal("50"),
            cost_basis_usd=Decimal("1100"),
        )
        
        tracker = LotTracker([lot1, lot2])
        
        # Sell 60 shares - should sell all of lot1 (30) and part of lot2 (30)
        txn = Transaction(
            date=date(2024, 9, 1),
            transaction_type=TransactionType.SELL,
            shares=Decimal("60"),
            amount=Decimal("1800"),
            commission=Decimal("10"),
            currency="USD",
            amount_usd=Decimal("1800"),
            commission_usd=Decimal("10"),
        )
        
        sold = tracker.process_transaction(txn)
        
        self.assertEqual(len(sold), 2)
        
        # First lot sold entirely
        self.assertEqual(sold[0].lot_id, "LOT-001")
        self.assertEqual(sold[0].shares, Decimal("30"))
        
        # Second lot partially sold
        self.assertEqual(sold[1].lot_id, "LOT-002")
        self.assertEqual(sold[1].shares, Decimal("30"))
        
        # Check remaining
        remaining = tracker.held_lots
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].lot_id, "LOT-002.1")
        self.assertEqual(remaining[0].shares, Decimal("20"))
    
    def test_insufficient_shares_creates_synthetic_lot(self):
        """Test that selling more than available creates synthetic lot."""
        lot = Lot(
            lot_id="LOT-001",
            purchase_date=date(2023, 1, 1),
            shares=Decimal("50"),
            cost_basis_usd=Decimal("1000"),
        )
        
        tracker = LotTracker([lot])
        
        txn = Transaction(
            date=date(2024, 6, 1),
            transaction_type=TransactionType.SELL,
            shares=Decimal("100"),  # More than available
            amount=Decimal("2000"),
            commission=Decimal("10"),
            currency="USD",
            amount_usd=Decimal("2000"),
            commission_usd=Decimal("10"),
        )
        
        # Should not raise error - instead creates synthetic lot
        sold = tracker.process_transaction(txn)
        
        # Should have sold 100 shares total (50 from real lot + 50 from synthetic)
        total_sold = sum(lot.shares for lot in sold)
        self.assertEqual(total_sold, Decimal("100"))
        
        # Should have a warning
        self.assertTrue(len(tracker.warnings) > 0)
        self.assertIn("INSUFFICIENT SHARES", tracker.warnings[0])
        
        # Should have an unknown lot
        self.assertTrue(len(tracker.unknown_lots) > 0)
    
    def test_days_held_calculation(self):
        """Test days held calculation for QEF."""
        # Lot held from before year start
        lot1 = Lot(
            lot_id="LOT-001",
            purchase_date=date(2023, 6, 1),
            shares=Decimal("100"),
            cost_basis_usd=Decimal("2000"),
        )
        
        # Lot purchased during year
        lot2 = Lot(
            lot_id="LOT-002",
            purchase_date=date(2024, 3, 1),
            shares=Decimal("50"),
            cost_basis_usd=Decimal("1000"),
        )
        
        tracker = LotTracker([lot1, lot2])
        
        # Get lots for 2024 (leap year - 366 days)
        lots_days = tracker.get_lots_for_qef_calculation(2024)
        
        # Lot1: held all of 2024 = 366 days
        # Lot2: held from March 1 through Dec 31 = 306 days
        lot1_days = next(d for l, d in lots_days if l.lot_id == "LOT-001")
        lot2_days = next(d for l, d in lots_days if l.lot_id == "LOT-002")
        
        self.assertEqual(lot1_days, 366)
        self.assertEqual(lot2_days, 306)


class TestLotTrackerFractionalShares(unittest.TestCase):
    """Tests for fractional share handling."""
    
    def test_fractional_shares(self):
        """Test that fractional shares are handled correctly."""
        tracker = LotTracker()
        
        txn = Transaction(
            date=date(2024, 3, 15),
            transaction_type=TransactionType.BUY,
            shares=Decimal("10.5432"),
            amount=Decimal("250"),
            commission=Decimal("5"),
            currency="USD",
            amount_usd=Decimal("250"),
            commission_usd=Decimal("5"),
        )
        
        lots = tracker.process_transaction(txn)
        
        # Should round to 4 decimal places
        self.assertEqual(lots[0].shares, Decimal("10.5432"))
    
    def test_split_fractional_shares(self):
        """Test splitting lots with fractional shares."""
        lot = Lot(
            lot_id="LOT-001",
            purchase_date=date(2023, 1, 1),
            shares=Decimal("100.1234"),
            cost_basis_usd=Decimal("2000"),
        )
        
        tracker = LotTracker([lot])
        
        # Sell fractional amount
        txn = Transaction(
            date=date(2024, 6, 1),
            transaction_type=TransactionType.SELL,
            shares=Decimal("33.3333"),
            amount=Decimal("700"),
            commission=Decimal("5"),
            currency="USD",
            amount_usd=Decimal("700"),
            commission_usd=Decimal("5"),
        )
        
        sold = tracker.process_transaction(txn)
        
        self.assertEqual(sold[0].shares, Decimal("33.3333"))
        
        remaining = tracker.held_lots
        self.assertEqual(remaining[0].shares, Decimal("66.7901"))  # 100.1234 - 33.3333


if __name__ == "__main__":
    unittest.main()

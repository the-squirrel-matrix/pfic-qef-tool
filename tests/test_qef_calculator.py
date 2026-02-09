"""
Tests for qef_calculator module.
"""

import unittest
from datetime import date
from decimal import Decimal

import sys
sys.path.insert(0, '/home/claude/pfic_qef_tool_github')

from pfic_qef_tool.models import Lot, AISData, UnderlyingPFIC
from pfic_qef_tool.lot_tracker import LotTracker
from pfic_qef_tool.qef_calculator import (
    calculate_lot_qef_income,
    apply_qef_adjustments,
    generate_form_8621_data,
)


class TestQEFCalculator(unittest.TestCase):
    """Tests for QEF calculations."""
    
    def setUp(self):
        """Set up test data."""
        # Create AIS data similar to XEQT
        self.ais_data = AISData(
            tax_year=2024,
            fund_ticker="XEQT",
            fund_name="iShares Core Equity ETF Portfolio",
            ordinary_earnings_per_day_per_share_usd=Decimal("0.0003080775"),
            net_capital_gains_per_day_per_share_usd=Decimal("0.0004661617"),
            total_distributions_per_share_usd=Decimal("0.4498954722"),
            underlying_pfics=[
                UnderlyingPFIC(
                    fund_ticker="XIC",
                    fund_name="iShares Core S&P/TSX Capped Composite Index ETF",
                    ordinary_earnings_per_day_per_share_usd=Decimal("0.0004731653"),
                    net_capital_gains_per_day_per_share_usd=Decimal("0.0008148535"),
                ),
                UnderlyingPFIC(
                    fund_ticker="XEF",
                    fund_name="iShares Core MSCI EAFE IMI Index ETF",
                    ordinary_earnings_per_day_per_share_usd=Decimal("0.0004135184"),
                    net_capital_gains_per_day_per_share_usd=Decimal("0.0001008374"),
                ),
                UnderlyingPFIC(
                    fund_ticker="XEC",
                    fund_name="iShares Core MSCI Emerging Markets IMI Index ETF",
                    ordinary_earnings_per_day_per_share_usd=Decimal("0.0000766569"),
                    net_capital_gains_per_day_per_share_usd=Decimal("0.0000164945"),
                ),
            ],
        )
    
    def test_calculate_lot_qef_income_full_year(self):
        """Test QEF income calculation for lot held full year."""
        lot = Lot(
            lot_id="LOT-001",
            purchase_date=date(2023, 1, 1),  # Before tax year
            shares=Decimal("100"),
            cost_basis_usd=Decimal("2500"),
        )
        
        # Held for full year = 366 days
        record = calculate_lot_qef_income(lot, 366, self.ais_data)
        
        # Check calculations for XEQT
        expected_xeqt_earnings = Decimal("0.0003080775") * 100 * 366
        self.assertAlmostEqual(
            float(record.earnings_by_pfic["XEQT"]),
            float(expected_xeqt_earnings),
            places=2
        )
        
        # Check that all PFICs are included
        self.assertIn("XEQT", record.earnings_by_pfic)
        self.assertIn("XIC", record.earnings_by_pfic)
        self.assertIn("XEF", record.earnings_by_pfic)
        self.assertIn("XEC", record.earnings_by_pfic)
        
        # Check distributions
        expected_dist = (Decimal("0.4498954722") / 366) * 100 * 366
        self.assertAlmostEqual(
            float(record.distributions_usd),
            float(expected_dist),
            places=2
        )
        
        # Check basis adjustment direction
        # Earnings and gains increase basis, distributions decrease it
        self.assertGreater(record.ordinary_earnings_usd, 0)
        self.assertGreater(record.capital_gains_usd, 0)
        self.assertGreater(record.distributions_usd, 0)
    
    def test_calculate_lot_qef_income_partial_year(self):
        """Test QEF income calculation for lot held partial year."""
        lot = Lot(
            lot_id="LOT-001",
            purchase_date=date(2024, 7, 1),  # Purchased mid-year
            shares=Decimal("50"),
            cost_basis_usd=Decimal("1200"),
        )
        
        # July 1 through Dec 31 = 184 days
        record = calculate_lot_qef_income(lot, 184, self.ais_data)
        
        # Earnings should be proportionally less
        full_year_earnings = Decimal("0.0003080775") * 50 * 366
        partial_year_earnings = Decimal("0.0003080775") * 50 * 184
        
        self.assertLess(
            float(record.earnings_by_pfic["XEQT"]),
            float(full_year_earnings)
        )
        self.assertAlmostEqual(
            float(record.earnings_by_pfic["XEQT"]),
            float(partial_year_earnings),
            places=2
        )
    
    def test_apply_qef_adjustments(self):
        """Test applying adjustments to tracker."""
        lot = Lot(
            lot_id="LOT-001",
            purchase_date=date(2023, 1, 1),
            shares=Decimal("100"),
            cost_basis_usd=Decimal("2500"),
        )
        
        tracker = LotTracker([lot])
        
        adjustments = apply_qef_adjustments(tracker, 2024, self.ais_data)
        
        self.assertEqual(len(adjustments), 1)
        
        # Check that lot was updated
        updated_lot = tracker.held_lots[0]
        self.assertGreater(updated_lot.qef_ordinary_earnings_usd, 0)
        self.assertGreater(updated_lot.qef_capital_gains_usd, 0)
        self.assertGreater(updated_lot.qef_distributions_usd, 0)
        
        # Check adjusted basis
        # Should be: original + earnings + gains - distributions
        expected_adjustment = (
            updated_lot.qef_ordinary_earnings_usd
            + updated_lot.qef_capital_gains_usd
            - updated_lot.qef_distributions_usd
        )
        expected_basis = Decimal("2500") + expected_adjustment
        
        self.assertAlmostEqual(
            float(updated_lot.adjusted_cost_basis_usd),
            float(expected_basis),
            places=2
        )
    
    def test_generate_form_8621_data(self):
        """Test Form 8621 data generation."""
        lot = Lot(
            lot_id="LOT-001",
            purchase_date=date(2023, 1, 1),
            shares=Decimal("100"),
            cost_basis_usd=Decimal("2500"),
        )
        
        tracker = LotTracker([lot])
        adjustments = apply_qef_adjustments(tracker, 2024, self.ais_data)
        
        form_data = generate_form_8621_data(adjustments, self.ais_data)
        
        # Should have 4 forms: XEQT + 3 underlying
        self.assertEqual(len(form_data), 4)
        
        # Check XEQT is marked as direct
        xeqt_form = next(f for f in form_data if f.fund_ticker == "XEQT")
        self.assertTrue(xeqt_form.is_direct_holding)
        
        # Check underlying are marked as indirect
        xic_form = next(f for f in form_data if f.fund_ticker == "XIC")
        self.assertFalse(xic_form.is_direct_holding)
        
        # Check that 6c = 6a and 7c = 7a (no excess distribution)
        self.assertEqual(
            xeqt_form.line_6c_tax_on_6a_usd,
            xeqt_form.line_6a_ordinary_earnings_usd
        )
        self.assertEqual(
            xeqt_form.line_7c_tax_on_7a_usd,
            xeqt_form.line_7a_net_capital_gains_usd
        )


class TestQEFWithSales(unittest.TestCase):
    """Tests for QEF calculations with sold lots."""
    
    def setUp(self):
        """Set up test data."""
        self.ais_data = AISData(
            tax_year=2024,
            fund_ticker="TEST",
            fund_name="Test Fund",
            ordinary_earnings_per_day_per_share_usd=Decimal("0.001"),
            net_capital_gains_per_day_per_share_usd=Decimal("0.002"),
            total_distributions_per_share_usd=Decimal("0.50"),
            underlying_pfics=[],
        )
    
    def test_sold_lot_gets_partial_income(self):
        """Test that sold lots accrue income only until sale."""
        from pfic_qef_tool.models import Transaction, TransactionType
        
        lot = Lot(
            lot_id="LOT-001",
            purchase_date=date(2023, 1, 1),
            shares=Decimal("100"),
            cost_basis_usd=Decimal("2500"),
        )
        
        tracker = LotTracker([lot])
        
        # Sell on June 30 (day 182 of leap year)
        txn = Transaction(
            date=date(2024, 6, 30),
            transaction_type=TransactionType.SELL,
            shares=Decimal("100"),
            amount=Decimal("3000"),
            commission=Decimal("10"),
            currency="USD",
            amount_usd=Decimal("3000"),
            commission_usd=Decimal("10"),
        )
        tracker.process_transaction(txn)
        
        adjustments = apply_qef_adjustments(tracker, 2024, self.ais_data)
        
        self.assertEqual(len(adjustments), 1)
        
        # Should only count 181 days (Jan 1 through June 29)
        # June 30 is the sale date, so we count up to June 29
        self.assertEqual(adjustments[0].days_held_in_year, 181)
        
        # Verify earnings calculation
        expected_earnings = Decimal("0.001") * 100 * 181
        self.assertAlmostEqual(
            float(adjustments[0].earnings_by_pfic["TEST"]),
            float(expected_earnings),
            places=2
        )


if __name__ == "__main__":
    unittest.main()

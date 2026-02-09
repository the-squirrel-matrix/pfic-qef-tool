"""
Integration test for the PFIC QEF Tool.

Uses example files and mock exchange rates to test the full pipeline.
"""

import sys
sys.path.insert(0, '/home/claude/pfic_qef_tool_github')

from datetime import date
from decimal import Decimal
from pathlib import Path

from pfic_qef_tool.models import Config, Lot, Transaction, TransactionType
from pfic_qef_tool.lot_tracker import LotTracker
from pfic_qef_tool.currency import OfflineCurrencyConverter
from pfic_qef_tool.qef_calculator import apply_qef_adjustments, generate_form_8621_data
from pfic_qef_tool.reports import (
    generate_sales_report,
    generate_lot_activity_report,
    generate_text_summary,
)
from pfic_qef_tool.serialization import (
    load_config,
    load_lots,
    load_transactions,
    load_ais_data,
    save_lots,
    save_form_8621_data,
    save_form_8621_csv,
    save_sales_report,
    save_sales_csv,
    save_basis_adjustments,
    save_lot_activity_report,
)


def create_mock_converter():
    """Create a converter with mock CAD/USD rates."""
    # Approximate 2024 rates: 1 CAD ≈ 0.74-0.75 USD
    rates = {}
    start = date(2024, 1, 1)
    for i in range(366):
        d = date(2024, 1, 1)
        d = date(d.year, d.month, d.day + i) if i == 0 else date.fromordinal(d.toordinal() + i)
        # Vary rate slightly for realism
        base_rate = Decimal("0.745")
        variation = Decimal(str((i % 30) * 0.001 - 0.015))
        rates[d] = base_rate + variation
    
    return OfflineCurrencyConverter(rates)


def run_integration_test():
    """Run full integration test."""
    print("=" * 60)
    print("PFIC QEF Tool Integration Test")
    print("=" * 60)
    
    examples_dir = Path("/home/claude/pfic_qef_tool/examples")
    output_dir = Path("/home/claude/pfic_qef_tool/test_output")
    output_dir.mkdir(exist_ok=True)
    
    # Set tax year explicitly (since config no longer includes it)
    tax_year = 2024
    
    # Load inputs
    print("\n1. Loading input files...")
    config = load_config(examples_dir / "config.json")
    print(f"   Config: Tax year {tax_year}, PFIC {config.pfic_ticker}")
    
    beginning_lots = load_lots(examples_dir / "beginning_lots.json")
    print(f"   Beginning lots: {len(beginning_lots)}")
    for lot in beginning_lots:
        print(f"      {lot.lot_id}: {lot.shares} shares, basis ${lot.cost_basis_usd}")
    
    transactions = load_transactions(examples_dir / "transactions.csv", config.default_currency)
    print(f"   Transactions: {len(transactions)}")
    for txn in transactions:
        print(f"      {txn.date}: {txn.transaction_type.value} {txn.shares} shares")
    
    ais_data = load_ais_data(examples_dir / "ais_xeqt_2024.json")
    print(f"   AIS: {ais_data.fund_ticker} with {len(ais_data.underlying_pfics)} underlying PFICs")
    
    # Convert transactions to USD
    print("\n2. Converting transactions to USD...")
    converter = create_mock_converter()
    
    for txn in transactions:
        amount_usd, rate = converter.to_usd(txn.amount, txn.currency, txn.date)
        commission_usd, _ = converter.to_usd(txn.commission, txn.currency, txn.date)
        txn.amount_usd = Decimal(str(round(float(amount_usd), 2)))
        txn.commission_usd = Decimal(str(round(float(commission_usd), 2)))
        txn.exchange_rate = rate
        print(f"   {txn.date}: {txn.currency} {txn.amount} -> USD {txn.amount_usd} (rate: {rate:.4f})")
    
    # Process transactions
    print("\n3. Processing transactions (FIFO)...")
    tracker = LotTracker(beginning_lots)
    
    for txn in sorted(transactions, key=lambda t: t.date):
        affected = tracker.process_transaction(txn)
        for lot in affected:
            if lot.sale_date:
                print(f"   SOLD {lot.lot_id}: {lot.shares} shares, proceeds ${lot.proceeds_usd}")
            else:
                print(f"   CREATED {lot.lot_id}: {lot.shares} shares, basis ${lot.cost_basis_usd}")
    
    print(f"\n   Held lots after transactions: {len(tracker.held_lots)}")
    print(f"   Sold lots: {len(tracker.sold_lots)}")
    
    # Calculate QEF adjustments
    print("\n4. Calculating QEF adjustments...")
    adjustments = apply_qef_adjustments(tracker, tax_year, ais_data)
    
    for adj in adjustments:
        print(f"   {adj.lot_id}: +${adj.ordinary_earnings_usd} earnings, "
              f"+${adj.capital_gains_usd} gains, -${adj.distributions_usd} dist "
              f"= ${adj.net_adjustment_usd:+} net")
    
    # Generate Form 8621 data
    print("\n5. Generating Form 8621 data...")
    form_8621_data = generate_form_8621_data(adjustments, ais_data)
    
    for f in form_8621_data:
        holding = "Direct" if f.is_direct_holding else "Indirect"
        print(f"   {f.fund_ticker} ({holding}): "
              f"6a=${f.line_6a_ordinary_earnings_usd}, "
              f"7a=${f.line_7a_net_capital_gains_usd}")
    
    # Generate reports
    print("\n6. Generating reports...")
    
    sales = generate_sales_report(tracker)
    print(f"   Sales report: {len(sales)} sales")
    
    report = generate_lot_activity_report(
        config,
        beginning_lots,
        transactions,
        tracker,
        adjustments,
        form_8621_data,
        tax_year=tax_year,
    )
    
    # Save outputs
    print("\n7. Saving output files...")
    
    save_form_8621_data(form_8621_data, output_dir / "form_8621_data.json")
    save_form_8621_csv(form_8621_data, output_dir / "form_8621_data.csv")
    print("   - form_8621_data.json/csv")
    
    if sales:
        save_sales_report(sales, output_dir / "sales_report.json")
        save_sales_csv(sales, output_dir / "sales_report.csv")
        print("   - sales_report.json/csv")
    
    save_basis_adjustments(adjustments, output_dir / "basis_adjustments.json")
    print("   - basis_adjustments.json")
    
    ending_lots = tracker.get_ending_lots()
    save_lots(ending_lots, output_dir / "year_end_lots.json")
    print("   - year_end_lots.json")
    
    save_lot_activity_report(report, output_dir / "lot_activity_report.json")
    print("   - lot_activity_report.json")
    
    summary = generate_text_summary(report)
    with open(output_dir / "summary.txt", 'w') as f:
        f.write(summary)
    print("   - summary.txt")
    
    # Try PDF generation
    try:
        from pfic_qef_tool.formatters.pdf_report import create_pdf_report
        create_pdf_report(report, output_dir / "report.pdf")
        print("   - report.pdf")
    except ImportError as e:
        print(f"   - report.pdf (skipped: {e})")
    
    # Print summary
    print("\n" + "=" * 60)
    print("TEXT SUMMARY")
    print("=" * 60)
    print(summary)
    
    print("\n" + "=" * 60)
    print("Integration test completed successfully!")
    print(f"Output files saved to: {output_dir}")
    print("=" * 60)
    
    return True


if __name__ == "__main__":
    success = run_integration_test()
    sys.exit(0 if success else 1)

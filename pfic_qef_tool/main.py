"""
PFIC QEF Tax Tool - Main entry point and orchestration.

This tool assists U.S. taxpayers in calculating QEF (Qualified Electing Fund)
income and basis adjustments for PFIC (Passive Foreign Investment Company)
holdings.

Usage:
    python -m pfic_qef_tool.main --config config.json --lots beginning_lots.csv \
        --transactions txns.csv --ais ais.json --output-dir ./output

DISCLAIMER: This tool is for informational purposes only and does not
constitute tax advice. Consult a qualified tax professional for your
specific situation.
"""

import argparse
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .models import Config, Lot, Transaction, AISData, round_money
from .lot_tracker import LotTracker, UNKNOWN_PURCHASE_DATE
from .currency import CurrencyConverter, ExchangeRateCache
from .qef_calculator import apply_qef_adjustments, generate_form_8621_data
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
    save_form_8621_csv,
    save_sales_report,
    save_sales_csv,
    save_basis_adjustments,
    save_lot_activity_report,
)

# Try to import Excel support (optional dependency)
try:
    from .excel_io import (
        create_template_workbook,
        load_from_excel,
        save_results_to_excel,
        OPENPYXL_AVAILABLE,
    )
except ImportError:
    OPENPYXL_AVAILABLE = False


class RunReport:
    """Tracks information about a tool run for reporting."""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.end_time: Optional[datetime] = None
        self.inputs: dict = {}
        self.outputs: list[str] = []
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.statistics: dict = {}
        self.unknown_lots: list[str] = []
    
    def add_input(self, name: str, path: Optional[Path], record_count: int = 0):
        """Record an input file."""
        self.inputs[name] = {
            "path": str(path) if path else None,
            "exists": path.exists() if path else False,
            "record_count": record_count,
        }
    
    def add_output(self, path: Path):
        """Record an output file."""
        self.outputs.append(str(path))
    
    def add_warning(self, message: str):
        """Add a warning message."""
        self.warnings.append(message)
    
    def add_error(self, message: str):
        """Add an error message."""
        self.errors.append(message)
    
    def finalize(self):
        """Mark the run as complete."""
        self.end_time = datetime.now()
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "run_timestamp": self.start_time.isoformat(),
            "duration_seconds": (
                (self.end_time - self.start_time).total_seconds()
                if self.end_time else None
            ),
            "inputs": self.inputs,
            "outputs": self.outputs,
            "warnings": self.warnings,
            "errors": self.errors,
            "statistics": self.statistics,
            "unknown_lots": self.unknown_lots,
            "success": len(self.errors) == 0,
        }
    
    def generate_text_report(self) -> str:
        """Generate a human-readable run report."""
        lines = []
        lines.append("=" * 70)
        lines.append("PFIC QEF TAX TOOL - RUN REPORT")
        lines.append("=" * 70)
        lines.append(f"Run started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        if self.end_time:
            duration = (self.end_time - self.start_time).total_seconds()
            lines.append(f"Run completed: {self.end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append(f"Duration: {duration:.2f} seconds")
        lines.append("")
        
        # Inputs
        lines.append("INPUT FILES")
        lines.append("-" * 40)
        for name, info in self.inputs.items():
            status = "✓" if info["exists"] else "✗ (not found)"
            path = info["path"] or "(not provided)"
            count = f" ({info['record_count']} records)" if info["record_count"] else ""
            lines.append(f"  {name}: {path} {status}{count}")
        lines.append("")
        
        # Statistics
        if self.statistics:
            lines.append("PROCESSING SUMMARY")
            lines.append("-" * 40)
            for key, value in self.statistics.items():
                lines.append(f"  {key}: {value}")
            lines.append("")
        
        # Warnings
        if self.warnings:
            lines.append("⚠ WARNINGS")
            lines.append("-" * 40)
            for warning in self.warnings:
                lines.append(f"  • {warning}")
            lines.append("")
        
        # Unknown lots
        if self.unknown_lots:
            lines.append("⚠ LOTS WITH UNKNOWN PURCHASE DATE / COST BASIS")
            lines.append("-" * 40)
            lines.append("  The following lots were created with $0 cost basis and")
            lines.append("  an unknown purchase date (shown as 1900-01-01) because")
            lines.append("  shares were sold without sufficient lot history:")
            for lot_id in self.unknown_lots:
                lines.append(f"  • {lot_id}")
            lines.append("")
            lines.append("  ACTION REQUIRED: Review these lots and update their")
            lines.append("  purchase dates and cost basis if you have records.")
            lines.append("")
        
        # Errors
        if self.errors:
            lines.append("✗ ERRORS")
            lines.append("-" * 40)
            for error in self.errors:
                lines.append(f"  • {error}")
            lines.append("")
        
        # Outputs
        lines.append("OUTPUT FILES")
        lines.append("-" * 40)
        for path in self.outputs:
            lines.append(f"  • {path}")
        lines.append("")
        
        # Status
        lines.append("=" * 70)
        if self.errors:
            lines.append("STATUS: COMPLETED WITH ERRORS")
        elif self.warnings:
            lines.append("STATUS: COMPLETED WITH WARNINGS")
        else:
            lines.append("STATUS: COMPLETED SUCCESSFULLY")
        lines.append("=" * 70)
        
        return "\n".join(lines)


def convert_transactions_to_usd(
    transactions: list[Transaction],
    converter: Optional[CurrencyConverter],
    run_report: RunReport,
    use_boc_rates: bool = False,
) -> list[Transaction]:
    """
    Convert all transaction amounts to USD.
    
    Priority:
    1. User-provided exchange_rate on transaction (always used if present)
    2. USD transactions (rate = 1.0)
    3. BoC API rate (if use_boc_rates is True)
    4. Error (if non-USD without rate and use_boc_rates is False)
    
    Updates transactions in-place and returns them.
    Raises ValueError if missing rates and use_boc_rates is False.
    """
    missing_rates = []
    
    for txn in transactions:
        # If user provided an exchange rate, use it
        if txn.exchange_rate is not None:
            rate = txn.exchange_rate
            txn.amount_usd = round_money(txn.amount * rate)
            txn.commission_usd = round_money(txn.commission * rate)
            continue
        
        # USD transactions don't need conversion
        if txn.currency.upper() == "USD":
            txn.amount_usd = txn.amount
            txn.commission_usd = txn.commission
            txn.exchange_rate = Decimal("1")
            continue
        
        # Non-USD without user rate - need BoC or error
        if not use_boc_rates:
            missing_rates.append(f"  - {txn.date}: {txn.transaction_type.value} {txn.shares} shares ({txn.currency})")
            continue
        
        # Try to fetch from BoC
        if converter is None:
            missing_rates.append(f"  - {txn.date}: {txn.transaction_type.value} {txn.shares} shares ({txn.currency}) - no converter available")
            continue
            
        try:
            amount_usd, rate = converter.to_usd(
                txn.amount,
                txn.currency,
                txn.date,
            )
            commission_usd, _ = converter.to_usd(
                txn.commission,
                txn.currency,
                txn.date,
            )
            
            txn.amount_usd = round_money(amount_usd)
            txn.commission_usd = round_money(commission_usd)
            txn.exchange_rate = rate
        except Exception as e:
            run_report.add_warning(
                f"Could not fetch BoC rate for {txn.date}: {e}. "
                f"Using 1:1 exchange rate."
            )
            txn.amount_usd = txn.amount
            txn.commission_usd = txn.commission
            txn.exchange_rate = Decimal("1")
    
    # If we have missing rates and BoC is disabled, raise error
    if missing_rates:
        error_msg = (
            f"Missing exchange rates for {len(missing_rates)} transaction(s):\n"
            + "\n".join(missing_rates) + "\n\n"
            "Either:\n"
            "  1. Add exchange_rate column to your transactions file, or\n"
            "  2. Use --use-boc-rates flag to fetch rates from Bank of Canada API"
        )
        raise ValueError(error_msg)
    
    return transactions


def process_year(
    config: Config,
    beginning_lots: list[Lot],
    transactions: list[Transaction],
    ais_data: AISData,
    converter: Optional[CurrencyConverter],
    run_report: RunReport,
    verbose: bool = False,
    tax_year: Optional[int] = None,
    use_boc_rates: bool = False,
) -> tuple:
    """
    Process a full tax year.
    
    Returns:
        (tracker, adjustments, form_8621_data, report)
    """
    # Use provided tax_year or fall back to config
    year = tax_year if tax_year is not None else config.tax_year
    
    if verbose:
        print(f"Processing tax year {year}")
        print(f"PFIC: {config.pfic_name} ({config.pfic_ticker})")
        print(f"Beginning lots: {len(beginning_lots)}")
        print(f"Transactions: {len(transactions)}")
    
    # Update statistics
    run_report.statistics["tax_year"] = year
    run_report.statistics["pfic_ticker"] = config.pfic_ticker
    run_report.statistics["beginning_lots"] = len(beginning_lots)
    run_report.statistics["transactions"] = len(transactions)
    
    # Step 1: Convert transactions to USD (if any)
    if transactions:
        if verbose:
            print("\nConverting transactions to USD...")
        
        # Try to prefetch rates for the year (only if using BoC rates)
        if use_boc_rates and converter:
            try:
                converter.prefetch_year(year)
            except Exception as e:
                run_report.add_warning(f"Could not prefetch exchange rates: {e}")
        
        transactions = convert_transactions_to_usd(transactions, converter, run_report, use_boc_rates)
        
        if verbose:
            for txn in transactions:
                print(f"  {txn.date}: {txn.transaction_type.value} {txn.shares} shares "
                      f"@ ${txn.amount_usd} (rate: {txn.exchange_rate:.6f})")
    else:
        if verbose:
            print("\nNo transactions to process.")
    
    # Step 2: Process transactions (FIFO)
    if verbose:
        print("\nProcessing transactions...")
    
    tracker = LotTracker(beginning_lots if beginning_lots else None)
    
    # Track processed transactions (within tax year only)
    processed_transactions = []
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    
    for txn in sorted(transactions, key=lambda t: t.date):
        # Check if transaction is outside tax year
        if txn.date < year_start or txn.date > year_end:
            warning = (f"Transaction {txn.date} ({txn.transaction_type.value}) "
                      f"is outside tax year {year} - ignoring")
            run_report.add_warning(warning)
            if verbose:
                print(f"  WARNING: {warning}")
            continue
        
        # Track this as a processed transaction
        processed_transactions.append(txn)
        
        affected = tracker.process_transaction(txn)
        if verbose:
            for lot in affected:
                if lot.status.value == "SOLD":
                    print(f"  Sold {lot.lot_id}: {lot.shares} shares, "
                          f"proceeds ${lot.proceeds_usd}")
                else:
                    print(f"  Created {lot.lot_id}: {lot.shares} shares, "
                          f"basis ${lot.cost_basis_usd}")
    
    # Collect warnings from tracker
    for warning in tracker.warnings:
        run_report.add_warning(warning)
    run_report.unknown_lots = tracker.unknown_lots
    
    # Step 3: Calculate QEF adjustments
    if verbose:
        print("\nCalculating QEF adjustments...")
    
    adjustments = apply_qef_adjustments(tracker, year, ais_data)
    
    if verbose:
        for adj in adjustments:
            print(f"  {adj.lot_id}: +${adj.ordinary_earnings_usd} earnings, "
                  f"+${adj.capital_gains_usd} gains, "
                  f"-${adj.distributions_usd} distributions = "
                  f"${adj.net_adjustment_usd:+} net")
    
    # Step 4: Generate Form 8621 data
    if verbose:
        print("\nGenerating Form 8621 data...")
    
    form_8621_data = generate_form_8621_data(adjustments, ais_data)
    
    if verbose:
        for f in form_8621_data:
            holding = "Direct" if f.is_direct_holding else "Indirect"
            print(f"  {f.fund_ticker} ({holding}): "
                  f"6a=${f.line_6a_ordinary_earnings_usd}, "
                  f"7a=${f.line_7a_net_capital_gains_usd}")
    
    # Update statistics
    run_report.statistics["lots_sold"] = len(tracker.sold_lots)
    run_report.statistics["lots_held_year_end"] = len(tracker.held_lots)
    run_report.statistics["form_8621_count"] = len(form_8621_data)
    
    total_qef = sum(
        f.line_6a_ordinary_earnings_usd + f.line_7a_net_capital_gains_usd
        for f in form_8621_data
    )
    run_report.statistics["total_qef_income_usd"] = str(round_money(total_qef))
    
    # Step 5: Generate full report (using only processed transactions)
    report = generate_lot_activity_report(
        config,
        beginning_lots,
        processed_transactions,  # Only BUY/SELL from this tax year
        tracker,
        adjustments,
        form_8621_data,
        tax_year=year,
    )
    
    return tracker, adjustments, form_8621_data, report


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="PFIC QEF Tax Tool - Calculate QEF income and basis adjustments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
DISCLAIMER: This tool is for informational purposes only and does not
constitute tax advice. Consult a qualified tax professional for your
specific situation.

Example usage (separate files):
    python -m pfic_qef_tool.main \\
        --config config.json \\
        --lots beginning_lots.json \\
        --transactions transactions.csv \\
        --ais ais_data.json \\
        --output-dir ./output

Example usage (Excel workbook):
    # First, create a template:
    python -m pfic_qef_tool.main --create-template my_pfic_data.xlsx
    
    # Fill in the template, then run:
    python -m pfic_qef_tool.main --excel my_pfic_data.xlsx --output-dir ./output

Notes:
    - Use --excel for a single-file workflow (requires: pip install openpyxl)
    - --lots is optional for the first year of ownership
    - --transactions is optional for years with no activity
    - If shares are sold without sufficient lot history, synthetic lots
      with $0 basis will be created and flagged in the run report
        """,
    )
    
    parser.add_argument(
        "--config",
        type=Path,
        required=False,
        help="Path to configuration JSON file (not needed if using --excel)",
    )
    parser.add_argument(
        "--lots",
        type=Path,
        default=None,
        help="Path to beginning lots JSON file (optional if no prior holdings)",
    )
    parser.add_argument(
        "--transactions",
        type=Path,
        default=None,
        help="Path to transactions CSV file (optional if no activity)",
    )
    parser.add_argument(
        "--ais",
        type=Path,
        required=False,
        help="Path to AIS data JSON file (not needed if using --excel)",
    )
    parser.add_argument(
        "--year",
        type=int,
        help="Tax year to process (required for JSON/CSV mode, optional for Excel mode)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./output"),
        help="Directory for output files (default: ./output)",
    )
    parser.add_argument(
        "--rate-cache",
        type=Path,
        help="Path to exchange rate cache file (optional)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print verbose output",
    )
    parser.add_argument(
        "--use-boc-rates",
        action="store_true",
        help="Fetch exchange rates from Bank of Canada API for CAD transactions without rates",
    )
    parser.add_argument(
        "--excel",
        type=Path,
        help="Path to Excel workbook containing all inputs (alternative to separate files)",
    )
    parser.add_argument(
        "--create-template",
        type=Path,
        metavar="OUTPUT_PATH",
        help="Create a template Excel workbook at the specified path and exit",
    )
    parser.add_argument(
        "--template-year",
        type=int,
        default=2024,
        help="Tax year to use in template (default: 2024)",
    )
    
    args = parser.parse_args()
    
    # Handle --create-template
    if args.create_template:
        if not OPENPYXL_AVAILABLE:
            print("ERROR: openpyxl is required for Excel support.")
            print("Install it with: pip install openpyxl")
            return 1
        
        print(f"Creating template Excel workbook at {args.create_template}...")
        create_template_workbook(args.create_template, args.template_year)
        print("Done! Fill in the workbook and run with --excel flag.")
        return 0
    
    # Initialize run report
    run_report = RunReport()
    
    try:
        # Load input data - either from Excel or separate files
        if args.excel:
            if not OPENPYXL_AVAILABLE:
                print("ERROR: openpyxl is required for Excel support.")
                print("Install it with: pip install openpyxl")
                return 1
            
            print(f"Loading all inputs from Excel workbook: {args.excel}...")
            config, beginning_lots, transactions, ais_data = load_from_excel(args.excel)
            run_report.add_input("excel_workbook", args.excel, 1)
            
            # For Excel mode, tax_year comes from the Excel Config sheet
            # But CLI --year can override if provided
            if args.year:
                tax_year = args.year
            elif config.tax_year:
                tax_year = config.tax_year
            else:
                print("ERROR: Tax year not found in Excel Config sheet. Specify with --year.")
                return 1
            
            print(f"  Tax Year: {tax_year}")
            print(f"  PFIC: {config.pfic_ticker}")
            print(f"  Beginning lots: {len(beginning_lots)}")
            print(f"  Transactions: {len(transactions)}")
            print(f"  AIS: {ais_data.fund_ticker} + {len(ais_data.underlying_pfics)} underlying PFICs")
        else:
            # Original file-based loading
            if not args.config:
                print("ERROR: Either --config or --excel is required")
                return 1
            if not args.ais:
                print("ERROR: Either --ais or --excel is required")
                return 1
            if not args.year:
                print("ERROR: --year is required for JSON/CSV mode")
                return 1
            
            tax_year = args.year
            
            # Load input data from separate files
            print(f"Loading configuration from {args.config}...")
            config = load_config(args.config)
            run_report.add_input("config", args.config, 1)
            
            # Load beginning lots (optional)
            beginning_lots = load_lots(args.lots, filter_ticker=config.pfic_ticker)
            run_report.add_input("beginning_lots", args.lots, len(beginning_lots))
            if beginning_lots:
                print(f"Loaded {len(beginning_lots)} beginning lots from {args.lots}")
            else:
                print("No beginning lots (first year of ownership or file not found)")
            
            # Load transactions (optional)
            transactions = load_transactions(
                args.transactions, 
                config.default_currency,
                filter_ticker=config.pfic_ticker,
            ) if args.transactions else []
            run_report.add_input("transactions", args.transactions, len(transactions))
            if transactions:
                print(f"Loaded {len(transactions)} transactions from {args.transactions}")
            else:
                print("No transactions for this tax year")
            
            # Load AIS data
            print(f"Loading AIS data from {args.ais}...")
            ais_data = load_ais_data(args.ais)
            run_report.add_input("ais_data", args.ais, 1 + len(ais_data.underlying_pfics))
        
        # Create output subdirectory: {ticker}_qef_{year}/
        ticker_lower = config.pfic_ticker.lower()
        output_subdir = args.output_dir / f"{ticker_lower}_qef_{tax_year}"
        output_subdir.mkdir(parents=True, exist_ok=True)
        print(f"Output directory: {output_subdir}")
        
        # Validate AIS year matches tax year
        if ais_data.tax_year != tax_year:
            warning = (f"AIS tax year ({ais_data.tax_year}) does not match "
                      f"processing tax year ({tax_year})")
            print(f"WARNING: {warning}")
            run_report.add_warning(warning)
        
        # Check if there's anything to process
        if not beginning_lots and not transactions:
            warning = "No beginning lots and no transactions - nothing to process"
            print(f"WARNING: {warning}")
            run_report.add_warning(warning)
        
        # Set up currency converter (only if using BoC rates)
        converter = None
        if args.use_boc_rates:
            cache_file = str(args.rate_cache) if args.rate_cache else None
            converter = CurrencyConverter(cache_file=cache_file)
            print("Using Bank of Canada exchange rates for CAD transactions without rates")
        
        # Process the year
        tracker, adjustments, form_8621_data, report = process_year(
            config,
            beginning_lots,
            transactions,
            ais_data,
            converter,
            run_report,
            verbose=args.verbose,
            tax_year=tax_year,
            use_boc_rates=args.use_boc_rates,
        )
        
        # Save outputs with ticker and year in filenames
        print(f"\nSaving outputs to {output_subdir}/...")
        
        # Form 8621 data
        f8621_json = output_subdir / f"{ticker_lower}_form_8621_data_{tax_year}.json"
        f8621_csv = output_subdir / f"{ticker_lower}_form_8621_data_{tax_year}.csv"
        save_form_8621_data(form_8621_data, f8621_json)
        save_form_8621_csv(form_8621_data, f8621_csv)
        run_report.add_output(f8621_json)
        run_report.add_output(f8621_csv)
        print(f"  - {f8621_json.name}")
        print(f"  - {f8621_csv.name}")
        
        # Sales report
        sales = generate_sales_report(tracker)
        if sales:
            sales_json = output_subdir / f"{ticker_lower}_sales_report_{tax_year}.json"
            sales_csv = output_subdir / f"{ticker_lower}_sales_report_{tax_year}.csv"
            save_sales_report(sales, sales_json)
            save_sales_csv(sales, sales_csv)
            run_report.add_output(sales_json)
            run_report.add_output(sales_csv)
            print(f"  - {sales_json.name}")
            print(f"  - {sales_csv.name}")
        
        # Basis adjustments
        basis_json = output_subdir / f"{ticker_lower}_basis_adjustments_{tax_year}.json"
        save_basis_adjustments(adjustments, basis_json)
        run_report.add_output(basis_json)
        print(f"  - {basis_json.name}")
        
        # Year-end lots (for next year's input)
        ending_lots = tracker.get_ending_lots()
        year_end_csv = output_subdir / f"{ticker_lower}_lots_held_end_of_{tax_year}.csv"
        save_lots(ending_lots, year_end_csv)
        run_report.add_output(year_end_csv)
        print(f"  - {year_end_csv.name}")
        
        # Full activity report
        activity_json = output_subdir / f"{ticker_lower}_lot_activity_report_{tax_year}.json"
        save_lot_activity_report(report, activity_json)
        run_report.add_output(activity_json)
        print(f"  - {activity_json.name}")
        
        # Text summary
        summary = generate_text_summary(report)
        summary_path = output_subdir / f"{ticker_lower}_summary_{tax_year}.txt"
        with open(summary_path, 'w') as f:
            f.write(summary)
        run_report.add_output(summary_path)
        print(f"  - {summary_path.name}")
        
        # Try PDF generation
        try:
            from .formatters.pdf_report import create_pdf_report
            pdf_path = output_subdir / f"{ticker_lower}_qef_report_{tax_year}.pdf"
            create_pdf_report(report, pdf_path)
            run_report.add_output(pdf_path)
            print(f"  - {pdf_path.name}")
        except ImportError:
            print(f"  - {ticker_lower}_qef_report_{tax_year}.pdf (skipped - reportlab not installed)")
        except Exception as e:
            run_report.add_warning(f"Could not generate PDF: {e}")
            print(f"  - {ticker_lower}_qef_report_{tax_year}.pdf (skipped - {e})")
        
        # Finalize and save run report
        run_report.finalize()
        
        run_report_json = output_subdir / f"{ticker_lower}_run_report_{tax_year}.json"
        with open(run_report_json, 'w') as f:
            json.dump(run_report.to_dict(), f, indent=2)
        run_report.add_output(run_report_json)
        print(f"  - {run_report_json.name}")
        
        run_report_txt = output_subdir / f"{ticker_lower}_run_report_{tax_year}.txt"
        with open(run_report_txt, 'w') as f:
            f.write(run_report.generate_text_report())
        print(f"  - {run_report_txt.name}")
        
        # Try Excel output
        if OPENPYXL_AVAILABLE:
            try:
                excel_path = output_subdir / f"{ticker_lower}_results_{tax_year}.xlsx"
                save_results_to_excel(
                    excel_path,
                    form_8621_data,
                    sales,
                    adjustments,
                    ending_lots,
                    report,
                )
                run_report.add_output(excel_path)
                print(f"  - {excel_path.name}")
            except Exception as e:
                run_report.add_warning(f"Could not generate Excel output: {e}")
                print(f"  - {ticker_lower}_results_{tax_year}.xlsx (skipped - {e})")
        
        # Print reports to console
        print("\n")
        print(run_report.generate_text_report())
        print("\n")
        print(summary)
        
        print("\nDone!")
        return 0
        
    except Exception as e:
        run_report.add_error(str(e))
        run_report.finalize()
        print(f"\nERROR: {e}")
        print(run_report.generate_text_report())
        return 1


def run_interactive(
    config_path: str,
    lots_path: Optional[str] = None,
    transactions_path: Optional[str] = None,
    ais_path: str = None,
    output_dir: str = "./output",
    rate_cache_path: Optional[str] = None,
):
    """
    Run the tool programmatically (for use in notebooks or other scripts).
    
    Args:
        config_path: Path to configuration JSON file
        lots_path: Path to beginning lots JSON (optional)
        transactions_path: Path to transactions CSV (optional)
        ais_path: Path to AIS data JSON
        output_dir: Directory for output files
        rate_cache_path: Path to exchange rate cache (optional)
    
    Returns:
        Tuple of (LotActivityReport, RunReport)
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    run_report = RunReport()
    
    # Load data
    config = load_config(config_path)
    run_report.add_input("config", Path(config_path), 1)
    
    beginning_lots = load_lots(lots_path, filter_ticker=config.pfic_ticker) if lots_path else []
    run_report.add_input("beginning_lots", Path(lots_path) if lots_path else None, len(beginning_lots))
    
    transactions = load_transactions(
        transactions_path, 
        config.default_currency,
        filter_ticker=config.pfic_ticker
    ) if transactions_path else []
    run_report.add_input("transactions", Path(transactions_path) if transactions_path else None, len(transactions))
    
    ais_data = load_ais_data(ais_path)
    run_report.add_input("ais_data", Path(ais_path), 1 + len(ais_data.underlying_pfics))
    
    # Set up converter
    converter = CurrencyConverter(cache_file=rate_cache_path)
    
    # Process
    tracker, adjustments, form_8621_data, report = process_year(
        config,
        beginning_lots,
        transactions,
        ais_data,
        converter,
        run_report,
    )
    
    # Save outputs
    save_form_8621_data(form_8621_data, output_path / "form_8621_data.json")
    save_form_8621_csv(form_8621_data, output_path / "form_8621_data.csv")
    run_report.add_output(output_path / "form_8621_data.json")
    run_report.add_output(output_path / "form_8621_data.csv")
    
    sales = generate_sales_report(tracker)
    if sales:
        save_sales_report(sales, output_path / "sales_report.json")
        save_sales_csv(sales, output_path / "sales_report.csv")
        run_report.add_output(output_path / "sales_report.json")
        run_report.add_output(output_path / "sales_report.csv")
    
    save_basis_adjustments(adjustments, output_path / "basis_adjustments.json")
    run_report.add_output(output_path / "basis_adjustments.json")
    
    save_lots(tracker.get_ending_lots(), output_path / "year_end_lots.csv")
    run_report.add_output(output_path / "year_end_lots.csv")
    
    save_lot_activity_report(report, output_path / "lot_activity_report.json")
    run_report.add_output(output_path / "lot_activity_report.json")
    
    summary = generate_text_summary(report)
    with open(output_path / "summary.txt", 'w') as f:
        f.write(summary)
    run_report.add_output(output_path / "summary.txt")
    
    # Try PDF
    try:
        from .formatters.pdf_report import create_pdf_report
        create_pdf_report(report, output_path / "report.pdf")
        run_report.add_output(output_path / "report.pdf")
    except:
        pass
    
    run_report.finalize()
    
    # Save run report
    with open(output_path / "run_report.json", 'w') as f:
        json.dump(run_report.to_dict(), f, indent=2)
    with open(output_path / "run_report.txt", 'w') as f:
        f.write(run_report.generate_text_report())
    
    return report, run_report


if __name__ == "__main__":
    sys.exit(main())

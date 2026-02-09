"""
GUI for PFIC QEF Tax Tool.

A simple tkinter-based interface for running the tool without command line.
"""

import os
import sys
import threading
import traceback
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# Add parent to path for imports
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from pfic_qef_tool.models import Config
from pfic_qef_tool.serialization import (
    load_config, load_lots, load_transactions, load_ais_data,
    save_lots, save_form_8621_data, save_form_8621_csv,
    save_sales_report, save_sales_csv, save_basis_adjustments,
    save_lot_activity_report
)
from pfic_qef_tool.lot_tracker import LotTracker
from pfic_qef_tool.currency import CurrencyConverter
from pfic_qef_tool.qef_calculator import apply_qef_adjustments, generate_form_8621_data
from pfic_qef_tool.reports import (
    generate_sales_report, generate_lot_activity_report, generate_text_summary
)
from pfic_qef_tool.models import round_money


class PFICToolGUI:
    """Main GUI application."""
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PFIC QEF Tax Tool")
        self.root.geometry("800x1000")
        self.root.minsize(700, 600)
        
        # Variables for file paths
        self.config_path = tk.StringVar()
        self.lots_path = tk.StringVar()
        self.transactions_path = tk.StringVar()
        self.ais_path = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(Path.home() / "pfic_output"))
        self.excel_path = tk.StringVar()
        
        # Tax year (for Individual Files mode)
        from datetime import date
        self.tax_year = tk.StringVar(value=str(date.today().year - 1))
        
        # Mode: 'files' or 'excel'
        self.input_mode = tk.StringVar(value='files')
        
        # Use Bank of Canada exchange rates (off by default)
        self.use_boc_rates = tk.BooleanVar(value=False)
        
        # Build the UI
        self._build_ui()
    
    def _build_ui(self):
        """Build the user interface."""
        # Main container with padding
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(
            main_frame, 
            text="PFIC QEF Tax Tool",
            font=('Helvetica', 16, 'bold')
        )
        title_label.pack(pady=(0, 10))
        
        subtitle = ttk.Label(
            main_frame,
            text="Calculate QEF income and basis adjustments for PFIC holdings",
            font=('Helvetica', 10)
        )
        subtitle.pack(pady=(0, 15))
        
        # Notebook for input modes
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Tab 1: Individual Files
        files_frame = ttk.Frame(notebook, padding="10")
        notebook.add(files_frame, text="Individual Files")
        self._build_files_tab(files_frame)
        
        # Tab 2: Excel Workbook
        excel_frame = ttk.Frame(notebook, padding="10")
        notebook.add(excel_frame, text="Excel Workbook")
        self._build_excel_tab(excel_frame)
        
        # Output directory (shared)
        output_frame = ttk.LabelFrame(main_frame, text="Output Directory", padding="5")
        output_frame.pack(fill=tk.X, pady=(0, 10))
        
        output_entry = ttk.Entry(output_frame, textvariable=self.output_dir, width=60)
        output_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        output_btn = ttk.Button(
            output_frame, 
            text="Browse...",
            command=lambda: self._browse_directory(self.output_dir)
        )
        output_btn.pack(side=tk.RIGHT)
        
        # Exchange rate options
        rate_frame = ttk.LabelFrame(main_frame, text="Exchange Rate Options", padding="5")
        rate_frame.pack(fill=tk.X, pady=(0, 10))
        
        boc_check = ttk.Checkbutton(
            rate_frame,
            text="Use Bank of Canada exchange rates for CAD transactions",
            variable=self.use_boc_rates
        )
        boc_check.pack(anchor='w')
        
        rate_note = ttk.Label(
            rate_frame,
            text="If unchecked, you must provide exchange_rate in your transactions file for all CAD transactions.",
            font=('Helvetica', 8),
            foreground='gray'
        )
        rate_note.pack(anchor='w', pady=(2, 0))
        
        # Process button
        self.process_btn = ttk.Button(
            main_frame,
            text="Process Tax Year",
            command=self._process,
            style='Accent.TButton'
        )
        self.process_btn.pack(pady=10)
        
        # Progress bar
        self.progress = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress.pack(fill=tk.X, pady=(0, 10))
        
        # Log output
        log_frame = ttk.LabelFrame(main_frame, text="Output Log", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = scrolledtext.ScrolledText(
            log_frame, 
            height=12,
            font=('Consolas', 9),
            state='disabled'
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Open output folder button
        self.open_folder_btn = ttk.Button(
            main_frame,
            text="Open Output Folder",
            command=self._open_output_folder,
            state='disabled'
        )
        self.open_folder_btn.pack(pady=(10, 0))
        
        # Disclaimer
        disclaimer = ttk.Label(
            main_frame,
            text="⚠️ This tool is for informational purposes only. Consult a tax professional.",
            font=('Helvetica', 8),
            foreground='gray'
        )
        disclaimer.pack(pady=(10, 0))
    
    def _build_files_tab(self, parent):
        """Build the individual files input tab."""
        # Instructions
        instructions = ttk.Label(
            parent,
            text="Provide PFIC information below OR upload a config file.\n"
                 "Beginning Lots and Transactions files are optional.",
            font=('Helvetica', 9),
            foreground='gray'
        )
        instructions.pack(anchor='w', pady=(0, 10))
        
        # PFIC Information Frame
        pfic_frame = ttk.LabelFrame(parent, text="Option 1: Enter PFIC Information Manually", padding=10)
        pfic_frame.pack(fill=tk.X, pady=(0, 5))
        
        # PFIC Ticker
        ticker_frame = ttk.Frame(pfic_frame)
        ticker_frame.pack(fill=tk.X, pady=2)
        ttk.Label(ticker_frame, text="PFIC Ticker: *", width=22, anchor='e').pack(side=tk.LEFT)
        self.pfic_ticker = tk.StringVar()
        ttk.Entry(ticker_frame, textvariable=self.pfic_ticker, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Label(ticker_frame, text="(e.g., XEQT, VEQT)", foreground='gray').pack(side=tk.LEFT)
        
        # PFIC Name
        name_frame = ttk.Frame(pfic_frame)
        name_frame.pack(fill=tk.X, pady=2)
        ttk.Label(name_frame, text="PFIC Name: *", width=22, anchor='e').pack(side=tk.LEFT)
        self.pfic_name = tk.StringVar()
        ttk.Entry(name_frame, textvariable=self.pfic_name, width=45).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        # Default Currency
        currency_frame = ttk.Frame(pfic_frame)
        currency_frame.pack(fill=tk.X, pady=2)
        ttk.Label(currency_frame, text="Default Currency:", width=22, anchor='e').pack(side=tk.LEFT)
        self.default_currency = tk.StringVar(value="CAD")
        currency_combo = ttk.Combobox(currency_frame, textvariable=self.default_currency, width=8, state='readonly', values=["CAD", "USD"])
        currency_combo.pack(side=tk.LEFT, padx=5)
        ttk.Label(currency_frame, text="(CAD for Canadian ETFs)", foreground='gray').pack(side=tk.LEFT)
        
        # OR separator with frame
        or_frame = ttk.LabelFrame(parent, text="Option 2: Upload Configuration File with PFIC Information", padding=10)
        or_frame.pack(fill=tk.X, pady=(5, 5))
        
        # Config file (now optional)
        config_frame = ttk.Frame(or_frame)
        config_frame.pack(fill=tk.X, pady=0)
        ttk.Label(config_frame, text="Config File (JSON):", width=22, anchor='e').pack(side=tk.LEFT)
        config_entry = ttk.Entry(config_frame, textvariable=self.config_path, width=45)
        config_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(
            config_frame,
            text="Browse...",
            command=lambda: self._browse_file(self.config_path, [("JSON files", "*.json")])
        ).pack(side=tk.RIGHT)
        
        ttk.Label(or_frame, text="(Config file will override manual entries above if provided)", 
                 foreground='gray', font=('Helvetica', 8, 'italic')).pack(anchor='w', padx=(0, 0), pady=(5, 0))
        
        # Tax Year input
        year_frame = ttk.Frame(parent)
        year_frame.pack(fill=tk.X, pady=3)
        ttk.Label(year_frame, text="Tax Year: *", width=22, anchor='e').pack(side=tk.LEFT)
        ttk.Entry(year_frame, textvariable=self.tax_year, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Label(year_frame, text="(e.g., 2024)", foreground='gray').pack(side=tk.LEFT)
        
        # Separator
        ttk.Separator(parent, orient='horizontal').pack(fill=tk.X, pady=(10, 10))
        ttk.Label(parent, text="Input Files", font=('Helvetica', 10, 'bold')).pack(anchor='w', pady=(0, 5))
        
        # Beginning Lots (CSV)
        lots_frame = ttk.Frame(parent)
        lots_frame.pack(fill=tk.X, pady=3)
        ttk.Label(lots_frame, text="Beginning Lots (CSV):", width=22, anchor='e').pack(side=tk.LEFT)
        ttk.Entry(lots_frame, textvariable=self.lots_path, width=45).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(lots_frame, text="Browse...", 
                  command=lambda: self._browse_file(self.lots_path, [("CSV files", "*.csv")])).pack(side=tk.RIGHT)
        ttk.Label(parent, text="(Leave blank if this is your first year owning this PFIC)", 
                 foreground='gray', font=('Helvetica', 8, 'italic')).pack(anchor='w', padx=(160, 0), pady=(0, 5))
        
        # Transactions (CSV)
        txn_frame = ttk.Frame(parent)
        txn_frame.pack(fill=tk.X, pady=3)
        ttk.Label(txn_frame, text="Transactions (CSV):", width=22, anchor='e').pack(side=tk.LEFT)
        ttk.Entry(txn_frame, textvariable=self.transactions_path, width=45).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(txn_frame, text="Browse...",
                  command=lambda: self._browse_file(self.transactions_path, [("CSV files", "*.csv")])).pack(side=tk.RIGHT)
        ttk.Label(parent, text="(Only BUY/SELL transactions matching the PFIC ticker will be processed)", 
                 foreground='gray', font=('Helvetica', 8, 'italic')).pack(anchor='w', padx=(160, 0), pady=(0, 5))
        
        # AIS Data (JSON)
        ais_frame = ttk.Frame(parent)
        ais_frame.pack(fill=tk.X, pady=3)
        ttk.Label(ais_frame, text="AIS Data (JSON): *", width=22, anchor='e').pack(side=tk.LEFT)
        ttk.Entry(ais_frame, textvariable=self.ais_path, width=45).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(ais_frame, text="Browse...",
                  command=lambda: self._browse_file(self.ais_path, [("JSON files", "*.json")])).pack(side=tk.RIGHT)
    
    def _build_excel_tab(self, parent):
        """Build the Excel workbook input tab."""
        # Instructions
        instructions = ttk.Label(
            parent,
            text="Use a single Excel workbook containing all inputs.\n"
                 "Click 'Create Template' to generate a pre-filled template workbook.",
            font=('Helvetica', 9),
            foreground='gray'
        )
        instructions.pack(anchor='w', pady=(0, 10))
        
        # Excel file input
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=3)
        
        label = ttk.Label(frame, text="Excel Workbook:", width=22, anchor='e')
        label.pack(side=tk.LEFT)
        
        entry = ttk.Entry(frame, textvariable=self.excel_path, width=45)
        entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        btn = ttk.Button(
            frame,
            text="Browse...",
            command=lambda: self._browse_file(
                self.excel_path, 
                [("Excel files", "*.xlsx")]
            )
        )
        btn.pack(side=tk.RIGHT)
        
        # Template buttons
        template_frame = ttk.Frame(parent)
        template_frame.pack(fill=tk.X, pady=20)
        
        create_template_btn = ttk.Button(
            template_frame,
            text="Create Template...",
            command=self._create_excel_template
        )
        create_template_btn.pack(side=tk.LEFT, padx=5)
        
        # Note about openpyxl
        note = ttk.Label(
            parent,
            text="Note: Excel support requires openpyxl (pip install openpyxl)",
            font=('Helvetica', 8),
            foreground='gray'
        )
        note.pack(anchor='w', pady=(10, 0))
    
    def _browse_file(self, var: tk.StringVar, filetypes: list):
        """Open file browser dialog."""
        filename = filedialog.askopenfilename(filetypes=filetypes)
        if filename:
            var.set(filename)
    
    def _browse_directory(self, var: tk.StringVar):
        """Open directory browser dialog."""
        dirname = filedialog.askdirectory()
        if dirname:
            var.set(dirname)
    
    def _log(self, message: str):
        """Add message to log output."""
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')
        self.root.update_idletasks()
    
    def _clear_log(self):
        """Clear the log output."""
        self.log_text.config(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state='disabled')
    
    def _create_excel_template(self):
        """Create an Excel template file."""
        try:
            from pfic_qef_tool.excel_io import create_template_workbook, OPENPYXL_AVAILABLE
            
            if not OPENPYXL_AVAILABLE:
                messagebox.showerror(
                    "Missing Dependency",
                    "openpyxl is required for Excel support.\n\n"
                    "Install it with: pip install openpyxl"
                )
                return
            
            # Ask for save location
            filename = filedialog.asksaveasfilename(
                defaultextension=".xlsx",
                filetypes=[("Excel files", "*.xlsx")],
                initialfile="pfic_input_template.xlsx"
            )
            
            if filename:
                # Ask for tax year
                year = tk.simpledialog.askinteger(
                    "Tax Year",
                    "Enter the tax year for the template:",
                    initialvalue=2024,
                    minvalue=2000,
                    maxvalue=2100
                )
                
                if year:
                    create_template_workbook(filename, year)
                    self.excel_path.set(filename)
                    messagebox.showinfo(
                        "Template Created",
                        f"Template created at:\n{filename}\n\n"
                        "Fill in the sheets and click 'Process Tax Year'."
                    )
        except ImportError:
            messagebox.showerror(
                "Missing Dependency",
                "openpyxl is required for Excel support.\n\n"
                "Install it with: pip install openpyxl"
            )
    
    def _process(self):
        """Process the tax year data."""
        self._clear_log()
        self.process_btn.config(state='disabled')
        self.open_folder_btn.config(state='disabled')
        self.progress.start()
        
        # Run processing in a thread to keep UI responsive
        thread = threading.Thread(target=self._process_thread)
        thread.start()
    
    def _process_thread(self):
        """Processing logic running in background thread."""
        try:
            # Determine input mode based on which tab has data
            excel_path = self.excel_path.get()
            config_path = self.config_path.get()
            pfic_ticker = self.pfic_ticker.get().strip()
            ais_path = self.ais_path.get()
            
            if excel_path:
                self._process_excel(excel_path)
            elif config_path or (pfic_ticker and ais_path):
                self._process_files()
            else:
                self._log("ERROR: Please provide either:")
                self._log("  1. Excel workbook, OR")
                self._log("  2. PFIC info (ticker & name) + AIS file, OR")
                self._log("  3. Config file + AIS file")
                return
            
            self.root.after(0, lambda: self.open_folder_btn.config(state='normal'))
            
        except Exception as e:
            self._log(f"\nERROR: {str(e)}")
            self._log(traceback.format_exc())
        finally:
            self.root.after(0, lambda: self.progress.stop())
            self.root.after(0, lambda: self.process_btn.config(state='normal'))
    
    def _process_excel(self, excel_path: str):
        """Process using Excel workbook input."""
        try:
            from pfic_qef_tool.excel_io import load_from_excel, save_results_to_excel
        except ImportError:
            self._log("ERROR: openpyxl is required for Excel support.")
            self._log("Install it with: pip install openpyxl")
            return
        
        self._log(f"Loading data from Excel: {excel_path}")
        config, lots, transactions, ais_data = load_from_excel(excel_path)
        
        # Tax year comes from Excel Config sheet
        tax_year = config.tax_year
        if not tax_year:
            self._log("ERROR: Tax year not found in Excel Config sheet.")
            return
        
        self._do_processing(config, lots, transactions, ais_data, tax_year=tax_year)
    
    def _process_files(self):
        """Process using individual file inputs."""
        config_path = self.config_path.get().strip()
        lots_path = self.lots_path.get().strip() or None
        transactions_path = self.transactions_path.get().strip() or None
        ais_path = self.ais_path.get().strip()
        
        # Validate AIS file (always required)
        if not ais_path:
            self._log("ERROR: AIS data file is required.")
            return
        
        # Validate tax year
        try:
            tax_year = int(self.tax_year.get())
        except ValueError:
            self._log("ERROR: Invalid tax year. Enter a 4-digit year like 2024.")
            return
        
        # Load or create config
        if config_path:
            # Use config file
            self._log(f"Loading config from: {config_path}")
            config = load_config(config_path)
        else:
            # Use manual entries
            pfic_ticker = self.pfic_ticker.get().strip().upper()
            pfic_name = self.pfic_name.get().strip()
            default_currency = self.default_currency.get().strip()
            
            if not pfic_ticker:
                self._log("ERROR: PFIC ticker is required (or provide a config file).")
                return
            if not pfic_name:
                self._log("ERROR: PFIC name is required (or provide a config file).")
                return
            
            self._log(f"Using manual PFIC config: {pfic_ticker} - {pfic_name}")
            config = Config(
                pfic_ticker=pfic_ticker,
                pfic_name=pfic_name,
                default_currency=default_currency,
                tax_year=tax_year
            )
        
        self._log(f"Loading lots from: {lots_path or '(none)'}")
        lots = load_lots(lots_path, filter_ticker=config.pfic_ticker) if lots_path else []
        self._log(f"  Found {len(lots)} lots for {config.pfic_ticker}")
        
        self._log(f"Loading transactions from: {transactions_path or '(none)'}")
        transactions = load_transactions(
            transactions_path, 
            config.default_currency,
            filter_ticker=config.pfic_ticker
        ) if transactions_path else []
        self._log(f"  Found {len(transactions)} transactions for {config.pfic_ticker}")
        
        self._log(f"Loading AIS data from: {ais_path}")
        ais_data = load_ais_data(ais_path)
        
        self._do_processing(config, lots, transactions, ais_data, tax_year=tax_year)
    
    def _do_processing(self, config, lots, transactions, ais_data, tax_year=None):
        """Common processing logic."""
        # Use provided tax_year or fall back to config
        year = tax_year if tax_year else config.tax_year
        if not year:
            self._log("ERROR: No tax year specified.")
            return
        
        # Create output subdirectory
        ticker_lower = config.pfic_ticker.lower()
        output_subdir = Path(self.output_dir.get()) / f"{ticker_lower}_qef_{year}"
        output_subdir.mkdir(parents=True, exist_ok=True)
        
        use_boc = self.use_boc_rates.get()
        
        self._log(f"\nProcessing tax year {year} for {config.pfic_ticker}...")
        self._log(f"  Beginning lots: {len(lots)}")
        self._log(f"  Transactions: {len(transactions)}")
        self._log(f"  Underlying PFICs: {len(ais_data.underlying_pfics)}")
        self._log(f"  Use BoC rates: {'Yes' if use_boc else 'No'}")
        self._log(f"  Output: {output_subdir}")
        
        # Set up currency converter (only if using BoC rates)
        converter = None
        if use_boc:
            self._log("\nSetting up Bank of Canada currency converter...")
            converter = CurrencyConverter()
            try:
                converter.prefetch_year(year)
            except Exception as e:
                self._log(f"  Warning: Could not prefetch rates: {e}")
        
        # Convert transactions to USD
        if transactions:
            self._log("\nConverting transactions to USD...")
            missing_rates = []
            
            for txn in transactions:
                # If user provided an exchange rate, use it
                if txn.exchange_rate is not None:
                    rate = txn.exchange_rate
                    txn.amount_usd = round_money(txn.amount * rate)
                    txn.commission_usd = round_money(txn.commission * rate)
                    self._log(f"  {txn.date}: Using provided rate {rate:.4f}")
                    continue
                
                # USD transactions don't need conversion
                if txn.currency.upper() == "USD":
                    txn.amount_usd = txn.amount
                    txn.commission_usd = txn.commission
                    txn.exchange_rate = Decimal("1")
                    continue
                
                # Non-USD without user rate - need BoC or error
                if not use_boc:
                    missing_rates.append(f"  - {txn.date}: {txn.transaction_type.value} {txn.shares} shares ({txn.currency})")
                    continue
                
                # Fetch from BoC
                try:
                    amount_usd, rate = converter.to_usd(txn.amount, txn.currency, txn.date)
                    commission_usd, _ = converter.to_usd(txn.commission, txn.currency, txn.date)
                    txn.amount_usd = round_money(amount_usd)
                    txn.commission_usd = round_money(commission_usd)
                    txn.exchange_rate = rate
                    self._log(f"  {txn.date}: BoC rate {rate:.4f}")
                except Exception as e:
                    self._log(f"  Warning: Could not fetch BoC rate for {txn.date}: {e}")
                    txn.amount_usd = txn.amount
                    txn.commission_usd = txn.commission
                    txn.exchange_rate = Decimal("1")
            
            # If we have missing rates and BoC is disabled, show error
            if missing_rates:
                self._log("\n❌ ERROR: Missing exchange rates for transactions:")
                for m in missing_rates:
                    self._log(m)
                self._log("\nEither:")
                self._log("  1. Add exchange_rate column to your transactions file, or")
                self._log("  2. Check 'Use Bank of Canada exchange rates' option")
                return
        
        # Process transactions
        self._log("\nProcessing transactions (FIFO)...")
        tracker = LotTracker(lots if lots else None)
        
        for txn in sorted(transactions, key=lambda t: t.date):
            affected = tracker.process_transaction(txn)
            for lot in affected:
                status = "SOLD" if lot.status.value == "SOLD" else "CREATED"
                self._log(f"  {status} {lot.lot_id}: {lot.shares} shares")
        
        if tracker.warnings:
            for warning in tracker.warnings:
                self._log(f"  ⚠️ {warning}")
        
        # Calculate QEF adjustments
        self._log("\nCalculating QEF adjustments...")
        adjustments = apply_qef_adjustments(tracker, year, ais_data)
        
        for adj in adjustments:
            self._log(
                f"  {adj.lot_id}: +${adj.ordinary_earnings_usd:.2f} earnings, "
                f"+${adj.capital_gains_usd:.2f} gains, "
                f"-${adj.distributions_usd:.2f} dist"
            )
        
        # Generate Form 8621 data
        self._log("\nGenerating Form 8621 data...")
        form_8621_data = generate_form_8621_data(adjustments, ais_data)
        
        for f in form_8621_data:
            holding = "Direct" if f.is_direct_holding else "Indirect"
            self._log(
                f"  {f.fund_ticker} ({holding}): "
                f"6a=${f.line_6a_ordinary_earnings_usd:.2f}, "
                f"7a=${f.line_7a_net_capital_gains_usd:.2f}"
            )
        
        # Generate reports
        self._log("\nGenerating reports...")
        report = generate_lot_activity_report(
            config, lots, transactions, tracker, adjustments, form_8621_data, tax_year=year
        )
        
        sales = generate_sales_report(tracker)
        ending_lots = tracker.get_ending_lots()
        
        # Save outputs with ticker and year in filenames
        self._log(f"\nSaving outputs to: {output_subdir}")
        
        save_form_8621_data(form_8621_data, output_subdir / f"{ticker_lower}_form_8621_data_{year}.json")
        save_form_8621_csv(form_8621_data, output_subdir / f"{ticker_lower}_form_8621_data_{year}.csv")
        self._log(f"  ✓ {ticker_lower}_form_8621_data_{year}.json/csv")
        
        if sales:
            save_sales_report(sales, output_subdir / f"{ticker_lower}_sales_report_{year}.json")
            save_sales_csv(sales, output_subdir / f"{ticker_lower}_sales_report_{year}.csv")
            self._log(f"  ✓ {ticker_lower}_sales_report_{year}.json/csv")
        
        save_basis_adjustments(adjustments, output_subdir / f"{ticker_lower}_basis_adjustments_{year}.json")
        self._log(f"  ✓ {ticker_lower}_basis_adjustments_{year}.json")
        
        save_lots(ending_lots, output_subdir / f"{ticker_lower}_lots_held_end_of_{year}.json")
        self._log(f"  ✓ {ticker_lower}_lots_held_end_of_{year}.json")
        
        save_lot_activity_report(report, output_subdir / f"{ticker_lower}_lot_activity_report_{year}.json")
        self._log(f"  ✓ {ticker_lower}_lot_activity_report_{year}.json")
        
        summary = generate_text_summary(report)
        with open(output_subdir / f"{ticker_lower}_summary_{year}.txt", 'w') as f:
            f.write(summary)
        self._log(f"  ✓ {ticker_lower}_summary_{year}.txt")
        
        # Try PDF
        try:
            from pfic_qef_tool.formatters.pdf_report import create_pdf_report
            create_pdf_report(report, output_subdir / f"{ticker_lower}_qef_report_{year}.pdf")
            self._log(f"  ✓ {ticker_lower}_qef_report_{year}.pdf")
        except ImportError:
            self._log("  ⚠️ PDF (skipped - reportlab not installed)")
        except Exception as e:
            self._log(f"  ⚠️ PDF (error: {e})")
        
        # Try Excel output
        try:
            from pfic_qef_tool.excel_io import save_results_to_excel
            save_results_to_excel(
                output_subdir / f"{ticker_lower}_results_{year}.xlsx",
                form_8621_data, sales, adjustments, ending_lots, report
            )
            self._log(f"  ✓ {ticker_lower}_results_{year}.xlsx")
        except ImportError:
            self._log("  ⚠️ Excel (skipped - openpyxl not installed)")
        except Exception as e:
            self._log(f"  ⚠️ Excel (error: {e})")
        
        # Print summary
        total_qef = sum(
            f.line_6a_ordinary_earnings_usd + f.line_7a_net_capital_gains_usd
            for f in form_8621_data
        )
        
        self._log("\n" + "=" * 50)
        self._log("SUMMARY")
        self._log("=" * 50)
        self._log(f"Tax Year: {year}")
        self._log(f"PFIC: {config.pfic_name} ({config.pfic_ticker})")
        self._log(f"Total QEF Income: ${total_qef:.2f}")
        self._log(f"Form 8621 required: {len(form_8621_data)}")
        self._log(f"Lots sold: {len(sales)}")
        self._log(f"Lots at year end: {len(ending_lots)}")
        self._log("=" * 50)
        self._log("\n✅ Processing complete!")
    
    def _open_output_folder(self):
        """Open the output folder in file explorer."""
        output_dir = self.output_dir.get()
        if os.path.exists(output_dir):
            if sys.platform == 'win32':
                os.startfile(output_dir)
            elif sys.platform == 'darwin':
                os.system(f'open "{output_dir}"')
            else:
                os.system(f'xdg-open "{output_dir}"')


def main():
    """Launch the GUI application."""
    # Need to import simpledialog for template year input
    import tkinter.simpledialog
    tk.simpledialog = tkinter.simpledialog
    
    root = tk.Tk()
    
    # Try to set a nice theme
    try:
        style = ttk.Style()
        if 'clam' in style.theme_names():
            style.theme_use('clam')
    except:
        pass
    
    app = PFICToolGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()

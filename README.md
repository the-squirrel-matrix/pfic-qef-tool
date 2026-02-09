# PFIC QEF Tax Tool

**Version 1.0**

A Python tool to assist U.S. taxpayers in calculating QEF income, basis adjustments, and capital gains for PFIC holdings with QEF election.

**Author:** the_squirrel_matrix  

**DISCLAIMER**: This tool is for informational purposes only and does not constitute tax advice. Consult a qualified tax professional for your specific situation.

## Installation

### Required
- Python 3.9+

### Dependencies (Highly Recommended)

```bash
# Install both recommended dependencies:
pip install reportlab openpyxl
```

| Package | Purpose | Without It |
|---------|---------|------------|
| `reportlab` | PDF report generation | No PDF output |
| `openpyxl` | Excel workbook support | JSON/CSV only |

## Quick Start

### Option A: GUI (Recommended)

```bash
python -m pfic_qef_tool.gui
```

The GUI provides file browsers, progress tracking, and log output.

### Option B: Excel Workbook (Command Line)

```bash
# Create a template workbook
python -m pfic_qef_tool.main --create-template my_pfic_2024.xlsx

# Fill in the template (year is in the Config sheet), then run:
python -m pfic_qef_tool.main --excel my_pfic_2024.xlsx --output-dir ./output
```

### Option C: Separate JSON/CSV Files (Command Line)

```bash
python -m pfic_qef_tool.main \
    --config config.json \
    --ais ais_data.json \
    --transactions transactions.csv \
    --lots beginning_lots.csv \
    --year 2024 \
    --output-dir ./output
```

Note: `--year` is required for JSON/CSV mode (not needed for Excel mode).

### Review the Output

Results are saved to a subdirectory like `output/xeqt_qef_2024/` containing:
- `xeqt_qef_report_2024.pdf` - Comprehensive PDF report
- `xeqt_form_8621_data_2024.csv` - Data for Form 8621 filings
- `xeqt_lots_held_end_of_2024.json` - **Save this for next year!**
- `xeqt_results_2024.xlsx` - All results in Excel format

## Features

- **GUI**: Point-and-click graphical interface
- **Excel Workflow**: Single workbook for all inputs
- **Ticker Filtering**: Process one PFIC at a time from combined files
- **FIFO Lot Tracking**: Automatic lot management with splitting for partial sales
- **Flexible Exchange Rates**: Provide your own rates, or optionally fetch CAD/USD rates from Bank of Canada API
- **QEF Income Calculation**: Computes pro rata income for top-level and underlying PFICs
- **Basis Adjustments**: Tracks cost basis changes
- **Graceful Error Handling**: Creates synthetic lots when history is incomplete
- **Form 8621 Data**: Generates data for Part III of Form 8621
- **Multiple Output Formats**: JSON, CSV, Excel, PDF

## Important Limitations

### Handles QEF election only, and the fund must provide an Annual Information Statement
This tool is only meant to assist with PFIC reporting under the QEF rules. Other regimes (e.g., Mark-to-Market, 1291, Deemed Sale Election) are NOT supported. The PFIC must provide an Annual Information Statement (AIS). 

### Calendar Year Tax Years Only
This tool assumes your PFIC's tax year is a calendar year (January 1 - December 31). For example, all ETFs Blackrock (e.g., XEQT) and Vanguard (e.g., VEQT) provide AIS and have reporting year the same as the calendar (tax) year.

**NOTE: If your PFIC has a fiscal year that doesn't align with the calendar year** (e.g., ends June 30), this tool cannot be used as-is. The QEF calculations would need to be adjusted for the different year-end date.

### One PFIC at a Time
The tool processes one PFIC ticker at a time. If you hold multiple PFICs:
- Run the tool separately for each PFIC
- Use the ticker filter to process the correct transactions
- Provide the appropriate AIS data for each PFIC
- Transactions with different tickers will generate warnings but processing will continue

### Date Format
- **Preferred format**: YYYY-MM-DD (e.g., 2024-01-15)
- Other formats are accepted but may be ambiguous
- Consistent date formats across all input files are recommended

## Input Files

### config.json

```json
{
  "pfic_ticker": "XEQT",
  "pfic_name": "iShares Core Equity ETF Portfolio",
  "default_currency": "CAD"
}
```

Note: `tax_year` is now a command-line argument (`--year`), not in the config file.

### ais_data.json

Get these values from your fund's Annual Information Statement:

```json
{
  "tax_year": 2024,
  "fund_ticker": "XEQT",
  "fund_name": "iShares Core Equity ETF Portfolio",
  "ordinary_earnings_per_day_per_share_usd": "0.0003080775",
  "net_capital_gains_per_day_per_share_usd": "0.0004661617",
  "total_distributions_per_share_usd": "0.4498954722",
  "underlying_pfics": [...]
}
```

**Note**: The number of days in the tax year (365 or 366 for leap years) is automatically calculated from `tax_year`.

### transactions.csv

```csv
date,type,ticker,quantity,amount,fees,currency,exchange_rate
2024-02-15,Buy,XEQT,25.0000,650.00,9.99,CAD,0.7450
2024-08-20,Sell,XEQT,40.0000,1200.00,9.99,CAD,0.7320
```

- `exchange_rate`: CAD to USD conversion rate (e.g., 0.75 means 1 CAD = 0.75 USD)
- **Required** for CAD transactions unless using `--use-boc-rates` flag
- Leave blank for USD transactions

Only rows where `ticker` matches `pfic_ticker` in config are processed.

### beginning_lots.csv

CSV format:
```csv
lot_id,purchase_date,quantity,cost_basis_usd,ticker,original_lot_id
LOT-001,2023-03-15,100.0000,2350.00,XEQT,
```

For first year: use empty CSV with just headers, or omit the file.
For subsequent years: use the `*_lots_held_end_of_*.csv` from previous year.

## Exchange Rates

By default, you must provide exchange rates in the `exchange_rate` column of your transactions file for all non-USD transactions. This ensures the tool works offline and doesn't depend on external APIs.

**To use Bank of Canada rates instead:**

- CLI: Add `--use-boc-rates` flag
- GUI: Check "Use Bank of Canada exchange rates" checkbox

When enabled, the tool will fetch CAD/USD rates from the Bank of Canada API for any transactions missing an exchange rate. User-provided rates always take precedence.

**Note:** Only CAD to USD conversion is supported via the BoC API. For other currencies, you must provide the exchange rate manually.

## Common Scenarios

### First Year (No Prior Holdings)

```bash
python -m pfic_qef_tool.main \
    --config config.json \
    --ais ais_data.json \
    --transactions transactions.csv \
    --year 2024 \
    --output-dir ./output
```

### Year with No Transactions

```bash
python -m pfic_qef_tool.main \
    --config config.json \
    --ais ais_data.json \
    --lots xeqt_lots_held_end_of_2023.json \
    --year 2024 \
    --output-dir ./output
```

## Key Concepts

### QEF Basis Adjustments

Under QEF elections, cost basis adjusts annually:
```
Adjusted Basis = Original Basis
                 + Ordinary Earnings (phantom income)
                 + Net Capital Gains (phantom income)
                 - Distributions received
```

### Lot Splitting

When selling fewer shares than a lot contains:
- Sold portion keeps original lot ID (e.g., `LOT-001`)
- Remaining portion gets suffixed ID (e.g., `LOT-001.1`)

### Days Counting

- Lots held at year start: count from January 1
- Lots purchased during year: count from purchase date
- Lots sold during year: count through day before sale

## Running Tests

```bash
python -m unittest discover -s pfic_qef_tool/tests -v
```

## License

MIT License - See LICENSE file.

## Acknowledgments

This tool was developed through collaborative prompting with Claude (Anthropic's AI assistant). The code was entirely written by Claude Opus 4.5 based on requirements and guidance from the_squirrel_matrix.

## Contributing

Issues and pull requests welcome on GitHub.

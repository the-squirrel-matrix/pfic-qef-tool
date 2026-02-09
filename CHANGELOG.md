# Changelog

All notable changes to the PFIC QEF Tax Tool will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-02-09

### Added
- Initial release of PFIC QEF Tax Tool
- FIFO lot tracking with automatic lot splitting for partial sales
- QEF income calculation for top-level and underlying PFICs
- Basis adjustments (phantom income increases basis, distributions decrease it)
- Form 8621 data generation for Part III
- Multiple input modes: GUI, Excel workbook, or separate JSON/CSV files
- Multiple output formats: JSON, CSV, Excel, PDF reports
- Ticker filtering: Process one PFIC at a time from combined files
- Flexible exchange rates: User-provided rates or optional Bank of Canada API integration
- Comprehensive test suite with 13 unit tests
- Example data for XEQT 2024
- Excel template creation via GUI or CLI
- CSV format support for beginning/ending lots (in addition to JSON)

### Features
- **Automatic year_days calculation**: Tax year days (365/366) are automatically computed from the tax year - no manual input needed
- **Flexible CSV headers**: Accepts both "quantity" and "shares", "fees" and "commission" for backward compatibility
- **Case-insensitive transaction types**: "Buy"/"Sell" and "BUY"/"SELL" both work
- **Absolute value conversion**: Negative values in CSV trigger warnings and are automatically converted to positive
- **Ticker filtering with warnings**: Wrong ticker transactions generate warnings (not silent skips)
- **Date format flexibility**: YYYY-MM-DD preferred, but other formats accepted via dateutil parser
- **Transaction type filtering**: Non-BUY/SELL types (DIST, DIV, etc.) silently skipped during CSV import
- **Tax year filtering**: Transactions outside tax year flagged with warnings but don't stop processing
- **Currency support**: CAD/USD with extensible conversion framework

### PDF Report Improvements
- Column header renamed: "Shares" → "Quantity" throughout all tables
- Column header renamed: "Commission" → "Fees" throughout all tables  
- Adjusted column widths to prevent header text truncation (especially "Currency" column)
- Clear documentation that only BUY/SELL transactions from the tax year are included
- Automatic year_days value included in output (calculated, not user-provided)

### Important Limitations
- **Calendar year only**: Tool assumes PFIC tax year aligns with calendar year (January 1 - December 31). Does not support fiscal years ending on other dates.
- **One PFIC at a time**: Process each PFIC ticker separately with its own AIS data. Tool warns about mismatched tickers but continues processing.
- **Date format**: YYYY-MM-DD strongly recommended to avoid ambiguity (e.g., 01/02/2024 could be Jan 2 or Feb 1).

### File Format Updates
- **Lot files**: CSV format only (JSON no longer supported for beginning/ending lots)
- **Output lots**: Year-end lots saved as CSV for easier editing
- GUI supports manual PFIC entry (ticker, name, currency) without requiring a separate config file

# Repository Structure

```
pfic_qef_tool/                    # Repository root
├── .gitignore                    # Git ignore patterns
├── CHANGELOG.md                  # Version history
├── LICENSE                       # MIT License
├── README.md                     # Main documentation
├── requirements.txt              # Optional dependencies
├── setup.py                      # Package installation script
│
├── pfic_qef_tool/               # Source code package
│   ├── __init__.py              # Package initialization
│   ├── main.py                  # CLI entry point
│   ├── gui.py                   # GUI entry point
│   ├── models.py                # Data models
│   ├── lot_tracker.py           # FIFO lot tracking
│   ├── qef_calculator.py        # QEF income calculations
│   ├── currency.py              # Bank of Canada exchange rates
│   ├── excel_io.py              # Excel workbook I/O
│   ├── serialization.py         # JSON/CSV I/O
│   ├── reports.py               # Report generation
│   └── formatters/
│       ├── __init__.py
│       └── pdf_report.py        # PDF generation (reportlab)
│
├── examples/                    # Sample data for XEQT 2024
│   ├── config.json
│   ├── beginning_lots.json
│   ├── transactions.csv
│   ├── ais_xeqt_2024.json
│   └── ais_veqt_2024.json
│
├── templates/                   # Input file templates
│   ├── config_template.json
│   ├── beginning_lots_template.json
│   ├── transactions_template.csv
│   └── ais_template.json
│
└── tests/                       # Unit and integration tests
    ├── __init__.py
    ├── test_lot_tracker.py
    ├── test_qef_calculator.py
    └── test_integration.py
```

## Installation Options

### Option 1: Direct Use (No Installation)
```bash
# Download and extract the repository
cd pfic_qef_tool
python pfic_qef_tool/gui.py        # GUI mode
python pfic_qef_tool/main.py --help # CLI mode
```

### Option 2: Install as Package
```bash
# Install with pip (from repo directory)
pip install .                      # Basic installation
pip install ".[full]"              # With Excel and PDF support

# Then run from anywhere
pfic-qef-gui                       # GUI mode
pfic-qef-tool --help              # CLI mode
```

### Option 3: Development Installation
```bash
# Install in editable mode for development
pip install -e ".[full]"
```

## Running Tests

```bash
# From repository root
python -m unittest discover tests/ -v
```

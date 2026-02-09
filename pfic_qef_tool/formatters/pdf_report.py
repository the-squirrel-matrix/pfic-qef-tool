"""
PDF report generation for PFIC QEF tax reports.

Uses reportlab to create professional-looking PDF reports.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Union

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, portrait
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    NextPageTemplate, PageTemplate, Frame, BaseDocTemplate
)

from ..models import (
    LotActivityReport, Form8621Data, SaleRecord, BasisAdjustmentRecord,
    Lot, GainType
)


def _format_money(value: Decimal) -> str:
    """Format a decimal as currency."""
    if value >= 0:
        return f"${value:,.2f}"
    else:
        return f"(${abs(value):,.2f})"


def _format_shares(value: Decimal) -> str:
    """Format shares with proper precision."""
    return f"{value:,.4f}"


def create_pdf_report(
    report: LotActivityReport,
    output_path: Union[str, Path],
):
    """
    Generate a comprehensive PDF report.
    
    Args:
        report: The LotActivityReport data
        output_path: Where to save the PDF
    """
    # Create document
    doc = BaseDocTemplate(
        str(output_path),
        pagesize=portrait(letter),
        rightMargin=0.5*inch,
        leftMargin=0.5*inch,
        topMargin=0.5*inch,
        bottomMargin=0.5*inch,
    )
    
    # Define frame for portrait
    portrait_frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        portrait(letter)[0] - 2*doc.leftMargin,
        portrait(letter)[1] - 2*doc.bottomMargin,
        id='portrait'
    )
    
    # Create page template
    portrait_template = PageTemplate(id='Portrait', frames=[portrait_frame], pagesize=portrait(letter))
    
    doc.addPageTemplates([portrait_template])
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=20,
        alignment=1,  # Center
    )
    
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=12,
        spaceAfter=20,
        alignment=1,
        textColor=colors.grey,
    )
    
    section_style = ParagraphStyle(
        'Section',
        parent=styles['Heading2'],
        fontSize=14,
        spaceBefore=15,
        spaceAfter=10,
        textColor=colors.darkblue,
    )
    
    disclaimer_style = ParagraphStyle(
        'Disclaimer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        alignment=1,
    )
    
    story = []
    
    # Title page
    story.append(Paragraph(
        f"PFIC QEF Tax Report",
        title_style
    ))
    story.append(Paragraph(
        f"Tax Year {report.tax_year}",
        subtitle_style
    ))
    story.append(Paragraph(
        f"{report.pfic_name} ({report.pfic_ticker})",
        subtitle_style
    ))
    story.append(Spacer(1, 30))
    
    # Disclaimer
    story.append(Paragraph(
        "DISCLAIMER: This report is for informational purposes only and does not "
        "constitute tax advice. Consult a qualified tax professional for your "
        "specific situation.",
        disclaimer_style
    ))
    story.append(Spacer(1, 30))
    
    # Summary section
    story.append(Paragraph("Executive Summary", section_style))
    
    # Calculate summary stats
    total_beginning_shares = sum(lot.shares for lot in report.beginning_lots)
    total_ending_shares = sum(lot.shares for lot in report.ending_lots)
    total_bought = sum(
        lot.shares for lot in report.lots_created 
        if not lot.original_lot_id  # Exclude split lots
    )
    total_sold = sum(sale.shares_sold for sale in report.lots_sold)
    
    total_ord_earnings = sum(f.line_6a_ordinary_earnings_usd for f in report.form_8621_data)
    total_cap_gains = sum(f.line_7a_net_capital_gains_usd for f in report.form_8621_data)
    
    summary_data = [
        ["Beginning of Year Quantity", _format_shares(total_beginning_shares)],
        ["Quantity Purchased", _format_shares(total_bought)],
        ["Quantity Sold", _format_shares(total_sold)],
        ["End of Year Quantity", _format_shares(total_ending_shares)],
        ["", ""],
        ["Total QEF Ordinary Earnings", _format_money(total_ord_earnings)],
        ["Total QEF Capital Gains", _format_money(total_cap_gains)],
        ["Total QEF Income", _format_money(total_ord_earnings + total_cap_gains)],
        ["", ""],
        ["Form 8621 Required", str(len(report.form_8621_data))],
    ]
    
    summary_table = Table(summary_data, colWidths=[3*inch, 2*inch])
    summary_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 20))
    
    # Transactions Summary section 
    if report.transactions_processed:
        story.append(PageBreak())
        
        story.append(Paragraph("Transactions Summary", section_style))
        story.append(Paragraph(
            f"Buy and sell transactions for {report.pfic_ticker} processed during tax year {report.tax_year}. "
            f"Only BUY and SELL transactions from this tax year are included; "
            f"distributions and transactions outside this year are excluded. "
            f"<b>Total</b> = Amount + Fees (BUY) or Amount − Fees (SELL).",
            styles['Normal']
        ))
        story.append(Spacer(1, 10))
        
        # Combined wide table with original currency and USD
        txn_headers = ["Date", "Type", "Ticker", "Quantity", "Amount", "Fees", "Total", "Currency", "FX Rate", "Amount\n(USD)", "Fees\n(USD)", "Net Amount\n(USD)"]
        txn_data = [txn_headers]
        
        for txn in sorted(report.transactions_processed, key=lambda t: t.date):
            # Calculate totals
            if txn.transaction_type.value == "BUY":
                total_orig = txn.amount + txn.commission
            else:
                total_orig = txn.amount - txn.commission
            
            rate = txn.exchange_rate if txn.exchange_rate else Decimal("1")
            amount_usd = txn.amount_usd if txn.amount_usd else Decimal("0")
            commission_usd = txn.commission_usd if txn.commission_usd else Decimal("0")
            
            if txn.transaction_type.value == "BUY":
                total_usd = amount_usd + commission_usd
            else:
                total_usd = amount_usd - commission_usd
            
            txn_data.append([
                txn.date.strftime("%Y-%m-%d"),
                txn.transaction_type.value,
                txn.ticker or report.pfic_ticker,
                _format_shares(txn.shares),
                f"{txn.amount:,.2f}",
                f"{txn.commission:,.2f}",
                f"{total_orig:,.2f}",
                txn.currency,
                f"{rate:.4f}",
                _format_money(amount_usd),
                _format_money(commission_usd),
                _format_money(total_usd),
            ])
        
        # Totals
        total_buy_cost = Decimal("0")
        total_sell_proceeds = Decimal("0")
        for txn in report.transactions_processed:
            if txn.amount_usd and txn.commission_usd:
                if txn.transaction_type.value == "BUY":
                    total_buy_cost += txn.amount_usd + txn.commission_usd
                else:
                    total_sell_proceeds += txn.amount_usd - txn.commission_usd
        
        txn_data.append(["", "", "", "", "", "", "", "", "", "Total Buys:", "", _format_money(total_buy_cost)])
        txn_data.append(["", "", "", "", "", "", "", "", "", "Total Sells:", "", _format_money(total_sell_proceeds)])
        
        # Adjusted column widths: Date, Type, Ticker, Quantity, Amount, Fees, Total, Currency, FX Rate, Amount USD, Fees USD, Total USD
        txn_table = Table(txn_data, colWidths=[0.7*inch, 0.4*inch, 0.5*inch, 0.65*inch, 0.7*inch, 0.5*inch, 0.7*inch, 0.7*inch, 0.6*inch, 0.7*inch, 0.5*inch, 0.7*inch])
        txn_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, -2), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('ALIGN', (3, 0), (-1, -1), 'RIGHT'),
            ('ALIGN', (0, 0), (2, -1), 'LEFT'),
            ('GRID', (0, 0), (-1, -3), 0.5, colors.grey),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(txn_table)
        story.append(Spacer(1, 20))
        
    
    # Form 8621 Section
    story.append(Paragraph("Form 8621 Data (Part III - QEF Election)", section_style))
    story.append(Paragraph(
        "The following data is needed to complete Part III of Form 8621 for each PFIC. "
        "One form is required for the directly-held fund and each underlying fund.",
        styles['Normal']
    ))
    story.append(Spacer(1, 10))
    
    form_headers = ["Fund", "Type", "Line 6a\nOrdinary", "Line 7a\nCap Gains", "Total"]
    form_data = [form_headers]
    
    for f in report.form_8621_data:
        holding_type = "Direct" if f.is_direct_holding else "Indirect"
        total = f.line_6a_ordinary_earnings_usd + f.line_7a_net_capital_gains_usd
        form_data.append([
            f.fund_ticker,
            holding_type,
            _format_money(f.line_6a_ordinary_earnings_usd),
            _format_money(f.line_7a_net_capital_gains_usd),
            _format_money(total),
        ])
    
    # Totals row
    form_data.append([
        "TOTAL", "",
        _format_money(total_ord_earnings),
        _format_money(total_cap_gains),
        _format_money(total_ord_earnings + total_cap_gains),
    ])
    
    form_table = Table(form_data, colWidths=[1.2*inch, 0.8*inch, 1.2*inch, 1.2*inch, 1.2*inch])
    form_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(form_table)
    story.append(Spacer(1, 20))
    
    # Sales section
    if report.lots_sold:
        story.append(Paragraph("Sales Report", section_style))
        story.append(Paragraph(
            "Capital gains and losses from PFIC sales during the tax year. "
            "The adjusted cost basis includes QEF income adjustments.",
            styles['Normal']
        ))
        story.append(Spacer(1, 10))
        
        sales_headers = ["Lot", "Purchase", "Sale", "Quantity", "Adj. Basis", "Proceeds", "Gain/Loss", "Type"]
        sales_data = [sales_headers]
        
        total_gain = Decimal("0")
        for sale in report.lots_sold:
            gain_type = "Short term" if sale.gain_type == GainType.SHORT_TERM else "Long term"
            sales_data.append([
                sale.lot_id,
                sale.purchase_date.strftime("%Y-%m-%d"),
                sale.sale_date.strftime("%Y-%m-%d"),
                _format_shares(sale.shares_sold),
                _format_money(sale.cost_basis_adjusted_usd),
                _format_money(sale.proceeds_usd),
                _format_money(sale.gain_loss_usd),
                gain_type,
            ])
            total_gain += sale.gain_loss_usd
        
        # Totals row
        sales_data.append([
            "TOTAL", "", "", "", "", "",
            _format_money(total_gain), ""
        ])
        
        sales_table = Table(sales_data, colWidths=[0.7*inch, 0.7*inch, 0.7*inch, 0.7*inch, 0.9*inch, 0.9*inch, 0.9*inch, 0.8*inch])
        sales_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
            ('ALIGN', (3, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(sales_table)
        story.append(Spacer(1, 20))
    
    # Basis adjustments section 
    story.append(PageBreak())
    story.append(Paragraph("Basis Adjustments Detail", section_style))
    story.append(Paragraph(
        f"QEF elections require annual basis adjustments. Pro rata ordinary earnings and capital gains increase basis; distributions decrease it. "
        f"<b>Days Held</b> = days during tax year {report.tax_year} the lot was owned.",
        styles['Normal']
    ))
    story.append(Spacer(1, 10))
    
    # Build lot info lookup
    lot_info = {}
    for lot in report.beginning_lots:
        lot_info[lot.lot_id] = {"purchase": lot.purchase_date, "sale": None, "init_basis": lot.cost_basis_usd}
    for lot in report.lots_created:
        if lot.lot_id not in lot_info:
            lot_info[lot.lot_id] = {"purchase": lot.purchase_date, "sale": None, "init_basis": lot.cost_basis_usd}
    for sale in report.lots_sold:
        if sale.lot_id in lot_info:
            lot_info[sale.lot_id]["sale"] = sale.sale_date
        else:
            lot_info[sale.lot_id] = {"purchase": sale.purchase_date, "sale": sale.sale_date, "init_basis": sale.cost_basis_usd}
    
    # Combined wide table
    adj_headers = ["Lot ID", "Quantity", "Purchase", "Sale", "Days\nHeld", "Initial Basis", f"Ordinary\nEarnings", "Capital\nGains", "Distributions", "Net Adj.", "Final Basis"]
    adj_data = [adj_headers]
    
    for adj in report.basis_adjustments:
        info = lot_info.get(adj.lot_id, {})
        purchase_date = info.get("purchase")
        sale_date = info.get("sale")
        
        if purchase_date:
            purchase_str = "UNKNOWN" if purchase_date.year == 1900 else purchase_date.strftime("%Y-%m-%d")
        else:
            purchase_str = "-"
        
        sale_str = sale_date.strftime("%Y-%m-%d") if sale_date else "-"
        
        adj_data.append([
            adj.lot_id,
            _format_shares(adj.shares),
            purchase_str,
            sale_str,
            str(adj.days_held_in_year),
            _format_money(adj.basis_before_usd),
            _format_money(adj.ordinary_earnings_usd),
            _format_money(adj.capital_gains_usd),
            _format_money(adj.distributions_usd),
            _format_money(adj.net_adjustment_usd),
            _format_money(adj.basis_after_usd),
        ])
    
    # Totals
    total_earnings = sum(a.ordinary_earnings_usd for a in report.basis_adjustments)
    total_gains = sum(a.capital_gains_usd for a in report.basis_adjustments)
    total_dist = sum(a.distributions_usd for a in report.basis_adjustments)
    total_net = sum(a.net_adjustment_usd for a in report.basis_adjustments)
    total_basis = sum(a.basis_after_usd for a in report.basis_adjustments)
    
    adj_data.append([
        "TOTAL", "", "", "", "", "",
        _format_money(total_earnings),
        _format_money(total_gains),
        _format_money(total_dist),
        _format_money(total_net),
        _format_money(total_basis),
    ])
    
    adj_table = Table(adj_data, colWidths=[0.6*inch, 0.6*inch, 0.6*inch, 0.6*inch, 0.4*inch, 0.8*inch, 0.7*inch, 0.7*inch, 0.7*inch, 0.7*inch, 0.8*inch])
    adj_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(adj_table)
    story.append(Spacer(1, 20))
    
    # Year-end lots
    story.append(Paragraph("Year-End Position", section_style))
    story.append(Paragraph(
        "Lots held at the end of the tax year with adjusted cost basis. "
        "This data can be used as beginning lots for next year.",
        styles['Normal']
    ))
    story.append(Spacer(1, 10))
    
    if report.ending_lots:
        end_headers = ["Lot ID", "Purchase Date", "Quantity", "Adjusted Basis"]
        end_data = [end_headers]
        
        total_shares = Decimal("0")
        total_basis = Decimal("0")
        
        for lot in report.ending_lots:
            end_data.append([
                lot.lot_id,
                lot.purchase_date.strftime("%Y-%m-%d"),
                _format_shares(lot.shares),
                _format_money(lot.cost_basis_usd),
            ])
            total_shares += lot.shares
            total_basis += lot.cost_basis_usd
        
        end_data.append([
            "TOTAL", "",
            _format_shares(total_shares),
            _format_money(total_basis),
        ])
        
        end_table = Table(end_data, colWidths=[1.2*inch, 1.5*inch, 1.2*inch, 1.5*inch])
        end_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
            ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(end_table)
    else:
        story.append(Paragraph("No lots held at end of year.", styles['Normal']))
    
    # Final disclaimer
    story.append(Spacer(1, 30))
    story.append(Paragraph(
        "Generated by PFIC QEF Tax Tool. "
        "This report is for informational purposes only. "
        "Consult a qualified tax professional.",
        disclaimer_style
    ))
    
    # Build PDF
    doc.build(story)

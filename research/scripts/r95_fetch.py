"""Runde 95: fehlende SEC-XBRL-Frames laden (Cache data_cache/edgar/frames)."""
import time

from tradingbot.research import edgar

INSTANT = [("Assets", "us-gaap", "USD"), ("Liabilities", "us-gaap", "USD"),
           ("StockholdersEquity", "us-gaap", "USD"), ("EntityCommonStockSharesOutstanding", "dei", "shares")]
ANNUAL = ["NetIncomeLoss", "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "GrossProfit",
          "OperatingIncomeLoss", "NetCashProvidedByUsedInOperatingActivities"]
n = 0
for y in range(2015, 2027):
    for q in range(1, 5):
        if (y, q) > (2026, 1):
            continue
        for concept, tax, unit in INSTANT:
            df = edgar.xbrl_frame(concept, y, q, True, taxonomy=tax, unit=unit)
            n += 1
    if y <= 2025:
        for concept in ANNUAL:
            df = edgar.xbrl_frame(concept, y, None, False)
            print(concept, y, len(df), flush=True)
            n += 1
    time.sleep(0.2)
print("fertig", n)

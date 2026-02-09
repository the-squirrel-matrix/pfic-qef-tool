"""
Currency conversion using Bank of Canada exchange rates.

Fetches CAD/USD rates from the Bank of Canada Valet API.
"""

import json
import urllib.request
import urllib.error
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional
import os


class ExchangeRateCache:
    """Cache for exchange rates with file persistence."""
    
    def __init__(self, cache_file: Optional[str] = None):
        self.cache_file = cache_file
        self._rates: dict[str, dict[date, Decimal]] = {}
        if cache_file and os.path.exists(cache_file):
            self._load_cache()
    
    def _load_cache(self):
        """Load cached rates from file."""
        try:
            with open(self.cache_file, 'r') as f:
                data = json.load(f)
                for pair, rates in data.items():
                    self._rates[pair] = {
                        date.fromisoformat(d): Decimal(str(r))
                        for d, r in rates.items()
                    }
        except (json.JSONDecodeError, KeyError, ValueError):
            self._rates = {}
    
    def _save_cache(self):
        """Save cached rates to file."""
        if not self.cache_file:
            return
        data = {
            pair: {d.isoformat(): str(r) for d, r in rates.items()}
            for pair, rates in self._rates.items()
        }
        with open(self.cache_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def get(self, currency_pair: str, rate_date: date) -> Optional[Decimal]:
        """Get cached rate if available."""
        if currency_pair in self._rates:
            return self._rates[currency_pair].get(rate_date)
        return None
    
    def set(self, currency_pair: str, rate_date: date, rate: Decimal):
        """Cache a rate."""
        if currency_pair not in self._rates:
            self._rates[currency_pair] = {}
        self._rates[currency_pair][rate_date] = rate
        self._save_cache()
    
    def set_bulk(self, currency_pair: str, rates: dict[date, Decimal]):
        """Cache multiple rates at once."""
        if currency_pair not in self._rates:
            self._rates[currency_pair] = {}
        self._rates[currency_pair].update(rates)
        self._save_cache()


class BankOfCanadaRates:
    """
    Fetch exchange rates from Bank of Canada Valet API.
    
    API documentation: https://www.bankofcanada.ca/valet/docs
    
    Note: The API returns CAD per 1 unit of foreign currency.
    For USD/CAD, the rate is how many CAD you get for 1 USD.
    To convert CAD to USD, divide by this rate.
    """
    
    # Bank of Canada series codes
    # FXUSDCAD = USD/CAD (CAD per 1 USD)
    SERIES_USD_CAD = "FXUSDCAD"
    
    BASE_URL = "https://www.bankofcanada.ca/valet/observations"
    
    def __init__(self, cache: Optional[ExchangeRateCache] = None):
        self.cache = cache or ExchangeRateCache()
    
    def _fetch_rates(self, series: str, start_date: date, 
                     end_date: date) -> dict[date, Decimal]:
        """
        Fetch rates from Bank of Canada API.
        
        Returns dict mapping date to rate.
        """
        url = (
            f"{self.BASE_URL}/{series}/json"
            f"?start_date={start_date.isoformat()}"
            f"&end_date={end_date.isoformat()}"
        )
        
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
        except urllib.error.URLError as e:
            raise RuntimeError(f"Failed to fetch exchange rates: {e}")
        
        rates = {}
        for obs in data.get("observations", []):
            obs_date = date.fromisoformat(obs["d"])
            # The rate value is nested under the series name
            rate_data = obs.get(series)
            if rate_data and "v" in rate_data:
                rates[obs_date] = Decimal(str(rate_data["v"]))
        
        return rates
    
    def get_usd_cad_rate(self, rate_date: date) -> Decimal:
        """
        Get USD/CAD rate for a specific date.
        
        Returns how many CAD you get for 1 USD.
        If the date is a weekend/holiday, uses the most recent available rate.
        """
        cache_key = "USD/CAD"
        
        # Check cache first
        cached = self.cache.get(cache_key, rate_date)
        if cached is not None:
            return cached
        
        # Fetch a range to handle weekends/holidays
        # Go back up to 7 days to find a rate
        start = rate_date - timedelta(days=7)
        rates = self._fetch_rates(self.SERIES_USD_CAD, start, rate_date)
        
        # Cache all fetched rates
        self.cache.set_bulk(cache_key, rates)
        
        # Find the rate for the requested date or most recent prior
        for days_back in range(8):
            check_date = rate_date - timedelta(days=days_back)
            if check_date in rates:
                return rates[check_date]
        
        raise ValueError(f"No exchange rate available for {rate_date}")
    
    def prefetch_rates_for_year(self, year: int):
        """
        Prefetch all rates for a given year.
        
        Useful for batch processing to avoid multiple API calls.
        """
        cache_key = "USD/CAD"
        start = date(year, 1, 1)
        end = date(year, 12, 31)
        
        rates = self._fetch_rates(self.SERIES_USD_CAD, start, end)
        self.cache.set_bulk(cache_key, rates)
        
        return len(rates)


class CurrencyConverter:
    """
    Convert amounts between currencies using Bank of Canada rates.
    """
    
    def __init__(self, rate_provider: Optional[BankOfCanadaRates] = None,
                 cache_file: Optional[str] = None):
        if rate_provider:
            self.rates = rate_provider
        else:
            cache = ExchangeRateCache(cache_file) if cache_file else None
            self.rates = BankOfCanadaRates(cache)
    
    def to_usd(self, amount: Decimal, from_currency: str, 
               rate_date: date) -> tuple[Decimal, Decimal]:
        """
        Convert an amount to USD.
        
        Returns (amount_usd, exchange_rate_used).
        
        The exchange rate returned is the rate to multiply the original
        currency by to get USD.
        """
        from_currency = from_currency.upper()
        
        if from_currency == "USD":
            return amount, Decimal("1")
        
        if from_currency == "CAD":
            # USD/CAD rate is CAD per 1 USD
            # To convert CAD to USD, divide by this rate
            usd_cad_rate = self.rates.get_usd_cad_rate(rate_date)
            conversion_rate = Decimal("1") / usd_cad_rate
            amount_usd = amount * conversion_rate
            return amount_usd, conversion_rate
        
        raise ValueError(f"Unsupported currency: {from_currency}")
    
    def prefetch_year(self, year: int) -> int:
        """Prefetch rates for a year. Returns count of rates fetched."""
        return self.rates.prefetch_rates_for_year(year)


def load_rates_from_csv(csv_path: str) -> dict[date, Decimal]:
    """
    Load exchange rates from a CSV file.
    
    Expected format:
    date,rate
    2024-01-01,0.7562
    
    The rate should be the CAD to USD conversion rate
    (i.e., multiply CAD by this to get USD).
    """
    rates = {}
    with open(csv_path, 'r') as f:
        header = f.readline()  # Skip header
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(',')
            if len(parts) >= 2:
                rate_date = date.fromisoformat(parts[0].strip())
                rate = Decimal(parts[1].strip())
                rates[rate_date] = rate
    return rates


class OfflineCurrencyConverter:
    """
    Currency converter using pre-loaded rates (no API calls).
    
    Useful for testing or when rates are provided via CSV.
    """
    
    def __init__(self, cad_to_usd_rates: dict[date, Decimal]):
        """
        Initialize with a dict of date -> CAD to USD rate.
        
        The rate is what you multiply CAD by to get USD.
        """
        self._rates = cad_to_usd_rates
    
    @classmethod
    def from_csv(cls, csv_path: str) -> "OfflineCurrencyConverter":
        """Create converter from a CSV file."""
        rates = load_rates_from_csv(csv_path)
        return cls(rates)
    
    def to_usd(self, amount: Decimal, from_currency: str,
               rate_date: date) -> tuple[Decimal, Decimal]:
        """Convert to USD using pre-loaded rates."""
        from_currency = from_currency.upper()
        
        if from_currency == "USD":
            return amount, Decimal("1")
        
        if from_currency == "CAD":
            # Find rate for date or most recent prior
            for days_back in range(8):
                check_date = rate_date - timedelta(days=days_back)
                if check_date in self._rates:
                    rate = self._rates[check_date]
                    return amount * rate, rate
            
            raise ValueError(f"No exchange rate available for {rate_date}")
        
        raise ValueError(f"Unsupported currency: {from_currency}")

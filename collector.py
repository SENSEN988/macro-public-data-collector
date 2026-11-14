"""Fetch and verify public Daily Treasury Statement TGA balances without credentials."""
import calendar
import datetime as dt
import decimal
import gzip
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

BASE = 'https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance'
MODERN = 'Treasury General Account (TGA) Closing Balance'
LEGACY = 'Treasury General Account (TGA)'
PAGE_SIZE = 2500

class TransportError(Exception):
    pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Treasury endpoint redirected; refusing unverified destination')

def fetch(url):
    request = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'TreasuryPublicDataCollector/1.0'})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError('Treasury response exceeds size limit')
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        if exc.code >= 500:
            raise TransportError(f'HTTP {exc.code}') from exc
        raise ValueError(f'Unexpected Treasury HTTP {exc.code}') from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise TransportError(str(exc)) from exc

def observed(day):
    return day + dt.timedelta(days=(-1 if day.weekday() == 5 else 1 if day.weekday() == 6 else 0))

def nth_weekday(year, month, weekday, n):
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(weekday - first.weekday()) % 7 + (n - 1) * 7)

def holidays(year):
    last_may = dt.date(year, 5, 31)
    return {observed(dt.date(year, 1, 1)), observed(dt.date(year + 1, 1, 1)),
            nth_weekday(year, 1, 0, 3), nth_weekday(year, 2, 0, 3),
            last_may - dt.timedelta(days=last_may.weekday()), observed(dt.date(year, 6, 19)),
            observed(dt.date(year, 7, 4)), nth_weekday(year, 9, 0, 1),
            nth_weekday(year, 10, 0, 2), observed(dt.date(year, 11, 11)),
            nth_weekday(year, 11, 3, 4), observed(dt.date(year, 12, 25))}

def business(day):
    return day.weekday() < 5 and day not in holidays(day.year)

def previous_business(day):
    day -= dt.timedelta(days=1)
    while not business(day):
        day -= dt.timedelta(days=1)
    return day

def expected_date(now):
    local = now.astimezone(ZoneInfo('America/New_York'))
    published = local.date() if business(local.date()) and local.hour >= 16 else previous_business(local.date())
    return previous_business(published)

def parse_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Invalid Treasury observation date')
    return dt.date.fromisoformat(value)

def load(start, end, requester=fetch):
    pages = []
    normalized = {}
    total_pages = None
    total_count = None
    page = 1
    while total_pages is None or page <= total_pages:
        params = {'fields': 'record_date,account_type,open_today_bal,close_today_bal',
                  'filter': f'record_date:gte:{start},record_date:lte:{end},account_type:in:({MODERN},{LEGACY})',
                  'sort': 'record_date', 'page[size]': PAGE_SIZE, 'page[number]': page}
        url = BASE + '?' + urllib.parse.urlencode(params)
        body = requester(url)
        if not isinstance(body, dict) or not isinstance(body.get('data'), list) or not isinstance(body.get('meta'), dict):
            raise ValueError('Treasury response schema changed')
        meta = body['meta']
        count, all_pages, all_count = meta.get('count'), meta.get('total-pages'), meta.get('total-count')
        if type(count) is not int or count != len(body['data']) or type(all_pages) is not int or not 1 <= all_pages <= 10 or type(all_count) is not int or all_count < 1:
            raise ValueError('Invalid Treasury pagination')
        if all_pages != (all_count + PAGE_SIZE - 1) // PAGE_SIZE or count != min(PAGE_SIZE, all_count - (page-1)*PAGE_SIZE):
            raise ValueError('Treasury response incomplete')
        if total_pages is not None and (all_pages != total_pages or all_count != total_count):
            raise ValueError('Treasury pagination changed during fetch')
        total_pages, total_count = all_pages, all_count
        formats = meta.get('dataFormats', {})
        if formats.get('open_today_bal') != '$1,000,000' or formats.get('close_today_bal') != '$1,000,000':
            raise ValueError('Treasury units changed')
        for row in body['data']:
            if not isinstance(row, dict) or row.get('account_type') not in (MODERN, LEGACY):
                raise ValueError('Treasury account filter mismatch')
            day = parse_date(row.get('record_date'))
            if not start <= day <= end:
                raise ValueError('Treasury observation outside requested window')
            raw = row.get('open_today_bal' if row['account_type'] == MODERN else 'close_today_bal')
            if not isinstance(raw, str) or not re.fullmatch(r'\d+', raw):
                raise ValueError('Missing or invalid Treasury closing balance')
            amount = int(raw)
            if amount <= 0 or day in normalized:
                raise ValueError('Invalid or duplicate Treasury balance date')
            normalized[day] = amount
        pages.append({'url': url, 'response': body})
        page += 1
    if len(normalized) != total_count:
        raise ValueError('Treasury observations incomplete')
    cursor = start
    while cursor <= end:
        if business(cursor) and cursor not in normalized:
            raise ValueError(f'Missing Treasury business day {cursor}')
        cursor += dt.timedelta(days=1)
    return pages, [{'date': day.isoformat(), 'value': float(decimal.Decimal(amount) / 1000)} for day, amount in sorted(normalized.items())]

def collect(now=None, requester=fetch):
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Collection time must be timezone aware')
    end = expected_date(now)
    try:
        pages, records = load(dt.date(2023, 1, 1), end, requester)
        coverage = 'full_since_2023'
        history_failure = None
    except TransportError as exc:
        history_failure = str(exc)
        pages, records = load(end - dt.timedelta(days=90), end, requester)
        coverage = 'last_90_days'
    return {'source': BASE, 'collected_at': now.astimezone(dt.timezone.utc).isoformat(),
            'expected_latest_date': end.isoformat(), 'unit': 'billions_USD', 'raw_unit': 'millions_USD',
            'coverage': coverage, 'history_transport_failure': history_failure, 'records': records, 'raw_pages': pages}

def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python collector.py OUTPUT.json.gz')
    result = collect()
    with gzip.open(sys.argv[1], 'wt', encoding='utf-8') as output:
        json.dump(result, output, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    print(f"Verified {len(result['records'])} observations through {result['expected_latest_date']} ({result['coverage']})")

if __name__ == '__main__':
    main()

import datetime as dt
import unittest
from urllib.parse import parse_qs, urlparse
import collector as c
F = {'open_today_bal': '$1,000,000', 'close_today_bal': '$1,000,000'}
def response(rows):
    return {'data': rows, 'meta': {'count': len(rows), 'total-count': len(rows), 'total-pages': 1, 'dataFormats': F}}
def row(day, value='922633', account=c.MODERN):
    return {'record_date': day, 'account_type': account, 'open_today_bal': value if account == c.MODERN else 'null', 'close_today_bal': value if account == c.LEGACY else 'null'}
class CollectorTests(unittest.TestCase):
    def test_expected_dst_weekend_holiday(self):
        cases = [('2026-11-13T20:59:00+00:00','2026-11-10'),('2026-11-13T21:00:00+00:00','2026-11-12'),('2026-11-14T12:00:00+00:00','2026-11-12'),('2026-07-06T19:59:00+00:00','2026-07-01'),('2026-07-06T20:00:00+00:00','2026-07-02')]
        for time, expected in cases: self.assertEqual(c.expected_date(dt.datetime.fromisoformat(time)).isoformat(), expected)
    def test_normalization(self):
        rows=[row('2026-11-06','100000',c.LEGACY),row('2026-11-09')]
        pages,records=c.load(dt.date(2026,11,6),dt.date(2026,11,9),lambda _:response(rows))
        self.assertEqual(records,[{'date':'2026-11-06','value':100.0},{'date':'2026-11-09','value':922.633}]); self.assertEqual(pages[0]['response']['data'],rows)
    def test_missing_duplicate_unit_value(self):
        start,end=dt.date(2026,11,6),dt.date(2026,11,9)
        for rows in [[row('2026-11-09')],[row('2026-11-06'),row('2026-11-06')],[row('2026-11-06','null'),row('2026-11-09')]]:
            with self.assertRaises(ValueError): c.load(start,end,lambda _, rows=rows:response(rows))
        bad=response([row('2026-11-06'),row('2026-11-09')]);bad['meta']['dataFormats']={}
        with self.assertRaises(ValueError): c.load(start,end,lambda _:bad)
    def test_pagination_inconsistency(self):
        bad=response([row('2026-11-09')]);bad['meta']['total-count']=2501
        with self.assertRaises(ValueError): c.load(dt.date(2026,11,9),dt.date(2026,11,9),lambda _:bad)
    def test_transport_only_fallback(self):
        now=dt.datetime.fromisoformat('2026-11-14T12:00:00+00:00')
        def requester(url):
            filt=parse_qs(urlparse(url).query)['filter'][0]
            if '2023-01-01' in filt: raise c.TransportError('timeout')
            day=c.expected_date(now)-dt.timedelta(days=90); end=c.expected_date(now); rows=[]
            while day<=end:
                if c.business(day): rows.append(row(day.isoformat()))
                day+=dt.timedelta(days=1)
            return response(rows)
        result=c.collect(now,requester)
        self.assertEqual(result['coverage'],'last_90_days');self.assertEqual(result['records'][-1]['date'],'2026-11-12')
        def bad(_): raise ValueError('invalid format')
        with self.assertRaises(ValueError): c.collect(now,bad)
if __name__ == '__main__': unittest.main()

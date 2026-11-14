# Treasury daily source verification

This directory is the root of a future dedicated private GitHub repository. Copy collector.py, test_collector.py and .github into that repository. No site credentials or site data are required.

Run python3 -m unittest -v test_collector.py, then python3 collector.py treasury-data.json.gz. Output contains each official API response and request URL, UTC collection start, expected latest business date, unit declarations, coverage, and normalized daily TGA closing balances in billions of US dollars. Federal holiday and New York release-time rules fail closed on missing expected observations; exceptional closures or delays require investigation.

The full window starts 2023-01-01. Only on transport failure, the script retries a 90-day window and marks the result partial. Invalid schemas, units, incomplete pagination, missing values, duplicate dates or missing business days fail without an artifact. There is no PDF or local-data fallback. GitHub Actions is manual only, times out after five minutes, has read-only repository permissions, and retains the successful artifact for one day. There is no schedule or site delivery.

"""Publish a freshly collected official response; never read a local data seed."""
import json
from pathlib import Path
from collector import collect

result = collect()
target = Path('data/treasury.json')
target.parent.mkdir(exist_ok=True)
temporary = target.with_suffix('.pending')
temporary.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n', encoding='utf-8')
if json.loads(temporary.read_text(encoding='utf-8')) != result:
    raise ValueError('Serialized official data did not read back consistently')
temporary.replace(target)
print(f"Verified {len(result['records'])} daily observations through {result['expected_latest_date']}; latest {result['records'][-1]['value']} billion USD")

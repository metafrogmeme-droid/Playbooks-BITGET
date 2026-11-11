"""Download the published official evidence for every version of runeclaw-limit-scanner.

Needs the Bitget OpenAPI ACCESS-KEY in the BITGET_API_KEY environment variable.
Writes pb_<version>.json next to this script (git-ignored).
"""
import json, os, pathlib, urllib.request

STRATEGY_ID = "e977214c-86e5-405b-be0b-d5bad50b97c8"
URL = "https://api.bitget.com/api/v1/playbook/list?status=published"
out = pathlib.Path(__file__).parent
req = urllib.request.Request(URL, headers={"ACCESS-KEY": os.environ["BITGET_API_KEY"]})
with urllib.request.urlopen(req, timeout=30) as r:
    items = json.load(r)["data"]["items"]
for x in items:
    if x["strategy_id"] == STRATEGY_ID:
        (out / f"pb_{x['version']}.json").write_text(json.dumps(x))
        m = x["official_metrics"]
        print(x["version"], x["playbook_id"], m["total_return_pct"], m["max_drawdown_pct"], m["total_trades"])

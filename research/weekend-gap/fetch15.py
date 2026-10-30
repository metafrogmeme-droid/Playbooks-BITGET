import json, sys, time, urllib.request, urllib.error
sym = sys.argv[1]
URL = "https://api.bitget.com/api/v2/mix/market/history-candles?symbol={s}&granularity=15m&productType=USDT-FUTURES&endTime={e}&limit=200"
end = int(time.time() * 1000); rows = {}
while True:
    for attempt in range(5):
        try:
            with urllib.request.urlopen(URL.format(s=sym, e=end), timeout=20) as r:
                d = json.load(r)["data"]; break
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2 ** attempt)
    else:
        raise SystemExit(f"{sym}: fetch failed")
    if not d: break
    for c in d: rows[int(c[0])] = [float(x) for x in c[1:7]]
    first = min(int(c[0]) for c in d)
    if first >= end: break
    end = first - 1
    time.sleep(0.15)
out = sorted(rows.items())
json.dump(out, open(f"{sym}_15m.json", "w"))
print(sym, len(out), time.strftime("%Y-%m-%d", time.gmtime(out[0][0] / 1000)) if out else "none")

import json, sys, time, urllib.request
sym = sys.argv[1]; rows={}; page=1
while page < 200:
    u=f"https://api.bitget.com/api/v2/mix/market/history-fund-rate?symbol={sym}&productType=USDT-FUTURES&pageSize=100&pageNo={page}"
    with urllib.request.urlopen(u, timeout=20) as r: d=json.load(r)["data"]
    if not d: break
    for x in d: rows[int(x["fundingTime"])]=float(x["fundingRate"])
    page+=1; time.sleep(0.12)
out=sorted(rows.items()); json.dump(out, open(f"{sym}_fund.json","w"))
print(sym, len(out), time.strftime("%Y-%m-%d", time.gmtime(out[0][0]/1000)) if out else None)

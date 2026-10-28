#!/usr/bin/env python3
"""Zakładka Alt sezon: metryki rynku, wykresy, altcoiny z kapitalizacją i mechaniczny potencjał do ATH.
Niezależna od prognoz. Dane: CoinGecko (publiczne API; opcjonalny klucz demo w sekrecie CG_KEY)
oraz alternative.me (indeks strachu i chciwości). Odświeżane co ~30 minut, żeby mieścić się w limitach API.
Wynik: data/alt_state.json; historia: data/alt/history.jsonl (tylko dopisywana)."""
import os, json, time, urllib.request
import bot

D = os.path.join(bot.DATA, 'alt')
HIST = os.path.join(D, 'history.jsonl')
META = os.path.join(D, 'meta.json')
OUT = os.path.join(bot.DATA, 'alt_state.json')
EVERY = 1800
STABLE = {'tether', 'usd-coin', 'dai', 'first-digital-usd', 'usds', 'ethena-usde', 'paypal-usd', 'true-usd', 'frax', 'usdd'}
WRAPPED = {'wrapped-bitcoin', 'staked-ether', 'wrapped-steth', 'weth', 'wrapped-eeth',
           'coinbase-wrapped-staked-eth', 'rocket-pool-eth'}
ATTR = ('Dane: CoinGecko (publiczne API). Indeks strachu i chciwości: alternative.me. '
        'Wskaźnik sezonu altów i lista kontrolna: autorska heurystyka, nie zweryfikowana historycznie.')


def cg(path):
    h = {'User-Agent': 'darmowa-prognoza-btc/1.0'}
    if os.environ.get('CG_KEY'):
        h['x-cg-demo-api-key'] = os.environ['CG_KEY']
    req = urllib.request.Request('https://api.coingecko.com/api/v3' + path, headers=h)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def clamp(v):
    return max(0.0, min(1.0, v))


def num(v, d=0.0):
    return d if v is None else v


def prev_row(hist, cutoff):
    rows = [h for h in hist if h['t'] <= cutoff]
    return rows[-1] if rows else None


def analyse(markets, glob, fng, now, hist):
    btc = next(m for m in markets if m['id'] == 'bitcoin')
    eth = next(m for m in markets if m['id'] == 'ethereum')
    total = glob['data']['total_market_cap']['usd']
    dom = glob['data']['market_cap_percentage']['btc']
    stable_cap = sum(num(m['market_cap']) for m in markets if m['id'] in STABLE)
    stable_dom = stable_cap / total * 100
    btc30 = num(btc.get('price_change_percentage_30d_in_currency'))
    eth30 = num(eth.get('price_change_percentage_30d_in_currency'))
    alts = [m for m in markets if m['id'] not in STABLE | WRAPPED | {'bitcoin', 'ethereum'}]
    top = alts[:50]
    d30 = [num(m.get('price_change_percentage_30d_in_currency')) for m in top]
    beat = sum(1 for v in d30 if v > btc30) / len(top) * 100
    med30 = sorted(d30)[len(d30) // 2]
    alt_cap = total - num(btc['market_cap']) - num(eth['market_cap']) - stable_cap
    f = fng['value'] if fng else None
    # wskaźnik autorski: średnia z 5 składników o równych wagach, każdy od 0 do 1
    parts = [beat / 100, clamp((60 - dom) / 20), clamp((12 - stable_dom) / 6),
             clamp(0.5 + (eth30 - btc30) / 60), (f / 100) if f is not None else 0.5]
    comp = sum(parts) / len(parts) * 100
    p7 = prev_row(hist, now - 7 * 86400)
    checks = [
        ('Ponad połowa top 50 altów pokonuje BTC (30 dni)', beat > 50),
        ('Dominacja BTC spada (7 dni)', None if not p7 else dom < p7['btc_dom']),
        ('Dominacja stablecoinów spada (7 dni)', None if not p7 else stable_dom < p7['stable_dom']),
        ('ETH/BTC rośnie (30 dni)', eth30 > btc30),
        ('Indeks strachu i chciwości powyżej 50', None if f is None else f > 50),
    ]
    verdict = 'Silne sygnały sezonu altów' if comp >= 65 else ('Sygnały mieszane' if comp >= 45 else 'Przewaga BTC')
    pot = [dict(sym=m['symbol'], cap=num(m['market_cap']),
                pot=100 / max(1, 100 + num(m.get('ath_change_percentage'), -50)),
                ath=num(m.get('ath_change_percentage')),
                rel30=num(m.get('price_change_percentage_30d_in_currency')) - btc30) for m in top]
    row = dict(t=now, btc_dom=round(dom, 2), stable_dom=round(stable_dom, 2), beat_pct=round(beat, 1),
               composite=round(comp, 1), fng=f)
    return dict(
        metrics=dict(composite=round(comp, 1), btc_dom=round(dom, 2), stable_dom=round(stable_dom, 2),
                     beat_pct=round(beat, 1), alt_cap=alt_cap,
                     eth_btc=num(eth['current_price']) / num(btc['current_price']),
                     fng=f, fng_label=fng['value_classification'] if fng else None,
                     median30=round(med30, 2), btc30=round(btc30, 2), total=total, verdict=verdict,
                     verdict_note=('Wskaźnik to średnia z 5 składników o równych wagach (moja propozycja). '
                                   'Historia zapisuje się od dziś, więc za kilka miesięcy można sprawdzić, '
                                   'czy odczyty coś mówiły.'),
                     checks=checks),
        table=[dict(sym=m['symbol'], cap=num(m['market_cap']), price=num(m['current_price']),
                    d1=m.get('price_change_percentage_24h_in_currency'),
                    d7=m.get('price_change_percentage_7d_in_currency'),
                    d30=m.get('price_change_percentage_30d_in_currency'),
                    rel30=num(m.get('price_change_percentage_30d_in_currency')) - btc30,
                    ath=num(m.get('ath_change_percentage'))) for m in alts[:30]],
        top15=[dict(sym=m['symbol'], rel30=num(m.get('price_change_percentage_30d_in_currency')) - btc30)
               for m in alts[:15]],
        potential=sorted(pot, key=lambda x: -x['pot'])[:10],
        row=row)


def main():
    os.makedirs(D, exist_ok=True)
    now = int(time.time())
    meta = json.load(open(META)) if os.path.exists(META) else {}
    if os.path.exists(OUT) and now - meta.get('last', 0) < EVERY:
        print('ALT: dane świeże, pominięto')
        return
    try:
        markets = cg('/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=100&page=1'
                     '&price_change_percentage=24h,7d,30d')
        glob = cg('/global')
    except Exception as e:
        print('ALT: CoinGecko niedostępne:', type(e).__name__, '- zostają poprzednie dane')
        return
    errors, fng = [], None
    try:
        d = bot.get('https://api.alternative.me/fng/?limit=1')['data'][0]
        fng = dict(value=int(d['value']), value_classification=d['value_classification'])
    except Exception:
        errors.append('brak indeksu strachu')
    hist = bot.load_jsonl(HIST)
    st = analyse(markets, glob, fng, now, hist)
    row = st.pop('row')
    bot.append_jsonl(HIST, row)
    st.update(updated=now, errors=errors, attribution=ATTR, history=(hist + [row])[-2000:])
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, OUT)
    with open(META, 'w') as f:
        json.dump(dict(last=now), f)
    print('ALT OK: wskaźnik', st['metrics']['composite'], '|', st['metrics']['verdict'])


if __name__ == '__main__':
    main()

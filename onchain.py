#!/usr/bin/env python3
"""Zakładka Cykl on-chain (wg artykułu CrypS „Jak przewidzieć cenę BTC? 5 wskaźników on-chain”).
Wskaźniki z artykułu oznaczone jako: wyliczane, zamiennik albo niedostępne bez płatnych źródeł.
Dane dzienne: blockchain.info (publiczne, bez klucza). Własny model i własny zapis prognoz 30-dniowych
oraz ich rozliczeń. Niezależny od pozostałych zakładek. Wynik: data/onchain_state.json;
zapis: data/onchain/*.jsonl (tylko dopisywany)."""
import os, json, time, bisect, datetime as dt
import bot

D = os.path.join(bot.DATA, 'onchain')
OUT = os.path.join(bot.DATA, 'onchain_state.json')
PRED = os.path.join(D, 'predictions.jsonl')
RES = os.path.join(D, 'results.jsonl')
META = os.path.join(D, 'meta.json')
EVERY, H, WIN, MA = 6 * 3600, 30, 1460, 365
KG = [5, 10, 20, 50, 100, 200, 500, 1000]
ATTR = ('Wskaźniki: artykuł CrypS „Jak przewidzieć cenę BTC? 5 wskaźników on-chain”. '
        'Dane dzienne: blockchain.info. Zamienniki, wskaźnik temperatury i model: autorskie, do weryfikacji w czasie.')


def series(name):
    j = bot.get(f'https://api.blockchain.info/charts/{name}?timespan=all&format=json')
    return {int(v['x']) // 86400: float(v['y']) for v in j['values']}


def ma_list(x, n=MA):
    out, s = [None] * len(x), 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ratio(x, m):
    return [None if mm is None or mm <= 0 else v / mm for v, mm in zip(x, m)]


def pct(x, win=WIN):
    """Ranking bieżącej wartości w poprzednich WIN dniach (tylko przeszłość)."""
    out, s = [None] * len(x), []
    for i, v in enumerate(x):
        if i >= win and x[i - win] is not None:
            del s[bisect.bisect_left(s, x[i - win])]
        if v is not None and len(s) >= 200:
            out[i] = bisect.bisect_left(s, v) / len(s)
        if v is not None:
            bisect.insort(s, v)
    return out


def walk(keys, ys, k):
    """Walk-forward: wynik dnia i poznajemy dopiero po H dniach, więc aktualizacja liczników z dnia i-H."""
    up, n, br, hit, m = {}, {}, 0.0, 0, 0
    for i in range(len(ys)):
        j = i - H
        if j >= 0 and ys[j] is not None and keys[j] is not None:
            kk = keys[j]
            up[kk] = up.get(kk, 0) + ys[j]
            n[kk] = n.get(kk, 0) + 1
        if keys[i] is None or ys[i] is None:
            continue
        kk = keys[i]
        u, nn = up.get(kk, 0), n.get(kk, 0)
        p = (u + k / 2) / (nn + k)
        br += (p - ys[i]) ** 2
        hit += int((p >= .5) == bool(ys[i]))
        m += 1
    return dict(br=br / m, acc=hit / m, m=m, up=up, n=n) if m else None


def select(cands, ys):
    best = None
    for nm, keys in cands.items():
        for k in KG:
            w = walk(keys, ys, k)
            if w and (best is None or w['br'] < best[2]['br']):
                best = (nm, k, w)
    return best


def zone(c):
    if c >= 75:
        return 'euforia (analogicznie do strefy NUPL > 0,75 z artykułu)'
    if c >= 50:
        return 'wiara (strefa 0,5–0,75)'
    if c >= 25:
        return 'optymizm (strefa 0,25–0,5)'
    return 'strach / kapitulacja (poniżej 0,25)'


def main():
    os.makedirs(D, exist_ok=True)
    now = int(time.time())
    meta = json.load(open(META)) if os.path.exists(META) else {}
    if os.path.exists(OUT) and now - meta.get('last', 0) < EVERY:
        print('ON-CHAIN: dane świeże, pominięto')
        return
    try:
        price, addr = series('market-price'), series('n-unique-addresses')
        fees, rev = series('transaction-fees-usd'), series('miners-revenue')
    except Exception as e:
        print('ON-CHAIN: blockchain.info niedostępne:', type(e).__name__, '- zostają poprzednie dane')
        return
    days = sorted(d for d in price if d in addr and d in fees and d in rev)
    N = len(days)
    p = [price[d] for d in days]
    a = [addr[d] for d in days]
    f = [fees[d] for d in days]
    r = [rev[d] for d in days]
    ma_p, ma_a, ma_f, ma_r = ma_list(p), ma_list(a), ma_list(f), ma_list(r)
    names = ['Wycena (cena / średnia 365 dni)', 'Aktywne adresy (vs średnia 365 dni)',
             'Opłaty (vs średnia 365 dni)', 'Puell (przychód górników vs średnia 365 dni)']
    comps = dict(zip(names, [ratio(p, ma_p), ratio(a, ma_a), ratio(f, ma_f), ratio(r, ma_r)]))
    pcts = {k: pct(v) for k, v in comps.items()}
    comp = [None] * N
    for i in range(N):
        vals = [pcts[k][i] for k in names]
        if all(v is not None for v in vals):
            comp[i] = 100 * sum(vals) / len(vals)
    ys = [int(p[i + H] > p[i]) if i + H < N else None for i in range(N)]
    ck = [None if c is None else min(4, int(c / 20)) for c in comp]
    vk = [None if v is None else min(4, int(v * 5)) for v in pcts[names[0]]]
    nk = [0 if c is not None else None for c in comp]
    cands = {'temperatura (5 składników)': ck, 'wycena (cena / średnia 365 dni)': vk, 'bazowy (bez cech)': nk}
    best = select(cands, ys)
    if best is None:
        print('ON-CHAIN: za mało danych do modelu')
        return
    name, k, w = best
    kn = cands[name][-1]
    known = [y for y in ys if y is not None]
    base_rate = sum(known) / len(known)
    p_up = (w['up'].get(kn, 0) + k / 2) / (w['n'].get(kn, 0) + k) if kn is not None else base_rate
    mname = f'{name}, k={k}'

    idx = {d: i for i, d in enumerate(days)}
    pred, res = bot.load_jsonl(PRED), bot.load_jsonl(RES)
    done = {x['d'] for x in res}
    for pr in pred:
        if pr['d'] in done or pr['d'] not in idx or idx[pr['d']] + H >= N:
            continue
        i = idx[pr['d']]
        y = int(p[i + H] > p[i])
        rec = dict(d=pr['d'], p=pr['p'], y=y, br=round((pr['p'] - y) ** 2, 6), hit=int((pr['p'] >= .5) == bool(y)))
        bot.append_jsonl(RES, rec)
        res.append(rec)
        done.add(pr['d'])
    ln = len(res)
    lbr = sum(x['br'] for x in res) / ln if ln else None
    lacc = sum(x['hit'] for x in res) / ln if ln else None
    fallback = ln >= 60 and lbr > .25
    if fallback:
        p_up, mname = 0.5, 'zapas: 50% (model przegrywa na żywo)'
    if days[-1] not in {x['d'] for x in pred}:
        bot.append_jsonl(PRED, dict(d=days[-1], p=round(p_up, 4), model=mname, issued=now))

    iso = lambda d: dt.datetime.fromtimestamp(d * 86400, dt.timezone.utc).date().isoformat()
    bw = walk(ck, ys, 5)
    bins = [dict(lo=20 * b, hi=20 * b + 20, n=bw['n'].get(b, 0),
                 p=round(bw['up'].get(b, 0) / bw['n'][b], 4) if bw['n'].get(b) else None) for b in range(5)]
    tail = range(max(0, N - 730), N)
    comp_now = comp[-1]
    st = dict(
        updated=now, data_day=iso(days[-1]),
        composite=round(comp_now, 1) if comp_now is not None else None,
        zone=zone(comp_now) if comp_now is not None else None,
        indicators=[
            dict(name='Realized Price (zamiennik: średnia 365 dni ceny)', status='zamiennik', value=round(ma_p[-1], 2),
                 unit='USD', note='to nie jest Realized Price z artykułu'),
            dict(name='MVRV (zamiennik: cena / średnia 365 dni)', status='zamiennik',
                 value=round(comps[names[0]][-1], 3), unit='x', note='prawdziwy MVRV wymaga bazy UTXO'),
            dict(name='NUPL', status='niedostępny', value=None, unit='',
                 note='wymaga kapitalizacji zrealizowanej (baza UTXO); brak darmowego źródła'),
            dict(name='Exchange Netflow', status='niedostępny', value=None, unit='',
                 note='wymaga oznaczonych adresów giełd; źródła płatne'),
            dict(name='LTH-SOPR', status='niedostępny', value=None, unit='',
                 note='wymaga wieku monet w UTXO; źródła płatne'),
            dict(name='Aktywne adresy / średnia 365 dni', status='wyliczany',
                 value=round(comps[names[1]][-1], 3), unit='x', note='aktywność sieci, wskaźnik z artykułu'),
            dict(name='Puell (przychód górników / średnia 365 dni)', status='dodatkowy',
                 value=round(comps[names[3]][-1], 3), unit='x', note='spoza artykułu'),
            dict(name='Opłaty / średnia 365 dni', status='dodatkowy',
                 value=round(comps[names[2]][-1], 3), unit='x', note='spoza artykułu'),
        ],
        components=[dict(name=k, pct=round(pcts[k][-1], 3) if pcts[k][-1] is not None else None) for k in names],
        model=dict(name=mname, p_up=round(p_up, 4), base_rate=round(base_rate, 4), k=k, walk_n=w['m'],
                   walk_acc=round(w['acc'], 4), walk_brier=round(w['br'], 4), live_n=ln,
                   live_acc=round(lacc, 4) if ln else None, live_brier=round(lbr, 4) if ln else None,
                   fallback=fallback),
        bins=bins,
        charts=dict(days=[iso(days[i]) for i in tail], composite=[comp[i] for i in tail],
                    price=[round(p[i], 2) for i in tail]),
        attribution=ATTR)
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(st, fh, ensure_ascii=False)
    os.replace(tmp, OUT)
    with open(META, 'w') as fh:
        json.dump(dict(last=now), fh)
    print('ON-CHAIN OK: temperatura', st['composite'], '|', mname, '| p_up', round(p_up, 4))


if __name__ == '__main__':
    main()

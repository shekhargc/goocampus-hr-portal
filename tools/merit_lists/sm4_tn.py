import os, re, collections, fitz, json
from sm4_common import *
P = '/Users/Santosh/goocampus-news/pdf/'
# APP.NO is read only for in-memory matching of the special-quota eligibility lists (sm4_tn_special.py); never written out
GQAPP = ('app', 100, 158)
MQAPP = ('app', 100, 176)
GQCOLS = [('rank', 60, 100), ('roll', 158, 200), ('comm', 382, 436), ('svc', 436, 478), ('inc', 478, 516), ('total', 516, 555), ('crank', 555, 640)]
MQCOLS = [('rank', 60, 100), ('roll', 176, 225), ('comm', 470, 530), ('score', 530, 640)]
COMM_OK = re.compile(r'^(OC|BC|BCM|MBC&DNC|MBC|MBCV|MBC\(V\)|DNC|SC|SCA|ST|BC\(M\)|MBC\(DNC\))$')
def read(fn, cols, anchor=(60, 100)):
    d = fitz.open(os.path.join(P, fn)); recs = []  # fn may be absolute
    for i, pg in enumerate(d):
        ws = dedupe(vwords(pg))
        hy = min([w[1] for w in ws if w[4] in ('RANK',)] or [0])
        # anchors: rank tokens (digits, maybe with A suffix)
        anchors = sorted([w for w in ws if anchor[0] <= w[0] < anchor[1] and w[1] > hy + 10 and re.fullmatch(r'\d+A?', w[4])], key=lambda w: w[1])
        for j, a in enumerate(anchors):
            y0 = a[1] - 6; y1 = (anchors[j + 1][1] - 6) if j + 1 < len(anchors) else a[1] + 14
            band = [w for w in ws if y0 <= w[1] < y1]
            rec = {'_page': i}
            for name, x0, x1 in cols:
                rec[name] = ' '.join(w[4] for w in sorted([w for w in band if x0 <= w[0] < x1], key=lambda w: (round(w[1]), w[0])))
            recs.append(rec)
    return recs
def diag(recs, keys):
    bad = [(r['_page'], r['rank']) for r in recs if not ROLL.fullmatch(r['roll'])]
    print('rows', len(recs), 'bad roll', len(bad), bad[:10])
    for k in keys:
        c = collections.Counter(r[k] for r in recs)
        if k == 'comm':
            print(k, {v: n for v, n in c.items() if COMM_OK.match(v)}, 'unrecognised:', sum(n for v, n in c.items() if not COMM_OK.match(v)))
        else:
            print(k, c.most_common(10) if k in ('svc', 'inc') else ('non-numeric', [v for v in c if not re.fullmatch(r'[\d.]+A?', v)][:10]))
if __name__ == '__main__':
    gq = read('cd488e3665c3.pdf', GQCOLS); print('GQ'); diag(gq, ['comm', 'svc', 'inc', 'total', 'crank', 'rank'])
    mq = read('e6df5a89bbbc.pdf', MQCOLS); print('MQ'); diag(mq, ['comm', 'score', 'rank'])

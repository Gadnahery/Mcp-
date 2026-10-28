"""Synthetic 1M candles for tests (the engine requires 1M execution data)."""
from __future__ import annotations


def with_1m(m5, side="BUY", post=4):
    """Split each *completed* 5M candle into five 1M candles, then add `post` directional 1M candles
    after the last completed 5M candle (the execution leg) plus one forming 1M candle."""
    out = []
    for c in m5[:-1]:
        o, cl, hi, lo = float(c["open"]), float(c["close"]), float(c["high"]), float(c["low"])
        for i in range(5):
            a = o + (cl - o) * i / 5
            b = o + (cl - o) * (i + 1) / 5
            h = max(a, b) + 0.001
            l = min(a, b) - 0.001
            if i == 1:
                h = max(h, hi)
            if i == 2:
                l = min(l, lo)
            out.append(dict(epoch=int(c["epoch"]) + 60 * i, open=a, high=max(h, a, b), low=min(l, a, b), close=b))
    last_close = float(m5[-2]["close"])
    start = int(m5[-1]["epoch"])
    step = 0.15 if side == "BUY" else -0.15
    px = last_close
    for k in range(post):
        o, cl = px, px + step
        out.append(dict(epoch=start + 60 * k, open=o, high=max(o, cl) + 0.01, low=min(o, cl) - 0.01, close=cl))
        px = cl
    out.append(dict(epoch=start + 60 * post, open=px, high=px + 0.02, low=px - 0.02, close=px))  # forming
    return out


def extend_5m(m5, n=2, step=0.4):
    """Drop the forming 5M candle, add n bullish completed 5M candles and a new forming one."""
    out = list(m5[:-1])
    px = float(out[-1]["close"])
    t = int(out[-1]["epoch"])
    for k in range(1, n + 1):
        o, cl = px, px + step
        out.append(dict(epoch=t + 300 * k, open=o, high=cl + 0.05, low=o - 0.05, close=cl))
        px = cl
    out.append(dict(epoch=t + 300 * (n + 1), open=px, high=px + 0.1, low=px - 0.05, close=px + 0.02))
    return out

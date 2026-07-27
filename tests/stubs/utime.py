"""Deterministic clock — tests must not depend on wall time."""
_now = [0]
def ticks_ms(): return _now[0]
def ticks_add(t, d): return t + d
def ticks_diff(a, b): return a - b
def sleep_ms(ms): _now[0] += max(1, ms)
def sleep_us(us): _now[0] += max(1, us // 1000)
def sleep(s): _now[0] += int(s * 1000)
def time(): return _now[0] // 1000
def localtime(t=None): return (2026, 7, 27, 12, 0, 0, 0, 208)

"""Minimal `micropython` module stub."""


def const(x):
    return x


def schedule(func, arg):
    # On hardware this defers to the main loop; in tests, just call it.
    func(arg)

# ============================================================
#  mp_lora — micropython-lib's official SX126x LoRa driver, vendored
# ============================================================
# These files are byte-identical copies from micropython-lib
# (https://github.com/micropython/micropython-lib), packages `lora`,
# `lora-sx126x` and `lora-sync`. MIT license; Copyright (c) 2023
# Angus Gratton. Keep them unmodified — that is what makes updating
# them a plain copy, and what makes their behaviour answerable by
# upstream rather than by us.
#
# Why vendored rather than `mip install`: the lamps in this project may
# never touch the internet, so everything a board needs has to travel
# in the repo and over the USB cable.
#
# What this package is NOT: a LoRaWAN stack. It drives the radio —
# TCXO, IRQs, calibration, the inverted-IQ silicon erratum — and the
# LoRaWAN layer (MIC, encryption, frame counters, Class C) remains
# ../lorawan_crypto.py and ../lorawan_abp.py, checked against RFC 4493
# and FIPS-197 vectors. No maintained MicroPython LoRaWAN stack exists;
# this split uses the best maintained code for the layer where it
# exists, and our tested code for the layer where it doesn't.

from .sx126x import SX1262  # noqa: F401

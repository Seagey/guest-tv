"""Check bookings.py against the made-up emails in tools/booking-samples (no Airbnb account needed).

    .venv/bin/python tools/booking_test.py
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import bookings, server

SAMPLES = os.path.join(HERE, "booking-samples")
bookings.INBOX = SAMPLES
found, errors = bookings.collect({}, {})
for b in found:
    print(b["kind"], b["guest"] or "-", b["guests"], b["code"] or "-", b["arrives"])
stays = server.ical_stays("file://" + os.path.join(SAMPLES, "airbnb-calendar.txt"))
names = bookings.match(found, stays)
print(names)

want = {"2026-11-02": {"guest": "Sarah", "guests": 3, "code": "HMTEST1234"},
        "2026-11-20": {"guest": "Priya", "guests": 2, "code": ""}}
assert not errors, errors
assert len(found) == 4, "the shop email should be ignored"
assert len(stays) == 3, "the host's blocked days are not a stay"
assert names == want, names
print("ok")

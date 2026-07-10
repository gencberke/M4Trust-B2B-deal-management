"""Moka numeric durum eşlemesi (§2.7) — internal M4Trust statüsünden ayrı tutulur.

`CANCELLED`/`REFUNDED` bu fazda implement edilen endpoint'lerin hiçbiri
tarafından üretilmez (cancel/refund akışları plan §07/ayrı child plan'a
bırakıldı); yalnızca katalog tamlığı için burada tanımlıdır.
"""

PAYMENT_STATUS_PENDING = 0
TRX_STATUS_PENDING = 0

PAYMENT_STATUS_APPROVED = 2
TRX_STATUS_APPROVED = 1

PAYMENT_STATUS_CANCELLED = 3
TRX_STATUS_CANCELLED = 1

PAYMENT_STATUS_REFUNDED = 4
TRX_STATUS_REFUNDED = 1

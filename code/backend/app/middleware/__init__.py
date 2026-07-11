"""Request-ID middleware paketi (Plan 02 / Faz 2B).

Bu pakete kayıt Yusuf'ta değildir — `main.py`'ye `app.add_middleware(...)`
Berke'nin entegrasyon commit'idir (bkz. program_haritasi §3).
"""

from .request_id import RequestIDMiddleware, generate_request_id

__all__ = ["RequestIDMiddleware", "generate_request_id"]

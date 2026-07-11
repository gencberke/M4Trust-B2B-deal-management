"""Standart API hata zarfı paketi (Plan 02 / Faz 2B).

Bu pakete kayıt Yusuf'ta değildir — `main.py`'ye handler bağlama Berke'nin
entegrasyon commit'idir (bkz. plans/planning/program_haritasi_paralel_calisma.md §3).
"""

from .errors import (
    ApiError,
    api_error_handler,
    build_error_body,
    unhandled_exception_handler,
)

__all__ = [
    "ApiError",
    "api_error_handler",
    "build_error_body",
    "unhandled_exception_handler",
]

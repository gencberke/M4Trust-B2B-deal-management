"""Bağımsız contract-faithful Moka mock servisi (GATE M1-YUSUF).

Ana backend'e import/register EDİLMEZ — kendi uvicorn process'i (port 8001
önerilir) ve kendi SQLite DB'siyle (`code/data/runtime/mock_moka.db`) çalışır
(plans/ready/01_moka_contract_mock_and_client.md Faz 1B, kırmızı çizgiler).

Çalıştırma:
    uvicorn backend.mock_moka.app:app --port 8001
"""

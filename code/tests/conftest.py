"""Ortak test-altyapısı — bu dosyanın tek sahibi Yusuf'tur (program_haritasi §3).

Domain-özel fixture'lar (ör. mock Moka'nın `MOCK_MOKA_*` env izolasyonu)
burada değil, kendi test modüllerinde kalır — bu dosya global fixture
çöplüğüne dönüşmez.
"""

from __future__ import annotations

import sys
import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_CODE_ROOT = Path(__file__).resolve().parent.parent

# İki kaynak kökü: offline parser `scripts/`, uygulama paketi `code/` (backend.app...).
sys.path.insert(0, str(_CODE_ROOT / "scripts"))
sys.path.insert(0, str(_CODE_ROOT))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "legacy_compat: legacy_v1 capability-token davranışını doğrulayan dar set "
        "(Plan 06 closure'da LEGACY_CAPABILITY_ACCESS_ENABLED default false olduğu "
        "için bu testler flag'i env üzerinden açar).",
    )


@pytest.fixture(autouse=True)
def _legacy_capability_compat(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`legacy_compat` işaretli testlerde legacy capability erişimini env ile açar.

    Plan 06 closure default'u kapalıdır; legacy token akışları yalnız bu dar
    işaretli sette (removal gate'ine kadar) yaşar."""
    if request.node.get_closest_marker("legacy_compat"):
        monkeypatch.setenv("LEGACY_CAPABILITY_ACCESS_ENABLED", "true")


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Her test kendi sqlite dosyasını kullanır — gerçek runtime DB'ye dokunulmaz.

    Ana `backend.app.*` testlerinin ortak (daha önce her dosyada ayrı ayrı
    kopyalanan) `DB_PATH`/`LLM_PROVIDER` izolasyonu. Mock Moka server kendi
    ayrı `MOCK_MOKA_*` env alanını kullanır ve bu fixture'dan etkilenmez
    (`test_mock_moka_server.py`, `test_moka_e2e_contract.py` kendi izolasyon
    fixture'larını korur).
    """
    db_path = tmp_path / "m4trust_test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("DOCUMENT_STORAGE_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    # Runtime storage is fail-closed without a 32-byte AES key. Tests use a
    # deterministic, process-local key; production/demo must provide its own.
    monkeypatch.setenv(
        "APP_ENCRYPTION_KEY", base64.b64encode(b"m4trust-test-storage-key-32byte!").decode("ascii")
    )
    from backend.app.services import auth_hardening

    auth_hardening.reset_rate_limit_state_for_tests()


@pytest.fixture()
def client() -> TestClient:
    """`backend.app.main.app` için lifespan-aware `TestClient`.

    Context-manager formu şart — `startup` (ve dolayısıyla `init_db`) bu
    FastAPI sürümünde yalnız `with TestClient(app) as c:` ile tetiklenir.
    """
    from backend.app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def stub_actor_factory():
    """`ActorContext` üreten fabrika — `app.dependency_overrides[get_current_actor] = ...`
    kalıbıyla kullanılır (Plan 03+ tüm auth-korumalı router testlerinin ortak
    ihtiyacı; domain-özel actor senaryoları yine kendi test modüllerinde
    kalır, burada yalnız üretim mekanizması paylaşılır).

    Kullanım::

        app.dependency_overrides[get_current_actor] = stub_actor_factory(user_id="u1")
    """
    from backend.app.services.access_control import ActorContext

    def _factory(**overrides):
        defaults = {
            "actor_type": "legacy_capability",
            "auth_method": "legacy_capability",
        }
        defaults.update(overrides)
        actor = ActorContext(**defaults)

        def _dependency() -> ActorContext:
            return actor

        return _dependency

    return _factory


@pytest.fixture()
def dependency_override_cleanup():
    """`app.dependency_overrides`'ı test sonunda temizler.

    Plan 03+'ta `app.dependency_overrides[get_current_actor] = stub_actor`
    kalıbını kullanacak testler için: override'ı unutmak sonraki testlere
    sızar (StubActor kalıntısı gerçek isteklerde de etkili kalır). Bu fixture
    çağrıldığı testte, test bitince (başarılı/başarısız fark etmeksizin)
    override sözlüğünü sıfırlar.
    """
    from backend.app.main import app

    yield app.dependency_overrides
    app.dependency_overrides.clear()

from src.tiktok import driver as drv


class TestMakeDriverFallback:
    def test_falls_back_when_uc_fails(self, monkeypatch):
        calls = []
        monkeypatch.setattr(drv, "_make_uc_driver",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no uc")))
        monkeypatch.setattr(drv, "_make_fallback_driver",
                            lambda *a, **k: calls.append("fallback") or "DRIVER")
        d = drv.make_driver(headless=True, account_id="main")
        assert d == "DRIVER" and calls == ["fallback"]

    def test_uses_uc_when_available(self, monkeypatch):
        monkeypatch.setattr(drv, "_make_uc_driver", lambda *a, **k: "UC")
        monkeypatch.setattr(drv, "_make_fallback_driver",
                            lambda *a, **k: "SHOULD_NOT_BE_CALLED")
        assert drv.make_driver(headless=False, account_id="main") == "UC"

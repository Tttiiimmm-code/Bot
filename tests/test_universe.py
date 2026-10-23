from tradingbot.research import universe as uni


class _RawClient:
    def __init__(self, assets):
        self.assets, self.calls = assets, []

    def get(self, path, params):
        self.calls.append((path, params))
        return self.assets


def test_fetch_assets_tolerates_unknown_exchange(tmp_path):
    # Regression 2026-10-20: Alpaca meldet Börse "TXSE", alpaca-py brach den ganzen Abruf ab.
    client = _RawClient([
        {"symbol": "AAA", "exchange": "NASDAQ", "status": "active", "name": "A Inc"},
        {"symbol": "TXS", "exchange": "TXSE", "status": "active", "name": "Texas Co"},
        {"symbol": "BRK.B", "exchange": "NYSE", "status": "active", "name": "Berkshire"},
        {"symbol": "OLD", "exchange": "NYSE", "status": "inactive", "name": None},
    ])
    symbols = uni.fetch_assets(client, tmp_path)
    assert client.calls == [("/assets", {"asset_class": "us_equity"})]
    assert "TXS" not in symbols and "BRK.B" not in symbols
    assert {"AAA", "OLD"} <= set(symbols)
    assert (tmp_path / "assets.pkl").exists()
    assert uni.fetch_assets(None, tmp_path) == symbols          # zweiter Aufruf aus dem Zwischenspeicher

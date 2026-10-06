from sigma.classification.decision_cache import ClassificationDecisionCache


def test_decision_cache_round_trip(tmp_path):
    cache = ClassificationDecisionCache(tmp_path / "decisions.sqlite")
    try:
        key = cache.key("psic", "rev5", ["011", "012"])
        assert cache.get(key) is None
        cache.put(key, {"code": "011", "agreement": 1.0})
        cache.flush()
        assert cache.get(key) == {"agreement": 1.0, "code": "011"}
    finally:
        cache.close()

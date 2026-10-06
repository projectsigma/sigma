from sigma import Sigma


def test_execution_scope_is_fresh_per_public_operation_and_shared_when_nested():
    job = Sigma.__new__(Sigma)
    job._runtime_cache = {"stale": object()}
    job._runtime_depth = 0

    with job._execution_scope():
        assert "stale" not in job._runtime_cache
        job._runtime_cache["source_ref"] = "current"
        with job._execution_scope():
            assert job._runtime_cache["source_ref"] == "current"
        assert job._runtime_cache["source_ref"] == "current"

    with job._execution_scope():
        assert "source_ref" not in job._runtime_cache

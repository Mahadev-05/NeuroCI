"""
NeuroCI — Metrics Tests.

Tests for Prometheus metrics and stage timing.
"""
from src.metrics.prometheus import (
    StageTimer,
    setup_metrics,
    track_repair_attempt,
    track_webhook,
)
from src.models import AgentState, FailureCategory, PatchResult, RepairResult


class TestMetrics:

    def test_setup_metrics(self):
        """setup_metrics should not raise."""
        setup_metrics()

    def test_track_repair_attempt(self):
        """Should increment fix counter."""
        state = AgentState(
            run_id=999, repo_full_name="o/r",
            head_branch="main", head_sha="abc",
            category=FailureCategory.IMPORT_ERROR,
            patch=PatchResult(confidence=0.9, unified_diff="d"),
            result=RepairResult(
                success=True, action_taken="auto_pr",
                category=FailureCategory.IMPORT_ERROR,
            ),
        )
        # Should not raise
        track_repair_attempt(state)

    def test_track_repair_no_result(self):
        """No result should be a no-op."""
        state = AgentState(
            run_id=999, repo_full_name="o/r",
            head_branch="main", head_sha="abc",
        )
        track_repair_attempt(state)  # Should not raise

    def test_track_webhook(self):
        """Should increment webhook counter."""
        track_webhook("completed", "failure")

    def test_stage_timer(self):
        """StageTimer should record duration."""
        import time
        with StageTimer("test_stage"):
            time.sleep(0.01)
        # Should not raise


class TestModels:

    def test_failure_category_patchable(self):
        assert FailureCategory.IMPORT_ERROR.is_patchable is True
        assert FailureCategory.FLAKY_TEST.is_patchable is False

    def test_failure_category_high_risk(self):
        assert FailureCategory.LOGIC_BUG.is_high_risk is True
        assert FailureCategory.IMPORT_ERROR.is_high_risk is False

    def test_metrics_snapshot_model(self):
        from src.models import MetricsSnapshot
        m = MetricsSnapshot(total_failures_processed=10, total_fixes_attempted=5)
        assert m.total_failures_processed == 10

    def test_policy_input_model(self):
        from src.models import PolicyInput
        p = PolicyInput(repo="o/r", branch="main", target_file="f.py",
                        confidence=0.9, category="ImportError", lines_changed=3)
        assert p.confidence == 0.9

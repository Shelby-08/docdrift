from docsentry.jobs.dedup import DeliveryTracker


def test_delivery_tracker_lifecycle() -> None:
    tracker = DeliveryTracker(capacity=3)
    assert tracker.begin("d1") is True
    assert tracker.get_state("d1") == "in_progress"

    # In-progress duplicate rejected
    assert tracker.begin("d1") is False

    tracker.mark("d1", "succeeded")
    assert tracker.get_state("d1") == "succeeded"
    assert tracker.begin("d1") is False

    tracker.mark("d1", "failed")
    assert tracker.get_state("d1") == "failed"
    # Failed delivery can be retried
    assert tracker.begin("d1") is True


def test_delivery_tracker_eviction() -> None:
    tracker = DeliveryTracker(capacity=2)
    tracker.begin("d1")
    tracker.mark("d1", "succeeded")
    tracker.begin("d2")
    tracker.mark("d2", "succeeded")
    tracker.begin("d3")
    tracker.mark("d3", "succeeded")

    # d1 should be evicted because capacity is 2
    assert tracker.get_state("d1") is None
    assert tracker.get_state("d2") == "succeeded"
    assert tracker.get_state("d3") == "succeeded"
    # Evicted ID can begin again
    assert tracker.begin("d1") is True


def test_delivery_tracker_empty_delivery_id() -> None:
    tracker = DeliveryTracker()
    assert tracker.begin("") is True
    tracker.mark("", "succeeded")
    assert tracker.get_state("") is None

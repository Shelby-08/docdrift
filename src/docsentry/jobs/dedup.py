from collections import OrderedDict
from typing import Literal

DeliveryState = Literal["in_progress", "succeeded", "superseded", "failed"]


class DeliveryTracker:
    """Bounded in-memory delivery ID tracker (oldest evicted above capacity)."""

    def __init__(self, capacity: int = 5000) -> None:
        self._capacity = capacity
        self._deliveries: OrderedDict[str, DeliveryState] = OrderedDict()

    def begin(self, delivery_id: str) -> bool:
        """Return True if delivery is new or previously failed;
        False if in_progress/succeeded/superseded.
        """
        if not delivery_id:
            return True

        if delivery_id in self._deliveries:
            state = self._deliveries[delivery_id]
            if state in ("in_progress", "succeeded", "superseded"):
                return False
            self._deliveries.move_to_end(delivery_id)

        self._deliveries[delivery_id] = "in_progress"
        while len(self._deliveries) > self._capacity:
            self._deliveries.popitem(last=False)
        return True

    def mark(self, delivery_id: str, state: DeliveryState) -> None:
        """Update delivery state."""
        if not delivery_id:
            return

        if delivery_id in self._deliveries:
            self._deliveries.move_to_end(delivery_id)
        self._deliveries[delivery_id] = state
        while len(self._deliveries) > self._capacity:
            self._deliveries.popitem(last=False)

    def get_state(self, delivery_id: str) -> DeliveryState | None:
        return self._deliveries.get(delivery_id)

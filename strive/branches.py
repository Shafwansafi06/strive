"""BR-01: one result shape for every evidence branch.

Fusion must never have to guess whether a branch ran. A branch that did not
produce evidence returns `available=False` with `score=None` — it is NOT a zero,
and a zero must never be read as "genuine".

`confidence` is how much the branch trusts its own output. `reliability` is how
much the channel permits us to trust it (see strive/channel.py). They are kept
separate so a confident branch on a broken channel is still discounted.
"""
from dataclasses import asdict, dataclass, field
import time


@dataclass
class BranchResult:
    name: str
    score: float | None = None
    confidence: float = 0.
    reliability: float = 1.
    timestamp: float = field(default_factory=time.time)
    latency_ms: float = 0.
    available: bool = False
    reason_codes: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.score is not None and not 0. <= self.score <= 1.:
            raise ValueError(f"{self.name}: score must be within [0,1] or None")
        for name in ("confidence", "reliability"):
            if not 0. <= getattr(self, name) <= 1.:
                raise ValueError(f"{self.name}: {name} must be within [0,1]")
        if self.available and self.score is None:
            raise ValueError(f"{self.name}: an available branch must carry a score")

    @classmethod
    def unavailable(cls, name: str, reason: str, latency_ms: float = 0., **metadata) -> "BranchResult":
        """Explicit absence of evidence. Never a zero score."""
        return cls(name=name, score=None, confidence=0., available=False,
                   latency_ms=latency_ms, reason_codes=[reason], metadata=metadata)

    def to_dict(self) -> dict:
        return asdict(self)


def weight_mask(branches: dict[str, BranchResult], weights: dict[str, float]) -> dict[str, float]:
    """Normalize configured weights over the branches that actually have evidence.

    Returns an empty mapping when nothing is available, so the caller must decide
    what to do rather than receiving a spurious 0.0 risk.
    """
    active = {name: weights.get(name, 0.) * branches[name].reliability
              for name, branch in branches.items() if branch.available}
    total = sum(active.values())
    return {name: value / total for name, value in active.items()} if total > 0 else {}

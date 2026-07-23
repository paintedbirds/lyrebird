"""WER scoring and timing statistics used to summarize benchmark runs."""

from dataclasses import dataclass, field


@dataclass
class WerResult:
    wer: float  # 0.0-1.0
    substitutions: int
    deletions: int
    insertions: int
    hits: int

    @property
    def exact_match(self) -> bool:
        return self.wer == 0.0


def compute_wer(expected: str, hypothesis: str) -> WerResult:
    """Word error rate between an expected transcript and a model's output.

    Case-insensitive and punctuation-insensitive: dictation transcripts
    differ on things like a trailing period or capitalization far more
    often than on actual word errors, and that noise would drown out the
    signal this benchmark exists to measure.
    """
    import jiwer

    transform = jiwer.Compose(
        [
            jiwer.ToLowerCase(),
            jiwer.RemovePunctuation(),
            jiwer.RemoveMultipleSpaces(),
            jiwer.Strip(),
            jiwer.ReduceToListOfListOfWords(),
        ]
    )
    out = jiwer.process_words(
        expected,
        hypothesis,
        reference_transform=transform,
        hypothesis_transform=transform,
    )
    return WerResult(
        wer=out.wer,
        substitutions=out.substitutions,
        deletions=out.deletions,
        insertions=out.insertions,
        hits=out.hits,
    )


@dataclass
class TimingStats:
    samples: list = field(default_factory=list)  # seconds, one per transcribe() call

    @property
    def count(self) -> int:
        return len(self.samples)

    @property
    def mean(self) -> float:
        return sum(self.samples) / len(self.samples) if self.samples else 0.0

    @property
    def p95(self) -> float:
        if not self.samples:
            return 0.0
        ordered = sorted(self.samples)
        idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
        return ordered[idx]

    @property
    def min(self) -> float:
        return min(self.samples) if self.samples else 0.0

    @property
    def max(self) -> float:
        return max(self.samples) if self.samples else 0.0

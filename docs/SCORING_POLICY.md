# Scoring Policy

`ScoringPolicy` is versioned by code and version. Weights are scenario-specific
and must sum to 1.0000.

The policy prohibits provider default bonuses or penalties. Customer preference
may only appear as explicit scenario input and must not be encoded as a system
default.

Scores are separated into:

- Match Score from Week 7 mapping;
- Dimension Fit Score;
- Business Fit Score;
- Confidence;
- Completeness.

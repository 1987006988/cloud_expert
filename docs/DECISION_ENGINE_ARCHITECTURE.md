# Decision Engine Architecture

Week 10 adds an internal scenario decision engine.

Flow:

1. Validate Week 7, Week 8, and Week 9 gates.
2. Load versioned scenario and scoring policy YAML.
3. Persist `DecisionScenario`, `ScenarioRequirement`, `ScoringPolicy`, and
   `ScoringRule`.
4. Select real `MappingCandidate` rows.
5. Link Evidence Package and TCO inputs when available.
6. Apply hard blockers before ranking.
7. Store separate Match Score, Business Fit, Confidence, and Completeness.
8. Generate internal-only `CandidateDecisionResult` rows.

The engine does not generate sales scripts, customer commitments, RAG answers,
or unconditional provider recommendations.

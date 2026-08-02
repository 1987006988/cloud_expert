# Scenario Model

`DecisionScenario` defines market mode, country, preferred regions, workload,
requirements, budget assumptions, and policy binding.

`ScenarioRequirement` defines requirement type, operator, mandatory status,
priority, missing-data policy, and evidence requirement.

Requirement priorities are:

- mandatory;
- critical;
- high;
- medium;
- low;
- informational.

Mandatory missing data defaults to `requires_review` or `block`.

from __future__ import annotations

import argparse
import json

from _bootstrap import ROOT as _ROOT  # noqa: F401

from cloud_expert.database.models.mapping import MappingCandidate
from cloud_expert.mapping.pipeline import make_session


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id", type=int, required=True)
    args = parser.parse_args()
    with make_session() as session:
        candidate = session.get(MappingCandidate, args.candidate_id)
        if candidate is None:
            print(json.dumps({"error": "candidate_not_found"}))
            return 1
        payload = {
            "id": candidate.id,
            "mapping_level": candidate.mapping_level,
            "source": f"{candidate.source_entity_type}:{candidate.source_entity_id}",
            "target": f"{candidate.target_entity_type}:{candidate.target_entity_id}",
            "relationship_type": candidate.relationship_type,
            "candidate_status": candidate.candidate_status,
            "review_status": candidate.review_status,
            "score": str(candidate.normalized_score),
            "confidence": str(candidate.confidence),
            "blocking_reasons": candidate.blocking_reasons or [],
            "conditions": candidate.conditions or [],
            "explanation": candidate.explanation,
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

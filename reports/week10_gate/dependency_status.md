# Dependency Status

{
  "policy_validation": {
    "policy_files": 5,
    "valid_files": 5,
    "invalid_files": 0,
    "results": [
      {
        "path": "config\\decision\\policies\\archive_object_storage.yaml",
        "code": "archive_object_storage",
        "version": "v1",
        "dimensions": [
          "availability_fit",
          "compliance_fit",
          "cost_fit",
          "data_freshness",
          "evidence_quality",
          "migration_fit",
          "operability_fit",
          "regional_fit",
          "reliability_fit",
          "review_readiness",
          "technical_fit"
        ],
        "missing_optional_dimensions": [],
        "rules": 1,
        "valid": true,
        "errors": []
      },
      {
        "path": "config\\decision\\policies\\cost_sensitive_compute.yaml",
        "code": "cost_sensitive_compute",
        "version": "v1",
        "dimensions": [
          "availability_fit",
          "compliance_fit",
          "cost_fit",
          "data_freshness",
          "evidence_quality",
          "migration_fit",
          "operability_fit",
          "regional_fit",
          "reliability_fit",
          "review_readiness",
          "technical_fit"
        ],
        "missing_optional_dimensions": [],
        "rules": 1,
        "valid": true,
        "errors": []
      },
      {
        "path": "config\\decision\\policies\\frequent_object_storage.yaml",
        "code": "frequent_object_storage",
        "version": "v1",
        "dimensions": [
          "availability_fit",
          "compliance_fit",
          "cost_fit",
          "data_freshness",
          "evidence_quality",
          "migration_fit",
          "operability_fit",
          "regional_fit",
          "reliability_fit",
          "review_readiness",
          "technical_fit"
        ],
        "missing_optional_dimensions": [],
        "rules": 1,
        "valid": true,
        "errors": []
      },
      {
        "path": "config\\decision\\policies\\general_compute.yaml",
        "code": "general_compute",
        "version": "v1",
        "dimensions": [
          "availability_fit",
          "compliance_fit",
          "cost_fit",
          "data_freshness",
          "evidence_quality",
          "migration_fit",
          "operability_fit",
          "regional_fit",
          "reliability_fit",
          "review_readiness",
          "technical_fit"
        ],
        "missing_optional_dimensions": [],
        "rules": 3,
        "valid": true,
        "errors": []
      },
      {
        "path": "config\\decision\\policies\\high_availability_compute.yaml",
        "code": "high_availability_compute",
        "version": "v1",
        "dimensions": [
          "availability_fit",
          "compliance_fit",
          "cost_fit",
          "data_freshness",
          "evidence_quality",
          "migration_fit",
          "operability_fit",
          "regional_fit",
          "reliability_fit",
          "review_readiness",
          "technical_fit"
        ],
        "missing_optional_dimensions": [],
        "rules": 1,
        "valid": true,
        "errors": []
      }
    ],
    "valid": true
  },
  "scenario_validation": {
    "scenario_files": 5,
    "valid_files": 5,
    "invalid_files": 0,
    "results": [
      {
        "path": "config\\decision\\scenarios\\archive_object_storage.yaml",
        "code": "archive_object_storage_v1",
        "version": "v1",
        "scenario_type": "object_storage_archive",
        "requirements": 2,
        "mandatory_requirements": 2,
        "valid": true,
        "errors": []
      },
      {
        "path": "config\\decision\\scenarios\\cost_sensitive_compute.yaml",
        "code": "cost_sensitive_compute_v1",
        "version": "v1",
        "scenario_type": "cost_sensitive_workload",
        "requirements": 1,
        "mandatory_requirements": 1,
        "valid": true,
        "errors": []
      },
      {
        "path": "config\\decision\\scenarios\\frequent_object_storage.yaml",
        "code": "frequent_object_storage_v1",
        "version": "v1",
        "scenario_type": "object_storage_frequent_access",
        "requirements": 2,
        "mandatory_requirements": 2,
        "valid": true,
        "errors": []
      },
      {
        "path": "config\\decision\\scenarios\\general_compute.yaml",
        "code": "general_compute_v1",
        "version": "v1",
        "scenario_type": "compute_general",
        "requirements": 2,
        "mandatory_requirements": 2,
        "valid": true,
        "errors": []
      },
      {
        "path": "config\\decision\\scenarios\\high_availability_compute.yaml",
        "code": "high_availability_compute_v1",
        "version": "v1",
        "scenario_type": "business_critical_compute",
        "requirements": 2,
        "mandatory_requirements": 2,
        "valid": true,
        "errors": []
      }
    ],
    "valid": true
  },
  "decision_scenarios": 5,
  "scoring_policies": 5,
  "decision_runs": 5,
  "candidate_decision_results": 1230,
  "missing_required_docs": [],
  "errors": [],
  "valid": true
}
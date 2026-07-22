# Unit Normalization

Week 6 standardizes units only for values already extracted from official
evidence-backed product specifications.

## Canonical Units

| Unit | Used for |
| --- | --- |
| `count` | vCPU, connection count, disk count, accelerator count |
| `GiB` | memory and storage capacity |
| `KiB` | minimum billable object size |
| `Gbps` | network or block-storage bandwidth |
| `PPS` | packets per second |
| `IOPS` | block storage operations per second |
| `percent` | durability and availability percentages |
| `day` | minimum storage duration |

## Conversion Policy

- Exact already-normalized units are retained.
- Mbps-like bandwidth values are converted to Gbps.
- 10k PPS, Kpps, and Mpps are converted to PPS.
- TB/TiB-like storage values are converted to GiB using the legacy binary
  convention already used in prior parsers.
- Decimal/binary ambiguity such as `GB` versus `GiB` is retained with
  `conversion_notes` and review impact.
- Unknown units are not guessed; the normalized row is marked for review or
  skipped if it cannot carry exactly one value.

## Week 6 Validation

`scripts/validate_canonical_units.py` checked 10172 normalized specifications
and found 0 canonical unit mismatches.


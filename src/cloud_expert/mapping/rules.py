from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from cloud_expert.database.enums import MappingRelationshipType

RULE_VERSION = "2026.07.week07.v1"


@dataclass(frozen=True)
class FamilyTag:
    category: str
    architecture_hint: str
    accelerator_hint: str
    bare_metal: bool
    burstable: bool


@dataclass(frozen=True)
class TierTag:
    access_class: str
    redundancy_scope: str
    archive_depth: str


def classify_family(code: str, name: str | None = None) -> FamilyTag:
    text = f"{code} {name or ''}".lower()
    compact = code.lower()
    bare_metal = "bare" in text or compact.startswith(("bms", "ebm", "metal"))
    burstable = compact.startswith(("t", "t6", "t7")) or "burstable" in text or "突发" in text
    accelerator = "none"
    category = "unknown"
    architecture = "unknown"

    if any(token in text for token in ["gpu", "gn", "p4", "p5", "g5", "g6", "g7"]):
        category = "gpu"
        accelerator = "gpu"
    elif any(token in text for token in ["inf", "trn", "npu", "ai"]):
        category = "ai_accelerator"
        accelerator = "ai_accelerator"
    elif "hpc" in text or compact.startswith("hpc"):
        category = "hpc"
    elif bare_metal:
        category = "bare_metal"
    elif burstable:
        category = "burstable"
    elif compact.startswith(("c", "hfc")):
        category = "compute_optimized"
    elif compact.startswith(("r", "m", "x", "u", "z")):
        category = "memory_optimized"
    elif compact.startswith(("i", "d", "h", "is", "ir")):
        category = "storage_optimized"
    elif compact.startswith(("s", "g", "m")):
        category = "general_purpose"
    elif compact[:1].isdigit():
        category = "previous_generation"

    if any(token in text for token in ["arm", "graviton", "kunpeng", "yitian", "倚天", "鲲鹏"]):
        architecture = "arm64"
    elif any(token in text for token in ["x86", "intel", "amd"]):
        architecture = "x86_64"

    return FamilyTag(
        category=category,
        architecture_hint=architecture,
        accelerator_hint=accelerator,
        bare_metal=bare_metal,
        burstable=burstable,
    )


def classify_tier(code: str, name: str, access_pattern: str | None) -> TierTag:
    text = f"{code} {name} {access_pattern or ''}".lower()
    redundancy = "unknown"
    if any(token in text for token in ["one zone", "single zone", "single-az", "单az", "单 zone"]):
        redundancy = "single_zone"
    elif any(token in text for token in ["multi", "多az", "标准", "standard"]):
        redundancy = "multi_zone"

    archive_depth = "none"
    access_class = "unknown"
    if "deep" in text or "深度" in text:
        archive_depth = "deep_archive"
        access_class = "deep_archive"
    elif "archive" in text or "归档" in text:
        archive_depth = "archive"
        access_class = "archive"
    elif "intelligent" in text or "智能" in text:
        access_class = "intelligent_tiering"
    elif any(token in text for token in ["infrequent", "ia", "低频", "低频访问"]):
        access_class = "infrequent_access"
    elif any(token in text for token in ["standard", "frequent", "标准", "高频"]):
        access_class = "frequent_access"

    return TierTag(
        access_class=access_class, redundancy_scope=redundancy, archive_depth=archive_depth
    )


def score_cpu_memory(
    source_vcpu: Decimal | None,
    source_memory: Decimal | None,
    target_vcpu: Decimal | None,
    target_memory: Decimal | None,
) -> tuple[Decimal, list[str], list[str]]:
    if source_vcpu is None or source_memory is None or target_vcpu is None or target_memory is None:
        return Decimal("0.2000"), ["missing_required_field"], ["vCPU or memory evidence missing"]
    if source_vcpu == 0 or source_memory == 0:
        return Decimal("0.2000"), ["invalid_source_shape"], ["source vCPU or memory is zero"]

    conditions: list[str] = []
    blockers: list[str] = []
    vcpu_ratio = target_vcpu / source_vcpu
    memory_ratio = target_memory / source_memory
    memory_delta = abs(memory_ratio - Decimal("1"))

    score = Decimal("0.3000")
    if vcpu_ratio == Decimal("1"):
        score += Decimal("0.3000")
    elif Decimal("0.5") <= vcpu_ratio <= Decimal("2"):
        score += Decimal("0.1500")
        conditions.append(f"vcpu_ratio={vcpu_ratio:.4f}")
    else:
        blockers.append(f"vcpu_ratio_outside_threshold={vcpu_ratio:.4f}")

    if memory_delta <= Decimal("0.05"):
        score += Decimal("0.3000")
    elif memory_delta <= Decimal("0.10"):
        score += Decimal("0.2000")
        conditions.append(f"memory_ratio={memory_ratio:.4f}")
    elif Decimal("0.5") <= memory_ratio <= Decimal("2"):
        score += Decimal("0.1000")
        conditions.append(f"memory_ratio_requires_review={memory_ratio:.4f}")
    else:
        blockers.append(f"memory_ratio_outside_threshold={memory_ratio:.4f}")

    return min(score, Decimal("0.9500")), blockers, conditions


def relationship_for_score(score: Decimal, blockers: list[str]) -> str:
    if blockers:
        return MappingRelationshipType.PARTIAL_OVERLAP.value
    if score >= Decimal("0.8500"):
        return MappingRelationshipType.CLOSE_ALTERNATIVE.value
    return MappingRelationshipType.PARTIAL_OVERLAP.value

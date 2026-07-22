# Compute Canonical Model

The compute canonical model covers ECS/EC2 instance specifications extracted
from Huawei Cloud, AWS, and Aliyun official sources.

## Core Field Groups

| Group | Example canonical fields |
| --- | --- |
| CPU | `compute.cpu.vcpu_count`, `compute.cpu.architecture`, `compute.cpu.processor_model` |
| Memory | `compute.memory.capacity_gib` |
| Network | `compute.network.bandwidth_gbps`, `compute.network.packets_per_second` |
| Block storage | `compute.block_storage.bandwidth_gbps`, `compute.block_storage.iops` |
| Local storage | `compute.storage.local_disk_count`, `compute.storage.local_capacity_gib` |
| Accelerator | `compute.accelerator.gpu_count`, `compute.accelerator.gpu_model` |
| System | `compute.system.virtualization_type`, `compute.system.supported_os_family` |

## Week 6 Coverage Notes

- vCPU, memory, and maximum network bandwidth have the broadest cross-provider
  coverage.
- Processor fields are strong for AWS and partial for Aliyun, but limited in
  current Huawei parsed rows.
- Local storage and GPU rows are sparse because many current accepted official
  tables do not expose those values consistently.
- `baseline` and `maximum` network values are separate `value_qualifier`
  values under the same canonical bandwidth field.


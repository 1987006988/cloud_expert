# Compute Canonical Field Matrix

| canonical_field_code | legacy_field_code | canonical_unit | value_qualifier | scope_type | provider_products | notes |
| --- | --- | --- | --- | --- | --- | --- |
| compute.accelerator.gpu_count | gpu.count | count | exact | sku | huawei_cloud/ecs, aws/ec2, aliyun/ecs |  |
| compute.accelerator.gpu_model | gpu.model |  | exact | sku | huawei_cloud/ecs, aws/ec2, aliyun/ecs |  |
| compute.block_storage.bandwidth_gbps | network.ebs_bandwidth_gbps | Gbps | maximum | sku | aws/ec2 |  |
| compute.block_storage.bandwidth_gbps | network.cloud_disk_bandwidth_gbps | Gbps | maximum | sku | aliyun/ecs |  |
| compute.block_storage.iops | storage.cloud_disk_iops | IOPS | maximum | sku | aliyun/ecs |  |
| compute.cpu.architecture | compute.cpu_architecture |  | exact | sku | huawei_cloud/ecs, aws/ec2, aliyun/ecs |  |
| compute.cpu.processor_model | compute.processor_model |  | exact | sku | huawei_cloud/ecs, aws/ec2, aliyun/ecs |  |
| compute.cpu.processor_vendor | compute.processor_vendor |  | exact | sku | huawei_cloud/ecs, aws/ec2, aliyun/ecs |  |
| compute.cpu.vcpu_count | compute.vcpu_count | count | exact | sku | huawei_cloud/ecs, aws/ec2, aliyun/ecs |  |
| compute.instance.family_level | system.instance_family_level |  | exact | product_family | aliyun/ecs |  |
| compute.memory.capacity_gib | compute.memory_gib | GiB | exact | sku | huawei_cloud/ecs, aws/ec2, aliyun/ecs |  |
| compute.network.bandwidth_gbps | network.baseline_bandwidth_gbps | Gbps | baseline | sku | aws/ec2, aliyun/ecs |  |
| compute.network.bandwidth_gbps | network.max_bandwidth_gbps | Gbps | maximum | sku | huawei_cloud/ecs, aws/ec2, aliyun/ecs |  |
| compute.network.connections | network.max_connections | count | maximum | sku | huawei_cloud/ecs, aliyun/ecs |  |
| compute.network.ena_express_supported | network.ena_express_supported |  | supported | sku | aws/ec2 |  |
| compute.network.packets_per_second | network.max_pps | PPS | maximum | sku | huawei_cloud/ecs, aliyun/ecs | Legacy Huawei definitions may use 10k PPS units. |
| compute.storage.local_capacity_gib | storage.local_disk_capacity_gib | GiB | exact | sku | huawei_cloud/ecs, aws/ec2, aliyun/ecs |  |
| compute.storage.local_disk_count | storage.local_disk_count | count | exact | sku | huawei_cloud/ecs, aws/ec2, aliyun/ecs |  |
| compute.storage.local_type | storage.local_disk_type |  | exact | sku | huawei_cloud/ecs, aws/ec2, aliyun/ecs |  |
| compute.system.supported_os_family | system.supported_os_family |  | supported | sku | huawei_cloud/ecs, aws/ec2 |  |
| compute.system.virtualization_type | system.virtualization_type |  | exact | sku | huawei_cloud/ecs |  |

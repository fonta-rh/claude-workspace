<!-- TNF context: repo's role in the TNF ecosystem. Always distributed as DOMAIN-CONTEXT.md. -->

# two-node-toolbox — TNF Context

**Category**: Deployment

**Purpose**: Deployment automation framework for two-node OpenShift clusters in development and testing environments

**TNF Relevance**: **THE go-to tool** for TNF developers/QA. One-stop-shop for cluster lifecycle:
- Automates AWS EC2 hypervisor provisioning via CloudFormation
- Supports "Bring Your Own Server" workflow for existing RHEL 9 hosts
- Wraps dev-scripts and kcli for simplified cluster deployment
- Provides cluster lifecycle management (deploy, clean, shutdown, startup)
- Automated Redfish stonith configuration for fencing topology
- Includes utilities for patching resource-agents on live clusters

**Deployment options**:
- **AWS Hypervisor**: Automated EC2 instance creation and cluster deployment
- **External Host**: Use existing RHEL 9 server with Ansible playbooks
- **dev-scripts method**: Traditional deployment (fencing topology)
- **kcli method**: Modern deployment with simplified VM management (fencing only)

**Key paths**:
- `deploy/` - Main deployment automation directory
  - `deploy/aws-hypervisor/` - AWS CloudFormation and instance lifecycle scripts
  - `deploy/openshift-clusters/` - Ansible playbooks (setup.yml, clean.yml, redeploy.yml)
  - `deploy/openshift-clusters/roles/` - Ansible roles (dev-scripts, kcli, redfish, proxy)
- `helpers/` - Utility scripts:
  - `build-and-patch-resource-agents.yml` - For patching resource-agents on live clusters
  - `collect-tnf-logs.yml` - Log collection playbook
  - `fencing_validator.sh` - Fencing validation script
- `docs/fencing/` - TNF-specific documentation

**Cross-references**:
- **dev-scripts**: TNT wraps dev-scripts; look there for underlying deployment logic
- **resource-agents**: Use `make patch-nodes` to test podman-etcd changes on live clusters

**Commands** (from `deploy/` directory):
```bash
# One-command deployment (AWS)
make deploy fencing-ipi    # Deploy TNF cluster with IPI
make deploy arbiter-ipi    # Deploy TNA cluster with IPI

# Instance lifecycle
make create                # Create EC2 instance
make init                  # Initialize instance
make ssh                   # SSH into hypervisor
make start / make stop     # Start/stop instance
make destroy               # Destroy instance

# Cluster operations
make redeploy-cluster      # Redeploy cluster
make clean                 # Clean cluster
make patch-nodes           # Build and patch resource-agents RPM
make get-tnf-logs          # Collect cluster logs
```

**External host workflow**:
```bash
cd deploy/openshift-clusters/
cp inventory.ini.sample inventory.ini
# Edit inventory.ini with server details
ansible-playbook init-host.yml -i inventory.ini  # One-time setup
ansible-playbook setup.yml -i inventory.ini      # Deploy cluster
```

**Prerequisites**:
- AWS CLI configured (for AWS hypervisor option)
- Ansible, make, jq, rsync, golang
- Pull secret from cloud.redhat.com
- CI_TOKEN for CI builds

## Cluster Access Patterns

**Hypervisor access**: The `[metal_machine]` group in `inventory.ini` defines the hypervisor (AWS EC2 instance). SSH via `make ssh`.

**Cluster VM access**: The `[cluster_vms]` group lists cluster nodes. SSH via ProxyJump through the hypervisor, user=`core`.

**Operational gotchas**:
- Inventory hostnames (e.g. `ostest_master_0`) ARE the virsh domain names on the hypervisor
- Inventory may list nodes in arbitrary order (master_1 before master_0) — never use array index as master number
- RHCOS VMs don't have qemu-guest-agent — use `ssh core@<ip> "sudo systemctl poweroff"` not `virsh shutdown`
- Pacemaker stop sequence takes 4-8 minutes on TNF nodes — use 600s timeout for graceful shutdown

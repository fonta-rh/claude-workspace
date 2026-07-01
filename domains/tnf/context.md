# TNF — Two Nodes with Fencing

TNF is a two-node OpenShift HA topology that replaces etcd's built-in quorum
with Pacemaker/Corosync cluster management. With only two control-plane nodes,
etcd cannot form a majority — so RHEL-HA provides fencing-based split-brain
protection instead.

## Core invariant

Exactly 2 control-plane nodes. Fencing (STONITH) is mandatory — without it,
a network partition leaves both nodes running and data diverges.

## Lifecycle

1. **Install** — MCO installs HA packages (pacemaker, pcs, corosync) and
   prepares directories on both nodes
2. **Bootstrap** — CEO manages etcd normally during cluster bootstrap
3. **Handover** — CEO's TNF controller initializes the Pacemaker cluster,
   configures STONITH, and hands etcd management to the podman-etcd OCF agent
4. **Steady state** — Pacemaker owns the etcd lifecycle; fencing protects
   against split-brain by powering off unresponsive nodes via BMC (Redfish)

## Key components

| Component | Role |
|-----------|------|
| **cluster-etcd-operator** | TNF controller: auth → setup → fencing → handover |
| **machine-config-operator** | OS prep: HA packages, systemd units, directories |
| **podman-etcd (resource-agents)** | OCF agent: runs etcd in podman under Pacemaker |
| **Pacemaker / Corosync** | Cluster membership, failover, resource management |
| **fence agents** | STONITH scripts (fence_redfish for baremetal BMC) |

## Constraints

- OCP 4.20+ only (`DualReplica` FeatureGate)
- Platform: `baremetal` or `none`
- BMC protocol: Redfish only
- etcd runs in **podman**, not CRI-O static pods (unlike standard OCP)

See `docs/architecture.md` for component diagrams and failure scenarios.
See `docs/debugging.md` for cluster inspection commands.

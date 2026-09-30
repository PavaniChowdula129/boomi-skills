---
name: boomi-excel-audit
description: Audits Boomi component usage dynamically (read-only), constructs full reference hierarchy Directed Acyclic Graphs (DAG), performs Package Change Impact Analysis (Latest vs Previous package versions across selected environments), and generates professional, multi-sheet Excel reports. Supports single component audits across 5 scopes, package version comparisons, process routes, process calls, circular references, and potential impact area identification.
---

# Boomi Component Audit & Package Change Impact Generator

## Overview: Two Separate Capabilities

The skill provides two completely independent capabilities:

```
┌────────────────────────────────────────────────────────┐
│                      BOOMI AUDIT                       │
└──────────────────────────┬─────────────────────────────┘
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
   [CAPABILITY 1: COMPONENT]   [CAPABILITY 2: PACKAGE]
       Component ID                 Package ID
             │                           │
    5 Original Audit Modes     Latest vs Previous (V9 vs V8)
             │                           │
  Build / Env Audit Reports    Select Environment(s)
                                         │
                                Audit ONLY Changed Components
                                (NO Unchanged Rows Anywhere)
                                         │
                               Trace Account-Wide Usages
                                         │
                              Change Impact Excel Report
```

---

## Capability 1 — Existing Component Audit (`--component-id`)

> [!IMPORTANT]
> The existing Component Audit functionality supports the original **5 audit modes** and remains **100% unchanged**.

When the user provides a specific Boomi component ID (Profile, Connector Operation, Map, Process, Subprocess, Process Property, Certificate, Cache, etc.):
- Traces references recursively upward to all entrypoint/main processes:
  `Component -> Operation / Map / Cache -> Subprocess -> Process Route / Call -> Main Process`
- Handles Process Call vs Process Route relationships and circular reference detection.
- **5 Supported Modes**:
  1. `BUILD`: Account-level Build scope (ignores environment deployment data).
  2. `ENVIRONMENT`: Single environment scope (`--environment-id "<ENV_ID>"`).
  3. `ALL_ENVIRONMENTS`: Multi-environment discovery creating a worksheet per environment where audit records exist.
  4. `BUILD_AND_ENVIRONMENT`: Generates both Build and Environment workbooks.
  5. `BUILD_AND_ALL_ENVIRONMENTS`: Generates both Build and All-Environments workbooks.
- **Output Files**:
  `Build_Audit_Report_{component_id}_{timestamp}.xlsx`
  `Environment_Audit_Report_{component_id}_{timestamp}.xlsx`

---

## Capability 2 — Package Change Impact Analysis (`--package-id`)

Triggered when the user provides a **Package ID / packaged component details**. The package is **never** treated as an audit entity or root; it serves solely as the comparison source to identify **what changed**.

### Workflow:

1. **Package Version Comparison (Latest vs Previous)**:
   - Identifies the target package and its latest version (e.g., **V9**).
   - Identifies the immediately previous package version (**`latest - 1`**, e.g., **V8**).
   - Diffs component manifests between V9 and V8 to find which components changed.

2. **Environment Selection**:
   - The skill inspects the account and retrieves all available environments.
   - When running interactively, if the user has not specified an environment, the agent presents the available environments and prompts the user:
     > The latest package version is V9 and the previous package version is V8.
     >
     > The following environments are available:
     > 1. DEV
     > 2. QA
     > 3. PROD
     >
     > Would you like to run the V9 vs V8 comparison for:
     > * All available environments
     > * A specific environment
     > * Multiple selected environments
   - If the user explicitly provided an environment in their request (e.g. *"for DEV"* or *"for all environments"*), that choice is used directly.

3. **Pre-Generation Environment Relevance Filtering**:
   - The analysis scans candidate environments to find active deployments of:
     - The changed components
     - The impacted main processes referencing the changed components
     - The primary packaged component
   - Any environment with **zero active deployments / no impact relationship** is completely excluded prior to building the report.
   - Irrelevant environments (e.g. hundreds of account environments where nothing is deployed) are never added as `NOT DEPLOYED` clutter.

4. **Identify and Audit ONLY Changed Components**:
   - Components that are unchanged between the compared versions are **completely excluded**.
   - **NO UNCHANGED ROWS**: The final report contains **zero** rows for unchanged components (no `UNCHANGED`, `NO (Unchanged)`, or `Not Audited (Unchanged)` rows).
   - Only modified, added, or removed components trigger the dependency audit engine.

5. **Trace Usages Across the Account (Potential Impact Areas)**:
   - Traces all upstream parents across the account that reference each changed component, including processes/subprocesses not in the package.
   - Identifies:
     - Referencing Connector Operations & Maps
     - Parent Subprocesses
     - Process Calls & Process Routes
     - Top-level Entrypoint / Main Processes

6. **Clear Separation of Build Version vs Deployed Package Version**:
   - **Component Build Version**: The version of the component/process in the Build repository (e.g. `6`, `7`).
   - **Deployed Package Version**: The version of the package deployed in an environment (e.g. `13.0`, `12.0`, `1.0`).
   - **Deployed Component Build Version**: Derived by inspecting the actual deployed package manifest to determine whether the environment is running the new build version, the prior build version, or an older build version.

---

## Package Change Impact Report Structure

File: [`Change_Impact_Report_{target_id}_{timestamp}.xlsx`](file:///d:/Boomi%20C%20-%20AI/skills/boomi-excel-audit/output)

### Sheet 1: `Impact_Summary`
- **Metadata Block**:
  - Primary Component / Process Name & ID
  - Package Comparison (`Packaged Version Comparison: v13.0 vs v12.0`)
  - Previous Package Version
  - Latest Package Version
  - Analyzed Environment Scope
  - Relevant Environments with Impact
  - Report Generated Timestamp (UTC)
  - Total Manifest Components Examined
  - Changed Components Identified
  - Total Potential Impact Areas Identified (Main Processes)
- **Changed Components Summary Table** (*Contains ONLY changed components*):
  - Changed Component Name
  - Changed Component ID
  - Component Type
  - Folder Path
  - Previous Build Version
  - New Build Version
  - Build Change Identified (`MODIFIED`, `ADDED`, `REMOVED`)
  - Potential Impact Areas Count

### Detailed Impact Worksheets (*Contains ONLY relevant environments and changed components*):
- **Columns (15 Columns)**:
  1. `Environment`
  2. `Changed Component Name`
  3. `Changed Component ID`
  4. `Component Type`
  5. `Previous Build Version`
  6. `New Build Version`
  7. `Build Change Identified`
  8. `Potential Impact Area (Main Process)`
  9. `Process ID`
  10. `Package Component ID`
  11. `Deployed Package Version`
  12. `Deployed Component Build Version`
  13. `Deployment & Impact Status`
  14. `Intermediate Dependency Chain`
  15. `Complete Dependency Hierarchy Path`

- **Identifier Distinctions**:
  - `Changed Component ID` and `Package Component ID` are distinct identifiers:
    - **Changed Component ID**: The ID of the modified Boomi component (e.g. connector action, profile, map).
    - **Package Component ID**: The actual Package ID of the deployed package for the impacted process in that environment (from `DeployedPackage.packageId`). Never infer or derive it from the Process ID or Changed Component ID.
- **Multi-Environment Structure**:
  - Sheet 2: `All_Environments_Impact` (Consolidated table of all relevant environments with active deployments).
  - Sheet 3+: Dedicated sheets per relevant environment (`{env_name}_Impact`) showing the specific deployment details.

---

## CLI & Execution Reference

### Capability 1: Component Audit (Original 5 Modes)
```bash
# 1. Build Scope
python scripts/generate_audit_report.py \
  --component-id "<TARGET_COMPONENT_ID>" \
  --mode BUILD

# 2. Specific Environment Scope
python scripts/generate_audit_report.py \
  --component-id "<TARGET_COMPONENT_ID>" \
  --mode ENVIRONMENT \
  --environment-id "<TARGET_ENVIRONMENT_ID>"

# 3. All Environments Scope
python scripts/generate_audit_report.py \
  --component-id "<TARGET_COMPONENT_ID>" \
  --mode ALL_ENVIRONMENTS

# 4. Build and Specific Environment Scope
python scripts/generate_audit_report.py \
  --component-id "<TARGET_COMPONENT_ID>" \
  --mode BUILD_AND_ENVIRONMENT \
  --environment-id "<TARGET_ENVIRONMENT_ID>"

# 5. Build and All Environments Scope
python scripts/generate_audit_report.py \
  --component-id "<TARGET_COMPONENT_ID>" \
  --mode BUILD_AND_ALL_ENVIRONMENTS
```

### Capability 2: Package Change Impact Analysis

```bash
# Helper: Inspect package versions and list available environments in account
python scripts/generate_audit_report.py \
  --package-id "<PACKAGE_ID>" \
  --inspect-package

# Run for a specific environment
python scripts/generate_audit_report.py \
  --package-id "<PACKAGE_ID>" \
  --environment-id "<ENV_ID>"

# Run for multiple environments (comma-separated)
python scripts/generate_audit_report.py \
  --package-id "<PACKAGE_ID>" \
  --environment-id "<ENV_ID_1>,<ENV_ID_2>"

# Run for all available environments in the account
python scripts/generate_audit_report.py \
  --package-id "<PACKAGE_ID>" \
  --environment-id ALL
```

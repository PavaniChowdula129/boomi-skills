---
name: boomi-excel-audit
description: Audits Boomi component and packaged component usage dynamically (read-only), constructs full reference hierarchy Directed Acyclic Graphs (DAG), compares package/component versions across environments, and generates professional, multi-sheet Excel reports. Supports single components, package IDs, process routes, process calls, circular references, multi-environment comparisons, and consolidated dependency impacts.
---

# Boomi Excel Component & Package Audit Generator

## Purpose
This skill generates professional Excel-based dependency and audit reports for:
1. **Component-Level Audit**: For any Boomi `ComponentId` (Process, Subprocess, Profile, Connector Operation, Cache, Map, etc.), it traces references recursively upward to all roots, capturing invocation mechanisms (Process Call vs Process Route), circular references, and deployment status.
2. **Package-Level Audit**: For any Boomi `PackageId`, it inspects the package manifest, determines all modified and included components (against the prior package version), and audits each modified component's dependencies and process hierarchies in a consolidated report.
3. **Environment/Package Comparison**: For a package or component deployed across environments (e.g. DEV vs PROD, DEV vs QA), it compares package versions and component manifests, highlights modified/added/removed components, and maps the complete dependency impact across all affected processes and subprocesses.

---

## Core Capabilities & Input Modes

### Mode A: Specific Component Audit (`--component-id`)
Traces upstream dependencies from the requested component up to parent subprocesses and main processes:
- `Component -> Operation / Map -> Subprocess -> Process Route -> Main Process`
- Reporting scopes:
  - `BUILD`: Build-oriented Excel report (ignores environment deployment data).
  - `ENVIRONMENT`: Environment-oriented Excel report for a specific `--environment-id`.
  - `ALL_ENVIRONMENTS`: Multi-environment report discovering all environments and creating a worksheet per environment where audit records exist.
  - `BUILD_AND_ENVIRONMENT`: Generates both Build and Environment reports.
  - `BUILD_AND_ALL_ENVIRONMENTS`: Generates both Build and All-Environments reports.

### Mode B: Packaged Component Audit (`--package-id`)
Audits a Boomi Package ID dynamically:
- Queries `PackagedComponent/{packageId}` and `PackagedComponentManifest/{packageId}`.
- Discovers the immediate predecessor package version for the same component to classify manifest components:
  - `MODIFIED`: Component version changed between packages.
  - `ADDED`: New component introduced in the package.
  - `UNCHANGED`: Existing component with matching version.
  - *(If initial package or no version differences, all manifest components are audited as `INCLUDED`)*.
- Audits the dependencies and hierarchy for every modified/included component.
- Consolidates shared parent process/subprocess hierarchies without redundant duplication while preserving individual component relationships.
- Generates a multi-sheet Excel workbook (`Package_Audit_Report_{package_id}_{timestamp}.xlsx`):
  - `Package_Summary`: Metadata, package versions, predecessor details, component counts, impacted process counts, deployment status.
  - `Packaged_Components`: Complete manifest inventory with versions, modification status, and count of dependent main processes.
  - `Package_Dependency_Hierarchy`: Cleanly grouped and merged hierarchy showing where each modified component is used.

### Mode C: Environment & Package Comparison (`--mode COMPARE` / `--source-env-id` & `--target-env-id`)
Compares component versions and dependencies across environments:
- Takes a source environment (`--source-env-id`) and target environment (`--target-env-id`) with `--package-id` or `--component-id`.
- Fetches active deployed packages in both environments and compares manifests:
  - `MODIFIED`: Component exists in both environments but has different versions.
  - `ADDED`: Component exists in source environment but not in comparison environment.
  - `REMOVED`: Component exists in comparison environment but not in source environment.
  - `IDENTICAL`: Component exists in both environments with matching versions.
- Audits dependencies for all differing components (`MODIFIED`, `ADDED`, `REMOVED`).
- Generates a comparison workbook (`Package_Comparison_Report_{primary_comp_id}_{timestamp}.xlsx`):
  - `Comparison_Summary`: Source/target environments, deployed package versions, total differences, metrics.
  - `Component_Differences`: Table of all compared components, their versions in each environment, and change status.
  - `Impacted_Dependencies`: Complete upstream dependency hierarchy for all differing components.

---

## Conversational Interaction & Environment Prompting

When the user asks for an environment comparison or provides a package deployed to an environment without specifying the comparison target:
1. **Do not assume the comparison environment.**
2. Inspect the platform for active deployments of that component/package across environments.
3. Prompt the user with the available choices using the `ask_question` tool (e.g., `DEV vs PROD` or `DEV vs QA`).
4. Once the user selects, execute the comparison using `--source-env-id` and `--target-env-id`.

---

## Empty Report Handling
- **No empty worksheets**: Before creating any worksheet, the skill verifies that actual audit or hierarchy records exist.
- **No dummy data**: Blank sheets with dummy/placeholder values are strictly avoided.
- **Environment filtering**: In `ALL_ENVIRONMENTS` mode, sheets are generated only for environments where actual audit data exists.
- **Clear feedback**: If no audit records exist for the requested scope or component, no empty workbook is created, and an informative notice is printed.

---

## Required Environment Variables
Ensure the following variables are defined in your `.env` or agent environment:
- `BOOMI_API_URL` (e.g., `https://api.boomi.com`)
- `BOOMI_ACCOUNT_ID`
- `BOOMI_USERNAME`
- `BOOMI_API_TOKEN`

---

## CLI & Execution Reference

First, ensure requirements are installed:
```bash
pip install -r scripts/requirements.txt
```

### 1. Component Audit (Existing Behavior Unchanged)
```bash
# Build Scope
python scripts/generate_audit_report.py \
  --component-id "<TARGET_COMPONENT_ID>" \
  --mode BUILD

# Specific Environment Scope
python scripts/generate_audit_report.py \
  --component-id "<TARGET_COMPONENT_ID>" \
  --mode ENVIRONMENT \
  --environment-id "<TARGET_ENVIRONMENT_ID>"

# All Environments Scope
python scripts/generate_audit_report.py \
  --component-id "<TARGET_COMPONENT_ID>" \
  --mode ALL_ENVIRONMENTS
```

### 2. Package-Level Audit
```bash
# Package Audit (Build Scope)
python scripts/generate_audit_report.py \
  --package-id "<PACKAGE_ID>"

# Package Audit with Environment Deployment Context
python scripts/generate_audit_report.py \
  --package-id "<PACKAGE_ID>" \
  --environment-id "<TARGET_ENVIRONMENT_ID>"
```

### 3. Environment Comparison
```bash
python scripts/generate_audit_report.py \
  --mode COMPARE \
  --source-env-id "<SOURCE_ENV_ID>" \
  --target-env-id "<TARGET_ENV_ID>" \
  --package-id "<PACKAGE_ID>" # or --component-id "<COMPONENT_ID>"
```

All generated reports are saved to the `output/` directory with timestamps and clear filenames.

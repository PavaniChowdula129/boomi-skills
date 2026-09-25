---
name: boomi-excel-audit
description: Audits Boomi component usage dynamically (read-only), constructs a full reference hierarchy Directed Acyclic Graph (DAG), and generates a professional, multi-sheet Excel report. Handles all component types, Process Routes, Process Calls, circular references, and multiple branches.
---

# Boomi Excel Component Audit & Report Generator

## Purpose
This skill generates a professional Excel-based dependency and audit report for any given Boomi `ComponentId` within a specific `EnvironmentId`.
It traverses references recursively upward to all roots, accurately capturing invocation mechanisms (e.g. Process Call vs Process Route), circular references, and orphaned components.

## Core Capabilities
- **Dynamic Hierarchy Building**: Discovers full path hierarchies (`Component -> Subprocess -> Process Route -> Main Process`).
- **Circular Reference Detection**: Identifies reference loops and safely halts traversal, marking them in the generated report.
- **Generic Deep Component Resolution**: Recursively traces the Boomi XML DOM structure (Parameters, Connector Actions, Map Configurations) to map generic properties up to their true executing shape/configuration.
- **Environment Context**: Checks active deployment status for the target component and its parents.
- **Strict Excel Generation**: Outputs precisely the requested reports based on the `--mode` parameter:
  - `BUILD`: Generates a single Build-Oriented Excel report (ignores environment deployment data).
  - `ENVIRONMENT`: Generates a single Environment-Oriented Excel report for a specific `--environment-id`.
  - `ALL_ENVIRONMENTS`: Discovers all environments and generates one Environment-Oriented Excel report with a worksheet per environment.
  - `BUILD_AND_ENVIRONMENT`: Generates both the Build and the specified Environment reports.

## Required Environment Variables
Ensure the following variables are defined in your `.env` or agent environment:
- `BOOMI_API_URL` (e.g., `https://api.boomi.com`)
- `BOOMI_ACCOUNT_ID`
- `BOOMI_USERNAME`
- `BOOMI_API_TOKEN`

## CLI & Execution Reference

First, ensure requirements are installed:
```bash
pip install -r scripts/requirements.txt
```

To run the audit directly via the bundled Python script:
```bash
python scripts/generate_audit_report.py \
  --component-id "<TARGET_COMPONENT_ID>" \
  --mode "<BUILD | ENVIRONMENT | ALL_ENVIRONMENTS | BUILD_AND_ENVIRONMENT>" \
  --environment-id "<TARGET_ENVIRONMENT_ID>" # (Optional, depending on mode)
```
The script produces the explicitly requested report(s) (`Build_Audit_Report...`, `Environment_Audit_Report...`, or `Environment_Audit_All_Environments...`) inside the `output/` directory.

#!/usr/bin/env python3
"""
Boomi Component Usage & Hierarchy Auditor
Performs recursive parent traversal, Process Route distinction,
and environment deployment verification via the Boomi Platform API.
"""

import os
import sys
import json
import base64
import argparse
import urllib.request
import urllib.error

def get_auth_header(username: str, token: str) -> str:
    raw = f"BOOMI_TOKEN.{username}:{token}"
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"

def call_boomi_api(endpoint: str, payload: dict, account_id: str, base_url: str, username: str, token: str) -> dict:
    url = f"{base_url.rstrip('/')}/api/rest/v1/{account_id}/{endpoint}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": get_auth_header(username, token),
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"API Call failed [{e.code}] for {endpoint}: {e.read().decode('utf-8')}\n")
        return {}
    except Exception as e:
        sys.stderr.write(f"Connection error calling {endpoint}: {str(e)}\n")
        return {}

def resolve_component_metadata(comp_id: str, account_id: str, base_url: str, username: str, token: str) -> dict:
    query = {
        "QueryFilter": {
            "expression": {
                "operator": "EQUALS",
                "property": "componentId",
                "argument": [comp_id]
            }
        }
    }
    res = call_boomi_api("ComponentMetadata/query", query, account_id, base_url, username, token)
    records = res.get("result", [])
    if records:
        return records[0]
    return {"componentId": comp_id, "name": "Unknown", "type": "Unknown", "folderName": "Unknown"}

def get_deployed_packages(env_id: str, account_id: str, base_url: str, username: str, token: str) -> dict:
    if not env_id:
        return {}
    query = {
        "QueryFilter": {
            "expression": {
                "operator": "and",
                "nestedExpression": [
                    {"operator": "EQUALS", "property": "environmentId", "argument": [env_id]},
                    {"operator": "EQUALS", "property": "active", "argument": ["true"]}
                ]
            }
        }
    }
    res = call_boomi_api("DeployedPackage/query", query, account_id, base_url, username, token)
    deployed = {}
    for pkg in res.get("result", []):
        cid = pkg.get("componentId")
        deployed[cid] = {
            "version": pkg.get("componentVersion"),
            "packageId": pkg.get("packageId"),
            "packageVersion": pkg.get("packageVersion"),
            "name": pkg.get("componentName")
        }
    return deployed

def audit_component(target_id: str, target_env_id: str, account_id: str, base_url: str, username: str, token: str) -> dict:
    # 1. Resolve Target Metadata
    target_meta = resolve_component_metadata(target_id, account_id, base_url, username, token)
    
    # 2. Resolve Environment Deployments
    deployed_pkgs = get_deployed_packages(target_env_id, account_id, base_url, username, token)

    # 3. Recursive Trace of Referencing Components
    main_processes = set()
    subprocess_calls = set()
    process_routes = set()
    routed_subprocesses = set()
    hierarchy_paths = []
    invocation_mechanisms = set()
    immediate_referrers = []
    visited_nodes = set()

    def trace_parents(current_id: str, current_path: str, level: int = 1):
        if current_id in visited_nodes:
            return
        visited_nodes.add(current_id)

        query = {
            "QueryFilter": {
                "expression": {
                    "operator": "EQUALS",
                    "property": "componentId",
                    "argument": [current_id]
                }
            }
        }
        ref_res = call_boomi_api("ComponentReference/query", query, account_id, base_url, username, token)
        refs = ref_res.get("result", [])
        
        if not refs and level == 1:
            return

        for ref_container in refs:
            for ref in ref_container.get("references", []):
                parent_id = ref.get("parentComponentId")
                ref_type = ref.get("type", "DEPENDENT") # DEPENDENT or INDEPENDENT
                
                parent_meta = resolve_component_metadata(parent_id, account_id, base_url, username, token)
                parent_name = parent_meta.get("name", parent_id)
                parent_type = parent_meta.get("type", "component")
                
                if level == 1:
                    immediate_referrers.append(f"{parent_name} [{parent_type}] (ID: {parent_id})")

                # Classification based on component type and link attribute
                if parent_type == "processroute" or ref_type == "INDEPENDENT":
                    process_routes.add(f"{parent_name} [{parent_id}]")
                    invocation_mechanisms.add("Process Route")
                    new_path = f"[Process Route: {parent_name}] -> {current_path}"
                elif parent_type == "process":
                    new_path = f"{parent_name} -> {current_path}"
                else:
                    new_path = f"[{parent_type}: {parent_name}] -> {current_path}"

                # Query higher levels for callers
                higher_query = {
                    "QueryFilter": {
                        "expression": {
                            "operator": "EQUALS",
                            "property": "componentId",
                            "argument": [parent_id]
                        }
                    }
                }
                higher_refs = call_boomi_api("ComponentReference/query", higher_query, account_id, base_url, username, token).get("result", [])
                has_grandparent = any(len(c.get("references", [])) > 0 for c in higher_refs)

                if parent_type == "process":
                    if has_grandparent:
                        if ref_type == "INDEPENDENT":
                            routed_subprocesses.add(f"{parent_name} [{parent_id}]")
                        else:
                            subprocess_calls.add(f"{parent_name} [{parent_id}]")
                            invocation_mechanisms.add("Process Call")
                        trace_parents(parent_id, new_path, level + 1)
                    else:
                        main_processes.add(f"{parent_name} [{parent_id}]")
                        hierarchy_paths.append(new_path)
                elif parent_type == "processroute":
                    trace_parents(parent_id, new_path, level + 1)
                else:
                    if has_grandparent:
                        trace_parents(parent_id, new_path, level + 1)
                    else:
                        main_processes.add(f"{parent_name} [{parent_id}]")
                        hierarchy_paths.append(new_path)

    trace_parents(target_id, target_meta.get("name", target_id))

    # 4. Determine Deployment Status
    deployment_status = "BUILD ONLY (Not Deployed in Target Environment)"
    if target_id in deployed_pkgs:
        d = deployed_pkgs[target_id]
        deployment_status = f"ACTIVE DEPLOYED (v{d['version']}, Package: {d['packageId']})"
    else:
        active_parents = [mp for mp in main_processes if any(pkg_id in mp for pkg_id in deployed_pkgs)]
        if active_parents:
            deployment_status = f"ACTIVE IN ENVIRONMENT via: {', '.join(active_parents)}"

    # 5. Output Single-Record Consolidated Report
    return {
        "audited_component_id": target_id,
        "audited_component_name": target_meta.get("name"),
        "audited_component_type": target_meta.get("type"),
        "audited_component_folder": target_meta.get("folderName"),
        "target_environment": target_env_id if target_env_id else "All / Not Specified",
        "deployment_status": deployment_status,
        "main_processes": sorted(list(main_processes)),
        "process_call_subprocesses": sorted(list(subprocess_calls)),
        "process_routes": sorted(list(process_routes)),
        "process_route_subprocesses": sorted(list(routed_subprocesses)),
        "reference_hierarchy_paths": hierarchy_paths or ["No referencing processes found."],
        "invocation_mechanisms": sorted(list(invocation_mechanisms)) or ["Direct Component Reference"],
        "immediate_referencing_components": sorted(list(immediate_referrers)) or ["None"]
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit Boomi component usage and hierarchy.")
    parser.add_argument("--component-id", required=True, help="Target Component ID to audit")
    parser.add_argument("--environment-id", default=os.getenv("BOOMI_ENVIRONMENT_ID"), help="Target Environment ID")
    parser.add_argument("--account-id", default=os.getenv("BOOMI_ACCOUNT_ID"), help="Boomi Account ID")
    parser.add_argument("--api-url", default=os.getenv("BOOMI_API_URL", "https://api.boomi.com"), help="Boomi Platform API URL")
    parser.add_argument("--username", default=os.getenv("BOOMI_USERNAME"), help="Boomi Username/Email")
    parser.add_argument("--token", default=os.getenv("BOOMI_API_TOKEN"), help="Boomi API Token")

    args = parser.parse_args()

    if not all([args.account_id, args.username, args.token]):
        sys.stderr.write("ERROR: Missing required credentials (account-id, username, token).\n")
        sys.exit(1)

    report = audit_component(args.component_id, args.environment_id, args.account_id, args.api_url, args.username, args.token)
    print(json.dumps(report, indent=2))
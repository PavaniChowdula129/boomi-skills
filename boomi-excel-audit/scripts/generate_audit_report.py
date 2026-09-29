import argparse
import sys
import os
import json
import base64
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

def get_auth_header(username: str, token: str) -> str:
    raw = f"BOOMI_TOKEN.{username}:{token}"
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"

def call_boomi_api(endpoint: str, payload: dict, account_id: str, base_url: str, username: str, token: str) -> dict:
    url = f"{base_url.rstrip('/')}/api/rest/v1/{account_id}/{endpoint}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={
            "Authorization": get_auth_header(username, token),
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        method="POST" if payload is not None else "GET"
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

def call_boomi_query_more(endpoint: str, query_token: str, account_id: str, base_url: str, username: str, token: str) -> dict:
    url = f"{base_url.rstrip('/')}/api/rest/v1/{account_id}/{endpoint}/queryMore"
    req = urllib.request.Request(
        url,
        data=query_token.encode("utf-8"),
        headers={
            "Authorization": get_auth_header(username, token),
            "Content-Type": "text/plain",
            "Accept": "application/json"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        sys.stderr.write(f"API queryMore failed for {endpoint}: {str(e)}\n")
        return {}

def get_all_environments(account_id: str, base_url: str, username: str, token: str) -> list:
    query = {"QueryFilter": {}}
    res = call_boomi_api("Environment/query", query, account_id, base_url, username, token)
    all_results = list(res.get("result", []))
    q_token = res.get("queryToken")
    while q_token:
        more_res = call_boomi_query_more("Environment", q_token, account_id, base_url, username, token)
        items = more_res.get("result", [])
        if not items:
            break
        all_results.extend(items)
        q_token = more_res.get("queryToken")

    envs = []
    for env in all_results:
        envs.append({
            "id": env.get("id"),
            "name": env.get("name", "Unknown Environment")
        })
    return envs

def fetch_component_xml(comp_id: str, account_id: str, base_url: str, username: str, token: str) -> str:
    url = f"{base_url.rstrip('/')}/api/rest/v1/{account_id}/Component/{comp_id}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": get_auth_header(username, token),
            "Accept": "application/xml"
        },
        method="GET"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        sys.stderr.write(f"Failed to fetch XML for {comp_id}: {str(e)}\n")
        return ""

def find_references_in_xml(xml_str: str, child_comp_id: str, required_route_key: str = None) -> list:
    refs = []
    if not xml_str or child_comp_id not in xml_str:
        return refs
        
    try:
        root = ET.fromstring(xml_str)
        parent_map = {c: p for p in root.iter() for c in p}
        
        def get_context(elem):
            curr = elem
            details = []
            shape_context = None
            
            while curr is not None:
                tag = curr.tag
                if tag == "shape":
                    stype = curr.get("shapetype", "unknown")
                    slabel = curr.get("userlabel") or curr.get("name", "Unnamed")
                    shape_context = f"[{stype}] {slabel}"
                elif tag == "parametervalue":
                    name = curr.get("elementToSetName") or curr.get("key") or "Unnamed"
                    details.insert(0, f"Parameter: {name}")
                elif tag == "processparameter":
                    name = curr.get("processproperty", "Unknown")
                    details.insert(0, f"ProcessProperty: {name}")
                elif tag == "profileelement":
                    name = curr.get("elementName", "Unknown")
                    details.insert(0, f"ProfileElement: {name}")
                elif tag == "processProperty":
                    name = curr.get("name", "Unknown Property")
                    details.insert(0, f"[Process Property] {name}")
                elif tag == "dynamicProperty":
                    name = curr.get("name", "Unknown Property")
                    details.insert(0, f"[Dynamic Property] {name}")
                elif tag == "processRoute":
                    details.insert(0, f"[Process Route] {curr.get('name', 'Unnamed')}")
                elif tag == "BusinessRule":
                    details.insert(0, f"[Business Rule] {curr.get('name', 'Unnamed')}")
                elif tag == "mapFunction":
                    details.insert(0, f"MapFunction: {curr.get('name', 'Unnamed')}")
                elif tag == "Component":
                    ctype = curr.get("type", "unknown")
                    cname = curr.get("name", "Unnamed")
                    if not shape_context:
                        shape_context = f"[{ctype}] {cname}"
                
                curr = parent_map.get(curr)
                
            if shape_context:
                if details:
                    return f"{shape_context} -> " + " -> ".join(details)
                return shape_context
            elif details:
                return " -> ".join(details)
            return "(Configuration)"

        found_contexts = set()
        for elem in root.iter():
            is_match = False
            for k, v in elem.attrib.items():
                if v and child_comp_id in v:
                    is_match = True
                    break
            if not is_match and elem.text and child_comp_id in elem.text:
                is_match = True
                
            if is_match:
                if required_route_key is not None and elem.tag == 'processroutecall':
                    param = elem.find('.//routeParameter//staticparameter')
                    if param is not None:
                        shape_route_key = param.get('staticproperty')
                        if shape_route_key != required_route_key:
                            continue
                found_contexts.add(get_context(elem))
                
        valid_contexts = [c for c in found_contexts if c != "(Configuration)"]
        refs = valid_contexts if valid_contexts else (list(found_contexts) if found_contexts else [])
    except Exception as e:
        sys.stderr.write(f"Error parsing XML for shapes: {str(e)}\n")
        
    return refs

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
    all_results = list(res.get("result", []))
    q_token = res.get("queryToken")
    while q_token:
        more_res = call_boomi_query_more("DeployedPackage", q_token, account_id, base_url, username, token)
        items = more_res.get("result", [])
        if not items:
            break
        all_results.extend(items)
        q_token = more_res.get("queryToken")

    deployed = {}
    for pkg in all_results:
        cid = pkg.get("componentId")
        deployed[cid] = {
            "version": pkg.get("componentVersion"),
            "packageId": pkg.get("packageId"),
            "packageVersion": pkg.get("packageVersion"),
            "name": pkg.get("componentName")
        }
    return deployed

def get_deployed_package_for_component(comp_id: str, env_id: str, account_id: str, base_url: str, username: str, token: str) -> dict:
    if not env_id or not comp_id:
        return None
    query = {
        "QueryFilter": {
            "expression": {
                "operator": "and",
                "nestedExpression": [
                    {"operator": "EQUALS", "property": "environmentId", "argument": [env_id]},
                    {"operator": "EQUALS", "property": "componentId", "argument": [comp_id]},
                    {"operator": "EQUALS", "property": "active", "argument": ["true"]}
                ]
            }
        }
    }
    res = call_boomi_api("DeployedPackage/query", query, account_id, base_url, username, token)
    items = res.get("result", [])
    return items[0] if items else None

def get_package_metadata(package_id: str, account_id: str, base_url: str, username: str, token: str) -> dict:
    return call_boomi_api(f"PackagedComponent/{package_id}", None, account_id, base_url, username, token)

def get_package_manifest(package_id: str, account_id: str, base_url: str, username: str, token: str) -> list:
    res = call_boomi_api(f"PackagedComponentManifest/{package_id}", None, account_id, base_url, username, token)
    return res.get("componentInfo", [])

def get_prior_package(primary_comp_id: str, current_pkg_id: str, account_id: str, base_url: str, username: str, token: str) -> dict:
    query = {
        "QueryFilter": {
            "expression": {
                "operator": "EQUALS",
                "property": "componentId",
                "argument": [primary_comp_id]
            }
        }
    }
    res = call_boomi_api("PackagedComponent/query", query, account_id, base_url, username, token)
    all_results = list(res.get("result", []))
    q_token = res.get("queryToken")
    while q_token:
        more_res = call_boomi_query_more("PackagedComponent", q_token, account_id, base_url, username, token)
        items = more_res.get("result", [])
        if not items:
            break
        all_results.extend(items)
        q_token = more_res.get("queryToken")

    pkgs_sorted = sorted(all_results, key=lambda x: x.get("createdDate", ""))
    for i, p in enumerate(pkgs_sorted):
        if p.get("packageId") == current_pkg_id:
            if i > 0:
                return pkgs_sorted[i - 1]
            return None
    return None

class Node:
    def __init__(self, comp_id, name, type_, folder):
        self.comp_id = comp_id
        self.name = name
        self.type = type_
        self.folder = folder
        self.parents = [] # List of tuples: (parent_node, ref_type)
        self.is_circular = False

def build_graph(target_id, account_id, base_url, username, token):
    target_meta = resolve_component_metadata(target_id, account_id, base_url, username, token)
    root_node = Node(target_id, target_meta.get("name", target_id), target_meta.get("type", "Unknown"), target_meta.get("folderName", "Unknown"))
    
    node_cache = {target_id: root_node}
    
    def traverse(current_id, current_node, visited_path):
        if current_id in visited_path:
            current_node.is_circular = True
            return
        
        visited_path.add(current_id)
        
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
        
        parent_map = {}
        for ref_container in refs:
            for ref in ref_container.get("references", []):
                parent_id = ref.get("parentComponentId")
                ref_type = ref.get("type", "DEPENDENT")
                if parent_id not in parent_map:
                    parent_map[parent_id] = set()
                parent_map[parent_id].add(ref_type)
                
        for parent_id, ref_types in parent_map.items():
            p_meta = resolve_component_metadata(parent_id, account_id, base_url, username, token)
            parent_type = p_meta.get("type", "Unknown")
            
            route_key = None
            cache_key = parent_id
            
            if parent_type == "processroute":
                p_xml = fetch_component_xml(parent_id, account_id, base_url, username, token)
                if p_xml:
                    try:
                        xml_body = p_xml[p_xml.find('<bns:object>')+12:p_xml.find('</bns:object>')] if '<bns:object>' in p_xml else p_xml
                        root_pr = ET.fromstring(xml_body)
                        for entry in root_pr.findall('.//processEntry'):
                            if entry.get('processId') == current_id:
                                route_key = entry.get('key')
                                break
                    except Exception:
                        pass
                if route_key:
                    cache_key = f"{parent_id}::route_{route_key}"

            if cache_key not in node_cache:
                p_node = Node(parent_id, p_meta.get("name", parent_id), parent_type, p_meta.get("folderName", "Unknown"))
                if route_key:
                    p_node.route_key = route_key
                node_cache[cache_key] = p_node
                traverse(parent_id, p_node, visited_path.copy())
            else:
                p_node = node_cache[cache_key]
                
            if parent_id in visited_path:
                p_node.is_circular = True
            
            added_edges = False
            p_xml = fetch_component_xml(parent_id, account_id, base_url, username, token)
            required_route_key = getattr(current_node, 'route_key', None)
            shapes = find_references_in_xml(p_xml, current_id, required_route_key=required_route_key)
            for shape_str in shapes:
                edge = (p_node, f"SHAPE:{shape_str}")
                if edge not in current_node.parents:
                    current_node.parents.append(edge)
                    added_edges = True
            
            if not added_edges:
                for r_type in ref_types:
                    edge = (p_node, r_type)
                    if edge not in current_node.parents:
                        current_node.parents.append(edge)
    
    traverse(target_id, root_node, set())
    return root_node, node_cache

def extract_paths(node, current_path, all_paths):
    if node.is_circular:
        all_paths.append(current_path + [{"node": node, "ref_type": "CIRCULAR_LINK"}])
        return
        
    if not node.parents:
        all_paths.append(current_path)
        return
        
    for parent_node, ref_type in node.parents:
        new_path = current_path + [{"node": parent_node, "ref_type": ref_type}]
        extract_paths(parent_node, new_path, all_paths)

def classify_path(path):
    rev_path = path[::-1]
    
    main_process = None
    for p in rev_path:
        if p["node"].type in ("process", "processroute"):
            main_process = p["node"]
            break
            
    hierarchy_str = f"[{rev_path[0]['node'].type}] {rev_path[0]['node'].name}"
    
    intermediate_nodes = []
    
    for i in range(1, len(rev_path)):
        prev = rev_path[i-1]
        prev_node = prev["node"]
        curr = rev_path[i]
        curr_node = curr["node"]
        ref_type = prev.get("ref_type", "DEPENDENT")
        
        if ref_type.startswith("SHAPE:"):
            shape_label = ref_type.replace("SHAPE:", "", 1)
            intermediate_nodes.append(shape_label)
        elif ref_type != "DEPENDENT" and ref_type != "CIRCULAR_LINK":
            intermediate_nodes.append(f"[{prev_node.type}] {prev_node.name} -> {ref_type}")
            
        if prev_node.type == "processroute" or ref_type == "INDEPENDENT":
            rel_str = f"-[Process Route]->"
        elif prev_node.type == "process" and curr_node.type == "process":
            rel_str = f"-[Process Call]->"
        elif ref_type.startswith("SHAPE:"):
            shape_label = ref_type.replace("SHAPE:", "", 1)
            if shape_label.startswith("(") and shape_label.endswith(")"):
                rel_str = f"-{shape_label}->"
            else:
                rel_str = f"-({shape_label})->"
        elif ref_type == "(Configuration)":
            rel_str = f"-{ref_type}->"
        else:
            rel_str = f"-({ref_type})->"
            
        hierarchy_str += f" {rel_str} [{curr_node.type}] {curr_node.name}"
        
    intermediate_chain_str = " -> ".join(intermediate_nodes) if intermediate_nodes else "(Directly Referenced)"
        
    return {
        "main_process": main_process,
        "intermediate_chain": intermediate_chain_str,
        "hierarchy_str": hierarchy_str
    }

def format_hierarchy_sheet(ws_det, deduped_rows):
    header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    
    headers = [
        "Main Process", "Main Process ID", "Main Process Deployment",
        "Intermediate Reference Chain", "Full Hierarchy Path"
    ]
    
    for col_idx, h in enumerate(headers, 1):
        cell = ws_det.cell(row=1, column=col_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        ws_det.column_dimensions[cell.column_letter].width = 35
        
    ws_det.column_dimensions['E'].width = 110 # Hierarchy Path
    
    deduped_rows.sort(key=lambda x: (x[0], x[3], x[4]))
            
    for row_idx, row_data in enumerate(deduped_rows, 2):
        for col_idx, val in enumerate(row_data, 1):
            ws_det.cell(row=row_idx, column=col_idx, value=val)
            
    if len(deduped_rows) > 1:
        current_mp = None
        start_row = 2
        for i in range(2, len(deduped_rows) + 3):
            mp_val = ws_det.cell(row=i, column=1).value if i <= len(deduped_rows) + 1 else None
            if mp_val != current_mp:
                if current_mp is not None and (i - 1) > start_row:
                    ws_det.merge_cells(start_row=start_row, start_column=1, end_row=i-1, end_column=1)
                    ws_det.merge_cells(start_row=start_row, start_column=2, end_row=i-1, end_column=2)
                    ws_det.merge_cells(start_row=start_row, start_column=3, end_row=i-1, end_column=3)
                    ws_det.cell(row=start_row, column=1).alignment = Alignment(vertical='top')
                    ws_det.cell(row=start_row, column=2).alignment = Alignment(vertical='top')
                    ws_det.cell(row=start_row, column=3).alignment = Alignment(vertical='top')
                current_mp = mp_val
                start_row = i

    ws_det.auto_filter.ref = ws_det.dimensions

def format_summary_sheet(ws_sum, target_node, target_env_name, is_build, deduped_rows, is_deployed_in_env):
    header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    
    unique_main_processes = set()
    for row in deduped_rows:
        mp_id = row[1]
        if mp_id:
            unique_main_processes.add(mp_id)

    if is_build:
        deployment_status = "N/A (Build Report)"
    else:
        deployment_status = "DEPLOYED (Active)" if is_deployed_in_env else f"NOT DEPLOYED in {target_env_name}"

    summary_data = [
        ("Audited Component Name", target_node.name),
        ("Component Type", target_node.type),
        ("Report Scope", "Build (All paths)" if is_build else f"Environment: {target_env_name}"),
        ("Total Main Processes Referenced", len(unique_main_processes)),
        ("Audit Timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("Direct Deployment Status", deployment_status)
    ]
    
    for row_idx, (k, v) in enumerate(summary_data, 1):
        cell_k = ws_sum.cell(row=row_idx, column=1, value=k)
        cell_k.fill = header_fill
        cell_k.font = header_font
        ws_sum.cell(row=row_idx, column=2, value=str(v))
        
    ws_sum.column_dimensions['A'].width = 35
    ws_sum.column_dimensions['B'].width = 50

def generate_build_excel(target_node, all_paths, output_file):
    seen_paths = set()
    deduped_rows = []
    
    for path in all_paths:
        if len(path) <= 1:
            continue
        classified = classify_path(path)
        main_proc = classified["main_process"]
        mp_name = main_proc.name if main_proc else "None / Orphaned"
        mp_id = main_proc.comp_id if main_proc else ""
        mp_dep = "N/A (Build Scope)"
        
        intermediate_chain = classified["intermediate_chain"]
        hierarchy = classified["hierarchy_str"]
        
        row_tuple = (mp_name, mp_id, mp_dep, intermediate_chain, hierarchy)
        if row_tuple not in seen_paths:
            seen_paths.add(row_tuple)
            deduped_rows.append(row_tuple)
            
    if not deduped_rows:
        print(f"No Build audit data found for component {target_node.comp_id}. Skipping Build report generation.")
        return False

    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "Audit Summary"
    
    ws_det = wb.create_sheet(title="Hierarchy Details")
    
    format_hierarchy_sheet(ws_det, deduped_rows)
    format_summary_sheet(ws_sum, target_node, "N/A", True, deduped_rows, False)
    
    wb.save(output_file)
    print(f"Build Audit report generated: {output_file}")
    return True

def generate_env_excel(target_node, all_paths, environments, account_id, api_url, username, token, output_file):
    wb = Workbook()
    
    # Remove default sheet
    wb.remove(wb.active)
    
    sheets_created = 0
    
    for env in environments:
        env_id = env["id"]
        env_name = env["name"]
        
        deployed_pkgs = get_deployed_packages(env_id, account_id, api_url, username, token)
        
        seen_paths = set()
        deduped_rows = []
        
        for path in all_paths:
            if len(path) <= 1:
                continue
            classified = classify_path(path)
            main_proc = classified["main_process"]
            mp_name = main_proc.name if main_proc else "None / Orphaned"
            mp_id = main_proc.comp_id if main_proc else ""
            
            mp_dep = "N/A"
            if main_proc and main_proc.comp_id in deployed_pkgs:
                d = deployed_pkgs[main_proc.comp_id]
                mp_dep = f"v{d['version']} (Pkg: {d['packageId']})"
            elif main_proc:
                mp_dep = "NOT DEPLOYED"
                
            # Filter out undeployed processes
            if mp_dep == "NOT DEPLOYED" and mp_name != "None / Orphaned":
                continue
    
            intermediate_chain = classified["intermediate_chain"]
            hierarchy = classified["hierarchy_str"]
            
            row_tuple = (mp_name, mp_id, mp_dep, intermediate_chain, hierarchy)
            if row_tuple not in seen_paths:
                seen_paths.add(row_tuple)
                deduped_rows.append(row_tuple)
                
        # Create worksheets only if actual audit data exists for this environment
        if not deduped_rows:
            continue
            
        base_name = "".join([c if c.isalnum() else "_" for c in env_name])[:20]
        safe_env_name = base_name
        counter = 1
        while f"{safe_env_name}_Summary" in wb.sheetnames or f"{safe_env_name}_Details" in wb.sheetnames:
            suffix = f"_{counter}"
            safe_env_name = f"{base_name[:20 - len(suffix)]}{suffix}"
            counter += 1

        ws_sum = wb.create_sheet(title=f"{safe_env_name}_Summary")
        ws_det = wb.create_sheet(title=f"{safe_env_name}_Details")
        
        is_deployed = target_node.comp_id in deployed_pkgs
                
        format_hierarchy_sheet(ws_det, deduped_rows)
        format_summary_sheet(ws_sum, target_node, env_name, False, deduped_rows, is_deployed)
        sheets_created += 2
        
    if sheets_created == 0:
        if len(environments) == 1:
            print(f"No audit data found for component {target_node.comp_id} in environment '{environments[0]['name']}' ({environments[0]['id']}). Skipping Environment report generation.")
        else:
            print(f"No audit data found for component {target_node.comp_id} across any environment. Skipping Environment report generation.")
        return False

    try:
        wb.save(output_file)
        if os.path.exists(output_file):
            print(f"Environment Audit report generated and verified on disk: {output_file}")
            return True
        else:
            print(f"ERROR: wb.save completed but file not found on disk: {output_file}")
            return False
    except Exception as e:
        print(f"CRITICAL ERROR saving Environment Workbook: {e}")
        return False

def generate_package_excel(package_id, environment_id, account_id, api_url, username, token, output_file):
    print(f"Fetching package metadata for Package ID: {package_id}...")
    pkg = get_package_metadata(package_id, account_id, api_url, username, token)
    if not pkg or not pkg.get("packageId"):
        print(f"ERROR: Package {package_id} not found or could not be retrieved.")
        return False

    primary_id = pkg.get("componentId")
    primary_meta = resolve_component_metadata(primary_id, account_id, api_url, username, token)
    manifest = get_package_manifest(package_id, account_id, api_url, username, token)
    if not manifest:
        print(f"No components found in manifest for package {package_id}. Skipping package audit report generation.")
        return False

    prior_pkg = get_prior_package(primary_id, package_id, account_id, api_url, username, token)
    prior_manifest_map = {}
    if prior_pkg:
        p_items = get_package_manifest(prior_pkg.get("packageId"), account_id, api_url, username, token)
        prior_manifest_map = {item["id"]: item["version"] for item in p_items}

    # Environment deployment context if requested
    deployed_pkgs = {}
    env_name = "Build Scope"
    if environment_id:
        all_e = get_all_environments(account_id, api_url, username, token)
        for e in all_e:
            if e["id"] == environment_id:
                env_name = e["name"]
                break
        deployed_pkgs = get_deployed_packages(environment_id, account_id, api_url, username, token)

    components_info = []
    modified_components = []

    for item in manifest:
        cid = item["id"]
        cver = item["version"]
        cmeta = resolve_component_metadata(cid, account_id, api_url, username, token)
        pver = prior_manifest_map.get(cid)

        if prior_pkg is None:
            status = "INCLUDED (Initial Package)"
            is_mod = True
        elif cid not in prior_manifest_map:
            status = "ADDED"
            is_mod = True
        elif pver != cver:
            status = "MODIFIED"
            is_mod = True
        else:
            status = "UNCHANGED"
            is_mod = False

        c_entry = {
            "comp_id": cid,
            "name": cmeta.get("name", cid),
            "type": cmeta.get("type", "Unknown"),
            "folder": cmeta.get("folderName", "Unknown"),
            "version": cver,
            "prior_version": pver if pver is not None else "N/A",
            "status": status,
            "is_modified": is_mod,
            "dependent_mps": set()
        }
        components_info.append(c_entry)
        if is_mod:
            modified_components.append(c_entry)

    # If no components were strictly flagged as modified/added vs prior package, audit all components as INCLUDED
    if not modified_components:
        for c in components_info:
            c["is_modified"] = True
            c["status"] = "INCLUDED"
            modified_components.append(c)

    print(f"Auditing {len(modified_components)} modified/included component(s) across dependencies...")
    hierarchy_rows = []
    seen_rows = set()
    total_impacted_mps = set()

    for m in modified_components:
        tnode, ncache = build_graph(m['comp_id'], account_id, api_url, username, token)
        paths = []
        extract_paths(tnode, [{"node": tnode}], paths)
        for p in paths:
            classified = classify_path(p)
            mp = classified["main_process"]
            mp_name = mp.name if mp else m['name']
            mp_id = mp.comp_id if mp else m['comp_id']
            m['dependent_mps'].add(mp_id)
            total_impacted_mps.add(mp_id)

            mp_dep = "N/A (Build Scope)"
            if environment_id:
                if mp_id in deployed_pkgs:
                    d = deployed_pkgs[mp_id]
                    mp_dep = f"v{d['version']} (Pkg: {d['packageId']})"
                else:
                    mp_dep = "NOT DEPLOYED"

            chain = classified["intermediate_chain"] if len(p) > 1 else ("(Direct Process / Entrypoint)" if m['type'] == "process" else "(No Parent References)")
            h_str = classified["hierarchy_str"]

            row_tup = (m['name'], m['comp_id'], m['type'], m['status'], mp_name, mp_id, mp_dep, chain, h_str)
            if row_tup not in seen_rows:
                seen_rows.add(row_tup)
                hierarchy_rows.append(row_tup)

    if not hierarchy_rows:
        print(f"No dependency hierarchy found for package {package_id}. Skipping package audit report generation.")
        return False

    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "Package_Summary"
    ws_comps = wb.create_sheet(title="Packaged_Components")
    ws_hier = wb.create_sheet(title="Package_Dependency_Hierarchy")

    header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)

    # 1. Package_Summary Sheet
    summary_data = [
        ("Audited Package ID", package_id),
        ("Package Version", pkg.get("packageVersion", "Unknown")),
        ("Primary Component Name", primary_meta.get("name", primary_id)),
        ("Primary Component ID", primary_id),
        ("Primary Component Type", primary_meta.get("type", "Unknown")),
        ("Package Created Date", pkg.get("createdDate", "Unknown")),
        ("Created By", pkg.get("createdBy", "Unknown")),
        ("Predecessor Package Version", prior_pkg.get("packageVersion") if prior_pkg else "None (Initial Package)"),
        ("Predecessor Package ID", prior_pkg.get("packageId") if prior_pkg else "N/A"),
        ("Total Packaged Components in Manifest", len(components_info)),
        ("Total Modified / Included Components Audited", len(modified_components)),
        ("Total Impacted Main Processes", len(total_impacted_mps)),
        ("Total Hierarchy Paths Discovered", len(hierarchy_rows)),
        ("Report Scope", f"Environment: {env_name}" if environment_id else "Build Scope (All Paths)"),
        ("Direct Deployment Status", ("DEPLOYED (Active)" if primary_id in deployed_pkgs else f"NOT DEPLOYED in {env_name}") if environment_id else "N/A (Build Scope)"),
        ("Audit Timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    ]
    for r_idx, (k, v) in enumerate(summary_data, 1):
        c_k = ws_sum.cell(row=r_idx, column=1, value=k)
        c_k.fill = header_fill
        c_k.font = header_font
        ws_sum.cell(row=r_idx, column=2, value=str(v))
    ws_sum.column_dimensions['A'].width = 42
    ws_sum.column_dimensions['B'].width = 60

    # 2. Packaged_Components Sheet
    comp_headers = [
        "Component Name", "Component ID", "Component Type", "Folder",
        "Package Version", "Predecessor Version", "Modification Status",
        "Dependent Main Processes Count"
    ]
    for c_idx, h in enumerate(comp_headers, 1):
        cell = ws_comps.cell(row=1, column=c_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        ws_comps.column_dimensions[cell.column_letter].width = 30
    ws_comps.column_dimensions['A'].width = 40
    ws_comps.column_dimensions['B'].width = 40

    components_info.sort(key=lambda x: (0 if x["is_modified"] else 1, x["name"]))
    for r_idx, c in enumerate(components_info, 2):
        ws_comps.cell(row=r_idx, column=1, value=c["name"])
        ws_comps.cell(row=r_idx, column=2, value=c["comp_id"])
        ws_comps.cell(row=r_idx, column=3, value=c["type"])
        ws_comps.cell(row=r_idx, column=4, value=c["folder"])
        ws_comps.cell(row=r_idx, column=5, value=c["version"])
        ws_comps.cell(row=r_idx, column=6, value=c["prior_version"])
        ws_comps.cell(row=r_idx, column=7, value=c["status"])
        ws_comps.cell(row=r_idx, column=8, value=len(c["dependent_mps"]))
    ws_comps.auto_filter.ref = ws_comps.dimensions

    # 3. Package_Dependency_Hierarchy Sheet
    hier_headers = [
        "Modified Component", "Component ID", "Component Type", "Modification Status",
        "Main Process", "Main Process ID", "Main Process Deployment",
        "Intermediate Reference Chain", "Full Hierarchy Path"
    ]
    for c_idx, h in enumerate(hier_headers, 1):
        cell = ws_hier.cell(row=1, column=c_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        ws_hier.column_dimensions[cell.column_letter].width = 30
    ws_hier.column_dimensions['A'].width = 35
    ws_hier.column_dimensions['B'].width = 38
    ws_hier.column_dimensions['E'].width = 35
    ws_hier.column_dimensions['F'].width = 38
    ws_hier.column_dimensions['H'].width = 45
    ws_hier.column_dimensions['I'].width = 110

    hierarchy_rows.sort(key=lambda x: (x[0], x[4], x[7], x[8]))
    for r_idx, row in enumerate(hierarchy_rows, 2):
        for c_idx, val in enumerate(row, 1):
            ws_hier.cell(row=r_idx, column=c_idx, value=val)

    if len(hierarchy_rows) > 1:
        # Merge Cols A-D (Modified Component)
        curr_comp = None
        start_r = 2
        for i in range(2, len(hierarchy_rows) + 3):
            val = ws_hier.cell(row=i, column=2).value if i <= len(hierarchy_rows) + 1 else None
            if val != curr_comp:
                if curr_comp is not None and (i - 1) > start_r:
                    for col in range(1, 5):
                        ws_hier.merge_cells(start_row=start_r, start_column=col, end_row=i-1, end_column=col)
                        ws_hier.cell(row=start_r, column=col).alignment = Alignment(vertical='top')
                curr_comp = val
                start_r = i

        # Merge Cols E-G (Main Process) within same component
        curr_mp = None
        start_mp_r = 2
        for i in range(2, len(hierarchy_rows) + 3):
            comp_val = ws_hier.cell(row=i, column=2).value if i <= len(hierarchy_rows) + 1 else None
            mp_val = ws_hier.cell(row=i, column=6).value if i <= len(hierarchy_rows) + 1 else None
            key = (comp_val, mp_val)
            if key != curr_mp:
                if curr_mp is not None and curr_mp[1] is not None and (i - 1) > start_mp_r:
                    for col in range(5, 8):
                        ws_hier.merge_cells(start_row=start_mp_r, start_column=col, end_row=i-1, end_column=col)
                        ws_hier.cell(row=start_mp_r, column=col).alignment = Alignment(vertical='top')
                curr_mp = key
                start_mp_r = i

    ws_hier.auto_filter.ref = ws_hier.dimensions

    try:
        wb.save(output_file)
        if os.path.exists(output_file):
            print(f"Package Audit report generated and verified on disk: {output_file}")
            return True
        else:
            print(f"ERROR: wb.save completed but file not found on disk: {output_file}")
            return False
    except Exception as e:
        print(f"CRITICAL ERROR saving Package Audit Workbook: {e}")
        return False

def generate_comparison_excel(primary_comp_id, package_id, source_env_id, target_env_id, account_id, api_url, username, token, output_file):
    print(f"Resolving environment information for comparison...")
    envs = get_all_environments(account_id, api_url, username, token)
    env_map = {e["id"]: e["name"] for e in envs}
    src_name = env_map.get(source_env_id, f"Env {source_env_id}")
    tgt_name = env_map.get(target_env_id, f"Env {target_env_id}")

    # Determine primary component ID if only package_id is given
    if not primary_comp_id and package_id:
        pkg = get_package_metadata(package_id, account_id, api_url, username, token)
        primary_comp_id = pkg.get("componentId")

    if not primary_comp_id:
        print("ERROR: Could not resolve target component for comparison.")
        return False

    primary_meta = resolve_component_metadata(primary_comp_id, account_id, api_url, username, token)
    print(f"Comparing {src_name} vs {tgt_name} for component: {primary_meta.get('name')} ({primary_comp_id})")

    dep_src = get_deployed_package_for_component(primary_comp_id, source_env_id, account_id, api_url, username, token)
    dep_tgt = get_deployed_package_for_component(primary_comp_id, target_env_id, account_id, api_url, username, token)

    src_pkg_id = dep_src.get("packageId") if dep_src else package_id
    tgt_pkg_id = dep_tgt.get("packageId") if dep_tgt else None

    m_src_items = get_package_manifest(src_pkg_id, account_id, api_url, username, token) if src_pkg_id else []
    m_tgt_items = get_package_manifest(tgt_pkg_id, account_id, api_url, username, token) if tgt_pkg_id else []

    m_src = {item["id"]: item["version"] for item in m_src_items}
    m_tgt = {item["id"]: item["version"] for item in m_tgt_items}

    all_cids = sorted(list(set(m_src.keys()) | set(m_tgt.keys())))
    if not all_cids:
        print(f"No components found in deployed packages for {primary_comp_id} across {src_name} and {tgt_name}.")
        return False

    diff_rows = []
    differing_components = []

    for cid in all_cids:
        v_src = m_src.get(cid)
        v_tgt = m_tgt.get(cid)
        meta = resolve_component_metadata(cid, account_id, api_url, username, token)
        cname = meta.get("name", cid)
        ctype = meta.get("type", "Unknown")
        cfolder = meta.get("folderName", "Unknown")

        if v_src is not None and v_tgt is not None:
            if v_src == v_tgt:
                status = "IDENTICAL"
                impacted = "NO"
            else:
                status = "MODIFIED"
                impacted = "YES"
        elif v_src is not None:
            status = f"ADDED (In {src_name})"
            impacted = "YES"
        else:
            status = f"REMOVED (In {src_name})"
            impacted = "YES"

        entry = {
            "comp_id": cid,
            "name": cname,
            "type": ctype,
            "folder": cfolder,
            "src_version": v_src if v_src is not None else "N/A",
            "tgt_version": v_tgt if v_tgt is not None else "N/A",
            "status": status,
            "impacted": impacted
        }
        diff_rows.append(entry)
        if impacted == "YES":
            differing_components.append(entry)

    print(f"Comparison completed: {len(diff_rows)} components evaluated, {len(differing_components)} differences detected.")

    header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)

    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "Comparison_Summary"
    ws_diff = wb.create_sheet(title="Component_Differences")
    ws_hier = wb.create_sheet(title="Impacted_Dependencies")

    # 1. Comparison_Summary
    summary_data = [
        ("Source Environment", f"{src_name} ({source_env_id})"),
        ("Comparison Environment", f"{tgt_name} ({target_env_id})"),
        ("Primary Component Name", primary_meta.get("name", primary_comp_id)),
        ("Primary Component ID", primary_comp_id),
        ("Primary Component Type", primary_meta.get("type", "Unknown")),
        ("Source Deployed Package", f"v{dep_src.get('packageVersion')} ({dep_src.get('packageId')})" if dep_src else (f"Specified Pkg: {package_id}" if package_id else "NOT DEPLOYED")),
        ("Comparison Deployed Package", f"v{dep_tgt.get('packageVersion')} ({dep_tgt.get('packageId')})" if dep_tgt else "NOT DEPLOYED"),
        ("Total Components in Source Package", len(m_src)),
        ("Total Components in Comparison Package", len(m_tgt)),
        ("Total Component Differences", len(differing_components)),
        ("Modified Components Count", sum(1 for d in diff_rows if d["status"] == "MODIFIED")),
        ("Added Components in Source", sum(1 for d in diff_rows if "ADDED" in d["status"])),
        ("Removed Components in Source", sum(1 for d in diff_rows if "REMOVED" in d["status"])),
        ("Identical Components Count", sum(1 for d in diff_rows if d["status"] == "IDENTICAL")),
        ("Comparison Timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    ]
    for r_idx, (k, v) in enumerate(summary_data, 1):
        c_k = ws_sum.cell(row=r_idx, column=1, value=k)
        c_k.fill = header_fill
        c_k.font = header_font
        ws_sum.cell(row=r_idx, column=2, value=str(v))
    ws_sum.column_dimensions['A'].width = 42
    ws_sum.column_dimensions['B'].width = 60

    # 2. Component_Differences
    diff_headers = [
        "Component Name", "Component ID", "Component Type", "Folder",
        f"{src_name} Version", f"{tgt_name} Version", "Comparison Status", "Impacted in Deployment"
    ]
    for c_idx, h in enumerate(diff_headers, 1):
        cell = ws_diff.cell(row=1, column=c_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        ws_diff.column_dimensions[cell.column_letter].width = 30
    ws_diff.column_dimensions['A'].width = 38
    ws_diff.column_dimensions['B'].width = 38

    diff_rows.sort(key=lambda x: (0 if x["impacted"] == "YES" else 1, x["name"]))
    for r_idx, d in enumerate(diff_rows, 2):
        ws_diff.cell(row=r_idx, column=1, value=d["name"])
        ws_diff.cell(row=r_idx, column=2, value=d["comp_id"])
        ws_diff.cell(row=r_idx, column=3, value=d["type"])
        ws_diff.cell(row=r_idx, column=4, value=d["folder"])
        ws_diff.cell(row=r_idx, column=5, value=d["src_version"])
        ws_diff.cell(row=r_idx, column=6, value=d["tgt_version"])
        ws_diff.cell(row=r_idx, column=7, value=d["status"])
        ws_diff.cell(row=r_idx, column=8, value=d["impacted"])
    ws_diff.auto_filter.ref = ws_diff.dimensions

    # 3. Impacted_Dependencies
    hier_headers = [
        "Differing Component", "Component ID", "Component Type", "Comparison Status",
        "Impacted Main Process", "Main Process ID", "Intermediate Reference Chain", "Full Hierarchy Path"
    ]
    for c_idx, h in enumerate(hier_headers, 1):
        cell = ws_hier.cell(row=1, column=c_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        ws_hier.column_dimensions[cell.column_letter].width = 30
    ws_hier.column_dimensions['A'].width = 35
    ws_hier.column_dimensions['B'].width = 38
    ws_hier.column_dimensions['E'].width = 35
    ws_hier.column_dimensions['F'].width = 38
    ws_hier.column_dimensions['G'].width = 45
    ws_hier.column_dimensions['H'].width = 110

    hier_rows = []
    seen_h = set()
    for d in differing_components:
        tnode, ncache = build_graph(d["comp_id"], account_id, api_url, username, token)
        paths = []
        extract_paths(tnode, [{"node": tnode}], paths)
        for p in paths:
            classified = classify_path(p)
            mp = classified["main_process"]
            mp_name = mp.name if mp else d["name"]
            mp_id = mp.comp_id if mp else d["comp_id"]
            chain = classified["intermediate_chain"] if len(p) > 1 else ("(Direct Process / Entrypoint)" if d["type"] == "process" else "(No Parent References)")
            h_str = classified["hierarchy_str"]

            row_t = (d["name"], d["comp_id"], d["type"], d["status"], mp_name, mp_id, chain, h_str)
            if row_t not in seen_h:
                seen_h.add(row_t)
                hier_rows.append(row_t)

    hier_rows.sort(key=lambda x: (x[0], x[4], x[6], x[7]))
    for r_idx, r in enumerate(hier_rows, 2):
        for c_idx, val in enumerate(r, 1):
            ws_hier.cell(row=r_idx, column=c_idx, value=val)

    if len(hier_rows) > 1:
        # Merge Cols A-D
        curr_comp = None
        start_r = 2
        for i in range(2, len(hier_rows) + 3):
            val = ws_hier.cell(row=i, column=2).value if i <= len(hier_rows) + 1 else None
            if val != curr_comp:
                if curr_comp is not None and (i - 1) > start_r:
                    for col in range(1, 5):
                        ws_hier.merge_cells(start_row=start_r, start_column=col, end_row=i-1, end_column=col)
                        ws_hier.cell(row=start_r, column=col).alignment = Alignment(vertical='top')
                curr_comp = val
                start_r = i

        # Merge Cols E-F
        curr_mp = None
        start_mp_r = 2
        for i in range(2, len(hier_rows) + 3):
            comp_val = ws_hier.cell(row=i, column=2).value if i <= len(hier_rows) + 1 else None
            mp_val = ws_hier.cell(row=i, column=6).value if i <= len(hier_rows) + 1 else None
            key = (comp_val, mp_val)
            if key != curr_mp:
                if curr_mp is not None and curr_mp[1] is not None and (i - 1) > start_mp_r:
                    for col in range(5, 7):
                        ws_hier.merge_cells(start_row=start_mp_r, start_column=col, end_row=i-1, end_column=col)
                        ws_hier.cell(row=start_mp_r, column=col).alignment = Alignment(vertical='top')
                curr_mp = key
                start_mp_r = i

    ws_hier.auto_filter.ref = ws_hier.dimensions

    try:
        wb.save(output_file)
        if os.path.exists(output_file):
            print(f"Comparison Audit report generated and verified on disk: {output_file}")
            return True
        else:
            print(f"ERROR: wb.save completed but file not found on disk: {output_file}")
            return False
    except Exception as e:
        print(f"CRITICAL ERROR saving Comparison Workbook: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Boomi Component and Package Excel Audit Reports")
    parser.add_argument("--component-id", help="Target Component ID to audit")
    parser.add_argument("--package-id", help="Target Boomi Package ID to audit")
    parser.add_argument("--environment-id", help="Target Environment ID (Optional)")
    parser.add_argument("--source-env-id", help="Source Environment ID for comparison")
    parser.add_argument("--target-env-id", "--compare-environment-id", dest="target_env_id", help="Comparison/Target Environment ID")
    parser.add_argument("--mode", choices=["BUILD", "ENVIRONMENT", "ALL_ENVIRONMENTS", "BUILD_AND_ENVIRONMENT", "BUILD_AND_ALL_ENVIRONMENTS", "PACKAGE", "COMPARE"], help="Reporting mode")
    parser.add_argument("--account-id", default=os.getenv("BOOMI_ACCOUNT_ID"), help="Boomi Account ID")
    parser.add_argument("--api-url", default=os.getenv("BOOMI_API_URL", "https://api.boomi.com"), help="Boomi Platform API URL")
    parser.add_argument("--username", default=os.getenv("BOOMI_USERNAME"), help="Boomi Username/Email")
    parser.add_argument("--token", default=os.getenv("BOOMI_API_TOKEN"), help="Boomi API Token")

    args = parser.parse_args()

    if not all([args.account_id, args.username, args.token]):
        sys.stderr.write("ERROR: Missing required credentials (account-id, username, token).\n")
        sys.exit(1)

    if not args.component_id and not args.package_id:
        sys.stderr.write("ERROR: Either --component-id or --package-id must be provided.\n")
        sys.exit(1)

    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(skill_dir, "output")
    os.makedirs(out_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    # Inferred mode handling
    selected_mode = args.mode
    if not selected_mode:
        if args.source_env_id and args.target_env_id:
            selected_mode = "COMPARE"
        elif args.package_id:
            selected_mode = "PACKAGE"
        elif args.environment_id:
            selected_mode = "ENVIRONMENT"
        else:
            selected_mode = "BUILD"

    # 1. Environment Comparison Mode
    if selected_mode == "COMPARE" or args.source_env_id:
        if not args.source_env_id or not args.target_env_id:
            # Check available deployments to guide user selection
            target_cid = args.component_id
            if not target_cid and args.package_id:
                p_meta = get_package_metadata(args.package_id, args.account_id, args.api_url, args.username, args.token)
                target_cid = p_meta.get("componentId")

            all_envs = get_all_environments(args.account_id, args.api_url, args.username, args.token)
            env_map = {e["id"]: e["name"] for e in all_envs}

            dep_list = []
            if target_cid:
                q = {
                    "QueryFilter": {
                        "expression": {
                            "operator": "and",
                            "nestedExpression": [
                                {"operator": "EQUALS", "property": "componentId", "argument": [target_cid]},
                                {"operator": "EQUALS", "property": "active", "argument": ["true"]}
                            ]
                        }
                    }
                }
                res_dep = call_boomi_api("DeployedPackage/query", q, args.account_id, args.api_url, args.username, args.token)
                for d in res_dep.get("result", []):
                    eid = d.get("environmentId")
                    dep_list.append(f"- {env_map.get(eid, eid)} ({eid}) [Pkg v{d.get('packageVersion')}]")

            print("\nERROR: Comparison mode requires both --source-env-id and --target-env-id.")
            if dep_list:
                print("Active deployments found for this component across environments:")
                for item in dep_list:
                    print(f"  {item}")
                print("\nPlease specify the comparison environment using --target-env-id.")
            else:
                print("Please provide --source-env-id and --target-env-id to perform the comparison.")
            sys.exit(1)

        comp_target = args.component_id or args.package_id
        compare_out_file = os.path.join(out_dir, f"Package_Comparison_Report_{comp_target}_{timestamp}.xlsx")
        success = generate_comparison_excel(args.component_id, args.package_id, args.source_env_id, args.target_env_id, args.account_id, args.api_url, args.username, args.token, compare_out_file)
        if not success:
            print(f"No comparison differences or deployment records found between the selected environments.")
        sys.exit(0)

    # 2. Package Audit Mode
    if selected_mode == "PACKAGE" or args.package_id:
        pkg_out_file = os.path.join(out_dir, f"Package_Audit_Report_{args.package_id}_{timestamp}.xlsx")
        success = generate_package_excel(args.package_id, args.environment_id, args.account_id, args.api_url, args.username, args.token, pkg_out_file)
        if not success:
            print(f"No audit data was found for the requested package: {args.package_id}")
        sys.exit(0)

    # 3. Component Audit Mode (Existing Behavior - 100% Unchanged)
    print(f"Starting audit for component: {args.component_id}...")
    target_node, node_cache = build_graph(args.component_id, args.account_id, args.api_url, args.username, args.token)
    
    print(f"Graph built. Total unique components found in hierarchy: {len(node_cache)}")
    
    all_paths = []
    extract_paths(target_node, [{"node": target_node}], all_paths)
    print(f"Total hierarchy paths extracted: {len(all_paths)}")
    
    build_success = False
    env_success = False

    if selected_mode in ["BUILD", "BUILD_AND_ENVIRONMENT", "BUILD_AND_ALL_ENVIRONMENTS"]:
        build_out_file = os.path.join(out_dir, f"Build_Audit_Report_{args.component_id}_{timestamp}.xlsx")
        build_success = generate_build_excel(target_node, all_paths, build_out_file)
    
    if selected_mode in ["ENVIRONMENT", "ALL_ENVIRONMENTS", "BUILD_AND_ENVIRONMENT", "BUILD_AND_ALL_ENVIRONMENTS"]:
        if selected_mode in ["ENVIRONMENT", "BUILD_AND_ENVIRONMENT"] and args.environment_id:
            print(f"Generating isolated environment report for Env ID: {args.environment_id}")
            env_out_file = os.path.join(out_dir, f"Environment_Audit_Report_{args.component_id}_{timestamp}.xlsx")
            env_meta = {"id": args.environment_id, "name": f"Env {args.environment_id}"} # Fallback name
            envs = [env_meta]
            # Attempt to get real name
            all_e = get_all_environments(args.account_id, args.api_url, args.username, args.token)
            for e in all_e:
                if e["id"] == args.environment_id:
                    envs = [e]
                    break
            env_success = generate_env_excel(target_node, all_paths, envs, args.account_id, args.api_url, args.username, args.token, env_out_file)
        else:
            print("Fetching all available environments...")
            env_out_file = os.path.join(out_dir, f"Environment_Audit_All_Environments_{args.component_id}_{timestamp}.xlsx")
            all_e = get_all_environments(args.account_id, args.api_url, args.username, args.token)
            print(f"Found {len(all_e)} environments.")
            env_success = generate_env_excel(target_node, all_paths, all_e, args.account_id, args.api_url, args.username, args.token, env_out_file)

    # Overall empty audit handling
    if selected_mode == "BUILD":
        if not build_success:
            print(f"No audit data was found for the requested component: {args.component_id}")
    elif selected_mode in ["ENVIRONMENT", "ALL_ENVIRONMENTS"]:
        if not env_success:
            print(f"No audit data was found for the requested component: {args.component_id}")
    elif selected_mode in ["BUILD_AND_ENVIRONMENT", "BUILD_AND_ALL_ENVIRONMENTS"]:
        if not build_success and not env_success:
            print(f"No audit data was found for the requested component: {args.component_id}")
        elif build_success and not env_success:
            print(f"Notice: Build report generated, but no audit data was found for component {args.component_id} in the requested environment scope.")
        elif not build_success and env_success:
            print(f"Notice: Environment report generated, but no audit data was found for component {args.component_id} in Build scope.")

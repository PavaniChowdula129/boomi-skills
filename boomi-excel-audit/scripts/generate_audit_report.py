import argparse
import sys
import os
import json
import base64
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

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

def get_latest_package_for_component(comp_id: str, account_id: str, base_url: str, username: str, token: str) -> dict:
    if not comp_id:
        return None
    query = {
        "QueryFilter": {
            "expression": {
                "operator": "EQUALS",
                "property": "componentId",
                "argument": [comp_id]
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
    if not all_results:
        return None
    pkgs_sorted = sorted(all_results, key=lambda x: x.get("createdDate", ""))
    return pkgs_sorted[-1]

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
            if target_node.type == "process":
                main_proc = target_node
                mp_name = target_node.name
                mp_id = target_node.comp_id
                intermediate_chain = "(Direct Process / Entrypoint)"
                hierarchy = f"[{target_node.type}] {target_node.name}"
            else:
                continue
        else:
            classified = classify_path(path)
            main_proc = classified["main_process"]
            mp_name = main_proc.name if main_proc else "None / Orphaned"
            mp_id = main_proc.comp_id if main_proc else ""
            intermediate_chain = classified["intermediate_chain"]
            hierarchy = classified["hierarchy_str"]

        mp_dep = "N/A (Build Scope)"
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
                if target_node.type == "process":
                    main_proc = target_node
                    mp_name = target_node.name
                    mp_id = target_node.comp_id
                    intermediate_chain = "(Direct Process / Entrypoint)"
                    hierarchy = f"[{target_node.type}] {target_node.name}"
                else:
                    continue
            else:
                classified = classify_path(path)
                main_proc = classified["main_process"]
                mp_name = main_proc.name if main_proc else "None / Orphaned"
                mp_id = main_proc.comp_id if main_proc else ""
                intermediate_chain = classified["intermediate_chain"]
                hierarchy = classified["hierarchy_str"]
            
            mp_dep = "N/A"
            if main_proc and main_proc.comp_id in deployed_pkgs:
                d = deployed_pkgs[main_proc.comp_id]
                mp_dep = f"v{d['version']} (Pkg: {d['packageId']})"
            elif main_proc:
                mp_dep = "NOT DEPLOYED"
                
            # Filter out undeployed processes
            if mp_dep == "NOT DEPLOYED" and mp_name != "None / Orphaned":
                continue
    
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

def inspect_package_and_environments(package_id, account_id, api_url, username, token):
    pkg_new = get_package_metadata(package_id, account_id, api_url, username, token)
    if not pkg_new or not pkg_new.get("packageId"):
        print(f"ERROR: Package {package_id} not found.")
        return False

    primary_id = pkg_new.get("componentId")
    primary_meta = resolve_component_metadata(primary_id, account_id, api_url, username, token)
    pkg_prev = get_prior_package(primary_id, package_id, account_id, api_url, username, token)

    all_envs = get_all_environments(account_id, api_url, username, token)
    
    # Active deployments for this primary component
    q = {
        "QueryFilter": {
            "expression": {
                "operator": "and",
                "nestedExpression": [
                    {"operator": "EQUALS", "property": "componentId", "argument": [primary_id]},
                    {"operator": "EQUALS", "property": "active", "argument": ["true"]}
                ]
            }
        }
    }
    res_dep = call_boomi_api("DeployedPackage/query", q, account_id, api_url, username, token)
    dep_map = {}
    for d in res_dep.get("result", []):
        dep_map[d.get("environmentId")] = d.get("packageVersion")

    print("\n========================================================")
    print(f"PACKAGE VERSION COMPARISON: v{pkg_new.get('packageVersion')} vs v{pkg_prev.get('packageVersion') if pkg_prev else 'N/A'}")
    print("========================================================")
    print(f"Latest Package ID   : {package_id} (v{pkg_new.get('packageVersion')})")
    print(f"Previous Package ID : {pkg_prev.get('packageId') if pkg_prev else 'None (Initial)'} (v{pkg_prev.get('packageVersion') if pkg_prev else 'N/A'})")
    print(f"Primary Component   : {primary_meta.get('name')} ({primary_id})")
    print(f"Total Environments  : {len(all_envs)}")
    print("\nAvailable Environments in Account:")
    for idx, e in enumerate(all_envs, 1):
        dep_ver = dep_map.get(e["id"])
        dep_str = f" [Active Deployed Pkg: v{dep_ver}]" if dep_ver else ""
        print(f"  {idx}. {e['name']} (ID: {e['id']}){dep_str}")
    print("========================================================\n")
    return True

def generate_change_impact_excel(primary_comp_id, new_package_id, prev_package_id, environment_ids, source_env_id, target_env_id, account_id, api_url, username, token, output_file):
    print("Initiating Boomi Package Change Impact Analysis...")

    all_envs = get_all_environments(account_id, api_url, username, token)
    env_map = {e["id"]: e for e in all_envs}

    # Case 1: Environment Comparison (DEV vs QA)
    if source_env_id and target_env_id:
        src_name = env_map.get(source_env_id, {}).get("name", f"Env {source_env_id}")
        tgt_name = env_map.get(target_env_id, {}).get("name", f"Env {target_env_id}")

        if not primary_comp_id and new_package_id:
            p_meta = get_package_metadata(new_package_id, account_id, api_url, username, token)
            primary_comp_id = p_meta.get("componentId")

        if not primary_comp_id:
            print("ERROR: Could not resolve target component for environment comparison.")
            return False

        primary_meta = resolve_component_metadata(primary_comp_id, account_id, api_url, username, token)
        print(f"Comparing environments {src_name} vs {tgt_name} for component: {primary_meta.get('name')} ({primary_comp_id})")

        dep_src = get_deployed_package_for_component(primary_comp_id, source_env_id, account_id, api_url, username, token)
        dep_tgt = get_deployed_package_for_component(primary_comp_id, target_env_id, account_id, api_url, username, token)

        if not dep_src and not dep_tgt:
            print(f"No active deployment records found for {primary_meta.get('name')} in {src_name} or {tgt_name}.")
            return False

        src_pkg_id = dep_src.get("packageId") if dep_src else None
        tgt_pkg_id = dep_tgt.get("packageId") if dep_tgt else None

        manifest_new = get_package_manifest(src_pkg_id, account_id, api_url, username, token) if src_pkg_id else []
        manifest_prev = get_package_manifest(tgt_pkg_id, account_id, api_url, username, token) if tgt_pkg_id else []

        new_label = f"{src_name} (Pkg v{dep_src.get('packageVersion', 'N/A') if dep_src else 'Not Deployed'})"
        prev_label = f"{tgt_name} (Pkg v{dep_tgt.get('packageVersion', 'N/A') if dep_tgt else 'Not Deployed'})"
        comparison_source_str = f"Environment Deployment: {src_name} vs {tgt_name}"
        pkg_new_meta = dep_src or {}
        pkg_prev_meta = dep_tgt or {}
        selected_envs = [env_map.get(source_env_id, {"id": source_env_id, "name": src_name}),
                         env_map.get(target_env_id, {"id": target_env_id, "name": tgt_name})]

    # Case 2: Package Version Comparison (Latest vs Previous in Selected Environment(s))
    else:
        if new_package_id:
            pkg_new_meta = get_package_metadata(new_package_id, account_id, api_url, username, token)
        elif primary_comp_id:
            pkg_new_meta = get_latest_package_for_component(primary_comp_id, account_id, api_url, username, token)
            if not pkg_new_meta:
                print(f"ERROR: No packaged components found for component ID: {primary_comp_id}")
                return False
            new_package_id = pkg_new_meta.get("packageId")
        else:
            print("ERROR: Either package ID or component ID must be provided.")
            return False

        if not pkg_new_meta or not pkg_new_meta.get("packageId"):
            print(f"ERROR: Package {new_package_id} could not be retrieved from Boomi API.")
            return False

        primary_comp_id = pkg_new_meta.get("componentId")
        primary_meta = resolve_component_metadata(primary_comp_id, account_id, api_url, username, token)

        if prev_package_id:
            pkg_prev_meta = get_package_metadata(prev_package_id, account_id, api_url, username, token)
        else:
            pkg_prev_meta = get_prior_package(primary_comp_id, new_package_id, account_id, api_url, username, token)

        new_ver_num = pkg_new_meta.get("packageVersion", "Unknown")
        prev_ver_num = pkg_prev_meta.get("packageVersion", "N/A") if pkg_prev_meta else "N/A (Initial)"

        new_label = f"Package v{new_ver_num} ({new_package_id})"
        prev_label = f"Package v{prev_ver_num} ({pkg_prev_meta.get('packageId')})" if pkg_prev_meta else "No Previous Package (Initial)"
        comparison_source_str = f"Packaged Version Comparison: v{new_ver_num} vs v{prev_ver_num}"

        manifest_new = get_package_manifest(new_package_id, account_id, api_url, username, token)
        manifest_prev = get_package_manifest(pkg_prev_meta.get("packageId"), account_id, api_url, username, token) if pkg_prev_meta else []

        # Determine target environments
        if environment_ids:
            if environment_ids.strip().upper() == "ALL":
                selected_envs = all_envs if all_envs else [{"id": None, "name": "Build Scope"}]
            else:
                req_ids = [eid.strip() for eid in environment_ids.split(",") if eid.strip()]
                selected_envs = [env_map.get(eid, {"id": eid, "name": f"Env {eid}"}) for eid in req_ids]
        else:
            # Default to all environments if available, else Build Scope
            selected_envs = all_envs if all_envs else [{"id": None, "name": "Build Scope"}]

    m_new = {item["id"]: item["version"] for item in manifest_new}
    m_prev = {item["id"]: item["version"] for item in manifest_prev}
    all_cids = sorted(list(set(m_new.keys()) | set(m_prev.keys())))

    if not all_cids:
        print("No component manifest data found for comparison.")
        return False

    print(f"Comparing manifests between {new_label} and {prev_label} ({len(all_cids)} components examined)...")

    changed_components = []

    for cid in all_cids:
        v_new = m_new.get(cid)
        v_prev = m_prev.get(cid)
        meta = resolve_component_metadata(cid, account_id, api_url, username, token)
        cname = meta.get("name", cid)
        ctype = meta.get("type", "Unknown")
        cfolder = meta.get("folderName", "Unknown")

        if not m_prev and not pkg_prev_meta:
            status = "ADDED (Initial Package)"
            is_changed = True
        elif v_new is not None and v_prev is not None:
            if v_new == v_prev:
                status = "UNCHANGED"
                is_changed = False
            else:
                status = "MODIFIED"
                is_changed = True
        elif v_new is not None:
            status = "ADDED"
            is_changed = True
        else:
            status = "REMOVED"
            is_changed = True

        if is_changed:
            changed_components.append({
                "comp_id": cid,
                "name": cname,
                "type": ctype,
                "folder": cfolder,
                "version": v_new if v_new is not None else "N/A",
                "prev_version": v_prev if v_prev is not None else "N/A",
                "status": status,
                "impacted_mps": set()
            })

    # Requirement 4 & 14: ONLY changed components are audited. If none, report and exit.
    if not changed_components:
        print(f"\nNo component changes were identified between the latest package version and the previous package version for the selected environment.")
        return True

    print(f"Found {len(changed_components)} changed component(s). Tracing account-wide usages for ONLY changed components...")

    # Run dependency tracing for each changed component across the account
    comp_paths_map = {}
    total_unique_impact_mps = set()
    all_unique_mps = set()

    for c in changed_components:
        cid = c["comp_id"]
        tnode, ncache = build_graph(cid, account_id, api_url, username, token)
        paths = []
        extract_paths(tnode, [{"node": tnode}], paths)
        comp_paths_map[cid] = (c, paths)
        for p in paths:
            if len(p) > 1:
                classified = classify_path(p)
                mp = classified["main_process"]
                if mp and mp.comp_id:
                    all_unique_mps.add(mp.comp_id)
                    c["impacted_mps"].add(mp.comp_id)
                    total_unique_impact_mps.add(mp.comp_id)
            elif len(p) == 1 and c["type"] == "process":
                all_unique_mps.add(c["comp_id"])
                c["impacted_mps"].add(c["comp_id"])
                total_unique_impact_mps.add(c["comp_id"])

    # Query active deployments for all identified main processes, primary component, and changed components
    env_mp_deployment = {}
    deployed_env_ids = set()
    query_targets = list(all_unique_mps | {primary_comp_id} | {c['comp_id'] for c in changed_components})
    for mpid in query_targets:
        q = {
            "QueryFilter": {
                "expression": {
                    "operator": "and",
                    "nestedExpression": [
                        {"operator": "EQUALS", "property": "componentId", "argument": [mpid]},
                        {"operator": "EQUALS", "property": "active", "argument": ["true"]}
                    ]
                }
            }
        }
        res_dep = call_boomi_api("DeployedPackage/query", q, account_id, api_url, username, token)
        for d in res_dep.get("result", []):
            eid = d.get("environmentId")
            env_mp_deployment[(eid, mpid)] = d
            deployed_env_ids.add(eid)

    # Environment Relevance Filtering (BEFORE report generation)
    # An environment is relevant IF AND ONLY IF:
    # 1. A changed component is actively deployed in that environment, OR
    # 2. An impacted main process using the changed component is actively deployed in that environment, OR
    # 3. The primary package component is actively deployed in that environment.
    if selected_envs and selected_envs[0].get("id") is not None:
        relevant_envs = [env for env in selected_envs if env.get("id") in deployed_env_ids]
    else:
        # Build scope (no environment ID specified)
        relevant_envs = selected_envs

    # Cache for package manifests to inspect component build versions inside deployed packages
    manifest_cache = {}
    def get_deployed_manifest(pkg_id):
        if not pkg_id:
            return []
        if pkg_id not in manifest_cache:
            manifest_cache[pkg_id] = get_package_manifest(pkg_id, account_id, api_url, username, token)
        return manifest_cache[pkg_id]

    # Evaluate impact ONLY in the context of relevant environments
    env_rows_map = {}
    all_env_rows = []

    for env in relevant_envs:
        env_id = env.get("id")
        env_name = env.get("name", "Build Scope")

        current_env_rows = []
        seen_keys = set()

        for c in changed_components:
            cid = c["comp_id"]
            _, paths = comp_paths_map[cid]

            has_usage = False
            for p in paths:
                if len(p) > 1:
                    classified = classify_path(p)
                    mp = classified["main_process"]
                    if mp:
                        mp_name = mp.name
                        mp_id = mp.comp_id
                    else:
                        mp_name = "(Unidentified Parent Process)"
                        mp_id = "N/A"
                    chain = classified["intermediate_chain"]
                    h_str = classified["hierarchy_str"]

                    # Determine deployment in this environment:
                    if env_id:
                        d = env_mp_deployment.get((env_id, mp_id))
                        if not d:
                            # Not deployed in this environment -> exclude irrelevant row
                            continue
                        dep_pkg_id = d.get("packageId")
                        dep_pkg_ver = str(d.get("packageVersion", "N/A"))

                        # Inspect manifest of the deployed package to find what build version of cid is deployed
                        pkg_man = get_deployed_manifest(dep_pkg_id)
                        dep_comp_build_ver = None
                        for m_item in pkg_man:
                            if m_item.get("id") == cid:
                                dep_comp_build_ver = m_item.get("version")
                                break

                        dep_build_ver_str = str(dep_comp_build_ver) if dep_comp_build_ver is not None else "N/A"

                        # Determine explicit deployment impact status
                        if dep_build_ver_str != "N/A":
                            if str(dep_build_ver_str) == str(c["version"]):
                                mp_dep_status = f"DEPLOYED (Package v{dep_pkg_ver} contains New Build v{dep_build_ver_str} - Active)"
                            elif str(dep_build_ver_str) == str(c["prev_version"]):
                                mp_dep_status = f"DEPLOYED (Package v{dep_pkg_ver} contains Prior Build v{dep_build_ver_str} - Pending Update)"
                            else:
                                mp_dep_status = f"DEPLOYED (Package v{dep_pkg_ver} contains Build v{dep_build_ver_str})"
                        else:
                            mp_dep_status = f"DEPLOYED (Package v{dep_pkg_ver})"
                    else:
                        dep_pkg_ver = "N/A (Build Scope)"
                        dep_build_ver_str = "N/A (Build Scope)"
                        mp_dep_status = "N/A (Build Scope)"

                    package_component_id = dep_pkg_id if env_id else "N/A (Build Scope)"
                    has_usage = True
                    r_key = (env_name, cid, mp_id, chain, h_str)
                    if r_key not in seen_keys:
                        seen_keys.add(r_key)
                        row_data = {
                            "env_name": env_name,
                            "comp_name": c["name"],
                            "comp_id": c["comp_id"],
                            "comp_type": c["type"],
                            "prev_build_version": c["prev_version"],
                            "new_build_version": c["version"],
                            "change": c["status"],
                            "impact_area": mp_name,
                            "process_id": mp_id,
                            "package_component_id": package_component_id,
                            "deployed_pkg_version": dep_pkg_ver,
                            "deployed_comp_build_version": dep_build_ver_str,
                            "dep_status": mp_dep_status,
                            "chain": chain,
                            "hierarchy": h_str
                        }
                        current_env_rows.append(row_data)
                        all_env_rows.append(row_data)

                elif len(p) == 1 and c["type"] == "process":
                    mp_name = c["name"]
                    mp_id = c["comp_id"]
                    chain = "(Direct Process / Entrypoint)"
                    h_str = f"Process: {c['name']}"

                    if env_id:
                        d = env_mp_deployment.get((env_id, mp_id))
                        if not d:
                            continue
                        dep_pkg_id = d.get("packageId")
                        dep_pkg_ver = str(d.get("packageVersion", "N/A"))

                        pkg_man = get_deployed_manifest(dep_pkg_id)
                        dep_comp_build_ver = None
                        for m_item in pkg_man:
                            if m_item.get("id") == cid:
                                dep_comp_build_ver = m_item.get("version")
                                break

                        dep_build_ver_str = str(dep_comp_build_ver) if dep_comp_build_ver is not None else "N/A"

                        if dep_build_ver_str != "N/A":
                            if str(dep_build_ver_str) == str(c["version"]):
                                mp_dep_status = f"DEPLOYED (Package v{dep_pkg_ver} contains New Build v{dep_build_ver_str} - Active)"
                            elif str(dep_build_ver_str) == str(c["prev_version"]):
                                mp_dep_status = f"DEPLOYED (Package v{dep_pkg_ver} contains Prior Build v{dep_build_ver_str} - Pending Update)"
                            else:
                                mp_dep_status = f"DEPLOYED (Package v{dep_pkg_ver} contains Build v{dep_build_ver_str})"
                        else:
                            mp_dep_status = f"DEPLOYED (Package v{dep_pkg_ver})"
                    else:
                        dep_pkg_id = None
                        dep_pkg_ver = "N/A (Build Scope)"
                        dep_build_ver_str = "N/A (Build Scope)"
                        mp_dep_status = "N/A (Build Scope)"

                    package_component_id = dep_pkg_id if env_id else "N/A (Build Scope)"
                    has_usage = True
                    r_key = (env_name, cid, mp_id, chain, h_str)
                    if r_key not in seen_keys:
                        seen_keys.add(r_key)
                        row_data = {
                            "env_name": env_name,
                            "comp_name": c["name"],
                            "comp_id": c["comp_id"],
                            "comp_type": c["type"],
                            "prev_build_version": c["prev_version"],
                            "new_build_version": c["version"],
                            "change": c["status"],
                            "impact_area": mp_name,
                            "process_id": mp_id,
                            "package_component_id": package_component_id,
                            "deployed_pkg_version": dep_pkg_ver,
                            "deployed_comp_build_version": dep_build_ver_str,
                            "dep_status": mp_dep_status,
                            "chain": chain,
                            "hierarchy": h_str
                        }
                        current_env_rows.append(row_data)
                        all_env_rows.append(row_data)

            if not has_usage:
                d = env_mp_deployment.get((env_id, cid)) if env_id else None
                if d or not env_id:
                    if d:
                        dep_pkg_id = d.get("packageId")
                        dep_pkg_ver = str(d.get("packageVersion", "N/A"))
                        pkg_man = get_deployed_manifest(dep_pkg_id)
                        dep_comp_build_ver = None
                        for m_item in pkg_man:
                            if m_item.get("id") == cid:
                                dep_comp_build_ver = m_item.get("version")
                                break
                        dep_build_ver_str = str(dep_comp_build_ver) if dep_comp_build_ver is not None else "N/A"
                        mp_dep_status = f"DEPLOYED (Package v{dep_pkg_ver} contains Build v{dep_build_ver_str})"
                    else:
                        dep_pkg_id = None
                        dep_pkg_ver = "N/A (Build Scope)"
                        dep_build_ver_str = "N/A (Build Scope)"
                        mp_dep_status = "N/A (Build Scope)"

                    package_component_id = dep_pkg_id if env_id and d else "N/A (Build Scope)"
                    r_key = (env_name, cid, "N/A", "(Unreferenced / Standalone Component)", "(Root Component Only)")
                    if r_key not in seen_keys:
                        seen_keys.add(r_key)
                        row_data = {
                            "env_name": env_name,
                            "comp_name": c["name"],
                            "comp_id": c["comp_id"],
                            "comp_type": c["type"],
                            "prev_build_version": c["prev_version"],
                            "new_build_version": c["version"],
                            "change": c["status"],
                            "impact_area": "(No Identified Usage / Unreferenced)",
                            "process_id": "N/A",
                            "package_component_id": package_component_id,
                            "deployed_pkg_version": dep_pkg_ver,
                            "deployed_comp_build_version": dep_build_ver_str,
                            "dep_status": mp_dep_status,
                            "chain": "(Unreferenced / Standalone Component)",
                            "hierarchy": f"{c['type'].capitalize()}: {c['name']} (No References Found)"
                        }
                        current_env_rows.append(row_data)
                        all_env_rows.append(row_data)

        if current_env_rows:
            env_rows_map[env_name] = current_env_rows

    # Build the Clean Excel Report
    wb = Workbook()
    thin_border = Border(left=Side(style='thin', color='D9D9D9'),
                         right=Side(style='thin', color='D9D9D9'),
                         top=Side(style='thin', color='D9D9D9'),
                         bottom=Side(style='thin', color='D9D9D9'))

    # Sheet 1: Impact_Summary
    ws_sum = wb.active
    ws_sum.title = "Impact_Summary"
    ws_sum.views.sheetView[0].showGridLines = True

    ws_sum.merge_cells("A1:H1")
    ws_sum["A1"] = "Boomi Package Change Impact Audit Report"
    ws_sum["A1"].font = Font(name="Calibri", size=16, bold=True, color="FFFFFF")
    ws_sum["A1"].fill = PatternFill(start_color="002060", end_color="002060", fill_type="solid")
    ws_sum["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws_sum.row_dimensions[1].height = 40

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if selected_envs and selected_envs[0].get("id") is not None:
        total_scanned = len(selected_envs)
        rel_count = len(relevant_envs)
        env_scope_str = f"{total_scanned} Environments Scanned"
        env_relevant_str = f"{rel_count} Relevant Environment(s) with Active Impact ({', '.join([e.get('name') for e in relevant_envs]) if relevant_envs else 'None'})"
    else:
        env_scope_str = "Build Scope"
        env_relevant_str = "Build Scope"

    meta_rows = [
        ("Audit Target / Primary Component:", f"{primary_meta.get('name')} ({primary_comp_id})"),
        ("Package Comparison:", comparison_source_str),
        ("Previous Package Version:", prev_label),
        ("Latest Package Version:", new_label),
        ("Analyzed Environment Scope:", env_scope_str),
        ("Relevant Environments with Impact:", env_relevant_str),
        ("Report Generated (UTC):", now_utc),
        ("Total Manifest Components Examined:", len(all_cids)),
        ("Changed Components Identified:", len(changed_components)),
        ("Total Potential Impact Areas Identified (Main Processes):", len(total_unique_impact_mps))
    ]

    for idx, (label, val) in enumerate(meta_rows, start=3):
        ws_sum.cell(row=idx, column=1, value=label).font = Font(name="Calibri", bold=True, size=11, color="1F4E78")
        ws_sum.merge_cells(start_row=idx, start_column=2, end_row=idx, end_column=8)
        c_val = ws_sum.cell(row=idx, column=2, value=val)
        c_val.font = Font(name="Calibri", size=11)
        c_val.alignment = Alignment(vertical="center")
        ws_sum.row_dimensions[idx].height = 20

    start_tbl = len(meta_rows) + 5
    ws_sum.cell(row=start_tbl, column=1, value="Changed Components Summary").font = Font(name="Calibri", size=13, bold=True, color="002060")
    ws_sum.row_dimensions[start_tbl].height = 25

    sum_headers = [
        "Changed Component Name", "Changed Component ID", "Component Type", "Folder",
        "Previous Build Version", "New Build Version", "Build Change Identified", "Potential Impact Areas Count"
    ]
    h_row = start_tbl + 1
    ws_sum.row_dimensions[h_row].height = 28
    for col_idx, h in enumerate(sum_headers, start=1):
        cell = ws_sum.cell(row=h_row, column=col_idx, value=h)
        cell.font = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
        cell.fill = PatternFill(start_color="002060", end_color="002060", fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    curr_r = h_row + 1
    # ONLY CHANGED COMPONENTS IN THE REPORT!
    for c in changed_components:
        ws_sum.cell(row=curr_r, column=1, value=c["name"]).alignment = Alignment(vertical="center")
        ws_sum.cell(row=curr_r, column=2, value=c["comp_id"]).alignment = Alignment(vertical="center")
        ws_sum.cell(row=curr_r, column=3, value=c["type"]).alignment = Alignment(vertical="center")
        ws_sum.cell(row=curr_r, column=4, value=c["folder"]).alignment = Alignment(vertical="center")
        ws_sum.cell(row=curr_r, column=5, value=c["prev_version"]).alignment = Alignment(horizontal="center", vertical="center")
        ws_sum.cell(row=curr_r, column=6, value=c["version"]).alignment = Alignment(horizontal="center", vertical="center")
        ws_sum.cell(row=curr_r, column=7, value=c["status"]).alignment = Alignment(horizontal="center", vertical="center")
        ws_sum.cell(row=curr_r, column=8, value=len(c["impacted_mps"])).alignment = Alignment(horizontal="center", vertical="center")
        for col in range(1, 9):
            ws_sum.cell(row=curr_r, column=col).border = thin_border
        ws_sum.row_dimensions[curr_r].height = 20
        curr_r += 1

    # Format helper for detailed impact sheets
    def populate_impact_sheet(ws, rows):
        ws.views.sheetView[0].showGridLines = True
        impact_headers = [
            "Environment", "Changed Component Name", "Changed Component ID", "Component Type",
            "Previous Build Version", "New Build Version", "Build Change Identified",
            "Potential Impact Area (Main Process)", "Process ID", "Package Component ID",
            "Deployed Package Version", "Deployed Component Build Version", "Deployment & Impact Status",
            "Intermediate Dependency Chain", "Complete Dependency Hierarchy Path"
        ]
        ws.row_dimensions[1].height = 28
        for col_idx, h in enumerate(impact_headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=h)
            cell.font = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
            cell.fill = PatternFill(start_color="002060", end_color="002060", fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        rows.sort(key=lambda x: (x["env_name"], x["comp_name"], x["impact_area"], x["chain"], x["hierarchy"]))

        for r_idx, r in enumerate(rows, start=2):
            ws.cell(row=r_idx, column=1, value=r["env_name"]).alignment = Alignment(vertical="top")
            ws.cell(row=r_idx, column=2, value=r["comp_name"]).alignment = Alignment(vertical="top")
            ws.cell(row=r_idx, column=3, value=r["comp_id"]).alignment = Alignment(vertical="top")
            ws.cell(row=r_idx, column=4, value=r["comp_type"]).alignment = Alignment(vertical="top")
            ws.cell(row=r_idx, column=5, value=r["prev_build_version"]).alignment = Alignment(horizontal="center", vertical="top")
            ws.cell(row=r_idx, column=6, value=r["new_build_version"]).alignment = Alignment(horizontal="center", vertical="top")
            ws.cell(row=r_idx, column=7, value=r["change"]).alignment = Alignment(horizontal="center", vertical="top")
            ws.cell(row=r_idx, column=8, value=r["impact_area"]).alignment = Alignment(vertical="top")
            ws.cell(row=r_idx, column=9, value=r["process_id"]).alignment = Alignment(vertical="top")
            ws.cell(row=r_idx, column=10, value=r["package_component_id"]).alignment = Alignment(vertical="top")
            ws.cell(row=r_idx, column=11, value=r["deployed_pkg_version"]).alignment = Alignment(horizontal="center", vertical="top")
            ws.cell(row=r_idx, column=12, value=r["deployed_comp_build_version"]).alignment = Alignment(horizontal="center", vertical="top")
            ws.cell(row=r_idx, column=13, value=r["dep_status"]).alignment = Alignment(vertical="top")
            ws.cell(row=r_idx, column=14, value=r["chain"]).alignment = Alignment(vertical="top")
            ws.cell(row=r_idx, column=15, value=r["hierarchy"]).alignment = Alignment(vertical="top")
            for col in range(1, 16):
                ws.cell(row=r_idx, column=col).border = thin_border
            ws.row_dimensions[r_idx].height = 22

        # Cell merging for readability
        if len(rows) > 1:
            # Merge Cols A-G (Component info)
            curr_comp = None
            start_r = 2
            for i in range(2, len(rows) + 3):
                val = (ws.cell(row=i, column=1).value, ws.cell(row=i, column=3).value) if i <= len(rows) + 1 else None
                if val != curr_comp:
                    if curr_comp is not None and (i - 1) > start_r:
                        for col in range(1, 8):
                            ws.merge_cells(start_row=start_r, start_column=col, end_row=i-1, end_column=col)
                            ws.cell(row=start_r, column=col).alignment = Alignment(vertical='top')
                    curr_comp = val
                    start_r = i

            # Merge Cols H-M (Process & deployment info)
            curr_mp = None
            start_mp_r = 2
            for i in range(2, len(rows) + 3):
                comp_key = (ws.cell(row=i, column=1).value, ws.cell(row=i, column=3).value) if i <= len(rows) + 1 else None
                mp_val = ws.cell(row=i, column=9).value if i <= len(rows) + 1 else None
                key = (comp_key, mp_val)
                if key != curr_mp:
                    if curr_mp is not None and curr_mp[1] not in [None, "N/A"] and (i - 1) > start_mp_r:
                        for col in range(8, 14):
                            ws.merge_cells(start_row=start_mp_r, start_column=col, end_row=i-1, end_column=col)
                            ws.cell(row=start_mp_r, column=col).alignment = Alignment(vertical='top')
                    curr_mp = key
                    start_mp_r = i

        ws.auto_filter.ref = ws.dimensions

    # Detailed Sheets:
    existing_sheet_titles = set(wb.sheetnames)

    def get_unique_sheet_title(base_name):
        cleaned = "".join([ch if ch.isalnum() else "_" for ch in base_name])[:22]
        cand = f"{cleaned}_Impact"[:31]
        idx = 2
        while cand in existing_sheet_titles:
            cand = f"{cleaned[:25]}_{idx}"[:31]
            idx += 1
        existing_sheet_titles.add(cand)
        return cand

    if len(relevant_envs) == 0:
        ws_none = wb.create_sheet(title="No_Active_Deployments")
        ws_none.views.sheetView[0].showGridLines = True
        ws_none.merge_cells("A1:H1")
        ws_none["A1"] = "No Active Deployments in Analyzed Environment(s)"
        ws_none["A1"].font = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
        ws_none["A1"].fill = PatternFill(start_color="002060", end_color="002060", fill_type="solid")
        ws_none["A1"].alignment = Alignment(horizontal="center", vertical="center")
        ws_none.row_dimensions[1].height = 35
        ws_none["A3"] = "None of the changed components or their impacted processes are actively deployed in the analyzed environment(s)."
        ws_none["A3"].font = Font(name="Calibri", size=11, italic=True)
    elif len(relevant_envs) == 1:
        # Single relevant environment: Clean detailed sheet
        env_single = relevant_envs[0]
        ws_det = wb.create_sheet(title=get_unique_sheet_title(env_single.get("name", "Impact")))
        populate_impact_sheet(ws_det, all_env_rows)
    else:
        # Multiple relevant environments: Consolidated sheet + per-environment sheets
        ws_all = wb.create_sheet(title="All_Environments_Impact")
        existing_sheet_titles.add("All_Environments_Impact")
        populate_impact_sheet(ws_all, all_env_rows)

        # Per-environment sheet for each relevant environment
        for env in relevant_envs:
            e_name = env.get("name", "Unknown")
            e_rows = env_rows_map.get(e_name, [])
            if e_rows:
                ws_env = wb.create_sheet(title=get_unique_sheet_title(e_name))
                populate_impact_sheet(ws_env, e_rows)

    # Auto-adjust column widths across all sheets
    for ws in wb.worksheets:
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                if ws == ws_sum and cell.row == 1:
                    continue
                if cell.value:
                    lines = str(cell.value).split("\n")
                    for l in lines:
                        if len(l) > max_len:
                            max_len = len(l)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)
            if ws.column_dimensions[col_letter].width > 60:
                ws.column_dimensions[col_letter].width = 60

    try:
        wb.save(output_file)
        if os.path.exists(output_file):
            print(f"\nPackage Change Impact report generated successfully: {output_file}")
            return True
        else:
            print(f"ERROR: File was not created on disk: {output_file}")
            return False
    except Exception as e:
        print(f"ERROR saving Change Impact Report workbook: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Boomi Component and Change Impact Excel Audit Reports")
    parser.add_argument("--component-id", help="Target Component ID to audit")
    parser.add_argument("--package-id", help="Target Boomi Package ID for change impact comparison")
    parser.add_argument("--prev-package-id", help="Optional prior Boomi Package ID to compare against (defaults to immediately previous version)")
    parser.add_argument("--environment-id", help="Target Environment ID (Single, comma-separated IDs, or 'ALL')")
    parser.add_argument("--inspect-package", action="store_true", help="Inspect package version details and list available environments")
    parser.add_argument("--source-env-id", help="Source Environment ID for environment change comparison")
    parser.add_argument("--target-env-id", "--compare-environment-id", dest="target_env_id", help="Comparison/Target Environment ID")
    parser.add_argument("--mode", choices=["BUILD", "ENVIRONMENT", "ALL_ENVIRONMENTS", "BUILD_AND_ENVIRONMENT", "BUILD_AND_ALL_ENVIRONMENTS", "CHANGE_IMPACT", "PACKAGE", "COMPARE"], help="Reporting mode")
    parser.add_argument("--account-id", default=os.getenv("BOOMI_ACCOUNT_ID"), help="Boomi Account ID")
    parser.add_argument("--api-url", default=os.getenv("BOOMI_API_URL", "https://api.boomi.com"), help="Boomi Platform API URL")
    parser.add_argument("--username", default=os.getenv("BOOMI_USERNAME"), help="Boomi Username/Email")
    parser.add_argument("--token", default=os.getenv("BOOMI_API_TOKEN"), help="Boomi API Token")

    args = parser.parse_args()

    if not all([args.account_id, args.username, args.token]):
        sys.stderr.write("ERROR: Missing required credentials (account-id, username, token).\n")
        sys.exit(1)

    if not args.component_id and not args.package_id and not (args.source_env_id and args.target_env_id):
        sys.stderr.write("ERROR: Either --component-id, --package-id, or environment comparison flags must be provided.\n")
        sys.exit(1)

    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(skill_dir, "output")
    os.makedirs(out_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    # Inspect package option
    if args.inspect_package and args.package_id:
        success = inspect_package_and_environments(args.package_id, args.account_id, args.api_url, args.username, args.token)
        sys.exit(0 if success else 1)

    # Inferred mode handling (map legacy PACKAGE/COMPARE to CHANGE_IMPACT)
    if args.mode in ["PACKAGE", "COMPARE"]:
        selected_mode = "CHANGE_IMPACT"
    else:
        selected_mode = args.mode

    if not selected_mode:
        if args.source_env_id and args.target_env_id:
            selected_mode = "CHANGE_IMPACT"
        elif args.package_id:
            selected_mode = "CHANGE_IMPACT"
        elif args.environment_id:
            selected_mode = "ENVIRONMENT"
        else:
            selected_mode = "BUILD"

    # Capability 2: Package Change Impact Analysis (Package or Environment comparison)
    if selected_mode == "CHANGE_IMPACT" or args.package_id or (args.source_env_id and args.target_env_id):
        if args.source_env_id and not args.target_env_id:
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

            print("\nERROR: Environment comparison requires both --source-env-id and --target-env-id.")
            if dep_list:
                print("Active deployments found for this component across environments:")
                for item in dep_list:
                    print(f"  {item}")
                print("\nPlease specify the comparison environment using --target-env-id.")
            else:
                print("Please provide --source-env-id and --target-env-id to perform the comparison.")
            sys.exit(1)

        target_file_id = args.package_id or args.component_id or f"{args.source_env_id}_vs_{args.target_env_id}"
        ci_out_file = os.path.join(out_dir, f"Change_Impact_Report_{target_file_id}_{timestamp}.xlsx")
        success = generate_change_impact_excel(
            args.component_id,
            args.package_id,
            args.prev_package_id,
            args.environment_id,
            args.source_env_id,
            args.target_env_id,
            args.account_id,
            args.api_url,
            args.username,
            args.token,
            ci_out_file
        )
        sys.exit(0 if success else 1)

    # Capability 1: Component Audit Mode (Existing Behavior - 100% UNCHANGED)
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
            env_ids = [e.strip() for e in args.environment_id.split(",") if e.strip()]
            print(f"Generating isolated environment report for Env ID(s): {', '.join(env_ids)}")
            env_out_file = os.path.join(out_dir, f"Environment_Audit_Report_{args.component_id}_{timestamp}.xlsx")
            all_e = get_all_environments(args.account_id, args.api_url, args.username, args.token)
            env_map = {e["id"]: e for e in all_e}
            envs = [env_map[eid] for eid in env_ids if eid in env_map]
            if not envs:
                envs = [{"id": eid, "name": f"Env {eid}"} for eid in env_ids]
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

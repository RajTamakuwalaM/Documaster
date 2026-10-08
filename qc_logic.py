import os
import concurrent.futures
import csv
import re
import datetime
import utils

# ==========================================
# 1. SUPER FAST PARALLEL SCANNING (OPTIMIZED)
# ==========================================

def scan_folder_worker(folder_path, category):
    """
    Worker function to scan a single folder using ultra-fast os.scandir.
    Calculates Count AND Size in a single pass without extra stat() calls.
    """
    files_set = set()
    total_size = 0
    count = 0
    
    if not folder_path or not os.path.isdir(folder_path):
        return category, files_set, 0, 0

    dirs_to_scan = [folder_path]
    
    while dirs_to_scan:
        current_dir = dirs_to_scan.pop()
        try:
            with os.scandir(current_dir) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        dirs_to_scan.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        files_set.add(entry.name)
                        count += 1                        
                        total_size += entry.stat(follow_symlinks=False).st_size
        except Exception as e:
            # --- NEW FIX: Log error instead of 'pass' ---
            error_msg = f"[{datetime.datetime.now()}] Scan Error: {str(e)}\n"
            try:
                with open("QC_Error_Log.txt", "a", encoding="utf-8") as err_log:
                    err_log.write(error_msg)
            except: pass
                
    return category, files_set, count, total_size

def scan_recursive_stats(path):
    """
    Scans a directory recursively to get TOTAL Count and Size using os.scandir.
    Matches TreeSize logic incredibly fast.
    """
    count = 0
    size = 0
    
    if not path or not os.path.isdir(path):
        return 0, 0

    dirs_to_scan = [path]
    
    while dirs_to_scan:
        current_dir = dirs_to_scan.pop()
        try:
            with os.scandir(current_dir) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        dirs_to_scan.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        count += 1
                        size += entry.stat(follow_symlinks=False).st_size
        except Exception:
            pass
            
    return count, size

def run_fast_qc_scan(folders, case_root=None):
    """
    Parallel Scan:
    1. Scans Natives, Text, Images (for categorization)
    2. Scans ENTIRE Root (for accurate Total Stats like TreeSize)
    """
    results = {
        "natives": (set(), 0, 0),
        "text": (set(), 0, 0),
        "images": (set(), 0, 0),
        "total_stats": (0, 0) # (Total Files, Total Bytes)
    }
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {}
        
        # Task 1: Categorized Scans
        if folders.get("natives"):
            futures[executor.submit(scan_folder_worker, folders["natives"], "natives")] = "cat"
        if folders.get("text"):
            futures[executor.submit(scan_folder_worker, folders["text"], "text")] = "cat"
        if folders.get("images"):
            futures[executor.submit(scan_folder_worker, folders["images"], "images")] = "cat"
            
        # Task 2: Full Root Scan (For Accurate TreeSize match)
        if case_root:
             futures[executor.submit(scan_recursive_stats, case_root)] = "root"

        # Collect Results
        for future in concurrent.futures.as_completed(futures):
            try:
                type_scan = futures[future]
                if type_scan == "cat":
                    cat, f_set, cnt, sz = future.result()
                    results[cat] = (f_set, cnt, sz)
                elif type_scan == "root":
                    results["total_stats"] = future.result()
            except Exception as e:
                print(f"Scan Error: {e}")
            
    return results

def scan_specific_folder(folder_path):
    return scan_folder_worker(folder_path, "generic")[1:]

# ==========================================
# 2. DAT & STRUCTURE PARSING
# ==========================================
def detect_export_folders(root):
    """
    Scans deeper to find 'NATIVES', 'TEXT', 'IMAGES' folders
    even if they are inside subfolders like 'WebexExport001'.
    """
    found = {"images": None, "natives": None, "text": None}
    
    if not os.path.exists(root): return found    
    
    root_depth = root.count(os.sep)
    
    for r, dirs, _ in os.walk(root):
        current_depth = r.count(os.sep)
        if current_depth - root_depth > 3:
            continue
            
        for d in dirs:
            d_lower = d.lower()
            full_path = os.path.join(r, d)
                        
            if "native" in d_lower and not found["natives"]:
                found["natives"] = full_path
            elif ("text" in d_lower or "ocr" in d_lower) and not found["text"]:
                found["text"] = full_path
            elif "image" in d_lower and not found["images"]:
                found["images"] = full_path
                
        if found["natives"] and found["text"] and found["images"]:
            break
            
    return found

def collect_expected_from_dat(root, headers, data, native_field=None, text_field=None, act_nat_set=None, act_txt_set=None):
    exp_natives = set()
    exp_texts = set()
    missing_natives = set()
    missing_texts = set()

    nat_col = -1
    txt_col = -1
        
    if native_field and native_field in headers:
        nat_col = headers.index(native_field)
        
    if text_field and text_field in headers:
        txt_col = headers.index(text_field)
    
    for row in data:
        # Collect Native & Fast Memory Check
        if nat_col > -1 and nat_col < len(row):
            val = row[nat_col].strip()
            if val: 
                fname = os.path.basename(val)
                exp_natives.add(fname)
                
                # --- NAYA FIX: Native Memory Check ---
                if act_nat_set: # Agar set mein files hain tabhi check karo
                    if fname not in act_nat_set: missing_natives.add(fname)
                else:
                    full_path = utils.resolve_relative_path(root, val)
                    if not full_path or not os.path.exists(full_path): missing_natives.add(fname)
            
        # Collect Text & Fast Memory Check
        if txt_col > -1 and txt_col < len(row):
            val = row[txt_col].strip()
            if val: 
                fname = os.path.basename(val)
                exp_texts.add(fname)
                
                if act_txt_set is not None:
                    if fname not in act_txt_set: missing_texts.add(fname)
                else:
                    full_path = utils.resolve_relative_path(root, val)
                    if not full_path or not os.path.exists(full_path): missing_texts.add(fname)

    return exp_natives, exp_texts, missing_natives, missing_texts


def collect_expected_images(root, opt_index, act_img_set=None):
    exp_images = set()
    missing_images = set()
    if not opt_index: return exp_images, missing_images

    for _, pages in opt_index.items():
        for img in pages:
            path = None
            if isinstance(img, str): path = img
            elif isinstance(img, dict): 
                path = img.get("path") or img.get("image")
            
            if path: 
                fname = os.path.basename(path)
                exp_images.add(fname)
                
                if act_img_set is not None:
                    if fname not in act_img_set: missing_images.add(fname)
                else:
                    # Fallback to direct disk check
                    full_path = utils.resolve_relative_path(root, path)
                    if not full_path or not os.path.exists(full_path):
                        missing_images.add(fname)
            
    return exp_images, missing_images

# ==========================================
# 3. TEXT CONTENT SCANNING (DEEP SCAN)
# ==========================================
def scan_text_chunk(files_chunk, search_terms, check_empty):
    """
    Worker function to process a batch (chunk) of files in a separate thread.
    """
    # Trackers: Numbers ki jagah ab hum 'Lists' use karenge Bates ID store karne ke liye
    chunk_stats = {"empty_docs": [], "errors": 0, "scanned_in_chunk": len(files_chunk), "terms_found": {}}
    for term in search_terms: 
        chunk_stats["terms_found"][term] = []
    
    import os
    for path in files_chunk:
        try:
            size = os.path.getsize(path)
            # E-discovery mein text file ka naam hi uska DocID/Bates hota hai (e.g. ABC001.txt -> ABC001)
            bates_id = os.path.splitext(os.path.basename(path))[0]
            
            # 1. Check literal 0-byte file
            if size == 0:
                if check_empty:
                    chunk_stats["empty_docs"].append(bates_id)
                continue
            
            # ⚡ RAM & DISK SAVER: Read max 5MB
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(5242880)
            
            clean_content = content.replace('\ufeff', '').strip()
            
            if check_empty and not clean_content:
                chunk_stats["empty_docs"].append(bates_id)
                continue
            
            # 2. Search Keywords
            if search_terms:
                content_lower = content.lower() 
                for term in search_terms:
                    if term in content_lower:
                        chunk_stats["terms_found"][term].append(bates_id)
        except:
            chunk_stats["errors"] += 1
            
    return chunk_stats

import os
import concurrent.futures

def scan_text_content_deep(text_folder, search_terms, check_empty, progress_callback):
    """
    Multi-threaded Deep Text QC for massive datasets (1M+ files).
    """
    all_files = []
    dirs_to_scan = [text_folder]

    while dirs_to_scan:
        current_dir = dirs_to_scan.pop()
        try:
            with os.scandir(current_dir) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        dirs_to_scan.append(entry.path)
                    elif entry.is_file(follow_symlinks=False) and entry.name.lower().endswith('.txt'):
                        all_files.append(entry.path)
        except:
            pass

    total_files = len(all_files)
    lower_terms = [t.lower() for t in search_terms] if search_terms else []
    
    stats = {
        "scanned": total_files, 
        "empty_docs": [],
        "terms_found": {term: [] for term in lower_terms}
    }

    if total_files == 0: return stats

    chunk_size = 1000
    file_chunks = [all_files[i:i + chunk_size] for i in range(0, total_files, chunk_size)]
    completed_files = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(scan_text_chunk, chunk, lower_terms, check_empty) for chunk in file_chunks]
        
        for future in concurrent.futures.as_completed(futures):
            chunk_result = future.result()
            completed_files += chunk_result.get("scanned_in_chunk", 0)
            
            # ⚡ Aggregating all lists of Bates numbers
            stats["empty_docs"].extend(chunk_result.get("empty_docs", []))
            for t in lower_terms:
                stats["terms_found"][t].extend(chunk_result["terms_found"].get(t, []))

            if progress_callback: progress_callback(completed_files)

    if progress_callback: progress_callback(total_files) 
    return stats

# ==========================================
# 4. REPORTING
# ==========================================
def write_missing_list(f, title, items):
    if not items: return
    f.write(f"\n{title}\n" + "-"*len(title) + "\n")
    for x in items[:100]: f.write(f"- {x}\n")
    if len(items) > 100: f.write(f"... and {len(items)-100} more ...\n")

def generate_qc_report(ctx, report_path):
    """
    Generates the formatted text report.
    FIXED: Converts 'Location' path slashes (/) to backslashes (\\).
    """
    root = ctx["root"]
    disk_stats = ctx["disk_stats"]
    
    # --- FIX: Force Windows Backslashes ---
    root_display = str(root).replace("/", "\\")
    # --------------------------------------
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("***HOSTING INTERNAL ONLY - DO NOT RESOLVE TICKET UNTIL SECONDARY QC IS COMPLETE ***\n\n")
        f.write("The following production is ready for an internal secondary QC.\n")
        f.write("Please QC at your earliest convenience.\n\n---\n\n")

        f.write("DETAILS:\n")
        f.write(f"• Production Volume: {os.path.basename(root)}\n")
        f.write(f"• Bates Range: {ctx.get('bates_range', 'N/A')}\n")
        
        doc_count = ctx.get("total_docs", len(ctx['exp_natives'])) 
        f.write(f"• Documents: {doc_count}\n")

        f.write(f"• Natives: {len(ctx['exp_natives'])}\n")
        f.write(f"• Images: {len(ctx['exp_images'])}\n")
        
        # --- USE FIXED PATH HERE ---
        f.write(f"• Location: {root_display}\n")
        # ---------------------------
        
        f.write(f"• TreeSize (Bytes): {disk_stats[1]:,}\n") 
        f.write(f"• Total File Count: {disk_stats[0]:,}\n")
        f.write("• ZIP Container password: N/A\n\n")
        
        f.write("• Checklist:\n• Is the Page Count and Data Export Field updated?: Yes\n\n---\n\n")

        f.write("QC VALIDATION SUMMARY:\n")

        f.write(f"• Native files in DAT: {len(ctx['exp_natives'])}\n")
        f.write(f"• Native files on disk: {ctx['native_disk_count']}\n")
        f.write(f"• Missing natives: {len(ctx['missing_natives'])}\n")
        f.write(f"• Extra natives: {len(ctx['extra_natives'])}\n\n")

        f.write(f"• Text files in DAT: {len(ctx['exp_texts'])}\n")
        f.write(f"• Text files on disk: {ctx['text_disk_count']}\n")
        f.write(f"• Missing text files: {len(ctx['missing_texts'])}\n")
        f.write(f"• Extra text files: {len(ctx['extra_texts'])}\n\n")

        f.write(f"• Images referenced in OPT: {len(ctx['exp_images'])}\n")
        f.write(f"• Images on disk: {ctx['image_disk_count']}\n")
        f.write(f"• Missing images: {len(ctx['missing_images'])}\n")
        f.write(f"• Extra images: {len(ctx['extra_images'])}\n\n")

        if "text_qc" in ctx:
            ts = ctx["text_qc"]
            f.write("TEXT CONTENT QC (Deep Scan):\n")
            f.write(f"• Empty text files: {ts.get('empty', 0)}\n")
            f.write(f"• Withheld for Privilege: {ts.get('withheld', 0)}\n")
            f.write(f"• Cannot be Rendered: {ts.get('cannot_render', 0)}\n")            
            f.write(f"• Contains 'Redact': {ts.get('redact', 0)}\n\n")
        else:
            f.write("TEXT CONTENT QC: Not Run (Run 'Deep Text QC' to populate)\n\n")

        f.write("---\n")

        write_missing_list(f, "MISSING NATIVES", sorted(list(ctx['missing_natives'])))
        write_missing_list(f, "MISSING TEXT", sorted(list(ctx['missing_texts'])))
        write_missing_list(f, "MISSING IMAGES", sorted(list(ctx['missing_images'])))
        
        f.write("\nGenerated by: DocuMaster\n")

    return report_path

# ==========================================
# 5. BATES GAP & OVERLAP ANALYSIS
# ==========================================
def parse_bates(val):
    if not val: return None
    match = re.match(r"^(.*?)(\d+)$", val.strip())
    if match:
        prefix = match.group(1)
        number = int(match.group(2))
        length = len(match.group(2)) 
        return (prefix, number, length)
    return None

def find_bates_issues(data, beg_col_idx, end_col_idx):
    gaps = []
    overlaps = []
    valid_rows = []
    
    for r_idx, row in enumerate(data):
        if beg_col_idx >= len(row): continue
        
        beg_val = row[beg_col_idx].strip()
        end_val = row[end_col_idx].strip() if end_col_idx < len(row) else beg_val

        if not end_val: end_val = beg_val

        p_beg = parse_bates(beg_val)
        p_end = parse_bates(end_val)
        
        if p_beg and p_end:
            if p_beg[0] != p_end[0]:
                continue
            
            valid_rows.append({
                "pfx": p_beg[0],
                "beg": p_beg[1],
                "end": p_end[1],
                "pad": p_beg[2],
                "raw_beg": beg_val,
                "raw_end": end_val,
                "row": r_idx + 1
            })

    valid_rows.sort(key=lambda x: (x["pfx"], x["beg"]))

    if not valid_rows: return [], []
    
    for i in range(len(valid_rows) - 1):
        curr = valid_rows[i]
        next_doc = valid_rows[i+1]

        if curr["pfx"] == next_doc["pfx"]:
            expected_next = curr["end"] + 1
            
            if next_doc["beg"] > expected_next:
                gap_start = expected_next
                gap_end = next_doc["beg"] - 1
                                
                pfx = curr["pfx"]
                pad = curr["pad"]
                s_str = f"{pfx}{str(gap_start).zfill(pad)}"
                e_str = f"{pfx}{str(gap_end).zfill(pad)}"
                
                count = (gap_end - gap_start) + 1
                
                if count == 1:
                    gaps.append(f"Missing: {s_str} (after Row {curr['row']})")
                else:
                    gaps.append(f"Gap: {s_str} - {e_str} ({count} pages missing after Row {curr['row']})")

            elif next_doc["beg"] <= curr["end"]:
                overlaps.append(
                    f"Row {next_doc['row']} ({next_doc['raw_beg']}) starts inside Row {curr['row']} range ({curr['raw_beg']} - {curr['raw_end']})"
                )

    return gaps, overlaps

def generate_bates_report(gaps, overlaps, save_path):
    with open(save_path, "w", encoding="utf-8") as f:
        f.write("BATES SEQUENCE ANALYSIS REPORT\n")
        f.write("==============================\n\n")
        
        f.write(f"Total Gaps: {len(gaps)}\n")
        f.write(f"Total Overlaps: {len(overlaps)}\n\n")
        
        f.write("---\n")
        f.write("GAPS detected:\n")
        if not gaps: f.write("None\n")
        else:
            for g in gaps: f.write(f"{g}\n")
            
        f.write("\n---\n")
        f.write("OVERLAPS detected:\n")
        if not overlaps: f.write("None\n")
        else:
            for o in overlaps: f.write(f"{o}\n")
                
    return save_path

# ==========================================
# 6. POST-EXPORT DELIVERY QC (EXCEL REPORT)
# ==========================================
def analyze_date_format(values):
    if not values: return "N/A"

    formats = {
        r"^\d{4}-\d{2}-\d{2}$": "YYYY-MM-DD",
        r"^\d{1,2}/\d{1,2}/\d{4}$": "MM/DD/YYYY", 
        r"^\d{4}/\d{2}/\d{2}$": "YYYY/MM/DD",
        r"^\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}$": "MM/DD/YYYY HH:MM",
        r"^\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}:\d{2}$": "MM/DD/YYYY HH:MM:SS",
        r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}$": "YYYY-MM-DD HH:MM:SS",
        r"^\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s+[APap][Mm]$": "MM/DD/YYYY hh:mm tt",        
        r"^\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}:\d{2}\s+[APap][Mm]$": "MM/DD/YYYY hh:mm:ss tt",
        r"^\d{1,2}:\d{2}:\d{2}$": "HH:MM:SS",         
        r"^\d{1,2}:\d{2}$": "HH:MM",        
        r"^\d{1,2}:\d{2}\s+[APap][Mm]$": "hh:mm tt",        
        r"^\d{1,2}:\d{2}:\d{2}\s+[APap][Mm]$": "hh:mm:ss tt"
    }
    
    detected = {}
    sample = [v for v in values if v.strip()][:50]
    if not sample: return "Empty"

    for val in sample:
        val = val.strip()
        matched = False
        for pattern, fmt in formats.items():
            if re.match(pattern, val):
                detected[fmt] = detected.get(fmt, 0) + 1
                matched = True
                break
        if not matched:
            detected["Unknown/Mixed"] = detected.get("Unknown/Mixed", 0) + 1
            
    if not detected: return "Unknown"
    return max(detected, key=detected.get)

def validate_export_delivery(headers, data, opt_index, qc_cache, field_map, root_dir, save_excel_path):
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        return "Error: 'openpyxl' library is missing. Install it using: pip install openpyxl"

    if not headers or not data:
        return "Error: No data to analyze."

    # --- EXACT MAPPING FROM USER ---
    id_field = field_map.get("id")
    nat_field = field_map.get("native")
    txt_field = field_map.get("text")

    id_col = headers.index(id_field) if id_field in headers else 0
    native_col = headers.index(nat_field) if nat_field in headers else -1
    text_col = headers.index(txt_field) if txt_field in headers else -1

    # Accurate Missing Lists directly from Background Cache
    missing_natives_cache = qc_cache.get("missing_natives", set())
    missing_texts_cache = qc_cache.get("missing_texts", set())
    missing_images_cache = qc_cache.get("missing_images", set())
    
    act_img_set = qc_cache["scan_results"].get("images", (set(), 0, 0))[0]

    wb = openpyxl.Workbook()
    ws_summary = wb.active
    ws_summary.title = "Summary & Fields"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
    
    col_data = {h: {"pop": 0, "emp": 0, "samples": []} for h in headers}
    
    missing_natives = []
    missing_texts = []
    total_rows = len(data)
    
    for r_idx, row in enumerate(data):
        docid = row[id_col] if len(row) > id_col else f"Row {r_idx+1}"
        
        for i, val in enumerate(row):
            if i < len(headers):
                h = headers[i]
                val = str(val).strip()
                if val:
                    col_data[h]["pop"] += 1
                    if len(col_data[h]["samples"]) < 50:
                        col_data[h]["samples"].append(val)
                else:
                    col_data[h]["emp"] += 1
        
        if native_col > -1 and native_col < len(row):
            val = row[native_col].strip()
            if val:
                fname = os.path.basename(val)
                # FIX: Check if it's ACTUALLY missing from the accurate cache
                if fname in missing_natives_cache:
                    missing_natives.append((docid, val))

        if text_col > -1 and text_col < len(row):
            val = row[text_col].strip()
            if val:
                fname = os.path.basename(val)
                if fname in missing_texts_cache:
                    missing_texts.append((docid, val))

    field_stats = []
    for h in headers:
        fmt = "Text/General"
        h_lower = h.lower()
        if any(x in h_lower for x in ["date", "time", "created", "modified", "sent", "received"]):
            fmt = analyze_date_format(col_data[h]["samples"])
        field_stats.append((h, col_data[h]["pop"], col_data[h]["emp"], fmt))

    image_stats = {"total": 0, "missing": 0}
    missing_images = []
    
    if opt_index:
        for docid, pages in opt_index.items():
            for page in pages:
                path = page["path"] if isinstance(page, dict) else page
                image_stats["total"] += 1
                if path:
                    fname = os.path.basename(path)
                    if fname in missing_images_cache or (act_img_set and fname not in act_img_set):
                        image_stats["missing"] += 1
                        missing_images.append((docid, path))
    
    ws_summary["A1"] = "EXPORT DELIVERY QC REPORT"
    ws_summary["A1"].font = Font(size=14, bold=True)
    
    ws_summary["A3"] = "Source Data:"
    ws_summary["B3"] = "Current Grid Data"
    ws_summary["A4"] = "Total Documents:"
    ws_summary["B4"] = total_rows

    ws_summary["D3"] = "FILE VALIDATION CHECK"
    ws_summary["D3"].font = Font(bold=True)
    
    ws_summary["D4"] = "Native Files Missing:"
    ws_summary["E4"] = len(missing_natives)
    ws_summary["E4"].font = Font(color="FF0000" if missing_natives else "008000", bold=True)
    
    ws_summary["D5"] = "Text Files Missing:"
    ws_summary["E5"] = len(missing_texts)
    ws_summary["E5"].font = Font(color="FF0000" if missing_texts else "008000", bold=True)
    
    ws_summary["D6"] = "Image Files Checked:"
    ws_summary["E6"] = image_stats["total"]
    
    ws_summary["D7"] = "Image Files Missing:"
    ws_summary["E7"] = image_stats["missing"]
    ws_summary["E7"].font = Font(color="FF0000" if image_stats["missing"] else "008000", bold=True)

    row_idx = 10
    headers_list = ["Field Name", "Populated Count", "Empty Count", "Detected Format"]
    
    for col_idx, h_name in enumerate(headers_list, 1):
        cell = ws_summary.cell(row=row_idx, column=col_idx, value=h_name)
        cell.font = header_font
        cell.fill = header_fill
    
    for stat in field_stats:
        row_idx += 1
        ws_summary.cell(row=row_idx, column=1, value=stat[0])
        ws_summary.cell(row=row_idx, column=2, value=stat[1])
        ws_summary.cell(row=row_idx, column=3, value=stat[2])
        ws_summary.cell(row=row_idx, column=4, value=stat[3])

    for col in ws_summary.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length: max_length = len(str(cell.value))
            except: pass
        ws_summary.column_dimensions[column].width = max_length + 2

    if missing_natives or missing_texts or missing_images:
        ws_err = wb.create_sheet("Missing Files Detail")

        err_headers = ["DocID", "File Type", "Missing Path"]
        for col_idx, h_name in enumerate(err_headers, 1):
            cell = ws_err.cell(row=1, column=col_idx, value=h_name)
            cell.font = header_font
            cell.fill = header_fill
        
        MAX_ERRORS = 50000 
        current_errors = 0
        
        for docid, path in missing_natives:
            if current_errors >= MAX_ERRORS: break
            ws_err.append([docid, "Native", path])
            current_errors += 1
            
        for docid, path in missing_texts:
            if current_errors >= MAX_ERRORS: break
            ws_err.append([docid, "Text", path])
            current_errors += 1
            
        for docid, path in missing_images:
            if current_errors >= MAX_ERRORS: break
            ws_err.append([docid, "Image", path])
            current_errors += 1
            
        if current_errors >= MAX_ERRORS:
            ws_err.append(["WARNING", "LIMIT REACHED", f"Only showing first {MAX_ERRORS} missing files to prevent Excel crash."])
            
        ws_err.column_dimensions["A"].width = 20
        ws_err.column_dimensions["B"].width = 15
        ws_err.column_dimensions["C"].width = 80

    try:
        wb.save(save_excel_path)
        return True
    except Exception as e:
        return f"Error saving Excel: {str(e)}"
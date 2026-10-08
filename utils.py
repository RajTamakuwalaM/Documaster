import os
import sys
import re
import subprocess

# =====================
# CONSTANTS & CONFIG
# =====================
FORMAT_MAP = {
    "yyyy": "%Y", "yy": "%y",
    "MM": "%m",   "M": "%m",
    "dd": "%d",   "d": "%d",
    "HH": "%H",   "H": "%H",   # 24-hour
    "hh": "%I",   "h": "%I",   # 12-hour
    "mm": "%M",   "m": "%M",   # Minute
    "ss": "%S",   "s": "%S",   # Second
    "tt": "%p",   "t": "%p",   # AM/PM
    "fff": "%f",               # Milliseconds
}

# =====================
# FILE & SYSTEM OPS
# =====================
def open_native_file(path: str):
    """Opens a file using the OS default application."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform.startswith("darwin"):
            subprocess.call(["open", path])
        else:
            subprocess.call(["xdg-open", path])
    except Exception as e:
        print(f"Error opening file: {e}")

def detect_case_root(dat_path: str) -> str:
    """Detect case root by looking for 'DATA' folder upwards."""
    cur = os.path.abspath(os.path.dirname(dat_path))
    for _ in range(3):
        if os.path.basename(cur).lower() == "data":
            return os.path.dirname(cur)
        cur = os.path.dirname(cur)
    return os.path.dirname(os.path.dirname(dat_path))

def resolve_relative_path(case_root: str, relative_path: str) -> str:
    """Resolves relative paths from DAT to absolute paths securely."""
    if not relative_path:
        return None
        
    # 1. Clean Quotes and hidden spaces
    rel = relative_path.strip().strip('"').strip("'").strip()
    
    # 2. Fix E-Discovery glitch where Network Paths start with .\     
    if rel.startswith(".\\\\") or rel.startswith(".//"):
        rel = rel[1:] # Dot hata diya, UNC slashes bacha liye
    elif rel.startswith(".\\") or rel.startswith("./"):
        # Check if the part after .\ is absolute (e.g., .\Z:\data)
        if len(rel) > 3 and rel[3] == ":": 
            rel = rel[2:]
    
    # 3. Protect Direct Absolute and Network (UNC) paths
    if os.path.isabs(rel) or rel.startswith("\\\\") or rel.startswith("//") or (len(rel) > 1 and rel[1] == ":"):
        return rel
        
    # 4. Handle Standard Relative Paths securely     
    if rel.startswith(".\\") or rel.startswith("./"):
        rel = rel[2:]
    elif rel.startswith("\\") or rel.startswith("/"):
        rel = rel[1:]
        
    # 5. Prevent Duplicate Root Folders
    if case_root:
        root_base = os.path.basename(case_root).lower() + os.sep
        if rel.lower().startswith(root_base):
            rel = rel[len(root_base):]
            
        final_path = os.path.normpath(os.path.join(case_root, rel))
        
        # --- NEW SECURITY FIX: Prevent Directory Traversal ---
        if not os.path.abspath(final_path).startswith(os.path.abspath(case_root)):
            print(f"SECURITY BLOCK: Path escapes case root: {relative_path}")
            return None
        # -----------------------------------------------------
        return final_path
        
    return rel

# =====================
# ENCODING & PARSING
# =====================
def detect_encoding(path: str, sample_size=65536) -> str:
    with open(path, "rb") as f:
        raw = f.read(sample_size)        
    
    if raw.startswith(b'\xef\xbb\xbf'): return "utf-8-sig"
    if raw.startswith(b'\xff\xfe'): return "utf-16-le"
    if raw.startswith(b'\xfe\xff'): return "utf-16-be"
        
    if b'\x00' in raw[:100]: return "utf-16"    
    
    try:
        raw[:-4].decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
        
    return "cp1252"

def get_python_encoding(enc_label: str) -> str:
    mapping = {
        "UTF-8 with BOM": "utf-8-sig",
        "UTF-8": "utf-8",
        "UTF-16 LE": "utf-16-le",
        "UTF-16 BE": "utf-16-be",
        "CP1252": "cp1252"  # 🚨 "ANSI" ki jagah "cp1252" likhna zaroori hai
    }
    return mapping.get(enc_label, "utf-8-sig")

def normalize_header(name: str) -> str:
    return name.replace("\ufeff", "").strip().lower()

# =====================
# DATA HELPERS
# =====================
def sort_value(val):
    if val is None: return (0, None)
    if isinstance(val, str):
        v = val.replace("\xFE", "").replace("\x14", "").strip()
        if v == "": return (0, None)
        try: return (1, int(v))
        except: return (2, v.lower())
    try: return (1, int(val))
    except: return (2, str(val).lower())

def convert_format(fmt: str) -> str:    
    if not fmt: return ""

    tokens = sorted(FORMAT_MAP.keys(), key=len, reverse=True)
    pattern = re.compile("|".join(map(re.escape, tokens)))

    return pattern.sub(lambda m: FORMAT_MAP[m.group(0)], fmt)
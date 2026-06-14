#!/usr/bin/env python3
"""
flutter_patcher_pro.py
Enhanced all-in-one patcher for Flutter Android apps.

Features:
  - Merge .apks → .apk (APKEditor or apktool fallback)
  - Extract lib/arm64-v8a/libapp.so
  - Run blutter (Dart snapshot reversing)
  - Parse pp.txt to find pp_address by keyword
  - Find related functions via pptool (pure subprocess, no r2pipe)
  - Patch libapp.so using r2 commands directly
  - Repack & auto-sign patched APK
  - Cleanup temp files
"""

import os, shutil, subprocess, urllib.request, json, glob, sys, zipfile, tempfile, re, textwrap, hashlib
from pathlib import Path

# ─── helpers ───────────────────────────────────────────────────────────────

def find_jar(pattern: str, search_dir: str = ".") -> str | None:
    for f in os.listdir(search_dir):
        if f.lower().endswith(".jar") and pattern in f.lower():
            return os.path.join(search_dir, f)
    jars = glob.glob(os.path.join(search_dir, pattern))
    return jars[0] if jars else None


def download_file(url: str, outname: str) -> None:
    print(f"[↓] Downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "flutter_patcher_pro/2.0"})
    with urllib.request.urlopen(req) as resp, open(outname, "wb") as f:
        shutil.copyfileobj(resp, f)
    print(f"[✓] Saved → {outname}")


def has_tool(name: str) -> bool:
    return shutil.which(name) is not None


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, **kwargs)


# ─── APKEditor ─────────────────────────────────────────────────────────────

APKEDITOR_URL = "https://github.com/REAndroid/APKEditor/releases/latest/download/APKEditor.jar"


def ensure_apkeditor() -> str:
    jar = find_jar("apkeditor*")
    if jar:
        print(f"[✓] Found APKEditor: {jar}")
        return jar
    print("[!] APKEditor not found — downloading...")
    download_file(APKEDITOR_URL, "APKEditor.jar")
    return "APKEditor.jar"


def merge_apks_via_apkeditor(apks_file: str, apk_out: str) -> bool:
    jar = ensure_apkeditor()
    if not has_tool("java"):
        print("[✗] Java not installed — can't merge")
        return False
    ret = run(["java", "-jar", jar, "m", "-i", apks_file, "-o", apk_out])
    return ret.returncode == 0 and os.path.exists(apk_out)


def merge_apks_via_apktool(apks_file: str, apk_out: str) -> bool:
    if not has_tool("apktool"):
        print("[✗] apktool not found — install with: pkg install apktool")
        return False
    base = apks_file.removesuffix(".apks")
    tmp_dir = base + "_tmp"
    run(["apktool", "d", apks_file, "-o", tmp_dir])
    run(["apktool", "b", tmp_dir, "-o", apk_out])
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return os.path.exists(apk_out)


# ─── Extraction ────────────────────────────────────────────────────────────

def extract_libapp_from_apk(apk_path: str, out_dir: Path) -> Path | None:
    print(f"[*] Extracting lib/arm64-v8a/libapp.so from {apk_path}")
    with zipfile.ZipFile(apk_path, "r") as z:
        # Try exact path first
        for candidate in ["lib/arm64-v8a/libapp.so", "lib/arm64-v8a/libapp.so"]:
            if candidate in z.namelist():
                out_path = out_dir / "libapp.so"
                with z.open(candidate) as src, open(out_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                print(f"[✓] Extracted → {out_path}")
                return out_path

        # Fallback: find any libapp.so under arm64-v8a
        for m in z.namelist():
            if m.startswith("lib/arm64-v8a/") and m.endswith("libapp.so"):
                out_path = out_dir / "libapp.so"
                with z.open(m) as src, open(out_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                print(f"[✓] Extracted → {out_path} (from {m})")
                return out_path

        # Try any .so in arm64
        for m in z.namelist():
            if m.startswith("lib/arm64-v8a/") and m.endswith(".so"):
                out_path = out_dir / "libapp.so"
                with z.open(m) as src, open(out_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                print(f"[✓] Extracted → {out_path} (from {m})")
                return out_path

    print("[✗] No libapp.so found under lib/arm64-v8a/")
    return None


# ─── Blutter ───────────────────────────────────────────────────────────────

def run_blutter(lib_path: Path, blutter_dir: Path, out_dir: Path) -> bool:
    print("[*] Running blutter...")
    # blutter.py <lib_dir_or_file> <out_dir>
    cmd = ["python3", "blutter.py", str(lib_path.parent), str(out_dir)]
    ret = run(cmd, cwd=str(blutter_dir))
    if ret.returncode != 0:
        print(f"[✗] blutter failed (exit {ret.returncode})")
        return False
    print(f"[✓] blutter output → {out_dir}")
    return True


# ─── Find pp_address ───────────────────────────────────────────────────────

def find_pp_address(pp_txt: Path, keyword: str) -> str | None:
    print(f"[*] Searching for '{keyword}' in {pp_txt}")
    if not pp_txt.exists():
        print(f"[✗] {pp_txt} not found")
        return None

    pattern = re.compile(r"\[pp\+([0-9a-fA-Fx]+)\]")
    with open(pp_txt, "r", errors="replace") as f:
        for i, line in enumerate(f, 1):
            if keyword in line:
                m = pattern.search(line)
                if m:
                    addr = m.group(1)
                    print(f"[✓] Found pp_address = {addr} at line {i}")
                    return addr
    print(f"[✗] Keyword '{keyword}' not found in pp.txt")
    return None


# ─── pptool (related functions) ───────────────────────────────────────────

def get_related_functions(libso_path: Path, pp_addr: str, timeout: int = 15) -> list[tuple[str, str]]:
    print(f"[*] Searching related functions for pp+{pp_addr} via pptool")
    pp_arg = f"pp+{pp_addr}" if not pp_addr.startswith("pp+") else pp_addr

    if not has_tool("pptool"):
        print("[✗] pptool not found — install with: pkg install pptool")
        return []

    try:
        proc = run(["pptool", str(libso_path), pp_arg],
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                   text=True, timeout=timeout)
        raw = proc.stdout or ""
    except subprocess.TimeoutExpired:
        print("[✗] pptool timed out")
        return []
    except Exception as e:
        print(f"[✗] pptool error: {e}")
        return []

    # Strip ANSI
    ansi = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
    clean = ansi.sub("", raw)

    # Parse triple hex pattern: func_addr    something    offset_value
    # Typical line: 0x1234abcd   0x00001234   0x5678
    triple = re.compile(r"(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)")
    matches: list[tuple[str, str]] = []
    for line in clean.splitlines():
        m = triple.search(line)
        if m:
            matches.append((m.group(1), m.group(3)))

    if not matches:
        # Fallback: grab all 0x tokens, treat first as func, last as offset
        for line in clean.splitlines():
            toks = re.findall(r"0x[0-9a-fA-F]+", line)
            if len(toks) >= 3:
                matches.append((toks[0], toks[-1]))

    # Dedup
    seen: set[tuple[str, str]] = set()
    funcs: list[tuple[str, str]] = []
    for func, off in matches:
        key = (func.lower(), off.lower())
        if key not in seen:
            seen.add(key)
            funcs.append((func, off))

    if not funcs:
        print("[✗] No function-offset pairs found")
        return []

    print(f"[✓] Found {len(funcs)} related functions:")
    for i, (fa, of) in enumerate(funcs, 1):
        print(f"    {i:>3}. function_address = {fa}  |  offset_value = {of}")
    return funcs


# ─── Patch selection ───────────────────────────────────────────────────────

def parse_selection(sel: str, max_idx: int) -> list[int]:
    if not sel:
        return []
    sel = sel.strip().lower()
    if sel == "all":
        return list(range(1, max_idx + 1))

    indices: set[int] = set()
    for tok in re.split(r"\s*,\s*", sel):
        rng = re.match(r"^(\d+)-(\d+)$", tok)
        if rng:
            a, b = int(rng.group(1)), int(rng.group(2))
            indices.update(i for i in range(min(a, b), max(a, b) + 1) if 1 <= i <= max_idx)
        elif tok.isdigit():
            i = int(tok)
            if 1 <= i <= max_idx:
                indices.add(i)
    return sorted(indices)


# ─── Patching via r2 (pure CLI, no r2pipe) ────────────────────────────────

def patch_with_r2(libso_path: Path, funcs: list[tuple[str, str]], patch_asm: str = "add x0, x22, 0x20") -> bool:
    if not funcs:
        print("[!] No functions to patch")
        return False

    max_idx = len(funcs)
    print(f"\n[*] Functions available to patch: 1–{max_idx}")
    choice = input("Enter function(s) to patch (e.g. 1,3,5 / 2-4 / all) [skip]: ").strip()
    indices = parse_selection(choice, max_idx)
    if not indices:
        print("[!] No selection — skipping")
        return False

    # Build r2 script
    r2_script = textwrap.dedent(f"""
        e asm.lines = false
        e asm.bytes = false
        e asm.comments = false
    """)

    target_asm = re.compile(r"add\s+x0,\s*x22,\s*0x30", re.IGNORECASE)
    patched_count = 0

    for idx in indices:
        func_addr, offset_str = funcs[idx - 1]
        offset = int(offset_str, 16)
        search_range = max(offset * 30, 0x2000)  # generous search window
        print(f"[→] Processing #{idx}: {func_addr} (offset {offset_str})")

        # Disassemble the function to find the target instruction
        disasm_cmd = f"s {func_addr}; pd {search_range}"
        disasm = run(["r2", "-q", "-c", disasm_cmd, str(libso_path)],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out = disasm.stdout or ""

        found_addr = None
        for line in out.splitlines():
            if target_asm.search(line):
                m = re.search(r"(0x[0-9a-fA-F]+)", line)
                if m:
                    found_addr = m.group(1)
                    break

        if not found_addr:
            print(f"[⚠]  #{idx}: target 'add x0, x22, 0x30' not found in range")
            continue

        print(f"[✓]  #{idx}: found at {found_addr} — patching...")
        patch_cmd = f"s {found_addr}; {patch_asm}; wd"
        result = run(["r2", "-w", "-q", "-c", patch_cmd, str(libso_path)],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            print(f"[✓]  #{idx}: patched successfully")
            patched_count += 1
        else:
            print(f"[✗]  #{idx}: patch failed — {result.stderr.strip()}")

    return patched_count > 0


# ─── Repack & sign ─────────────────────────────────────────────────────────

def generate_debug_keystore(keystore_path: Path) -> None:
    if keystore_path.exists():
        return
    print("[*] Generating debug keystore...")
    run([
        "keytool", "-genkey", "-v", "-keystore", str(keystore_path),
        "-alias", "debug", "-keyalg", "RSA", "-keysize", "2048",
        "-validity", "10000",
        "-storepass", "android", "-keypass", "android",
        "-dname", "CN=Debug, OU=Dev, O=Company, L=City, ST=State, C=US"
    ])


def repack_and_sign(apk_path: Path, patched_lib: Path) -> Path:
    print(f"[*] Repacking {apk_path} with patched libapp.so")
    tmp_apk = apk_path.with_suffix(".patched.apk")
    out_apk = apk_path.with_stem(apk_path.stem + "_patched_signed")

    with zipfile.ZipFile(apk_path, "r") as zin, zipfile.ZipFile(tmp_apk, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename == "lib/arm64-v8a/libapp.so":
                zout.write(str(patched_lib), item.filename)
            else:
                zout.writestr(item, zin.read(item.filename))

    print(f"[✓] Patched APK: {tmp_apk}")

    # Sign with apksigner (preferred) or jarsigner
    if has_tool("apksigner"):
        keystore = Path.home() / ".android" / "debug.keystore"
        generate_debug_keystore(keystore)
        print("[*] Signing with apksigner...")
        run([
            "apksigner", "sign", "--ks", str(keystore),
            "--ks-pass", "pass:android", "--key-pass", "pass:android",
            "--ks-key-alias", "debug", "--out", str(out_apk), str(tmp_apk)
        ])
    elif has_tool("jarsigner"):
        keystore = Path.home() / ".android" / "debug.keystore"
        generate_debug_keystore(keystore)
        print("[*] Signing with jarsigner...")
        run([
            "jarsigner", "-sigalg", "SHA1withRSA",
            "-digestalg", "SHA1",
            "-keystore", str(keystore),
            "-storepass", "android", "-keypass", "android",
            str(tmp_apk), "debug"
        ])
        shutil.move(str(tmp_apk), str(out_apk))
    else:
        print("[!] Neither apksigner nor jarsigner found — APK unsigned")
        shutil.move(str(tmp_apk), str(out_apk))
        return out_apk

    # Clean temp
    if tmp_apk.exists():
        tmp_apk.unlink()
    print(f"[✓] Signed patched APK: {out_apk}")
    return out_apk


# ─── Cleanup ───────────────────────────────────────────────────────────────

def cleanup(workdir: Path) -> None:
    print("[*] Cleanup...")
    for p in workdir.iterdir():
        if p.name in ("arm64-v8a",) or p.name.endswith(".so"):
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
            print(f"  🧹 Removed {p.name}")
    print("[✓] Done")


# ─── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  Flutter Patcher Pro — Enhanced Edition")
    print("=" * 60)

    apk_input = input("\n[?] Enter APK/APKS filename: ").strip()
    if not apk_input:
        return print("[✗] No filename provided")

    keyword = input("[?] Enter keyword to search in pp.txt: ").strip()
    if not keyword:
        return print("[✗] No keyword provided")

    # Resolve paths
    apk_path = Path(apk_input).resolve()
    if apk_path.suffix == ".apks":
        apks_path = apk_path
        apk_path = apk_path.with_suffix(".apk")
    elif apk_path.suffix == ".apk":
        apks_path = apk_path.with_suffix(".apks")
    else:
        apk_path = apk_path.with_suffix(".apk")
        apks_path = apk_path.with_suffix(".apks")

    # ── Step 1: Merge APKs if needed ──
    if not apk_path.exists():
        if not apks_path.exists():
            return print(f"[✗] Neither {apk_path} nor {apks_path} found")
        print("[*] Merging APKS → APK")
        merged = merge_apks_via_apkeditor(str(apks_path), str(apk_path))
        if not merged:
            merged = merge_apks_via_apktool(str(apks_path), str(apk_path))
        if not merged:
            return print("[✗] Failed to merge APKs")
        # Clean APKS split folder
        split_folder = apks_path.with_suffix("")
        if split_folder.is_dir():
            shutil.rmtree(split_folder)
    else:
        print(f"[✓] APK ready: {apk_path}")

    # ── Step 2: Create workdir ──
    workdir = Path(tempfile.mkdtemp(prefix="flutter_patcher_")).resolve()
    print(f"[*] Working directory: {workdir}")

    # ── Step 3: Extract libapp.so ──
    libso = extract_libapp_from_apk(str(apk_path), workdir)
    if not libso:
        shutil.rmtree(workdir, ignore_errors=True)
        return

    # ── Step 4: Run blutter ──
    blutter_home = Path.home() / "blutter-termux"
    out_dir = workdir / "blutter_out"
    out_dir.mkdir(exist_ok=True)
    if not run_blutter(libso, blutter_home, out_dir):
        cleanup(workdir)
        return

    # ── Step 5: Find pp_address ──
    pp_txt = out_dir / "pp.txt"
    pp_addr = find_pp_address(pp_txt, keyword)
    if not pp_addr:
        cleanup(workdir)
        return

    # ── Step 6: Get related functions ──
    funcs = get_related_functions(libso, pp_addr)
    if not funcs:
        print("[!] No functions to patch — skipping patch step")
    else:
        # ── Step 7: Patch ──
        patched = patch_with_r2(libso, funcs)
        if patched:
            # ── Step 8: Repack & sign ──
            repack_and_sign(apk_path, libso)
        else:
            print("[!] No patches applied — skipping repack")

    # ── Step 9: Cleanup ──
    cleanup(workdir)


if __name__ == "__main__":
    main()
#!/bin/bash

# ═══════════════════════════════════════════════════════════════
# ZIP Password Cracker — Professional Edition
# For authorized penetration testing only
# ═══════════════════════════════════════════════════════════════

RED="\e[31m"; GREEN="\e[32m"; YELLOW="\e[33m"; BLUE="\e[34m"; CYAN="\e[36m"; BOLD="\e[1m"; RESET="\e[0m"

banner() {
    clear
    echo -e "${CYAN}${BOLD}"
    echo '███████╗██╗██████╗     ██████╗██████╗  █████╗  ██████╗██╗  ██╗███████╗██████╗ '
    echo '╚══███╔╝██║██╔══██╗   ██╔════╝██╔══██╗██╔══██╗██╔════╝██║  ██║██╔════╝██╔══██╗'
    echo '  ███╔╝ ██║██████╔╝   ██║     ██████╔╝███████║██║     ███████║█████╗  ██████╔╝'
    echo ' ███╔╝  ██║██╔═══╝    ██║     ██╔══██╗██╔══██║██║     ██╔══██║██╔══╝  ██╔══██╗'
    echo '███████╗██║██║        ╚██████╗██║  ██║██║  ██║╚██████╗██║  ██║███████╗██║  ██║'
    echo '╚══════╝╚═╝╚═╝         ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝'
    echo -e "${RESET}"
    echo -e "${YELLOW}Professional ZIP Password Cracker — Authorized Pentest Tool${RESET}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════════${RESET}\n"
}

detect_tools() {
    local tools=("unzip" "7z" "fcrackzip" "zip2john" "john" "hashcat" "rar2john" "zipinfo" "file")
    echo -e "${YELLOW}[*] Checking available tools...${RESET}"
    for tool in "${tools[@]}"; do
        if command -v "$tool" &>/dev/null; then
            echo -e "  ${GREEN}[+]${RESET} $tool — available"
        else
            echo -e "  ${RED}[-]${RESET} $tool — not installed"
        fi
    done
    echo
}

get_zip_info() {
    local zip="$1"
    echo -e "${CYAN}[*] ZIP File Analysis:${RESET}"
    
    # File info
    echo -e "  ${YELLOW}File:${RESET}     $(basename "$zip")"
    echo -e "  ${YELLOW}Size:${RESET}     $(du -h "$zip" | cut -f1)"
    echo -e "  ${YELLOW}Files:${RESET}    $(unzip -l "$zip" 2>/dev/null | tail -1 | awk '{print $2}')"
    
    # Encryption type
    if command -v zipinfo &>/dev/null; then
        local enc=$(zipinfo -v "$zip" 2>/dev/null | grep -i "encryption")
        echo -e "  ${YELLOW}Encryption:${RESET} $(echo "$enc" | head -1 || echo "Unknown")"
    fi
    
    # Check if password protected
    if unzip -tq "$zip" &>/dev/null; then
        echo -e "  ${RED}⚠  NOT password protected!${RESET}"
        return 1
    else
        echo -e "  ${GREEN}✓  Password protected${RESET}"
    fi
    echo
    return 0
}

# ─── Method 1: Shell loop (unzip / 7z) ───────────────────────
method_shell_loop() {
    local zip="$1" wl="$2"
    echo -e "${CYAN}[Method 1] Shell Loop — unzip + 7z${RESET}"
    echo -e "${YELLOW}  Wordlist:${RESET} $wl ($(wc -l < "$wl") passwords)"
    
    local start=$(date +%s) count=0 found=false
    
    while IFS= read -r pass || [[ -n "$pass" ]]; do
        ((count++))
        [[ $((count % 100)) -eq 0 ]] && printf "${YELLOW}[%d]${RESET} %s\r" "$count" "${pass:0:40}"
        
        # unzip (ZipCrypto 2.0)
        if unzip -P "$pass" -tq "$zip" 2>/dev/null; then
            echo -e "\n${GREEN}[+] PASSWORD FOUND (unzip):${RESET} $pass"
            found=true; break
        fi
        
        # 7z (AES-256)
        if command -v 7z &>/dev/null; then
            if 7z t -p"$pass" "$zip" 2>/dev/null | grep -q "Everything is Ok"; then
                echo -e "\n${GREEN}[+] PASSWORD FOUND (7z):${RESET} $pass"
                found=true; break
            fi
        fi
    done < "$wl"
    
    local elapsed=$(( $(date +%s) - start ))
    
    if $found; then
        echo -e "${GREEN}[+] Cracking complete — $count tries in ${elapsed}s${RESET}"
        echo "$pass" > /tmp/zip_cracked.txt
        echo -e "${GREEN}[+] Password saved to /tmp/zip_cracked.txt${RESET}"
        return 0
    else
        echo -e "${RED}[-] Not found — $count tries in ${elapsed}s${RESET}"
        return 1
    fi
}

# ─── Method 2: fcrackzip ──────────────────────────────────────
method_fcrackzip() {
    local zip="$1" wl="$2"
    echo -e "${CYAN}[Method 2] fcrackzip (optimized)${RESET}"
    
    if ! command -v fcrackzip &>/dev/null; then
        echo -e "${RED}[-] fcrackzip not installed${RESET}"
        echo -e "${YELLOW}  Install: sudo apt install fcrackzip${RESET}"
        return 1
    fi
    
    local start=$(date +%s)
    fcrackzip -u -D -p "$wl" "$zip" 2>&1
    local elapsed=$(( $(date +%s) - start ))
    
    echo -e "${BLUE}  Time: ${elapsed}s${RESET}"
    return $?
}

# ─── Method 3: John the Ripper ────────────────────────────────
method_john() {
    local zip="$1" wl="$2"
    echo -e "${CYAN}[Method 3] John the Ripper${RESET}"
    
    if ! command -v zip2john &>/dev/null; then
        echo -e "${RED}[-] zip2john not installed${RESET}"
        echo -e "${YELLOW}  Install: sudo apt install john${RESET}"
        return 1
    fi
    
    local hashfile="/tmp/zip_hash_$$.txt"
    local potfile="/tmp/zip_john_pot_$$.txt"
    
    echo -e "${YELLOW}  Extracting hash...${RESET}"
    zip2john "$zip" > "$hashfile" 2>/dev/null
    
    local start=$(date +%s)
    john --wordlist="$wl" --pot="$potfile" "$hashfile" 2>&1 | tail -5
    john --pot="$potfile" --show "$hashfile" 2>/dev/null
    local elapsed=$(( $(date +%s) - start ))
    
    echo -e "${BLUE}  Time: ${elapsed}s${RESET}"
    rm -f "$hashfile" "$potfile" 2>/dev/null
}

# ─── Method 4: hashcat (GPU-accelerated) ──────────────────────
method_hashcat() {
    local zip="$1" wl="$2"
    echo -e "${CYAN}[Method 4] hashcat (GPU-accelerated)${RESET}"
    
    if ! command -v zip2john &>/dev/null || ! command -v hashcat &>/dev/null; then
        echo -e "${RED}[-] zip2john or hashcat not installed${RESET}"
        echo -e "${YELLOW}  Install: sudo apt install john hashcat${RESET}"
        return 1
    fi
    
    local hashfile="/tmp/zip_hashcat_$$.txt"
    
    echo -e "${YELLOW}  Extracting hash...${RESET}"
    zip2john "$zip" > "$hashfile" 2>/dev/null
    
    # Detect hash type
    local hash_type
    if grep -q '$zip2$' "$hashfile" 2>/dev/null; then
        hash_type=17210  # ZipCrypto + AES
    elif grep -q '$pkzip2$' "$hashfile" 2>/dev/null; then
        hash_type=17220  # PKZIP
    else
        hash_type=17200  # ZipCrypto
    fi
    
    echo -e "${YELLOW}  Hash type: -m $hash_type${RESET}"
    
    local start=$(date +%s)
    hashcat -m $hash_type -a 0 "$hashfile" "$wl" --potfile-disable --force 2>&1 | grep -E "Recovered|Cracked|Speed|Time"
    local elapsed=$(( $(date +%s) - start ))
    
    # Show result
    hashcat -m $hash_type -a 0 "$hashfile" "$wl" --potfile-disable --force --show 2>/dev/null
    
    echo -e "${BLUE}  Time: ${elapsed}s${RESET}"
    rm -f "$hashfile" 2>/dev/null
}

# ─── Method 5: RAR2JOHN (RAR support) ────────────────────────
method_rar() {
    local rar="$1" wl="$2"
    echo -e "${CYAN}[Method 5] RAR cracking${RESET}"
    
    if ! command -v rar2john &>/dev/null; then
        echo -e "${RED}[-] rar2john not installed${RESET}"
        echo -e "${YELLOW}  Install: sudo apt install john${RESET}"
        return 1
    fi
    
    local hashfile="/tmp/rar_hash_$$.txt"
    
    rar2john "$rar" > "$hashfile" 2>/dev/null
    local start=$(date +%s)
    john --wordlist="$wl" "$hashfile" 2>&1 | tail -5
    john --show "$hashfile" 2>/dev/null
    local elapsed=$(( $(date +%s) - start ))
    
    echo -e "${BLUE}  Time: ${elapsed}s${RESET}"
    rm -f "$hashfile" 2>/dev/null
}

# ─── Method 6: Brute-force (small length) ─────────────────────
method_bruteforce() {
    local zip="$1"
    echo -e "${CYAN}[Method 6] Brute-force (short passwords only)${RESET}"
    
    if ! command -v fcrackzip &>/dev/null; then
        echo -e "${RED}[-] fcrackzip required${RESET}"
        return 1
    fi
    
    read -p "  Max password length (1-4, default 3): " max_len
    max_len=${max_len:-3}
    [[ $max_len -gt 4 ]] && max_len=4
    
    local charset="abcdefghijklmnopqrstuvwxyz0123456789"
    
    echo -e "${YELLOW}  Charset:${RESET} $charset"
    echo -e "${YELLOW}  Length:${RESET}  1-$max_len"
    echo -e "${RED}  ⚠  This can take a long time!${RESET}"
    read -p "  Continue? (y/N): " confirm
    
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        local start=$(date +%s)
        fcrackzip -u -b -l "1-$max_len" -c "$charset" "$zip" 2>&1
        local elapsed=$(( $(date +%s) - start ))
        echo -e "${BLUE}  Time: ${elapsed}s${RESET}"
    fi
}

# ─── Main ─────────────────────────────────────────────────────
main() {
    banner
    detect_tools
    
    # Input
    read -p "Enter target file path (ZIP/RAR): " TARGET
    [[ ! -f "$TARGET" ]] && echo -e "${RED}File not found${RESET}" && exit 1
    
    read -p "Enter wordlist path: " WORDLIST
    [[ ! -f "$WORDLIST" ]] && echo -e "${RED}Wordlist not found${RESET}" && exit 1
    
    # Analyze
    get_zip_info "$TARGET" || exit 1
    
    # Method selection
    echo -e "${CYAN}Select cracking method:${RESET}"
    echo "  1) Shell loop (unzip + 7z) — universal"
    echo "  2) fcrackzip — fastest for ZipCrypto"
    echo "  3) John the Ripper — handles ZIP/RAR/AES"
    echo "  4) hashcat — GPU-accelerated"
    echo "  5) RAR cracking"
    echo "  6) Brute-force (short passwords)"
    echo "  7) ALL methods (sequential)"
    echo "  8) Parallel — run ALL simultaneously"
    read -p "Choice [1-8]: " METHOD
    
    case $METHOD in
        1) method_shell_loop "$TARGET" "$WORDLIST" ;;
        2) method_fcrackzip "$TARGET" "$WORDLIST" ;;
        3) method_john "$TARGET" "$WORDLIST" ;;
        4) method_hashcat "$TARGET" "$WORDLIST" ;;
        5) method_rar "$TARGET" "$WORDLIST" ;;
        6) method_bruteforce "$TARGET" ;;
        7)
            method_shell_loop "$TARGET" "$WORDLIST"
            method_fcrackzip "$TARGET" "$WORDLIST"
            method_john "$TARGET" "$WORDLIST"
            method_hashcat "$TARGET" "$WORDLIST"
            ;;
        8)
            echo -e "${YELLOW}[*] Running all methods in parallel...${RESET}"
            method_shell_loop "$TARGET" "$WORDLIST" &
            method_fcrackzip "$TARGET" "$WORDLIST" &
            method_john "$TARGET" "$WORDLIST" &
            method_hashcat "$TARGET" "$WORDLIST" &
            wait
            ;;
        *) echo -e "${RED}Invalid choice${RESET}" ;;
    esac
    
    # Cleanup
    echo -e "\n${BLUE}[*] Done.${RESET}"
}

main "$@"
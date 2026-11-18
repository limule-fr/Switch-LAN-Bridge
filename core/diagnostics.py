import platform
import socket
import subprocess
import urllib.request
from datetime import datetime

def _run_command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=5)
        return (result.stdout or result.stderr).strip()
    except (OSError, subprocess.TimeoutExpired):
        return "Commande indisponible."

def _default_gateway():
    system = platform.system().lower()
    if system == "linux":
        output = _run_command(["ip", "route", "show", "default"])
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0] == "default" and parts[1] == "via":
                return parts[2]
    elif system == "windows":
        output = _run_command(["route", "print", "-4"])
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                return parts[2]
    elif system == "darwin":
        output = _run_command(["route", "-n", "get", "default"])
        for line in output.splitlines():
            if "gateway:" in line:
                return line.split("gateway:", 1)[1].strip()
    return "Non détectée"

def _local_ip():
    # UDP connect obtains the selected local interface without sending application data.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 53))
        return sock.getsockname()[0]
    except OSError:
        return "Indisponible"
    finally:
        sock.close()

def _internet_test():
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=4):
            return True, "Connexion TCP vers 1.1.1.1:443 réussie"
    except OSError as exc:
        return False, f"Échec de connexion : {exc}"

def _dns_test():
    try:
        addresses = socket.getaddrinfo("example.com", 443, type=socket.SOCK_STREAM)
        unique = sorted({item[4][0] for item in addresses})
        return True, ", ".join(unique[:3])
    except OSError as exc:
        return False, str(exc)

def run_diagnostics():
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    system = platform.platform()
    hostname = socket.gethostname()
    try:
        interfaces = socket.if_nameindex()
        interface_text = "\n".join(f"  - {name} (index {idx})" for idx, name in interfaces)
    except OSError:
        interface_text = "Impossible de lister les interfaces."

    ip = _local_ip()
    gateway = _default_gateway()
    internet_ok, internet_detail = _internet_test()
    dns_ok, dns_detail = _dns_test()

    lines = [
        "SWITCH LAN BRIDGE — DIAGNOSTIC",
        f"Date : {now}",
        f"Machine : {hostname}",
        f"Système : {system}",
        "",
        "INTERFACES RÉSEAU",
        interface_text or "Aucune interface détectée.",
        "",
        "CONFIGURATION IP",
        f"Adresse IPv4 sélectionnée : {ip}",
        f"Passerelle par défaut : {gateway}",
        "",
        "CONNECTIVITÉ",
        f"Internet (TCP) : {'OK' if internet_ok else 'ÉCHEC'}",
        f"  {internet_detail}",
        f"Résolution DNS : {'OK' if dns_ok else 'ÉCHEC'}",
        f"  {dns_detail}",
        "",
        "LIMITES DE CETTE VERSION",
        "- Ce diagnostic ne détecte pas encore la Switch sur le réseau.",
        "- Il ne teste ni le mode moniteur ni l'injection Wi-Fi.",
        "- Aucun tunnel LDN n'est implémenté dans cette version.",
    ]
    return "\n".join(lines)

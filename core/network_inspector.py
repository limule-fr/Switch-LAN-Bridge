"""Network interface inventory using operating-system tools where available."""

import json
import platform
import shutil
import socket
import subprocess
from pathlib import Path


def _run_command(args, timeout=8):
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError:
        return "", f"Outil indisponible : {args[0]}"
    except subprocess.TimeoutExpired:
        return "", f"Délai dépassé : {' '.join(args)}"
    except OSError as exc:
        return "", f"Impossible d'exécuter {' '.join(args)} : {exc}"
    output = (result.stdout or "").strip()
    if result.returncode:
        detail = (result.stderr or output or f"code {result.returncode}").strip()
        return output, f"{' '.join(args)} : {detail}"
    return output, None


def _linux_interface_type(name, sysfs_path, hardware_name=""):
    if name == "lo":
        return "Loopback"
    if (sysfs_path / "wireless").exists() or (sysfs_path / "phy80211").exists():
        return "Wi-Fi"
    if name.startswith(("wwan", "wwp")) or any(
        marker in hardware_name.lower()
        for marker in ("mobile broadband", "cellular", "modem")
    ):
        return "Modem"
    try:
        link_type = int((sysfs_path / "type").read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return "Autre (non vérifié)"
    if link_type == 512:
        return "Modem/PPP"
    if link_type == 1:
        return "Ethernet" if (sysfs_path / "device").exists() else "Ethernet/autre"
    return f"Autre (type {link_type})"


def _linux_driver(sysfs_path):
    driver_path = sysfs_path / "device" / "driver"
    try:
        return driver_path.resolve(strict=True).name
    except OSError:
        return "Non vérifié"


def get_driver_version(interface_name, driver):
    if not driver or driver == "Non vérifié":
        return "Non vérifié"
    output, error = _run_command(["ethtool", "-i", interface_name])
    if not error:
        for line in output.splitlines():
            if line.lower().startswith("version:"):
                version = line.split(":", 1)[1].strip()
                if version:
                    return version
    output, error = _run_command(["modinfo", "-F", "version", driver])
    return output if not error and output else "Non vérifié"


def _linux_hardware_name(sysfs_path):
    if not shutil.which("udevadm"):
        return "Non vérifié"
    try:
        device_path = str(sysfs_path.resolve(strict=True))
    except OSError:
        return "Non vérifié"
    output, error = _run_command(
        ["udevadm", "info", "--query=property", f"--path={device_path}"], timeout=3
    )
    if error:
        return "Non vérifié"
    properties = dict(
        line.split("=", 1) for line in output.splitlines() if "=" in line
    )
    vendor = properties.get("ID_VENDOR_FROM_DATABASE") or properties.get("ID_VENDOR")
    model = properties.get("ID_MODEL_FROM_DATABASE") or properties.get("ID_MODEL")
    if vendor and model:
        return f"{vendor} {model}"
    return model or vendor or "Non vérifié"


def _linux_interfaces():
    errors = []
    interfaces = []
    names = []
    try:
        names = [name for _, name in socket.if_nameindex()]
    except OSError as exc:
        errors.append(f"Liste des interfaces indisponible : {exc}")

    addresses = {}
    output, error = _run_command(["ip", "-j", "address", "show"])
    if error:
        errors.append(error)
    else:
        try:
            for entry in json.loads(output):
                by_family = {"ipv4": [], "ipv6": []}
                for address in entry.get("addr_info", []):
                    family = address.get("family")
                    key = "ipv4" if family == "inet" else "ipv6" if family == "inet6" else None
                    if key and address.get("local"):
                        by_family[key].append(address["local"])
                addresses[entry.get("ifname")] = by_family
                addresses[entry.get("ifname")]["operstate"] = entry.get("operstate")
                addresses[entry.get("ifname")]["flags"] = entry.get("flags", [])
                if entry.get("ifname") and entry["ifname"] not in names:
                    names.append(entry["ifname"])
        except (json.JSONDecodeError, TypeError) as exc:
            errors.append(f"Réponse de `ip` illisible : {exc}")

    for name in names:
        path = Path("/sys/class/net") / name
        try:
            operstate = (path / "operstate").read_text(encoding="ascii").strip()
        except OSError:
            operstate = str(addresses.get(name, {}).get("operstate") or "unknown").lower()
        flags = addresses.get(name, {}).get("flags", [])
        state = (
            "active" if operstate == "up" or (operstate == "unknown" and "UP" in flags)
            else "inactive" if operstate in {"down", "dormant", "lowerlayerdown"}
            else "unavailable"
        )
        try:
            mac = (path / "address").read_text(encoding="ascii").strip()
            if not mac or mac == "00:00:00:00:00:00":
                mac = "Non disponible"
        except OSError:
            mac = "Non disponible"
        hardware_name = _linux_hardware_name(path)
        driver = _linux_driver(path)
        interfaces.append({
            "name": name,
            "type": _linux_interface_type(name, path, hardware_name),
            "hardware_name": hardware_name,
            "mac": mac,
            "ipv4": addresses.get(name, {}).get("ipv4", []),
            "ipv6": addresses.get(name, {}).get("ipv6", []),
            "state": state,
            "driver": driver,
            "driver_version": get_driver_version(name, driver),
        })

    wifi = [item for item in interfaces if item["type"] == "Wi-Fi"]
    primary = next((item["name"] for item in wifi if item["state"] == "active"), None)
    if primary is None and wifi:
        primary = wifi[0]["name"]
    return {"interfaces": interfaces, "primary_wifi": primary, "errors": errors}


def _windows_interfaces():
    script = (
        "$a=@(Get-NetAdapter -IncludeHidden | Select-Object Name,InterfaceDescription,"
        "Status,MacAddress,DriverName,DriverVersion,ifIndex,PhysicalMediaType);"
        "$p=@(Get-NetIPAddress -ErrorAction SilentlyContinue | "
        "Select-Object InterfaceIndex,AddressFamily,IPAddress);"
        "@{adapters=$a;addresses=$p} | ConvertTo-Json -Depth 4 -Compress"
    )
    output, error = _run_command(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=15
    )
    if error:
        return {
            "interfaces": [], "primary_wifi": None,
            "errors": [f"Inventaire Windows non disponible : {error}"],
        }
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, TypeError) as exc:
        return {
            "interfaces": [], "primary_wifi": None,
            "errors": [f"Réponse PowerShell illisible : {exc}"],
        }
    adapters = data.get("adapters") or []
    addresses = data.get("addresses") or []
    if isinstance(adapters, dict):
        adapters = [adapters]
    if isinstance(addresses, dict):
        addresses = [addresses]
    by_index = {}
    for entry in addresses:
        family = entry.get("AddressFamily")
        key = (
            "ipv4" if family in (2, "IPv4")
            else "ipv6" if family in (23, "IPv6")
            else None
        )
        if key and entry.get("IPAddress"):
            by_index.setdefault(str(entry.get("InterfaceIndex")), {"ipv4": [], "ipv6": []})[key].append(
                entry["IPAddress"]
            )

    interfaces = []
    for adapter in adapters:
        name = str(adapter.get("Name") or "Interface inconnue")
        description = str(adapter.get("InterfaceDescription") or "")
        combined = f"{name} {description} {adapter.get('PhysicalMediaType', '')}".lower()
        if "loopback" in combined:
            interface_type = "Loopback"
        elif "wi-fi" in combined or "wifi" in combined or "802.11" in combined:
            interface_type = "Wi-Fi"
        elif "ethernet" in combined:
            interface_type = "Ethernet"
        elif "cellular" in combined or "mobile broadband" in combined:
            interface_type = "Modem"
        else:
            interface_type = "Autre (non vérifié)"
        status = str(adapter.get("Status") or "").lower()
        state = "active" if status == "up" else "inactive" if status else "unavailable"
        mac = str(adapter.get("MacAddress") or "Non disponible")
        interfaces.append({
            "name": name,
            "type": interface_type,
            "hardware_name": description or "Non vérifié",
            "mac": mac,
            "ipv4": by_index.get(str(adapter.get("ifIndex")), {}).get("ipv4", []),
            "ipv6": by_index.get(str(adapter.get("ifIndex")), {}).get("ipv6", []),
            "state": state,
            "driver": str(adapter.get("DriverName") or "Non vérifié"),
            "driver_version": str(adapter.get("DriverVersion") or "Non vérifié"),
        })
    wifi = [item for item in interfaces if item["type"] == "Wi-Fi"]
    primary = next((item["name"] for item in wifi if item["state"] == "active"), None)
    if primary is None and wifi:
        primary = wifi[0]["name"]
    return {"interfaces": interfaces, "primary_wifi": primary, "errors": []}


def inspect_interfaces():
    """Return a structured interface inventory without changing network state."""
    system = platform.system().lower()
    if system == "linux":
        result = _linux_interfaces()
    elif system == "windows":
        result = _windows_interfaces()
    else:
        try:
            interfaces = [
                {
                    "name": name,
                    "type": "Non vérifié",
                    "hardware_name": "Non vérifié",
                    "mac": "Non vérifié",
                    "ipv4": [],
                    "ipv6": [],
                    "state": "unavailable",
                    "driver": "Non vérifié",
                    "driver_version": "Non vérifié",
                }
                for _, name in socket.if_nameindex()
            ]
            errors = ["Détails d'interface non implémentés pour ce système."]
        except OSError as exc:
            interfaces = []
            errors = [f"Liste des interfaces indisponible : {exc}"]
        result = {"interfaces": interfaces, "primary_wifi": None, "errors": errors}
    result["platform"] = platform.platform()
    return result

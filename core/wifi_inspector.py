"""Conservative Wi-Fi capability inspection and bounded passive beacon capture."""

import platform
import re
import shutil
import struct
import subprocess
from pathlib import Path

from core.network_inspector import _run_command, get_driver_version, inspect_interfaces


def _iw_interfaces():
    output, error = _run_command(["iw", "dev"])
    if error:
        return [], [error]
    interfaces = []
    current = None
    for line in output.splitlines():
        match = re.match(r"\s*Interface\s+(\S+)", line)
        if match:
            current = {"name": match.group(1), "phy": None, "mode": "Non vérifié"}
            interfaces.append(current)
            continue
        if current is None:
            continue
        match = re.match(r"\s*wiphy\s+(\S+)", line)
        if match:
            current["phy"] = f"phy{match.group(1)}"
        match = re.match(r"\s*type\s+(.+)", line)
        if match:
            current["mode"] = match.group(1).strip().lower()
    return interfaces, []


def _phy_capabilities():
    output, error = _run_command(["iw", "phy"])
    if error:
        return {}, [error]
    phys = {}
    current = None
    in_modes = False
    for line in output.splitlines():
        match = re.match(r"Wiphy\s+(\S+)", line)
        if match:
            current = {
                "name": match.group(1),
                "modes": set(),
                "modes_verified": False,
                "channels": [],
            }
            phys[current["name"]] = current
            in_modes = False
            continue
        if current is None:
            continue
        if "Supported interface modes:" in line:
            in_modes = True
            current["modes_verified"] = True
            continue
        if in_modes:
            mode = re.match(r"\s*\*\s+(\S+)", line)
            if mode:
                current["modes"].add(mode.group(1).lower())
                continue
            if line.strip():
                in_modes = False
        channel = re.match(r"\s*\*\s+(\d+(?:\.\d+)?)\s+MHz\s+\[(\d+)\]", line)
        if channel and "disabled" not in line.lower():
            current["channels"].append({
                "frequency_mhz": int(float(channel.group(1))),
                "channel": int(channel.group(2)),
            })
    return phys, []


def inspect_wifi_capabilities():
    """Report only capabilities explicitly exposed by the system."""
    if platform.system().lower() == "windows":
        inventory = inspect_interfaces()
        wifi_interfaces = []
        for item in inventory.get("interfaces", []):
            if item["type"] != "Wi-Fi":
                continue
            wifi_interfaces.append({
                "name": item["name"],
                "card_name": item.get("hardware_name", "Non vérifié"),
                "phy": "Non vérifié",
                "current_mode": "Non vérifié",
                "driver": item["driver"],
                "driver_version": item["driver_version"],
                "managed_support": "Non vérifié",
                "monitor_support": "Non vérifié",
                "injection_support": "Non vérifié",
                "supported_modes": [],
                "bands": [],
                "channels": [],
                "errors": [
                    "Le pilote/API Windows ne fournit pas ici de preuve vérifiable des modes 802.11."
                ],
            })
        return {
            "platform": platform.platform(),
            "wifi_interfaces": wifi_interfaces,
            "errors": inventory.get("errors", []),
        }
    if platform.system().lower() != "linux":
        return {
            "platform": platform.platform(),
            "wifi_interfaces": [],
            "errors": [
                "L'inspection détaillée des modes 802.11 via `iw` n'est disponible que sous Linux.",
                "Injection de trames : Non vérifié.",
            ],
        }

    interfaces, interface_errors = _iw_interfaces()
    phys, phy_errors = _phy_capabilities()
    inventory = inspect_interfaces()
    hardware_names = {
        item["name"]: item.get("hardware_name", "Non vérifié")
        for item in inventory.get("interfaces", [])
    }
    result = []
    errors = interface_errors + phy_errors
    for interface in interfaces:
        phy_name = interface["phy"]
        phy = phys.get(phy_name) if phy_name else None
        if phy is None and len(phys) == 1:
            phy = next(iter(phys.values()))
        modes = sorted(phy["modes"]) if phy else []
        channels = phy["channels"] if phy else []
        bands = []
        if any(2400 <= item["frequency_mhz"] < 2500 for item in channels):
            bands.append("2,4 GHz")
        if any(4900 <= item["frequency_mhz"] < 5925 for item in channels):
            bands.append("5 GHz")
        if any(5925 <= item["frequency_mhz"] <= 7125 for item in channels):
            bands.append("6 GHz")

        driver_path = Path("/sys/class/net") / interface["name"] / "device" / "driver"
        try:
            driver = driver_path.resolve(strict=True).name
        except OSError:
            driver = "Non vérifié"
        result.append({
            "name": interface["name"],
            "card_name": hardware_names.get(interface["name"], "Non vérifié"),
            "phy": phy_name or (phy["name"] if phy else "Non vérifié"),
            "current_mode": interface["mode"],
            "driver": driver,
            "driver_version": get_driver_version(interface["name"], driver),
            "managed_support": (
                "Oui" if "managed" in modes
                else "Non" if phy and phy["modes_verified"]
                else "Non vérifié"
            ),
            "monitor_support": (
                "Oui" if "monitor" in modes
                else "Non" if phy and phy["modes_verified"]
                else "Non vérifié"
            ),
            "injection_support": "Non vérifié",
            "supported_modes": modes,
            "bands": bands,
            "channels": channels,
            "errors": [] if phy else ["Capacités PHY non vérifiées."],
        })
    if not interfaces and not errors:
        errors.append("Aucune interface Wi-Fi exposée par `iw`.")
    return {"platform": platform.platform(), "wifi_interfaces": result, "errors": errors}


def get_passive_scan_preflight(interface_name):
    """Check capture prerequisites and whether a mode change would be needed."""
    if platform.system().lower() != "linux":
        return {
            "available": False,
            "can_change_mode": False,
            "current_mode": "Non vérifié",
            "monitor_supported": "Non vérifié",
            "errors": [
                "La capture passive 802.11 via tcpdump/iw n'est pas exposée par cette plateforme.",
                "Aucun scan WLAN classique n'est présenté comme capture passive.",
            ],
        }
    missing = [tool for tool in ("iw", "tcpdump") if not shutil.which(tool)]
    if missing:
        return {
            "available": False,
            "can_change_mode": False,
            "current_mode": "Non vérifié",
            "monitor_supported": "Non vérifié",
            "errors": [f"Outil(s) manquant(s) : {', '.join(missing)}"],
        }
    interfaces, errors = _iw_interfaces()
    selected = next((item for item in interfaces if item["name"] == interface_name), None)
    if selected is None:
        return {
            "available": False,
            "can_change_mode": False,
            "current_mode": "Non vérifié",
            "monitor_supported": "Non vérifié",
            "errors": errors or [f"Interface Wi-Fi inconnue : {interface_name}"],
        }
    phys, phy_errors = _phy_capabilities()
    phy = phys.get(selected["phy"]) if selected["phy"] else None
    if phy is None and len(phys) == 1:
        phy = next(iter(phys.values()))
    monitor_supported = (
        "Oui" if phy and "monitor" in phy["modes"]
        else "Non" if phy and phy["modes_verified"]
        else "Non vérifié"
    )
    mode = selected["mode"]
    can_change = mode == "managed" and monitor_supported == "Oui"
    ready = mode == "monitor"
    preflight_errors = errors + phy_errors
    if not ready and not can_change:
        preflight_errors.append(
            "Capture impossible sans mode monitor vérifié. Aucune modification n'a été effectuée."
        )
    return {
        "available": ready or can_change,
        "can_change_mode": can_change,
        "current_mode": mode,
        "monitor_supported": monitor_supported,
        "errors": preflight_errors,
    }


def _parse_radiotap(packet):
    if len(packet) < 8:
        return None, None, None, None
    radiotap_length = struct.unpack_from("<H", packet, 2)[0]
    if radiotap_length < 8 or radiotap_length > len(packet):
        return None, None, None, None
    present_words = []
    offset = 4
    while True:
        if offset + 4 > radiotap_length:
            return None, None, None, None
        word = struct.unpack_from("<I", packet, offset)[0]
        present_words.append(word)
        offset += 4
        if not word & 0x80000000:
            break
    channel = frequency = signal = None
    field_offset = offset
    fields = {
        0: (8, 8), 1: (1, 1), 2: (1, 1), 3: (2, 4), 4: (2, 2),
        5: (1, 1), 6: (1, 1), 7: (2, 2), 8: (2, 2), 9: (2, 2),
        10: (1, 1), 11: (1, 1), 12: (1, 1), 13: (1, 1), 14: (2, 2),
        15: (2, 2), 16: (1, 1), 17: (1, 1), 18: (4, 8),
        19: (1, 3), 20: (4, 8), 21: (2, 12), 22: (8, 12),
        23: (2, 12), 24: (2, 12), 25: (1, 1), 26: (2, 4),
    }
    for word_index, word in enumerate(present_words):
        for bit in range(31):
            if not word & (1 << bit):
                continue
            field_index = word_index * 32 + bit
            if field_index == 29 or field_index == 30:
                continue
            field = fields.get(field_index)
            if field is None:
                return radiotap_length, channel, frequency, signal
            alignment, size = field
            field_offset = (field_offset + alignment - 1) & ~(alignment - 1)
            if field_offset + size > radiotap_length:
                return radiotap_length, channel, frequency, signal
            if field_index == 3:
                frequency = struct.unpack_from("<H", packet, field_offset)[0]
            elif field_index == 5:
                signal = struct.unpack_from("b", packet, field_offset)[0]
            field_offset += size
    if frequency and channel is None:
        if 2412 <= frequency <= 2472:
            channel = (frequency - 2407) // 5
        elif frequency == 2484:
            channel = 14
        elif frequency == 5935:
            channel = 2
        elif 5000 <= frequency < 5925:
            channel = (frequency - 5000) // 5
        elif 5925 <= frequency <= 7125:
            channel = (frequency - 5950) // 5
    return radiotap_length, channel, frequency, signal


def _parse_beacon(packet, link_type):
    channel = signal = frequency = None
    if link_type == 127:
        radiotap_length, channel, frequency, signal = _parse_radiotap(packet)
        if radiotap_length is None:
            return None
        packet = packet[radiotap_length:]
    elif link_type != 105:
        return None
    if len(packet) < 36:
        return None
    frame_control = packet[0]
    if (frame_control & 0x0C) != 0 or ((frame_control >> 4) & 0x0F) != 8:
        return None
    bssid = ":".join(f"{byte:02x}" for byte in packet[16:22])
    capability = struct.unpack_from("<H", packet, 34)[0]
    ies = packet[36:]
    ssid = None
    security = "Non vérifié"
    while len(ies) >= 2:
        element_id, length = ies[0], ies[1]
        if len(ies) < 2 + length:
            break
        value = ies[2:2 + length]
        if element_id == 0:
            if value:
                decoded_ssid = value.decode("utf-8", errors="replace")
                ssid = "".join(
                    character if character.isprintable() else f"\\u{ord(character):04x}"
                    for character in decoded_ssid
                )
            else:
                ssid = "(SSID masqué)"
        elif element_id == 3 and length == 1:
            channel = value[0]
        elif element_id == 48:
            security = "WPA2/WPA3 (RSN)"
            if length >= 8:
                if len(value) >= 8:
                    pairwise_count = struct.unpack_from("<H", value, 6)[0]
                    akm_offset = 8 + pairwise_count * 4
                    if len(value) >= akm_offset + 2 + 4:
                        akm_count = struct.unpack_from("<H", value, akm_offset)[0]
                        akm_offset += 2
                        for index in range(akm_count):
                            suite = value[akm_offset + index * 4:akm_offset + index * 4 + 4]
                            if len(suite) == 4 and suite[:3] == b"\x00\x0f\xac" and suite[3] in (8, 9, 12):
                                security = "WPA3/RSN"
                                break
        elif element_id == 221 and value.startswith(b"\x00\x50\xf2\x01"):
            if security == "Non vérifié":
                security = "WPA (RSN absent)"
        ies = ies[2 + length:]
    if security == "Non vérifié" and capability & 0x0010:
        security = "Chiffrement indiqué (type non vérifié)"
    elif security == "Non vérifié":
        security = "Ouvert (indiqué par beacon)"
    if frequency is None and channel is not None and channel == 14:
        frequency = 2484
    elif frequency is None and channel == 2:
        frequency = 5935
    elif frequency is None and channel is not None and 1 <= channel <= 13:
        frequency = 2407 + channel * 5
    elif frequency is None and channel is not None and 15 <= channel <= 196:
        frequency = 5000 + channel * 5
    if frequency is not None:
        if 2412 <= frequency <= 2472:
            channel = (frequency - 2407) // 5
        elif frequency == 2484:
            channel = 14
        elif frequency == 5935:
            channel = 2
        elif 5000 <= frequency < 5925:
            channel = (frequency - 5000) // 5
        elif 5925 <= frequency <= 7125:
            channel = (frequency - 5950) // 5
    return {
        "ssid": ssid if ssid is not None else "(SSID non annoncé)",
        "bssid": bssid,
        "channel": channel,
        "frequency_mhz": frequency,
        "signal_dbm": signal,
        "security": security,
    }


def _read_pcap(data):
    if len(data) < 24:
        return [], ["Capture pcap vide ou incomplète."]
    magic = data[:4]
    formats = {
        b"\xd4\xc3\xb2\xa1": "<",
        b"\xa1\xb2\xc3\xd4": ">",
        b"\x4d\x3c\xb2\xa1": "<",
        b"\xa1\xb2\x3c\x4d": ">",
    }
    endian = formats.get(magic)
    if not endian:
        return [], ["Format pcap non reconnu."]
    link_type = struct.unpack_from(endian + "I", data, 20)[0]
    if link_type not in (105, 127):
        return [], [f"Type de trame pcap non pris en charge : {link_type}."]
    records = {}
    offset = 24
    while offset + 16 <= len(data):
        _, _, captured_length, _ = struct.unpack_from(endian + "IIII", data, offset)
        offset += 16
        if captured_length > len(data) - offset:
            break
        record = _parse_beacon(data[offset:offset + captured_length], link_type)
        offset += captured_length
        if record:
            key = record["bssid"]
            if key not in records or (
                record["signal_dbm"] is not None and
                (records[key]["signal_dbm"] is None or record["signal_dbm"] > records[key]["signal_dbm"])
            ):
                records[key] = record
    return list(records.values()), []


def scan_passive_wifi(interface_name, duration_seconds, allow_mode_change=False):
    """Capture beacons for a bounded time; restores Managed mode if changed."""
    duration_seconds = max(3, min(int(duration_seconds), 60))
    preflight = get_passive_scan_preflight(interface_name)
    if not preflight["available"]:
        return {
            "interface": interface_name, "duration_seconds": duration_seconds,
            "networks": [], "errors": preflight["errors"], "mode_changed": False,
        }
    changed_mode = False
    errors = list(preflight["errors"])
    if preflight["can_change_mode"]:
        if not allow_mode_change:
            return {
                "interface": interface_name, "duration_seconds": duration_seconds,
                "networks": [], "errors": [
                    "Le passage en mode monitor exige une confirmation explicite."
                ], "mode_changed": False,
            }
        _, error = _run_command(["iw", "dev", interface_name, "set", "type", "monitor"])
        if error:
            return {
                "interface": interface_name, "duration_seconds": duration_seconds,
                "networks": [], "errors": [error], "mode_changed": False,
            }
        changed_mode = True

    capture_errors = []
    networks = []
    command = [
        "tcpdump", "-i", interface_name, "-s", "512", "-c", "5000",
        "-w", "-", "type", "mgt", "subtype", "beacon",
    ]
    try:
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as exc:
            capture_errors.append(f"Impossible de démarrer tcpdump : {exc}")
        else:
            try:
                capture, stderr = process.communicate(timeout=duration_seconds)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    capture, stderr = process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    capture, stderr = process.communicate()
            except OSError as exc:
                capture = b""
                stderr = b""
                capture_errors.append(f"Erreur pendant la capture tcpdump : {exc}")
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.communicate(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
            if process.returncode not in (0, -15, 15) and stderr_text:
                capture_errors.append(stderr_text)
            networks, parse_errors = _read_pcap(capture)
            capture_errors.extend(parse_errors)
    finally:
        restore_error = None
        if changed_mode:
            _, restore_error = _run_command(
                ["iw", "dev", interface_name, "set", "type", "managed"]
            )
        if restore_error:
            errors.append(
                "ÉCHEC DE RESTAURATION : impossible de rétablir le mode Managed. "
                f"Action manuelle nécessaire. {restore_error}"
            )
        errors.extend(capture_errors)
    return {
        "interface": interface_name,
        "duration_seconds": duration_seconds,
        "networks": networks,
        "errors": errors,
        "mode_changed": changed_mode,
        "capture_type": (
            "Capture passive de beacons 802.11 sur le canal actuel "
            "(pas de balayage des canaux ni capture LDN)."
        ),
    }

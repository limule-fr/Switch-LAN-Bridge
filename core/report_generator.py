"""Formatting and export helpers for diagnostic reports."""

from datetime import datetime
from pathlib import Path
import platform


def _format_addresses(addresses):
    return ", ".join(addresses) if addresses else "Non disponible"


def generate_report(interfaces_result=None, wifi_result=None, scan_result=None, errors=None):
    lines = [
        "SWITCH LAN BRIDGE — RAPPORT NETWORK INSPECTOR",
        f"Date : {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"Système d'exploitation : {platform.platform()}",
        "",
        "INTERFACES RÉSEAU",
    ]
    if not interfaces_result:
        lines.append("Non analysées.")
    else:
        interfaces = interfaces_result.get("interfaces", [])
        if not interfaces:
            lines.append("Aucune interface détaillée.")
        for interface in interfaces:
            primary = " — Wi-Fi principal" if interface["name"] == interfaces_result.get("primary_wifi") else ""
            lines.extend([
                f"- {interface['name']} ({interface['type']}){primary}",
                f"  Carte/modèle : {interface.get('hardware_name', 'Non vérifié')}",
                f"  État : {interface['state']}",
                f"  MAC : {interface['mac']}",
                f"  IPv4 : {_format_addresses(interface['ipv4'])}",
                f"  IPv6 : {_format_addresses(interface['ipv6'])}",
                f"  Pilote : {interface['driver']}",
                f"  Version du pilote : {interface['driver_version']}",
            ])
        for error in interfaces_result.get("errors", []):
            lines.append(f"  Erreur/indisponibilité : {error}")

    lines.extend(["", "CAPACITÉS WI-FI"])
    if not wifi_result:
        lines.append("Non analysées.")
    else:
        wifi_interfaces = wifi_result.get("wifi_interfaces", [])
        if not wifi_interfaces:
            lines.append("Aucune interface Wi-Fi détaillée.")
        for interface in wifi_interfaces:
            lines.extend([
                f"- {interface['name']} ({interface.get('phy', 'Non vérifié')})",
                f"  Carte Wi-Fi : {interface.get('card_name', 'Non vérifié')}",
                f"  Mode actuel : {interface['current_mode']}",
                f"  Pilote / version : {interface['driver']} / {interface['driver_version']}",
                f"  Managed : {interface['managed_support']}",
                f"  Monitor : {interface['monitor_support']}",
                f"  Injection de trames : {interface['injection_support']}",
                f"  Bandes vérifiées : {', '.join(interface['bands']) or 'Non vérifiées'}",
                "  Fréquences/canaux : " + (
                    ", ".join(
                        f"{item['frequency_mhz']} MHz (canal {item['channel']})"
                        for item in interface["channels"]
                    ) or "Non vérifiés"
                ),
            ])
            for error in interface.get("errors", []):
                lines.append(f"  Erreur/indisponibilité : {error}")
        for error in wifi_result.get("errors", []):
            lines.append(f"Erreur/indisponibilité : {error}")

    lines.extend(["", "RÉSEAUX DÉTECTÉS"])
    if not scan_result:
        lines.append("Aucun scan effectué.")
    else:
        lines.append(scan_result.get("capture_type", "Type de scan non vérifié."))
        lines.append(
            f"Interface : {scan_result.get('interface', 'Non vérifiée')} — "
            f"durée demandée : {scan_result.get('duration_seconds', 'Non vérifiée')} s"
        )
        networks = scan_result.get("networks", [])
        if not networks:
            lines.append("Aucun réseau/beacon décodé.")
        for network in networks:
            frequency = (
                f"{network['frequency_mhz']} MHz"
                if network["frequency_mhz"] is not None else "Non vérifiée"
            )
            signal = (
                f"{network['signal_dbm']} dBm"
                if network["signal_dbm"] is not None else "Non vérifié"
            )
            lines.append(
                f"- SSID : {network['ssid']} | BSSID : {network['bssid']} | "
                f"Canal : {network['channel'] if network['channel'] is not None else 'Non vérifié'} | "
                f"Fréquence : {frequency} | Signal : {signal} | "
                f"Sécurité : {network['security']}"
            )
        for error in scan_result.get("errors", []):
            lines.append(f"Erreur/indisponibilité : {error}")

    lines.extend([
        "",
        "LIMITES",
        "- Le mode Monitor ne prouve pas la prise en charge de l'injection.",
        "- Une capture passive de beacons ne constitue pas une capture du trafic LDN.",
        "- La capture écoute le canal actuellement configuré ; elle ne parcourt pas les canaux.",
        "- Aucun tunnel réseau ou relais de jeu n'est implémenté.",
        "- Aucun mot de passe Wi-Fi n'est collecté ou inclus dans ce rapport.",
    ])
    if errors:
        lines.extend(["", "ERREURS DE L'APPLICATION"])
        lines.extend(f"- {error}" for error in errors)
    return "\n".join(lines)


def export_report(content, reports_dir="reports"):
    folder = Path(reports_dir)
    folder.mkdir(parents=True, exist_ok=True)
    filename = folder / f"slb-network-inspector-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
    filename.write_text(content.rstrip() + "\n", encoding="utf-8")
    return filename

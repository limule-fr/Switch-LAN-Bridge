import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from datetime import datetime
from pathlib import Path

from core import __version__
from core.network_inspector import inspect_interfaces
from core.report_generator import export_report, generate_report
from core.wifi_inspector import (
    get_passive_scan_preflight,
    inspect_wifi_capabilities,
    scan_passive_wifi,
)


class SLBWindow:
    def __init__(self, root, diagnostic_function):
        self.root = root
        self.diagnostic_function = diagnostic_function
        self.root.title(f"Switch LAN Bridge — {__version__}")
        self.root.geometry("920x700")
        self.root.minsize(700, 520)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.results_queue = queue.Queue()
        self.busy = False
        self.interfaces_result = None
        self.wifi_result = None
        self.scan_result = None
        self.inspector_errors = []
        self._build()
        self.root.after(100, self._drain_results)

    def _build(self):
        container = ttk.Frame(self.root, padding=14)
        container.pack(fill="both", expand=True)

        header = ttk.Frame(container)
        header.pack(fill="x")
        ttk.Label(header, text="Switch LAN Bridge", font=("TkDefaultFont", 19, "bold")).pack(anchor="w")
        ttk.Label(
            header, text=f"Prototype de diagnostic réseau — version {__version__}"
        ).pack(anchor="w", pady=(2, 10))

        self.notebook = ttk.Notebook(container)
        self.notebook.pack(fill="both", expand=True)
        self.diagnostics_tab = ttk.Frame(self.notebook, padding=10)
        self.inspector_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.diagnostics_tab, text="Diagnostic")
        self.notebook.add(self.inspector_tab, text="Network Inspector")
        self._build_diagnostics_tab()
        self._build_inspector_tab()

    def _build_diagnostics_tab(self):
        status = ttk.LabelFrame(self.diagnostics_tab, text="État du programme", padding=10)
        status.pack(fill="x", pady=(0, 10))
        self.status_var = tk.StringVar(value="En attente d'un diagnostic")
        ttk.Label(status, textvariable=self.status_var).pack(side="left")
        self.run_button = ttk.Button(status, text="Lancer le diagnostic", command=self.start_diagnostic)
        self.run_button.pack(side="right")

        output_frame = ttk.LabelFrame(self.diagnostics_tab, text="Rapport", padding=8)
        output_frame.pack(fill="both", expand=True)
        self.output = tk.Text(output_frame, wrap="word", font=("TkFixedFont", 10), state="disabled")
        scrollbar = ttk.Scrollbar(output_frame, orient="vertical", command=self.output.yview)
        self.output.configure(yscrollcommand=scrollbar.set)
        self.output.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        footer = ttk.Frame(self.diagnostics_tab)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Button(footer, text="Enregistrer le rapport", command=self.save_report).pack(side="left")
        ttk.Label(footer, text="SLB ne modifie aucune configuration réseau sans confirmation.").pack(side="right")

        self._set_text(
            self.output,
            "Bienvenue dans Switch LAN Bridge.\n\n"
            "Cette version vérifie les interfaces réseau, l'adresse IP, la passerelle, "
            "la connectivité Internet et le DNS.\n\n"
            "L'onglet Network Inspector ajoute l'inventaire des interfaces et les "
            "diagnostics Wi-Fi vérifiables. Aucun tunnel LDN n'est implémenté.",
        )

    def _build_inspector_tab(self):
        controls = ttk.LabelFrame(self.inspector_tab, text="Network Inspector", padding=10)
        controls.pack(fill="x", pady=(0, 10))
        button_row = ttk.Frame(controls)
        button_row.pack(fill="x")
        self.inspect_interfaces_button = ttk.Button(
            button_row, text="Analyser les interfaces", command=self.start_interface_inspection
        )
        self.inspect_interfaces_button.pack(side="left", padx=(0, 6))
        self.inspect_wifi_button = ttk.Button(
            button_row, text="Analyser les capacités Wi-Fi", command=self.start_wifi_inspection
        )
        self.inspect_wifi_button.pack(side="left", padx=6)
        self.scan_button = ttk.Button(
            button_row, text="Scanner les réseaux", command=self.start_scan_preflight
        )
        self.scan_button.pack(side="left", padx=6)
        self.export_button = ttk.Button(
            button_row, text="Exporter le rapport", command=self.export_inspector_report
        )
        self.export_button.pack(side="right", padx=(6, 0))

        scan_options = ttk.Frame(controls)
        scan_options.pack(fill="x", pady=(10, 0))
        ttk.Label(scan_options, text="Interface Wi-Fi :").pack(side="left")
        self.interface_var = tk.StringVar()
        self.interface_selector = ttk.Combobox(
            scan_options, textvariable=self.interface_var, state="readonly", width=18
        )
        self.interface_selector.pack(side="left", padx=(6, 18))
        ttk.Label(scan_options, text="Durée (secondes, 3–60) :").pack(side="left")
        self.duration_var = tk.IntVar(value=10)
        self.duration_selector = ttk.Spinbox(
            scan_options, from_=3, to=60, textvariable=self.duration_var, width=5
        )
        self.duration_selector.pack(side="left", padx=6)

        self.inspector_status_var = tk.StringVar(value="En attente d'une analyse")
        ttk.Label(
            self.inspector_tab, textvariable=self.inspector_status_var
        ).pack(anchor="w", pady=(0, 6))
        output_frame = ttk.LabelFrame(self.inspector_tab, text="Résultats", padding=8)
        output_frame.pack(fill="both", expand=True)
        self.inspector_output = tk.Text(
            output_frame, wrap="word", font=("TkFixedFont", 10), state="disabled"
        )
        scrollbar = ttk.Scrollbar(
            output_frame, orient="vertical", command=self.inspector_output.yview
        )
        self.inspector_output.configure(yscrollcommand=scrollbar.set)
        self.inspector_output.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._set_text(
            self.inspector_output,
            "Les capacités sont affichées comme vérifiées uniquement si le système "
            "les expose explicitement.\n\n"
            "La capture passive Linux nécessite `iw`, `tcpdump` et des privilèges de "
            "capture. Elle observe les beacons du canal actuel ; ce n'est pas une capture LDN.",
        )

        self.action_buttons = [
            self.run_button,
            self.inspect_interfaces_button,
            self.inspect_wifi_button,
            self.scan_button,
            self.export_button,
        ]

    @staticmethod
    def _set_text(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _set_busy(self, busy, status=None):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for button in self.action_buttons:
            button.configure(state=state)
        if status:
            self.inspector_status_var.set(status)

    def _on_close(self):
        if self.busy:
            messagebox.showwarning(
                "Opération en cours",
                "Attendez la fin de l'opération avant de fermer l'application. "
                "Cela permet à SLB de terminer la capture et de tenter la restauration "
                "du mode Managed.",
            )
            return
        self.root.destroy()

    def _launch_task(self, key, label, function, *args):
        if self.busy:
            return
        self._set_busy(True, f"{label} en cours…")
        threading.Thread(
            target=self._worker, args=(key, function, args), daemon=True
        ).start()

    def _worker(self, key, function, args):
        try:
            result = function(*args)
            self.results_queue.put((key, result, None))
        except Exception as exc:
            self.results_queue.put((key, None, exc))

    def _drain_results(self):
        try:
            while True:
                key, result, error = self.results_queue.get_nowait()
                self._set_busy(False)
                if error is not None:
                    self.inspector_errors.append(f"{key} : {error}")
                    if key == "diagnostic":
                        self.status_var.set("Le diagnostic a rencontré une erreur")
                        messagebox.showerror("Erreur", str(error))
                    else:
                        self.inspector_status_var.set(f"{key} : erreur")
                        messagebox.showerror("Erreur", str(error))
                    self._refresh_inspector_output()
                    continue
                self._handle_result(key, result)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_results)

    def _handle_result(self, key, result):
        if key == "diagnostic":
            self._set_text(self.output, result)
            self.status_var.set("Diagnostic terminé")
        elif key == "interfaces":
            self.interfaces_result = result
            names = [
                item["name"] for item in result.get("interfaces", [])
                if item["type"] == "Wi-Fi"
            ]
            self.interface_selector.configure(values=names)
            if names and self.interface_var.get() not in names:
                primary = result.get("primary_wifi")
                self.interface_var.set(primary if primary in names else names[0])
            self.inspector_status_var.set("Analyse des interfaces terminée")
            self._refresh_inspector_output()
        elif key == "wifi":
            self.wifi_result = result
            names = [item["name"] for item in result.get("wifi_interfaces", [])]
            self.interface_selector.configure(values=names)
            if names and self.interface_var.get() not in names:
                self.interface_var.set(names[0])
            self.inspector_status_var.set("Analyse des capacités Wi-Fi terminée")
            self._refresh_inspector_output()
        elif key == "scan_preflight":
            self._handle_scan_preflight(result)
        elif key == "scan":
            self.scan_result = result
            status = "Capture passive terminée"
            if result.get("errors"):
                status += " — consultez les résultats"
            self.inspector_status_var.set(status)
            self._refresh_inspector_output()
        elif key == "export":
            messagebox.showinfo("Rapport enregistré", f"Rapport enregistré dans :\n{result.resolve()}")
            self.inspector_status_var.set("Rapport exporté")

    def _refresh_inspector_output(self):
        content = generate_report(
            self.interfaces_result,
            self.wifi_result,
            self.scan_result,
            self.inspector_errors,
        )
        self._set_text(self.inspector_output, content)

    def start_diagnostic(self):
        if self.busy:
            return
        self.run_button.configure(state="disabled")
        self.status_var.set("Diagnostic en cours…")
        self._launch_task("diagnostic", "Diagnostic", self.diagnostic_function)

    def start_interface_inspection(self):
        self._launch_task("interfaces", "Analyse des interfaces", inspect_interfaces)

    def start_wifi_inspection(self):
        self._launch_task("wifi", "Analyse des capacités Wi-Fi", inspect_wifi_capabilities)

    def start_scan_preflight(self):
        interface = self.interface_var.get().strip()
        if not interface:
            messagebox.showwarning(
                "Interface Wi-Fi requise",
                "Analysez les interfaces ou les capacités Wi-Fi, puis choisissez une interface.",
            )
            return
        try:
            duration = int(self.duration_var.get())
        except (ValueError, tk.TclError):
            messagebox.showwarning("Durée invalide", "La durée doit être comprise entre 3 et 60 secondes.")
            return
        if not 3 <= duration <= 60:
            messagebox.showwarning("Durée invalide", "La durée doit être comprise entre 3 et 60 secondes.")
            return
        self.pending_scan = (interface, duration)
        self._launch_task(
            "scan_preflight", "Vérification des prérequis", get_passive_scan_preflight, interface
        )

    def _handle_scan_preflight(self, preflight):
        interface, duration = self.pending_scan
        if not preflight.get("available"):
            self.scan_result = {
                "interface": interface,
                "duration_seconds": duration,
                "networks": [],
                "errors": preflight.get("errors", ["Prérequis de capture non satisfaits."]),
                "mode_changed": False,
                "capture_type": "Capture passive non effectuée.",
            }
            self.inspector_status_var.set("Capture passive indisponible")
            self._refresh_inspector_output()
            return
        allow_mode_change = False
        if preflight.get("can_change_mode"):
            allow_mode_change = messagebox.askyesno(
                "Confirmer le passage en mode Monitor",
                f"L'interface {interface} est actuellement en mode Managed.\n\n"
                "Le changement en mode Monitor peut interrompre ou déconnecter le Wi-Fi. "
                "Après la capture, SLB tentera de rétablir automatiquement le mode Managed, "
                "mais la reconnexion au réseau peut nécessiter une action manuelle.\n\n"
                "Continuer pour cette capture ?",
                icon="warning",
            )
            if not allow_mode_change:
                self.scan_result = {
                    "interface": interface,
                    "duration_seconds": duration,
                    "networks": [],
                    "errors": ["Capture annulée : aucun changement de mode n'a été effectué."],
                    "mode_changed": False,
                    "capture_type": "Capture passive non effectuée.",
                }
                self.inspector_status_var.set("Capture annulée")
                self._refresh_inspector_output()
                return
        self._launch_task(
            "scan",
            "Capture passive",
            scan_passive_wifi,
            interface,
            duration,
            allow_mode_change,
        )

    def export_inspector_report(self):
        content = generate_report(
            self.interfaces_result,
            self.wifi_result,
            self.scan_result,
            self.inspector_errors,
        )
        self._launch_task("export", "Export du rapport", export_report, content)

    def save_report(self):
        content = self.output.get("1.0", "end").strip()
        if not content:
            messagebox.showwarning("Rapport vide", "Lance d'abord un diagnostic.")
            return
        try:
            folder = Path("reports")
            folder.mkdir(exist_ok=True)
            filename = folder / f"slb-diagnostic-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
            filename.write_text(content + "\n", encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Erreur d'export", str(exc))
            return
        messagebox.showinfo("Rapport enregistré", f"Rapport enregistré dans :\n{filename.resolve()}")

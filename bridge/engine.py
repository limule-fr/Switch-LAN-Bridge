"""
Moteur SLB réservé aux expérimentations futures.

Aucun tunnel LDN n'est implémenté ici. Ne pas annoncer cette fonctionnalité
comme disponible avant validation sur du matériel réel.
"""

class BridgeEngine:
    def status(self):
        return {
            "implemented": False,
            "message": "Le moteur de relais LDN n'est pas encore implémenté."
        }

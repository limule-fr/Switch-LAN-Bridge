# Switch LAN Bridge (SLB)

**Version : 0.2.0 — Network Inspector**

SLB est un projet expérimental visant à étudier la possibilité de relier à distance
des consoles Nintendo Switch utilisant le mode sans fil local (LDN).

Cette version est uniquement un outil de diagnostic PC. Elle ne crée aucun tunnel
LDN et ne transporte pas de trafic de jeu.

## Prérequis

- Python 3.10 ou plus récent
- Tkinter
- Linux ou Windows 11 (macOS : diagnostic de base, détails Wi-Fi non vérifiés)
- Sous Linux, `iproute2` fournit les adresses IP ; `iw` et `tcpdump` sont nécessaires
  à l'inspection Wi-Fi et à la capture passive. `ethtool` est facultatif pour la
  version du pilote ; `modinfo` est utilisé en solution de repli.

Sous Lubuntu/Ubuntu, si Tkinter manque :

```bash
sudo apt install python3-tk
```

## Lancer

Depuis le dossier du projet :

```bash
python3 main.py
```

Sous Windows :

```powershell
py main.py
```

## Fonctions de la version 0.1.0

- Nom de la machine et système d'exploitation
- Liste des interfaces réseau connues du système
- Adresse IPv4 sélectionnée pour sortir vers Internet
- Passerelle par défaut (selon les outils disponibles)
- Test TCP vers `1.1.1.1:443`
- Test de résolution DNS
- Export du rapport texte dans `reports/`

## Fonctions de la version 0.2.0

- Onglet **Network Inspector**, sans retrait du diagnostic de base 0.1.0
- Inventaire des interfaces : type, MAC, adresses IPv4/IPv6, état et pilote lorsque vérifiables
- Identification de l'interface Wi-Fi principale
- Capacités Managed/Monitor et bandes/canaux issus de `iw phy` sous Linux
- L'injection de trames est toujours affichée **Non vérifié** : Monitor ne la prouve pas
- Capture passive limitée de beacons 802.11 avec `tcpdump` sur Linux
- Capture limitée au canal actuellement configuré (aucun balayage/changement de canal)
- Durée de capture configurable (3 à 60 secondes)
- Si un changement de mode est nécessaire, une confirmation explicite est demandée ;
  SLB tente ensuite de restaurer le mode Managed et signale tout échec
- Rapport Network Inspector exporté en texte dans `reports/`

La capture passive ne commence que lorsque les outils, l'interface et les privilèges
le permettent. Aucun scan WLAN classique n'est présenté comme capture passive. Sous
Windows, cette capture n'est pas annoncée comme disponible par défaut.

## Limites connues et sécurité

- La détection de la Switch n'est pas implémentée.
- Les données non exposées par le système sont indiquées « Non vérifié ».
- Un pilote qui annonce Monitor n'implique pas que l'injection fonctionne.
- Le passage d'une interface connectée en mode Monitor peut interrompre le Wi-Fi.
  Il n'est jamais réalisé sans confirmation. La restauration du mode Managed peut
  réussir sans rétablir automatiquement la connexion : une reconnexion manuelle
  peut être nécessaire.
- La capture passive porte sur des beacons Wi-Fi visibles, pas sur les trames LDN
  d'une partie Animal Crossing.
- Aucun protocole LDN n'est transporté.
- Les résultats de connectivité ne garantissent pas qu'une session de jeu fonctionnera.

## Structure

- `core/` : logique de diagnostic
- `gui/` : interface Tkinter
- `core/network_inspector.py` : inventaire des interfaces
- `core/wifi_inspector.py` : capacités Wi-Fi et capture passive bornée
- `core/report_generator.py` : génération des rapports texte
- `bridge/` : futur moteur expérimental, non implémenté

## Principe

Stabilité, transparence et tests reproductibles avant toute fonctionnalité de relais.

## Tests manuels sous Lubuntu

1. Démarrer `python3 main.py` et vérifier que les onglets **Diagnostic** et
   **Network Inspector** s'ouvrent.
2. Dans **Diagnostic**, lancer le diagnostic et vérifier les informations réseau,
   Internet et DNS habituelles.
3. Dans **Network Inspector**, lancer **Analyser les interfaces**. Comparer les
   interfaces, IPv4/IPv6, MAC, état et interface Wi-Fi principale avec
   `ip -br address` et `ip link`.
4. Lancer **Analyser les capacités Wi-Fi**. Comparer les modes et canaux indiqués
   avec `iw phy`; vérifier que l'injection reste « Non vérifié ».
5. Si l'interface prend en charge Monitor mais est en mode Managed, lancer
   **Scanner les réseaux** : vérifier que l'application demande une autorisation
   avant tout changement. Refuser et vérifier qu'aucune commande de modification
   n'est exécutée. Si Monitor n'est pas annoncé, la capture doit rester indisponible.
6. Dans un environnement de test, autoriser une capture de courte durée. Vérifier
   que la durée est respectée, que le mode Managed est restauré après capture et
   que les erreurs/privilèges manquants sont affichés. Attendre la fin avant de
   fermer la fenêtre ; l'application bloque sa fermeture pendant l'opération.
7. Choisir une interface déjà en mode Monitor (si disponible) pour vérifier qu'une
   capture passive n'affiche pas de demande de changement de mode. La capture reste
   limitée au canal actuel, sans balayage des canaux.
8. Cliquer sur **Exporter le rapport** et vérifier le fichier créé dans `reports/` :
   date, système, interfaces, capacités, résultats/indisponibilités et absence de
   mot de passe Wi-Fi.
9. Sans `iw` ou `tcpdump` dans le `PATH` (ou sous Windows), vérifier que la capture
   est signalée comme indisponible, sans prétendre avoir effectué un scan passif.

### Lancement et vérifications

```bash
python3 --version
python3 -m compileall -q core gui main.py
python3 main.py
```

Sous Lubuntu, installer les outils système manquants si nécessaire :

```bash
sudo apt update
sudo apt install python3-tk iw tcpdump iproute2
```

La capture peut nécessiter des privilèges `CAP_NET_RAW` et, si un changement de
mode est explicitement confirmé, `CAP_NET_ADMIN`. SLB ne lance pas `sudo` et ne
demande pas de mot de passe. Ne lancer l'application avec des privilèges élevés
que lorsque cela est nécessaire et compris.

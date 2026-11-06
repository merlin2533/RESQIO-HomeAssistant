<div align="center">

<img src="https://raw.githubusercontent.com/merlin2533/RESQIO-HomeAssistant/main/custom_components/resqio/brand/icon@2x.png" alt="RESQIO" width="140">

# RESQIO Home Assistant Integration

**Alarm, Fahrzeugstatus und mehr aus Ihrer Feuerwehr direkt in Home Assistant.**

[![Release](https://img.shields.io/github/v/release/merlin2533/RESQIO-HomeAssistant?label=Release)](https://github.com/merlin2533/RESQIO-HomeAssistant/releases)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5?logo=homeassistantcommunitystore&logoColor=white)](https://hacs.xyz)
[![Lizenz Apache-2.0](https://img.shields.io/badge/Lizenz-Apache--2.0-blue)](LICENSE)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-unterst%C3%BCtzen-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/merlin2533)

[![In HACS öffnen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=merlin2533&repository=RESQIO-HomeAssistant&category=integration)

</div>

---

## Was ist das?

Die Integration zeigt in Home Assistant, was in Ihrer Feuerwehr gerade los ist: **Alarm mit Stichwort und Uhrzeit**, Fahrzeugstatus, offene Wartungen und Mängel, Veranstaltungen, Fahrzeugreservierungen und mehr. Daraus bauen Sie Automationen, Ansagen und Dashboards.

Die Integration **liest nur**. Sie ändert nichts in RESQIO und löst keine Alarme aus.

## Anwendungsfälle

### Im Feuerwehrhaus

| Was passiert | Wie |
|---|---|
| **Fahrzeugtore öffnen bei Alarm**, pro Fahrzeug | Blueprint *Gerätehaus-Tor pro Fahrzeug öffnen*: Es öffnet nur das Tor des Fahrzeugs, das ausrückt. Alternativ öffnen alle Tore bei jedem Alarm. |
| **Licht an über KNX** | Blueprint *Licht über KNX bei Alarm*: schaltet KNX-Lichter oder Gruppenadressen über die KNX-Integration von Home Assistant. |
| **Ansage mit Einsatzstichwort** | Blueprint *Ansage mit Stichwort*: Ein Lautsprecher nennt das Stichwort. |
| **Anzeige im Dashboard** | Beispielkarte `lovelace/resqio-alarm-card.yaml`: Alarm, Stichwort, Einsatzort und Fahrzeugstatus auf einem Wandtablet. |
| **Hinweis bei Wartung und Mängeln** | Die Anzahl offener Wartungen und Mängel steht als Sensor bereit, zum Beispiel für eine Benachrichtigung oder eine Ampel im Hausflur. |

### Zu Hause

- **Licht oder Ansage bei einem Alarm Ihrer Feuerwehr**, zum Beispiel das Flurlicht oder eine Durchsage, damit Sie den Alarm sicher bemerken.
- Hinweis: Eine **persönliche Anbindung** (nur Ihr eigener Alarm) folgt später. Derzeit erhalten Sie den Zugang **pro Feuerwehr**. Sie sehen also die Alarme der freigegebenen Feuerwehr.

## Das brauchen Sie

- Home Assistant 2024.11 oder neuer
- Einen RESQIO-Zugang für Ihre Feuerwehr. Ihr Administrator legt ihn in RESQIO unter **Enterprise → Home Assistant** an und bestimmt dort, welche Daten Sie sehen.

## Installation über HACS

HACS ist der Store für zusätzliche Integrationen in Home Assistant. Ist HACS bei Ihnen noch nicht installiert, finden Sie die Anleitung auf [hacs.xyz](https://hacs.xyz/docs/use/download/download/).

**Schnellweg:** Der Knopf oben öffnet die Integration direkt in Ihrem HACS.

**Oder von Hand:**

1. In Home Assistant **HACS** öffnen.
2. Oben rechts auf die drei Punkte → **Benutzerdefinierte Repositories**.
3. Als Adresse `https://github.com/merlin2533/RESQIO-HomeAssistant` eintragen, als Kategorie **Integration** wählen, auf **Hinzufügen** klicken.
4. **RESQIO** in HACS suchen und auf **Herunterladen** klicken.
5. Home Assistant **neu starten** (*Einstellungen → System → Neu starten*).

**Ohne HACS:** Den Ordner `custom_components/resqio` aus diesem Repository in den Ordner `custom_components` Ihrer Home-Assistant-Installation kopieren und neu starten.

## Einrichtung mit Kopplungscode

1. In RESQIO unter **Enterprise → Home Assistant** den Zugang öffnen und **Zugang koppeln** wählen. Es erscheint ein Code, der 10 Minuten gültig ist.
2. In Home Assistant: **Einstellungen → Geräte & Dienste → Integration hinzufügen → RESQIO**.
3. Adresse Ihres RESQIO-Servers und den Code eintragen. Fertig.

Der Code funktioniert nur einmal. Wenn etwas schiefgeht, erzeugen Sie in RESQIO einfach einen neuen.

Haben Sie mehrere Feuerwehren freigegeben, erscheint für jede ein eigenes Gerät.

**Neu koppeln:** Hat Ihr Administrator den Zugang gesperrt oder erneuert, meldet Home Assistant das als Reparaturhinweis. Dort geben Sie einen neuen Code ein. Auch nach einer geänderten Freigabe können Sie jederzeit neu koppeln: *Geräte & Dienste → RESQIO → ⋮ → Neu konfigurieren*.

## Verbindung und Zuverlässigkeit

- **Push statt Abfragen:** Die Integration hält eine ausgehende MQTT-Verbindung zum RESQIO-Server. Ein Alarm kommt sofort an. Home Assistant muss dafür nicht von außen erreichbar sein.
- **Kurze Unterbrechungen gehen nicht verloren:** Die Verbindung nutzt eine persistente Sitzung. Fällt das Netz für bis zu 2 Minuten aus, liefert der Server verpasste Alarmmeldungen nach. Nach einem Neustart von Home Assistant oder längerem Ausfall werden nachgelieferte Alarme bewusst **nicht** mehr als neuer Alarm behandelt. So öffnet sich kein Tor wegen eines Alarms von gestern.
- **Gesperrte MQTT-Ports:** Blockiert Ihr Netz die Ports 1883 und 8883, kann der RESQIO-Server MQTT über **WebSockets** auf dem normalen HTTPS-Port anbieten (`broker_transport: websockets`, Pfad `ws_path`). Bei der Kopplung übernimmt die Integration das aus der Serverantwort. Bei manueller Einrichtung wählen Sie *Transport* aus.
- **Ausfall bemerken:** Ist der Server länger als 10 Minuten nicht erreichbar, zeigt Home Assistant einen Reparaturhinweis an. Der Sensor *Verbindung* zeigt den aktuellen Stand und eignet sich für eine Benachrichtigung.

## Was Sie sehen

Ihr Administrator wählt in RESQIO, welche Daten gesendet werden. Nicht freigegebene Daten tauchen in Home Assistant gar nicht erst auf.

| Bereich | Beispiele |
|---|---|
| Alarm | Alarm aktiv, Stichwort, Alarmzeit, Kategorie |
| Einsatz | Einsatzort, Position auf der Karte, Alarmtext |
| Fahrzeuge | Status je Fahrzeug, Anzahl ausgerückt |
| Personal | nur Zahlen: Zusagen, Absagen, anwesend |
| Wartung und Mängel | Anzahl offener Wartungen und Mängel, nach Kategorie |
| Veranstaltungen | Kalender mit den nächsten Terminen |
| Reservierungen | Kalender je Fahrzeug und für die ganze Wehr |
| Weiteres | Pegelstände, Neuigkeiten, Straßensperren, kommende Veranstaltungen (diese Sensoren sind zunächst **deaktiviert**; aktivieren Sie sie bei Bedarf unter *Geräte & Dienste → RESQIO → Entitäten*) |
| Diagnose | *Verbindung* (Home Assistant ↔ RESQIO), *Letzte Nachricht*, *Wiederverbindungen* (deaktiviert) |

## Blueprints

Blueprints sind fertige Automationen. Sie werden **nicht automatisch** installiert. Mit einem Klick importieren Sie die gewünschten in Ihr Home Assistant:

| Blueprint | Import |
|---|---|
| Gerätehaus-Tor pro Fahrzeug öffnen | [![Importieren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://raw.githubusercontent.com/merlin2533/RESQIO-HomeAssistant/main/blueprints/automation/resqio/geraetehaus_tor_pro_fahrzeug.yaml) |
| Tor öffnen bei Alarm | [![Importieren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://raw.githubusercontent.com/merlin2533/RESQIO-HomeAssistant/main/blueprints/automation/resqio/tor_oeffnen_bei_alarm.yaml) |
| Gerätehaus-Licht bei Alarm | [![Importieren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://raw.githubusercontent.com/merlin2533/RESQIO-HomeAssistant/main/blueprints/automation/resqio/geraetehaus_licht_bei_alarm.yaml) |
| Licht über KNX bei Alarm | [![Importieren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://raw.githubusercontent.com/merlin2533/RESQIO-HomeAssistant/main/blueprints/automation/resqio/licht_ueber_knx_bei_alarm.yaml) |
| Benachrichtigung bei Alarm (Handy, mit Stichwort-Filter) | [![Importieren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://raw.githubusercontent.com/merlin2533/RESQIO-HomeAssistant/main/blueprints/automation/resqio/alarm_benachrichtigung.yaml) |
| Ansage mit Stichwort | [![Importieren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://raw.githubusercontent.com/merlin2533/RESQIO-HomeAssistant/main/blueprints/automation/resqio/ansage_mit_stichwort.yaml) |

Nach dem Import finden Sie sie unter **Einstellungen → Automatisierungen & Szenen → Blueprints**.

**Hinweis zu KNX:** Home Assistant steuert Ihre KNX-Anlage über die KNX-Integration von Home Assistant. Diese müssen Sie dort einrichten. RESQIO spricht nicht selbst mit KNX.

Eine Beispielkarte für Ihr Dashboard liegt in `lovelace/resqio-alarm-card.yaml`.

## Datenschutz

- **Personenbezogene Felder werden nicht übertragen.** Beim Personal gibt es nur Zahlen, Reservierungen zeigen nur den Zeitraum.
- Freitexte wie Titel, Kurztext, Einsatzort und Alarmtext **können Namen enthalten**. Diese Bereiche sind deshalb standardmäßig aus und müssen von Ihrem Administrator ausdrücklich freigegeben werden.
- Alarmdaten verschwinden standardmäßig **2 Stunden nach der letzten (Nach-)Alarmierung**, bei Einsatzende früher. Die Frist ist einstellbar.
- Nutzen Sie Home Assistant Cloud (Nabu Casa) oder andere Cloud-Dienste, können die Daten darüber zu Dritten gelangen.
- Ihr Administrator kann den Zugang in RESQIO jederzeit sperren oder neu koppeln. Geben Sie ein Gerät ab oder verkaufen es, lassen Sie den Zugang sperren.

## Updates

Neue Versionen erscheinen automatisch als **Release** in diesem Repository (Versionsnummer `0.8.x` und höher, jede Änderung zählt hoch). HACS meldet sie selbst: Sie klicken auf **Aktualisieren** und starten Home Assistant danach neu.

## Hilfe

- **Verbindung klappt nicht:** Stimmen Adresse und Code? Ist der Server aus Ihrem Netz erreichbar? Im Zweifel in RESQIO einen neuen Code erzeugen.
- **Zugang abgelehnt:** Ihr Administrator hat ihn eventuell gesperrt oder erneuert. Home Assistant bietet dann **Neu koppeln** an (neuer Code).
- **Es fehlen Angaben:** Der Administrator muss den jeweiligen Bereich in RESQIO freigeben. Danach hilft *Neu konfigurieren*.
- **Weiterhin Probleme:** *Geräte & Dienste → RESQIO → Diagnosedaten herunterladen* und an Ihren Administrator weitergeben. Zugangsdaten sind darin entfernt. Fehler melden Sie unter [Issues](https://github.com/merlin2533/RESQIO-HomeAssistant/issues).

## Lizenz

Apache License 2.0 (siehe `LICENSE`). Die Integration darf frei genutzt und verändert werden. Bei jeder Weitergabe müssen die Lizenz und der Hinweis auf **RESQIO** (Datei `NOTICE`) erhalten bleiben.

## Unterstützen

Die Integration ist kostenlos. Wenn sie Ihnen hilft und Sie die Weiterentwicklung unterstützen möchten, freue ich mich über einen Kaffee:

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-unterst%C3%BCtzen-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/merlin2533)

# RESQIO für Home Assistant

Diese Integration zeigt in Home Assistant den Zustand Ihrer Feuerwehr aus RESQIO an:
Alarm, Einsatzdaten, Fahrzeugstatus, Wartungen und Mängel, Veranstaltungen,
Reservierungen und Straßensperrungen. Damit lassen sich Automationen auslösen, zum
Beispiel Gerätehaus-Licht, eine Sprachansage mit dem Stichwort oder ein Tor, das sich öffnet.

**Die Integration liest nur.** Sie veröffentlicht nichts in RESQIO und löst keine Alarme aus.
Die Daten kommen über MQTT vom RESQIO-Server. Home Assistant verbindet sich selbst mit dem
Server, eine öffentliche Adresse für Home Assistant ist nicht nötig.

## Voraussetzungen

- Home Assistant 2024.10 oder neuer (die Blueprints nutzen die Schreibweise `trigger:` und `action:`)
- Die Integration „MQTT“ ist in Home Assistant installiert (sie ist Abhängigkeit; die
  Verbindung zu RESQIO läuft über eigene Zugangsdaten, nicht über Ihren MQTT-Broker in Home Assistant)
- Ein RESQIO-Zugang mit Freigabe für Ihre Wehr. Ihr Administrator legt ihn unter
  *Enterprise → Home Assistant* an. Dort wird auch festgelegt, welche Datengruppen sichtbar sind.

## Installation über HACS

1. HACS öffnen, **Benutzerdefinierte Repositories** wählen.
2. Die Adresse dieses Repositorys eintragen, Kategorie **Integration**.
3. Die Integration „RESQIO“ suchen und installieren.
4. Home Assistant neu starten.

Ohne HACS: den Ordner `custom_components/resqio` in das Verzeichnis `custom_components` Ihrer
Home-Assistant-Installation kopieren und neu starten.

## Einrichtung

*Einstellungen → Geräte & Dienste → Integration hinzufügen → RESQIO.*

### Mit Kopplungscode (empfohlen)

1. In RESQIO unter *Enterprise → Home Assistant* den Zugang anlegen und **Zugang koppeln**
   wählen. Es erscheint ein Code, der 10 Minuten gültig ist.
2. In Home Assistant die Adresse Ihres RESQIO-Servers und den Code eintragen.

Der Code wird beim Speichern verbraucht. Schlägt die Kopplung fehl, erzeugen Sie in RESQIO
einen neuen Code. Home Assistant prüft vor dem Speichern, ob der Broker erreichbar ist und
die Zugangsdaten stimmen.

### Manuell

Wenn der RESQIO-Server von Home Assistant aus nicht erreichbar ist oder keine Integration
genutzt werden kann: Broker-Host, Port, TLS, Benutzername, Passwort, Topic-Wurzel
(Vorgabe `HomeAssistant`) und die Wehr-Kürzel (kommagetrennt, z. B. `hauptwache`) eintragen.
Ein CA-Zertifikat im PEM-Format ist nur nötig, wenn der Server ein eigenes Zertifikat nutzt.
Die Verbindung ist immer mit Benutzername und Passwort gesichert; ein Gerätezertifikat (mTLS)
wird nicht verwendet.

Mehrere Wehren: Jede Wehr erhält ein eigenes Gerät „RESQIO <Wehr>“. Werte verschiedener
Wehren werden nie zusammengeführt.

## Datengruppen

Welche Daten Home Assistant erreichen, legt Ihr RESQIO-Administrator je Zugang fest. Entitäten
entstehen erst, wenn die Daten einer Gruppe tatsächlich eintreffen. Ist eine Gruppe
abgeschaltet, sehen Sie die Entitäten dazu nicht.

| Gruppe | Inhalt | Standard |
|---|---|---|
| Alarm-Kern | Alarm aktiv, Status, Stichwort, Alarmzeit, Kategorie, Alarmereignis | an |
| Verbindung | Bridge online (Heartbeat) | an |
| Einsatzort | Einsatzort als Text | aus |
| Koordinaten | Einsatzposition als Gerätetracker | aus |
| Alarmtext | Text der Leitstelle | aus |
| Fahrzeuge | FMS-Status je Fahrzeug, Anzahl ausgerückt | aus |
| Personal-Zahlen | Zusagen, Vorbehalt, Absagen, ohne Rückmeldung, anwesend (nur Zahlen) | aus |
| Wartungen | offene Wartungen gesamt und je Kategorie | aus |
| Mängel | offene Mängel gesamt, je Kategorie und je Schweregrad | aus |
| Pegel | Pegelstände mit Messwert | aus |
| Veranstaltungen | Kalender und Anzahl der anstehenden Veranstaltungen | aus |
| Reservierungen | Kalender je Fahrzeug und Summe der Wehr | aus |
| Neuigkeiten | neueste Meldung (Titel und Kurztext) | aus |
| Straßensperren | Anzahl und Liste aktiver Sperrungen | aus |
| Übungen | Übungen wie Alarme | aus |

Personen werden nie mit Namen übertragen. Reservierungen zeigen nur den Zeitraum, nicht den
Zweck oder die Person.

## Entitäten (Auszug)

Die Entitäts-IDs entstehen aus dem Gerätenamen und der Bezeichnung, z. B.
`sensor.resqio_hauptwache_stichwort`.

- **binary_sensor**: Alarm aktiv, Bridge online
- **sensor**: Status, Stichwort, Alarmzeit, Kategorie, Einsatzort, Alarmtext,
  Fahrzeuge ausgerückt, je Fahrzeug „<Fahrzeug> FMS“ (Klartext des Status),
  Zusagen, Vorbehalt, Absagen, Ohne Rückmeldung, Anwesend, Wartungen offen gesamt,
  „Wartungen offen: <Kategorie>“, Mängel offen gesamt, „Mängel offen: <Schweregrad>“,
  „Mängel offen: <Kategorie>“, „Pegel <Name>“, Nächste Veranstaltung,
  Anstehende Veranstaltungen, Neueste Meldung, Straßensperrungen
- **device_tracker**: Einsatzposition
- **event**: Alarmereignis (Ereignisse: neu, nachalarmiert, beendet)
- **calendar**: Veranstaltungen, Reservierungen gesamt, „Reservierungen <Fahrzeug>“

Das Alarmereignis löst nur aus, wenn es live ankommt. Beim Start von Home Assistant
löst es nichts aus.

Wenn der Server meldet, dass ein Wert fehlt, ist die Entität **nicht verfügbar**. Der
Zustand bleibt nicht veraltet stehen.

## Heartbeat

Der Server sendet regelmäßig einen Zeitstempel. Ist er älter als 2 Minuten, gilt die
Verbindung als unterbrochen. Die Entität „Bridge online“ und alle davon abhängigen Werte
werden dann nicht verfügbar.

## Blueprints

Unter *Einstellungen → Automatisierungen → Blueprints* finden Sie:

- **Gerätehaus-Licht bei Alarm**: schaltet Licht bei Alarm ein, optional bei Ende aus
- **Ansage mit Stichwort**: spricht das Stichwort über Sprachausgabe (nur bei aktivem Alarm)
- **Tor öffnen bei Alarm**: öffnet Tore bei Alarm, optional mit Verzögerung

## Dashboard

`lovelace/resqio-alarm-card.yaml` enthält eine Beispielkarte. Sie benötigt kein eigenes
JavaScript. Ersetzen Sie die Beispiel-Entitäten durch die Ihrer Wehr.

## Datenschutz

- Die Daten verlassen den RESQIO-Server in Richtung Home Assistant. Ihr Administrator
  entscheidet je Zugang, welche Gruppen gesendet werden.
- Der Alarmtext und der Einsatzort können Namen oder Gesundheitsangaben enthalten.
  Deshalb sind diese Gruppen standardmäßig aus und müssen einzeln bestätigt werden.
- Wenn Sie Home Assistant Cloud (Nabu Casa) oder andere Cloud-Dienste nutzen, gelangen
  die Daten über diese Dienste zu Dritten. Berücksichtigen Sie das bei der Freigabe.
- Die Zugangsdaten stehen in der Konfiguration von Home Assistant. Wenn Sie ein Gerät
  verkaufen oder abgeben, widerrufen Sie den Zugang in RESQIO.
- Ein Zugang lässt sich in RESQIO jederzeit widerrufen oder neu koppeln; die bestehende
  Verbindung wird dann getrennt.

## Fehlersuche

- **Verbindung fehlgeschlagen**: Adresse, Port und TLS prüfen. Ist der Port aus dem
  Gerätehaus-Netz erreichbar? Vom RESQIO-Administrator den Zugang prüfen lassen.
- **Benutzername oder Passwort abgelehnt**: Zugang in RESQIO prüfen oder neu koppeln.
- **Entitäten fehlen**: Die zugehörige Datengruppe muss in RESQIO freigegeben sein und
  Daten senden. Entitäten entstehen erst, wenn Daten eintreffen.
- Diagnosedaten: *Geräte & Dienste → RESQIO → Diagnosedaten herunterladen*. Passwort und
  Benutzername sind darin entfernt.

## Entwicklung

```bash
pip install ruff pytest
ruff check . && ruff format --check .
pytest
```

Die Parser-Logik liegt in `custom_components/resqio/parsing.py` und hat keine Abhängigkeit
von Home Assistant. Die Tests laufen deshalb ohne Home Assistant.

# RESQIO für Home Assistant

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-unterst%C3%BCtzen-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/merlin2533)

Zeigt in Home Assistant, was in Ihrer Feuerwehr gerade los ist: **Alarm mit Stichwort und Uhrzeit**, Fahrzeugstatus, offene Wartungen und Mängel, Veranstaltungen, Fahrzeugreservierungen und mehr. Damit lösen Sie zum Beispiel aus:

- das Licht im Gerätehaus schaltet sich bei Alarm ein,
- eine Sprachansage nennt das Einsatzstichwort,
- Tore öffnen sich automatisch.

Die Integration **liest nur**. Sie ändert nichts in RESQIO und löst keine Alarme aus.

## Das brauchen Sie

- Home Assistant 2024.10 oder neuer
- Einen RESQIO-Zugang für Ihre Feuerwehr. Ihr Administrator legt ihn in RESQIO unter **Enterprise → Home Assistant** an und bestimmt dort, welche Daten Sie sehen.

## Installation

1. In Home Assistant **HACS** öffnen → **Benutzerdefinierte Repositories** → Adresse dieses Repositorys eintragen, Kategorie **Integration**.
2. **RESQIO** suchen und installieren.
3. Home Assistant neu starten.

## Einrichtung

1. In RESQIO unter **Enterprise → Home Assistant** den Zugang öffnen und **Zugang koppeln** wählen. Es erscheint ein Code, der 10 Minuten gültig ist.
2. In Home Assistant: **Einstellungen → Geräte & Dienste → Integration hinzufügen → RESQIO**.
3. Adresse Ihres RESQIO-Servers und den Code eintragen. Fertig.

Der Code funktioniert nur einmal. Wenn etwas schiefgeht, erzeugen Sie in RESQIO einfach einen neuen.

Haben Sie mehrere Feuerwehren freigegeben, erscheint für jede ein eigenes Gerät.

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
| Weiteres | Pegelstände, Neuigkeiten, Straßensperren |

Alarmdaten verschwinden wieder, sobald der Einsatz beendet ist, spätestens nach zwei Stunden.

## Fertige Automationen

Unter **Einstellungen → Automatisierungen → Blueprints** finden Sie:

- **Gerätehaus-Licht bei Alarm**
- **Ansage mit Stichwort**
- **Tor öffnen bei Alarm**

Eine Beispielkarte für Ihr Dashboard liegt in `lovelace/resqio-alarm-card.yaml`.

## Datenschutz

- Es werden **keine Namen von Personen** übertragen. Beim Personal gibt es nur Zahlen, Reservierungen zeigen nur den Zeitraum.
- Einsatzort und Alarmtext können sensible Angaben enthalten. Diese Bereiche sind deshalb standardmäßig aus und müssen von Ihrem Administrator ausdrücklich freigegeben werden.
- Nutzen Sie Home Assistant Cloud (Nabu Casa) oder andere Cloud-Dienste, können die Daten darüber zu Dritten gelangen.
- Ihr Administrator kann den Zugang in RESQIO jederzeit sperren oder neu koppeln. Geben Sie ein Gerät ab oder verkaufen es, lassen Sie den Zugang sperren.

## Hilfe bei Problemen

- **Verbindung klappt nicht:** Stimmen Adresse und Code? Ist der Server aus Ihrem Netz erreichbar? Im Zweifel in RESQIO einen neuen Code erzeugen.
- **Zugang abgelehnt:** Ihr Administrator hat ihn eventuell gesperrt. Neu koppeln lassen.
- **Es fehlen Angaben:** Der Administrator muss den jeweiligen Bereich in RESQIO freigeben.
- **Weiterhin Probleme:** *Geräte & Dienste → RESQIO → Diagnosedaten herunterladen* und an Ihren Administrator weitergeben. Zugangsdaten sind darin entfernt.

## Unterstützen

Die Integration ist kostenlos. Wenn sie Ihnen hilft und Sie die Weiterentwicklung unterstützen möchten, freue ich mich über einen Kaffee:

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-unterst%C3%BCtzen-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/merlin2533)

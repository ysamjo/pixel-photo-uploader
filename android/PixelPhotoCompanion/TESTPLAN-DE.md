# Testplan vor der großen Bibliothek

1. Resilio mit 20 kopierten Testfotos und einem größeren Testvideo befüllen.
2. Während einer laufenden Resilio-Übertragung prüfen, dass `.!sync` nicht als fertige Datei gezählt wird.
3. Prüfen, dass die App erst nach zwei Minuten unveränderter Dateigröße startet.
4. Während Google Fotos hochlädt, muss der Status „warte auf Google-Fotos-Sicherung“ erscheinen.
5. Pixel sperren: Die App darf den Freigabevorgang nicht starten.
6. Pixel entsperren und prüfen, dass „Sicherung abgeschlossen“ zweimal protokolliert wird.
7. Nach der Freigabe prüfen:
   - Originale auf dem Haupthandy bleiben bestehen.
   - Resilio lädt gelöschte Pixel-Dateien nicht erneut herunter.
   - Google Fotos zeigt die Testmedien vollständig an.
   - Die App zählt nur tatsächlich lokal entfernte Dateien als abgeschlossen.
8. Google-Fotos-Sicherung testweise deaktivieren: Die App muss in den Fehlerzustand wechseln und darf nichts freigeben.
9. Freigabebildschirm absichtlich stehen lassen (Knopf nicht berühren, aber auch nicht von der App bestätigen lassen): Die App muss den Menüpunkt sechs Mal neu suchen (Fünf-Minuten-Abstand) und erst danach im Fehlerzustand die Bildschirmtexte nennen. Es darf keine Datei fehlen.
10. Teilfreigabe prüfen: Nach dem Löschen nur eines Teils der Batchdateien muss die App beim nächsten Ticker einen Rückbeleg über genau die fehlenden Dateien schreiben (`remainingCount` = Rest) und den Fehlerzustand nicht als Endstation behalten.
11. Bildschirm dunkel oder Pixel gesperrt: Es darf nichts freigegeben werden; die App wartet und holt Google Fotos erst, wenn das Fenster sichtbar ist.
12. Erst danach einen 5–20-GB-Test aus der Server-Bibliothek durchführen.
13. Google Fotos auf Englisch umstellen und Schritte 3–7 wiederholen: Die Automatik muss entweder weiterlaufen oder nach 30 Minuten mit Bildschirmtexten anhalten — lautloses Stehenbleiben ist ein Fehler.

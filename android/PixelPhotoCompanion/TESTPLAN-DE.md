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
14. Speicherbericht prüfen: Spätestens nach fünf Minuten muss `control/pixel-storage.json` vorliegen und der Uploader den Wert im Web-UI unter „Pixel-Speicher" zeigen. Der freie Speicher in der App muss zu `df /data` per ADB passen.
15. Fehlt `pixel-storage.json`, muss der Uploader weiterarbeiten wie vor 3.3.21 (nur die Batchgröße bindet) — ein fehlender Bericht darf die Queue nie stilllegen. Ebenso ein Bericht, der älter als 30 Minuten ist.
16. Teilkopie aufräumen: Eine Übertragung abbrechen, damit eine `*.!sync`-Datei liegen bleibt. Unter 3 GiB frei und nach über einer Stunde Unberührtheit muss die App sie freigeben und im Bericht als freigegeben ausweisen. Bei einer **laufenden** Übertragung darf sie nichts anfassen.
17. Reserve prüfen: `ReserveGiB` im Web-UI hochsetzen, bis `freeBytes - ReserveGiB` kleiner als die Batchgröße ist. Der Uploader muss den Pass mit der Zeile „handover limited to …" protokollieren und weniger nachlegen als die Batch-Kappe erlaubt.

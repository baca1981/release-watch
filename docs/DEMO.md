# A 90-second client demo

## Preparation

Run `python -m release_watch demo --output demo-output` from the project directory.
For another run, use a new output directory. Open `report-before-retry.html`,
`report.html`, and `webhook-receipts.json` from that directory.

## English presentation

**0–15 seconds — the problem**

“This automation checks a public API for new software releases. It replaces manual
checking with a repeatable process and keeps a record of what happened.”

**15–35 seconds — show the command and results**

“The first check establishes a baseline. Checking the same release again creates
no alert. When the release changes, the application stores an event and attempts
to send it to the configured webhook.”

**35–60 seconds — show recovery**

Open `report-before-retry.html`: one change, one pending alert, one failed attempt.

“Here the receiving service deliberately returned HTTP 503. The event was retained
in SQLite. The next run retried it after the backoff period.”

Open `report.html`: one change, zero pending, two delivery attempts.

“The delivery succeeded without creating a second change event. The event ID is
the same on both requests, so the receiver can deduplicate retries.”

**60–90 seconds — show evidence and scope**

Open `webhook-receipts.json` and point to the 503 and 204 responses.

“This demo uses synthetic release data and a real local HTTP receiver. The actual
source adapter reads GitHub's public API. The project also includes automated tests
for persistence, rollback, failure handling and duplicate suppression. It runs as
a small scheduled command on Windows or Linux.”

Do not describe the demo as a deployed client system or as an external Slack/email
notification. The external destination is a configurable generic JSON webhook.

## Krótka wersja po polsku

„To mała automatyzacja, która sprawdza publiczne API, zapisuje stan i rozpoznaje
zmiany. Pierwszy odczyt ustala punkt odniesienia. Kolejne identyczne odczyty nie
tworzą nowych alertów.

Tutaj pojawiła się nowa wersja, ale odbiorca alertu chwilowo nie działał. Zdarzenie
zostało w bazie. Przy następnym uruchomieniu alert dotarł, z tym samym identyfikatorem.
Raport pokazuje zarówno zmianę, jak i historię dostarczenia.

Demo działa lokalnie na przykładowych danych, przez prawdziwe żądania HTTP. Integracja
z publicznym API jest osobnym adapterem, który można dostosować do danych klienta.
Do projektu dołączone są testy, dokumentacja i instrukcja cyklicznego uruchamiania.”

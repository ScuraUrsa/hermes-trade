# Maszyna scenariuszy dla zdarzeń zaplanowanych (decyzje banków centralnych)

> **Tylko PAPER.** Ten moduł nie łączy się z żadnym brokerem. `PaperExecutor`
> jedynie zapisuje i loguje zlecenia. Podłączenie prawdziwego brokera nastąpi
> dopiero, gdy Filip potwierdzi w wątku: **konto**, **limit kwoty (money cap)**
> oraz **limity strat (dzienny / na zdarzenie)**. Do tego czasu nie dodajemy
> żadnego kodu wysyłającego zlecenia na rynek.

## Po co to jest (i po co nie)

Przewaga szybkościowa liczona w milisekundach/sekundach po publikacji
komunikatu należy do HFT (kolokacja, bezpośrednie feedy, maszynowe czytanie
nagłówków). Nie konkurujemy z tym. Wartość tego modułu to:

1. **Dyscyplina** — plan na każdy scenariusz (CUT / HOLD / HIKE) jest gotowy
   *przed* zdarzeniem, z obowiązkowym stop-lossem i take-profitem (OCO).
   W chwili publikacji nie ma improwizacji.
2. **Logika zaskoczenia względem oczekiwań** — liczy się różnica między
   wynikiem a tym, co rynek wycenił, a nie sama zmiana stopy. Jeśli rynek
   wycenia obniżkę (np. 80%), a bank stopy *utrzymuje*, to jest to
   **jastrzębie zaskoczenie**, mimo że stopa się nie zmieniła. Scenariusz z
   najwyższym prawdopodobieństwem w playbooku = oczekiwanie rynku; plan dla
   scenariusza bez zaskoczenia jest zwykle pusty („nic nie rób”).

## Elementy

Pakiet `src/hermes_trade/events/`:

| Plik | Zawartość |
| --- | --- |
| `models.py` | `ScheduledEvent`, `Scenario`, `BracketLeg` (TradeSignal + TP, stop obowiązkowy), `ScenarioPlan`, `PrepositionedPlan` (własny limit wielkości), `EventPlaybook`, `classify_surprise` |
| `parser.py` | Szybka ścieżka bez LLM: `parse_fomc_statement` (federalreserve.gov), `parse_nbp_communique` („Komunikat po posiedzeniu RPP”) |
| `dispatcher.py` | `ScenarioDispatcher`, `PaperExecutor`, `KillSwitch` |
| `evaluation.py` | Ocena trafności parsera na historycznych komunikatach |
| `loader.py` | Wczytanie playbooków z YAML (`config/events.example.yaml`) |

### Parser (fast path)

- FOMC: szuka wyłącznie zdania decyzyjnego „*the Committee decided to
  lower/maintain/raise the target range for the federal funds rate … to X to Y
  percent*”. Zdania o zdaniach odrębnych („*preferred to lower …*”) są
  ignorowane. Obsługuje zapis `4-1/4`, `1/4`, znaki `¼ ½ ¾`, łączniki
  niełamiące, twarde spacje. Stopa = górna granica przedziału.
- NBP: „*Rada postanowiła obniżyć / pozostawić … bez zmian / podwyższyć stopy
  procentowe NBP*” + „*stopa referencyjna 5,75%*”. Działa także na tekście bez
  polskich znaków.
- Klasyfikacja CUT/HOLD/HIKE względem poprzedniej stopy. Jeśli czasownik i
  zmiana stopy są sprzeczne albo zdania decyzyjnego brak, parser rzuca
  `StatementParseError` i **nic nie jest wysyłane**.

### Dispatcher

- Każde zlecenie wejścia przechodzi przez istniejący `RiskManager`; odrzucenia
  są zwracane z powodem (`DispatchResult.rejected`).
- Zabezpieczenia: kill switch, zgodność banku i poprzedniej stopy z
  playbookiem, okno czasowe (nie przed `scheduled_at`, nie później niż
  `max_delay`, domyślnie 30 min — chroni przed reakcją na nieaktualną stronę
  z komunikatem z poprzedniego posiedzenia), jednokrotne wykonanie na zdarzenie.
- **Pre-positioning**: `dispatch_prepositioned()` otwiera małą pozycję przed
  zdarzeniem na scenariusz, którego się spodziewamy (z własnym limitem
  `max_total_quantity`). Jeśli wynik jest inny, pozycja jest zamykana po
  rynku (wyjście redukujące ryzyko, poza kontrolami wejścia), a następnie
  odpalany jest plan właściwego scenariusza.

### Kill switch

Jeśli istnieje plik `~/.hermes/trade/STOP` (ścieżka konfigurowalna:
`KillSwitch(path)`), dispatcher nie robi **nic** — ani wejść, ani
pre-positioningu, ani zamknięć. Pozycje trzeba wtedy obsłużyć ręcznie.

```bash
touch ~/.hermes/trade/STOP   # zatrzymaj
rm ~/.hermes/trade/STOP      # wznów
```

## Konfiguracja

`config/events.example.yaml` zawiera przykładowe playbooki dla najbliższego
FOMC i posiedzenia RPP. Daty, poprzednie stopy, prawdopodobieństwa i poziomy
stop/TP to **placeholdery oznaczone `TODO verify`** — trzeba je odświeżyć
dzień przed zdarzeniem. Instrumenty: SPY, TLT, EPOL (iShares MSCI Poland w USD
jako zgrubne proxy USD/PLN — brak płynnego ETF-u na samą parę).

## Ocena parsera

```bash
python -m hermes_trade.events.evaluation tests/fixtures/central_bank_statements.yaml
```

Fixtures to krótkie fragmenty prawdziwych komunikatów (Fed 2020–2025,
NBP 2021–2025), odtworzone z pamięci — zdania decyzyjne odpowiadają
oficjalnemu brzmieniu, ale przed poleganiem na nich warto porównać z
oryginałami.

## Ograniczenia i kolejne kroki

- Wielkość ruchu nie jest jeszcze częścią zaskoczenia (np. obniżka o 50 pb
  przy wycenionych 25 pb to też zaskoczenie gołębie) — `ParsedDecision.change_bp`
  jest już dostępne, logika do dodania.
- Brak pobierania komunikatów (fetcher HTTP z weryfikacją daty publikacji).
- **Wolna ścieżka (przyszłość)**: ocena tonu konferencji prasowej / forward
  guidance przez LLM jako drugi, wolniejszy sygnał — nie zastępuje szybkiej
  ścieżki regex, tylko ją uzupełnia.
- Prawdziwy broker: dopiero po potwierdzeniu konta, limitu kwoty i limitów
  strat przez Filipa w wątku.

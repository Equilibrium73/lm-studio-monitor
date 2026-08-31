# LLM VRAM / RAM Monitor

![AI-generated code](https://img.shields.io/badge/AI--generated%20code-Hermes%20Agent-blueviolet)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Platform: Windows](https://img.shields.io/badge/Platform-Windows-0078D6)

> **Transparenz:** Dieses Projekt wurde mit Unterstützung von **Hermes Agent** (eine KI von Nous Research)
> entwickelt. Der Code ist von einem Menschen kuratiert und getestet, aber KI-gestützt entstanden —
> die Korrekturen und Verbesserungen (siehe Git-Historie) sind Teil der Zusammenarbeit.

Native Python/Tkinter-Anwendung im Afterburner-Look. Zeigt geladene LM-Studio-Modelle
und teilt den Speicher (VRAM + DDR5-RAM) in Kategorien auf:

- **Gewichte GPU** (cyan)     – Modell-Gewichte im VRAM (Offload-Anteil)
- **KV-Cache GPU** (orange)   – KV-Cache der Modelle im VRAM
- **Gewichte RAM** (blau)     – Modell-Gewichte im System-RAM (Spillover)
- **KV-Cache RAM** (lila)     – KV-Cache der Modelle im System-RAM (nur wenn
  KV-Offload ausgeschaltet oder nicht genug VRAM)
- **Datei-Mapping (Host)** (stahlblau) – mmap-Seiten der GGUF im RAM: die
  schreibgeschützte Datei-Basis, aus der CUDA beim Offload schöpft. Liegt
  parallel zu den GPU-Gewichten im RAM, ist aber **kein** KV-Cache und **kein**
  Nadelöhr – bei vollem GPU-Offload einfach die Host-Kopie des Modells.
- **Sonstiges** (grau)        – alles andere (Treiber, OS, Spiele, Browser …)

## Starten

```bat
start.bat
```
(oder: `python monitor.py` im Verzeichnis)

## Datenquellen

| Wert | Quelle |
|------|--------|
| Geladene Modelle, Größe, Kontext, Architektur | `lms ps --json` |
| KV-Cache-Größe (theoretisch) | berechnet aus GGUF-Architekturparametern |
| VRAM gesamt/belegt | `nvidia-smi` (NVIDIA) — Fallback AMD/Intel: Registry `qwMemorySize` + GPU-Adapter-Counter |
| RAM gesamt/frei | `Get-CimInstance Win32_OperatingSystem` (PowerShell) |
| GGUF-Architektur (Layer, Köpfe, head_dim) | eigener Parser über `D:\LLM_Models\...` |
| **Echter VRAM pro Prozess** | Windows Performance-Counter `GPU Process Memory → Dedicated Usage` (Get-Counter, **ohne Admin**) |
| **Echtes RAM pro Prozess** | `Get-Process` WorkingSet64 |
| **KV-Offload / GPU-Cap-Konfiguration** | `~/.lmstudio/.internal/hardware-config.json` |

## Echtes Messprinzip (neu, statt reiner Schätzung)

LM Studio meldet **live nicht**, wie viele Layer eines Modells im VRAM bzw. im RAM
liegen. Die GPU-Layer-Aufteilung wird deshalb jetzt **prozessgenau gemessen**:

```
llama-server (echter Inference-Prozess) belegt laut Performance-Counter:
    - XY MB VRAM  (Dedicated Usage)  → das sind Gewichte + KV auf der GPU
    - XY MB RAM   (WorkingSet)       → das sind Gewichte + KV im System-RAM
```

- **Echte Inference-Prozesse** (`llama-server`, `llm_engine`, `llama.cpp`) liefern
  die reale Gewichte-/KV-Basis. Ihre VRAM-Summe wird für die Balken verwendet.
- **LM-Studio-App/UI** (`LM Studio`, ~50 MB VRAM) wird **nicht** als Modell-VRAM
  gezählt — sie wird im Detail-Panel nur informativ ausgewiesen (UI-Rendering).
- **Fallback:** Ist die Prozessmessung nicht verfügbar (z.B. Performance-Counter
  nicht installiert), schätzt der Monitor weiterhin aus der Sensordifferenz
  `VRAM_belegt − Basis`.

Die interne Aufteilung „Gewichte zuerst, dann KV" bleibt: Gewichte haben im VRAM
Priorität, der Rest der gemessenen GPU-Kapazität ist KV-Cache, alles weitere RAM.

## Wichtig: KV-Cache-Auslagerung

Der Monitor liest `hardware-config.json` und warnt, wenn LM Studio den KV-Cache
**nicht** in den VRAM auslagert:

- Wenn `llm.load.offloadKVCacheToGpu = false` → KV-Cache liegt im System-RAM
  (typische Ursache für „Speicher wird nicht ideal zugewiesen").
  Fix in LM Studio: Einstellungen → Hardware → KV-Cache-Auslagerung aktivieren,
  dann die geladene Konfiguration im Monitor neu laden.
- Wenn `load.gpuStrictVramCap = true` → LM Studio hält einen strikten VRAM-Cap
  ein (weniger Offload-Spielraum).

## Einstellungen (in der GUI)

- **KV-Quant (Q4_0/Q4_1/Q5_0/Q5_1/Q8_0/F16):** Element-Breite des KV-Cache.
  Wird **automatisch** aus der llama-server-Kommandozeile erkannt
  (`--cache-type-k/v`) — bei LM Studio meist `q4_0`. Manuell überschreibbar.
- **VRAM-Basis (MB):** Reserve, die nicht dem LLM zugerechnet wird (Treiber +
  LM-Studio-Runtime). Default 400 MB. Erhöhen, wenn „Sonstiges VRAM" zu klein wirkt.
- **RAM-Basis (MB):** Reserve für Windows + Hintergrund (Default 12000 MB).

## Wichtig: Parallelität (`Max Concurrent Predictions`)

LM Studio startet llama.cpp mit `--parallel N` (Prozess-Kommandozeile). **Jeder
parallele Slot bekommt seinen vollen KV-Cache** (`--ctx-size` pro Slot, nicht
geteilt). Der effektive KV-Pool ist also `kv_pro_slot × parallel`.

Echter Fall (Ternary Q2_K, Q4_0-KV):
- 128k Kontext, `parallel 1` → KV ≈ 4,5 GB → passt in den VRAM ✓
- 128k Kontext, `parallel 4` → KV ≈ 17,9 GB → sprengt 16-GB-Chip, läuft in den
  DDR5-RAM über → **massiver Performance-Einbruch**

🡒 Bei langen Kontexten lohnt sich hohe Parallelität nur, wenn der VRAM es
hergibt. Der Monitor erkennt `--parallel` automatisch und rechnet den KV-Pool
entsprechend.

## Hinweis zur KV-Dimension (Qwen)

Bei Qwen-Architekturen (qwen3/qwen35) ist die in GGUF gemeldete `key_length`
die Q-Dimension (z.B. 256); der reale KV-Cache nutzt die **halbe** Dimension
(128). Der Monitor wendet das automatisch an (empirisch verifiziert am
Ternary-Bonsai: gemessen ≈ 4,2 GB pro Slot @128k ≈ Formel 4,46 GB).

## Sliding-Window Attention (SWA)

Viele moderne Modelle (Mistral, Mixtral, **Gemma 2**, **Llama 4**, Cohere
Command-R, …) halten den KV-Cache **nicht** über die volle Kontextlänge, sondern
nur über ein Fenster (`attention.sliding_window`, z.B. 4096 Tokens). Der
effektive KV-Bedarf pro Slot ist dann `min(ctx_size, sliding_window)`.

Der Monitor liest `sliding_window` aus der GGUF und deckelt den KV-Cache
automatisch — sonst würde er bei 128k Kontext + 4k-Fenster den Cache **32×
zu groß** anzeigen. Beispiel: Mistral-7B @128k/q4_0 = **4,5 GB** ohne SWA,
korrekt **~0,14 GB** mit 4k-Fenster.

## KV-Cache-Quantisierung (vollständige Tabelle)

`KV-Quant` in der GUI wird automatisch aus der llama-server-Kommandozeile
(`--cache-type-k/v`) erkannt. Unterstützte Stufen (Bytes/Element, exakt aus
llama.cpp `ggml-common.h`):

| Stufe | B/Element | ~bits | | Stufe | B/Element | ~bits |
|-------|-----------|-------|-|-------|-----------|-------|
| F16   | 2,0000 | 16,0 | | Q3_K  | 0,4297 | 3,4 |
| Q8_1  | 1,1250 | 9,0  | | Q2_K  | 0,3281 | 2,6 |
| Q8_0  | 1,0625 | 8,5  | | IQ4_XS| 0,5313 | 4,3 |
| Q8_K  | 1,1406 | 9,1  | | IQ4_NL| 0,5625 | 4,5 |
| Q6_K  | 0,8203 | 6,6  | | IQ3_S | 0,4297 | 3,4 |
| Q5_K  | 0,6875 | 5,5  | | IQ3_XXS|0,3828| 3,1 |
| Q5_1  | 0,7500 | 6,0  | | IQ2_S | 0,3203 | 2,6 |
| Q5_0  | 0,6875 | 5,5  | | IQ2_XS| 0,2891 | 2,3 |
| Q4_K  | 0,5625 | 4,5  | | IQ2_XXS|0,2578| 2,1 |
| Q4_1  | 0,6250 | 5,0  | | IQ1_S | 0,1953 | 1,6 |
| Q4_0  | 0,5625 | 4,5  | | IQ1_M | 0,2188 | 1,8 |

Trifft der Monitor eine KV-Quant, die nicht in dieser Tabelle steht (neuere
llama.cpp-Stufe), gibt er **deutlich eine Warnung aus** und rechnet
konservativ mit Q4_0 weiter — statt still falsch zu rechnen. Bitte in dem Fall
den Monitor aktualisieren.

## Anpassung: wo liegen deine GGUFs?

Der Monitor findet GGUFs **automatisch** — keine Pfad-Anpassung nötig:
`~/.lmstudio/models`, der LM-Studio-Bundle-Ordner sowie an allen
Windows-Laufwerken C:…Z: ein Ordner `LLM_Models` / `llm_models` / `models` an
der Wurzel (z.B. `D:/LLM_Models`). Liegt dein Modell-Verzeichnis woanders,
ergänze es in `monitor.py` → `_discover_model_roots()`.

## Plattform

Windows (nvidia-smi für NVIDIA; bei AMD/Intel automatisch Hersteller-Fallback
über Registry `qwMemorySize` + GPU-Adapter-Counter). Python 3.11, nur Stdlib +
lokales `gguf_meta.py` (keine pip-Installs nötig).

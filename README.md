# LLM VRAM / RAM Monitor

![AI-generated code](https://img.shields.io/badge/AI--generated%20code-Hermes%20Agent-blueviolet)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Platform: Windows](https://img.shields.io/badge/Platform-Windows-0078D6)

> **Transparency / Transparenz:** This project was developed with the support of **Hermes Agent** (an AI by Nous Research) — human-curated and human-tested, AI-assisted. / Dieses Projekt wurde mit Unterstützung von **Hermes Agent** (einer KI von Nous Research) entwickelt — von einem Menschen kuratiert und getestet, KI-gestützt.

**Language / Sprache:** [🇩🇪 Deutsch](#deutsch) · [🇬🇧 English](#english)

---

# 🇩🇪 Deutsch <a name="deutsch"></a>

## LLM VRAM / RAM Monitor

Eine native Python/Tkinter-Anwendung im Afterburner-Look. Zeigt geladene LM-Studio-Modelle
und teilt deren Speicher (VRAM + Arbeitsspeicher) in Kategorien auf:

- **Gewichte GPU** (cyan)      – Modell-Gewichte im VRAM (Offload-Anteil)
- **KV-Cache GPU** (orange)    – KV-Cache der Modelle im VRAM
- **Gewichte RAM** (blau)      – Modell-Gewichte im System-RAM (Spillover)
- **KV-Cache RAM** (lila)      – KV-Cache der Modelle im System-RAM (nur wenn
  KV-Offload ausgeschaltet oder nicht genug VRAM)
- **Datei-Mapping (Host)** (stahlblau) – mmap-Seiten der GGUF im RAM: die
  schreibgeschützte Datei-Basis, aus der CUDA beim Offload schöpft. Liegt parallel
  zu den GPU-Gewichten im RAM, ist aber **kein** KV-Cache und **kein** Nadelöhr –
  bei vollem GPU-Offload einfach die Host-Kopie des Modells.
- **Sonstiges** (grau)         – alles andere (Treiber, OS, Spiele, Browser …)

> **Kompatibilität:** Das Tool funktioniert mit **jedem System-RAM** (DDR3, DDR4, DDR5 …) —
> es liest die Betriebssystem-Speicherzähler, nicht eine bestimmte RAM-Generation.

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
| VRAM gesamt/belegt | `nvidia-smi` (NVIDIA) — AMD/Intel-Fallback: Registry `qwMemorySize` + GPU-Adapter-Counter |
| RAM gesamt/frei | `Get-CimInstance Win32_OperatingSystem` (PowerShell) |
| GGUF-Architektur (Layer, Köpfe, head_dim) | eigener Parser über `D:\LLM_Models\...` |
| **Echter VRAM pro Prozess** | Windows Performance-Counter `GPU Process Memory → Dedicated Usage` (Get-Counter, **ohne Admin**) |
| **Echtes RAM pro Prozess** | `Get-Process` WorkingSet64 |
| **KV-Offload / GPU-Cap-Konfiguration** | `~/.lmstudio/.internal/hardware-config.json` |

## Echtes Messprinzip (statt reiner Schätzung)

LM Studio meldet **live nicht**, wie viele Layer eines Modells im VRAM bzw. im RAM
liegen. Die GPU-Layer-Aufteilung wird deshalb **prozessgenau gemessen**:

```
llama-server (echter Inference-Prozess) laut Performance-Counter:
    - XY MB VRAM  (Dedicated Usage)  → das sind Gewichte + KV auf der GPU
    - XY MB RAM   (WorkingSet)       → das sind Gewichte + KV im System-RAM
```

- **Echte Inference-Prozesse** (`llama-server`, `llm_engine`, `llama.cpp`) liefern
  die reale Gewichte-/KV-Basis. Ihre VRAM-Summe wird für die Balken verwendet.
- **LM-Studio-App/UI** (`LM Studio`, ~50 MB VRAM) wird **nicht** als Modell-VRAM
  gezählt — sie wird im Detail-Panel nur informativ ausgewiesen (UI-Rendering).
- **Fallback:** Ist die Prozessmessung nicht verfügbar (z.B. Performance-Counter
  nicht installiert), schätzt der Monitor aus der Sensordifferenz `VRAM_belegt − Basis`.

Die interne Aufteilung „Gewichte zuerst, dann KV" bleibt: Gewichte haben im VRAM
Priorität, der Rest der gemessenen GPU-Kapazität ist KV-Cache, alles Weitere geht in den RAM.

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

- **Sprache:** Deutsch / Englisch (Umschalter unten rechts in der GUI).
- **KV-Quant (Q4_0 … F16, 22 Stufen):** Element-Breite des KV-Cache. Wird
  **automatisch** aus der llama-server-Kommandozeile erkannt (`--cache-type-k/v`)
  — bei LM Studio meist `q4_0`. Manuell überschreibbar.
- **VRAM-Basis (MB):** Reserve, die nicht dem LLM zugerechnet wird (Treiber +
  LM-Studio-Runtime). Default 400 MB.
- **RAM-Basis (MB):** Reserve für Windows + Hintergrund (Default 12000 MB).

## Wichtig: Parallelität (`Max Concurrent Predictions`)

LM Studio startet llama.cpp mit `--parallel N` (Prozess-Kommandozeile). **Jeder
parallele Slot bekommt seinen vollen KV-Cache** (`--ctx-size` pro Slot, nicht
geteilt). Der effektive KV-Pool ist also `kv_pro_slot × parallel`.

Echter Fall (Ternary Q2_K, Q4_0-KV):
- 128k Kontext, `parallel 1` → KV ≈ 4,5 GB → passt in den VRAM ✓
- 128k Kontext, `parallel 4` → KV ≈ 17,9 GB → sprengt einen 16-GB-Chip, läuft in
  den System-RAM über → **massiver Performance-Einbruch**

🡒 Bei langen Kontexten lohnt sich hohe Parallelität nur, wenn der VRAM es hergibt.
Der Monitor erkennt `--parallel` automatisch und skaliert den KV-Pool entsprechend.

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
llama.cpp-Stufe), gibt er **deutlich eine Warnung aus** und rechnet konservativ
mit Q4_0 weiter — statt still falsch zu rechnen.

## Anpassung: wo liegen deine GGUFs?

Der Monitor findet GGUFs **automatisch** — keine Pfad-Anpassung nötig:
`~/.lmstudio/models`, der LM-Studio-Bundle-Ordner sowie an allen
Windows-Laufwerken C:…Z: ein Ordner `LLM_Models` / `llm_models` / `models` an
der Wurzel (z.B. `D:/LLM_Models`). Liegt dein Modell-Verzeichnis woanders,
ergänze es in `monitor.py` → `_discover_model_roots()`.

## Plattform

Windows (nvidia-smi für NVIDIA; bei AMD/Intel automatischer herstellerneutraler
Fallback über Registry `qwMemorySize` + GPU-Adapter-Counter). Python 3.11, nur
Stdlib + lokales `gguf_meta.py` (keine pip-Installs nötig).

---

# 🇬🇧 English <a name="english"></a>

## LLM VRAM / RAM Monitor

A native Python/Tkinter application with an Afterburner-style look. Shows loaded LM Studio
models and splits their memory (VRAM + system RAM) into categories:

- **Weights GPU** (cyan)      – model weights in VRAM (offload share)
- **KV-Cache GPU** (orange)   – KV-cache of the models in VRAM
- **Weights RAM** (blue)      – model weights in system RAM (spillover)
- **KV-Cache RAM** (purple)   – KV-cache of the models in system RAM (only when
  KV-offload is off or there isn't enough VRAM)
- **File mapping (Host)** (steel blue) – mmap pages of the GGUF in RAM: the
  read-only file base that CUDA draws from during offload. It sits parallel to the
  GPU weights in RAM, but is **not** a KV-cache and **not** a bottleneck — at full
  GPU offload it's simply the host copy of the model.
- **Other** (gray)           – everything else (drivers, OS, games, browser …)

> **Compatibility:** The tool works with **any system RAM** (DDR3, DDR4, DDR5, …) —
> it reads the OS memory counters, not a specific RAM generation.

## Getting started

```bat
start.bat
```
(or: `python monitor.py` in the directory)

## Data sources

| Value | Source |
|-------|--------|
| Loaded models, size, context, architecture | `lms ps --json` |
| KV-cache size (theoretical) | computed from GGUF architecture params |
| VRAM total/used | `nvidia-smi` (NVIDIA) — AMD/Intel fallback: Registry `qwMemorySize` + GPU adapter counters |
| RAM total/free | `Get-CimInstance Win32_OperatingSystem` (PowerShell) |
| GGUF architecture (layers, heads, head_dim) | own parser over `D:\LLM_Models\...` |
| **Real VRAM per process** | Windows Performance Counter `GPU Process Memory → Dedicated Usage` (Get-Counter, **no admin**) |
| **Real RAM per process** | `Get-Process` WorkingSet64 |
| **KV-offload / GPU-cap config** | `~/.lmstudio/.internal/hardware-config.json` |

## Real measurement principle (instead of pure estimation)

LM Studio does **not** report live how many layers of a model sit in VRAM vs. RAM.
The GPU-layer split is therefore measured **per process**:

```
llama-server (real inference process) according to performance counter:
    - XY MB VRAM  (Dedicated Usage)  → these are weights + KV on the GPU
    - XY MB RAM   (WorkingSet)       → these are weights + KV in system RAM
```

- **Real inference processes** (`llama-server`, `llm_engine`, `llama.cpp`) provide
  the real weights/KV base. Their VRAM sum is used for the bars.
- **LM Studio app/UI** (`LM Studio`, ~50 MB VRAM) is **not** counted as model VRAM —
  it is only shown informatively in the detail panel (UI rendering).
- **Fallback:** If process measurement is unavailable (e.g. performance counter
  not installed), the monitor estimates from the sensor difference `VRAM_used − basis`.

The internal split "weights first, then KV" stays: weights have priority in VRAM,
the rest of the measured GPU capacity is KV-cache, everything beyond that goes to RAM.

## Important: KV-cache offload

The monitor reads `hardware-config.json` and warns when LM Studio does **not**
offload the KV-cache to VRAM:

- If `llm.load.offloadKVCacheToGpu = false` → KV-cache sits in system RAM
  (typical cause of "memory not being allocated ideally").
  Fix in LM Studio: Settings → Hardware → enable KV-cache offload, then reload
  the loaded config in the monitor.
- If `load.gpuStrictVramCap = true` → LM Studio enforces a strict VRAM cap
  (less offload headroom).

## Settings (in the GUI)

- **Language:** German / English (switch at the bottom-right of the GUI).
- **KV-Quant (Q4_0 … F16, 22 levels):** element width of the KV-cache. Auto-detected
  from the llama-server command line (`--cache-type-k/v` — usually `q4_0` with
  LM Studio). Manually overridable.
- **VRAM-Basis (MB):** reserve not attributed to the LLM (driver + LM-Studio
  runtime). Default 400 MB.
- **RAM-Basis (MB):** reserve for Windows + background (default 12000 MB).

## Important: Parallelism (`Max Concurrent Predictions`)

LM Studio launches llama.cpp with `--parallel N` (process command line). **Each
parallel slot gets its full KV-cache** (`--ctx-size` per slot, not shared).
The effective KV pool is therefore `kv_per_slot × parallel`.

Real case (Ternary Q2_K, Q4_0-KV):
- 128k context, `parallel 1` → KV ≈ 4.5 GB → fits in VRAM ✓
- 128k context, `parallel 4` → KV ≈ 17.9 GB → overflows a 16 GB chip, spills into
  system RAM → **massive performance drop**

🡒 With long contexts, high parallelism only pays off if VRAM allows it.
The monitor auto-detects `--parallel` and scales the KV pool accordingly.

## Note on the KV dimension (Qwen)

For Qwen architectures (qwen3/qwen35) the `key_length` reported in GGUF
is the Q dimension (e.g. 256); the real KV-cache uses the **half** dimension
(128). The monitor applies this automatically (empirically verified on the
Ternary Bonsai: measured ≈ 4.2 GB per slot @128k ≈ formula 4.46 GB).

## Sliding-Window Attention (SWA)

Many modern models (Mistral, Mixtral, **Gemma 2**, **Llama 4**, Cohere
Command-R, …) do **not** keep the KV-cache over the full context length, but
only over a window (`attention.sliding_window`, e.g. 4096 tokens). The
effective KV demand per slot is then `min(ctx_size, sliding_window)`.

The monitor reads `sliding_window` from the GGUF and caps the KV-cache
automatically — otherwise it would show the cache **32× too large** with
128k context + a 4k window. Example: Mistral-7B @128k/q4_0 = **4.5 GB** without
SWA, correct **~0.14 GB** with a 4k window.

## KV-cache quantization (full table)

`KV-Quant` in the GUI is auto-detected from the llama-server command line
(`--cache-type-k/v`). Supported levels (bytes/element, exact from
llama.cpp `ggml-common.h`):

| Level | B/elem | ~bits | | Level | B/elem | ~bits |
|-------|--------|-------|-|-------|--------|-------|
| F16   | 2.0000 | 16.0  | | Q3_K  | 0.4297 | 3.4 |
| Q8_1  | 1.1250 | 9.0   | | Q2_K  | 0.3281 | 2.6 |
| Q8_0  | 1.0625 | 8.5   | | IQ4_XS| 0.5313 | 4.3 |
| Q8_K  | 1.1406 | 9.1   | | IQ4_NL| 0.5625 | 4.5 |
| Q6_K  | 0.8203 | 6.6   | | IQ3_S | 0.4297 | 3.4 |
| Q5_K  | 0.6875 | 5.5   | | IQ3_XXS|0.3828| 3.1 |
| Q5_1  | 0.7500 | 6.0   | | IQ2_S | 0.3203 | 2.6 |
| Q5_0  | 0.6875 | 5.5   | | IQ2_XS| 0.2891 | 2.3 |
| Q4_K  | 0.5625 | 4.5   | | IQ2_XXS|0.2578| 2.1 |
| Q4_1  | 0.6250 | 5.0   | | IQ1_S | 0.1953 | 1.6 |
| Q4_0  | 0.5625 | 4.5   | | IQ1_M | 0.2188 | 1.8 |

If the monitor hits a KV-quant not in this table (newer llama.cpp level), it
issues a **clear warning** and continues conservatively with Q4_0 — instead of
silently computing wrong values.

## Customization: where are your GGUFs?

The monitor finds GGUFs **automatically** — no path adjustment needed:
`~/.lmstudio/models`, the LM Studio bundle folder, and on all Windows drives
C:…Z: a `LLM_Models` / `llm_models` / `models` folder at the root (e.g.
`D:/LLM_Models`). If your model directory lives elsewhere, add it in
`monitor.py` → `_discover_model_roots()`.

## Platform

Windows (nvidia-smi for NVIDIA; automatic vendor-agnostic fallback for
AMD/Intel via Registry `qwMemorySize` + GPU adapter counters). Python 3.11,
stdlib only + local `gguf_meta.py` (no pip installs required).

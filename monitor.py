"""
LLM-VRAM-Monitor - native Python/Tkinter-Anwendung (Afterburner-Look).

Zeigt fuer LM Studio (via `lms ps --json`) geladene Modelle an und teilt
den Speicher in Kategorien auf:

  VRAM (Grafikkarte):
    - Modell-Gewichte  (GPU-Offload-Anteil)   [Messung, falls LLM-Prozess da]
    - KV-Cache         (GPU-Anteil)           [berechnet]
    - Sonstiges        (Rest von VRAM)        [nvidia-smi]

  DDR5-RAM (System):
    - Modell-Gewichte  (CPU/Rest-Anteil)      [Messung, falls LLM-Prozess da]
    - KV-Cache         (CPU-Anteil)           [berechnet]
    - Sonstiges        (Rest von RAM)         [Windows]

WICHTIG (Transparenz):
  LM Studio gibt live NICHT aus, wie viele Layer im VRAM bzw. RAM liegen.
  Daher wird die Gewichts-Aufteilung VRAM<->RAM entweder
    (a) ECHT gemessen:  Windows Performance Counter "GPU Process Memory"
        (get_counter) liefert den tatsaechlichen VRAM-Verbrauch pro Prozess
        (z.B. des llama-server / LM-Studio-Prozesses) OHNE Admin-Rechte.
        Zusammen mit Get-Process (WorkingSet = echtes RAM pro Prozess) haben
        wir die echte LLM-Speicherbasis, nicht die Differenz-Gaetung.
    (b) geschaetzt (Fallback): llm_vram = max(0, vram_used - VRAM_BASIS),
        wenn kein LLM-Prozess erkannt wird (z.B. kein Modell geladen).
  KV-Cache wird (typischerweise) zuerst auf der GPU untergebracht,
  der Rest der GPU-Kapazitaet faellt auf die Modell-Gewichte,
  alles weitere liegt im RAM.
  Zusaetzlich wird die LM-Studio-Konfiguration (hardware-config.json)
  ausgelesen: ob der KV-Cache ueberhaupt in den VRAM ausgelagert wird
  (llm.load.offloadKVCacheToGpu) und ob ein striktes VRAM-Cap gilt.
"""

import os
import sys
import json
import subprocess
import tkinter as tk
from tkinter import ttk
from pathlib import Path

import gguf_meta

# ---------------------------------------------------------------------------
# i18n - bilingual (German default / English)
# Alle User-sichtbaren Texte laufen ueber das T()-Dictionary. Aktive Sprache
# wird global in LANG gehalten und ist in der GUI umschaltbar.
# ---------------------------------------------------------------------------
LANG = "de"   # "de" oder "en"

T = {
    "de": {
        "ram_label":        "Arbeitsspeicher (RAM)",
        "legend_w_gpu":      "Gewichte GPU",
        "legend_kv_gpu":     "KV-Cache GPU",
        "legend_w_ram":      "Gewichte RAM",
        "legend_kv_ram":     "KV-Cache RAM",
        "legend_filemap":    "Datei-Mapping (Host)",
        "legend_other":      "Sonstiges",
        "legend_free":       "Frei (Sensor)",
        "always_on_top":     "Immer im Vordergrund",
        "vram_basis":        "VRAM-Basis (MB):",
        "ram_basis":         "RAM-Basis (MB):",
        "kv_quant":          "KV-Quant:",
        "lang_label":        "Sprache:",
        "apply":             "Anwenden",
        "refresh":           "Jetzt aktualisieren",
        "initializing":      "Initialisiere...",
        "unknown_kv_cli":    "⚠ KV-Quant '{ct}' unbekannt — bitte Monitor aktualisieren",
        "unknown_kv_log":    "Unbekannte KV-Quant aus llama-server-CLI: {ct}",
        "error":             "Fehler: {e}",
        "vram_unavail":      "nvidia-smi nicht verfügbar",
        "ram_unavail":       "RAM nicht verfügbar",
        "warn_kv_off":       "⚠ KV-Cache-Auslagerung in VRAM ist AUS (offloadKVCacheToGpu=false) → KV liegt im System-RAM!",
        "warn_kv_missing":   "⚠ KV-Offload-Einstellung (hardware-config.json) nicht gefunden",
        "warn_strict_cap":   "⚠ GPU-Strict-VRAM-Cap aktiv (gpuStrictVramCap=true)",
        "warn_real_proc":    "✔ Echte Prozessmessung aktiv: {x}",
        "sec_models":        "=== GELADENE MODELLE (LM Studio) ===",
        "no_model":          "  (kein Modell geladen)",
        "arch":              "Architektur",
        "weights":           "Gewichte",
        "context":           "Kontext",
        "kv_theo":           "KV theoretisch",
        "layers":            "Layer",
        "kv_heads":          "KV-Köpfe",
        "kv_missing":        " ⚠ GGUF nicht gefunden!",
        "kv_calc_impossible":"    ⚠ KV-Berechnung nicht möglich (GGUF nicht gefunden).",
        "gpu_split":         "    -> GPU: Gewichte {a} | KV {b}  [sensor-basiert]",
        "ram_split":         "    -> RAM: Gewichte {a} | KV {b}  [sensor-basiert]",
        "sec_sensor":        "=== SENSOR-ABGLEICH ===",
        "other_base":        "Sonstiges+Base",
        "free":              "Frei",
        "sec_proc":          "=== ECHTE PROZESSMESSUNG (GPU Process Memory) ===",
        "no_proc_data":      "  (keine Prozessdaten verfügbar)",
        "inf_procs":         "  Inference-Prozesse erkannt: {n}",
        "sum_llm_vram":      "    Σ LLM VRAM: {x}   [wird für die Zuordnung verwendet]",
        "sum_llm_ram":       "    Σ LLM RAM (Priv/committed): {x}",
        "ram_note":          "    (RAM: mmap-Datei-Basis + KV + Compute; WorkingSet unterschätzt bei --no-mmap stark)",
        "no_inf_proc":       "    (kein llama-server/Inference-Prozess aktiv → Schätzung aus Sensordifferenz)",
        "ui_procs":          "  LM-Studio-UI (kein Modell-VRAM, nur UI-Rendering):",
        "other_gpu":         "  Andere GPU-Nutzer (Top 3):",
        "sec_hw":            "=== LM-STUDIO-KONFIG (hardware-config.json) ===",
        "hw_not_found":      "  hardware-config.json nicht gefunden",
        "cfg_vs_reality":    "  ⚠ KONFIG vs. REALITÄT: hardware-config sagt offload={a}, aber der laufende llama-server läuft mit --{b}kv-offload → beide verrechnet. Maßgeblich ist die CLI (Realität).",
        "kv_not_offloaded":  "  => DER KV-CACHE WIRD NICHT IN DEN VRAM AUSGELAGERT.",
        "reason_mem_alloc":  "     Grund für 'Speicher wird nicht ideal zugewiesen'.",
        "fix_lmstudio":      "     Fix in LM Studio: Einstellungen -> Hardware -> 'KV cache offload to GPU' aktivieren (dann hier neu laden).",
        "kv_offload_act":    "  KV-Cache-Offload (Config): AKTIV (in VRAM).",
        "basis_line":        "VRAM-Basis: {a} MB | RAM-Basis: {b} MB | KV-Quant: {c} ({d} B/Elem)",
        "kv_overflow":       "⚠ KV-ÜBERLAUF (KRITISCH): >25% des KV-Cache im System-RAM! KV-BEDARF {a} → VRAM-Platz {b} → {c} im RAM",
        "overflow_perf":     "    → Performance-Einbruch bei langem Kontext zu erwarten.",
        "overflow_fix1":     "    → Kontext verkleinern, Parallelität senken oder ein",
        "overflow_fix2":     "      kleineres/quantisierteres Modell wählen.",
        "kv_ram_small":      "ℹ KV klein im RAM (marginal, unter 25% des Bedarfs): {x} — bei 96 GB RAM praktisch ohne Performance-Auswirkung.",
        "sec_cli":           "=== ECHTE llama.cpp-PARAMETER (aus llama-server CLI) ===",
        "offload_layers":    "    → Offload: {x} Schichten auf der GPU",
        "moe_all_gpu":       "    → MoE-Experten: ALLE auf der GPU (separat von Attention-Layern)",
        "moe_cpu":           "    → MoE-Experten: {x} Layer auf der CPU, Rest auf GPU",
        "kv_lies_in":        "    → KV-Cache liegt im ",
        "ram_deliberate":    "System-RAM (bewusst!)",
        "status_updated":    "Aktualisiert · {n} Modell(e) geladen",
        "kv_quant_unknown":  "Unbekannte KV-Quant '{kv_mode}' — falle auf Q4_0 zurück. Bitte Monitor aktualisieren.",
        "seg_other_vram":    "Sonstiges (VRAM)",
        "seg_other_ram":     "Sonstiges (RAM)",
        "seg_free_vram":     "Frei (VRAM)",
        "seg_free_ram":      "Frei (RAM)",
        "seg_filemap":       "Datei-Mapping (Host-Gewichte)",
    },
    "en": {
        "ram_label":        "System RAM",
        "legend_w_gpu":      "Weights GPU",
        "legend_kv_gpu":     "KV-Cache GPU",
        "legend_w_ram":      "Weights RAM",
        "legend_kv_ram":     "KV-Cache RAM",
        "legend_filemap":    "File mapping (Host)",
        "legend_other":      "Other",
        "legend_free":       "Free (sensor)",
        "always_on_top":     "Always on top",
        "vram_basis":        "VRAM base (MB):",
        "ram_basis":         "RAM base (MB):",
        "kv_quant":          "KV-Quant:",
        "lang_label":        "Language:",
        "apply":             "Apply",
        "refresh":           "Refresh now",
        "initializing":      "Initializing...",
        "unknown_kv_cli":    "⚠ Unknown KV-quant '{ct}' — please update the monitor",
        "unknown_kv_log":    "Unknown KV-quant from llama-server CLI: {ct}",
        "error":             "Error: {e}",
        "vram_unavail":      "nvidia-smi not available",
        "ram_unavail":       "RAM not available",
        "warn_kv_off":       "⚠ KV-cache offload to VRAM is OFF (offloadKVCacheToGpu=false) → KV sits in system RAM!",
        "warn_kv_missing":   "⚠ KV-offload setting (hardware-config.json) not found",
        "warn_strict_cap":   "⚠ GPU strict VRAM cap active (gpuStrictVramCap=true)",
        "warn_real_proc":    "✔ Real process measurement active: {x}",
        "sec_models":        "=== LOADED MODELS (LM Studio) ===",
        "no_model":          "  (no model loaded)",
        "arch":              "Architecture",
        "weights":           "Weights",
        "context":           "Context",
        "kv_theo":           "KV theoretical",
        "layers":            "layers",
        "kv_heads":          "KV heads",
        "kv_missing":        " ⚠ GGUF not found!",
        "kv_calc_impossible":"    ⚠ KV computation not possible (GGUF not found).",
        "gpu_split":         "    -> GPU: Weights {a} | KV {b}  [sensor-based]",
        "ram_split":         "    -> RAM: Weights {a} | KV {b}  [sensor-based]",
        "sec_sensor":        "=== SENSOR RECONCILIATION ===",
        "other_base":        "Other+base",
        "free":              "Free",
        "sec_proc":          "=== REAL PROCESS MEASUREMENT (GPU Process Memory) ===",
        "no_proc_data":      "  (no process data available)",
        "inf_procs":         "  Inference processes detected: {n}",
        "sum_llm_vram":      "    Σ LLM VRAM: {x}   [used for allocation]",
        "sum_llm_ram":       "    Σ LLM RAM (private/committed): {x}",
        "ram_note":          "    (RAM: mmap file base + KV + compute; WorkingSet understates heavily with --no-mmap)",
        "no_inf_proc":       "    (no llama-server/inference process active → estimate from sensor difference)",
        "ui_procs":          "  LM Studio UI (no model VRAM, UI rendering only):",
        "other_gpu":         "  Other GPU users (Top 3):",
        "sec_hw":            "=== LM STUDIO CONFIG (hardware-config.json) ===",
        "hw_not_found":      "  hardware-config.json not found",
        "cfg_vs_reality":    "  ⚠ CONFIG vs. REALITY: hardware-config says offload={a}, but the running llama-server runs with --{b}kv-offload → the two disagree. The CLI (reality) is authoritative.",
        "kv_not_offloaded":  "  => THE KV-CACHE IS NOT OFFLOADED TO VRAM.",
        "reason_mem_alloc":  "     Cause of 'memory not allocated ideally'.",
        "fix_lmstudio":      "     Fix in LM Studio: Settings -> Hardware -> enable 'KV cache offload to GPU' (then reload here).",
        "kv_offload_act":    "  KV-cache offload (config): ACTIVE (in VRAM).",
        "basis_line":        "VRAM base: {a} MB | RAM base: {b} MB | KV-Quant: {c} ({d} B/elem)",
        "kv_overflow":       "⚠ KV OVERFLOW (CRITICAL): >25% of KV-cache in system RAM! KV DEMAND {a} → VRAM room {b} → {c} in RAM",
        "overflow_perf":     "    → Performance drop expected with long context.",
        "overflow_fix1":     "    → Reduce context, lower parallelism, or pick a",
        "overflow_fix2":     "      smaller/more-quantized model.",
        "kv_ram_small":      "ℹ KV small in RAM (marginal, under 25% of demand): {x} — practically no performance impact with 96 GB RAM.",
        "sec_cli":           "=== REAL llama.cpp PARAMETERS (from llama-server CLI) ===",
        "offload_layers":    "    → Offload: {x} layers on the GPU",
        "moe_all_gpu":       "    → MoE experts: ALL on the GPU (separate from attention layers)",
        "moe_cpu":           "    → MoE experts: {x} layers on the CPU, rest on GPU",
        "kv_lies_in":        "    → KV-cache sits in ",
        "ram_deliberate":    "system RAM (deliberately!)",
        "status_updated":    "Updated · {n} model(s) loaded",
        "kv_quant_unknown":  "Unknown KV-quant '{kv_mode}' — falling back to Q4_0. Please update the monitor.",
        "seg_other_vram":    "Other (VRAM)",
        "seg_other_ram":     "Other (RAM)",
        "seg_free_vram":     "Free (VRAM)",
        "seg_free_ram":      "Free (RAM)",
        "seg_filemap":       "File mapping (host weights)",
    },
}


def t(key, **kw):
    """Uebersetzter String in der aktiven Sprache (LANG)."""
    s = T.get(LANG, T["de"]).get(key, key)
    if kw:
        try:
            s = s.format(**kw)
        except Exception:
            pass
    return s

# --------------------------------------------------------------------------
# Farben (Afterburner-inspiriert, dunkles Theme)
# --------------------------------------------------------------------------
BG          = "#15181e"
PANEL       = "#1c2027"
BAR_BG      = "#0e1014"
TEXT        = "#e6e9ef"
MUTED       = "#8b93a1"
GRID        = "#2a2f38"

COLOR_W_VRAM  = "#22d3ee"   # cyan   - Gewichte GPU
COLOR_KV_VRAM = "#fb923c"   # orange - KV GPU
COLOR_W_RAM   = "#3b82f6"   # blue   - Gewichte RAM
COLOR_KV_RAM  = "#a855f7"   # purple - KV RAM
COLOR_MAP     = "#475569"   # steel  - Datei-Mapping (Host-Gewichte, mmap)
COLOR_OTHER   = "#3a3f4a"   # gray   - Sonstiges
COLOR_FREE    = "#1e222b"   # dunkel - Frei (Sensor)
COLOR_WARN    = "#f97316"   # orange - Warnhinweise (Konfig)

# KV-Cache-Quantisierung: Bytes pro KV-Element (K und V zusammen = 2× pro Layer).
# Alle Werte exakt aus llama.cpp (ggml/src/ggml-common.h, static_assert in
# block_q*_K / block_iq*): Bytes pro Block / Elemente pro Block (QK_K = 256
# bzw. QK4_0/QK4_NL = 32). Referenz-Check: Q4_0 = 0.5625, Q8_0 = 1.0625,
# F16 = 2.0 — alle verifiziert gegen die llama.cpp-Quelle (Aug 2026).
# Hinweis: KV_FACTORS ist der Faktor pro EINZELNEM K- oder V-Element. In
# kv_bytes() wird am Ende mit 2 multipliziert (K + V).
KV_FACTORS = {
    # --- F16 (volle Präzision) ---
    "F16":  2.0,
    # --- Legacy-Quants (QK = 32) ---
    "Q8_1": 1.125,     # (2×fp16 + 32×int8) / 32
    "Q8_0": 1.0625,    # (1×fp16 + 32×int8) / 32
    "Q5_1": 0.75,      # (2×fp16 + 32×4bit + 32×1bit) / 32
    "Q5_0": 0.6875,    # (1×fp16 + 32×4bit + 32×1bit) / 32
    "Q4_1": 0.625,     # (2×fp16 + 32×4bit) / 32
    "Q4_0": 0.5625,    # (1×fp16 + 32×4bit) / 32
    # --- K-Quants (QK_K = 256, wichtungsgewichtet) ---
    "Q8_K": 1.140625,  # (1×float + 256×int8 + 16×int16) / 256
    "Q6_K": 0.8203125, # (1×fp16 + 256/16 + 3×256/4) / 256
    "Q5_K": 0.6875,    # (2×fp16 + 12 + 256/2 + 256/8) / 256
    "Q4_K": 0.5625,    # (2×fp16 + 12 + 256/2) / 256
    "Q3_K": 0.4296875, # (1×fp16 + 256/4 + 256/8 + 12) / 256
    "Q2_K": 0.328125,  # (2×fp16 + 256/16 + 256/4) / 256
    # --- IQ-Quants (imatrix, QK_K = 256 außer IQ4_NL = 32) ---
    "IQ4_XS": 0.53125, # (1×fp16 + 2 + 256/64 + 256/2) / 256
    "IQ4_NL": 0.5625,  # (1×fp16 + 32/2) / 32
    "IQ3_S":  0.4296875, # (1×fp16 + 13×256/32 + 4) / 256
    "IQ3_XXS": 0.3828125, # (1×fp16 + 3×256/8) / 256
    "IQ2_S":  0.3203125, # (1×fp16 + 256/4 + 256/16) / 256
    "IQ2_XS": 0.2890625, # (1×fp16 + 256/8×2 + 256/32) / 256
    "IQ2_XXS": 0.2578125, # (1×fp16 + 256/8×2) / 256
    "IQ1_S":  0.1953125, # (1×fp16 + 256/8 + 256/16) / 256
    "IQ1_M":  0.21875,  # (256/8 + 256/16 + 256/32) / 256
}
# Bekannte llama.cpp-KV-Quant-Namen (für Warnung bei unbekanntem Wert aus der
# llama-server-CLI). Gross-/Kleinschreibung wird normalisiert verglichen.
KNOWN_KV_QUANTS = set(k.upper() for k in KV_FACTORS)

# --------------------------------------------------------------------------
# Datenquellen
# --------------------------------------------------------------------------
def _discover_model_roots():
    """Auto-Erkennung der GGUF-Suchverzeichnisse — portabel für Fremdnutzer.

    Statt harter User-Pfade werden Standard-Orte sowie (unter Windows) alle
    Laufwerke C:..Z: mit einem 'LLM_Models'-Ordner an der Wurzel einbezogen.
    So funktioniert der Monitor auf fremden Rechnern ohne Pfad-Anpassung.
    """
    home = Path.home()
    roots = [
        home / ".lmstudio" / "models",
        home / ".lmstudio" / ".internal" / "bundled-models",
        home / "AppData" / "Local" / "Programs" / "LM Studio"
             / "resources" / "app" / ".webpack" / "bin" / "bundled-models",
        # Häufiges manuelles Modell-Verzeichnis an Laufwerkswurzel (D:/LLM_Models …)
        Path("D:/LLM_Models"),
        Path("E:/LLM_Models"),
    ]
    # Unter Windows: alle Laufwerke C:..Z: mit 'LLM_Models' an der Wurzel scannen
    if os.name == "nt":
        for d in range(ord("C"), ord("Z") + 1):
            drive = f"{chr(d)}:/"
            for cand in (Path(drive) / "LLM_Models",
                        Path(drive) / "llm_models",
                        Path(drive) / "models"):
                if cand not in roots:
                    roots.append(cand)
    # Doppelte + nicht existierende entfernen (Existenz erst beim Scan prüfen)
    seen = set()
    out = []
    for r in roots:
        try:
            k = str(r).lower()
        except Exception:
            continue
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


MODELS_ROOTS = _discover_model_roots()
GGUF_CACHE = {}
_GGUF_INDEX = None

_HW_CONFIG_PATH = Path.home() / ".lmstudio" / ".internal" / "hardware-config.json"


def _build_gguf_index():
    """Einmaliger Scan aller .gguf-Dateien unter den Model-Roots (mit Cache)."""
    global _GGUF_INDEX
    if _GGUF_INDEX is not None:
        return _GGUF_INDEX
    _GGUF_INDEX = []
    for root in MODELS_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.gguf"):
            # mmproj-Dateien überspringen (sind Vision-Projektoren, keine LLMs)
            if p.name.lower().startswith("mmproj"):
                continue
            try:
                size = p.stat().st_size
            except Exception:
                size = 0
            _GGUF_INDEX.append({
                "path": str(p),
                "name": p.name,
                "parent": p.parent.name,
                "size": size,
            })
    return _GGUF_INDEX


def _score_gguf(entry, model_key, arch_name, quant_bits, size_bytes):
    """Score wie gut eine GGUF-Datei zum geladenen Modell passt."""
    path_lower = (entry["name"] + " " + entry["parent"]).lower()
    key_lower = (model_key or "").lower()
    score = 0

    # Keyword-Überlappung
    keywords = [w for w in key_lower.replace("/", " ").replace("-", " ").replace("_", " ").split()
                if len(w) >= 2 and w not in ("gguf", "qat", "it")]
    for kw in keywords:
        if kw in path_lower:
            score += 10
        elif kw[:3] in path_lower:
            score += 3

    # Architektur-Treffer (z.B. "gemma" im Pfad)
    if arch_name and arch_name.lower() in path_lower:
        score += 15

    # Größen-Proximity (sizeBytes aus lms ps ≈ Dateigröße bei Q4_0 oft leicht abweichend)
    if size_bytes and entry["size"] > 0:
        ratio = min(size_bytes, entry["size"]) / max(size_bytes, entry["size"])
        if ratio > 0.85:
            score += 20
        elif ratio > 0.6:
            score += 8

    return score


def find_gguf(path_rel, model_key="", arch_name="", quant_bits=0, size_bytes=0):
    """Findet die GGUF-Datei für ein geladenes Modell.
    Strategie: 1) exakter Pfad, 2) Keyword+Architektur+Größen-Matching."""
    cache_key = path_rel or model_key
    if cache_key in GGUF_CACHE:
        return GGUF_CACHE[cache_key]

    result = None

    # 1) Exakter Pfad (wenn path_rel auf eine .gguf-Datei zeigt)
    if path_rel and path_rel.endswith(".gguf"):
        for root in MODELS_ROOTS:
            if not root.exists():
                continue
            candidate = root / path_rel
            if candidate.exists():
                result = str(candidate)
                break
            # Basename-Fallback
            basename = os.path.basename(path_rel)
            for p in root.rglob(basename):
                result = str(p)
                break
            if result:
                break

    # 2) Keyword + Architektur + Größen-Matching
    if not result:
        index = _build_gguf_index()
        best_score = 0
        best_entry = None
        for entry in index:
            s = _score_gguf(entry, model_key, arch_name, quant_bits, size_bytes)
            if s > best_score:
                best_score = s
                best_entry = entry
        if best_entry and best_score >= 15:
            result = best_entry["path"]

    GGUF_CACHE[cache_key] = result
    return result


def arch_for(path_rel, model_key, ctx_len, arch_name, quant_bits, size_bytes):
    """GGUF-Metadaten laden mit multi-Strategie-Suche."""
    params = None
    gpath = find_gguf(path_rel, model_key, arch_name, quant_bits, size_bytes)
    if gpath:
        try:
            g = gguf_meta.GGUFMeta(gpath)
            params = g.arch_params()
        except Exception:
            params = None
    if params is None:
        params = {"architecture": arch_name, "n_layers": None,
                  "n_head_kv": None, "head_dim": None}
    if params.get("context_length") is None:
        params["context_length"] = ctx_len
    return params


def get_vram():
    """VRAM-Gesamt/belegt. Bevorzugt nvidia-smi (exakt, inkl. free).

    Fallback (AMD/Intel, kein nvidia-smi):
      - Gesamt:   Registry HardwareInformation.qwMemorySize (64-bit, WDDM).
      - Belegt:   Performance Counter 'GPU Adapter Memory(*)\\Dedicated Usage'
                  der phys. GPU mit dem meisten gewidmeten Speicher.
      - Frei:     total - used (naeherung).
    Liefert None, wenn nichts verfuegbar ist.
    """
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
    except Exception:
        out = None
    if out is not None and out.returncode == 0 and out.stdout.strip():
        gpus = []
        for line in out.stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                name, total, used, free = [x.strip() for x in line.split(",")]
            except ValueError:
                continue
            gpus.append({
                "name": name,
                "total": int(float(total)) * 1024 * 1024,
                "used": int(float(used)) * 1024 * 1024,
                "free": int(float(free)) * 1024 * 1024,
            })
        if gpus:
            return gpus[0]
    return _get_vram_windows_fallback()


def _get_vram_windows_fallback():
    """Herstellerneutraler Windows-Fallback ohne nvidia-smi (AMD/Intel).

    Quelle: Registry 'qwMemorySize' (64-Bit, liefert korrekte VRAM-Groesse,
    z.B. 17094934528 = 16303 MB bei RTX 5070 Ti) + GPU Adapter Memory Counter.
    """
    # 1) Gesamt: Registry (fuer den Adapter mit qwMemorySize)
    reg_script = (
        "Get-ChildItem 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\"
        "{4d36e968-e325-11ce-bfc1-08002be10318}' -ErrorAction SilentlyContinue "
        "| ForEach-Object { $p = Get-ItemProperty $_.PSPath -ErrorAction "
        "SilentlyContinue; if ($p.'HardwareInformation.qwMemorySize') { "
        "[PSCustomObject]@{ Desc = $p.DriverDesc; Size = "
        "$p.'HardwareInformation.qwMemorySize' } } } | ConvertTo-Json"
    )
    total = None
    name = "GPU"
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", reg_script],
                             capture_output=True, text=True, timeout=15)
        # WICHTIG: NICHT auf returncode == 0 pruefen — PowerShell setzt den
        # Exit-Code auch bei harmlosen nicht-terminierenden Fehlern (z.B.
        # fehlende Registry-Subkeys) auf 1, obwohl stdout das Ergebnis
        # korrekt enthaelt.
        if out.stdout.strip():
            data = json.loads(out.stdout)
            if isinstance(data, dict):
                data = [data]
            for d in data:
                sz = d.get("Size")
                if sz and int(sz) > 0:
                    total = int(sz)
                    name = d.get("Desc") or name
                    break
    except Exception:
        pass

    # 2) Belegt: GPU Adapter Memory -> Dedicated Usage (summiert je LUID)
    used = None
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "(Get-Counter '\\GPU Adapter Memory(*)\\Dedicated Usage' "
             "-ErrorAction SilentlyContinue).CounterSamples | "
             "Where-Object { $_.CookedValue -gt 0 } | "
             "Measure-Object -Property CookedValue -Sum | Select-Object -ExpandProperty Sum"],
            capture_output=True, text=True, timeout=15)
        if out.returncode == 0 and out.stdout.strip():
            used = int(float(out.stdout.strip()))
    except Exception:
        pass

    if total:
        used = used if used is not None else 0
        return {
            "name": name,
            "total": total,
            "used": used,
            "free": max(0, total - used),
        }
    return None


def get_ram():
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-CimInstance Win32_OperatingSystem | Select-Object "
             "TotalVisibleMemorySize,FreePhysicalMemory | ConvertTo-Json"],
            capture_output=True, text=True, timeout=15)
    except Exception:
        return None
    try:
        d = json.loads(out.stdout)
    except Exception:
        return None
    total = d.get("TotalVisibleMemorySize")
    free = d.get("FreePhysicalMemory")
    if total is None:
        return None
    return {"total": int(total) * 1024, "free": (int(free) if free else 0) * 1024}


# --- NEU: Echte prozessgenaue VRAM/RAM-Messung (ohne Admin-Rechte) ---------
# Quelle: Windows Performance Counter "GPU Process Memory" -> Dedicated Usage.
# Liefert den tatsaechlichen dedizierten VRAM-Verbrauch pro Prozess (in Bytes),
# zusammen mit dem WorkingSet (geparkter physischer RAM) je Prozess.
#
# WICHTIG zur Prozess-Klassifizierung:
#  - Echte INFERENCE-Prozesse (deren VRAM = Gewichte + KV des Modells):
#    * llama-server.*          -> separater llama.cpp-Serverprozess
#    * llm_engine / llama.cpp  -> Engine-Prozesse
#    NUR diese werden fuer die Gewichte-/KV-Messung herangezogen.
#  - App-/UI-Prozesse (LM Studio, lmstudio): deren geringer VRAM (~50 MB)
#    ist UI-Rendering, KEINE Modellgewichte -> nur im Bericht anzeigen.
_INFERENCE_HINTS = ("llama-server", "llm_engine", "llama.cpp", "llama-cli",
                    "llama-quantize", "llama-gguf", "llama-tokenize")
_APP_HINTS = ("lmstudio", "lm-studio", "lm studio", "llmster", "lmstudio.exe")


def get_process_gpu():
    """Liste: {pid, name, vram, ram} fuer alle Prozesse mit VRAM>0.

    Vram  = Dedicated Usage (echter VRAM des Prozesses).
    Ram   = WorkingSet64 (physisch belegter RAM des Prozesses).
    Liefert None bei Fehler.
    """
    script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$c = Get-Counter '\GPU Process Memory(*)\Dedicated Usage' -MaxSamples 1 -ErrorAction SilentlyContinue
if (-not $c) { $c = Get-Counter '\\GPU Process Memory(*)\Dedicated Usage' -MaxSamples 1 -ErrorAction SilentlyContinue }
$rows = @()
if ($c) {
    foreach ($s in $c.CounterSamples) {
        if ($s.CookedValue -le 0) { continue }
        $m = [regex]::Match($s.InstanceName, 'pid_(\d+)_')
        $pidv = if ($m.Success) { [int]$m.Groups[1].Value } else { -1 }
        $p = Get-Process -Id $pidv -ErrorAction SilentlyContinue
        $nm = if ($p) { $p.ProcessName } else { 'unknown' }
        $ws = if ($p) { [int64]$p.WorkingSet64 } else { 0 }
        $priv = if ($p) { [int64]$p.PrivateMemorySize64 } else { 0 }
        $rows += [PSCustomObject]@{
            pid  = $pidv
            name = $nm
            vram = [int64]$s.CookedValue
            ram  = $ws
            priv = $priv
        }
    }
}
# mehrere LUIDs (Multi-GPU/Adapter) pro Prozess zusammenfassen
$agg = @{}
foreach ($r in $rows) {
    $k = "$($r.pid)|$($r.name)"
    if ($agg.ContainsKey($k)) {
        $agg[$k].vram += $r.vram
        # WorkingSet/Private nur einmal zaehlen
        $agg[$k].ram = [math]::Max($agg[$k].ram, $r.ram)
        $agg[$k].priv = [math]::Max($agg[$k].priv, $r.priv)
    } else {
        $agg[$k] = [PSCustomObject]@{ pid=$r.pid; name=$r.name; vram=$r.vram; ram=$r.ram; priv=$r.priv }
    }
}
$agg.Values | Sort-Object vram -Descending | ConvertTo-Json -Compress
"""
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                              "-Command", script],
                             capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    try:
        data = json.loads(out.stdout) if out.stdout.strip() else []
        if isinstance(data, dict):   # einzelner Prozess
            data = [data]
        for d in data:
            d["vram"] = int(d.get("vram", 0))
            d["ram"] = int(d.get("ram", 0))
            d["priv"] = int(d.get("priv", 0))
            d["pid"] = int(d.get("pid", 0))
            d["kind"] = classify_process(d.get("name", ""))
        return data
    except Exception:
        return None


def classify_process(name):
    """'inference' = echter LLM-Serverprozess, 'app' = LM-Studio-UI, '' = sonst."""
    n = (name or "").lower()
    if any(h in n for h in _INFERENCE_HINTS):
        return "inference"
    if any(h in n for h in _APP_HINTS):
        return "app"
    return ""


def is_llm_process(name):
    """Legacy: ist ein Prozessname ueberhaupt LLM-verwandt (inference ODER app)?"""
    return classify_process(name) in ("inference", "app")


def get_hardware_config():
    """Liest hardware-config.json aus (LM Studio): KV-Offload-Flag + Cap.

    Ruestet den active CUDA-Backend-Eintrag aus:
      { offload_kv_gpu: bool, strict_vram_cap: bool, found: bool }
    """
    info = {"offload_kv_gpu": None, "strict_vram_cap": None, "found": False,
            "raw_keys": []}
    try:
        if not _HW_CONFIG_PATH.exists():
            return info
        d = json.loads(_HW_CONFIG_PATH.read_text(encoding="utf-8"))
        info["found"] = True
        entries = d.get("json", [])
        for entry in entries:
            if not (isinstance(entry, list) and len(entry) == 2):
                continue
            backend_name, cfg = entry
            fields = cfg.get("fields", []) if isinstance(cfg, dict) else []
            for f in fields:
                key = f.get("key")
                val = f.get("value")
                info["raw_keys"].append(f"{backend_name}:{key}={val}")
                if key == "llm.load.offloadKVCacheToGpu":
                    info["offload_kv_gpu"] = bool(val)
                elif key == "load.gpuStrictVramCap":
                    info["strict_vram_cap"] = bool(val)
    except Exception:
        pass
    return info


def get_llama_cmdline():
    """Liest die Kommandozeile des laufenden llama-server (nur der Erste).

    Liefert die echten llama.cpp-Parameter, mit denen LM Studio das Modell
    gestartet hat: Kontext, KV-Cache-Quant (cache-type-k/v), KV-Offload,
    n-gpu-layers, mlock/mmap. Das ist die WAHRHEIT statt Schätzung.
    Gibt die raw CommandLine-String zurueck oder None.
    """
    script = ("$p = Get-CimInstance Win32_Process | "
              "Where-Object { $_.Name -like 'llama-server*' -or $_.Name -like 'llama-cli*' } | "
              "Select-Object -First 1; "
              "if ($p) { $p.CommandLine }")
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                              "-Command", script],
                             capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    cli = out.stdout.strip() if out.stdout else ""
    return cli or None


def parse_llama_cmdline(cli):
    """Parst die llama-server-Kommandozeile in aussagekraeftige Parameter.

    Return: dict mit ctx_size, cache_type, kv_offload, gpu_layers,
    no_mmap, mlock, parallel (oder None-felder).
    """
    if not cli:
        return {}
    info = {
        "raw": cli,
        "ctx_size": None,
        "cache_type_k": None,
        "cache_type_v": None,
        "kv_offload": None,     # --kv-offload vorhanden?
        "gpu_layers": None,     # --n-gpu-layers Wert
        "cpu_moe": None,        # --n-cpu-moe Wert (MoE-Experten auf CPU)
        "no_mmap": None,
        "mlock": None,
        "parallel": None,
    }
    args = cli.split()
    i = 0
    n = len(args)

    def _val(i):
        """Wert des naechsten Arguments (i+1) oder '' am Ende."""
        return args[i + 1] if i + 1 < n else ""

    while i < n:
        t = args[i]
        eq = "=" in t
        key, _, val = t.partition("=")
        if t == "--kv-offload":
            info["kv_offload"] = True
        elif t == "--no-kv-offload":
            info["kv_offload"] = False
        elif key == "--no-mmap":
            info["no_mmap"] = True
        elif key == "--mlock":
            info["mlock"] = True
        elif key == "--ctx-size":
            try:
                info["ctx_size"] = int(val if eq else _val(i))
            except Exception:
                info["ctx_size"] = None
            if not eq:
                i += 1
        elif key == "--n-gpu-layers":
            info["gpu_layers"] = val if eq else _val(i)
            if not eq:
                i += 1
        elif key == "--n-cpu-moe":
            info["cpu_moe"] = val if eq else _val(i)
            if not eq:
                i += 1
        elif key == "--cache-type-k":
            info["cache_type_k"] = val if eq else _val(i)
            if not eq:
                i += 1
        elif key == "--cache-type-v":
            info["cache_type_v"] = val if eq else _val(i)
            if not eq:
                i += 1
        elif key == "--parallel":
            try:
                info["parallel"] = int(val if eq else _val(i))
            except Exception:
                info["parallel"] = None
            if not eq:
                i += 1
        i += 1
    return info


def get_loaded_models():
    try:
        out = subprocess.run(["lms", "ps", "--json"],
                             capture_output=True, text=True, timeout=15)
    except Exception:
        return []
    try:
        data = json.loads(out.stdout)
    except Exception:
        return []
    models = []
    for m in data:
        path_rel = m.get("path", "")
        model_key = m.get("modelKey", "")
        ctx = m.get("contextLength") or m.get("maxContextLength") or 0
        arch = m.get("architecture", "")
        quant = m.get("quantization", {})
        quant_bits = quant.get("bits", 0) if isinstance(quant, dict) else 0
        size_bytes = m.get("sizeBytes", 0)
        params = arch_for(path_rel, model_key, ctx, arch, quant_bits, size_bytes)
        models.append({
            "name": m.get("displayName") or m.get("identifier") or m.get("modelKey"),
            "identifier": m.get("identifier"),
            "size_bytes": m.get("sizeBytes", 0),
            "context_length": ctx,
            "type": m.get("type", "llm"),
            "arch_params": params,
        })
    return models


def kv_bytes(params, ctx_len, kv_element_bytes, parallel=1):
    """KV-Cache-Groesse fuer EINEN geladenen Kontext-Slot.

    kv_element_bytes = Bytes pro KV-Element (Quant-Faktor, K+V zusammen = 2×).
    parallel         = Anzahl paralleler Kontext-Slots (--parallel). Jeder Slot
                       bekommt seinen eigenen KV-Cache -> Pool = slot × parallel.
                       WICHTIG (empirisch belegt): LM Studio alokiert pro Slot
                       den vollen --ctx-size, nicht ctx/parallel.
    """
    nl = params.get("n_layers")
    nkv = params.get("n_head_kv")
    hd = params.get("head_dim") or params.get("head_dim_kv")
    if not (nl and hd and ctx_len):
        return None
    nl = int(nl)

    # Sliding-Window Attention (SWA): bei Mistral/Mixtral/Gemma 2/Llama 4/
    # Cohere Command-R … wird der KV-Cache nur ueber ein Fenster der Laenge
    # `sliding_window` gehalten, nicht ueber den vollen Kontext. Der effektive
    # KV-Bedarf pro Slot ist min(ctx_len, sliding_window). Ohne Korrektur
    # wuerde der Monitor den KV-Cache massiv ueberschaetzen (z.B. 32× bei
    # 128k ctx + 4k Fenster).
    sw = params.get("sliding_window")
    effective_ctx = ctx_len
    if sw:
        try:
            sw = int(sw)
            if sw > 0:
                effective_ctx = min(ctx_len, sw)
        except Exception:
            pass
    # (merke effective_ctx fuer die spaetere Multiplikation unten)

    # MLA (Multi-head Latent Attention, z.B. DeepSeek V3/V4, Qwen3.8-Flash-Next
    # / qwen4exp): der KV-Cache lebt im latenten Indexer-Raum
    # (attention.indexer.key_length, z.B. 128), NICHT im vollen
    # attention.key_length (z.B. 512). Ohne Korrektur waere der KV-Bedarf um
    # den Faktor (512/128)=4 ueberschaetzt.
    # WICHTIG (Bugfix Aug 2026): Der Indexer hat VORRANG — die Qwen-hd//2-
    # Regel darf hier NICHT zusaetzlich greifen. qwen4exp startet mit "qwen",
    # daher stapelten sich beide Korrekturen (128 -> 64) und der KV-Bedarf
    # wurde um Faktor 2 UNTERschaetzt (899 MB statt 1.76 GiB bei 72k ctx q8_0).
    hd_indexer = params.get("head_dim_indexer")
    if hd_indexer:
        hd = int(hd_indexer)
    else:
        # Qwen-Familie (qwen3/qwen35): GGUF key_length ist die Q-Dimension (z.B. 256),
        # der echte KV-Cache nutzt aber die halbe Dimension (head_dim_kv). Die
        # Messung (128k parallel1: KV pro Slot ≈ 4.1 GB) bestaetigt hd_kv = hd//2.
        arch = str(params.get("architecture", "")).lower()
        if arch.startswith("qwen") and params.get("head_dim_kv") is None:
            hd = int(hd) // 2
    # n_head_kv kann eine Liste sein (z.B. Gemma 4 A4B mit variierenden KV-Köpfen pro Layer)
    if isinstance(nkv, (list, tuple)):
        if len(nkv) != nl:
            # Länge anpassen: falls Liste kürzer, mit letztem Wert auffüllen; sonst abschneiden
            if len(nkv) < nl:
                nkv = list(nkv) + [nkv[-1]] * (nl - len(nkv))
            else:
                nkv = list(nkv[:nl])
        # head_dim kann auch eine Liste sein
        if isinstance(hd, (list, tuple)):
            if len(hd) != nl:
                hd = list(hd) + [hd[-1]] * (nl - len(hd)) if hd else [0]*nl
            total = sum(int(nkv[i]) * int(hd[i]) for i in range(nl))
        else:
            total = sum(int(n) for n in nkv) * int(hd)
    else:
        if nkv is None:
            return None
        total = nl * int(nkv) * int(hd)
    return int(total) * int(effective_ctx) * 2 * kv_element_bytes * int(parallel or 1)


# --------------------------------------------------------------------------
# Berechnung der Platzierung
# --------------------------------------------------------------------------
def compute(gpu, ram, models, settings, processes=None, hw=None, ram_base=None):
    VRAM_BASE = settings["vram_base_mb"] * 1024 * 1024
    kv_mode = settings.get("kv_mode", "Q8_0")
    # KV-Quant-Faktor: bei unbekanntem/kaputtem Wert NICHT still auf Q8_0
    # zurückfallen, sondern auf Q4_0 (konservativste verbreitete Stufe) und
    # eine Warnung setzen. Sonst zeigt der Monitor eine falsche (zu hohe)
    # KV-Grösse ohne Hinweis.
    KV_EL = KV_FACTORS.get(kv_mode)
    kv_quant_warning = None
    if KV_EL is None:
        kv_quant_warning = t("kv_quant_unknown", kv_mode=kv_mode)
        kv_mode = "Q4_0"
        KV_EL = KV_FACTORS["Q4_0"]
    # RAM-Basis: wenn nicht übergeben, schätze aus Settings
    if ram_base is None:
        ram_base = settings.get("ram_base_mb", 12000) * 1024 * 1024

    vram_total = gpu["total"] if gpu else 0
    vram_used = gpu["used"] if gpu else 0
    vram_free = max(0, vram_total - vram_used)
    ram_total = ram["total"] if ram else 0
    ram_used = (ram["total"] - ram["free"]) if ram else 0
    ram_free = max(0, ram_total - ram_used)

    for m in models:
        m["weights"] = m["size_bytes"]
        ap = m["arch_params"]
        if m["type"] == "embedding":
            m["kv_theoretical"] = 0
            m["kv_missing"] = False
        else:
            kv = kv_bytes(ap, m["context_length"], KV_EL,
                          parallel=settings.get("parallel", 1))
            m["kv_theoretical"] = kv if kv is not None else 0
            m["kv_missing"] = (kv is None)

    total_weights = sum(m["weights"] for m in models)
    total_kv_theoretical = sum(m["kv_theoretical"] for m in models)

    # === ECHTE Prozessmessung (wenn vorhanden) ===
    # NUR echte Inference-Prozesse (llama-server / llm_engine / llama.cpp)
    # liefern die Modellgewichte+KV. Die LM-Studio-App-UI (kind="app") hat nur
    # ~50 MB UI-Rendering und zaehlt NICHT als Gewichte.
    inf_procs = [p for p in (processes or [])
                 if p.get("kind") == "inference" and p.get("vram", 0) > 0]
    llm_vram_meas = sum(p["vram"] for p in inf_procs)
    # RAM: bevorzugt PrivateMemory (committed) — bei --no-mmap ist das die echte
    # Modell-/KV-Belegung; WorkingSet unterschätzt massiv (nl. nur 1 GB vs 17 GB).
    use_priv = any(p.get("priv", 0) > 0 for p in inf_procs)
    llm_ram_meas = sum(p["priv"] for p in inf_procs) if use_priv else sum(p["ram"] for p in inf_procs)
    llm_procs = inf_procs

    app_procs = [p for p in (processes or [])
                 if p.get("kind") == "app" and p.get("vram", 0) > 0]

    # === SENSOR-basierte Schätzung (NUR Fallback bei fehlgeschlagener Messung) ===
    # WICHTIG: Die Sensor-Differenz (vram_used - Basis) summiert ALLE
    # GPU-Prozesse (QmlRenderer, Browser, Hermes-App ...) und ist nur dann
    # aussagekraeftig, wenn wirklich ein llama-server laeuft. Sobald die
    # Prozessmessung erfolgreich war (processes is not None), gilt:
    #   kein Inference-Prozess = kein geladenes Modell = LLM-VRAM 0.
    llm_vram_est = max(0, vram_used - VRAM_BASE)
    llm_ram_est = max(0, ram_used - ram_base)

    if processes is not None and llm_vram_meas == 0 and llm_ram_meas == 0:
        # Prozessmessung ok, aber kein Inference-Prozess aktiv.
        # Nur wenn WIRKLICH kein Modell geladen ist -> 0 (echt).
        # Falls lms ps ein geladenes Modell meldet bzw. Gewichte > 0, aber der
        # Prozess nicht gefunden wurde (eingebetteter Engine-Fall), zurueck auf
        # Sensor-Fallback, damit nichts faelschlich als 0 angezeigt wird.
        if total_weights > 0 and llm_vram_est > 0:
            llm_vram = llm_vram_est
            llm_ram = llm_ram_est
        else:
            llm_vram = 0
            llm_ram = 0
    elif processes is not None:
        # Prozessmessung ok und Inference-Prozess gefunden -> echte Messung
        llm_vram = llm_vram_meas
        llm_ram = llm_ram_meas
    else:
        # Prozessmessung fehlgeschlagen -> alter Sensor-Fallback
        llm_vram = llm_vram_est
        llm_ram = llm_ram_est

    # Gewichte im VRAM: NICHT "alles bis der VRAM voll" — sondern nur der
    # tatsaechlich geladene Offload-Anteil (--n-gpu-layers / n_layers).
    # Bei partiellem Offload (z.B. 35/65) liegen nur ~54% der Gewichte im VRAM,
    # der Rest des llama-server-VRAM gehoert dem KV-Cache.
    n_gpu = settings.get("n_gpu_layers")
    n_layers_total = None
    for m in models:
        nl = m.get("arch_params", {}).get("n_layers")
        if nl:
            n_layers_total = int(nl)
            break
    if n_gpu is not None and n_layers_total:
        try:
            offload_frac = min(1.0, int(n_gpu) / max(1, n_layers_total))
        except Exception:
            offload_frac = 1.0
    else:
        offload_frac = 1.0
    # Gewichte, die laut Offload-Einstellung auf der GPU liegen sollten
    weights_vram_potential = total_weights * offload_frac

    # MoE-Experten-Sonderfall: --n-cpu-moe 0 bedeutet, dass ALLE Experten-
    # Tensoren auf die GPU gelegt werden, getrennt von den Attention-Layern.
    # Bei DeepSeek-V4 (256 Experten) sind die Experten ~96% der Gewichte!
    # n_gpu_layers=0 + n_cpu_moe=0 => Attention auf CPU, ABER Experten auf GPU.
    cpu_moe = settings.get("cpu_moe")
    if cpu_moe is not None:
        try:
            if int(cpu_moe) == 0 and total_weights > 0:
                # Alle Experten auf GPU (so viel wie in den VRAM passt);
                # Attention-Layer bleiben bei offload_frac.
                weights_vram_potential = total_weights  # Experten + Layer
        except Exception:
            pass

    # ... begrenzt durch den tatsaechlich gemessenen llama-server-VRAM
    weights_vram = min(weights_vram_potential, llm_vram)
    weights_ram_total = total_weights - weights_vram

    # === KV-ZUORDNUNG: physikalische Überlauf-Erkennung ===
    # Der llama-server-VRAM (Messung) besteht aus Gewichten + dem KV-Anteil,
    # der tatsaechlich in den VRAM passte.
    #   kv_capacity_vram = llm_vram - weights_vram  (Sensor: realer VRAM-Platz fuer KV)
    #   kv_bedarf        = total_kv_theoretical     (KV fuer geladenen Kontext, exakter Faktor)
    # Wenn der KV-Bedarf GROESSER ist als der VRAM-Platz -> der Ueberschuss liegt
    # im RAM (Ueberlauf bei grossem Kontext!). Unabhaengig vom offload-Flag,
    # denn physikalisch kann nur so viel in den VRAM, wie Platz bietet.
    kv_capacity_vram = max(0.0, llm_vram - weights_vram)
    kv_bedarf = max(0.0, total_kv_theoretical)
    # ECHTER Ueberlauf NUR wenn der KV eigentlich in den VRAM soll
    # (--kv-offload aktiv), aber der Platz nicht reicht. Wenn der User
    # --no-kv-offload gesetzt hat (oder kein CLI bekannt und hw sagt off), dann
    # liegt der KV BEWUSST im RAM -> kein Ueberlauf, sondern Konfiguration.
    # Prioritaet: CLI-Wahrheit (settings["kv_offload"]) > hardware-config > Default true
    kv_offload_cli = settings.get("kv_offload")
    if kv_offload_cli is None:
        kv_offload_cli = (hw.get("offload_kv_gpu", True) if hw else True)
    if kv_offload_cli:
        kv_vram_actual = min(kv_bedarf, kv_capacity_vram)
        kv_ram_actual = max(0.0, kv_bedarf - kv_vram_actual)
        kv_overflow_mb = max(0.0, kv_bedarf - kv_capacity_vram)
        # Abgestufte Bewertung: ganz kleine Reste (z.B. 215 MB bei Q5_1-KV)
        # sind bei 96 GB RAM vernachlaessigbar und kein Performance-Problem.
        # Kritisch wird es erst, wenn ein signifikanter Anteil des KV im RAM liegt.
        if kv_bedarf > 0:
            overflow_frac = kv_overflow_mb / kv_bedarf
        else:
            overflow_frac = 0.0
        kv_overflow = overflow_frac > 0.25          # >25% im RAM -> kritisch
        kv_overflow_marginal = 0 < overflow_frac <= 0.25
    else:
        # --no-kv-offload: KV liegt BEWUSST komplett im RAM (kein Ueberlauf).
        kv_vram_actual = 0.0
        kv_ram_actual = kv_bedarf
        kv_overflow = False
        kv_overflow_marginal = False

    # Prozess-RAM (WorkingSet) = Dateimapping-Host-Seiten (gguf) + KV-RAM +
    # Gewichte-Spillover. Was nach KV-RAM und Gewichte-Overflow uebrig bleibt,
    # ist die mmap-Datei-Kopie (host_map).
    host_map = max(0.0, llm_ram - weights_ram_total - kv_ram_actual)

    # Pro-Modell Aufteilung
    if total_weights > 0:
        for m in models:
            m["w_vram"] = weights_vram * (m["weights"] / total_weights)
            m["w_ram"] = m["weights"] - m["w_vram"]
    else:
        for m in models:
            m["w_vram"] = 0.0
            m["w_ram"] = 0.0

    if total_kv_theoretical > 0:
        for m in models:
            m["kv_vram"] = kv_vram_actual * (m["kv_theoretical"] / total_kv_theoretical)
            m["kv_ram"] = (kv_ram_actual * (m["kv_theoretical"] / total_kv_theoretical)
                           if kv_ram_actual > 0 else 0.0)
    else:
        for m in models:
            m["kv_vram"] = 0.0
            m["kv_ram"] = 0.0

    sonst_vram = max(0, vram_used - kv_vram_actual - weights_vram)
    sonst_ram = max(0, ram_used - kv_ram_actual - weights_ram_total - host_map)

    vram_segs = []
    ram_segs = []
    for m in models:
        if m["w_vram"] > 0:
            vram_segs.append((m["w_vram"], COLOR_W_VRAM, f'{m["name"]} · Gewichte (GPU)'))
        if m["kv_vram"] > 0:
            vram_segs.append((m["kv_vram"], COLOR_KV_VRAM, f'{m["name"]} · KV (GPU)'))
        if m["w_ram"] > 0:
            ram_segs.append((m["w_ram"], COLOR_W_RAM, f'{m["name"]} · Gewichte (RAM)'))
        if m["kv_ram"] > 0 and kv_ram_actual > 0:
            ram_segs.append((m["kv_ram"], COLOR_KV_RAM, f'{m["name"]} · KV (RAM)'))
    if host_map > 0:
        ram_segs.append((host_map, COLOR_MAP, t("seg_filemap")))
    if sonst_vram > 0:
        vram_segs.append((sonst_vram, COLOR_OTHER, t("seg_other_vram")))
    if sonst_ram > 0:
        ram_segs.append((sonst_ram, COLOR_OTHER, t("seg_other_ram")))
    if vram_free > 0 and vram_total > 0:
        vram_segs.append((vram_free, COLOR_FREE, t("seg_free_vram")))
    if ram_free > 0 and ram_total > 0:
        ram_segs.append((ram_free, COLOR_FREE, t("seg_free_ram")))

    return {
        "vram_total": vram_total, "vram_used": vram_used, "vram_free": vram_free,
        "ram_total": ram_total, "ram_used": ram_used, "ram_free": ram_free,
        "models": models, "vram_segs": vram_segs, "ram_segs": ram_segs,
        "llm_vram": llm_vram, "llm_ram": llm_ram,
        "llm_vram_meas": llm_vram_meas, "llm_ram_meas": llm_ram_meas,
        "llm_procs": llm_procs, "app_procs": app_procs,
        "host_map": host_map,
        "total_weights": total_weights, "total_kv_theoretical": total_kv_theoretical,
        "kv_vram_actual": kv_vram_actual, "kv_ram_actual": kv_ram_actual,
        "kv_bedarf": kv_bedarf, "kv_overflow": kv_overflow, "kv_mode": kv_mode,
        "kv_overflow_marginal": kv_overflow_marginal,
        "kv_quant_warning": kv_quant_warning,
    }


# --------------------------------------------------------------------------
# Format-Helfer
# --------------------------------------------------------------------------
def fmt_mb(b):
    b = float(b)
    if b >= 1024 ** 3:
        return f"{b / 1024 ** 3:.2f} GB"
    return f"{b / 1024 ** 2:.0f} MB"


def fmt_pct(part, total):
    if not total:
        return "0%"
    return f"{100.0 * part / total:.1f}%"


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("LLM VRAM / RAM Monitor")
        self.root.configure(bg=BG)
        self.root.geometry("1120x760")
        self.root.resizable(True, True)

        self.settings = {
            "vram_base_mb": 400,     # LM Studio Runtime + Treiber-Reserve
            "ram_base_mb": 12000,    # Windows + Hintergrundprozesse ohne LLM
            "kv_mode": "Q4_0",       # KV-Cache-Quantisierung (Q4_0/Q4_1/Q5_0/Q5_1/Q8_0/F16)
            "interval": 2000,
        }
        self.topmost = tk.BooleanVar(value=False)

        self._build_ui()
        self._poll()

    def _build_ui(self):
        # Titel
        self.title_lbl = tk.Label(self.root, text="LLM VRAM / RAM Monitor",
                                  fg=TEXT, bg=BG, font=("Segoe UI", 14, "bold"))
        self.title_lbl.pack(anchor="w", padx=14, pady=(10, 2))
        self.status = tk.Label(self.root, text=t("initializing"),
                               fg=MUTED, bg=BG, font=("Segoe UI", 9))
        self.status.pack(anchor="w", padx=14, pady=(0, 6))

        # Warnzeile (Konfig-Diagnose)
        self.warn = tk.Label(self.root, text="", fg=COLOR_WARN, bg=BG,
                             font=("Segoe UI", 9, "bold"), anchor="w",
                             justify="left", wraplength=1080)
        self.warn.pack(anchor="w", padx=14, pady=(0, 4))

        # Balken-Bereich
        self.bar_frame = tk.Frame(self.root, bg=BG)
        self.bar_frame.pack(fill="x", padx=14, pady=4)

        self.vram_label = tk.Label(self.bar_frame, text="VRAM", fg=TEXT,
                                   bg=BG, font=("Segoe UI", 11, "bold"))
        self.vram_label.pack(anchor="w")
        self.vram_canvas = tk.Canvas(self.bar_frame, height=34,
                                     bg=BAR_BG, highlightthickness=0)
        self.vram_canvas.pack(fill="x", pady=(2, 8))
        self.vram_text = tk.Label(self.bar_frame, text="", fg=MUTED,
                                  bg=BG, font=("Segoe UI", 9))
        self.vram_text.pack(anchor="e", pady=(0, 6))

        self.ram_label = tk.Label(self.bar_frame, text=t("ram_label"), fg=TEXT,
                                  bg=BG, font=("Segoe UI", 11, "bold"))
        self.ram_label.pack(anchor="w")
        self.ram_canvas = tk.Canvas(self.bar_frame, height=34,
                                    bg=BAR_BG, highlightthickness=0)
        self.ram_canvas.pack(fill="x", pady=(2, 8))
        self.ram_text = tk.Label(self.bar_frame, text="", fg=MUTED,
                                 bg=BG, font=("Segoe UI", 9))
        self.ram_text.pack(anchor="e", pady=(0, 6))

        # Legende (Labels-Referenzen speichern fuer Live-Uebersetzung)
        legend = tk.Frame(self.root, bg=BG)
        legend.pack(anchor="w", padx=14, pady=(0, 4))
        self.legend_items = []
        for color, key in [
            (COLOR_W_VRAM, "legend_w_gpu"),
            (COLOR_KV_VRAM, "legend_kv_gpu"),
            (COLOR_W_RAM, "legend_w_ram"),
            (COLOR_KV_RAM, "legend_kv_ram"),
            (COLOR_MAP, "legend_filemap"),
            (COLOR_OTHER, "legend_other"),
            (COLOR_FREE, "legend_free"),
        ]:
            c = tk.Canvas(legend, width=14, height=14, bg=color,
                          highlightthickness=0)
            c.pack(side="left", padx=(0, 4))
            lbl = tk.Label(legend, text=t(key), fg=MUTED, bg=BG,
                           font=("Segoe UI", 9))
            lbl.pack(side="left", padx=(0, 14))
            self.legend_items.append((lbl, key))

        # Detail-Breakdown
        det_frame = tk.Frame(self.root, bg=PANEL)
        det_frame.pack(fill="both", expand=True, padx=14, pady=(6, 4))
        self.detail = tk.Text(det_frame, bg=PANEL, fg=TEXT,
                              font=("Consolas", 10), relief="flat",
                              state="disabled", wrap="none")
        self.detail.pack(fill="both", expand=True, padx=8, pady=8)

        # Controls
        ctrl = tk.Frame(self.root, bg=BG)
        ctrl.pack(fill="x", padx=14, pady=(4, 10))

        self.cb_topmost = tk.Checkbutton(ctrl, text=t("always_on_top"),
                                         variable=self.topmost,
                                         command=self._apply_topmost,
                                         fg=TEXT, bg=BG, selectcolor=PANEL,
                                         activebackground=BG,
                                         activeforeground=TEXT,
                                         font=("Segoe UI", 9))
        self.cb_topmost.pack(side="left")

        self.lbl_vbase = tk.Label(ctrl, text=t("vram_basis"), fg=MUTED, bg=BG,
                                  font=("Segoe UI", 9))
        self.lbl_vbase.pack(side="left", padx=(14, 2))
        self.e_base = tk.Entry(ctrl, width=7, bg=PANEL, fg=TEXT,
                               insertbackground=TEXT, relief="flat")
        self.e_base.insert(0, str(self.settings["vram_base_mb"]))
        self.e_base.pack(side="left")

        self.lbl_rbase = tk.Label(ctrl, text=t("ram_basis"), fg=MUTED, bg=BG,
                                  font=("Segoe UI", 9))
        self.lbl_rbase.pack(side="left", padx=(12, 2))
        self.e_rbase = tk.Entry(ctrl, width=7, bg=PANEL, fg=TEXT,
                                insertbackground=TEXT, relief="flat")
        self.e_rbase.insert(0, str(self.settings["ram_base_mb"]))
        self.e_rbase.pack(side="left")

        self.lbl_kvq = tk.Label(ctrl, text=t("kv_quant"), fg=MUTED, bg=BG,
                                font=("Segoe UI", 9))
        self.lbl_kvq.pack(side="left", padx=(12, 2))
        self.cb_kv = ttk.Combobox(ctrl, width=6, state="readonly",
                                  values=list(KV_FACTORS.keys()),
                                  font=("Segoe UI", 9))
        self.cb_kv.set(self.settings["kv_mode"])
        self.cb_kv.pack(side="left")

        # Sprach-Umschalter (DE/EN)
        self.lbl_lang = tk.Label(ctrl, text=t("lang_label"), fg=MUTED, bg=BG,
                                 font=("Segoe UI", 9))
        self.lbl_lang.pack(side="left", padx=(14, 2))
        self.cb_lang = ttk.Combobox(ctrl, width=3, state="readonly",
                                    values=["de", "en"], font=("Segoe UI", 9))
        self.cb_lang.set(LANG)
        self.cb_lang.bind("<<ComboboxSelected>>", self._on_lang_change)
        self.cb_lang.pack(side="left")

        self.btn_apply = tk.Button(ctrl, text=t("apply"),
                                   command=self._apply_settings,
                                   bg="#2a2f38", fg=TEXT, relief="flat",
                                   font=("Segoe UI", 9))
        self.btn_apply.pack(side="left", padx=(14, 0))
        self.btn_refresh = tk.Button(ctrl, text=t("refresh"),
                                     command=self._poll,
                                     bg="#2a2f38", fg=TEXT, relief="flat",
                                     font=("Segoe UI", 9))
        self.btn_refresh.pack(side="left", padx=(6, 0))

    def _on_lang_change(self, _evt=None):
        global LANG
        LANG = self.cb_lang.get()
        # Alle statischen Widget-Texte neu setzen
        self.ram_label.configure(text=t("ram_label"))
        for lbl, key in self.legend_items:
            lbl.configure(text=t(key))
        self.cb_topmost.configure(text=t("always_on_top"))
        self.lbl_vbase.configure(text=t("vram_basis"))
        self.lbl_rbase.configure(text=t("ram_basis"))
        self.lbl_kvq.configure(text=t("kv_quant"))
        self.lbl_lang.configure(text=t("lang_label"))
        self.btn_apply.configure(text=t("apply"))
        self.btn_refresh.configure(text=t("refresh"))
        self._poll()   # Detail-Panel + Status direkt neu rendern

    def _apply_topmost(self):
        self.root.wm_attributes("-topmost", self.topmost.get())

    def _apply_settings(self):
        try:
            self.settings["vram_base_mb"] = int(self.e_base.get())
        except Exception:
            pass
        try:
            self.settings["ram_base_mb"] = int(self.e_rbase.get())
        except Exception:
            pass
        try:
            self.settings["kv_mode"] = self.cb_kv.get()
        except Exception:
            pass
        self._poll()

    def _draw_bar(self, canvas, total, segs):
        canvas.delete("all")
        w = canvas.winfo_width() or 700
        h = canvas.winfo_height() or 34
        canvas.create_rectangle(0, 0, w, h, fill=BAR_BG, outline=GRID, width=1)
        if not total or total <= 0:
            return
        cx = 0
        for val, color, _label in segs:
            sw = w * (val / total)
            if sw <= 0:
                continue
            canvas.create_rectangle(cx, 0, cx + sw, h, fill=color,
                                    outline="#000", width=1)
            if sw > 46:
                canvas.create_text(cx + sw / 2, h / 2, text=fmt_mb(val),
                                   fill="#0b0d10",
                                   font=("Segoe UI", 8, "bold"))
            cx += sw

    def _poll(self):
        try:
            gpu = get_vram()
            ram = get_ram()
            models = get_loaded_models()
            processes = get_process_gpu()
            hw = get_hardware_config()

            # Auto-Erkennung der echten llama.cpp-Parameter aus der
            # llama-server-Kommandozeile (WAHRHEIT statt Schätzung).
            cli = get_llama_cmdline()
            cli_parsed = parse_llama_cmdline(cli) if cli else {}
            self.last_cli = cli_parsed
            if cli_parsed.get("cache_type_k"):
                # KV-Quant automatisch: cache-type-k == cache-type-v (fast immer)
                ct = str(cli_parsed["cache_type_k"]).upper()
                if ct in KV_FACTORS:
                    self.cb_kv.set(ct)   # UI-Synk (ohne _apply_settings zu triggern)
                    self.settings["kv_mode"] = ct
                else:
                    # Bekanntes llama.cpp-Quant, aber nicht in unserer Tabelle:
                    # nicht still ignorieren, sondern deutlich warnen.
                    self.status.configure(
                        text=t("unknown_kv_cli", ct=ct))
                    self._log(t("unknown_kv_log", ct=ct))
            # Echte Kontextgröße + Parallelität an models/settings übergeben
            if cli_parsed.get("ctx_size") and models:
                for m in models:
                    if m.get("context_length"):
                        m["context_length"] = cli_parsed["ctx_size"]
            if cli_parsed.get("parallel"):
                self.settings["parallel"] = cli_parsed["parallel"]
            else:
                self.settings["parallel"] = 1
            if cli_parsed.get("kv_offload") is not None:
                self.settings["kv_offload"] = cli_parsed["kv_offload"]
            if cli_parsed.get("gpu_layers") is not None:
                try:
                    self.settings["n_gpu_layers"] = int(cli_parsed["gpu_layers"])
                except Exception:
                    pass
            if cli_parsed.get("cpu_moe") is not None:
                try:
                    self.settings["cpu_moe"] = int(cli_parsed["cpu_moe"])
                except Exception:
                    pass

            data = compute(gpu, ram, models, self.settings, processes=processes, hw=hw)
            self._render(gpu, ram, data, hw, processes)
        except Exception as e:
            self.status.configure(text=t("error", e=e))
        self.root.after(self.settings["interval"], self._poll)

    def _render(self, gpu, ram, data, hw, processes):
        self._draw_bar(self.vram_canvas, data["vram_total"], data["vram_segs"])
        self._draw_bar(self.ram_canvas, data["ram_total"], data["ram_segs"])

        if gpu:
            self.vram_label.configure(
                text=f'VRAM — {gpu["name"]}')
            self.vram_text.configure(
                text=f'MEASURED (nvidia-smi): {fmt_mb(data["vram_used"])} / '
                     f'{fmt_mb(data["vram_total"])} '
                     f'({fmt_pct(data["vram_used"], data["vram_total"])} used)  |  '
                     f'free: {fmt_mb(data["vram_free"])}')
        else:
            self.vram_text.configure(text=t("vram_unavail"))

        if ram:
            self.ram_text.configure(
                text=f'{fmt_mb(data["ram_used"])} / {fmt_mb(data["ram_total"])} '
                      f'({fmt_pct(data["ram_used"], data["ram_total"])} used)  |  '
                      f'free: {fmt_mb(data["ram_free"])}')
        else:
            self.ram_text.configure(text=t("ram_unavail"))

        # --- Warnzeile (Konfig-Diagnose) ---
        warn_parts = []
        if hw.get("found"):
            okv = hw.get("offload_kv_gpu")
            if okv is False:
                warn_parts.append(t("warn_kv_off"))
            elif okv is None:
                warn_parts.append(t("warn_kv_missing"))
            if hw.get("strict_vram_cap") is True:
                warn_parts.append(t("warn_strict_cap"))
        if data["llm_procs"]:
            llm_txt = ", ".join(f'{p["name"]}(PID {p["pid"]})' for p in data["llm_procs"])
            warn_parts.append(t("warn_real_proc", x=llm_txt))
        self.warn.configure(text="  |  ".join(warn_parts) if warn_parts else "")

        # --- Detail-Text ---
        lines = []
        lines.append(t("sec_models"))
        if not data["models"]:
            lines.append(t("no_model"))
        for m in data["models"]:
            ap = m["arch_params"]
            lines.append(f'\n• {m["name"]}  [{m["type"]}]')
            lines.append(f'    {t("arch")}  : {ap.get("architecture")}')
            lines.append(f'    {t("weights")}     : {fmt_mb(m["weights"])}')
            lines.append(f'    {t("context")}      : {m["context_length"]} tokens')
            if m["type"] != "embedding":
                missing = t("kv_missing") if m.get("kv_missing") else ""
                kv_theo = m.get("kv_theoretical", 0)
                lines.append(f'    {t("kv_theo")}: {fmt_mb(kv_theo)}{missing}')
                lines.append(f'                   ({ap.get("n_layers")} {t("layers")}, '
                             f'{ap.get("n_head_kv") if not isinstance(ap.get("n_head_kv"), list) else "var"} {t("kv_heads")}, '
                             f'head_dim {ap.get("head_dim")})')
            lines.append(t("gpu_split", a=fmt_mb(m["w_vram"]), b=fmt_mb(m["kv_vram"])))
            lines.append(t("ram_split", a=fmt_mb(m["w_ram"]), b=fmt_mb(m["kv_ram"])))
            if m.get("kv_missing"):
                lines.append(t("kv_calc_impossible"))

        lines.append("\n" + t("sec_sensor"))
        if gpu:
            lines.append(f'VRAM (nvidia-smi): {fmt_mb(data["vram_used"])} / {fmt_mb(data["vram_total"])}')
            lines.append(f'  └─ Weights GPU:   {fmt_mb(sum(m["w_vram"] for m in data["models"]))}')
            lines.append(f'  └─ KV GPU:        {fmt_mb(data["kv_vram_actual"])}')
            lines.append(f'  └─ {t("other_base")}: {fmt_mb(max(0,data["vram_used"]-data["kv_vram_actual"]-sum(m["w_vram"] for m in data["models"])))}')
            lines.append(f'  └─ {t("free")}:       {fmt_mb(data["vram_free"])}')
        if ram:
            lines.append(f'RAM (Windows):     {fmt_mb(data["ram_used"])} / {fmt_mb(data["ram_total"])}')
            lines.append(f'  └─ Weights RAM:   {fmt_mb(sum(m["w_ram"] for m in data["models"]))}')
            lines.append(f'  └─ KV RAM:        {fmt_mb(data["kv_ram_actual"])}')
            if data.get("host_map"):
                lines.append(f'  └─ File mapping:  {fmt_mb(data["host_map"])}')
            lines.append(f'  └─ {t("other_base")}: {fmt_mb(max(0,data["ram_used"]-data["kv_ram_actual"]-sum(m["w_ram"] for m in data["models"])-data.get("host_map",0)))}')
            lines.append(f'  └─ {t("free")}:       {fmt_mb(data["ram_free"])}')

        # --- Echte Prozessmessung (NEU) ---
        lines.append("\n" + t("sec_proc"))
        if not processes:
            lines.append(t("no_proc_data"))
        else:
            lines.append(t("inf_procs", n=len(data["llm_procs"])))
            if data["llm_procs"]:
                for p in data["llm_procs"]:
                    lines.append(f'    {p["name"]} (PID {p["pid"]}): '
                                 f'VRAM {fmt_mb(p["vram"])} | RAM(WS) {fmt_mb(p["ram"])}'
                                 f' | RAM(Priv) {fmt_mb(p.get("priv", 0))}')
                lines.append(t("sum_llm_vram", x=fmt_mb(data["llm_vram_meas"])))
                lines.append(t("sum_llm_ram", x=fmt_mb(data["llm_ram_meas"])))
                lines.append(t("ram_note"))
            else:
                lines.append(t("no_inf_proc"))
            if data["app_procs"]:
                lines.append(t("ui_procs"))
                for p in data["app_procs"]:
                    lines.append(f'    {p["name"]} (PID {p["pid"]}): '
                                 f'VRAM {fmt_mb(p["vram"])} | RAM {fmt_mb(p["ram"])}')
            # Top-3 nicht-LLM GPU-Verbraucher (für Kontext: was sonst VRAM belegt)
            others = [p for p in processes if p.get("kind") not in ("inference", "app")][:3]
            if others:
                lines.append(t("other_gpu"))
                for p in others:
                    lines.append(f'    {p["name"]} (PID {p["pid"]}): '
                                 f'VRAM {fmt_mb(p["vram"])} | RAM {fmt_mb(p["ram"])}')

        # --- LM-Studio-Konfig-Diagnose (NEU) ---
        lines.append("\n" + t("sec_hw"))
        if not hw.get("found"):
            lines.append(t("hw_not_found"))
        else:
            for rk in hw.get("raw_keys", []):
                lines.append(f"  {rk}")
            okv = hw.get("offload_kv_gpu")
            cli = getattr(self, "last_cli", None)
            cli_kvo = cli.get("kv_offload") if cli else None
            if cli_kvo is not None and okv is not None and bool(cli_kvo) != bool(okv):
                lines.append(t("cfg_vs_reality", a=okv,
                               b=("no-" if not cli_kvo else "")))
            if okv is False:
                lines.append(t("kv_not_offloaded"))
                lines.append(t("reason_mem_alloc"))
                lines.append(t("fix_lmstudio"))
            elif okv is True:
                lines.append(t("kv_offload_act"))

        lines.append("\n" + t("basis_line",
                              a=self.settings["vram_base_mb"],
                              b=self.settings["ram_base_mb"],
                              c=data.get("kv_mode", self.settings["kv_mode"]),
                              d=KV_FACTORS.get(data.get("kv_mode", self.settings["kv_mode"]), 0)))
        if data.get("kv_quant_warning"):
            lines.append(f"⚠ {data['kv_quant_warning']}")
        if data.get("kv_overflow"):
            lines.append(t("kv_overflow",
                           a=fmt_mb(data["kv_bedarf"]),
                           b=fmt_mb(data["kv_vram_actual"]),
                           c=fmt_mb(data["kv_ram_actual"])))
            lines.append(t("overflow_perf"))
            lines.append(t("overflow_fix1"))
            lines.append(t("overflow_fix2"))
        elif data.get("kv_overflow_marginal"):
            lines.append(t("kv_ram_small", x=fmt_mb(data["kv_ram_actual"])))

        # --- Echte llama.cpp-Parameter aus Prozess-Kommandozeile ---
        cli = getattr(self, "last_cli", None)
        if cli and cli.get("ctx_size"):
            lines.append("\n" + t("sec_cli"))
            lines.append(f'  --ctx-size     : {cli.get("ctx_size")}')
            lines.append(f'  --cache-type-k : {cli.get("cache_type_k")}')
            lines.append(f'  --cache-type-v : {cli.get("cache_type_v")}')
            lines.append(f'  --parallel     : {cli.get("parallel")}')
            # GPU-Layer-Offload klar bewerten
            gpl = cli.get("gpu_layers")
            cmoe = cli.get("cpu_moe")
            if gpl is not None:
                lines.append(f'  --n-gpu-layers : {gpl}')
                try:
                    n_total = sum(
                        (m["arch_params"].get("n_layers") or 0)
                        for m in data["models"]) or ""
                    if isinstance(n_total, int) and n_total:
                        val = int(gpl)
                        shown = "max" if val >= n_total else f"{val}/{n_total}"
                        lines.append(t("offload_layers", x=shown))
                except Exception:
                    pass
            # MoE-Experten: --n-cpu-moe N = N Experten-Layer auf CPU.
            # N=0 heisst: ALLE Experten auf die GPU (getrennt von den
            # Attention-Layern!). Deshalb kann ein Modell mit n_gpu_layers=0
            # trotzdem VRAM belegen (Expert-Tensoren).
            if cmoe is not None:
                lines.append(f'  --n-cpu-moe    : {cmoe}')
                try:
                    if int(cmoe) == 0:
                        lines.append(t("moe_all_gpu"))
                    else:
                        lines.append(t("moe_cpu", x=cmoe))
                except Exception:
                    pass
            # KV-Offload-Status + Konsequenz fürs Layout
            kvo = cli.get("kv_offload")
            if kvo is not None:
                lines.append(f'  --kv-offload   : {kvo}')
                lines.append(t("kv_lies_in") + ("VRAM" if kvo else t("ram_deliberate")))
            lines.append(f'  --no-mmap      : {bool(cli.get("no_mmap"))}')
            lines.append(f'  --mlock        : {bool(cli.get("mlock"))}')

        self.detail.configure(state="normal")
        self.detail.delete(1.0, "end")
        self.detail.insert("end", "\n".join(lines))
        self.detail.configure(state="disabled")

        self.status.configure(text=t("status_updated", n=len(data["models"])))


def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

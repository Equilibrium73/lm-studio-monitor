"""
Minimaler, abhängigkeitsfreier GGUF-Metadaten-Leser.

Liest aus einer .gguf-Datei die Architekturparameter, die für die
KV-Cache-Berechnung und die Layer-Aufschlüsselung gebraucht werden:
  - block_count        (Anzahl Transformer-Blöcke = Schichten)
  - embedding_length   (Modell-Breite)
  - attention.head_count_kv (KV-Köpfe, wichtig bei GQA)
  - attention.key_length    (head_dim)
  - context_length     (trainierter Kontext)

Format-Referenz: GGUF-Spec (Version 2 und 3).
"""
import struct

GGUF_MAGIC = b"GGUF"


class GGUFMeta:
    def __init__(self, path):
        self.path = path
        self.version = None
        self.meta = {}
        self._read()

    def _read(self):
        with open(self.path, "rb") as f:
            magic = f.read(4)
            if magic != GGUF_MAGIC:
                raise ValueError("Keine GGUF-Datei: %r" % self.path)
            self.version = struct.unpack("<I", f.read(4))[0]
            struct.unpack("<Q", f.read(8))[0]  # tensor_count (hier egal)
            kv_count = struct.unpack("<Q", f.read(8))[0]
            for _ in range(kv_count):
                key = self._read_str(f)
                vtype = struct.unpack("<I", f.read(4))[0]
                val = self._read_value(f, vtype)
                self.meta[key] = val

    def _read_str(self, f):
        n = struct.unpack("<Q", f.read(8))[0]
        return f.read(n).decode("utf-8", "replace")

    def _read_value(self, f, vtype):
        # GGUFMetadataValueType
        if vtype == 0:
            return struct.unpack("<B", f.read(1))[0]
        if vtype == 1:
            return struct.unpack("<b", f.read(1))[0]
        if vtype == 2:
            return struct.unpack("<H", f.read(2))[0]
        if vtype == 3:
            return struct.unpack("<h", f.read(2))[0]
        if vtype == 4:
            return struct.unpack("<I", f.read(4))[0]
        if vtype == 5:
            return struct.unpack("<i", f.read(4))[0]
        if vtype == 6:
            return struct.unpack("<f", f.read(4))[0]
        if vtype == 7:
            return struct.unpack("<B", f.read(1))[0] != 0
        if vtype == 8:
            return self._read_str(f)
        if vtype == 9:  # ARRAY
            atype = struct.unpack("<I", f.read(4))[0]
            acount = struct.unpack("<Q", f.read(8))[0]
            return [self._read_value(f, atype) for _ in range(acount)]
        if vtype == 10:
            return struct.unpack("<Q", f.read(8))[0]
        if vtype == 11:
            return struct.unpack("<q", f.read(8))[0]
        if vtype == 12:
            return struct.unpack("<d", f.read(8))[0]
        raise ValueError("Unbekannter GGUF-Werttyp %d" % vtype)

    def arch_params(self):
        """Architekturparameter als Dictionary (oder None-Werte wenn fehlend)."""
        arch = self.meta.get("general.architecture", "")
        p = {
            "architecture": arch,
            "n_layers": self.meta.get(f"{arch}.block_count"),
            "n_embd": self.meta.get(f"{arch}.embedding_length"),
            "n_head": self.meta.get(f"{arch}.attention.head_count"),
            "n_head_kv": self.meta.get(
                f"{arch}.attention.head_count_kv",
                self.meta.get(f"{arch}.attention.head_count"),
            ),
            "head_dim": self.meta.get(f"{arch}.attention.key_length"),
            # MLA (DeepSeek V3/V4): latenter KV-Raum ist der Indexer (meist 128)
            "head_dim_indexer": self.meta.get(f"{arch}.attention.indexer.key_length"),
            # Sliding-Window Attention (SWA): bei vielen modernen Modellen
            # (Mistral, Mixtral, Gemma 2, Llama 4, Cohere Command-R …) wird der
            # KV-Cache NICHT ueber die volle Kontextlaenge gehalten, sondern nur
            # ueber ein Fenster. Der echte KV-Bedarf ist dann
            # min(ctx_size, sliding_window). Ohne Korrektur wuerde der Monitor
            # den KV-Cache massiv ueberschaetzen (z.B. 32x bei 128k ctx + 4k Fenster).
            "sliding_window": self.meta.get(f"{arch}.attention.sliding_window"),
            "context_length": self.meta.get(f"{arch}.context_length"),
        }
        # head_dim ableiten, falls nicht explizit vorhanden
        if p["head_dim"] is None and p["n_embd"] and p["n_head"]:
            p["head_dim"] = p["n_embd"] // p["n_head"]
        return p


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python gguf_meta.py <model.gguf>")
        sys.exit(1)
    g = GGUFMeta(sys.argv[1])
    print("GGUF version:", g.version)
    print(json.dumps(g.arch_params(), indent=2))

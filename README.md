# jp-transpos — Transpose jianpu-ly input files

Re-notate a jianpu-ly input file (`.tex` etc.) from one key to another while **preserving sounding pitch**.

## Usage

```
python jp-transpos.py --from <source> --to <target> --up|--down [options] input [-o output]
```

A shorthand form is also accepted:

```
python jp-transpos.py --<source>-to-<target> --up|--down input
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--from KEY` | Yes | Source key name |
| `--to KEY` | Yes | Target key name |
| `--up` or `--down` | One required | Whether the target tonic sits above or below the source tonic |
| `--enharmonic MODE` | No | Enharmonic simplification strategy, default `auto` (see table) |
| `--key-mode MODE` | No | Key signature handling, default `interval` (see table) |
| `--chord-octaves MODE` | No | Chord octave-mark positioning, default `normalize` (see table) |
| `--lines RANGE` | No | Limit transposition to a line range, e.g. `30-50`, `30-`, `-50` |
| `-o FILE` | No | Output file, default `input_transposed.ext` |

### Key name formats

Three conventions are accepted, case-insensitive:

| Type | Examples |
|------|----------|
| Naturals | `C`, `D`, `E`, `F`, `G`, `A`, `B` |
| Accidental-before-letter (Chinese convention) | `bB`, `#C`, `bE`, `#F`, `bA` |
| Lilypond names | `bes`, `cis`, `es`, `fis`, `gis`, `ais`, `des`, `dis`, `ges`, `as` |

### `--enharmonic` modes

| Mode | Simplifies | Accidental preference | Notes |
|------|-----------|----------------------|-------|
| `auto` (default) | Yes | `--up` → sharps, `--down` → flats | Recommended for daily use |
| `none` | **No** | Same as above | Keeps #7, b4, etc. as-is |
| `sharp` | Yes | Force sharps | All ambiguous pitches use sharps (includes key names) |
| `flat` | Yes | Force flats | All ambiguous pitches use flats (includes key names) |

Only four unambiguous enharmonic equivalents are simplified: `#7→1'`, `b1→7,`, `#3→4`, `b4→3`.  
Truly ambiguous pairs like `#1` vs `b2` are resolved by the sharp/flat preference without merging.

### `--key-mode` modes

| Mode | Description |
|------|-------------|
| `interval` (default) | Constant-interval: key-change distances are preserved. G→bE→G transposed to C becomes C→bA→C |
| `uniform` | All key signatures replaced with the target key. All modulations are erased |

Key signature names follow the `--to` argument's convention: `--to bE` produces `bE`, `--to #C` produces `#C`. For neutral key names (e.g. `C`, `G`), the `--up`/`--down` direction determines the fallback format. Note accidentals are still governed by `--enharmonic`.

### `--chord-octaves` modes

| Mode | Description |
|------|-------------|
| `normalize` (default) | Trailing octave marks inside chords are moved before their digits (OctavesBefore style). `,,62,` → `,,6,2` |
| `preserve` | Original positions kept verbatim. The trailing `,` in `,,62,///` stays where it was |

### Examples

```sh
# Transpose a piece in G major to C major
#   (target tonic placed below, for cleaner notation)
python jp-transpos.py --from G --to C --down piece.tex -o piece_C.tex

# Bb major up to C# major, no enharmonic simplification
python jp-transpos.py --bes-to-cis --up piece.tex --enharmonic none

# Force all accidentals to flats
python jp-transpos.py --from G --to C --down piece.tex --enharmonic flat

# All key signatures unified to C major (ignore original modulations)
python jp-transpos.py --from G --to C --down piece.tex --key-mode uniform

# Preserve original octave-mark positions inside chords
python jp-transpos.py --from G --to C --down piece.tex --chord-octaves preserve
```

---

## Internals

### 1. Transposition formula

In jianpu, the digit 1 always represents the tonic of the current key.

Let the source and target key tonics be $K_1$ and $K_2$ (in semitones above C: C=0, C#=1, D=2, ...).

Preserving sounding pitch means:

$\displaystyle K_1 + \mathrm{DEG2SEMI}[d_1] + \mathrm{ACC2SEMI}[a_1] + 12 \cdot o_1 = K_2 + \mathrm{DEG2SEMI}[d_2] + \mathrm{ACC2SEMI}[a_2] + 12 \cdot o_2$

Rearranging:

$\displaystyle \Delta = K_1 - K_2$

$\displaystyle \text{new\_value} = \Delta + \mathrm{DEG2SEMI}[d_1] + \mathrm{ACC2SEMI}[a_1] + 12 \cdot o_1$

$\displaystyle o_2 = \text{new\_value} \;//\; 12 \qquad p = \text{new\_value} \bmod 12$

Then we look up $p \mapsto (d_2, a_2)$ in one of two tables:

| p | Sharp table | Flat table |
|---|-------------|------------|
| 0 | 1 | 1 |
| 1 | #1 | b2 |
| 2 | 2 | 2 |
| 3 | #2 | b3 |
| 4 | 3 | 3 |
| 5 | 4 | 4 |
| 6 | #4 | b5 |
| 7 | 5 | 5 |
| 8 | #5 | b6 |
| 9 | 6 | 6 |
| 10| #6 | b7 |
| 11| 7 | 7 |

### 2. The meaning of `--up` / `--down`

$K_1$ and $K_2$ are semitone numbers (0–11) without octave information. The `--up` / `--down` flag chooses which octave $K_2$ occupies relative to $K_1$:

```python
def compute_delta(source, target, up):
    raw = source - target        # -11 ~ +11
    if up:
        return raw - 12 if raw > 0 else raw   # always ≤0
    else:
        return raw + 12 if raw < 0 else raw   # always ≥0
```

Intuition: when the target key goes up, notes are written lower relative to the new tonic (more `,` marks). When the target goes down, notes are written higher (more `'` marks).

Example: G(7) → C(0)
- `--down`: C4 below G4, Δ=+7 — most notes land in the "upper half" of the new key, visually clean
- `--up`: C5 above G4, Δ=-5 — most notes land in the "lower half"

### 3. Token processing pipeline

Each music line is split on whitespace into tokens; each token passes through:

```
Raw token (e.g. q,,5,256'.///)
│
├─ ① Extract ///  (tremolo — must be removed first since / is not
│     in the note_regex character set)
│
├─ ② Match against jianpu-ly's note_regex to identify note tokens:
│     note_regex = (?:[.,'cqsdh#b][.,'cqsdh\\#b]*)?[0-9x-][0-9x.,'cqsdh\\#b-]*
│     Non-matching → returned verbatim
│
├─ ③ Replace shorthands:  8→1', 9→2'
│
├─ ④ Extract <>  (base-octave change, passed through)
│
├─ ⑤ normalize_octaves: recursively move trailing octave marks
│     before the last affected digit
│     5' → '5     5'. → '5.    ,,5,256' → ,,5,25'6
│     (Skipped for chords when --chord-octaves preserve is set)
│
├─ ⑥ Character-by-character parsing:
│     ',' / '   → accumulate octave
│     # / b     → accumulate accidental
│     1–7       → trigger transposition using accumulated octave + accidental
│     Other     → passed through (q s d h . \ etc. are duration markers)
│
└─ ⑦ Reassemble:  base_oct + result + tremolo
```

### 4. File-level processing

Line-by-line scanning with differentiated handling:

```
Each line
├── LP: / :LP blocks   → skipped (raw Lilypond code)
├── L: / H: lyrics     → skipped
├── title= composer=   → skipped (headers)
├── 4=90  4/4          → skipped (tempo / time signature)
├── R{ DC Segno etc.   → skipped (structural keywords)
├── 1=bE / 6=A key sig → checked at both line and token level
│      interval mode: key name transposed by key_interval = (target - source) % 12
│      uniform  mode: key name replaced with target key
└── Everything else     → tokens processed through the pipeline
```

Key signatures are checked at the **line level** for standalone lines (`1=G`) and at the **token level** for mixed lines (`1=bE R*4 ^"text"`).

### 5. Enharmonic simplification

The following four cases are always merged (except under `--enharmonic none`) because writing them with accidentals is less natural than using the adjacent scale degree:

| Raw | Simplified | Reason |
|-----|-----------|--------|
| #7 | 1' (oct+1) | Augmented 7th = perfect octave above |
| b1 | 7, (oct-1) | Diminished unison = leading tone below |
| #3 | 4 | Augmented 3rd = perfect 4th |
| b4 | 3 | Diminished 4th = major 3rd |

Use `--enharmonic none` to disable this step and keep #7, b4, etc. verbatim.

### 6. Caveats

- **Whitespace is not preserved**: double spaces are collapsed to single spaces (does not affect jianpu-ly parsing)
- **Octave mark positions**: by default, trailing octave marks in chords are moved before their digits (OctavesBefore style). Use `--chord-octaves preserve` to keep original positions
- **LP blocks are untouched**: content between LP: ... :LP is treated as raw Lilypond code
- **Key name format is preserved**: if the input uses `bE` (accidental before letter), the output uses the same convention; likewise for `Eb`

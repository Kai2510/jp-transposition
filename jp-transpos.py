#!/usr/bin/env python3
# -*- coding: utf-8 -*-

r"""
jp-transpos.py - Transpose jianpu-ly input files (pitch-preserving re-notation)

Usage:
    python jp-transpos.py --from bE --to C --down input.tex [-o output.tex]
    python jp-transpos.py --bes-to-cis --up input.tex [output.tex]
    python jp-transpos.py --from G --to C --up input.tex --simplify flat

The --up/--down flag controls which octave the target key tonic is in
relative to the source key tonic:
  --up   : target tonic is above source tonic (notation shifts down)
  --down : target tonic is below source tonic (notation shifts up)

Key names: C D E F G A B, with sharps/flats as:
  bB bE bA bD bG  or  #C #D #F #G #A
  Lilypond names also work: bes cis es fis gis ais des dis ges as
"""

import re
import sys
import os

# ============================================================
# Constants
# ============================================================

KEY_TO_SEMI = {}
_raw_keys = {
    'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11,
    'cis': 1, 'des': 1, 'dis': 3, 'es': 3, 'fis': 6, 'ges': 6,
    'gis': 8, 'as': 8, 'ais': 10, 'bes': 10,
}
for _k, _v in _raw_keys.items():
    KEY_TO_SEMI[_k] = _v
    KEY_TO_SEMI[_k.lower()] = _v
    KEY_TO_SEMI[_k.upper()] = _v
for _letter, _semi in [('C',0),('D',2),('E',4),('F',5),('G',7),('A',9),('B',11)]:
    KEY_TO_SEMI['#' + _letter] = (_semi + 1) % 12
    KEY_TO_SEMI['#' + _letter.lower()] = (_semi + 1) % 12
    KEY_TO_SEMI['b' + _letter] = (_semi - 1) % 12
    KEY_TO_SEMI['b' + _letter.lower()] = (_semi - 1) % 12

DEG2SEMI = {1: 0, 2: 2, 3: 4, 4: 5, 5: 7, 6: 9, 7: 11}
ACC2SEMI = {'#': 1, 'b': -1, '': 0}

SEMI2DEG_SHARP = {
    0: (1, ''), 1: (1, '#'), 2: (2, ''), 3: (2, '#'), 4: (3, ''),
    5: (4, ''), 6: (4, '#'), 7: (5, ''), 8: (5, '#'), 9: (6, ''),
    10: (6, '#'), 11: (7, '')
}
SEMI2DEG_FLAT = {
    0: (1, ''), 1: (2, 'b'), 2: (2, ''), 3: (3, 'b'), 4: (3, ''),
    5: (4, ''), 6: (5, 'b'), 7: (5, ''), 8: (6, 'b'), 9: (6, ''),
    10: (7, 'b'), 11: (7, '')
}

SEMI_TO_KEY_SHARP = {
    0:'C', 1:'#C', 2:'D', 3:'#D', 4:'E', 5:'F',
    6:'#F', 7:'G', 8:'#G', 9:'A', 10:'#A', 11:'B'
}
SEMI_TO_KEY_FLAT = {
    0:'C', 1:'bD', 2:'D', 3:'bE', 4:'E', 5:'F',
    6:'bG', 7:'G', 8:'bA', 9:'A', 10:'bB', 11:'B'
}

NOTE_RE = (
    r"(?:[.,'cqsdh#b]"
    r"[.,'cqsdh\\#b]*)?"
    r"[0-9x-]"
    r"[0-9x.,'cqsdh\\#b-]*"
)

# ============================================================
# Key parsing
# ============================================================

def parse_key(name):
    if name in KEY_TO_SEMI:
        return KEY_TO_SEMI[name]
    sys.stderr.write(f"Error: Unknown key name '{name}'\n")
    sys.stderr.write("Valid: C D E F G A B, bB #C bE etc., bes cis es etc.\n")
    sys.exit(1)


def _key_name_is_flat(name):
    if name.lower().startswith('b') and len(name) > 1:
        return True
    if name.lower() in ('es', 'des', 'ges', 'bes', 'as', 'ees', 'aes'):
        return True
    if name.lower() in ('f',) and len(name) == 1:
        return True
    return False

def compute_delta(source_semi, target_semi, direction_up):
    raw = source_semi - target_semi
    if direction_up:
        return raw - 12 if raw > 0 else raw
    else:
        return raw + 12 if raw < 0 else raw

# ============================================================
# Note transposition
# ============================================================

ENHARMONIC_MODES = ('auto', 'none', 'sharp', 'flat')

def simplify(digit, acc, oct_level):
    if digit == 7 and acc == '#':
        return 1, '', oct_level + 1
    if digit == 1 and acc == 'b':
        return 7, '', oct_level - 1
    if digit == 3 and acc == '#':
        return 4, '', oct_level
    if digit == 4 and acc == 'b':
        return 3, '', oct_level
    return digit, acc, oct_level

def transpose_single_note(digit, acc, oct_level, delta, prefer_sharp, do_simplify):
    new_value = delta + DEG2SEMI[digit] + ACC2SEMI.get(acc, 0) + 12 * oct_level
    new_oct = new_value // 12
    pitch_mod = new_value % 12
    table = SEMI2DEG_SHARP if prefer_sharp else SEMI2DEG_FLAT
    new_digit, new_acc = table[pitch_mod]
    if do_simplify:
        return simplify(new_digit, new_acc, new_oct)
    return new_digit, new_acc, new_oct

# ============================================================
# Token normalization and transposition
# ============================================================

def normalize_octaves(s, normalize_chords=True):
    digit_count = sum(1 for c in s if c in '1234567')
    if not normalize_chords and digit_count > 1:
        return s

    last_digit_pos = -1
    for i in range(len(s) - 1, -1, -1):
        if s[i] in '1234567':
            last_digit_pos = i
            break
    if last_digit_pos == -1:
        return s

    core = s[:last_digit_pos + 1]
    suffix = s[last_digit_pos + 1:]

    pitch_after = ''.join(c for c in suffix if c in "',#b")
    suffix = ''.join(c for c in suffix if c not in "',#b")
    core = core + pitch_after

    def gof(s):
        m = re.match(r"^(.*)([1-7])([',#b]+)$", s)
        if m:
            return gof(m.group(1)) + m.group(3) + m.group(2)
        return s

    core = gof(core)
    return core + suffix

def transpose_token(token, delta, prefer_sharp, do_simplify, normalize_chords):
    tremolo = ''
    if '///' in token:
        tremolo = '///'
        token = token.replace('///', '', 1)

    if not re.match(NOTE_RE + '$', token):
        return token + tremolo
    if not re.search('[1-7]', token):
        return token + tremolo

    token = token.replace('8', "1'").replace('9', "2'")

    base_oct = ''.join(c for c in token if c in '<>')
    token = ''.join(c for c in token if c not in '<>')
    if not token:
        return base_oct + tremolo

    token = normalize_octaves(token, normalize_chords)

    result = []
    current_octave = ''
    current_acc = ''
    i = 0
    chars = list(token)

    while i < len(chars):
        c = chars[i]
        if c in "',":
            oct_str = c
            while i + 1 < len(chars) and chars[i + 1] == c:
                oct_str += c
                i += 1
            current_octave = oct_str
            i += 1
        elif c in '#b':
            current_acc = c
            i += 1
        elif c in '1234567':
            digit = int(c)
            oct_level = current_octave.count("'") - current_octave.count(",")
            nd, na, no = transpose_single_note(
                digit, current_acc, oct_level, delta, prefer_sharp, do_simplify)
            if no > 0:
                os_ = "'" * no
            elif no < 0:
                os_ = "," * (-no)
            else:
                os_ = ''
            result.append(os_ + na + str(nd))
            current_octave = ''
            current_acc = ''
            i += 1
        else:
            result.append(c)
            i += 1

    if current_octave or current_acc:
        result.append(current_octave + current_acc)

    return base_oct + ''.join(result) + tremolo

# ============================================================
# Key signature line transposition
# ============================================================

def transpose_key_in_line(line, key_interval, prefer_sharp_keys):
    def replace_key(m):
        prefix = m.group(1) + '='
        key_name = m.group(2)
        acc_before = bool(re.match(r'^[#b][A-Ga-g]$', key_name))
        letter_after = bool(re.match(r'^[A-Ga-g][#b]$', key_name))
        semi = parse_key(key_name)
        new_semi = (semi + key_interval) % 12
        if prefer_sharp_keys:
            new_name = SEMI_TO_KEY_SHARP[new_semi]
        else:
            new_name = SEMI_TO_KEY_FLAT[new_semi]
        if letter_after and len(new_name) == 2:
            new_name = new_name[1] + new_name[0]
        if len(key_name) == 1 and key_name.islower():
            new_name = new_name.lower()
        elif len(key_name) > 1 and key_name[-1].islower():
            new_name = new_name[0] + new_name[1:].lower()
        return prefix + new_name

    return re.sub(r'([16])=([#b]?[A-Ga-g][#b]?|[A-Ga-g])\b', replace_key, line)

# ============================================================
# File processing
# ============================================================

SKIP_WORDS = {
    'NextPart', 'NextScore', 'OnePage', 'NoBarNums', 'NoIndent',
    'RaggedLast', 'SeparateTimesig', 'WithStaff', 'PartMidi',
    'KeepLength', 'OctavesBefore', 'OctavesAfter', 'ChordsRoman',
    'angka', 'Indonesian', 'Fine', 'DC', 'DS', 'Segno', 'ToCoda',
    'Harm:', ':Harm',
}

def process_content(content, delta, key_interval, prefer_sharp, do_simplify,
                    normalize_chords, key_mode, target_key_name, prefer_sharp_keys):
    """Process entire file content.

    key_mode: 'interval' (preserve key-change distances) or 'uniform' (all to target)
    target_key_name: e.g. 'C' - the target key name as user typed it
    target_key_pfx: e.g. '1=' - keep the prefix from the first key change
    """
    lines = content.split('\n')
    result = []
    in_lp_block = False
    octaves_before_added = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith('LP:') or stripped.startswith('LPH:'):
            in_lp_block = True
            result.append(line)
            continue
        if stripped.startswith(':LP') or stripped.startswith(':LPH'):
            in_lp_block = False
            result.append(line)
            continue
        if in_lp_block:
            result.append(line)
            continue

        if not stripped or stripped.startswith('%'):
            result.append(line)
            continue

        if not octaves_before_added and not in_lp_block:
            if stripped in ('OctavesBefore', 'OctavesAfter'):
                octaves_before_added = True
            elif re.match(r'^[16]=', stripped) or \
                 (not stripped.startswith('L:') and not stripped.startswith('H:')
                  and not re.match(r'^[A-Za-z]+\s*=', stripped)
                  and stripped not in SKIP_WORDS):
                result.append('OctavesBefore')
                octaves_before_added = True

        if re.match(r'^[16]=[#b]?[A-Ga-g][#b]?$', stripped) or \
           re.match(r'^[16]=[A-Ga-g][#b]?$', stripped):
            if key_mode == 'uniform':
                pfx = stripped.split('=')[0] + '='
                result.append(pfx + target_key_name)
            else:
                result.append(transpose_key_in_line(stripped, key_interval, prefer_sharp_keys))
            continue

        if re.match(r'^[A-Za-z]+\s*=', stripped):
            result.append(line)
            continue
        if stripped.startswith('L:') or stripped.startswith('H:'):
            result.append(line)
            continue
        if stripped in SKIP_WORDS:
            result.append(line)
            if stripped in ('NextPart', 'NextScore'):
                result.append('OctavesBefore')
            continue
        if re.match(r'^[1-9][0-9]*=[1-9][0-9]*$', stripped):
            result.append(line)
            continue
        if re.match(r'^[1-9][0-9]*/[1-468]+', stripped):
            result.append(line)
            continue

        new_tokens = []
        for token in stripped.split():
            if re.match(r'^[16]=[#b]?[A-Ga-g][#b]?$', token) or \
               re.match(r'^[16]=[A-Ga-g][#b]?$', token):
                if key_mode == 'uniform':
                    pfx = token.split('=')[0] + '='
                    new_tokens.append(pfx + target_key_name)
                else:
                    new_tokens.append(transpose_key_in_line(token, key_interval, prefer_sharp_keys))
                continue

            grace_m = re.match(r'^g\[([#b\',1-7qsdh]+)\]$', token)
            if grace_m:
                inner = grace_m.group(1)
                new_inner = transpose_token(inner, delta, prefer_sharp, do_simplify, normalize_chords)
                new_tokens.append('g[' + new_inner + ']')
                continue

            grace_a = re.match(r'^\[([#b\',1-7,q,s,d,h]+)\]g$', token)
            if grace_a:
                inner = grace_a.group(1)
                new_inner = transpose_token(inner, delta, prefer_sharp, do_simplify, normalize_chords)
                new_tokens.append('[' + new_inner + ']g')
                continue

            new_tokens.append(transpose_token(token, delta, prefer_sharp, do_simplify, normalize_chords))

        result.append(' '.join(new_tokens))

    return '\n'.join(result)

# ============================================================
# CLI
# ============================================================

def preprocess_args(argv):
    new_args = []
    for arg in argv:
        m = re.match(r'^--([a-zA-Z#]+)-to-([a-zA-Z#]+)$', arg)
        if m and arg not in ('--from', '--to'):
            new_args.extend(['--from', m.group(1), '--to', m.group(2)])
        else:
            new_args.append(arg)
    return new_args

def main():
    import argparse

    argv = preprocess_args(sys.argv[1:])

    parser = argparse.ArgumentParser(
        description='Transpose jianpu-ly input files (pitch-preserving re-notation)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --from bE --to C --down input.tex
  %(prog)s --bes-to-cis --up input.tex output.tex
  %(prog)s --from G --to C --down input.tex --enharmonic none
  %(prog)s --from G --to C --down input.tex --enharmonic sharp
  %(prog)s --from G --to C --down input.tex --key-mode uniform
  %(prog)s --from G --to C --down input.tex --chord-octaves preserve

Key names: C D E F G A B, bB #C bE bA bD, bes cis es fis gis ais des dis ges as
        """)
    parser.add_argument('--from', dest='source', required=True,
                        help='Source key (e.g., bE, #C, bes, G)')
    parser.add_argument('--to', dest='target', required=True,
                        help='Target key (e.g., C, #C, cis, bB)')
    direction = parser.add_mutually_exclusive_group(required=True)
    direction.add_argument('--up', action='store_true',
                           help='Target tonic is above source tonic')
    direction.add_argument('--down', action='store_true',
                           help='Target tonic is below source tonic')
    parser.add_argument('--enharmonic', choices=ENHARMONIC_MODES, default='auto',
                        help='Enharmonic simplification: '
                             'auto (simplify, prefer --up=sharps --down=flats), '
                             'none (keep #7/b1/#3/b4 etc., prefer by direction), '
                             'sharp (force sharps), '
                             'flat (force flats) [default: auto]')
    parser.add_argument('--key-mode', choices=('interval', 'uniform'), default='interval',
                        help='Key signature handling: '
                             'interval (preserve key-change distances), '
                             'uniform (all keys become target) [default: interval]')
    parser.add_argument('--chord-octaves', choices=('normalize', 'preserve'), default='normalize',
                        help='Chord octave mark handling: '
                             'normalize (move trailing marks before digits, OctavesBefore style), '
                             'preserve (keep original positions in chords) [default: normalize]')
    parser.add_argument('-o', '--output',
                        help='Output file (default: input_transposed.ext)')
    parser.add_argument('input', help='Input jianpu-ly file')

    args = parser.parse_args(argv)

    enharmonic = args.enharmonic
    if enharmonic == 'sharp':
        prefer_sharp = True
        do_simplify = True
    elif enharmonic == 'flat':
        prefer_sharp = False
        do_simplify = True
    elif enharmonic == 'none':
        prefer_sharp = args.up
        do_simplify = False
    else:  # auto
        prefer_sharp = args.up
        do_simplify = True

    normalize_chords = (args.chord_octaves == 'normalize')
    key_mode = args.key_mode

    source_semi = parse_key(args.source)
    target_semi = parse_key(args.target)
    delta = compute_delta(source_semi, target_semi, args.up)
    key_interval = (target_semi - source_semi) % 12

    if enharmonic == 'sharp':
        prefer_sharp_keys = True
    elif enharmonic == 'flat':
        prefer_sharp_keys = False
    else:
        prefer_sharp_keys = not _key_name_is_flat(args.target)

    if prefer_sharp_keys:
        target_key_name = SEMI_TO_KEY_SHARP[target_semi]
    else:
        target_key_name = SEMI_TO_KEY_FLAT[target_semi]

    try:
        with open(args.input, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        sys.stderr.write(f"Error: File not found: {args.input}\n")
        sys.exit(1)

    result = process_content(content, delta, key_interval, prefer_sharp, do_simplify,
                             normalize_chords, key_mode, target_key_name, prefer_sharp_keys)

    output = args.output
    if not output:
        base, ext = os.path.splitext(args.input)
        output = base + '_transposed' + ext

    with open(output, 'w', encoding='utf-8') as f:
        f.write(result)

    direction_str = 'up' if args.up else 'down'
    src_name = args.source
    tgt_name = args.target
    sys.stderr.write(f"Transposed: {args.input} -> {output}\n")
    sys.stderr.write(f"  {src_name} -> {tgt_name} ({direction_str}), "
                     f"delta={delta:+d} semitones, enharmonic={enharmonic}, "
                     f"key-mode={key_mode}, chord-octaves={args.chord_octaves}\n")

if __name__ == '__main__':
    main()

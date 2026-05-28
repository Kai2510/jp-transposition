# jp-transpos — jianpu-ly 移调脚本

将 jianpu-ly 输入文件（`.tex` 等）从某个调重新记谱到另一个调，**保持实际音高不变**。

## 用法

```
python jp-transpos.py --from <源调> --to <目标调> --up|--down [选项] 输入文件 [-o 输出文件]
```

也可以合并写成缩短形式：

```
python jp-transpos.py --<源调>-to-<目标调> --up|--down 输入文件
```

### 参数

| 参数 | 必需 | 说明 |
|------|------|------|
| `--from KEY` | ✓ | 源调名 |
| `--to KEY` | ✓ | 目标调名 |
| `--up` 或 `--down` | 二选一 | 目标的 tonic 放在源 tonic 的上方还是下方八度 |
| `--enharmonic MODE` | ✗ | 等音简化策略，默认 `auto`（见下表） |
| `-o FILE` | ✗ | 输出文件，默认 `输入_transposed.扩展名` |

### 调名写法

支持三种记法，大小写无关：

| 类型 | 示例 |
|------|------|
| 自然音 | `C`, `D`, `E`, `F`, `G`, `A`, `B` |
| 汉字习惯（升降号在前） | `bB`, `#C`, `bE`, `#F`, `bA` |
| Lilypond 名 | `bes`, `cis`, `es`, `fis`, `gis`, `ais`, `des`, `dis`, `ges`, `as` |

### `--enharmonic` 模式

| 模式 | 等音合并 | 升降偏好 | 说明 |
|------|----------|----------|------|
| `auto`（默认） | 是 | `--up`→升号，`--down`→降号 | 日常使用推荐 |
| `none` | **否** | 同上 | 不合并 #7→1'、b4→3 等，保留原始结果 |
| `sharp` | 是 | 强制升号 | 所有模糊音用升号（含调号名） |
| `flat` | 是 | 强制降号 | 所有模糊音用降号（含调号名） |

被自动合并的只有四类必然等音：`#7→1'`、`b1→7,`、`#3→4`、`b4→3`。  
而 `#1` 与 `b2` 这种真·歧义音不合并，由 `prefer_sharp` 选表决定。

### 示例

```sh
# G 调谱子转到 C 调（目标 tonic 取下方八度，记谱更干净）
python jp-transpos.py --from G --to C --down piece.tex -o piece_C.tex

# bB 大调向上转到 #C 大调 (等音不合并)
python jp-transpos.py --bes-to-cis --up piece.tex --enharmonic none

# 强制全用降号记谱
python jp-transpos.py --from G --to C --down piece.tex --enharmonic flat
```

---

## 内部逻辑

### 一、移调公式

jianpu 的核心约定：数字 1 永远是当前调的 tonic。

设源调和目标调的 tonic 分别为 $K_1$ 和 $K_2$（单位：从 C 起的半音数，C=0, #C=1, D=2, ...）。

音高保持不变意味着：

$$K_1 + \text{DEG2SEMI}[d_1] + \text{ACC2SEMI}[a_1] + 12 \cdot o_1 = K_2 + \text{DEG2SEMI}[d_2] + \text{ACC2SEMI}[a_2] + 12 \cdot o_2$$

整理得：

$$\Delta = K_1 - K_2$$

$$\text{new\_value} = \Delta + \text{DEG2SEMI}[d_1] + \text{ACC2SEMI}[a_1] + 12 \cdot o_1$$

$$o_2 = \text{new\_value} \;\text{//}\; 12 \qquad p = \text{new\_value} \bmod 12$$

然后查表 $p \mapsto (d_2, a_2)$：

| p | 升号表 | 降号表 |
|---|--------|--------|
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

### 二、`--up` / `--down` 的意义

$K_1$ 和 $K_2$ 只是 0~11 的半音编号，不含八度信息。`--up` / `--down` 决定 $K_2$ 的有效高度：

```python
def compute_delta(source, target, up):
    raw = source - target        # -11 ~ +11
    if up:
        return raw - 12 if raw > 0 else raw   # 总是 ≤0，记谱整体下移
    else:
        return raw + 12 if raw < 0 else raw   # 总是 ≥0，记谱整体上移
```

直觉：目标调往上走，音符相对于新 tonic 就偏低（出更多 `,`）；目标调往下走，音符相对偏高（出更多 `'`）。

例如 G(7)→C(0)：
- `--down`：C4 在 G4 下方，Δ=+7，多数音在新调的"高半区"，视觉干净
- `--up`：C5 在 G4 上方，Δ=-5，多数音在新调的"低半区"

### 三、Token 处理流水线

每条音乐行按空格拆成 token，每个 token 走：

```
原始 token (如 q,,5,256'.///)
│
├─ ① 先剥 ///  (tremolo，必须先摘，因 / 不在 note_regex 字符集内)
│
├─ ② 用 jianpu-ly 同款正则匹配是否为音符 token:
│     note_regex = (?:[.,'cqsdh#b][.,'cqsdh\\#b]*)?[0-9x-][0-9x.,'cqsdh\\#b-]*
│     不匹配 → 原样返回
│
├─ ③ 替换快捷记法:  8→1', 9→2'
│
├─ ④ 提取 <>  (base-octave change，passthrough)
│
├─ ⑤ normalize_octaves: 将尾部八度标记递归移到数字前
│     5' → '5     5'. → '5.    ,,5,256' → ,,5,25'6
│
├─ ⑥ 逐字解析:
│     ','  '   → 积累 octave
│     #   b    → 积累 accidental
│     1-7      → 触发移调: 用积累的 octave+acc 算 new_digit/new_acc/new_oct
│     其他字符   → 原样输出 (q s d h . \ 等时长标记)
│
└─ ⑦ 拼回:  base_oct + 结果 + tremolo
```

### 四、文件级处理

逐行扫描，区别对待：

```
每行
├── LP: / :LP 块      → 跳过，不改
├── L: / H: 歌词行     → 跳过
├── title= composer= 等 → 跳过
├── 4=90 拍号 4/4      → 跳过
├── R{  DC  Segno 等  → 跳过
├── 1=bE 6=A 调号      → token级检查，移调key name
│                        key_interval = (target - source) % 12
└── 其余白音符行        → 逐token走流水线
```

调号在行级和 token 级各检查一次，因为 `1=bE R*4 ^"text"` 这种混合行无法在行级匹配。

### 五、等音简化（simplify）

以下四种情形无论什么模式（除 `none`）都会合并，因为它们写成升降号反而不自然：

| 原始 | 合并后 | 原因 |
|------|--------|------|
| #7 | 1' (八度+1) | 增七度 = 高八度纯一度 |
| b1 | 7, (八度-1) | 减一度 = 低八度导音 |
| #3 | 4 | 增三度 = 纯四度 |
| b4 | 3 | 减四度 = 大三度 |

`--enharmonic none` 禁用此步骤，允许 #7、b4 原样输出。

### 六、注意事项

- **空格不保留**：原始双空格等会被压缩为单空格（不影响 jianpu-ly 解析）
- **八度标记位置**：输出统一为 `OctavesBefore` 风格（八度标记在数字前），如 `2,,` 会变成 `,,2`，已设 `OctavesBefore` 的文件语义不变
- **不在 LP block 里改东西**：LP:  … :LP 之间的内容视为 Lilypond 裸代码，完全不碰
- **调号格式保持**：原文件用 `bE` 则输出 `bX`，用 `Eb` 则输出 `Xb`

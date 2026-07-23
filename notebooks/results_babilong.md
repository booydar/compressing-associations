# BABILong RMM v5p7 results

## Length-extrapolation eval (exact_match)

| variant | 0.5k | 1k | 2k | 4k | 8k | 16k | 32k | 64k | 128k |
|---|---|---|---|---|---|---|---|---|---|
| identity/identity mem8 ss32 lr1e-05 | 1.000 | 1.000 | 0.999 | 1.000 | 0.999 | 0.999 | 0.989 | 0.874 |  |
| pool/unpool mem16 ss32 lr1e-04 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.985 |
| pool/unpool mem16 ss32 lr1e-05 | 0.568 | 0.547 | 0.529 | 0.508 | 0.514 | 0.518 | 0.515 | 0.520 |  |

## Training curriculum (exact_match)

| variant | 0.5k | 1k | 2k | 3k | 4k | 8k | 16k |
|---|---|---|---|---|---|---|---|
| identity/identity mem8 ss32 lr1e-05 | 0.569 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| pool/unpool mem16 ss32 lr1e-04 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |  | 1.000 |
| pool/unpool mem16 ss32 lr1e-05 | 0.194 | 0.564 | 0.558 | 0.547 | 0.548 | 0.528 |  |

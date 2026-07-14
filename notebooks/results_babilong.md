# BABILong RMM v5p7 results

## Length-extrapolation eval (exact_match)

| task | variant | src | seg1 | seg2 | seg4 | seg8 | seg16 | seg32 | seg64 | seg128 |
|---|---|---|---|---|---|---|---|---|---|---|
| qa1 | identity/identity mem8 ss32 lr1e-05 | 32 | 1.000 | 1.000 | 0.999 | 1.000 | 0.999 | 0.999 | 0.989 |  |
| qa1 | pool/unpool mem16 ss32 lr1e-04 | 16 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |  |  |
| qa1 | pool/unpool mem16 ss32 lr1e-05 | 32 | 0.568 | 0.547 | 0.529 | 0.508 | 0.514 | 0.518 | 0.515 | 0.520 |

## Training curriculum (exact_match)

| task | variant | seg1 | seg2 | seg4 | seg6 | seg8 | seg16 | seg32 |
|---|---|---|---|---|---|---|---|---|
| qa1 | identity/identity mem8 ss32 lr1e-05 | 0.569 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| qa1 | pool/unpool mem16 ss32 lr1e-04 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |  |  |
| qa1 | pool/unpool mem16 ss32 lr1e-05 | 0.194 | 0.564 | 0.558 | 0.547 | 0.548 | 0.528 |  |

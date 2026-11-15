# Names

Each feature's published version carries a bare Pro name (ProEngine, ProProjection). Earlier versions that I tested are numbered 0.1, 0.2 in the order I built them; the next planned version of a feature is called v2. The source files keep the names of the version they were written as, so this table says which file is which.

| Public name | What it is | Source file |
|---|---|---|
| ProEngine | the model of whether an under-21 becomes a regular in one of 31 first divisions within three seasons (published) | models/engine_v2.py, models/score_v2c.py |
| ProEngine 0.1 | the first engine: a penalised logistic on the first inputs (tested, replaced) | models/engine_v2.py |
| ProEngine 0.2 | the engine with per-90 match stats from every year (tested, replaced) | models/engine_v2.py |
| ProEngine 0.3 | the same stats, only from the years that have them (tested, replaced) | models/engine_v2.py |
| ProProjection | the model of a player's future level, with ranges that hold 80 times in 100 (published) | models/projection_hurdle.py |
| ProProjection 0.1 | the first projection: calibrated ranges by value tier (tested, replaced) | models/projection.py |
| ProProjection 0.2 | the projection from what happened only, ranges by thirds of quality minutes (tested, did not pass its range test) | models/projection.py |
| ProProjection v2 | the next version, a sharper range: planned, not passed yet, an aim for later months | models/projection_v4.py |
| ProT6 0.1 | development by system, first test (did not pass) | gold/development.py |
| ProT6 | development by system, on more seasons and with players who stay (did not pass) | models/t6v2.py |

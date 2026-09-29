# Real hold-outs: the drawings AutoModel was not designed around

The synthetic benchmarks are regression locks, not evidence. Evidence is
a real architectural drawing set, its truth established by hand **before
AutoModel's result is examined**, compiled blind exactly once, with that
first result preserved untouched as the baseline.

## Lifecycle — one project at a time

```
UNSEEN holdout-001
      │  truth frozen first (truth/ committed before any run)
      ▼
blind run             blender -b --python tools/holdout_run.py -- holdouts/holdout-001
      │               (writes results/baseline.json once; never overwritten)
      ▼
score                 python3 tools/holdout_score.py holdouts/holdout-001
      │
      ▼
failure analysis      the F-code table picks what gets built next
      ▼
development
      ▼
holdout-001 RETIRES to the regression pool — it has been seen.
UNSEEN holdout-002 is the next evaluation. A hold-out used to diagnose
and improve the compiler is no longer a hold-out; pretending otherwise
trains the system against its own examination.
```

One project is enough to expose the harness; do not start with three.

## Directory layout

```
holdout-001/
├── source/                 the untouched drawings (.dxf / .dwg)
├── truth/                  hand-established, frozen before any run
│   ├── walls.json          [{"start":[x,y],"end":[x,y],"thickness":m}]
│   ├── openings.json       [{"classification":"DOOR"|"WINDOW",
│   │                         "width":m,"center":[x,y],"mark":optional}]
│   ├── spaces.json         [{"label":str,"area":m2,"inside":[x,y]}]
│   ├── storeys.json        [{"name":str,"elevation":m}]
│   └── drawing-register.json  [{"file":str,"view_type":"PLAN"|...}]
├── config/
│   └── project.json        {"stage":"detailed","typology":...,
│                            "height":m,"heights":{layer:m},
│                            "timings":{"truth_minutes":..,
│                                       "review_minutes":..,
│                                       "corrections":..}}
├── source/georeference.json      optional, the project's stated CRS
├── source/external_checker.json  optional, a real checker's recorded
│                                 results (instruments F13; schema
│                                 validation is not acceptance)
└── results/                generated; NEVER truth
    ├── baseline.json       the first blind run, preserved
    └── latest.json         subsequent runs during development
```

Truth coordinates are metres in the reference sheet's system (the first
plan holds the datum). `inside` is any point known to lie in the room.

## What the score reports

Per project, never only aggregated: walls TP/FP/FN with precision and
recall; opening P/R with door and window classification kept separate,
width MAE; spaces detected, area deviation and label accuracy; storeys
and elevations; the F-code failure table; human interventions; the two
KPIs (review minutes per 100 generated objects, correct objects per
intervention); and the gate that fails the run outright: **silent
unsupported assertions must be zero.**

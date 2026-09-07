# ClinicalTrials.gov lead-sponsor enumeration

Generated 2026-09-07T16:33:01Z. Interventional studies only.

**Nothing here has been written to `universe.yaml`.** These are candidates for review.

`exact` is a whole-field match on the lead sponsor
(`AREA[LeadSponsorName]COVERAGE[FullMatch]`), which is what M4 will use to count.
`seen` is how many studies the broad discovery query returned for that sponsor, and is
inflated by collaborator matches — it is a discovery signal, not a count.

## Traps

### 1. Merck & Co is not Merck KGaA

These strings belong to **Merck KGaA of Darmstadt**, a separate listed company, and
must be excluded explicitly from MRK:

- `EMD Serono` — surfaced under **PFE**
- `Merck KGaA, Darmstadt, Germany` — surfaced under **MRK**, 158 interventional studies
- `Merck Healthcare KGaA, Darmstadt, Germany, an affiliate of Merck KGaA, Darmstadt, Germany` — surfaced under **MRK**, 30 interventional studies
- `SpringWorks Therapeutics, Inc., a healthcare company of Merck KGaA, Darmstadt, Germany` — surfaced under **MRK**, 5 interventional studies
- `EMD Serono Research & Development Institute, Inc.` — surfaced under **MRK**
- `EMD Serono` — surfaced under **MRK**
- `EMD Serono Research & Development Institute, Inc.` — surfaced under **GILD**

Either way, never match on the bare token `Merck`: a `query.spons=Merck` discovery run
returns thousands of studies spanning both companies plus unrelated collaborators.

### 2. The Janssen to Johnson & Johnson Innovative Medicine handover

Date ranges per string, so the handover is visible. Taking only one side of it
would show a pipeline collapse that never happened:

| Lead sponsor | Exact | Earliest start | Latest start |
|---|---:|---|---|
| `Janssen-Cilag Turkey` | 0 | None | None |
| `Janssen-Cilag B.V.` | 3 | 1999-11 | 2003-08 |
| `Janssen Cilag Pharmaceutica S.A.C.I., Greece` | 2 | 2003-03 | 2004-10 |
| `Janssen-Cilag A.G., Switzerland` | 1 | 2004-11 | 2004-11 |
| `Janssen-Ortho LLC` | 4 | 2003-07 | 2005-12 |
| `Janssen-Cilag Pty Ltd` | 7 | 1998-03 | 2009-01 |
| `Janssen-Cilag S.p.A.` | 4 | 2001-08 | 2009-06 |
| `Janssen-Cilag Ltd.,Thailand` | 11 | 2004-04 | 2009-08 |
| `Janssen Cilag S.A.S.` | 4 | 2001-02 | 2009-11 |
| `JANSSEN Alzheimer Immunotherapy Research & Development, LLC` | 8 | 2001-09 | 2011-01 |
| `Janssen-Cilag Farmaceutica Ltda.` | 6 | 2003-02 | 2011-09 |
| `Janssen Biotech, Inc.` | 4 | 2009-12 | 2013-10 |
| `Janssen Cilag N.V./S.A.` | 4 | 2006-04 | 2015-05-18 |
| `Janssen-Cilag G.m.b.H` | 9 | 2006-02 | 2016-12-12 |
| `Janssen-Cilag, S.A.` | 5 | 2003-10 | 2020-09-08 |
| `Janssen-Cilag International NV` | 45 | 2004-06 | 2021-07-22 |
| `Janssen Vaccines & Prevention B.V.` | 46 | 2014-12-22 | 2023-05-17 |
| `Janssen Pharmaceutical K.K.` | 95 | 2001-04 | 2024-02-09 |
| `Janssen-Cilag Ltd.` | 14 | 2003-09 | 2024-04-17 |
| `Janssen Research & Development, LLC` | 671 | 2004-12 | 2026-10-29 |

### 3. Organon

Organon was spun out of Merck in 2021, the clinical counterpart of the FY2020
financial restatement already flagged in the fundamentals. Surfaced as:

- `Organon and Co` — under **PFE**
- `Organon and Co` — under **MRK**, 348 interventional studies, starts 1993-08-23 to 2025-12-29

### 4. Companies invisible to a query on their own name

ClinicalTrials.gov matches whole tokens, so a registrant name can fail to find its
own trials. These need an explicit alias, and a silent zero here would look identical
to a company with no trials:

- **MRNA** (Moderna, Inc.) — plain-name queries returned 1 studies

## Candidates by company

### MRNA — Moderna, Inc.

Queries run: `Moderna, Inc.`, `Moderna`, `ModernaTX`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `ModernaTX, Inc.` | 81 | 94 | 2015-12 | 2026-08-11 | NCT07764237 |

11 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### NVAX — Novavax, Inc.

Queries run: `Novavax, Inc.`, `Novavax`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Novavax` | 47 | 47 | 2007-07 | 2025-11-20 | NCT07086222 |

6 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### EBS — Emergent BioSolutions Inc.

Queries run: `Emergent BioSolutions Inc.`, `Emergent BioSolutions`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Emergent BioSolutions` | 30 | 37 | 2003-01 | 2027-01 | NCT02177721 |

7 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### VIR — Vir Biotechnology, Inc.

Queries run: `Vir Biotechnology, Inc.`, `Vir Biotechnology`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Vir Biotechnology, Inc.` | 18 | 42 | 2018-11-14 | 2025-08-05 | NCT07142811 |

8 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### PFE — Pfizer Inc.

Queries run: `Pfizer Inc.`, `Pfizer`, `Wyeth`, `Hospira`, `Array BioPharma`, `Medivation`, `Arena Pharmaceuticals`, `Biohaven`, `Seagen`, `Global Blood Therapeutics`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Pfizer` | 2198 | 2839 | 1990-03 | 2026-11-06 | NCT07768358 |
| `Wyeth is now a wholly owned subsidiary of Pfizer` | 344 | 843 | 1994-09 | 2011-08 | NCT00911573 |
| `Pfizer's Upjohn has merged with Mylan to form Viatris Inc.` | 296 | 728 | 1992-11 | 2021-01-30 | NCT04391868 |
| `Seagen Inc.` | 65 | 86 | 2000-10 | 2022-04-21 | NCT05229900 |
| `Seagen, a wholly owned subsidiary of Pfizer` | 25 | 84 | 2018-06-25 | 2024-08-21 | NCT06549816 |
| `Array Biopharma, now a wholly owned subsidiary of Pfizer` | 23 | 50 | 2004-06 | 2015-06 | NCT02109653 |
| `Hospira, now a wholly owned subsidiary of Pfizer` | 16 | 44 | 2005-03 | 2012-10 | NCT01519167 |
| `Medivation, Inc.` | 14 | 24 | 2005-09 | 2016-12 | NCT02653989 |
| `Biohaven Therapeutics Ltd.` | 16 | 18 | 2024-03-14 | 2026-06 | NCT07642050 |
| `Arena Pharmaceuticals` | 16 | 17 | 2007-02 | 2021-01-29 | NCT04655599 |
| `Biohaven Pharmaceuticals, Inc.` | 10 | 12 | 2016-12-15 | 2022-07-06 | NCT05337553 |
| `Global Blood Therapeutics` | 6 | 9 | 2014-12 | 2016-12 | NCT03051711 |
| `Array BioPharma` | 5 | 6 | 2009-03 | 2014-12 | NCT02278133 |
| `Wyeth-Lederle Vaccines` | 2 | 2 | None | None | NCT00002231 |
| `European Society for Blood and Marrow Transplantation` | 14 | 1 | 1995-01 | 2015-07 | NCT02099747 |
| `Metsera, a wholly owned subsidiary of Pfizer` | 1 | 1 | 2024-04-01 | 2024-04-01 | NCT06857617 |

672 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### MRK — Merck & Co., Inc.

Queries run: `Merck & Co., Inc.`, `Merck &`, `Merck Sharp & Dohme`, `Acceleron Pharma`, `Prometheus Biosciences`, `Pandion Therapeutics`, `Imago BioSciences`, `Organon`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Merck Sharp & Dohme LLC` | 1715 | 4018 | 1990-12 | 2026-11-23 | NCT07700758 |
| `Organon and Co` | 348 | 490 | 1993-08-23 | 2025-12-29 | NCT07265479 |
| `Merck KGaA, Darmstadt, Germany` | 158 | 184 | 1992-02-29 | 2019-09-02 | NCT03845140 |
| `Cubist Pharmaceuticals LLC, a subsidiary of Merck & Co., Inc. (Rahway, New Jersey USA)` | 55 | 128 | 2000-10-31 | 2015-03-25 | NCT02276482 |
| `ArQule, Inc., a subsidiary of Merck Sharp & Dohme LLC, a subsidiary of Merck & Co., Inc. (Rahway, NJ USA)` | 30 | 90 | 2003-09 | 2017-06-26 | NCT03162536 |
| `Acceleron Pharma, Inc., a wholly-owned subsidiary of Merck & Co., Inc., Rahway, NJ USA` | 23 | 78 | 2008-01 | 2023-03-10 | NCT04948554 |
| `Merck Healthcare KGaA, Darmstadt, Germany, an affiliate of Merck KGaA, Darmstadt, Germany` | 30 | 46 | 2019-04-15 | 2026-03-26 | NCT07499362 |
| `Trius Therapeutics LLC, a subsidiary of Merck & Co., Inc. (Rahway, New Jersey USA)` | 12 | 38 | 2008-01-06 | 2012-04-23 | NCT01577459 |
| `Verona Pharma, Inc., a subsidiary of Merck & Co., Inc. (Rahway, New Jersey USA` | 18 | 36 | 2014-12 | 2025-10-06 | NCT07132983 |
| `Afferent Pharmaceuticals, Inc., a subsidiary of Merck & Co., Inc. (Rahway, New Jersey USA)` | 13 | 30 | 2011-09-22 | 2016-05-16 | NCT02790840 |
| `Cidara Therapeutics Inc., a subsidiary of Merck & Co., Inc. (Rahway, New Jersey USA)` | 11 | 24 | 2015-07 | 2025-10-29 | NCT07225959 |
| `NovaCardia, Inc., a subsidiary of Merck & Co., Inc. (Rahway, New Jersey USA)` | 6 | 18 | 2004-08 | 2007-08 | NCT00443690 |
| `Prometheus Biosciences, Inc., a subsidiary of Merck & Co., Inc. (Rahway, New Jersey USA)` | 3 | 18 | 2021-07-14 | 2022-03-29 | NCT05270668 |
| `Immune Design, a subsidiary of Merck & Co., Inc. (Rahway, New Jersey USA)` | 6 | 16 | 2013-11 | 2018-09-18 | NCT03520959 |
| `Imago BioSciences, Inc., a subsidiary of Merck & Co., Inc., (Rahway, New Jersey USA)` | 3 | 15 | 2016-10-06 | 2021-12-15 | NCT05223920 |
| `Peloton Therapeutics, Inc., a subsidiary of Merck & Co., Inc. (Rahway, New Jersey USA)` | 4 | 14 | 2014-11-25 | 2018-09-27 | NCT03634540 |
| `Oncoimmune, Inc., a subsidiary of Merck & Co., Inc. (Rahway, New Jersey USA)` | 6 | 12 | 2014-06-02 | 2021-06-15 | NCT04060407 |
| `Optimer Pharmaceuticals LLC, a subsidiary of Merck & Co., Inc. (Rahway, New Jersey USA)` | 4 | 12 | 2004-11-01 | 2012-10-10 | NCT01691248 |
| `SpringWorks Therapeutics, Inc., a healthcare company of Merck KGaA, Darmstadt, Germany` | 5 | 11 | 2019-04-17 | 2024-07-31 | NCT06251310 |
| `Oncoethix GmbH, a subsidiary of Merck & Co., Inc. (Rahway, New Jersey USA)` | 4 | 10 | 2012-02 | 2015-01 | NCT02303782 |
| `Terns, Inc., a subsidiary of Merck & Co., Inc. (Rahway, New Jersey USA)` | 3 | 10 | 2021-05-20 | 2025-03-07 | NCT06854952 |
| `Harpoon Therapeutics, Inc., a subsidiary of Merck & Co., Inc. (Rahway, New Jersey USA)` | 3 | 8 | 2018-07-24 | 2020-12-14 | NCT04471727 |
| `Dupont Merck` | 1 | 4 | None | None | NCT00002410 |
| `VelosBio Inc., a subsidiary of Merck & Co., Inc. (Rahway, New Jersey USA)` | 1 | 4 | 2020-10-07 | 2020-10-07 | NCT04504916 |
| `Merck Medication Familiale` | 2 | 2 | 2010-04 | 2011-05 | NCT01652066 |

941 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### JNJ — Johnson & Johnson

Queries run: `Johnson & Johnson`, `Janssen Research & Development`, `Janssen Biotech`, `Janssen Vaccines & Prevention`, `Janssen-Cilag`, `Johnson & Johnson Innovative Medicine`, `Actelion`, `Abiomed`, `Shockwave`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Janssen Research & Development, LLC` | 671 | 851 | 2004-12 | 2026-10-29 | NCT07746687 |
| `Johnson & Johnson Pharmaceutical Research & Development, L.L.C.` | 363 | 463 | 1931-06 | 2020-03-31 | NCT04330248 |
| `Johnson & Johnson Vision Care, Inc.` | 208 | 210 | 2005-09 | 2026-08-28 | NCT07788521 |
| `Actelion` | 107 | 131 | 2002-01 | 2024-03-14 | NCT05731492 |
| `Johnson & Johnson Consumer and Personal Products Worldwide` | 53 | 59 | 1999-10 | 2025-01-20 | NCT06798441 |
| `Janssen-Cilag International NV` | 45 | 57 | 2004-06 | 2021-07-22 | NCT04940039 |
| `Johnson & Johnson Consumer Inc. (J&JCI)` | 46 | 53 | 2014-04-30 | 2025-01-20 | NCT06852742 |
| `Janssen Vaccines & Prevention B.V.` | 46 | 50 | 2014-12-22 | 2023-05-17 | NCT05901636 |
| `Mead Johnson Nutrition` | 45 | 45 | 1994-06 | 2026-04-03 | NCT07513506 |
| `Johnson & Johnson Surgical Vision, Inc.` | 25 | 25 | 2018-06-28 | 2025-01-01 | NCT05090787 |
| `Shockwave Medical, Inc.` | 20 | 24 | 2005-11 | 2026-07 | NCT07512128 |
| `Abiomed Inc.` | 21 | 22 | 2006-08 | 2026-04-01 | NCT06965504 |
| `Johnson & Johnson Taiwan Ltd` | 16 | 17 | 2004-09 | 2014-12 | NCT02268890 |
| `Janssen-Cilag Ltd.` | 14 | 15 | 2003-09 | 2024-04-17 | NCT06408935 |
| `Robert Wood Johnson Foundation` | 15 | 15 | 2001-07 | 2008-01 | NCT00729040 |
| `Janssen-Cilag Ltd.,Thailand` | 11 | 11 | 2004-04 | 2009-08 | NCT01387542 |
| `Janssen-Cilag G.m.b.H` | 9 | 9 | 2006-02 | 2016-12-12 | NCT02951533 |
| `Bankole Johnson` | 8 | 8 | 2005-03 | 2008-10 | NCT00769158 |
| `JANSSEN Alzheimer Immunotherapy Research & Development, LLC` | 8 | 8 | 2001-09 | 2011-01 | NCT01284387 |
| `Janssen-Cilag Pty Ltd` | 7 | 8 | 1998-03 | 2009-01 | NCT00872521 |
| `Johnson & Johnson Consumer Inc., McNeil Consumer Healthcare Division` | 6 | 7 | 2016-04-30 | 2020-11-09 | NCT04447040 |
| `Johnson & Johnson Enterprise Innovation Inc.` | 7 | 7 | 2021-12-10 | 2026-05-18 | NCT07525141 |
| `Janssen Cilag N.V./S.A.` | 4 | 6 | 2006-04 | 2015-05-18 | NCT02455856 |
| `Janssen-Cilag Farmaceutica Ltda.` | 6 | 6 | 2003-02 | 2011-09 | NCT01448720 |
| `Johnson & Johnson Private Limited` | 6 | 6 | 2019-01-07 | 2025-08-12 | NCT07141004 |
| `Janssen Biotech, Inc.` | 4 | 5 | 2009-12 | 2013-10 | NCT01962974 |
| `Janssen-Cilag, S.A.` | 5 | 5 | 2003-10 | 2020-09-08 | NCT04476446 |
| `Johnson & Johnson Consumer Products Company Division of Johnson & Johnson Consumer Companies, Inc.` | 5 | 5 | 2011-03 | 2017-11-15 | NCT03450070 |
| `Johnson & Johnson Healthcare Products Division of McNEIL-PPC, Inc.` | 3 | 5 | 2010-06 | 2014-12-31 | NCT02320708 |
| `Janssen Cilag S.A.S.` | 4 | 4 | 2001-02 | 2009-11 | NCT00989300 |
| `Janssen-Cilag S.p.A.` | 4 | 4 | 2001-08 | 2009-06 | NCT01391013 |
| `French Innovative Leukemia Organisation` | 46 | 3 | 1994-06 | 2026-09-01 | NCT07624799 |
| `Janssen-Cilag B.V.` | 3 | 3 | 1999-11 | 2003-08 | NCT00216541 |
| `Johnson & Johnson K.K. Medical Company` | 3 | 3 | 2010-07 | 2013-05 | NCT01895634 |
| `Johnson & Johnson Medical (Suzhou) Ltd.` | 3 | 3 | 2014-07 | 2017-08-17 | NCT02399046 |
| `Johnson & Johnson Medical, China` | 3 | 3 | 2009-02 | 2017-06-12 | NCT03305887 |
| `Patrick C. Johnson, MD` | 3 | 3 | 2023-03-01 | 2026-04-14 | NCT07553572 |
| `Ralph H. Johnson VA Medical Center` | 3 | 3 | 2003-08 | 2024-01 | NCT05669170 |
| `Ari Johnson, MD` | 2 | 2 | 2015-11-01 | 2019-02-01 | NCT04106921 |
| `Janssen Cilag Pharmaceutica S.A.C.I., Greece` | 2 | 2 | 2003-03 | 2004-10 | NCT00216450 |
| `Janssen-Ortho LLC` | 4 | 2 | 2003-07 | 2005-12 | NCT00257010 |
| `Jonas Johnson` | 2 | 2 | 2016-01 | 2021-01-14 | NCT04608773 |
| `R W Johnson Pharmaceutical Research Institute` | 2 | 2 | None | None | NCT00002022 |
| `Robert Wood Johnson Barnabas Health` | 2 | 2 | 2021-04-05 | 2021-09-01 | NCT05003596 |
| `Theodore S. Johnson` | 2 | 2 | 2019-10-02 | 2022-02-08 | NCT05106296 |
| `Advance Shockwave Technology GmbH` | 1 | 1 | 2010-06 | 2010-06 | NCT00959153 |
| `Amy K. Johnson, PhD, MSW` | 1 | 1 | 2023-04-17 | 2023-04-17 | NCT05783297 |
| `Anthony Johnson` | 1 | 1 | 2015-12-01 | 2015-12-01 | NCT02596802 |
| `Cali Johnson` | 1 | 1 | 2025-05-15 | 2025-05-15 | NCT07065760 |
| `David A. Johnson, MD` | 1 | 1 | 2008-07 | 2008-07 | NCT01079884 |
| `Douglas Johnson` | 1 | 1 | 2023-03-03 | 2023-03-03 | NCT05660421 |
| `Egil Johnson` | 1 | 1 | 2016-05 | 2016-05 | NCT01815411 |
| `Janssen Pharmaceutical K.K.` | 95 | 1 | 2001-04 | 2024-02-09 | NCT06295692 |
| `Janssen-Cilag A.G., Switzerland` | 1 | 1 | 2004-11 | 2004-11 | NCT00886002 |
| `Janssen-Cilag Turkey` | 0 | 1 | None | None | None |
| `Johnson & Johnson Health and Wellness Solutions, Inc.` | 1 | 1 | 2017-09-16 | 2017-09-16 | NCT03451240 |
| `Johnson & Johnson Pte Ltd` | 1 | 1 | 2017-05-18 | 2017-05-18 | NCT03264677 |
| `Johnson & Wales University` | 1 | 1 | 2022-11-01 | 2022-11-01 | NCT07768774 |
| `Johnson Thomas` | 1 | 1 | 2020-10-26 | 2020-10-26 | NCT04277455 |
| `Nathalie Johnson` | 1 | 1 | 2004-10 | 2004-10 | NCT00266331 |
| `Stacy Johnson` | 1 | 1 | 2026-06-03 | 2026-06-03 | NCT06941415 |

360 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### GILD — Gilead Sciences, Inc.

Queries run: `Gilead Sciences, Inc.`, `Gilead Sciences`, `Kite Pharma`, `Immunomedics`, `Forty Seven`, `CymaBay Therapeutics`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Gilead Sciences` | 533 | 655 | 1997-03 | 2026-07-29 | NCT07708727 |
| `Kite, A Gilead Company` | 27 | 36 | 2015-04-21 | 2026-05-22 | NCT07479797 |

240 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### VRTX — Vertex Pharmaceuticals Incorporated

Queries run: `Vertex Pharmaceuticals Incorporated`, `Vertex`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Vertex Pharmaceuticals Incorporated` | 175 | 468 | 1998-12 | 2027-07-31 | NCT05951205 |
| `Alpine Immune Sciences Inc, A Subsidiary of Vertex` | 2 | 2 | 2021-06-22 | 2024-08-30 | NCT06564142 |

22 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### BDX — Becton, Dickinson and Company

Queries run: `Becton, Dickinson and Company`, `Becton Dickinson`, `C. R. Bard`, `CareFusion`, `Bard Peripheral Vascular`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `C. R. Bard` | 90 | 99 | 2001-01 | 2025-11-21 | NCT07282860 |
| `Becton, Dickinson and Company` | 35 | 74 | 2007-09 | 2026-05-07 | NCT07216573 |

35 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.


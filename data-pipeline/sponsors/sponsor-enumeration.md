# ClinicalTrials.gov lead-sponsor enumeration

Generated 2026-09-08T18:17:23Z. Interventional studies only.

**Nothing here has been written to `universe.yaml`.** These are candidates for review.

`exact` is a whole-field match on the lead sponsor
(`AREA[LeadSponsorName]COVERAGE[FullMatch]`), which is what M4 will use to count.
`seen` is how many studies the broad discovery query returned for that sponsor, and is
inflated by collaborator matches — it is a discovery signal, not a count.

## Traps

### 1. Merck & Co is not Merck KGaA

No Merck KGaA or EMD Serono strings surfaced in these queries.

Either way, never match on the bare token `Merck`: a `query.spons=Merck` discovery run
returns thousands of studies spanning both companies plus unrelated collaborators.

### 2. The Janssen to Johnson & Johnson Innovative Medicine handover


### 3. Organon

No Organon strings surfaced under the Merck queries.

### 4. Companies invisible to a query on their own name

ClinicalTrials.gov matches whole tokens, so a registrant name can fail to find its
own trials. These need an explicit alias, and a silent zero here would look identical
to a company with no trials:

- **ZTS** (Zoetis Inc.) — plain-name queries returned 0 studies
- **ABT** (Abbott Laboratories) — plain-name queries returned 2 studies
- **DGX** (Quest Diagnostics Incorporated) — plain-name queries returned 0 studies
- **A** (Agilent Technologies, Inc.) — plain-name queries returned 1 studies
- **DHR** (Danaher Corporation) — plain-name queries returned 0 studies
- **TMO** (Thermo Fisher Scientific Inc.) — plain-name queries returned 14 studies
- **CVS** (CVS Health Corporation) — plain-name queries returned 0 studies
- **HCA** (HCA Healthcare, Inc.) — plain-name queries returned 0 studies
- **THC** (Tenet Healthcare Corporation) — plain-name queries returned 1 studies
- **UHS** (Universal Health Services, Inc.) — plain-name queries returned 0 studies
- **DOCS** (Doximity, Inc.) — plain-name queries returned 0 studies
- **VEEV** (Veeva Systems Inc.) — plain-name queries returned 4 studies
- **COR** (Cencora, Inc.) — plain-name queries returned 0 studies
- **MCK** (McKesson Corporation) — plain-name queries returned 0 studies

## Candidates by company

### ARCT — Arcturus Therapeutics Holdings Inc.

Queries run: `Arcturus Therapeutics Holdings Inc.`, `Arcturus`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Arcturus Therapeutics, Inc.` | 11 | 13 | 2020-06-01 | 2024-12-12 | NCT06747858 |

3 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### OCGN — Ocugen, Inc.

Queries run: `Ocugen, Inc.`, `Ocugen`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Ocugen` | 10 | 10 | 2017-09-06 | 2026-08-11 | NCT07770828 |

1 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### PCVX — Vaxcyte, Inc.

Queries run: `Vaxcyte, Inc.`, `Vaxcyte`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Vaxcyte, Inc.` | 8 | 18 | 2022-02-22 | 2026-06-01 | NCT07616934 |

### SCYX — Scynexis, Inc.

Queries run: `Scynexis, Inc.`, `Scynexis`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Scynexis, Inc.` | 16 | 36 | 2007-04 | 2023-07-12 | NCT06954493 |

### SIGA — SIGA Technologies, Inc.

Queries run: `SIGA Technologies, Inc.`, `SIGA Technologies`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `SIGA Technologies` | 6 | 8 | 2007-02 | 2022-03-29 | NCT04971109 |

1 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### SPRO — Spero Therapeutics, Inc.

Queries run: `Spero Therapeutics, Inc.`, `Spero`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Spero Therapeutics` | 10 | 22 | 2018-12-18 | 2023-12-21 | NCT06059846 |

1 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### VXRT — Vaxart, Inc.

Queries run: `Vaxart, Inc.`, `Vaxart`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Vaxart` | 17 | 23 | 2011-04 | 2025-03-03 | NCT06944717 |

6 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### ABBV — AbbVie Inc.

Queries run: `AbbVie Inc.`, `AbbVie`, `Allergan`, `Pharmacyclics`, `Stemcentrx`, `Cerevel Therapeutics`, `ImmunoGen`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `AbbVie` | 643 | 777 | 2006-12-11 | 2026-11-30 | NCT07728188 |
| `Allergan` | 373 | 397 | 1999-03 | 2023-02-15 | NCT04609020 |
| `AbbVie (prior sponsor, Abbott)` | 124 | 161 | 2000-12 | 2013-06 | NCT01773070 |
| `Pharmacyclics LLC.` | 50 | 53 | 1998-08 | 2018-11-19 | NCT03790332 |
| `Cerevel Therapeutics, LLC` | 7 | 22 | 2019-10-15 | 2022-12-15 | NCT05610189 |
| `Naurex, Inc, an affiliate of Allergan plc` | 16 | 20 | 2009-11 | 2019-07-01 | NCT03855865 |
| `ImmunoGen, Inc.` | 11 | 16 | 2005-02 | 2020-10-29 | NCT04622774 |
| `Allergan Medical` | 8 | 8 | 1997-12 | 2012-04 | NCT01579305 |
| `Durata Therapeutics Inc., an affiliate of Allergan plc` | 3 | 6 | 2011-03 | 2013-06 | NCT01946568 |
| `Chase Pharmaceuticals Corporation, an affiliate of Allergan plc` | 2 | 4 | 2015-01-08 | 2015-10-07 | NCT02549196 |
| `Stemcentrx` | 4 | 4 | 2013-07 | 2016-09 | NCT02874664 |
| `Pharmacyclics Switzerland GmbH` | 2 | 2 | 2016-09-20 | 2017-05-22 | NCT03229200 |
| `Vitae Pharmaceuticals Inc., an Allergan affiliate` | 2 | 2 | 2015-08 | 2015-08-01 | NCT03724292 |

301 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### AMGN — Amgen Inc.

Queries run: `Amgen Inc.`, `Amgen`, `Onyx Pharmaceuticals`, `Horizon Therapeutics`, `Five Prime Therapeutics`, `ChemoCentryx`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Amgen` | 801 | 953 | 1997-04 | 2026-10-31 | NCT07222553 |
| `Amgen Research (Munich) GmbH` | 9 | 10 | 2008-01 | 2012-07 | NCT01741792 |
| `Five Prime Therapeutics, Inc.` | 8 | 10 | 2011-01 | 2018-10-18 | NCT04074759 |
| `Horizon Therapeutics Ireland DAC` | 1 | 1 | 2022-11-22 | 2022-11-22 | NCT05565768 |

246 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### BMY — Bristol-Myers Squibb Company

Queries run: `Bristol-Myers Squibb Company`, `Bristol-Myers Squibb`, `Celgene`, `Juno Therapeutics`, `MyoKardia`, `Turning Point Therapeutics`, `RayzeBio`, `Karuna Therapeutics`, `Mirati Therapeutics`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Bristol-Myers Squibb` | 996 | 1225 | 1995-01 | 2026-12-31 | NCT07791199 |
| `Celgene` | 273 | 366 | 2001-09-01 | 2025-10-07 | NCT06988488 |
| `Karuna Therapeutics, Inc., a Bristol Myers Squibb company` | 19 | 69 | 2018-09-18 | 2026-08-03 | NCT07681076 |
| `Mirati Therapeutics Inc.` | 42 | 51 | 2004-04 | 2026-05-06 | NCT07415031 |
| `Celgene Corporation` | 40 | 50 | 2000-04 | 2014-11 | NCT02321644 |
| `Juno Therapeutics, Inc., a Bristol-Myers Squibb Company` | 12 | 44 | 2023-09-13 | 2026-08-31 | NCT07603557 |
| `Juno Therapeutics, a Subsidiary of Celgene` | 9 | 19 | 2015-08-21 | 2021-02-24 | NCT04674813 |
| `Turning Point Therapeutics, Inc.` | 8 | 9 | 2017-03-07 | 2022-07-28 | NCT05828277 |
| `MyoKardia, Inc.` | 6 | 7 | 2014-12 | 2018-05-29 | NCT03470545 |
| `RayzeBio, Inc.` | 6 | 7 | 2022-03-24 | 2026-06 | NCT07671092 |
| `Adnexus, A Bristol-Myers Squibb R&D Company` | 3 | 6 | 2006-08 | 2008-10 | NCT00768911 |

616 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### LLY — Eli Lilly and Company

Queries run: `Eli Lilly and Company`, `Eli Lilly`, `Loxo Oncology`, `Dermira`, `Prevail Therapeutics`, `POINT Biopharma`, `Morphic`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Eli Lilly and Company` | 1837 | 4117 | 1989-02 | 2026-12 | NCT07790861 |
| `Loxo Oncology, Inc.` | 14 | 48 | 2019-03-15 | 2024-05-01 | NCT06104683 |
| `Dermira, Inc.` | 10 | 30 | 2011-12 | 2017-03-21 | NCT03127956 |
| `DICE Therapeutics, Inc., a wholly owned subsidiary of Eli Lilly and Company` | 5 | 20 | 2021-09-22 | 2024-10-25 | NCT06602219 |
| `Morphic Therapeutic, Inc. (A Wholly Owned Subsidiary of Eli Lilly and Company)` | 5 | 15 | 2020-09-23 | 2025-02-19 | NCT06977880 |
| `Morphic Medical Inc.` | 11 | 13 | 2007-01 | 2019-09-09 | NCT04101669 |
| `Prevail Therapeutics` | 4 | 13 | 2020-01-03 | 2024-08-27 | NCT06565195 |
| `POINT Biopharma, a wholly owned subsidiary of Eli Lilly and Company` | 2 | 6 | 2021-02-25 | 2022-07-13 | NCT05432193 |
| `Scorpion Therapeutics, a wholly owned subsidiary of Eli Lilly and Company` | 1 | 4 | 2025-03-20 | 2025-03-20 | NCT06901336 |

305 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### ZTS — Zoetis Inc.

Queries run: `Zoetis Inc.`, `Zoetis`

No lead sponsors surfaced sharing a token with any query string.

### ALNY — Alnylam Pharmaceuticals, Inc.

Queries run: `Alnylam Pharmaceuticals, Inc.`, `Alnylam`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Alnylam Pharmaceuticals` | 64 | 69 | 2007-07 | 2026-08-17 | NCT07636811 |

8 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### BIIB — Biogen Inc.

Queries run: `Biogen Inc.`, `Biogen`, `Reata Pharmaceuticals`, `HI-Bio`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Biogen` | 354 | 422 | 1995-04 | 2026-11-16 | NCT07483632 |
| `HI-Bio, A Biogen Company` | 5 | 10 | 2019-10-15 | 2023-11-01 | NCT06064929 |
| `NightstaRx Ltd, a Biogen Company` | 1 | 1 | 2018-06-04 | 2018-06-04 | NCT03584165 |
| `Reata, a wholly owned subsidiary of Biogen` | 1 | 1 | 2023-07-28 | 2023-07-28 | NCT05895552 |

67 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### INCY — Incyte Corporation

Queries run: `Incyte Corporation`, `Incyte`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Incyte Corporation` | 189 | 532 | 2006-04 | 2026-12-01 | NCT07797283 |
| `Incyte Biosciences International Sàrl` | 7 | 18 | 2016-06-20 | 2023-03-01 | NCT05359692 |
| `Incyte Biosciences Japan GK` | 4 | 12 | 2019-07-22 | 2021-02-03 | NCT04674748 |

93 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### IONS — Ionis Pharmaceuticals, Inc.

Queries run: `Ionis Pharmaceuticals, Inc.`, `Ionis`, `Akcea Therapeutics`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Ionis Pharmaceuticals, Inc.` | 85 | 224 | 2001-01-10 | 2026-09 | NCT07782827 |
| `Akcea Therapeutics` | 10 | 30 | 2015-12-23 | 2021-01-21 | NCT04306510 |

9 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### NBIX — Neurocrine Biosciences, Inc.

Queries run: `Neurocrine Biosciences, Inc.`, `Neurocrine`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Neurocrine Biosciences` | 66 | 83 | 2001-03 | 2026-02-16 | NCT07288333 |
| `Neurocrine UK Limited` | 15 | 18 | 2007-08 | 2022-05-24 | NCT05063994 |
| `Neurocrine Switzerland GmbH` | 0 | 1 | None | None | None |

5 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### REGN — Regeneron Pharmaceuticals, Inc.

Queries run: `Regeneron Pharmaceuticals, Inc.`, `Regeneron`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Regeneron Pharmaceuticals` | 325 | 355 | 2001-11 | 2027-02-02 | NCT07559513 |

131 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### SRPT — Sarepta Therapeutics, Inc.

Queries run: `Sarepta Therapeutics, Inc.`, `Sarepta`, `Myonexus Therapeutics`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Sarepta Therapeutics, Inc.` | 43 | 98 | 2003-08 | 2026-08-31 | NCT07542314 |

4 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### ARVN — Arvinas, Inc.

Queries run: `Arvinas, Inc.`, `Arvinas`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Arvinas Inc.` | 5 | 10 | 2019-03-01 | 2026-07-29 | NCT07749586 |
| `Arvinas Estrogen Receptor, Inc.` | 2 | 4 | 2019-08-05 | 2022-09-08 | NCT05501769 |
| `Arvinas Androgen Receptor, Inc.` | 0 | 2 | None | None | None |

1 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### BEAM — Beam Therapeutics Inc.

Queries run: `Beam Therapeutics Inc.`, `Beam`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Beam Therapeutics Inc.` | 5 | 10 | 2022-08-30 | 2025-10-27 | NCT07304791 |
| `Ion Beam Applications` | 3 | 3 | 2025-04-29 | 2025-08-19 | NCT07152353 |
| `Beam` | 2 | 2 | 2022-05-09 | 2024-07-02 | NCT07183735 |

2 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### CRSP — CRISPR Therapeutics AG

Queries run: `CRISPR Therapeutics AG`, `CRISPR`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `CRISPR Therapeutics AG` | 9 | 22 | 2019-07-22 | 2026-08-08 | NCT07758634 |
| `CRISPR Therapeutics` | 3 | 3 | 2024-08-13 | 2026-09-15 | NCT07804004 |

1 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### DNLI — Denali Therapeutics Inc.

Queries run: `Denali Therapeutics Inc.`, `Denali`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Denali Therapeutics Inc.` | 15 | 36 | 2017-06-01 | 2026-08-07 | NCT07758595 |

3 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### NTLA — Intellia Therapeutics, Inc.

Queries run: `Intellia Therapeutics, Inc.`, `Intellia`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Intellia Therapeutics` | 7 | 7 | 2020-11-05 | 2025-01-15 | NCT06634420 |

1 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### RVMD — Revolution Medicines, Inc.

Queries run: `Revolution Medicines, Inc.`, `Revolution Medicines`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Revolution Medicines, Inc.` | 17 | 38 | 2019-07-02 | 2026-08-28 | NCT07805954 |

5 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### ABT — Abbott Laboratories

Queries run: `Abbott Laboratories`, `St. Jude Medical`, `Alere`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Alere San Diego` | 3 | 3 | 2011-04 | 2014-08 | NCT01941277 |
| `St. Jude Children's Research Hospital` | 260 | 1 | 1991-03 | 2026-11 | NCT07585136 |

12 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### BSX — Boston Scientific Corporation

Queries run: `Boston Scientific Corporation`, `Boston Scientific`, `Guidant`, `Preventice`, `Axonics`, `Baylis Medical`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Boston Scientific Corporation` | 363 | 750 | 1998-02 | 2027-04 | NCT07639684 |
| `Guidant Corporation` | 6 | 9 | 1997-01 | 2008-11 | NCT00833352 |
| `Axonics, Inc.` | 5 | 6 | 2016-06 | 2026-04-30 | NCT07335484 |
| `Baylis Medical Company` | 4 | 4 | 2007-09 | 2010-07 | NCT01158092 |
| `Boston Medical Center` | 273 | 1 | 1994-12 | 2027-09 | NCT07708038 |
| `Boston Scientific Japan K.K.` | 1 | 1 | 2017-02-27 | 2017-02-27 | NCT03033134 |

165 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### ISRG — Intuitive Surgical, Inc.

Queries run: `Intuitive Surgical, Inc.`, `Intuitive Surgical`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Intuitive Surgical` | 21 | 25 | 2010-05 | 2026-08-28 | NCT07761351 |

14 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### MDT — Medtronic plc

Queries run: `Medtronic plc`, `Medtronic`, `Covidien`, `Mazor Robotics`, `Intersect ENT`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Medtronic Cardiac Rhythm and Heart Failure` | 167 | 168 | 1999-06-09 | 2026-08 | NCT07526896 |
| `Medtronic - MITG` | 97 | 97 | 2004-01 | 2025-12-30 | NCT07351071 |
| `Medtronic MiniMed, Inc.` | 63 | 63 | 2002-06 | 2026-10-15 | NCT07401901 |
| `Medtronic Cardiovascular` | 51 | 52 | 2001-10 | 2026-10 | NCT07754318 |
| `Medtronic Vascular` | 51 | 51 | 2003-06 | 2025-09-22 | NCT07115953 |
| `Medtronic Spinal and Biologics` | 41 | 44 | 1996-10 | 2026-04-24 | NCT07414745 |
| `Medtronic Endovascular` | 41 | 43 | 2004-04 | 2025-05-09 | NCT06742801 |
| `Medtronic Cardiac Ablation Solutions` | 24 | 25 | 2002-09 | 2026-09-02 | NCT07789925 |
| `Medtronic BRC` | 22 | 22 | 2000-07 | 2021-02 | NCT04671888 |
| `Intersect ENT` | 12 | 12 | 2008-03 | 2021-05-12 | NCT04858802 |
| `Medtronic Neurovascular Clinical Affairs` | 11 | 12 | 2001-05 | 2024-04-16 | NCT02998229 |
| `Medtronic Surgical Technologies` | 11 | 11 | 2008-12 | 2014-12 | NCT02284347 |
| `Medtronic Cardiac Surgery` | 6 | 7 | 2005-09 | 2024-11-20 | NCT06506903 |
| `Medtronic Spine LLC` | 7 | 7 | 2003-02 | 2009-02 | NCT00810043 |
| `Medtronic` | 5 | 5 | 2000-09 | 2022-09 | NCT05049720 |
| `Covidien, GI Solutions` | 2 | 4 | 2003-11 | 2009-01 | NCT02047305 |
| `Medtronic Corporate Technologies and New Ventures` | 3 | 3 | 2009-06 | 2013-03-29 | NCT01823705 |
| `Medtronic Diabetes R&D Denmark` | 3 | 3 | 2012-10 | 2013-03 | NCT01775059 |
| `Medtronic Heart Valves` | 3 | 3 | 2012-10 | 2017-01 | NCT02979587 |
| `Medtronic Italia` | 2 | 2 | 2006-09 | 2010-02 | NCT01109641 |
| `Medtronic Xomed, Inc.` | 2 | 2 | 2007-11 | 2008-04 | NCT00729781 |
| `ENT and Allergy Associates, LLP` | 1 | 1 | 2015-12 | 2015-12 | NCT02687438 |
| `Mazor Robotics` | 1 | 1 | 2009-02 | 2009-02 | NCT00810433 |
| `Medtronic Hellas Medical Devices ΑEE` | 1 | 1 | 2007-11 | 2007-11 | NCT00559143 |
| `Medtronic Latin America` | 1 | 1 | 2011-02 | 2011-02 | NCT01238874 |

352 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### SYK — Stryker Corporation

Queries run: `Stryker Corporation`, `Stryker`, `Wright Medical`, `Vocera`, `K2M`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Stryker Orthopaedics` | 37 | 40 | 1987-10 | 2024-03-02 | NCT05591859 |
| `Stryker Neurovascular` | 11 | 11 | 2004-01 | 2025-06-20 | NCT06872684 |
| `Stryker Trauma and Extremities` | 9 | 9 | 2007-04 | 2023-08-22 | NCT06638138 |
| `Stryker South Pacific` | 5 | 5 | 2010-12 | 2020-11-12 | NCT04600583 |
| `Novadaq Technologies ULC, now a part of Stryker` | 4 | 4 | 2012-05 | 2019-01-04 | NCT03200704 |
| `Stryker Japan K.K.` | 4 | 4 | 2010-07 | 2015-04 | NCT02543463 |
| `Stryker Sustainability Solutions` | 4 | 4 | 2021-11-02 | 2023-05-27 | NCT06149416 |
| `Stryker Biotech` | 3 | 3 | 2007-03 | 2010-05 | NCT01133613 |
| `Stryker Instruments` | 3 | 3 | 2007-01 | 2019-11-05 | NCT04154605 |
| `Stryker Endoscopy` | 2 | 2 | 2021-06-28 | 2022-02-07 | NCT05329584 |
| `Wright State University` | 36 | 2 | 2003-05 | 2027-06 | NCT07640061 |
| `David Wright` | 2 | 1 | 2002-05 | 2010-03 | NCT00822900 |
| `K2M, Inc.` | 1 | 1 | 2022-09 | 2022-09 | NCT02590380 |
| `Karen D. Wright MD` | 2 | 1 | 2011-09 | 2018-02-27 | NCT03429803 |
| `Orthovita d/b/a Stryker` | 1 | 1 | 2004-09 | 2004-09 | NCT00290862 |
| `Stryker Australia Pty Ltd.` | 1 | 1 | 2024-02-22 | 2024-02-22 | NCT06108934 |
| `Stryker Craniomaxillofacial` | 1 | 1 | 2020-11-19 | 2020-11-19 | NCT04498026 |
| `Stryker GI Ltd.` | 1 | 1 | 2008-10 | 2008-10 | NCT00715325 |
| `Thomas Wright, MD` | 1 | 1 | 2020-01-31 | 2020-01-31 | NCT04213989 |

70 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### DGX — Quest Diagnostics Incorporated

Queries run: `Quest Diagnostics Incorporated`, `Quest Diagnostics`

No lead sponsors surfaced sharing a token with any query string.

### LH — Labcorp Holdings Inc.

Queries run: `Labcorp Holdings Inc.`, `Labcorp`, `Covance`, `Labcorp Drug Development`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Laser LabCorp` | 1 | 1 | 2021-12-15 | 2021-12-15 | NCT04683120 |

92 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### NTRA — Natera, Inc.

Queries run: `Natera, Inc.`, `Natera`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Natera, Inc.` | 10 | 20 | 2009-11 | 2026-12 | NCT07689812 |

25 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### A — Agilent Technologies, Inc.

Queries run: `Agilent Technologies, Inc.`, `Agilent Technologies`

No lead sponsors surfaced sharing a token with any query string.

### DHR — Danaher Corporation

Queries run: `Danaher Corporation`, `Danaher`, `Cepheid`, `Beckman Coulter`, `Cytiva`, `Integrated DNA Technologies`

No lead sponsors surfaced sharing a token with any query string.

### ILMN — Illumina, Inc.

Queries run: `Illumina, Inc.`, `Illumina`, `GRAIL`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Illumina, Inc.` | 2 | 6 | 2014-09 | 2017-09-14 | NCT03290469 |
| `Innervate Radiopharmaceuticals LLC (Formerly: Illumina Radiopharmaceuticals LLC)` | 5 | 5 | 2021-11-05 | 2026-04-30 | NCT07176286 |
| `GRAIL, Inc.` | 4 | 4 | 2019-12-12 | 2024-07-12 | NCT05673018 |

5 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### TMO — Thermo Fisher Scientific Inc.

Queries run: `Thermo Fisher Scientific Inc.`, `Thermo Fisher Scientific`, `PPD`, `Patheon`, `Life Technologies`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `PPD Development, LP` | 5 | 5 | 2000-08 | 2025-10-28 | NCT06701656 |
| `On-X Life Technologies, Inc.` | 3 | 3 | 2003-07 | 2011-11-18 | NCT01812174 |
| `Full-Life Technologies UK Limited` | 1 | 1 | 2024-08-30 | 2024-08-30 | NCT06492122 |
| `Life Research Technologies GmbH` | 1 | 1 | 2010-09 | 2010-09 | NCT01456065 |
| `Sellas Life Sciences Group` | 6 | 1 | 2010-12-21 | 2021-05-10 | NCT04588922 |

103 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### CVS — CVS Health Corporation

Queries run: `CVS Health Corporation`, `CVS Health`, `Aetna`, `Oak Street Health`, `Signify Health`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Aetna, Inc.` | 1 | 1 | 2008-11 | 2008-11 | NCT01105572 |

14 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### ELV — Elevance Health, Inc.

Queries run: `Elevance Health, Inc.`, `Elevance Health`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Elevance Health` | 1 | 2 | 2020-10-30 | 2020-10-30 | NCT04609644 |

2 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### UNH — UnitedHealth Group Incorporated

Queries run: `UnitedHealth Group Incorporated`, `UnitedHealth`, `Optum`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `UnitedHealth Group` | 5 | 5 | 2011-01-01 | 2021-05-03 | NCT04810026 |

12 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### HCA — HCA Healthcare, Inc.

Queries run: `HCA Healthcare, Inc.`, `HCA Healthcare`

No lead sponsors surfaced sharing a token with any query string.

### THC — Tenet Healthcare Corporation

Queries run: `Tenet Healthcare Corporation`, `Tenet Healthcare`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Tenet Healthcare Corporation` | 1 | 2 | 2013-09 | 2013-09 | NCT01944111 |

### UHS — Universal Health Services, Inc.

Queries run: `Universal Health Services, Inc.`, `Universal Health Services`

No lead sponsors surfaced sharing a token with any query string.

### DOCS — Doximity, Inc.

Queries run: `Doximity, Inc.`, `Doximity`

No lead sponsors surfaced sharing a token with any query string.

### VEEV — Veeva Systems Inc.

Queries run: `Veeva Systems Inc.`, `Veeva Systems`

No lead sponsors surfaced sharing a token with any query string.

### CAH — Cardinal Health, Inc.

Queries run: `Cardinal Health, Inc.`, `Cardinal Health`

| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |
|---|---:|---:|---|---|---|
| `Cardinal Health 414, LLC` | 3 | 3 | 2015-08 | 2016-09 | NCT02857608 |
| `Cardinal Health` | 1 | 1 | 2023-08 | 2023-08 | NCT05945186 |

10 further lead sponsors appeared in the discovery results without
sharing a token with any query string — collaborator matches, mostly academic.
They are listed in the JSON alongside this report.

### COR — Cencora, Inc.

Queries run: `Cencora, Inc.`, `Cencora`

No lead sponsors surfaced sharing a token with any query string.

### MCK — McKesson Corporation

Queries run: `McKesson Corporation`, `McKesson`

No lead sponsors surfaced sharing a token with any query string.


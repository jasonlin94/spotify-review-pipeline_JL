# Decision Memo — Next-Quarter Product Priority

**Recommendation: Playback (failures/crashes)** — Spotify should focus its next quarter of product effort on playback issues, specifically addressing crashing and shuffle bugs.

## Why

Playback ranks as the highest priority issue with a priority score of 43467 (C4), driven by 12902 complaints (C1) and a severe severity sum of 43467 (C2). Users frequently report critical failures such as the app force-closing or crashing completely (e.g., review `1730c0f6-e36b-4e2b-b1a2-547922f89673`) and hardware-level playback disruptions following updates (e.g., review `07f59bbd-a997-47f6-b91e-4a9a5c645c32`). With a high mean severity of 3.369 (C3), resolving these stability flaws is vital to preventing immediate user churn.

Supporting claims:
- `C1` — issue `playback` complaint_count = **12902**
- `C2` — issue `playback` severity_sum = **43467**
- `C3` — issue `playback` mean_severity = **3.369013**
- `C4` — issue `playback` priority_score = **43467**

Representative reviews: `00d770d6-fdc3-4521-8cce-1a9613b9cadd`, `07f59bbd-a997-47f6-b91e-4a9a5c645c32`, `1730c0f6-e36b-4e2b-b1a2-547922f89673`

## Alternatives considered

- **Usability (controls/ads)** — While usability has a high complaint count, its priority score of 33931 (C8) and lower mean severity of 2.514 (C7) rank it behind playback stability.
- **Catalog (search/content)** — Catalog issues carry a lower priority score of 11794 (C12) compared to the severe stability disruptions affecting playback.
- **Access (login/account)** — Access issues account for only 2885 complaints (C13) and a priority score of 10878 (C16), making playback a more widespread concern.
- **Billing (charges/premium)** — Billing generates fewer total complaints (2647) and a lower priority score of 8458 (C20) than playback.

## Full baseline ranking

| rank | issue | complaints | severity_sum | mean_severity | priority |
|---|---|---|---|---|---|
| 1 | playback | 12902 | 43467 | 3.369013 | 43467 |
| 2 | usability | 13497 | 33931 | 2.513966 | 33931 |
| 3 | catalog | 4469 | 11794 | 2.639069 | 11794 |
| 4 | access | 2885 | 10878 | 3.770537 | 10878 |
| 5 | billing | 2647 | 8458 | 3.195315 | 8458 |
| 6 | downloads | 1748 | 5575 | 3.189359 | 5575 |
| 7 | other | 1710 | 3272 | 1.913450 | 3272 |
| 8 | support | 159 | 500 | 3.144654 | 500 |

## Limitations

The findings are derived from self-selected historical reviews representing a subset of user feedback. Expressed intent in reviews may not always translate directly to actual long-term churn. Additionally, the data covers only partial review windows and specific timeframes.

_Every number above traces to `grading/claims.csv` and the deterministic `grading/ranking.csv`; see README for the evidence map._
# Decision Memo — Next-Quarter Product Priority

**Recommendation: Playback (failures/crashes)** — Spotify should focus its next quarter of product effort on playback issues to address app crashes and shuffle problems.

## Why

Playback ranks as the highest priority issue with a priority score of 43471 (C4), driven by 12903 complaints (C1) and the highest severity sum of 43471 (C2). Users report severe disruptions such as app force closes, freezing, and hardware interference, as highlighted by reviews like review_id=1730c0f6-e36b-4e2b-b1a2-547922f89673 and review_id=07f59bbd-a997-47f6-b91e-4a9a5c645c32. Addressing core playback stability will directly mitigate the most damaging complaints affecting user experience.

Supporting claims:
- `C1` — issue `playback` complaint_count = **12903**
- `C2` — issue `playback` severity_sum = **43471**
- `C3` — issue `playback` mean_severity = **3.369061**
- `C4` — issue `playback` priority_score = **43471**

Representative reviews: `00d770d6-fdc3-4521-8cce-1a9613b9cadd`, `07f59bbd-a997-47f6-b91e-4a9a5c645c32`, `1730c0f6-e36b-4e2b-b1a2-547922f89673`

## Alternatives considered

- **Usability (controls/ads)** — Although usability has a high complaint count of 13507 (C5), its priority score of 33962 (C8) ranks behind playback.
- **Access (login/account)** — Access has a lower priority score of 10882 (C16) compared to playback.
- **Billing (charges/premium)** — Billing has a lower priority score of 8458 (C20) compared to playback.

## Full baseline ranking

| rank | issue | complaints | severity_sum | mean_severity | priority |
|---|---|---|---|---|---|
| 1 | playback | 12903 | 43471 | 3.369061 | 43471 |
| 2 | usability | 13507 | 33962 | 2.514400 | 33962 |
| 3 | catalog | 4471 | 11799 | 2.639007 | 11799 |
| 4 | access | 2886 | 10882 | 3.770617 | 10882 |
| 5 | billing | 2647 | 8458 | 3.195315 | 8458 |
| 6 | downloads | 1748 | 5575 | 3.189359 | 5575 |
| 7 | other | 1716 | 3278 | 1.910256 | 3278 |
| 8 | support | 159 | 500 | 3.144654 | 500 |

## Limitations

Self-selected historical reviews may skew the feedback toward extreme negative experiences rather than normal usage. Expressed intent in reviews does not always translate into actual user churn. The review window is based on partial months, limiting temporal consistency.

_Every number above traces to `grading/claims.csv` and the deterministic `grading/ranking.csv`; see README for the evidence map._
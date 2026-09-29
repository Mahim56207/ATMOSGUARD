## 1. Introduction

### 1.1 The problem
An Automatic Weather Station (AWS) reports temperature, pressure and humidity every few minutes, often from places nobody visits.
A failing sensor and real weather look alike on a chart: a barometer that has stuck reads the same flat line as the calm before a
cyclone, and the sharp pressure fall of a cyclone reads like a barometer that has failed. A system that silences every surprise
deletes the storm the network exists to see; a system that trusts every surprise sends bad data into forecasts and warnings.
Problem statement 26073 asks for anomaly detection and sensor-health monitoring **from these three channels only**.

We accepted two constraints beyond the statement, because they are what sparse networks (the Andamans, Ladakh, the Thar) actually have:
one station is judged on its own record, with **no neighbouring stations and no reanalysis**; and **no fault labels**, because
no public labelled record of real AWS faults exists.

### 1.2 What we built
AtmosGuard judges every reading with one of four verdicts, `VALID | WEATHER | SUSPECT | FAULT`, and gives the reason in words. Real
weather is **escalated as an alert (`WEATHER`), never deleted as noise**. A raw value is never overwritten; an estimate for a missing
or faulty value is stored beside it with an uncertainty band. Around the verdicts sit a health score, a drift monitor with a stated
detectability floor, a maintenance ticket with a projected service date, live fault injection for the demonstration, and an ESP32
node whose first layer is one portable C++ header that the tests compile and compare with the Python (Section 3).

### 1.3 What we claim, and what we do not
**We do not claim a new algorithm.** Physics checks, persistence tests, CUSUM, Isolation Forest, Mahalanobis distance, SHAP and
weather-versus-fault discrimination are standard, and Section 7 says where each comes from. We claim an **integration** built for one
station with no neighbours that copes with the rounded values real stations report, and an **evidence standard**: real records from 14
Indian stations, a holdout sealed in time and in space with the protocol committed first, false alarms on real cyclones reported
separately from injected-fault scores, baselines and an ablation on the same data, and the failures kept on record. Section 6 lists what
we cannot show.

### 1.4 Reading guide
Section 2 describes the data and the protocol. Section 3 describes the method. Section 4 gives the results exactly as the evaluation
program wrote them, in five separate numbers that are never merged. Section 5 explains what the holdout found that development did not.
Section 6 is the limitations. Section 7 is related work and what is ours. Section 8 shows how to reproduce everything.

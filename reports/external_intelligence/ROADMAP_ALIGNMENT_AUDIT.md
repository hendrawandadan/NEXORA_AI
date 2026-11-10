# AUDIT — Alignment of External Information Intelligence with MASTER_ROADMAP.md

**Tanggal audit:** sesi ini
**Acuan:** `docs/MASTER_ROADMAP.md` (living document), `HANDOFF_NEXT_SESSION.md`,
`GOVERNANCE_DECISION_PRD_001.md`, `FINAL_AUDIT_REPORT.md` (fase2a).
**Metode:** verifikasi kode & jalur nyata (bukan asumsi), menjalankan suite penuh.

---

## 0. RINGKASAN EKSEKUTIF

| Pertanyaan | Jawaban |
|---|---|
| Apakah ada jalur yang **terputus** (disconnected)? | **YA — beberapa.** Lihat §2. |
| Apakah ada yang **terlewat** (missing vs roadmap)? | **YA.** Lihat §3. |
| Apakah pekerjaan external-intelligence **sesuai** roadmap? | **Sebagian: maju terlalu jauh (Fase 4) sambil melewati gate Fase 2.** Lihat §1 & §4. |
| Ada regresi? | **Tidak.** Full suite **626 passed** (baseline handoff 534 + 92 baru). |

**Kesimpulan inti:** Secara *teknis* external-intelligence adalah kapabilitas nyata dan
teruji, tetapi ia berdiri sebagai **pulau terisolasi (orphan package)** yang **tidak
terhubung ke loop riset A–E**, dan secara roadmap ia melompat ke wilayah **Fase 4
(Global Market Intelligence)** padahal roadmap menetapkan **Fase 2 masih ACTIVE dan
belum GO** dan Fase 4 masih **PLANNED** dan "menunggu fondasi Fase 2 terbukti" (§9).

---

## 1. POSISI TERHADAP ROADMAP (yang paling penting)

Roadmap §3: **Fase 2 = ACTIVE**, **Fase 4 (Global Market Intelligence) = PLANNED**.
Roadmap §9: *"Perluasan pair & Global Intelligence tetap tujuan utama — tapi **menunggu**
fondasi Fase 2 terbukti."*

Bukti repo (bukan opini):
- `reports/fase2a/FINAL_AUDIT_REPORT.md` → **"Belum GO"**, berhenti menunggu persetujuan.
- `experiments/prep001_abc_sweep_...json` → **semua kandidat gagal net-of-cost**
  (kandidat B: `total_return` +0.09 @0 bps → **−0.37 @1 bps**; `profit_factor` < 1).
- `HANDOFF_NEXT_SESSION.md` §3j → hanya **`R_EVOLVE_NEW_INFO_SOURCE` (lane
  INFO_ACQUISITION) yang ALLOWED**; price-derived BLOCKED.

**Maka:** membangun pipeline external-intelligence **secara arah dibenarkan** (ini justru
"new information source" = syarat reopening #1, satu-satunya jalur maju jujur). **Tetapi
penempatannya harus dibingkai sebagai *penguat jalan INFO_ACQUISITION menuju keputusan
ulang Fase 2*, BUKAN sebagai lompatan resmi ke Fase 4.** Saat ini dokumentasi modul
(`new_information.py` docstring) menyebut "PHASE A5/A6/A7" — penomoran yang **tidak ada di
MASTER_ROADMAP** dan bisa disalahpahami sebagai ratifikasi fase baru. Ini **inkonsistensi
dokumentasi** yang harus dikoreksi (roadmap §"living document": perubahan fase harus
diratifikasi di roadmap dulu).

---

## 2. JALUR TERPUTUS (disconnected paths) — ditemukan & terverifikasi

> **STATUS UPDATE — P0 RESOLVED.** Item **2.1, 2.2, 2.3** di bawah **sudah diperbaiki**:
> `control_loop.run_control_loop` kini menerima `external_proposals` (INFO_ACQUISITION),
> mengekspor `external_intelligence` dari `nexora_research/__init__.py`, dan gate
> governance kini **lane-aware** (INFO_ACQUISITION diizinkan saat price-derived SUSPENDED;
> kandidat price-derived tetap BLOCKED). Tes: `tests/test_control_loop_external_intake.py`
> (11 baru). Full suite **637 passed**. Item 2.4 & 2.5 masih terbuka (lihat §7).
> — *Update berikutnya: item 2.4 kini RESOLVED (lihat blok di bawah & §2.4); hanya 2.5
> (scheduler cadence) yang tersisa di daftar ini.*
>
> **P0-2 RESOLVED (ratifikasi fase).** `docs/MASTER_ROADMAP.md` kini memuat **§3a** yang
> meratifikasi External Information Intelligence sebagai **enabler Fase 2 (INFO_ACQUISITION)**
> — bukan pembukaan Fase 4. Fase 2 & Fase 4 diberi catatan silang. Penomoran lama
> "PHASE A2–A7" di docstring modul **diganti** menjadi "External Information Intelligence —
> <Komponen> [INFO_ACQUISITION lane; enabler Fase 2]" (0 kemunculan "PHASE A" tersisa).
>
> **ITEM 2.4 RESOLVED (eksekusi akuisisi nyata).** `R_EVOLVE_NEW_INFO_SOURCE` (pemicu
> Tahap E) kini **benar-benar menjalankan akuisisi** lewat
> `strategy_evolution.execute_new_info_acquisition()`: proposal → `orchestrator.run_intelligence()`
> (akuisisi+interpretasi) → `run_control_loop(external_proposals=...)` (jalur riset). Hanya
> proposal `R_EVOLVE_NEW_INFO_SOURCE` ber-lane `INFO_ACQUISITION` + `ALLOWED` yang dieksekusi
> (fail-closed); `dry_run` default True; tidak pernah train/promote/trade/reopen. Tes:
> `tests/test_strategy_evolution_acquisition.py` (8 baru). Full suite **645 passed**.

### 2.1 `external_intelligence` adalah orphan package (SEVERITY: TINGGI)
Verifikasi `grep`: satu-satunya pemakai `external_intelligence`, `run_intelligence`,
`discover_new_information` adalah **tes miliknya sendiri + `tools/external_intel_registry.py`**.
- `nexora_research/__init__.py` **tidak** meng-export `external_intelligence`
  (hanya `store, failure_learning, knowledge_query, hypothesis_generator, registry,
  control_loop, strategy_evolution`).
- **Tidak ada** pemanggil di `control_loop.py`, `strategy_evolution.py`,
  `nexora_scheduler/` (kosong), atau runner.

**Akibat:** proposal eksternal tidak pernah masuk ke `OBSERVE` loop riset. Kapabilitas
ada, tetapi **tidak tersambung** ke siklus `OBSERVE→…→IMPROVE` (roadmap §5).

### 2.2 `control_loop.OBSERVE` tidak punya intake INFO_ACQUISITION (SEVERITY: TINGGI)
`run_control_loop(...)` hanya menerima `horizon_evidence`/`feature_power_evidence`
(turunan harga). Tidak ada parameter untuk menerima proposal eksternal / event / CB / news.
**Jalur dari `orchestrator.run_intelligence` → `control_loop` tidak ada.**

### 2.3 Jembatan proposal→hipotesis melewati gate governance loop (SEVERITY: SEDANG) — **RESOLVED (P1)**
`research_bridge.route_to_research_memory` memanggil `pre_register` +
`register_experiment_for` **langsung**, tidak lewat `control_loop._governance_gate`.
Untuk hipotesis INFO_ACQUISITION ini *aman* (bukan kandidat price-derived tersuspensi),
tetapi secara desain ia **melewati** jalur gate kanonik — berisiko bila kelak dipakai
untuk instrumen/tf/horizon tersuspensi. Perlu ditegakkan eksplisit.

> **FIXED (P1 — Canonical Governance Gate).** Lihat **§8** di bawah untuk audit lengkap,
> call graph, implementasi, dan bukti pengujian. Ringkas: ada **satu** gate kanonik
> (`control_loop.canonical_governance_gate`) dan `research_bridge` **mendelegasikan** ke
> gate itu **sebelum** `pre_register`/`register_experiment_for`. Tidak ada gate alternatif.

### 2.4 `R_EVOLVE_NEW_INFO_SOURCE` (Tahap E) tidak menyambung ke akuisisi nyata — **RESOLVED**
Tahap E hanya **mengeluarkan proposal generik "cari info baru"**. Ia **tidak** memanggil
`external_intelligence` untuk benar-benar mengakuisisi/mengolah data. Jadi ada dua
potongan yang **seharusnya bertemu** tetapi belum: Tahap E (pemicu) ↔ external_intelligence
(eksekutor).

> **FIXED:** ditambahkan `strategy_evolution.execute_new_info_acquisition(store, proposal, ...)`
> yang menjalankan `orchestrator.run_intelligence()` lalu merutekan proposal yang ditemukan
> ke `run_control_loop(external_proposals=...)`. Fail-closed: hanya
> `R_EVOLVE_NEW_INFO_SOURCE` + `INFO_ACQUISITION` + `ALLOWED`; `dry_run` default True;
> tidak pernah train/promote/trade/reopen. `IntelReport.discovered_proposals` (baru,
> tak terserialisasi) mengekspos proposal ke pemanggil. Tes:
> `tests/test_strategy_evolution_acquisition.py` (8).

### 2.5 Tidak ada scheduler/CLI cadence untuk pengumpulan eksternal (SEVERITY: RENDAH)
`nexora_scheduler/` kosong (sesuai roadmap Fase 7 PLANNED). Tidak ada runner berkala yang
memanggil `orchestrator.run_intelligence`. Wajar (di luar scope), tetapi menandakan
pipeline belum "hidup" otomatis.

---

## 3. YANG TERLEWAT (missing vs roadmap / gap internal)

| # | Item terlewat | Bukti | Dampak |
|---|---|---|---|
| 3.1 | Integrasi ke `nexora_research/__init__.py` + `config/research.json` | grep kosong | Modul tak resmi jadi bagian riset |
| 3.2 | Hook proposal eksternal di `control_loop.OBSERVE` | `control_loop.py` tak punya param | Loop tetap buta info eksternal |
| 3.3 | `lane` secara eksplisit di `research_hypotheses` (store) | `store.py` schema tak punya kolom lane | INFO vs PRICE lane hanya di `go_criteria`, tak ter-query |
| 3.4 | Konektor nyata ber-kredensial untuk mayoritas sumber | `connector_status`: FRED/NewsAPI UNCONFIGURED; BoJ/BoE belum | Data riil belum mengalir |
| 3.5 | Point-in-time / as-of (ALFRED) untuk hindari look-ahead data revisi | tidak ada di repo | Risiko leakage pada backtest event nyata |
| 3.6 | ~~Ratifikasi penomoran fase di MASTER_ROADMAP~~ **RESOLVED (P0-2)** | §3a + docstring diganti | Ambiguitas tata kelola fase **teratasi** |

Catatan: 3.4–3.5 memang **di luar scope** build ini dan sudah dinyatakan jujur di
`FINAL_EXTERNAL_INTELLIGENCE_REPORT.md` §10 (next steps). Bukan kelalaian, tetapi tetap
"terlewat" relatif visi roadmap.

---

## 4. YANG SUDAH BENAR & TERSAMBUNG (verifikasi, bukan klaim)

- `research_bridge` benar-benar memakai API nyata yang ada:
  - `pre_register(store, hyp)` ✔ (signature cocok)
  - `register_experiment_for(store, hyp_id, hyp)` ✔
  - `store.record_knowledge(kind="STRATEGY_LEAD")` ✔ (`KNOWLEDGE_KINDS` memuatnya)
  - `knowledge_query.list_knowledge` ✔ ada
  - `GeneratedHypothesis` field cocok persis ✔
- Nama aksi governance yang dipakai (`train`, `promote_model`, `enable_live_trading`,
  `auto_reopen`) **benar-benar** ada di `PROHIBITED_ACTIONS` → guard aktif, bukan no-op.
- Isolasi DB: `test_isolation.py` membuktikan `nexora_state.db` & `nexora_research.db`
  **byte-identik** sebelum/sesudah run.
- Lane proposals = INFO_ACQUISITION saja; price-derived tetap BLOCKED (dites).

---

## 5. TES & REPRODUKSI

```
.\.venv\Scripts\python.exe -m pytest tests -q                         # 645 passed
.\.venv\Scripts\python.exe -m pytest tests/external_intelligence -q  # 92 passed
```

## 6. REKOMENDASI PERBAIKAN (prioritas)

1. **P0 — Sambungkan atau tandai eksplisit.** Tambahkan parameter `external_proposals`
   (opsional) pada `run_control_loop.OBSERVE`, atau buat adapter resmi
   `external_intelligence → control_loop`. Jika belum, tandai modul sebagai
   `status="available, not yet wired"` agar tidak menyesatkan.
2. **P0 — Ratifikasi fase.** ✅ **DONE**: `MASTER_ROADMAP.md` §3a meratifikasi pekerjaan
   ini sebagai **enabler INFO_ACQUISITION (reopening condition #1)**, bukan pembukaan
   Fase 4. Penomoran "PHASE A5/A6/A7" diganti menjadi "External Information Intelligence".
3. **P1 — Ekspor resmi.** Tambahkan `external_intelligence` ke `nexora_research/__init__.py`
   dan entri konfigurasi (path DB, provider aktif) di `config/`.
4. **P1 — Gate kanonik.** Agar `research_bridge` untuk instrumen tersuspensi juga melewati
   `_governance_gate`/`is_candidate_suspended` sebelum `pre_register`.
5. **P2 — Kolom `lane`** di `research_hypotheses` (migration) supaya INFO vs PRICE
   ter-query dan tidak tercampur.
6. **P2 — Data riil PIT**: konektor ber-kredensial + as-of store (lihat laporan external
   §10), sebelum klaim apa pun dari data nyata.

---

## 7. KESIMPULAN JUJUR

- **Tidak ada regresi** dan **tidak ada pelanggaran governance** (seluruh aksi terlarang
  tetap terblokir, terbukti tes).
- **Jalur terputus sudah ditutup (P0):** package external-intelligence kini tersambung ke
  `control_loop` lewat `external_proposals`, dan pemicu `R_EVOLVE_NEW_INFO_SOURCE` kini
  **benar-benar menjalankan akuisisi** (`execute_new_info_acquisition`) lalu merutekan
  hasilnya ke loop riset. Sisa terbuka: **2.5** (scheduler cadence, P2) dan P1/P2 lain.
- **Secara roadmap**: arah benar (satu-satunya jalan maju jujur = info baru), dan posisi
  fase **telah diratifikasi** (§3a) agar tidak tampak "melompat ke Fase 4".
- **Tidak ada edge yang diklaim.** Semua temuan = research lead belum tervalidasi.

---

## 8. P1 — CANONICAL GOVERNANCE GATE (VERIFIED)

**Tujuan.** Memastikan seluruh jalur riset NEXORA melewati canonical governance gate yang
SAMA, tanpa bypass — termasuk jalur dari `external_intelligence`, `strategy_evolution`,
dan `control_loop`.

### 8.1 TAHAP 1 — Audit READ-ONLY (call graph)

Entry point yang menyentuh registry / pembuatan eksperimen / eksekusi riset:

| Entry point | Pemanggil | Jalur registry/eksperimen sebelum P1 |
|---|---|---|
| `research_bridge.route_to_research_memory(register=True)` | `orchestrator.run_intelligence(register=...)`, `execute_new_info_acquisition` | `_governance_preflight()` (LIGHT) → `pre_register` → `register_experiment_for` **LANGSUNG** |
| `research_bridge.prepare_hypothesis` | bridge / orchestrator | hanya cek `lane==INFO` + `status=="ALLOWED"` (string) |
| `research_bridge.persist_proposal`, `record_external_finding` | orchestrator | external repo / knowledge saja (bukan registrasi) |
| `control_loop.run_control_loop(external_proposals=...)` | `strategy_evolution`, tests | `_external_records` → `_proposal_to_hypothesis` → `_register_external_hypothesis` (registrasi) SEBELUM `_governance_gate` |
| `control_loop.run_control_loop(horizon_evidence=...)` | tests, strategy_evolution | `registry.generate_and_register` lalu `_governance_gate` |

**BY PASS DIBUKTIKAN:**
1. `research_bridge` memanggil `pre_register`/`register_experiment_for` **tanpa** melewati
   `control_loop._governance_gate`; `_governance_preflight` **bukan** gate kanonik (tidak
   memeriksa `is_candidate_suspended`, tidak memeriksa rule_id, tidak mendelegasi ke gate).
2. Di `control_loop`, `_external_records` (yang mendaftarkan hipotesis) dipanggil **SEBELUM**
   gate governance — sehingga registrasi terjadi lebih dulu, gate belakangan (urutan bocor).
3. Tidak ada pemeriksaan `rule_id` (lane-laundering: rule price-shaped di bawah lane INFO).

Konsistensi yang diaudit (sebelum P1): `lane` dicek longgar (string), `governance_status`
dicek string, `rule_id` **tidak** dicek sama sekali di bridge, `suspension` hanya dicek
sebagai *arming* guard (bukan per-kandidat) di bridge.

### 8.2 TAHAP 2 — Implementasi TERBATAS

Satu-satunya gate kanonik (baru, TIDAK berbeda aturan antar-pemanggil):

`nexora_research/control_loop.py`
- `GovernanceDecision` — verdict fail-closed + audit trail (`as_dict`).
- `canonical_governance_gate(...)` — **THE** gate. Aturan:
  1. `governance_status` wajib tepat `"ALLOWED"`. UNKNOWN / invalid / kosong / tak dapat
     diverifikasi → **BLOCKED** (fail-closed).
  2. `lane` wajib dikenal. `None`/unknown → **BLOCKED**.
     - `INFO_ACQUISITION`: **diizinkan** saat price-derived SUSPENDED (reopening condition
       #1) — TAPI hanya untuk rule `R_EXT_*` (rule price-shaped dismuggle → dicek ulang
       sebagai price-derived dan **BLOCKED**).
     - `PRICE_DERIVED`: kandidat tersuspensi → **BLOCKED** (semantik kandidat yang sudah
       berlaku; dipertahankan agar `test_control_loop.py` tidak berubah).
  3. Status suspensi **hanya DIBACA** dari registry pusat — gate **tidak pernah** mengubahnya.
- `run_control_loop` — Gate 2 kini memakai `canonical_governance_gate`.
- `_external_records` — gate kanonik dijalankan **SEBELUM** registrasi; proposal yang
  gagal **tidak** didaftarkan (hanya dilaporkan BLOCKED).

`nexora_research/external_intelligence/research_bridge.py`
- `_governance_gate(proposal)` — **mendelegasikan** ke `control_loop.canonical_governance_gate`
  (bukan gate alternatif). Bridge hanya merutekan `INFO_ACQUISITION`; lane lain **ditolak**.
- `prepare_hypothesis` & `route_to_research_memory` — gate kanonik dijalankan **SEBELUM**
  `pre_register`. Registrasi tidak pernah terjadi bila gate BLOCKED.
- Audit trail: knowledge `STRATEGY_LEAD` menyimpan `gate` (verdict) bersama id.

Jaminan yang ditegakkan:
- INFO_ACQUISITION tetap berjalan sesuai kebijakan ✔
- PRICE_DERIVED tetap **SUSPENDED** (kandidat tersuspensi diblokir; bridge menolak lane
  price-derived sepenuhnya) ✔
- UNKNOWN / invalid / tak-terverifikasi → **BLOCKED** ✔
- Tidak ada perubahan status suspensi otomatis ✔
- Semua jalur punya audit trail (report outcomes + knowledge `gate` detail) ✔

### 8.3 TAHAP 3 — Pengujian

`tests/test_canonical_governance_gate_p1.py` (**30 tes baru**):
- INFO_ACQUISITION valid melewati gate ✔
- PRICE_DERIVED diblokir selama suspensi aktif ✔
- UNKNOWN lane diblokir ✔ (+ `None` lane)
- Governance status selain ALLOWED diblokir (parametrized) ✔
- `research_bridge` tidak bisa melewati canonical gate (delegasi identik) ✔
- Jalur langsung vs tidak langsung tunduk pada aturan sama (`test_direct_and_indirect_paths_agree`) ✔
- Tidak ada registrasi eksperimen yang lolos dari gate (loop & bridge) ✔
- Tidak ada training / tuning / promotion / live trading (+ auto_reopen) ✔
- Tidak ada perubahan status suspensi ✔
- Production DB tidak tersentuh ✔

### 8.4 TAHAP 4 — Regression & Verification

```
.\.venv\Scripts\python.exe -m pytest tests/test_canonical_governance_gate_p1.py -q  # 30 passed
.\.venv\Scripts\python.exe -m pytest tests -q                                       # 675 passed
```

- **Baseline sebelum P1:** 645 passed. **Sesudah P1:** 675 passed (645 + 30 baru). **0 regresi.**
- **Integritas production DB:** `nexora_state.db` sha256 **identik** sebelum & sesudah
  (`7d945b4d…`). `nexora_research.db` juga identik (`877ba913…`). Hanya DB eksternal
  terisolasi (`nexora_external_intel.db`) yang ditulis oleh tes isolasi DBnya sendiri.
- **Konfigurasi governance sebelum & sesudah:** `status=SUSPENDED`, daftar
  `suspended_candidates` (5 kandidat) **tidak berubah**.

### 8.5 File yang berubah

| File | Perubahan |
|---|---|
| `nexora_research/control_loop.py` | + `GovernanceDecision`, + `canonical_governance_gate`; Gate 2 & `_external_records` memakai gate kanonik SEBELUM registrasi |
| `nexora_research/external_intelligence/research_bridge.py` | `_governance_gate` mendelegasikan ke gate kanonik; gate dijalankan SEBELUM `pre_register`; lane non-INFO ditolak; audit trail `gate` |
| `tests/test_canonical_governance_gate_p1.py` | **baru** — 30 tes |
| `reports/external_intelligence/ROADMAP_ALIGNMENT_AUDIT.md` | §8 (bagian ini) + penandaan §2.3 RESOLVED |

### 8.6 Risiko tersisa

- **R-1 (RENDAH).** Pada jalur price-derived `run_control_loop`, `generate_and_register`
  masih mendaftarkan hipotesis/hypothesis PRE_REGISTERED **sebelum** Gate 2 menandai
  BLOCKED untuk kandidat tersuspensi. Ini perilaku **pra-eksisting** (bukan regresi P1):
  tidak ada training/evaluasi, dan status suspensi tidak berubah. Di luar cakupan P1
  (fokus: research_bridge). Dicatat untuk P2 (reorder registrasi di `generate_and_register`
  atau pra-gate sebelum registrasi).
- **R-2 (RENDAH).** Gate block pada `research_bridge` tetap **mempersist proposal** ke DB
  eksternal terisolasi sebagai provenance (bukan registrasi eksperimen). Ini disengaja agar
  percobaan yang diblokir tetap dapat diaudit; tidak menyentuh research DB maupun
  production DB.
- **R-3 (RENDAH).** Cakupan gate untuk *tooling* eksternal (`tools/external_intel_registry.py`)
  hanya membaca registry, tidak membuat eksperimen — tidak ada bypass.
- Scheduler tidak diaktifkan; tidak ada training/tuning/promotion/live; ATR baseline &
  data historis tidak berubah; tidak ada akuisisi eksternal live; scope tidak melebar ke P2.

**Status P1: VERIFIED.**

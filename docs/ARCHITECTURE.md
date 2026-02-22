# Mimari Dokumantasyon

## Genel Bakis

Annem Guvende, tek bir Docker container icinde calisan **FastAPI** tabanli bir uygulamadir.

| Bilesen | Teknoloji |
|---------|-----------|
| Web framework | FastAPI + uvicorn (port 8099) |
| Veritabani | SQLite (WAL modu, busy_timeout=5000ms) |
| Zamanlayici | APScheduler 3.x AsyncIOScheduler (Europe/Istanbul) |
| MQTT | paho-mqtt 2.x (arka plan thread) |
| Bildirim | Telegram Bot API (sync httpx) |
| Frontend | Chart.js (offline, bundled) |
| Konfigursyon | Pydantic BaseModel (9 alt model) |
| CI/CD | GitHub Actions (ruff + pytest) |

Uygulama `src/main.py` icerisindeki async lifespan fonksiyonu ile baslatilir. Lifespan:
1. Config yukler (`config.yml` veya `config.yml.example` fallback)
2. SQLite veritabanini baslatir (migrasyon)
3. MQTT baglantisini kurar
4. APScheduler'i 11 gorevle baslatir
5. Telegram notifier olusturur
6. Static dosyalari mount eder

---

## Veri Akisi

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│   Zigbee    │────>│ Zigbee2MQTT  │────>│ MQTT Broker  │
│  Sensorler  │     │              │     │  (:1883)     │
└─────────────┘     └──────────────┘     └──────┬───────┘
                                                │
                                    ┌───────────┴───────────┐
                                    │     MQTTCollector      │
                                    │  parse + debounce(30s) │
                                    │  + active filtre       │
                                    └───────────┬───────────┘
                                                │
                                    ┌───────────┴───────────┐
                                    │    sensor_events      │
                                    │      (SQLite)         │
                                    └───────────┬───────────┘
                                                │ her 15 dk
                                    ┌───────────┴───────────┐
                                    │    SlotAggregator     │
                                    │  96 slot x N kanal    │
                                    └───────────┬───────────┘
                                                │
                                    ┌───────────┴───────────┐
                                    │    slot_summary       │
                                    │      (SQLite)         │
                                    └───────────┬───────────┘
                                                │ gunluk 00:15
                                    ┌───────────┴───────────┐
                                    │   RoutineLearner      │
                                    │  Beta-Binomial update │
                                    └───────────┬───────────┘
                                                │
                                    ┌───────────┴───────────┐
                                    │  model_state +        │
                                    │  daily_scores         │
                                    └───────────┬───────────┘
                                                │ gunluk 00:20
                                    ┌───────────┴───────────┐
                                    │   AnomalyScorer       │
                                    │  NLL + Z-score        │
                                    │  ThresholdEngine      │
                                    └───────────┬───────────┘
                                                │
                                    ┌───────────┴───────────┐
                                    │    AlertManager       │
                                    │  rate limiting        │
                                    │  explanation          │
                                    └───────────┬───────────┘
                                                │
                                    ┌───────────┴───────────┐
                                    │  Telegram Bot API     │
                                    │  Bildirim + Komutlar  │
                                    └───────────────────────┘
```

---

## Veritabani Semasi

SQLite WAL modunda calisir. 6 tablo:

### sensor_events

Ham sensor olaylari.

| Kolon | Tip | Aciklama |
|-------|-----|----------|
| id | INTEGER PK | Otomatik artan |
| timestamp | TEXT NOT NULL | ISO format (YYYY-MM-DD HH:MM:SS) |
| sensor_id | TEXT NOT NULL | Zigbee2MQTT friendly name |
| channel | TEXT NOT NULL | presence / fridge / bathroom / door |
| event_type | TEXT DEFAULT 'state_change' | Olay tipi |
| value | TEXT | Ham deger |
| created_at | TEXT | Kayit zamani |

**Indeksler:** `idx_events_ts(timestamp)`, `idx_events_channel(channel, timestamp)`

### slot_summary

15 dakikalik zaman dilimi ozetleri.

| Kolon | Tip | Aciklama |
|-------|-----|----------|
| date | TEXT | YYYY-MM-DD |
| slot | INTEGER | 0-95 (15dk aralik, 24 saat) |
| channel | TEXT | Kanal adi |
| active | INTEGER | 1 = olay var, 0 = yok |
| event_count | INTEGER | Olay sayisi |

**PK:** `(date, slot, channel)`

### daily_scores

Gunluk anomali skorlari ve metrikler.

| Kolon | Tip | Aciklama |
|-------|-----|----------|
| date | TEXT PK | YYYY-MM-DD |
| train_days | INTEGER | Toplam egitim gunu sayisi |
| nll_presence | REAL | Presence kanal NLL |
| nll_fridge | REAL | Fridge kanal NLL |
| nll_bathroom | REAL | Bathroom kanal NLL |
| nll_door | REAL | Door kanal NLL |
| nll_total | REAL | Toplam NLL |
| expected_count | REAL | Beklenen olay sayisi |
| observed_count | INTEGER | Gozlenen olay sayisi |
| count_z | REAL | Count Z-skoru |
| composite_z | REAL | Bilesik Z-skoru |
| alert_level | INTEGER DEFAULT 0 | 0-3 alarm seviyesi |
| aw_accuracy | REAL | Uyanik saat dogrulugu |
| aw_balanced_acc | REAL | Dengeli dogruluk |
| aw_active_recall | REAL | Aktif geri cagirma |
| is_learning | INTEGER DEFAULT 1 | 1 = ogrenme, 0 = aktif |
| created_at | TEXT | Kayit zamani |

### model_state

Beta-Binomial model parametreleri.

| Kolon | Tip | Aciklama |
|-------|-----|----------|
| slot | INTEGER | 0-95 zaman dilimi |
| channel | TEXT | Kanal adi |
| alpha | REAL DEFAULT 1 | Beta dagilimi alpha |
| beta | REAL DEFAULT 1 | Beta dagilimi beta |
| last_updated | TEXT | Son guncelleme |

**PK:** `(slot, channel)`

### system_state

Key-value sistem durumu.

| Kolon | Tip | Aciklama |
|-------|-----|----------|
| key | TEXT PK | Durum anahtari (ornegin `vacation_mode`) |
| value | TEXT NOT NULL | Deger |
| updated_at | TEXT | Son guncelleme |

### schema_version

Veritabani migrasyon takibi.

| Kolon | Tip | Aciklama |
|-------|-----|----------|
| version | INTEGER PK | Migrasyon numarasi |
| applied_at | TEXT | Uygulama zamani |

---

## ML Pipeline

### Model: Beta-Binomial

Konjuge prior (conjugate prior) Bayesian model. Her zaman dilimi ve kanal icin bagimsiz Beta dagilimi.

**Boyutlar:**
- 96 zaman dilimi (15 dakika aralik, 24 saat)
- 4 varsayilan kanal: presence, fridge, bathroom, door
- Toplam: **384 parametre** (96 x 4, her biri alpha + beta cifti)

**Prior:** `Beta(1.0, 1.0)` = uniform (konfigurasyondan degistirilebilir)

**Guncelleme (immutable):**
- Slot aktif (olay var): `alpha += 1`
- Slot pasif (olay yok): `beta += 1`

**Olasilik:** `E[p] = alpha / (alpha + beta)`

### NLL Hesaplama

Her gun icin, her slot ve kanalda:
- Slot aktif: `NLL = -log(p)` (dusuk olasilikli aktivite = yuksek NLL)
- Slot pasif: `NLL = -log(1 - p)` (yuksek olasilikli pasiflik = dusuk NLL)
- p [0.001, 0.999] araligina clamp edilir

Kanal bazli NLL toplanir: `nll_total = sum(nll_presence, nll_fridge, nll_bathroom, nll_door)`

### Composite Z-Score

Iki bagimsiz sinyalin maksimumu:

```
composite_z = max(nll_z, count_risk)
```

- `nll_z = max(0, (nll_total - mean_nll) / std_nll)` — tek yonlu, sadece yuksek NLL riskli
- `count_risk = max(0, -count_z)` — tek yonlu, sadece dusuk aktivite riskli

### Alarm Seviyeleri

| Seviye | Ad | Esik | Varsayilan |
|--------|----|------|-----------|
| 0 | Normal | `composite_z < z_gentle` | < 2.0 |
| 1 | Nazik Kontrol | `z_gentle <= composite_z < z_serious` | 2.0 - 3.0 |
| 2 | Ciddi | `z_serious <= composite_z < z_emergency` | 3.0 - 4.0 |
| 3 | Acil | `composite_z >= z_emergency` | >= 4.0 |

**Ogrenme donemi (ilk 14 gun):** Alarm seviyesi maksimum 1 ile sinirlidir.

**Rate limiting:** Ayni seviye icin 6 saat sogutma suresi. Seviye artisi sogutmayi atlar.

---

## Zamanlayici Gorevleri

APScheduler ile yonetilen 11 gorev:

| Gorev | Tip | Zamanlama | Aciklama |
|-------|-----|-----------|----------|
| `slot_aggregator` | cron | `minute="0,15,30,45"` | 15dk slot ozetleme |
| `fill_missing_slots` | cron | `hour=0, minute=5` | Onceki gun eksik slotlari doldur |
| `daily_learning` | cron | `hour=0, minute=15` | Gunluk model ogrenme |
| `daily_scoring` | cron | `hour=0, minute=20` | Gunluk anomali skorlama |
| `realtime_checks` | cron | `minute="0,30"` | Sabah sessizlik + uzun sessizlik |
| `daily_summary` | cron | `hour=22, minute=0` | Gunluk Telegram ozet |
| `heartbeat` | interval | `seconds=config` | VPS heartbeat ping |
| `system_watchdog` | cron | `minute="0,15,30,45"` | CPU/RAM/disk saglik kontrolu |
| `mqtt_retry` | interval | `seconds=30` | MQTT yeniden baglanti |
| `nightly_maintenance` | cron | `hour=3, minute=0` | DB temizlik + WAL checkpoint |
| `telegram_commands` | interval | `seconds=30` | Telegram komut polling |

**Tatil modunda atlanan gorevler:** `daily_learning`, `daily_scoring`, `realtime_checks`, `daily_summary`

**Kosullu gorevler:** `heartbeat` (config.heartbeat.enabled), `telegram_commands` (notifier.enabled)

---

## Guvenlik Katmanlari

| Katman | Mekanizma | Aciklama |
|--------|-----------|----------|
| **Dashboard** | HTTP Basic Auth | `BasicAuthMiddleware`, `/health` haric tum endpoint'ler korunur |
| **Telegram** | Chat ID filtresi | Sadece `config.yml`'deki kayitli `chat_id`'ler komut gonderebilir |
| **Veri** | Lokal SQLite | Tum veri cihazda kalir, bulut bagimliligi yok |
| **Mahremiyet** | Sensor tipi | Kamera yok, mikrofon yok, sadece hareket ve kapi sensorleri |
| **Config** | .gitignore | `config.yml` (token, sifre iceren) repo disinda tutulur |
| **CI/CD** | GitHub Actions | Her push'ta `ruff check` + `pytest` otomatik calisir |

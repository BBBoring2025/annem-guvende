# Annem Güvende — Claude Code Sprint Planı

## Proje Özeti

**Ne yapıyoruz:** Raspberry Pi üzerinde Home Assistant yanında çalışan, yaşlı bireyin günlük rutinini sensör verisiyle öğrenen, anomali tespit eden ve aileye kademeli bildirim gönderen Python tabanlı bir sistem.

**Ne yapmıyoruz (kapsam dışı):**
- Kamera / mikrofon / ses kaydı (mahremiyet)
- Tıbbi teşhis / düşme algılama iddiası
- Bulut bağımlı işleme (local-first)
- Mobil uygulama (MVP'de Telegram yeterli)

---

## Mimari Genel Bakış

```
┌─────────────────────────────────────────────────┐
│                 Raspberry Pi 4                   │
│                                                  │
│  ┌──────────────┐    ┌────────────────────────┐  │
│  │ Home         │    │  Annem Güvende Engine   │  │
│  │ Assistant    │◄──►│  (Docker Container)     │  │
│  │              │    │                          │  │
│  │ Zigbee       │    │  ┌──────────┐           │  │
│  │ Sensörler ──►│────┤  │ Collector│           │  │
│  │              │MQTT│  └────┬─────┘           │  │
│  │ Blueprints   │    │       │                 │  │
│  │ (SOS, Banyo) │    │  ┌────▼─────┐           │  │
│  └──────────────┘    │  │ SQLite   │           │  │
│                      │  │ Events DB│           │  │
│                      │  └────┬─────┘           │  │
│                      │       │                 │  │
│                      │  ┌────▼─────┐           │  │
│                      │  │ Learner  │ Beta-Bin  │  │
│                      │  │ Engine   │ per-sensor│  │
│                      │  └────┬─────┘           │  │
│                      │       │                 │  │
│                      │  ┌────▼─────┐           │  │
│                      │  │ Anomaly  │ NLL+Count │  │
│                      │  │ Detector │ +2-sided  │  │
│                      │  └────┬─────┘           │  │
│                      │       │                 │  │
│                      │  ┌────▼─────┐           │  │
│                      │  │ Alerter  │──► Telegram│  │
│                      │  │ Engine   │──► TTS     │  │
│                      │  └──────────┘           │  │
│                      │                          │  │
│                      │  ┌──────────┐            │  │
│                      │  │ FastAPI  │──► Dashboard│  │
│                      │  │ Web UI   │  (lokal)   │  │
│                      │  └──────────┘            │  │
│                      └──────────────────────────┘  │
│                                                    │
│  ┌──────────────┐                                  │
│  │ Heartbeat    │──────► Dış VPS (5dk/ping)        │
│  │ Client       │                                  │
│  └──────────────┘                                  │
└────────────────────────────────────────────────────┘
```

## Teknoloji Kararları

| Katman | Seçim | Gerekçe |
|--------|-------|---------|
| Dil | Python 3.11+ | Pi uyumu, math kütüphaneleri, HA entegrasyonu |
| Veritabanı | SQLite | Tek dosya, yedekleme kolay, Pi'de yeterli |
| Sensör iletişimi | MQTT (Zigbee2MQTT) | Event-driven, güvenilir, standart |
| Web framework | FastAPI | Async, hafif, Pi'de iyi performans |
| Bildirim | Telegram Bot API | Türkiye'de yaygın, ücretsiz, zengin mesaj formatı |
| Konteyner | Docker Compose | HA yanında izole çalışma, kolay güncelleme |
| Zamanlayıcı | APScheduler | Gece batch, gün sonu skorlama |

---

## Sensör → Kanal Eşleşmesi

| Fiziksel Sensör | MQTT Topic Örneği | Kanal Adı | Anlamı |
|-----------------|-------------------|-----------|--------|
| Aqara Motion (mutfak) | `zigbee2mqtt/mutfak_motion` | `presence` | Genel hareket/varlık |
| Aqara Motion (salon) | `zigbee2mqtt/salon_motion` | `presence` | Genel hareket/varlık |
| Aqara Door (buzdolabı) | `zigbee2mqtt/buzdolabi_kapi` | `fridge` | Beslenme kanıtı |
| Aqara Door (banyo kapı) | `zigbee2mqtt/banyo_kapi` | `bathroom` | Hijyen/hareket kanıtı |
| Aqara Door (dış kapı) | `zigbee2mqtt/dis_kapi` | `door` | Dışarı çıkma/sosyal aktivite |
| Aqara Button (SOS) | `zigbee2mqtt/sos_button` | `sos` | Manuel alarm (ayrı işlenir) |

---

## Veri Şeması

### `sensor_events` tablosu (ham veri)
```sql
CREATE TABLE sensor_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,           -- ISO 8601
    sensor_id   TEXT NOT NULL,           -- "mutfak_motion"
    channel     TEXT NOT NULL,           -- "presence" | "fridge" | "bathroom" | "door"
    event_type  TEXT NOT NULL DEFAULT 'state_change',
    value       TEXT,                    -- "on"/"off", "open"/"closed"
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_events_ts ON sensor_events(timestamp);
CREATE INDEX idx_events_channel ON sensor_events(channel, timestamp);
```

### `slot_summary` tablosu (15dk özetler)
```sql
CREATE TABLE slot_summary (
    date        TEXT NOT NULL,            -- "2025-02-11"
    slot        INTEGER NOT NULL,         -- 0-95 (15dk dilimler)
    channel     TEXT NOT NULL,            -- "presence" | "fridge" | "bathroom" | "door"
    active      INTEGER NOT NULL DEFAULT 0, -- 0 veya 1
    event_count INTEGER NOT NULL DEFAULT 0, -- slot içindeki toplam event
    PRIMARY KEY (date, slot, channel)
);
```

### `daily_scores` tablosu (gün sonu analiz)
```sql
CREATE TABLE daily_scores (
    date              TEXT PRIMARY KEY,
    train_days        INTEGER,
    -- Per-sensor NLL
    nll_presence      REAL,
    nll_fridge        REAL,
    nll_bathroom      REAL,
    nll_door          REAL,
    nll_total         REAL,
    -- Event count scores
    expected_count    REAL,
    observed_count    INTEGER,
    count_z           REAL,
    -- Composite
    composite_z       REAL,           -- combined anomaly score
    alert_level       INTEGER DEFAULT 0, -- 0=normal, 1=nazik, 2=ciddi, 3=acil
    -- Awake window metrics
    aw_accuracy       REAL,
    aw_balanced_acc   REAL,
    aw_active_recall  REAL,
    -- Metadata
    is_learning       INTEGER DEFAULT 1, -- ilk 14 gün
    created_at        TEXT DEFAULT (datetime('now'))
);
```

### `model_state` tablosu (Beta parametreleri)
```sql
CREATE TABLE model_state (
    slot        INTEGER NOT NULL,         -- 0-95
    channel     TEXT NOT NULL,
    alpha       REAL NOT NULL DEFAULT 1,  -- Beta α (prior + successes)
    beta        REAL NOT NULL DEFAULT 1,  -- Beta β (prior + failures)
    last_updated TEXT,
    PRIMARY KEY (slot, channel)
);
```

---

## SPRINT PLANI

Her sprint = Claude Code'a verilecek bağımsız bir görev.
Tahmini süre: sprint başına 1-2 saat Claude Code çalışması.

---

### SPRINT 0: Proje İskeleti
**Hedef:** Çalışan boş proje yapısı, Docker, DB migration, config

**Claude Code Prompt:**
```
Raspberry Pi üzerinde çalışacak "Annem Güvende" (annem_guvende) Python projesi oluştur.

Proje yapısı:
annem_guvende/
├── docker-compose.yml          # Ana servis + mosquitto (opsiyonel)
├── Dockerfile                  # Python 3.11-slim tabanlı
├── requirements.txt
├── config.yml.example          # Örnek konfigürasyon
├── src/
│   ├── __init__.py
│   ├── main.py                 # Entry point, APScheduler başlatır
│   ├── config.py               # YAML config yükleyici
│   ├── database.py             # SQLite bağlantı + migration'lar
│   ├── models.py               # Pydantic veri modelleri
│   ├── collector/              # Sprint 1
│   │   └── __init__.py
│   ├── learner/                # Sprint 2
│   │   └── __init__.py
│   ├── detector/               # Sprint 3
│   │   └── __init__.py
│   ├── alerter/                # Sprint 4
│   │   └── __init__.py
│   ├── heartbeat/              # Sprint 5
│   │   └── __init__.py
│   └── dashboard/              # Sprint 6
│       └── __init__.py
├── tests/
│   ├── __init__.py
│   ├── test_database.py
│   └── conftest.py
└── scripts/
    └── init_db.py

Gereksinimler:
- Python 3.11+
- SQLite3 (built-in)
- paho-mqtt (MQTT client)
- apscheduler (zamanlayıcı)
- fastapi + uvicorn (dashboard API)
- pyyaml (config)
- pydantic (data validation)
- httpx (Telegram API + heartbeat)
- pytest (test)

config.yml yapısı:
```yaml
mqtt:
  broker: "localhost"
  port: 1883
  topic_prefix: "zigbee2mqtt"

sensors:
  - id: "mutfak_motion"
    channel: "presence"
    type: "motion"
    trigger_value: "on"          # veya {"occupancy": true}
  - id: "buzdolabi_kapi"
    channel: "fridge"
    type: "contact"
    trigger_value: "open"
  - id: "banyo_kapi"
    channel: "bathroom"
    type: "contact"
    trigger_value: "open"
  - id: "dis_kapi"
    channel: "door"
    type: "contact"
    trigger_value: "open"

model:
  slot_minutes: 15              # 96 slots/gün
  awake_start_hour: 6           # 06:00
  awake_end_hour: 23            # 23:00
  learning_days: 14             # minimum öğrenme süresi
  prior_alpha: 1.0              # Beta prior
  prior_beta: 1.0

alerts:
  z_threshold_gentle: 2.0       # nazik kontrol
  z_threshold_serious: 3.0      # aile bildirimi
  z_threshold_emergency: 4.0    # acil durum
  min_train_days: 7             # alarm başlamadan önce min gün

telegram:
  bot_token: ""
  chat_ids: []                  # aile üyeleri

heartbeat:
  enabled: false
  url: ""                       # dış VPS endpoint
  interval_seconds: 300         # 5 dakika

database:
  path: "./data/annem_guvende.db"
```

database.py şunları içermeli:
- init_db() → yukarıdaki 4 tabloyu oluştur (IF NOT EXISTS)
- get_db() → SQLite connection context manager
- Migration versiyonlama (basit: schema_version tablosu)

main.py şunları içermeli:
- Config yükle
- DB başlat
- MQTT bağlantısı placeholder
- APScheduler başlat (boş job'lar - sonraki sprint'lerde doldurulacak)
- Graceful shutdown (SIGTERM)

Docker:
- Python 3.11-slim base
- /app/data volume mount (DB + logs)
- /app/config volume mount (config.yml)
- Network: host (MQTT erişimi için)

Test:
- test_database.py: DB oluşturma, tablo varlığı, basit insert/select

Tüm kodda Türkçe yorum satırları kullan.
```

---

### SPRINT 1: Veri Toplama (Collector)
**Hedef:** MQTT'den sensör eventlerini al, DB'ye yaz, 15dk slot özetleri üret

**Claude Code Prompt:**
```
annem_guvende projesinin collector modülünü geliştir.

src/collector/
├── __init__.py
├── mqtt_client.py        # MQTT bağlantısı ve event dinleme
├── event_processor.py    # Ham event → slot_summary dönüştürme
└── slot_aggregator.py    # 15dk periyodik slot özetleme

Davranış:

1. mqtt_client.py:
   - config.yml'deki sensörleri dinle
   - Zigbee2MQTT mesaj formatlarını parse et:
     * Motion sensör: {"occupancy": true/false} veya basit "on"/"off"
     * Contact sensör: {"contact": true/false} veya "open"/"closed"
   - Her event'i sensor_events tablosuna kaydet
   - Bağlantı kopması durumunda otomatik reconnect (exponential backoff)
   - Last Will and Testament (LWT) mesajı ayarla

2. event_processor.py:
   - Gelen ham event'i normalize et:
     * sensor_id + channel + timestamp + active(0/1)
   - Debounce: Aynı sensörden 30sn içinde gelen tekrar event'leri filtrele
     (motion sensörleri çok sık tetiklenir)

3. slot_aggregator.py (her 15 dakikada çalışır):
   - Son 15dk içindeki eventleri kontrol et
   - Her (date, slot, channel) için:
     * active = 1 eğer slot içinde en az 1 event varsa
     * event_count = slot içindeki toplam event sayısı
   - slot_summary tablosuna upsert et

   Slot hesaplama:
   ```python
   def get_slot(dt: datetime) -> int:
       """15dk slot numarası (0-95)"""
       return dt.hour * 4 + dt.minute // 15
   ```

4. main.py entegrasyonu:
   - MQTT client başlat
   - APScheduler'a 15dk'lık slot_aggregator job'ı ekle
   - Cron: her gün 00:05'te önceki günün eksik slotlarını doldur
     (tüm boş slotlar = active:0 olarak kaydet)

Test:
- test_mqtt_client.py: Mock MQTT mesajlarıyla event parsing
- test_slot_aggregator.py: Bilinen event listesiyle slot özetleme doğruluğu
- test_debounce.py: 30sn debounce kuralı

Edge case'ler:
- Gece yarısı geçişi (23:45 slotu → yeni gün)
- MQTT mesajı timestamp'siz gelirse → datetime.now() kullan
- Sensör payload formatı tanınmazsa → log yaz, event'i atla
```

---

### SPRINT 2: Öğrenme Motoru (Learner)
**Hedef:** Per-sensor Beta-Binomial model, daily güncelleme, credible interval

**Claude Code Prompt:**
```
annem_guvende projesinin learner modülünü geliştir.

src/learner/
├── __init__.py
├── beta_model.py         # Beta-Binomial hesaplama çekirdeği
├── routine_learner.py    # Günlük model güncelleme
└── metrics.py            # Accuracy, balanced acc, CI hesaplama

Davranış:

1. beta_model.py — Matematiksel çekirdek:

   ```python
   from dataclasses import dataclass
   import math

   @dataclass
   class BetaPosterior:
       alpha: float       # prior + successes
       beta: float        # prior + failures
       
       @property
       def mean(self) -> float:
           return self.alpha / (self.alpha + self.beta)
       
       @property
       def variance(self) -> float:
           a, b = self.alpha, self.beta
           return (a * b) / ((a + b)**2 * (a + b + 1))
       
       @property
       def std(self) -> float:
           return math.sqrt(self.variance)
       
       def credible_interval(self, level: float = 0.90) -> tuple[float, float]:
           """Normal yaklaşım ile credible interval.
           SciPy doğrulaması: n>=7'de max %2 hata, n>=14'te ~%0.
           Uç değerlerde (p≈0 veya p≈1) hata artabilir."""
           z = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}[level]
           lo = max(0.0, self.mean - z * self.std)
           hi = min(1.0, self.mean + z * self.std)
           return (lo, hi)
       
       @property 
       def ci_width(self) -> float:
           lo, hi = self.credible_interval()
           return hi - lo
       
       def nll(self, observed: int) -> float:
           """Negative log-likelihood: observed=0 veya 1"""
           p = max(0.001, min(0.999, self.mean))
           if observed == 1:
               return -math.log(p)
           else:
               return -math.log(1 - p)
       
       def update(self, observed: int) -> 'BetaPosterior':
           """Yeni gözlemle posterior güncelle (immutable)"""
           if observed == 1:
               return BetaPosterior(self.alpha + 1, self.beta)
           else:
               return BetaPosterior(self.alpha, self.beta + 1)
   ```

2. routine_learner.py — Günlük güncelleme (her gece 00:15 çalışır):

   Akış:
   a) Dünün slot_summary verisini oku (96 slot × 4 kanal)
   b) model_state tablosundan mevcut Beta parametrelerini yükle
   c) Her (slot, channel) için:
      - Dünkü active değerine göre alpha veya beta'yı +1 artır
      - model_state tablosunu güncelle
   d) daily_scores tablosuna günün metriklerini yaz

   İlk gün: model_state tablosu boşsa, tüm slotlar için
   Beta(prior_alpha, prior_beta) ile başlat.

3. metrics.py — Per-sensor ve composite metrikler:

   ```python
   def calculate_daily_metrics(
       slot_data: dict[str, list[int]],      # channel → [96 active values]
       model: dict[str, list[BetaPosterior]], # channel → [96 posteriors]
       awake_start: int = 24,                 # slot 24 = 06:00
       awake_end: int = 92,                   # slot 92 = 23:00
   ) -> DailyMetrics:
   ```

   Hesaplanacak metrikler:

   a) PER-SENSOR NLL (KRİTİK — v3'teki en büyük düzeltme):
      Her kanal için ayrı NLL hesapla, sonra topla.
      Bu sayede "buzdolabı hiç açılmadı" gibi durumlar
      composite NLL'de görünür olur.

      ```python
      nll_per_channel = {}
      for channel in ['presence', 'fridge', 'bathroom', 'door']:
          nll = sum(model[channel][s].nll(slot_data[channel][s]) 
                    for s in range(96))
          nll_per_channel[channel] = nll
      nll_total = sum(nll_per_channel.values())
      ```

   b) EVENT COUNT DEVIATION (v3'te eksik — ChatGPT Pro önerisi):
      Günlük toplam event sayısının beklentiden sapması.
      "Bugün çok az olay oldu" durumunu DOĞRUDAN yakalar.

      ```python
      # Beklenen günlük toplam event sayısı
      expected = sum(model[ch][s].mean 
                     for ch in channels for s in range(96))
      # Gözlenen
      observed = sum(slot_data[ch][s] 
                     for ch in channels for s in range(96))
      # Varyans
      var_count = sum(model[ch][s].mean * (1 - model[ch][s].mean)
                      for ch in channels for s in range(96))
      # Z-skoru
      count_z = (observed - expected) / math.sqrt(var_count) if var_count > 0 else 0
      ```

   c) İKİ TARAFLI ANOMALİ SKORU (v3'te NLL ters çalışıyordu):
      ```python
      # NLL z-skoru (tarihsel ortalamaya göre)
      nll_z = (nll_total - historical_mean_nll) / historical_std_nll
      
      # Composite: her iki skor da kullanılır
      # |nll_z| → hem "fazla sessiz" hem "fazla aktif" yakalar
      # count_z → negatif = az olay = risk
      composite_z = max(abs(nll_z), abs(count_z))
      ```

   d) AWAKE WINDOW ACCURACY (dürüst metrik):
      Sadece slot 24-91 (06:00-23:00) üzerinde:
      - Accuracy, balanced accuracy, active recall
      - Awake baseline-0 (karşılaştırma için)

   e) CI DARALMASI:
      Tüm slotların ortalama CI genişliği.
      Öğrenmenin "gerçekten olduğunun" matematiksel kanıtı.

Test:
- test_beta_model.py: BetaPosterior hesaplamaları, NLL doğruluğu
- test_metrics.py: Bilinen veriyle metric hesaplama
- test_nll_direction.py: KRİTİK — "az aktivite" anomalisinin
  composite skorda YÜKSEK çıktığını doğrula
  (v3'teki ters çalışma bugı tekrarlanmamalı)
```

---

### SPRINT 3: Anomali Tespit (Detector)
**Hedef:** Günlük skorlama, alarm seviyesi belirleme, tarihsel karşılaştırma

**Claude Code Prompt:**
```
annem_guvende projesinin detector modülünü geliştir.

src/detector/
├── __init__.py
├── anomaly_scorer.py     # Günlük anomali skoru hesaplama
├── threshold_engine.py   # Z-skoru → alarm seviyesi
└── history_manager.py    # Tarihsel NLL istatistikleri

Davranış:

1. anomaly_scorer.py — Her gün 00:20'de çalışır (learner'dan sonra):

   a) Dünün daily_scores'dan nll_total ve count_z'yi oku
   b) history_manager'dan tarihsel normal günlerin 
      mean/std istatistiklerini al
   c) İki taraflı anomali skoru hesapla:

      ```python
      def score_day(self, date: str) -> AnomalyResult:
          scores = self.db.get_daily_scores(date)
          history = self.history.get_normal_stats()
          
          # NLL z-skoru (iki taraflı)
          nll_z = abs(scores.nll_total - history.mean_nll) / history.std_nll
          
          # Count z-skoru (tek taraflı: düşük = risk)
          # Negatif count_z → beklenenden az event → risk
          count_risk = max(0, -scores.count_z)  # sadece "az" yönü
          
          # Composite: en yüksek risk sinyali
          composite = max(nll_z, count_risk)
          
          return AnomalyResult(
              date=date,
              nll_z=nll_z,
              count_z=scores.count_z,
              count_risk=count_risk,
              composite_z=composite,
              alert_level=self.threshold.get_level(composite)
          )
      ```

2. threshold_engine.py — Kademeli alarm:

   ```python
   def get_level(self, composite_z: float) -> int:
       """
       0 = Normal
       1 = Nazik kontrol ("Bugün biraz farklı")
       2 = Ciddi ("Anne ile iletişim kur")
       3 = Acil ("Acil kontrol gerekli")
       """
       if composite_z >= config.z_threshold_emergency:  # default 4.0
           return 3
       elif composite_z >= config.z_threshold_serious:  # default 3.0
           return 2
       elif composite_z >= config.z_threshold_gentle:   # default 2.0
           return 1
       return 0
   ```

3. history_manager.py — Rolling istatistikler:

   - Son N normal günün (alert_level=0) NLL mean/std'ini hesapla
   - Minimum 7 gün veri gerekli (yoksa alarm üretme)
   - Öğrenme döneminde (ilk 14 gün) alarm seviyesi max 1 
     (ciddi/acil alarm üretme)
   - Outlier'ları (önceki anomali günleri) istatistikten çıkar

   ```python
   def get_normal_stats(self) -> HistoryStats:
       """Son 30 normal günün NLL istatistikleri"""
       rows = self.db.query(
           "SELECT nll_total FROM daily_scores "
           "WHERE alert_level = 0 AND is_learning = 0 "
           "ORDER BY date DESC LIMIT 30"
       )
       if len(rows) < 7:
           return HistoryStats(ready=False)
       nlls = [r['nll_total'] for r in rows]
       return HistoryStats(
           ready=True,
           mean_nll=statistics.mean(nlls),
           std_nll=statistics.stdev(nlls),
           n_days=len(nlls)
       )
   ```

4. GERÇEK ZAMANLI KONTROLLER (slot bazlı, gün sonu beklenmeden):

   Bazı durumlar gün sonunu bekleyemez:
   
   a) Sabah vital sign: 11:00'a kadar HİÇBİR sensörden event yok
      → Hemen alert_level=2 bildirim
   
   b) Uzun sessizlik: Son 3+ saattir (awake window içinde)
      hiçbir sensörden event yok
      → alert_level=1 bildirim
   
   Bu kontroller APScheduler ile her 30dk çalışır.
   Blueprint'lerdeki "sabah kontrolü" ile çakışmaması için:
   - HA Blueprint → TTS ile yaşlıya sesli uyarı
   - Detector → Telegram ile aileye bildirim
   İkisi birbirini tamamlar, çelişmez.

Test:
- test_anomaly_scorer.py: Bilinen verilerle z-skoru hesaplama
- test_threshold.py: Eşik değerleri doğrulama
- test_realtime.py: Sabah sessizlik senaryosu
- test_low_activity.py: KRİTİK — "çok az aktivite" günü 
  composite_z > 2.0 üretmeli (v3 bugı kontrolü)
```

---

### SPRINT 4: Bildirim Motoru (Alerter)
**Hedef:** Telegram bildirimleri, günlük özet, kademeli mesajlar

**Claude Code Prompt:**
```
annem_guvende projesinin alerter modülünü geliştir.

src/alerter/
├── __init__.py
├── telegram_bot.py       # Telegram Bot API entegrasyonu
├── message_templates.py  # Mesaj şablonları (Türkçe)
└── alert_manager.py      # Bildirim kararı ve rate limiting

Davranış:

1. telegram_bot.py — Telegram Bot API (httpx ile):

   ```python
   class TelegramNotifier:
       async def send_message(self, chat_id: str, text: str, 
                               parse_mode: str = "HTML"):
           """Telegram mesajı gönder"""
       
       async def send_to_all(self, text: str):
           """Tüm kayıtlı aile üyelerine gönder"""
       
       async def send_photo(self, chat_id: str, photo_bytes: bytes,
                            caption: str):
           """Günlük grafik/özet görseli"""
   ```

2. message_templates.py — Türkçe mesaj şablonları:

   ```python
   TEMPLATES = {
       # Günlük özet (her akşam 22:00)
       "daily_summary": """
   🏠 <b>Annem Güvende — Günlük Özet</b>
   📅 {date}
   
   ✅ Durum: {status}
   📊 Günlük Skor: {composite_z:.1f}σ (normal: <2.0)
   
   📋 Aktivite Özeti:
   • Mutfak: {kitchen_events} hareket
   • Buzdolabı: {fridge_events} açılma  
   • Banyo: {bathroom_events} kullanım
   • Dış kapı: {door_events} giriş/çıkış
   
   🧠 Öğrenme: Gün {train_days}/14 | Belirsizlik: %{ci_width:.0f}
   """,
       
       # Seviye 1: Nazik kontrol
       "alert_gentle": """
   💛 <b>Annem Güvende — Dikkat</b>
   📅 {date}
   
   Bugün annenin rutini normalden biraz farklı görünüyor.
   Skor: {composite_z:.1f}σ
   
   Detay: {explanation}
   
   ℹ️ Bu bilgilendirme amaçlıdır. Endişelenecek bir durum 
   olmayabilir, ama kontrol etmek isteyebilirsiniz.
   """,
       
       # Seviye 2: Ciddi
       "alert_serious": """
   🟠 <b>Annem Güvende — Önemli Uyarı</b>
   📅 {date}
   
   Annenin bugünkü aktivitesi belirgin şekilde normalden farklı.
   Skor: {composite_z:.1f}σ
   
   {explanation}
   
   📞 Lütfen annenizi arayın veya ziyaret edin.
   """,
       
       # Seviye 3: Acil
       "alert_emergency": """
   🔴 <b>Annem Güvende — ACİL UYARI</b>
   📅 {date} ⏰ {time}
   
   ⚠️ Annenizden beklenen aktivite sinyalleri çok düşük.
   Skor: {composite_z:.1f}σ
   
   {explanation}
   
   🚨 Lütfen HEMEN iletişime geçin.
   """,
       
       # Sabah sessizlik (gerçek zamanlı)
       "morning_silence": """
   ☀️ <b>Annem Güvende — Sabah Kontrolü</b>
   ⏰ {time}
   
   Saat {check_time}'a kadar hiçbir sensörden hareket algılanmadı.
   
   Bu, annenizin henüz uyanmadığı veya bir sorun yaşadığı 
   anlamına gelebilir.
   
   📞 Kontrol etmenizi öneriyoruz.
   """,

       # Öğrenme süreci bildirimi
       "learning_progress": """
   🧠 <b>Annem Güvende — Öğrenme Güncellemesi</b>
   📅 {date}
   
   Sistem {train_days}. gününde. Annenin rutinini öğrenmeye devam ediyor.
   Belirsizlik bandı: %{ci_width:.0f} (hedef: <%20)
   
   {extra_message}
   """,

       # 14. gün: Öğrenme tamamlandı
       "learning_complete": """
   🎉 <b>Annem Güvende — Sistem Hazır!</b>
   
   14 günlük öğrenme süreci tamamlandı.
   Annenin rutin deseni başarıyla oluşturuldu.
   
   Bundan sonra anormal günler otomatik tespit edilecek
   ve size bildirilecektir.
   
   📊 Sistem güveni: %{confidence:.0f}
   🛡️ Aktif koruma başladı.
   """
   }
   ```

3. alert_manager.py — Rate limiting ve karar:

   - Aynı seviye alarm 6 saat içinde tekrar gönderilmez
   - Seviye yükseldiyse (1→2, 2→3) her zaman gönder
   - Sabah sessizlik alarmı günde max 2 kez
   - Öğrenme döneminde (gün 1-7): sadece günlük özet
   - Öğrenme döneminde (gün 8-14): özet + max seviye 1 alarm
   - Aktif korumada (gün 15+): tüm seviyeler aktif

   ```python
   def should_send(self, alert_level: int) -> bool:
       """Rate limiting kontrolü"""
   
   def generate_explanation(self, scores: DailyMetrics) -> str:
       """Anomali nedenini açıklayan Türkçe metin üret.
       Örnek: 'Buzdolabı bugün hiç açılmadı (normalde 3-4 kez).
       Banyo kullanımı da beklenenden düşük.'"""
   ```

4. main.py entegrasyonu:
   - APScheduler: her akşam 22:00 → günlük özet
   - Anomaly detector callback → anlık alarm
   - Öğrenme milestone'ları (gün 7, 14) → bilgilendirme

Test:
- test_templates.py: Şablon rendering
- test_rate_limiting.py: 6 saat kuralı
- test_explanation.py: Anomali açıklama üretimi
```

---

### SPRINT 5: Heartbeat + Sistem Sağlığı
**Hedef:** Pi offline tespiti, watchdog, sistem metrikleri

**Claude Code Prompt:**
```
annem_guvende projesinin heartbeat modülünü geliştir.

src/heartbeat/
├── __init__.py
├── heartbeat_client.py   # Dış VPS'e ping gönderme
├── system_monitor.py     # CPU, RAM, disk, sıcaklık izleme
└── watchdog.py           # Servis sağlık kontrolü

Davranış:

1. heartbeat_client.py — Dış VPS'e periyodik ping:

   Her 5 dakikada bir HTTP POST:
   ```python
   payload = {
       "device_id": config.device_id,
       "timestamp": datetime.utcnow().isoformat(),
       "uptime_seconds": get_uptime(),
       "system": {
           "cpu_percent": psutil.cpu_percent(),
           "memory_percent": psutil.virtual_memory().percent,
           "disk_percent": psutil.disk_usage('/').percent,
           "cpu_temp": get_cpu_temp(),  # Pi özel
       },
       "services": {
           "mqtt_connected": collector.is_connected(),
           "db_size_mb": get_db_size(),
           "last_event_minutes_ago": get_last_event_age(),
           "today_event_count": get_today_events(),
       }
   }
   ```
   
   VPS tarafı (ayrı küçük servis — bu sprint'te sadece client):
   - 15 dakika ping yoksa → Telegram'a "Cihaz offline" bildirimi
   - Bu, Pi çökse bile ailenin haberdar olmasını sağlar

2. system_monitor.py — Lokal sağlık metrikleri:

   Her 15 dakikada kontrol:
   - CPU sıcaklığı > 80°C → uyarı log
   - Disk > %90 → eski event_log temizliği teklif et
   - RAM > %85 → uyarı log
   - MQTT son bağlantı > 10dk → reconnect tetikle
   - Son sensör event > 3 saat (awake window) → "sensör sessiz" uyarı

3. watchdog.py — Servis sağlık kontrolü:

   ```python
   class ServiceWatchdog:
       """Her bileşenin sağlığını kontrol et"""
       
       def check_mqtt(self) -> HealthStatus:
           """MQTT bağlantısı aktif mi?"""
       
       def check_db(self) -> HealthStatus:
           """DB yazılabilir mi? Son kayıt ne zaman?"""
       
       def check_scheduler(self) -> HealthStatus:
           """APScheduler job'ları çalışıyor mu?"""
       
       def check_all(self) -> SystemHealth:
           """Tüm bileşenleri kontrol et, özet döndür"""
   ```

4. VPS Heartbeat Receiver (minimal — opsiyonel ama önemli):

   Ayrı bir FastAPI micro-service (VPS'te çalışır):
   ```python
   # heartbeat_server.py — DigitalOcean/Hetzner'da $4/ay
   
   @app.post("/heartbeat")
   async def receive_heartbeat(payload: HeartbeatPayload):
       store_heartbeat(payload)
   
   # Cron job: her 5dk kontrol
   async def check_heartbeats():
       for device in get_devices():
           if minutes_since_last_ping(device) > 15:
               await send_telegram_alert(
                   f"🔴 {device.name} cihazı {mins}dk'dır yanıt vermiyor!"
               )
   ```

Test:
- test_heartbeat.py: Payload oluşturma, HTTP mock
- test_system_monitor.py: Eşik kontrolü
```

---

### SPRINT 6: Lokal Dashboard (Web UI)
**Hedef:** FastAPI + statik HTML dashboard, aile için basit web arayüz

**Claude Code Prompt:**
```
annem_guvende projesinin dashboard modülünü geliştir.

src/dashboard/
├── __init__.py
├── api.py                # FastAPI endpoint'leri
├── charts.py             # Grafik veri hazırlama
└── static/
    └── index.html        # Tek sayfa dashboard (vanilla JS + Chart.js CDN)

Davranış:

1. api.py — REST endpoint'leri:

   GET /api/status
   → Anlık sistem durumu: son event, bugünkü event sayısı,
     öğrenme durumu, alarm seviyesi

   GET /api/daily/{date}
   → Belirli günün detaylı metrikleri + slot verileri

   GET /api/history?days=30
   → Son N günün daily_scores listesi (grafik için)

   GET /api/heatmap?days=14
   → Model olasılık haritası (96 slot × 4 kanal)

   GET /api/learning-curve
   → Öğrenme eğrisi: CI daralması, accuracy trend

   GET /api/health
   → Sistem sağlık durumu (watchdog sonuçları)

2. static/index.html — Tek sayfa, minimal, Pi'de hızlı:

   Tasarım ilkeleri:
   - Chart.js CDN (ek paket yok)
   - Vanilla JavaScript (React/Vue gereksiz)
   - Koyu tema (v3 dashboard estetiği)
   - Responsive (telefonda da bakılabilir)
   - Auto-refresh: 5 dakikada bir API'dan çek
   - Türkçe arayüz

   Bölümler:
   a) Üst bant: Durum kartları (alarm seviyesi, gün sayısı, 
      CI genişliği, son event zamanı)
   b) Bugünün slot haritası (aktif/pasif, sensör bazlı renkli)
   c) Son 14 günün NLL trend çizgisi + alarm eşikleri
   d) Öğrenme eğrisi (CI daralması)
   e) Sensör bazlı günlük event sayıları (bar chart)

3. FastAPI mount:
   - Statik dosyaları serve et
   - CORS: sadece lokal ağ
   - Port: 8099 (HA ile çakışmasın — HA: 8123)

Test:
- test_api.py: Her endpoint'in doğru JSON döndürmesi
- Manuel test: Tarayıcıda http://pi-ip:8099 açıp kontrol
```

---

### SPRINT 7: Entegrasyon Testi + Pilot Hazırlık
**Hedef:** Uçtan uca test, simülasyon modu, dokümantasyon

**Claude Code Prompt:**
```
annem_guvende projesinin entegrasyon testini ve pilot hazırlığını yap.

Görevler:

1. SİMÜLASYON MODU (gerçek sensör olmadan test):

   src/simulator/
   ├── __init__.py
   └── fake_mqtt.py      # Sahte sensör event'leri üret

   ```python
   class SensorSimulator:
       """v3 dashboard'daki elderly day generator'ın 
       Python versiyonu. MQTT mesajı olarak publish eder."""
       
       def generate_normal_day(self, speed: float = 60.0):
           """1 günü speed kat hızlı simüle et.
           speed=60 → 1 gün = 24 dakika
           speed=1440 → 1 gün = 1 dakika"""
       
       def generate_anomaly_day(self, anomaly_type: str):
           """Anomali türleri:
           - 'low_activity': çok az hareket
           - 'no_fridge': buzdolabı hiç açılmadı  
           - 'late_wake': geç uyanma
           - 'no_bathroom': banyo kullanımı yok
           """
       
       def run_pilot_simulation(self, days: int = 21):
           """14 normal gün + 7 gün (6 normal + 1 anomali)
           Tam pilot senaryosunu simüle et."""
   ```

2. UÇTAN UCA TEST:

   tests/test_integration.py:
   
   a) Simülatör 21 gün verisini üretir
   b) Collector event'leri alır, slot_summary oluşturur
   c) Learner her "gün sonunda" modeli günceller
   d) Detector 18. günde anomali tespit eder
   e) Alerter doğru seviyede bildirim üretir
   
   Assertion'lar:
   - 14. günde CI genişliği < başlangıcın %50'si
   - Anomali gününde composite_z > 2.0
   - Normal günlerde composite_z < 2.0 (max 1 false alarm kabul)
   - Tüm Telegram mesajları doğru template'le üretildi

3. KURULUM DOKÜMANTASYONU:

   docs/
   ├── INSTALL.md          # Pi'ye kurulum adımları
   ├── CONFIG.md           # config.yml açıklaması  
   ├── SENSORS.md          # Sensör eşleştirme rehberi
   └── TROUBLESHOOTING.md  # Sık sorunlar

   INSTALL.md içeriği:
   ```
   ## Ön Koşullar
   - Raspberry Pi 4 (2GB+ RAM)
   - Home Assistant çalışıyor
   - Zigbee2MQTT çalışıyor
   - Sensörler eşleştirilmiş

   ## Kurulum
   1. git clone ...
   2. cp config.yml.example config.yml
   3. config.yml'i düzenle (sensör ID'leri, Telegram token)
   4. docker compose up -d
   5. http://pi-ip:8099 adresinden dashboard'u kontrol et

   ## İlk 14 Gün
   - Sistem otomatik öğrenme modunda başlar
   - Gün 7: İlk öğrenme raporu gelir
   - Gün 14: "Sistem hazır" bildirimi
   - Gün 15+: Aktif anomali tespiti başlar
   ```

4. PILOT CHECKLIST:

   scripts/pilot_checklist.py:
   - [ ] config.yml sensör ID'leri doğru mu?
   - [ ] MQTT bağlantısı çalışıyor mu?
   - [ ] Her sensörden en az 1 event geldi mi?
   - [ ] Telegram bot mesaj atabiliyor mu?
   - [ ] Heartbeat VPS'e ulaşabiliyor mu?
   - [ ] DB yazılabilir mi?
   - [ ] Dashboard erişilebilir mi?

Test:
- test_integration.py: Uçtan uca 21 gün simülasyonu
- test_pilot_checklist.py: Checklist kontrolleri
```

---

## Sprint Sıralaması ve Bağımlılıklar

```
Sprint 0 ──► Sprint 1 ──► Sprint 2 ──► Sprint 3 ──► Sprint 4
(iskelet)    (veri)       (öğrenme)    (anomali)    (bildirim)
                                                        │
                                           Sprint 5 ◄───┘
                                           (heartbeat)
                                               │
                                           Sprint 6
                                           (dashboard)
                                               │
                                           Sprint 7
                                           (entegrasyon)
```

## Claude Code Kullanım Stratejisi

1. **Her sprint = ayrı Claude Code session.** Sprint prompt'unu kopyala, önceki sprint'in kodunu context olarak ver.

2. **"Devam et" değil, "doğrula ve devam et":** Her sprint sonunda `pytest` çalıştır, yeşil görene kadar Claude Code'a düzelttir.

3. **Config-first test:** Her sprint'i önce config.yml'deki ayarlarla test et. Sensör olmadan bile simülatör ile çalışabilmeli.

4. **Git commit per sprint:** Her sprint sonunda `git add . && git commit -m "Sprint N: ..."` yaptır.

---

## Risk Tablosu

| Risk | Olasılık | Etki | Azaltma |
|------|----------|------|---------|
| MQTT mesaj formatı beklenenden farklı | Yüksek | Sprint 1 takılır | config.yml'de esnek trigger_value tanımı |
| Pi'de disk dolması | Orta | Sistem durur | 90 gün üzeri event otomatik temizleme |
| Telegram API rate limit | Düşük | Bildirim gecikmesi | Rate limiting + queue |
| NLL hâlâ ters çalışır | Düşük | Yanlış alarm | Sprint 2'de zorunlu yön testi |
| Zigbee ağ kararsızlığı | Orta | Veri kaybı | Reconnect + "sensör sessiz" uyarısı |

---

## Başarı Kriterleri (Pilot Sonunda)

- [ ] 14 gün sonunda CI genişliği başlangıcın %50'sinden az
- [ ] Simüle anomali gününde alarm seviyesi ≥ 1
- [ ] Normal günlerde false alarm oranı < %5 (30 günde max 1-2)
- [ ] Sabah sessizlik tespiti 30dk içinde bildirim
- [ ] Heartbeat: Pi kapatılınca 15dk içinde aile bildirimi
- [ ] Günlük özet her akşam 22:00'da geliyor
- [ ] Dashboard telefonda okunabilir

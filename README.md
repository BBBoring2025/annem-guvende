# Annem Guvende

> Yasli bireyler icin sensor tabanli rutin ogrenme ve anomali tespit sistemi

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite&logoColor=white)
![MQTT](https://img.shields.io/badge/MQTT-Zigbee2MQTT-660066)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-288%20passing-brightgreen)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Nedir?

**Annem Guvende**, yalniz yasayan yasli bireylerin gunluk rutinlerini otonom olarak ogrenen ve sapma durumunda aile yakinlarini kademeli olarak uyaran bir IoT sistemdir. Raspberry Pi uzerinde calisan sistem, Zigbee hareket ve kapi sensorlerinden gelen verileri **Bayesian ogrenme** (Beta-Binomial model) ile isler. **Kamera veya mikrofon kullanmaz** — mahremiyeti oncelikli, tamamen yerel veri isleme prensibiyle calisir. Anomali tespit edildiginde Telegram uzerinden 3 kademeli bildirim gonderir.

---

## Mimari

```
Zigbee Sensorler ──> Zigbee2MQTT ──> MQTT Broker (:1883)
                                          │
                                ┌─────────┴─────────┐
                                │   Annem Guvende    │
                                │   Engine (:8099)   │
                                ├────────────────────┤
                                │ Collector          │  EventProcessor + SlotAggregator
                                │ Learner            │  Beta-Binomial (96 slot x 4 kanal)
                                │ Detector           │  NLL + Z-score ──> 3 alarm seviyesi
                                │ Alerter            │  Telegram iki yonlu
                                │ Dashboard          │  FastAPI + Chart.js
                                │ Heartbeat          │  Watchdog + VPS ping
                                └────────────────────┘
```

---

## Ozellikler

| | Ozellik | Aciklama |
|---|---------|----------|
| :brain: | **Rutin Ogrenme** | Beta-Binomial model, 96 zaman dilimi x 4 kanal, 14 gun ogrenme donemi |
| :mag: | **Anomali Tespiti** | NLL + composite Z-score, 3 kademeli alarm (nazik / ciddi / acil) |
| :iphone: | **Telegram Iki Yonlu** | Bildirimler + komutlar: `/durum`, `/bugun`, `/tatil`, `/evdeyim`, `/yardim` |
| :bar_chart: | **Web Dashboard** | Gercek zamanli durum, heatmap, ogrenme egrisi, tarihsel grafikler |
| :desert_island: | **Tatil Modu** | Telegram veya dashboard uzerinden alarmlar duraklatilabilir |
| :battery: | **Pil Takibi** | Sensor pili %10'un altina dustugunde Telegram uyarisi |
| :clapper: | **Demo Modu** | 21 gunluk hizlandirilmis simulasyon (juri demo icin) |
| :lock: | **Mahremiyet** | Kamera yok, mikrofon yok, tamamen lokal veri, Zigbee sensorler |

---

## Hizli Baslangic

### Gereksinimler

- Python 3.11+
- Raspberry Pi 4 (veya herhangi bir Linux/macOS)
- Zigbee2MQTT + uyumlu sensorler (pilot icin)

### Kurulum

```bash
git clone https://github.com/BBBoring2025/annem-guvende.git
cd annem-guvende

# Config dosyasini hazirlayin
cp config.yml.example config.yml
# config.yml icerisindeki sensor, Telegram ve diger ayarlari duzenleyin

# Bagimliliklari yukleyin
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Demo modu ile hemen deneyin (sensor gerekmez)
python -m src.simulator --demo --speed 0
```

Demo modu 21 gunluk simulasyon calistirir: 14 gun ogrenme + 7 gun test. Gun 18'de anomali (dusuk aktivite) tespit edilir.

---

## Docker Kurulum

```bash
# Config dosyasini hazirlayin
mkdir -p config
cp config.yml.example config/config.yml

# Sistemi baslatin
docker compose up -d

# (Opsiyonel) Dahili MQTT broker ile:
docker compose --profile mqtt-broker up -d
```

Dashboard: `http://RASPBERRY_PI_IP:8099`

---

## Proje Yapisi

```
annem-guvende/
├── src/
│   ├── main.py                # FastAPI uygulama + zamanlayici + lifespan
│   ├── config.py              # Pydantic typed config (9 bolum)
│   ├── database.py            # SQLite + migrasyon
│   ├── jobs.py                # 11 zamanlayici gorevi
│   ├── collector/             # MQTT + EventProcessor + SlotAggregator
│   ├── learner/               # BetaPosterior + RoutineLearner + Metrics
│   ├── detector/              # AnomalyScorer + ThresholdEngine + Realtime
│   ├── alerter/               # AlertManager + TelegramBot + Templates
│   ├── heartbeat/             # HeartbeatClient + Watchdog + SystemMonitor
│   ├── dashboard/             # REST API + Charts + static/
│   └── simulator/             # Demo modu (21 gun simulasyon)
├── tests/                     # 288 test
├── docs/                      # ARCHITECTURE, API, CONFIG, INSTALL, vb.
├── scripts/                   # init_db.py, pilot_checklist.py
├── .github/workflows/         # CI (ruff + pytest)
├── docker-compose.yml
├── Dockerfile
├── config.yml.example
└── requirements.txt
```

---

## Telegram Komutlari

Bot'a asagidaki komutlari gonderebilirsiniz:

| Komut | Aciklama |
|-------|----------|
| `/durum` | Sistem durumu (tatil modu, egitim gunu, faz, son olay) |
| `/bugun` | Bugunun kanal bazli olay sayilari |
| `/tatil` | Tatil modunu ac (alarmlar duraklatilir) |
| `/evdeyim` | Tatil modunu kapat (normal izlemeye don) |
| `/yardim` | Komut listesi |

> **Not:** Sadece `config.yml`'de kayitli `chat_id`'ler komut gonderebilir.

---

## Gelistirme

```bash
# Testleri calistir
pytest -v --tb=short              # 288 test

# Lint kontrolu
ruff check src/ tests/ scripts/   # 0 hata

# Demo modu
python -m src.simulator --demo --speed 0

# Pilot kontrol listesi
python scripts/pilot_checklist.py
```

### CI/CD

Her push ve PR'da GitHub Actions otomatik calisir:
- **Lint:** `ruff check src/ tests/`
- **Test:** `pytest -v --tb=short`

---

## Dokumantasyon

| Dokuman | Aciklama |
|---------|----------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Teknik mimari, veri akisi, DB semasi, ML pipeline |
| [API.md](docs/API.md) | Dashboard REST API endpoint'leri |
| [CONFIG.md](docs/CONFIG.md) | Konfigurasyon referansi |
| [INSTALL.md](docs/INSTALL.md) | Kurulum rehberi |
| [SENSORS.md](docs/SENSORS.md) | Sensor eslestirme rehberi |
| [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Sorun giderme |
| [CHANGELOG.md](CHANGELOG.md) | Sprint bazli degisiklik kaydi |

---

## Lisans

Bu proje [MIT Lisansi](LICENSE) altinda lisanslanmistir.

---

<p align="center">
  <b>ITU Cekirdek 2025</b><br>
  Bu proje ITU Cekirdek On Kulucelik Programi kapsaminda gelistirilmistir.
</p>

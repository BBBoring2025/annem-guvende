# Dashboard API Referansi

## Genel Bilgiler

| Ozellik | Deger |
|---------|-------|
| Base URL | `http://RASPBERRY_PI_IP:8099` |
| Kimlik Dogrulama | HTTP Basic Auth |
| Yanit Formati | JSON |
| Karakter Seti | UTF-8 |

> Aynı cihazdan test ediyorsanız: `http://localhost:8099`

### Kimlik Dogrulama

Dashboard API, HTTP Basic Authentication kullanir. Kullanici adi ve sifre `config.yml`'den alinir:

```yaml
dashboard:
  username: "admin"
  password: "guclu_sifre"
```

Eger `username` veya `password` bos birakilirsa kimlik dogrulama devre disi kalir (uyari loglanir).

**Muaf endpoint:** `GET /health` — kimlik dogrulama gerektirmez.

> **Production Notu:** `ANNEM_ENV=production` ortaminda `dashboard.username` ve
> `dashboard.password` **zorunludur**. Bos veya varsayilan sifre ile uygulama baslamaz.

---

## Endpoint'ler

### GET /health

Temel sistem sagligi. Kimlik dogrulama gerektirmez.

**Yanit (200 OK):**

```json
{
  "status": "ok",
  "version": "0.1.0",
  "checks": {
    "database": true,
    "mqtt_connected": true
  },
  "metrics": {
    "cpu_percent": 12.5,
    "memory_percent": 45.2,
    "disk_percent": 62.1,
    "cpu_temp": 48.0,
    "db_size_mb": 0.7,
    "today_event_count": 42
  }
}
```

| Alan | Tip | Aciklama |
|------|-----|----------|
| status | string | `"ok"` veya `"degraded"` |
| version | string | Uygulama versiyonu |
| checks | object | Alt sistem kontrolleri |
| metrics | object | Sistem metrikleri |

---

### GET /api/status

Gercek zamanli sistem durumu.

**Yanit (200 OK):**

```json
{
  "last_event": {
    "timestamp": "2025-01-15 14:32:00",
    "sensor_id": "mutfak_motion",
    "channel": "presence"
  },
  "today_count": 38,
  "learning": {
    "is_learning": false,
    "train_days": 18,
    "ci_width": 0.12
  },
  "latest_score": {
    "date": "2025-01-14",
    "composite_z": 0.8,
    "alert_level": 0,
    "nll_total": 12.3
  },
  "vacation_mode": false,
  "mqtt_connected": true
}
```

---

### GET /api/daily/{date}

Belirli bir gunun detayli verileri.

**Parametre:**

| Ad | Tip | Zorunlu | Aciklama |
|----|-----|---------|----------|
| date | string (path) | Evet | `YYYY-MM-DD` formatinda tarih |

**Yanit (200 OK):**

```json
{
  "date": "2025-01-15",
  "scores": {
    "nll_total": 14.2,
    "nll_presence": 3.1,
    "nll_fridge": 4.5,
    "nll_bathroom": 3.8,
    "nll_door": 2.8,
    "composite_z": 1.2,
    "count_z": -0.5,
    "alert_level": 0,
    "observed_count": 42,
    "expected_count": 45.3,
    "train_days": 18,
    "is_learning": false,
    "aw_accuracy": 0.85,
    "aw_balanced_acc": 0.82
  },
  "slots": {
    "presence": [0, 0, 0, "...(96 eleman)"],
    "fridge": [0, 0, 0, "...(96 eleman)"],
    "bathroom": [0, 0, 0, "...(96 eleman)"],
    "door": [0, 0, 0, "...(96 eleman)"]
  },
  "event_counts": {
    "presence": 18,
    "fridge": 8,
    "bathroom": 12,
    "door": 4
  }
}
```

**Yanit (404 Not Found):** Tarih icin veri yoksa

```json
{
  "detail": "Veri bulunamadi"
}
```

---

### GET /api/history

Tarihsel gunluk skorlar.

**Parametre:**

| Ad | Tip | Zorunlu | Varsayilan | Aciklama |
|----|-----|---------|-----------|----------|
| days | integer (query) | Hayir | 30 | Kac gun geriye gidilecegi |

**Yanit (200 OK):**

```json
{
  "days": [
    {
      "date": "2025-01-15",
      "nll_total": 14.2,
      "composite_z": 1.2,
      "alert_level": 0,
      "observed_count": 42,
      "is_learning": false,
      "train_days": 18
    }
  ]
}
```

---

### GET /api/heatmap

Model olasilik haritasi ve son aktivite verisi.

**Yanit (200 OK):**

```json
{
  "model": {
    "presence": [
      {"slot": 0, "probability": 0.05, "ci_width": 0.08},
      {"slot": 1, "probability": 0.03, "ci_width": 0.06},
      "...(96 slot)"
    ],
    "fridge": ["...(96 slot)"],
    "bathroom": ["...(96 slot)"],
    "door": ["...(96 slot)"]
  },
  "recent_activity": {
    "presence": [0.0, 0.0, "...(96 deger)"],
    "fridge": [0.0, 0.0, "...(96 deger)"],
    "bathroom": [0.0, 0.0, "...(96 deger)"],
    "door": [0.0, 0.0, "...(96 deger)"]
  }
}
```

Her slot 15 dakikalik zaman dilimine karsilik gelir (slot 0 = 00:00-00:15, slot 95 = 23:45-24:00).

---

### GET /api/learning-curve

Ogrenme sureci metrikleri.

**Yanit (200 OK):**

```json
{
  "dates": ["2025-01-01", "2025-01-02", "..."],
  "train_days": [1, 2, 3, "..."],
  "nll_totals": [45.2, 38.1, 32.5, "..."],
  "accuracies": [0.65, 0.72, 0.78, "..."],
  "balanced_accuracies": [0.60, 0.68, 0.75, "..."],
  "ci_widths": [0.45, 0.38, 0.32, "..."]
}
```

---

### GET /api/trends

Kanal bazli uzun vadeli trend egimleri (kirilganlik endeksi).

**Yanit (200 OK):**

```json
{
  "trends": {
    "presence": -0.12,
    "fridge": 0.05,
    "bathroom": 0.35,
    "door": -0.02
  },
  "period_days": 30
}
```

| Alan | Tip | Aciklama |
|------|-----|----------|
| trends | object | Kanal bazli egim degerleri (pozitif = artis, negatif = azalis) |
| period_days | integer | Analiz periyodu (gun) |

**Not:** Yeterli veri yoksa (`trend_min_days`'den az) kanal degeri `null` doner.

---

### GET /api/health

Detayli sistem sagligi (kimlik dogrulama gerektirir).

**Yanit (200 OK):**

```json
{
  "status": "ok",
  "checks": {
    "database": true,
    "mqtt_connected": true,
    "disk_ok": true,
    "memory_ok": true,
    "cpu_temp_ok": true
  },
  "metrics": {
    "cpu_percent": 12.5,
    "memory_percent": 45.2,
    "disk_percent": 62.1,
    "cpu_temp": 48.0,
    "db_size_mb": 0.7,
    "today_event_count": 42
  }
}
```

| status | Kosul |
|--------|-------|
| `"ok"` | Tum kontroller basarili |
| `"degraded"` | En az bir kontrol basarisiz |

---

## HTTP Durum Kodlari

| Kod | Aciklama |
|-----|----------|
| 200 | Basarili |
| 401 | Kimlik dogrulama gerekli / basarisiz |
| 404 | Kaynak bulunamadi (ornegin belirli tarih) |
| 500 | Sunucu hatasi |

---

## Ornek Kullanim

```bash
# Sagligi kontrol et (auth gerekmez)
curl http://localhost:8099/health

# Sistem durumu (auth gerekli)
curl -u admin:sifre http://localhost:8099/api/status

# Belirli gun verisi
curl -u admin:sifre http://localhost:8099/api/daily/2025-01-15

# Son 7 gunluk tarihce
curl -u admin:sifre "http://localhost:8099/api/history?days=7"
```

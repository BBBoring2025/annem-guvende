# Sorun Giderme Rehberi

## MQTT Baglanti Sorunlari

### "MQTT baglantisi kurulamadi"

1. Mosquitto servisini kontrol edin:
   ```bash
   docker compose ps mosquitto
   ```

2. Port 1883 dinleniyor mu:
   ```bash
   # macOS / Linux
   lsof -i :1883
   ```

3. Mosquitto loglarini inceleyin:
   ```bash
   docker compose logs mosquitto --tail 50
   ```

4. MQTT broker'a manuel baglanmayi deneyin:
   ```bash
   mosquitto_sub -h localhost -p 1883 -t "zigbee2mqtt/#" -v
   ```

### "Sensor eventleri gelmiyor"

1. Zigbee2MQTT'nin calistigini dogrulayin:
   ```bash
   docker compose ps zigbee2mqtt
   ```

2. MQTT topic'lerini dinleyin:
   ```bash
   mosquitto_sub -h localhost -p 1883 -t "zigbee2mqtt/#" -v
   ```

3. Sensoru tetikleyin (hareket yapin veya kapi acin) ve mesaj gelip gelmedigini izleyin.

4. `config.yml`'deki sensor `id` degerlerinin Zigbee2MQTT friendly name ile eslestiginden emin olun.

---

## Sensor Sorunlari

### "Sensor eslesmedi"

1. Zigbee2MQTT arayuzune gidin (`http://localhost:8080`)
2. "Permit join (All)" butonuna tiklayin
3. Sensordeki eslestirme butonuna basin:
   - **Aqara Motion**: Alt taraftaki butona 5 sn basin
   - **Aqara Contact**: Igne ile reset deligine basin
4. LED yanip sonene kadar bekleyin (10-30 saniye)

### "Sensor bazen event gondermiyior"

- Pil seviyesini kontrol edin (Zigbee2MQTT arayuzunden)
- Sensor ile koordinator arasi mesafeyi kontrol edin (max ~10m ic mekan)
- Zigbee mesh aginda yeterli router cihaz var mi kontrol edin

### "Yanlis kanal eslesmesi"

`config.yml`'deki sensor tanimlarini kontrol edin:

```yaml
sensors:
  - id: "mutfak_motion"      # Zigbee2MQTT friendly name
    channel: "presence"       # Sistem kanali
    type: "motion"
    trigger_value: "on"
```

`id` alani Zigbee2MQTT'deki friendly name ile **birebir ayni** olmalidir.

---

## Veritabani Sorunlari

### "Database is locked"

SQLite WAL modunda bile yogun yazma islemlerinde kilitlenme olabilir:

1. Sistemi durdurun:
   ```bash
   docker compose down
   ```

2. WAL dosyalarini kontrol edin:
   ```bash
   ls -la data/annem_guvende.db*
   ```

3. WAL checkpoint yapin:
   ```bash
   sqlite3 data/annem_guvende.db "PRAGMA wal_checkpoint(TRUNCATE);"
   ```

4. Sistemi yeniden baslatin:
   ```bash
   docker compose up -d
   ```

### "Database dosyasi bulunamadi"

- `config.yml`'deki `database.path` degerini kontrol edin
- Dizinin var oldugundan emin olun:
  ```bash
  mkdir -p data
  ```
- Yetkileri kontrol edin:
  ```bash
  ls -la data/
  ```

### "Tablo bulunamadi (no such table)"

Veritabani sifindan olusturulmus olabilir. `init_db` otomatik calisir ama
sorun devam ederse:

```bash
# Mevcut DB'yi yedekleyin
cp data/annem_guvende.db data/annem_guvende.db.bak

# Sistemi yeniden baslatin (init_db otomatik calisir)
docker compose restart annem-guvende
```

---

## Dashboard Sorunlari

### "Dashboard acilmiyor (port 8099)"

1. Servisin calistigini kontrol edin:
   ```bash
   docker compose ps annem-guvende
   ```

2. Health endpoint'i kontrol edin:
   ```bash
   curl http://localhost:8099/health
   ```

3. Loglari inceleyin:
   ```bash
   docker compose logs annem-guvende --tail 50
   ```

4. Port cakismasi var mi kontrol edin:
   ```bash
   lsof -i :8099
   ```

### "Dashboard'da grafik gorunmuyor"

- En az 1 gunluk veri toplanmasi gerekir
- Tarayicida sayfayi yenileyin (Ctrl+F5)
- Farkli bir tarayici deneyin
- Tarayici konsolunda JavaScript hatalari kontrol edin (F12)

---

## Telegram Bildirim Sorunlari

### "Telegram bildirimi gelmiyor"

1. Bot token'i dogrulayin:
   ```bash
   curl https://api.telegram.org/bot<TOKEN>/getMe
   ```
   Basarili yanit JSON icinde bot bilgisi dondurmelidir.

2. Chat ID'yi dogrulayin:
   - Bot'a `/start` mesaji gonderin
   - `getUpdates` ile chat_id'yi alin:
     ```bash
     curl https://api.telegram.org/bot<TOKEN>/getUpdates
     ```

3. `config.yml`'deki ayarlari kontrol edin:
   ```yaml
   telegram:
     bot_token: "123456:ABC-DEF..."
     chat_ids:
       - 987654321
   ```

4. Loglarda Telegram hatasi arayin:
   ```bash
   docker compose logs annem-guvende | grep -i telegram
   ```

### "Bot token gecersiz (401 Unauthorized)"

- BotFather'dan token'i yeniden kopyalayin
- Token'da bosluk veya fazla karakter olmadigindan emin olun
- Gerekirse BotFather'dan `/revoke` ile yeni token alin

---

## Heartbeat Sorunlari

### "Heartbeat bildirimi gelmiyor"

1. `config.yml`'de heartbeat ayarlarini kontrol edin:
   ```yaml
   heartbeat:
     enabled: true
     cron_hour: 21
     cron_minute: 0
   ```

2. Sistem saatini kontrol edin:
   ```bash
   date
   ```

3. APScheduler loglarini inceleyin:
   ```bash
   docker compose logs annem-guvende | grep -i heartbeat
   ```

---

## Ogrenme Donemi Sorunlari

### "14 gun gecti ama hala ogrenme modunda"

- `daily_scores` tablosundaki `is_learning` degerini kontrol edin:
  ```bash
  sqlite3 data/annem_guvende.db \
    "SELECT date, is_learning, train_days FROM daily_scores ORDER BY date DESC LIMIT 20;"
  ```

- `train_days` degeri 14'e ulastiginda `is_learning=0` olur
- Eksik gunler varsa (sistem kapali kaldiysa), ogrenme uzar

### "False alarm cok fazla"

Ogrenme donemi bittiginde bile ilk birfkac gun `count_z` hassas olabilir:

1. `z_threshold_gentle` degerini artirin (ornegin 2.0 -> 2.5):
   ```yaml
   alerts:
     z_threshold_gentle: 2.5
   ```

2. `min_train_days` degerini artirin (ornegin 7 -> 10):
   ```yaml
   alerts:
     min_train_days: 10
   ```

3. Normal gunde yuksek skor goruyorsaniz, rutin degisikliginden kaynaklanabilir.
   Sistem birfkac gun icinde yeni rutine adapte olacaktir.

---

## Pilot Checklist Sorunlari

### "pilot_checklist.py FAIL donuyor"

Her kontrol icin ayri cozum:

| Kontrol | Olasi Sorun | Cozum |
|---------|-------------|-------|
| config_sensors | Eksik sensor tanimi | `config.yml`'e 4 kanal ekleyin |
| mqtt_connection | MQTT broker kapali | `docker compose up -d mosquitto` |
| sensor_events | Hic event yok | Sensoru tetikleyin, 5 dk bekleyin |
| telegram | Bot token hatali | BotFather'dan kontrol edin |
| heartbeat | Heartbeat kapalı | `config.yml`'de `enabled: true` |
| db_writable | Yetki sorunu | `chmod 755 data/` |
| dashboard | Servis kapali | `docker compose up -d` |

Checklist'i tekrar calistirin:
```bash
python scripts/pilot_checklist.py --config config.yml
```

---

## Genel Sorunlar

### "Docker container baslamiyor"

```bash
# Loglari inceleyin
docker compose logs --tail 100

# Container'lari yeniden olusturun
docker compose down
docker compose up -d --build
```

### "Python modulu bulunamiyor (ModuleNotFoundError)"

```bash
# Virtual environment aktif mi?
source .venv/bin/activate

# Bagimliliklari yeniden yukleyin
pip install -r requirements.txt
```

### "Config dosyasi bulunamiyor"

```bash
# Ornek config'den kopyalayin
cp config.yml.example config.yml

# Duzenleyin
nano config.yml
```

---

## Cihaz Offline / Internet Kesintisi

### "MQTT baglantisi kopuk" uyarisi aliyorum

Bu durum iki farkli sebepten kaynaklanabilir:

1. **Internet kesintisi**: Pi'nin interneti kesilmis olabilir.
   - Modem/router'i kontrol edin
   - Pi'ye SSH ile baglanmayi deneyin: `ssh pi@<IP>`
   - Pi'den ping atin: `ping 8.8.8.8`

2. **Pi'nin kendisi kapanmis**: Guc kaynagi sorunu olabilir.
   - Pi'nin LED'lerini kontrol edin (kirmizi=guc, yesil=disk aktivitesi)
   - Guc kablosunu kontrol edin
   - Pi'yi yeniden baslatin

3. **MQTT broker sorunu**: Mosquitto calismiyor olabilir.
   - `docker compose ps mosquitto` ile kontrol edin
   - `docker compose restart mosquitto` ile yeniden baslatin

> **Not**: Watchdog uyarisinda "internet kesintisi" notu gorurseniz, once internet baglantisinizi kontrol edin.

---

## Pil Uyarilari

### "Dusuk Pil Uyarisi" aldim

Sistem, sensor pil seviyesi **%10'un altina** dustugunde Telegram bildirimi gonderir.

1. Uyarida belirtilen sensoru bulun (ornegin `mutfak_motion`)
2. Zigbee2MQTT arayuzunden (`http://localhost:8080`) pil seviyesini dogrulayin
3. Sensordeki pili degistirin:
   - **Aqara Motion Sensor**: Alt kapagi cevirip cikartin, CR2450 pil
   - **Aqara Contact Sensor**: Ince bir cisimle yan kapagi acin, CR1632 pil

> **Onemli**: Pil degistirdikten sonra sistem otomatik olarak uyari bayrağını sıfırlar (pil > %20 oldugunda). Yeni bir islem yapmaniza gerek yoktur.

---

## Tatil Modu

### Tatil modunu nasil kullanirim?

Evden uzun sureli ayrildiginizda tatil modunu acin. Bu modda:
- Gunluk ogrenme duraklar (rutin degismez)
- Anomali skorlama atlanir
- Gereksiz alarm gelmez

**Telegram ile:**
- Tatil modunu acmak: `/tatil` yazin
- Eve donunce kapatmak: `/evdeyim` yazin

**Dashboard ile:**
- Dashboard'daki tatil modu toggle'ini kullanin

> **Not**: Tatil modunda bile sensörler veri toplamaya devam eder. Sistem watchdog ve heartbeat kontrolleri de devam eder.

---

## Destek

Sorun devam ederse:

1. `docker compose logs > logs.txt` ile tam loglari kaydedin
2. `python scripts/pilot_checklist.py --config config.yml` ciktisini alin
3. GitHub Issues'a raporlayin (hassas bilgileri cikararak)

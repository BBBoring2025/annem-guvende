# Kurulum Rehberi

## On Kosullar

- Raspberry Pi 4 (2GB+ RAM)
- Home Assistant kurulu ve calisiyor
- Zigbee2MQTT kurulu ve calisiyor
- Sensorler Zigbee2MQTT ile eslestirilmis (bkz. [SENSORS.md](SENSORS.md))
- Docker ve Docker Compose kurulu

## Kurulum Adimlari

### 1. Projeyi indir

```bash
cd /home/pi
git clone <repo-url> annem-guvende
cd annem-guvende
```

### 2. Konfigurasyonu hazirla

```bash
cp config.yml.example config.yml
nano config.yml
```

Duzenlenmesi gereken alanlar:
- `sensors`: Zigbee2MQTT'deki sensor ID'leri (bkz. [CONFIG.md](CONFIG.md))
- `telegram.bot_token`: BotFather'dan alinan token
- `telegram.chat_ids`: Bildirim alacak kullanicilarin chat ID'leri
- `heartbeat.url`: (opsiyonel) Dis VPS heartbeat endpoint'i

### 3. Baslat

```bash
mkdir -p config data
cp config.yml.example config/config.yml
# config/config.yml icindeki sensor, Telegram ve diger ayarlari duzenleyin

docker compose up -d
```

### 3b. Docker Volume Izinleri

Container `annem` kullanicisi UID `10001` ile calisir. Host dizinlerinin
bu kullaniciya ait olmasi gerekir:

```bash
sudo chown -R 10001:10001 ./data ./config
```

**Uretim ortami** icin guvenlik sertlestirmesi:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Bu ek dosya sunlari saglar:
- Salt-okunur kok dosya sistemi (`read_only`)
- Yetki yukselme engeli (`no-new-privileges`)
- Tum Linux yetenekleri kaldirilir (`cap_drop: ALL`)

> **Not:** Volume izinleri hatali ise uygulama baslangicta
> `"Veri dizini yazilabilir degil"` hatasi verir ve cikar.

### 3c. Production Ortam Degiskenleri

Production modda hassas bilgileri config dosyasina yazmak yerine ortam
degiskenleri ile verin. Proje dizininde bir `.env` dosyasi olusturun:

```bash
cp .env.example .env
# .env dosyasını düzenleyin: sifre, token vb. gercek degerlerle degistirin
nano .env

chmod 600 .env
```

Docker Compose bu dosyayi otomatik okur. Desteklenen degiskenler:

| Degisken | Aciklama |
|----------|----------|
| `ANNEM_ENV` | `production` ise guvenlik kontrolleri aktif |
| `ANNEM_DASHBOARD_USERNAME` | Dashboard kullanici adi |
| `ANNEM_DASHBOARD_PASSWORD` | Dashboard sifresi |
| `ANNEM_TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `ANNEM_DB_PATH` | Veritabani dosya yolu |

> **Onemli:** `ANNEM_ENV=production` oldugunda bos kullanici adi, bos sifre
> veya varsayilan sifre (`change_me_immediately`) ile uygulama **baslamaz**.
> Bu fail-closed tasarimdir.

### 4. Dogrula

```bash
# Pilot checklist calistir
python scripts/pilot_checklist.py

# Dashboard'u kontrol et
# Tarayicida: http://<pi-ip>:8099
```

## Ilk 14 Gun (Ogrenme Donemi)

Sistem otomatik olarak ogrenme modunda baslar:

| Gun | Olay |
|-----|-------|
| 1-7 | Sessiz ogrenme, bildirim yok |
| 7 | Ilk ogrenme raporu (Telegram) |
| 8-14 | Ogrenme devam ediyor, sadece dikkat seviyesi bildirimler |
| 14 | "Sistem hazir" bildirimi |
| 15+ | Aktif anomali tespiti baslar |

Bu sure boyunca:
- Sensorlerin duzgun calistigini dashboard'dan kontrol edin
- Gunluk ozet mesajlari (22:00) gelecektir
- Sistem herhangi bir mudahale gerektirmez

## Guncelleme

```bash
cd /home/pi/annem-guvende
git pull
docker compose up -d --build
```

## Sorun Giderme

Sorunlar icin bkz. [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

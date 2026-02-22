# Konfigurason Rehberi

`config.yml` dosyasi tum sistem ayarlarini icerir.

## Genel Yapi

```yaml
mqtt:          # MQTT broker baglantisi
sensors:       # Sensor tanimlari
model:         # Ogrenme modeli parametreleri
alerts:        # Alarm esikleri
telegram:      # Bildirim ayarlari
heartbeat:     # Dis sunucu saglik kontrolu
database:      # Veritabani ayarlari
```

## mqtt

```yaml
mqtt:
  broker: "localhost"      # MQTT broker adresi
  port: 1883               # MQTT portu
  topic_prefix: "zigbee2mqtt"  # Zigbee2MQTT topic on eki
```

- `broker`: Home Assistant/Mosquitto calistiran makinenin adresi
- `topic_prefix`: Zigbee2MQTT'nin kullandigi topic on eki (genelde degistirmeye gerek yok)

## sensors

Her sensor icin 4 alan gereklidir:

```yaml
sensors:
  - id: "mutfak_motion"       # Zigbee2MQTT'deki friendly_name
    channel: "presence"        # Kanal: presence, fridge, bathroom, door
    type: "motion"             # Sensor tipi: motion veya contact
    trigger_value: "on"        # Aktif deger: "on" (motion) veya "open" (contact)
```

### Kanal Aciklamalari

| Kanal | Aciklama | Sensor Tipi |
|-------|----------|-------------|
| `presence` | Evde varlik/hareket | Hareket sensoru |
| `fridge` | Buzdolabi kullanimi | Kapi/pencere sensoru |
| `bathroom` | Banyo kullanimi | Kapi/pencere sensoru |
| `door` | Dis kapi aktivitesi | Kapi/pencere sensoru |

### Sensor ID Bulma

Zigbee2MQTT arayuzunde (genelde `http://localhost:8080`):
1. Devices sekmesine git
2. Sensorun "Friendly name" degerini kopyala
3. Bu degeri `id` alanina yaz

## model

```yaml
model:
  slot_minutes: 15         # Slot suresi (dk) - degistirmeyin
  awake_start_hour: 6      # Uyanik saatleri baslangici
  awake_end_hour: 23       # Uyanik saatleri bitisi
  learning_days: 14        # Ogrenme donemi suresi (gun)
  prior_alpha: 1.0         # Beta dagilimi prior (degistirmeyin)
  prior_beta: 1.0          # Beta dagilimi prior (degistirmeyin)
```

- `awake_start_hour` / `awake_end_hour`: Yasli bireyin tipik uyanik oldugu saatler
- `learning_days`: Sistem bu kadar gun veri topladiktan sonra "hazir" olur

## alerts

```yaml
alerts:
  z_threshold_gentle: 2.0     # Dikkat seviyesi esigi
  z_threshold_serious: 3.0    # Uyari seviyesi esigi
  z_threshold_emergency: 4.0  # Acil seviyesi esigi
  min_train_days: 7           # Bildirim icin minimum egitim gunu
```

### Alarm Seviyeleri

| Seviye | Etiket | Anlam |
|--------|--------|-------|
| 0 | Normal | Rutin icinde |
| 1 | Dikkat | Hafif sapma |
| 2 | Uyari | Belirgin sapma |
| 3 | Acil | Ciddi anomali |

## telegram

```yaml
telegram:
  bot_token: "123456:ABC-..."  # BotFather'dan alinan token
  chat_ids:
    - "123456789"              # Bildirim alacak kullanici(lar)
```

### Bot Olusturma

1. Telegram'da @BotFather'i acin
2. `/newbot` yazin ve talimatlari izleyin
3. Alinan token'i `bot_token`'a yapisitirin
4. Bot'u bir gruba ekleyin veya dogrudan mesaj gonderin
5. Chat ID'nizi bulmak icin: bot'a mesaj gonderin, ardindan
   `https://api.telegram.org/bot<TOKEN>/getUpdates` adresini ziyaret edin

### Devre Disi Birakma

`bot_token` alanini bos birakin:

```yaml
telegram:
  bot_token: ""
  chat_ids: []
```

## heartbeat

```yaml
heartbeat:
  url: "https://vps.example.com/heartbeat"  # Dis sunucu URL
  device_id: "annem-pi"                      # Cihaz kimligi
  interval_seconds: 300                       # Gonderm araligi (sn)
```

- Bos `url` = heartbeat devre disi
- Dis sunucu Pi'nin ayakta oldugunu dogrular

## database

```yaml
database:
  path: "./data/annem_guvende.db"  # SQLite veritabani yolu
```

- Varsayilan yol genelde yeterlidir
- Docker kullaniyorsaniz volume mount ile kalicilik saglayin

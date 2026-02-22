# Sensor Eslestirme Rehberi

## Desteklenen Sensorler

### Hareket Sensoru (Motion)
- **Aqara Motion Sensor (RTCGQ11LM)** - Tavsiye edilen
- Zigbee uyumlu herhangi bir hareket sensoru

### Kapi/Pencere Sensoru (Contact)
- **Aqara Door and Window Sensor (MCCGQ11LM)** - Tavsiye edilen
- Zigbee uyumlu herhangi bir kapi sensoru

## Minimum Sensor Gereksinimleri

| Konum | Sensor Tipi | Kanal | Aciklama |
|-------|-------------|-------|----------|
| Mutfak/Salon | Hareket | `presence` | Evde varlik tespiti |
| Buzdolabi | Kapi | `fridge` | Yemek hazirlama/beslenme |
| Banyo kapisi | Kapi | `bathroom` | Banyo kullanimi |
| Dis kapi | Kapi | `door` | Dis kapi aktivitesi |

## Zigbee2MQTT ile Eslestirme

### 1. Eslestirme Modunu Acin

Zigbee2MQTT arayuzunde (genelde `http://localhost:8080`):
- "Permit join (All)" butonuna tiklayin
- veya MQTT ile: `zigbee2mqtt/bridge/request/permit_join` topic'ine `{"value": true}` gonderin

### 2. Sensoru Eslestirin

- **Aqara Motion**: Sensorun altindaki butona 5 saniye basin (LED yanip sonecek)
- **Aqara Contact**: Ince bir igneyle sifrilama deligine basin

### 3. Friendly Name Belirleyin

Zigbee2MQTT arayuzunde:
1. Yeni eklenen cihazi secin
2. "Friendly name" alanini duzenlerin:
   - Hareket sensoru: `mutfak_motion`
   - Buzdolabi: `buzdolabi_kapi`
   - Banyo: `banyo_kapi`
   - Dis kapi: `dis_kapi`

### 4. config.yml'e Ekleyin

```yaml
sensors:
  - id: "mutfak_motion"
    channel: "presence"
    type: "motion"
    trigger_value: "on"
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
```

## Kanal Aciklamasi

### presence (Varlik)
- Evin ana yasam alanina yerlestirilir (mutfak, salon)
- Hareket algilandiginda "on", hareketsizlikte "off" mesaji gelir
- Gunluk hareket paterni ogrenilir

### fridge (Buzdolabi)
- Buzdolabi kapisina yapistrilir
- Duzgun beslenme izlemesi icin kritik
- Buzdolabinin hic acilmamasi anomali isaretiidir

### bathroom (Banyo)
- Banyo kapisina yapistrilir
- Hijyen ve saglik izlemesi
- Banyo kullaniminda uzun sureli degisiklik anomali isaretiidir

### door (Dis Kapi)
- Dis kapiya yapistrilir
- Dis ortam aktivitesi izlemesi
- Opsiyonel: gelmezse diger kanallar yeterli olabilir

## Yeni Sensor Ekleme

1. Sensoru Zigbee2MQTT ile eslestirin
2. Friendly name belirleyin
3. `config.yml`'in `sensors` bolumune ekleyin
4. Sistemi yeniden baslatin: `docker compose restart`

## Evcil Hayvan Uyarisi

Evde kedi veya kopek varsa hareket (presence) sensorleri hayvan hareketlerinden de tetiklenir. Bu durum modeli bozabilir.

**Cozum secenekleri:**

1. Pet-immune PIR sensor kullanin (Aqara FP2 mmWave sensor hayvan/insan ayrimiyapabilir)
2. Standart PIR sensorleri yerden en az 1.2 metre yukseklige, asagi dogru bakmayacak aciyla monte edin
3. Pilot kurulum oncesi ev sakinleriyle evcil hayvan durumunu mutlaka konusun

## Pil Omru

- Aqara Motion: ~2 yil (CR2450 pil)
- Aqara Contact: ~2 yil (CR1632 pil)
- Pil seviyesi Zigbee2MQTT arayuzunden izlenebilir

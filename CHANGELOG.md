# Degisiklik Kaydi (Changelog)

Tum onemli degisiklikler sprint bazinda belgelenmistir.

---

## Sprint 16 — Security Hotfix + Documentation Drift Fix
- **Production Auth Fail-Closed:** Boş kullanıcı adı, boş şifre veya varsayılan şifre ile production başlatma engellendi (3 ayrı ValueError). Eski mantıktaki fail-open bug düzeltildi.
- **Env Username Override:** `ANNEM_DASHBOARD_USERNAME` ortam değişkeni desteği eklendi.
- **Telegram Callback Authorization:** `_handle_callback_query()` artık chat_id whitelist kontrolü yapıyor. Kayıtsız kullanıcılardan gelen buton tıklamaları reddedilir.
- **pending_alerts DB Index:** `(status, timestamp)` composite index ile eskalasyon sorgusu hızlandırıldı (Migration v4).
- **Nightly Cleanup:** 30 günden eski pending_alerts kayıtları gece bakımında temizlenir.
- **Private Access Temizliği:** `alert_mgr._notifier.send_to_all()` → `alert_mgr.send_notification()` public API.
- **Docs Drift Fix:** README, CONFIG, ARCHITECTURE, API, INSTALL, TROUBLESHOOTING belgeleri Sprint 13-16 değişiklikleriyle güncellendi.
- **Prod Compose Fix (16.1):** Hardcoded şifreler `${VAR}` interpolasyona çevrildi, `.env.example` eklendi, `ANNEM_DB_PATH` env desteği eklendi.

**Test sayısı:** 310 → 313 (+3)

---

## Sprint 15 — Akıllı Eskalasyon (Ölü Adamın Anahtarı)
- **pending_alerts Tablosu:** Level 3 alarmlar DB'ye kaydedilir, yaşam döngüsü: pending → acknowledged / escalated (Migration v3).
- **Inline Keyboard:** Acil alarm mesajlarında "✅ Gördüm, İlgileniyorum" butonu. `answerCallbackQuery` ile anında geri bildirim.
- **Eskalasyon Job:** 2 dakikada bir yanıtsız alarmları kontrol eder. Süresi dolmuş alarmlar `emergency_chat_ids` listesine iletilir.
- **Config:** `telegram.emergency_chat_ids` ve `telegram.escalation_minutes` ayarları.
- **Telegram Komut Dinleme:** `allowed_updates` listesine `callback_query` eklendi.

**Test sayısı:** 303 → 310 (+7)

---

## Sprint 14 — Kırılganlık Endeksi (Frailty Index)
- **Trend Analyzer:** Saf Python OLS lineer regresyon ile kanal bazlı uzun vadeli trend tespiti.
- **Sıfır-Gün Doldurma:** SQL GROUP BY'ın atladığı boş günler 0 ile padding — eğim doğruluğu garanti.
- **Dashboard Endpoint:** GET /api/trends → kanal bazlı eğim değerleri.
- **Haftalık Rapor:** Pazar 10:00 — banyo artış ve hareket azalış trendleri Telegram bildirimi.
- **Config:** trend_analysis_days, trend_min_days, trend_bathroom_threshold, trend_presence_threshold.

**Test sayısı:** 294 → 303 (+9)

---

## Sprint 13 — Kamerasız Düşme Tespiti (Time-to-Return)
- **Fall Detection:** Banyo kapısı kapandıktan sonra 45dk sessizlik → Level 3 ACİL alarm.
- **Akıllı State Temizleme:** Banyo dışı HERHANGİ BİR sensör tetiklenince state temizlenir (gece yatağa dönme dahil).
- **Alarm Spam Önleme:** Alarm verildikten sonra state otomatik temizlenir.
- **Feature Flag:** fall_detection_minutes=0 ile tamamen kapatılabilir.

**Test sayısı:** 289 → 294 (+5)

---

## Sprint 12 — Final Polish
- **Realtime Rate-Limit DB Persist:** handle_realtime_alert() restart-safe.
- **Callable Type-Hint:** callable → Callable (semantik duzeltme).
- **CI Compile Gate:** scripts/ci_check.sh + compileall CI adimi.
- **Docker Hardening:** read_only, cap_drop ALL, no-new-privileges, tmpfs.
- **Volume Izin Kontrolu:** Yazilabilirlik kontrolu + UID 10001 sabitleme.
- **Secrets Env Override:** ANNEM_DASHBOARD_PASSWORD, ANNEM_TELEGRAM_BOT_TOKEN.
- **Production Password Block:** ANNEM_ENV=production'da varsayilan sifre → ValueError.

**Test sayisi:** 284 → 288 (+4)

---

## Sprint 11 — Production Hardening
- **Import Crash Fix:** from \_\_future\_\_ import annotations (callable | None crash).
- **Battery Callback Setter:** _battery_callback → set_battery_callback() public API.
- **init_db.py Fix:** config.get() → config.database.path.
- **Health Endpoint 503:** Exception'da HTTP 200 → 503.
- **Default Password Warning:** CRITICAL log uyarisi.
- **Non-Root Docker:** useradd annem + HEALTHCHECK.
- **.dockerignore:** Image temizligi.
- **Rate-Limit DB Persist:** Daily alarm rate-limit restart-safe.

**Test sayisi:** 279 → 284 (+5)

---

## Sprint 10 — Urun Ozellikleri (ITU Cekirdek Hazirligi)

**Yeni ozellikler:**

- **Demo Modu:** `python -m src.simulator --demo` ile 21 gunluk hizlandirilmis simulasyon. 14 gun ogrenme + 7 gun test, gun 18'de anomali tespiti. Juri demosu icin `--speed N` parametresi.
- **Telegram Iki Yonlu Komutlar:** `/durum`, `/bugun`, `/tatil`, `/evdeyim`, `/yardim` komutlari. 30 saniye polling ile komut dinleme.
- **Sensor Pil Takibi:** Pil seviyesi %10'un altina dustugunde Telegram uyarisi. %20'nin uzerine cikinca uyari bayragi sifirlanir.
- **Dinamik Kanallar:** Kanal listesi config'den okunur, 4 sabit kanal yerine dinamik. Geriye uyumlu (`channels=None` varsayilan).
- **Heartbeat Internet Notu:** MQTT kopukluk uyarisinda internet kesintisi olasiligi notu.
- **Pilot Checklist:** Demo modu ve Telegram komut kontrolleri eklendi.

**Yeni dosyalar:** `src/simulator/__main__.py`, `tests/test_demo_mode.py`, `tests/test_channels_dynamic.py`, `tests/test_battery_monitor.py`, `tests/test_telegram_commands.py`

**Test sayisi:** 254 → 279 (+25)

---

## Sprint 9 — Kalite ve Altyapi

- **Pydantic Typed Config:** `AppConfig` ile 9 alt modelli tip guvenli konfigurasyon. Tum `config.get()` ve `config["key"]` erisimleri attribute erisimi ile degistirildi.
- **GitHub Actions CI:** Her push ve PR'da `ruff check` + `pytest` otomatik calisir.
- **Ruff Linter:** py311, satir uzunlugu 120, E/F/I/N/W kurallari.
- **Jobs Refaktor:** Zamanlayici gorevleri `main.py`'den `jobs.py`'ye tasindi.
- **Ruff Temizligi:** 62 lint hatasi duzeltildi (59 otomatik, 3 manuel).

**Test sayisi:** 246 → 254 (+8)

---

## Sprint 8 — Guvenlik ve Skor Duzeltmeleri

- **HTTP Basic Auth:** Dashboard icin `BasicAuthMiddleware`. `/health` haric tum endpoint'ler korunur. Config'den kullanici adi/sifre.
- **Tek Yonlu NLL Z-Skoru:** Sadece yuksek NLL riskli (`max(0, z)`). Dusuk NLL (iyi) artik alarm tetiklemiyor.
- **Tek Yonlu Count Risk:** Sadece dusuk aktivite riskli (`max(0, -count_z)`). Yuksek aktivite alarm tetiklemiyor.
- **Composite Z-Score:** `max(nll_z, count_risk)` — iki bagimsiz sinyalin maksimumu.
- **Vacation Mode:** `system_state` tablosunda DB-tabanli tatil modu. Config fallback.
- **DB Bakim Gorevi:** Gece 03:00'te eski olaylari temizleme + WAL checkpoint.
- **Evcil Hayvan Kontrolu:** Pilot checklist'te pet-immune sensor hatirlatmasi.

**Test sayisi:** 224 → 246 (+22)

---

## Sprint 7 — Heartbeat ve Watchdog

- **Heartbeat Client:** Harici VPS'e periyodik HTTP ping. Sistem metrikleri (CPU, RAM, disk, sicaklik) payload'a eklenir.
- **System Monitor:** `psutil` ile CPU, bellek, disk, sicaklik, DB boyutu izleme.
- **Watchdog:** 15 dakikada bir saglik kontrolu. CPU sicaklik > 80C, disk > 90%, RAM > 90%, MQTT kopuk, DB buyuk uyarilari. Telegram ile bildirim.

**Test sayisi:** 204 → 224 (+20)

---

## Sprint 6 — Web Dashboard

- **FastAPI Dashboard Router:** 6 REST API endpoint (`/api/status`, `/api/daily/{date}`, `/api/history`, `/api/heatmap`, `/api/learning-curve`, `/api/health`).
- **Chart.js Frontend:** Tek sayfa HTML dashboard. Durum karti, gunluk detay, tarihsel grafik, heatmap, ogrenme egrisi.
- **Offline Assets:** Chart.js yerel olarak bundled (`chart.umd.min.js`), CDN bagimliligi yok.

**Test sayisi:** 184 → 204 (+20)

---

## Sprint 5 — Gercek Zamanli Kontroller

- **Sabah Sessizlik Kontrolu:** Saat 11:00'e kadar hic aktivite yoksa uyari.
- **Uzun Sessizlik Kontrolu:** Uyanik saatlerde 3+ saat sessizlik varsa uyari.
- **30 Dakika Aralik:** Realtime check'ler her 30 dakikada bir calisir.
- **Tatil Modunda Atlama:** Tatil modunda gercek zamanli kontroller atlanir.

**Test sayisi:** 166 → 184 (+18)

---

## Sprint 4 — Telegram Bildirimleri

- **TelegramNotifier:** Sync httpx ile Telegram Bot API entegrasyonu. `send_message`, `send_to_all`, `send_photo`.
- **AlertManager:** 3 kademeli alarm bildirimi. Rate limiting (6 saat sogutma). Seviye artisi sogutmayi atlar.
- **Mesaj Sablonlari:** Gunluk ozet, alarm seviyeleri (nazik/ciddi/acil), sabah sessizligi, ogrenme ilerleme, ogrenme tamamlandi.
- **Ogrenme Donemi Filtreleri:** Gun 1-7 sessiz ogrenme, gun 8-14 maksimum seviye 1, gun 15+ tam alarm.

**Test sayisi:** 136 → 166 (+30)

---

## Sprint 1-3 — Temel ML Pipeline

### Sprint 3: Anomali Tespiti
- **AnomalyScorer:** NLL-tabanli anomali puanlama. 30 gunluk hareketli istatistikler.
- **ThresholdEngine:** Z-score esik motoru, 4 seviyeli alarm (0-3).
- **HistoryManager:** Anomali ve ogrenme gunlerini tarihceden haric tutma.

### Sprint 2: Rutin Ogrenme
- **BetaPosterior:** Beta-Binomial konjuge prior modeli. Immutable guncelleme.
- **RoutineLearner:** Gunluk ogrenme pipeline. 96 slot x 4 kanal.
- **Metrics:** Kanal bazli NLL, count Z-skoru, uyanik saat dogrulugu, CI genisligi.

### Sprint 1: Veri Toplama
- **MQTTCollector:** paho-mqtt 2.x ile MQTT baglantisi. Topic-sensor eslestirmesi.
- **EventProcessor:** Payload parse, debounce (30s), aktif/pasif filtre.
- **SlotAggregator:** 15 dakikalik zaman dilimi ozetleme. `fill_missing_slots` ile eksik doldurma.

### Sprint 0: Proje Iskeleti
- FastAPI uygulama iskeleti (async lifespan)
- SQLite veritabani (WAL modu, migrasyon sistemi)
- Docker Compose konfigurasyonu
- Config yonetimi (YAML)
- SensorSimulator (test veri uretici)

**Test sayisi:** 0 → 136

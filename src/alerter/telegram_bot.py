"""Telegram Bot API entegrasyonu (sync httpx).

TelegramNotifier: mesaj ve fotograf gonderimi.
Token bos ise sessizce devre disi kalir (graceful degradation).
"""

import logging

import httpx

logger = logging.getLogger("annem_guvende.alerter")

TELEGRAM_API_BASE = "https://api.telegram.org"
SEND_TIMEOUT = 10.0


class TelegramNotifier:
    """Telegram Bot API uzerinden bildirim gondericisi.

    Args:
        bot_token: Telegram bot token (bos ise bildirimler devre disi)
        chat_ids: Bildirim gonderilecek chat ID listesi
        client: Opsiyonel httpx.Client (test icin dependency injection)
    """

    def __init__(
        self,
        bot_token: str,
        chat_ids: list[str],
        client: httpx.Client | None = None,
    ):
        self._token = bot_token
        self._chat_ids = [str(cid) for cid in chat_ids]
        self._enabled = bool(bot_token)
        self._base_url = f"{TELEGRAM_API_BASE}/bot{bot_token}"
        self._client = client or httpx.Client(timeout=SEND_TIMEOUT)

        if not self._enabled:
            logger.warning("Telegram bot_token ayarlanmamis - bildirimler devre disi")

    @property
    def enabled(self) -> bool:
        """Bildirimler aktif mi?"""
        return self._enabled

    def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
    ) -> bool:
        """Tek bir chat'e mesaj gonder.

        Returns:
            True = basarili, False = hata veya devre disi
        """
        if not self._enabled:
            return False

        try:
            response = self._client.post(
                f"{self._base_url}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                },
            )
            if response.status_code == 200:
                logger.info("Telegram mesaji gonderildi: chat_id=%s", chat_id)
                return True
            else:
                logger.error(
                    "Telegram API hatasi: status=%d body=%s",
                    response.status_code,
                    response.text[:200],
                )
                return False
        except httpx.HTTPError as exc:
            logger.error("Telegram baglanti hatasi: %s", exc)
            return False

    def send_to_all(self, text: str, parse_mode: str = "HTML") -> dict[str, bool]:
        """Tum kayitli chat_ids'e mesaj gonder.

        Returns:
            {chat_id: basarili_mi} dict'i
        """
        results = {}
        for chat_id in self._chat_ids:
            results[chat_id] = self.send_message(chat_id, text, parse_mode)
        return results

    def send_photo(
        self,
        chat_id: str,
        photo_bytes: bytes,
        caption: str = "",
        parse_mode: str = "HTML",
    ) -> bool:
        """Fotograf gonder (Sprint 6 dashboard grafikleri icin).

        Returns:
            True = basarili
        """
        if not self._enabled:
            return False

        try:
            response = self._client.post(
                f"{self._base_url}/sendPhoto",
                data={
                    "chat_id": chat_id,
                    "caption": caption,
                    "parse_mode": parse_mode,
                },
                files={"photo": ("chart.png", photo_bytes, "image/png")},
            )
            if response.status_code == 200:
                logger.info("Telegram fotograf gonderildi: chat_id=%s", chat_id)
                return True
            else:
                logger.error(
                    "Telegram photo API hatasi: status=%d", response.status_code
                )
                return False
        except httpx.HTTPError as exc:
            logger.error("Telegram photo baglanti hatasi: %s", exc)
            return False

    def close(self) -> None:
        """HTTP client'i kapat (shutdown sirasinda cagrilir)."""
        self._client.close()

    # --- Komut Dinleme (FIX 16) ---

    def get_updates(self, offset: int = 0) -> list[dict]:
        """Telegram Bot API'den yeni mesajlari al.

        Args:
            offset: Son islenen update_id + 1

        Returns:
            Update listesi
        """
        if not self._enabled:
            return []

        try:
            params: dict = {"timeout": 5, "allowed_updates": ["message"]}
            if offset > 0:
                params["offset"] = offset
            response = self._client.get(
                f"{self._base_url}/getUpdates",
                params=params,
                timeout=10.0,
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("result", [])
            logger.warning("getUpdates hatasi: status=%d", response.status_code)
            return []
        except httpx.HTTPError as exc:
            logger.error("getUpdates baglanti hatasi: %s", exc)
            return []

    def process_commands(self, db_path: str, config) -> None:
        """Gelen Telegram komutlarini isle.

        Bilinen komutlar: /durum, /bugun, /tatil, /evdeyim, /yardim, /start
        Sadece kayitli chat_id'lerden gelen komutlar islenir.
        """
        from src.database import get_system_state, set_system_state

        last_offset_str = get_system_state(db_path, "telegram_last_offset", "0")
        try:
            last_offset = int(last_offset_str)
        except ValueError:
            last_offset = 0

        updates = self.get_updates(offset=last_offset)
        if not updates:
            return

        new_offset = last_offset
        for update in updates:
            update_id = update.get("update_id", 0)
            if update_id >= new_offset:
                new_offset = update_id + 1

            message = update.get("message", {})
            chat_id = str(message.get("chat", {}).get("id", ""))
            text = (message.get("text") or "").strip()

            # Sadece kayitli chat_id'lerden
            if chat_id not in self._chat_ids:
                logger.warning("Bilinmeyen chat_id: %s (ignoring)", chat_id)
                continue

            if not text.startswith("/"):
                continue

            command = text.split()[0].lower()
            if "@" in command:
                command = command.split("@")[0]

            if command in ("/yardim", "/start"):
                self._handle_yardim(chat_id)
            elif command == "/durum":
                self._handle_durum(chat_id, db_path, config)
            elif command == "/bugun":
                self._handle_bugun(chat_id, db_path)
            elif command == "/tatil":
                self._handle_tatil(chat_id, db_path)
            elif command == "/evdeyim":
                self._handle_evdeyim(chat_id, db_path)

        set_system_state(db_path, "telegram_last_offset", str(new_offset))

    def _handle_yardim(self, chat_id: str) -> None:
        """Yardim metni gonder."""
        text = (
            "🏠 <b>Annem Güvende - Komutlar</b>\n\n"
            "/durum — Sistem durumu\n"
            "/bugun — Bugünün olay sayıları\n"
            "/tatil — Tatil modunu aç\n"
            "/evdeyim — Tatil modunu kapat\n"
            "/yardim — Bu yardım mesajı"
        )
        self.send_message(chat_id, text)

    def _handle_durum(self, chat_id: str, db_path: str, config) -> None:
        """Sistem durumu gonder."""
        from src.database import get_db, is_vacation_mode

        vacation = is_vacation_mode(db_path, config)
        vacation_text = "ACIK" if vacation else "KAPALI"

        with get_db(db_path) as conn:
            score_row = conn.execute(
                "SELECT train_days, is_learning FROM daily_scores "
                "ORDER BY date DESC LIMIT 1"
            ).fetchone()
            event_row = conn.execute(
                "SELECT timestamp FROM sensor_events "
                "ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()

        train_days = score_row["train_days"] if score_row else 0
        is_learning = bool(score_row["is_learning"]) if score_row else True
        last_event = event_row["timestamp"] if event_row else "Yok"
        phase = "Ogrenme" if is_learning else "Aktif"

        text = (
            f"📊 <b>Sistem Durumu</b>\n\n"
            f"Tatil modu: {vacation_text}\n"
            f"Egitim gunu: {train_days}\n"
            f"Faz: {phase}\n"
            f"Son olay: {last_event}"
        )
        self.send_message(chat_id, text)

    def _handle_bugun(self, chat_id: str, db_path: str) -> None:
        """Bugunun kanal bazli event sayilarini gonder."""
        from datetime import datetime

        from src.database import get_db

        today = datetime.now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            rows = conn.execute(
                "SELECT channel, COUNT(*) as cnt "
                "FROM sensor_events WHERE timestamp >= ? "
                "GROUP BY channel",
                (today,),
            ).fetchall()

        if not rows:
            self.send_message(chat_id, "Bugün henüz olay kaydedilmedi.")
            return

        lines = [f"📋 <b>Bugünün Olayları</b> — {today}\n"]
        total = 0
        for row in rows:
            lines.append(f"  {row['channel']}: {row['cnt']}")
            total += row["cnt"]
        lines.append(f"\nToplam: {total}")
        self.send_message(chat_id, "\n".join(lines))

    def _handle_tatil(self, chat_id: str, db_path: str) -> None:
        """Tatil modunu ac."""
        from src.database import set_system_state

        set_system_state(db_path, "vacation_mode", "true")
        self.send_message(
            chat_id,
            "Tatil modu <b>açıldı</b>.\n"
            "Alarmlar duraklatıldı. Eve döndüğünüzde /evdeyim yazın.",
        )

    def _handle_evdeyim(self, chat_id: str, db_path: str) -> None:
        """Tatil modunu kapat."""
        from src.database import set_system_state

        set_system_state(db_path, "vacation_mode", "false")
        self.send_message(
            chat_id,
            "Tatil modu <b>kapatıldı</b>.\nSistem normal izleme moduna döndü.",
        )

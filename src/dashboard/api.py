"""Dashboard REST API endpoint'leri.

FastAPI APIRouter ile 6 endpoint.
app.state uzerinden DB path ve MQTT durumuna erisir.
Veri hazirlamasi charts.py'ye delege edilir.
"""

from fastapi import APIRouter, HTTPException, Request, Response

from src.dashboard.charts import (
    get_daily_data,
    get_heatmap_data,
    get_history_data,
    get_learning_curve_data,
    get_status_data,
)
from src.heartbeat import collect_system_metrics, run_health_checks

router = APIRouter(prefix="/api", tags=["dashboard"])


def _safe_mqtt_check(request: Request) -> bool:
    """MQTT baglanti durumunu guvenli sekilde kontrol et.

    Test ortaminda mqtt_collector olmayabilir.
    """
    try:
        return request.app.state.mqtt_collector.is_connected()
    except AttributeError:
        return False


@router.get("/status")
async def api_status(request: Request):
    """Anlik durum verisi."""
    db_path = request.app.state.db_path
    mqtt_ok = _safe_mqtt_check(request)
    return get_status_data(db_path, mqtt_ok)


@router.get("/daily/{date}")
async def api_daily(date: str, request: Request):
    """Belirli bir gune ait detayli veri."""
    result = get_daily_data(request.app.state.db_path, date)
    if result is None:
        raise HTTPException(status_code=404, detail="Tarih bulunamadi")
    return result


@router.get("/history")
async def api_history(request: Request, days: int = 30):
    """Tarihsel gunluk skor verileri."""
    return get_history_data(request.app.state.db_path, days)


@router.get("/heatmap")
async def api_heatmap(request: Request):
    """Model olasilik haritasi ve son aktivite."""
    return get_heatmap_data(request.app.state.db_path)


@router.get("/learning-curve")
async def api_learning_curve(request: Request):
    """Ogrenme egrisi verileri."""
    return get_learning_curve_data(request.app.state.db_path)


@router.get("/health")
async def api_health(request: Request, response: Response):
    """Sistem saglik kontrolu.

    Mevcut /health endpoint mantigini yeniden kullanir.
    """
    try:
        db_path = request.app.state.db_path
        mqtt_ok = _safe_mqtt_check(request)
        metrics = collect_system_metrics(db_path)
        status = run_health_checks(metrics, mqtt_ok)
        return {
            "status": "ok" if status.all_healthy else "degraded",
            "checks": {c.name: c.healthy for c in status.checks},
            "metrics": {
                "cpu_percent": metrics.cpu_percent,
                "memory_percent": metrics.memory_percent,
                "disk_percent": metrics.disk_percent,
                "cpu_temp": metrics.cpu_temp,
                "db_size_mb": round(metrics.db_size_mb, 2),
                "today_event_count": metrics.today_event_count,
            },
        }
    except Exception as exc:
        response.status_code = 503
        return {"status": "error", "reason": str(exc)}

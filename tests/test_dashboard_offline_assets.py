"""FIX 4 Tests: Chart.js offline.

- index.html icinde "cdn.jsdelivr.net" yok
- chart.umd.min.js dosyasi mevcut
"""

import os


def test_no_cdn_reference_in_html():
    """index.html icinde CDN referansi olmamali."""
    html_path = os.path.join(
        os.path.dirname(__file__), "..", "src", "dashboard", "static", "index.html"
    )
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "cdn.jsdelivr.net" not in content, (
        "index.html hala CDN referansi iceriyor!"
    )


def test_chart_js_file_exists():
    """chart.umd.min.js dosyasi repo icinde mevcut olmali."""
    chart_path = os.path.join(
        os.path.dirname(__file__), "..", "src", "dashboard", "static", "chart.umd.min.js"
    )
    assert os.path.isfile(chart_path), (
        "chart.umd.min.js dosyasi bulunamadi!"
    )
    # Dosya boyutu > 10KB (bos olmamali)
    assert os.path.getsize(chart_path) > 10_000, (
        "chart.umd.min.js dosyasi cok kucuk - bozuk olabilir"
    )


def test_html_references_local_chart():
    """index.html local chart.js dosyasina referans icermeli."""
    html_path = os.path.join(
        os.path.dirname(__file__), "..", "src", "dashboard", "static", "index.html"
    )
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "/static/chart.umd.min.js" in content, (
        "index.html local chart.js referansi icermiyor!"
    )

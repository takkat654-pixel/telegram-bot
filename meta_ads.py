"""Meta (Facebook) Ads Marketing API helper.

Handles fetching ad account insights (spend, results, etc.) and formatting
them into Thai-language Telegram messages, plus simple threshold-based
anomaly checks.

Required environment variables:
    META_ACCESS_TOKEN     - Access token with the `ads_read` permission
    META_AD_ACCOUNT_ID    - Ad account ID (numeric, with or without "act_")

Optional environment variables:
    META_API_VERSION                  - default "v21.0"
    META_CURRENCY_LABEL                - default "บาท"
    ADS_SPEND_ALERT_THRESHOLD          - alert when today's spend reaches this
    ADS_ZERO_RESULTS_SPEND_THRESHOLD   - alert when spend passes this with 0 results
"""

import os

import requests

META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID")
META_API_VERSION = os.getenv("META_API_VERSION", "v21.0")
META_CURRENCY_LABEL = os.getenv("META_CURRENCY_LABEL", "บาท")

GRAPH_API_BASE = "https://graph.facebook.com"

SPEND_ALERT_THRESHOLD = float(os.getenv("ADS_SPEND_ALERT_THRESHOLD", "0") or 0)
ZERO_RESULTS_SPEND_THRESHOLD = float(os.getenv("ADS_ZERO_RESULTS_SPEND_THRESHOLD", "0") or 0)

ACTION_LABELS = {
    "link_click": "คลิกลิงก์",
    "lead": "Lead",
    "purchase": "การซื้อ",
    "offsite_conversion.fb_pixel_purchase": "การซื้อ (Pixel)",
    "offsite_conversion.fb_pixel_lead": "Lead (Pixel)",
    "offsite_conversion.fb_pixel_complete_registration": "ลงทะเบียน (Pixel)",
    "complete_registration": "ลงทะเบียน",
    "messaging_conversation_started_7d": "เริ่มแชท",
    "onsite_conversion.messaging_conversation_started_7d": "เริ่มแชท",
    "onsite_conversion.lead_grouped": "Lead (ในแพลตฟอร์ม)",
    "landing_page_view": "เข้าชม Landing Page",
    "post_engagement": "การมีส่วนร่วมกับโพสต์",
    "page_engagement": "การมีส่วนร่วมกับเพจ",
    "video_view": "ดูวิดีโอ",
}

# Action types that count as a genuine "result" (conversion) rather than a
# top-of-funnel engagement metric (clicks/views/engagement are already shown
# separately). Kept intentionally conservative — covers the most common lead
# generation / e-commerce / messaging objectives.
CONVERSION_ACTION_TYPES = {
    "lead",
    "purchase",
    "offsite_conversion.fb_pixel_purchase",
    "offsite_conversion.fb_pixel_lead",
    "offsite_conversion.fb_pixel_complete_registration",
    "complete_registration",
    "messaging_conversation_started_7d",
    "onsite_conversion.messaging_conversation_started_7d",
    "onsite_conversion.lead_grouped",
}

DATE_PRESET_LABELS = {
    "today": "วันนี้",
    "yesterday": "เมื่อวาน",
    "last_7d": "7 วันล่าสุด",
    "last_30d": "30 วันล่าสุด",
}


class AdsConfigError(Exception):
    """Raised when Meta Ads credentials are not configured."""


def is_configured() -> bool:
    return bool(META_ACCESS_TOKEN and META_AD_ACCOUNT_ID)


def _ensure_configured():
    if not is_configured():
        raise AdsConfigError(
            "ยังไม่ได้ตั้งค่า META_ACCESS_TOKEN และ/หรือ META_AD_ACCOUNT_ID"
        )


def fetch_insights(date_preset: str = "today") -> dict:
    """Fetch aggregated insights for the whole ad account for a date preset.

    date_preset: one of Meta's supported presets, e.g. "today", "yesterday",
    "last_7d", "last_30d".
    """
    _ensure_configured()
    account_id = META_AD_ACCOUNT_ID
    if not account_id.startswith("act_"):
        account_id = f"act_{account_id}"

    url = f"{GRAPH_API_BASE}/{META_API_VERSION}/{account_id}/insights"
    params = {
        "fields": "spend,impressions,clicks,ctr,cpc,actions",
        "date_preset": date_preset,
        "access_token": META_ACCESS_TOKEN,
    }
    resp = requests.get(url, params=params, timeout=20)
    try:
        data = resp.json()
    except ValueError:
        resp.raise_for_status()
        raise RuntimeError("Meta API ตอบกลับข้อมูลที่อ่านไม่ได้")

    if resp.status_code != 200 or "error" in data:
        error = data.get("error", {})
        message = error.get("message", str(data))
        raise RuntimeError(f"Meta API error: {message}")

    rows = data.get("data", [])
    if not rows:
        return {
            "spend": 0.0,
            "impressions": 0,
            "clicks": 0,
            "ctr": 0.0,
            "cpc": 0.0,
            "actions": [],
        }

    row = rows[0]
    return {
        "spend": float(row.get("spend", 0) or 0),
        "impressions": int(row.get("impressions", 0) or 0),
        "clicks": int(row.get("clicks", 0) or 0),
        "ctr": float(row.get("ctr", 0) or 0),
        "cpc": float(row.get("cpc", 0) or 0),
        "actions": row.get("actions", []) or [],
    }


def total_results(actions: list) -> int:
    """Sum only genuine conversion-type actions (see CONVERSION_ACTION_TYPES).

    Deliberately excludes top-of-funnel actions like link_click or
    landing_page_view, since those are already surfaced as separate metrics
    (clicks/CTR) and summing everything would double-count the funnel.
    """
    total = 0
    for action in actions:
        if action.get("action_type") not in CONVERSION_ACTION_TYPES:
            continue
        try:
            total += int(float(action.get("value", 0)))
        except (TypeError, ValueError):
            continue
    return total


def format_actions(actions: list) -> str:
    if not actions:
        return "  (ไม่มีข้อมูลผลลัพธ์)"
    lines = []
    for action in actions:
        action_type = action.get("action_type", "")
        label = ACTION_LABELS.get(action_type, action_type)
        value = action.get("value", "0")
        marker = "🎯" if action_type in CONVERSION_ACTION_TYPES else "•"
        lines.append(f"  {marker} {label}: {value}")
    return "\n".join(lines)


def format_insights_message(insights: dict, date_preset: str) -> str:
    label = DATE_PRESET_LABELS.get(date_preset, date_preset)
    spend = insights["spend"]
    results = total_results(insights["actions"])
    cost_per_result = (spend / results) if results else 0.0

    lines = [
        f"📊 *สรุปผลการยิงแอด ({label})*",
        "━━━━━━━━━━━━━━━",
        f"💰 ยอดใช้จ่าย: {spend:,.2f} {META_CURRENCY_LABEL}",
        f"👁 การเข้าถึง (Impressions): {insights['impressions']:,}",
        f"🖱 คลิก: {insights['clicks']:,} (CTR {insights['ctr']:.2f}%)",
        f"💵 CPC เฉลี่ย: {insights['cpc']:,.2f} {META_CURRENCY_LABEL}",
        "",
        "🎯 ผลลัพธ์ทั้งหมด: "
        + f"{results:,}"
        + (
            f" (ต้นทุน/ผลลัพธ์ ≈ {cost_per_result:,.2f} {META_CURRENCY_LABEL})"
            if results
            else ""
        ),
        format_actions(insights["actions"]),
        "",
        "(🎯 = นับรวมในผลลัพธ์ทั้งหมด, • = ข้อมูลประกอบ)",
    ]
    return "\n".join(lines)


def check_anomalies(insights: dict) -> list[str]:
    """Return a list of Thai-language warning strings for today's insights."""
    warnings = []
    spend = insights["spend"]
    results = total_results(insights["actions"])

    if SPEND_ALERT_THRESHOLD and spend >= SPEND_ALERT_THRESHOLD:
        warnings.append(
            f"⚠️ ยอดใช้จ่ายวันนี้ ({spend:,.2f} {META_CURRENCY_LABEL}) "
            f"ถึงเกณฑ์ที่ตั้งไว้ ({SPEND_ALERT_THRESHOLD:,.2f} {META_CURRENCY_LABEL}) แล้ว"
        )

    if (
        ZERO_RESULTS_SPEND_THRESHOLD
        and spend >= ZERO_RESULTS_SPEND_THRESHOLD
        and results == 0
    ):
        warnings.append(
            f"⚠️ ใช้จ่ายไปแล้ว {spend:,.2f} {META_CURRENCY_LABEL} "
            "แต่ยังไม่มีผลลัพธ์เลย ลองตรวจสอบแอดดูครับ"
        )

    return warnings

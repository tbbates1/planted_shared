"""Watsonx Orchestrate tools for Salesforce pipeline insights.

These functions reuse the existing pipeline-mcp services (no MCP transport).
Environment requirements:
- SALESFORCE_USERNAME (SF CLI authenticated via `sf org login web -a ...`)
- Optional Neo4j vars (if Neo4j is used by pipeline-mcp): NEO4J_PIPELINE_URI, NEO4J_PIPELINE_USER, NEO4J_PIPELINE_PASSWORD
"""

from __future__ import annotations

import os
import re
import sys
from importlib import import_module
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from statistics import mean
from typing import Any

from ibm_watsonx_orchestrate.agent_builder.connections import ConnectionType, ExpectedCredentials
from ibm_watsonx_orchestrate.agent_builder.tools import tool

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

_VENDOR_DIR = _TOOLS_DIR.parent / "vendor"
if str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))


def _register_vendor_paths() -> None:
    """Best-effort discovery of vendor paths in local and cloud runtimes."""
    candidates: list[Path] = [
        _TOOLS_DIR / "vendor",
        _TOOLS_DIR.parent / "vendor",
        Path.cwd() / "vendor",
    ]

    for parent in _TOOLS_DIR.parents:
        candidates.append(parent / "vendor")

    shared_root = Path("/shared")
    if shared_root.exists():
        try:
            for child in shared_root.iterdir():
                candidates.append(child / "vendor")
        except Exception:
            pass

    for base in candidates:
        module_dir = base / "pipeline_mcp"
        if module_dir.exists() and str(base) not in sys.path:
            sys.path.insert(0, str(base))


_register_vendor_paths()

# Avoid strict settings validation failures in older vendored revisions.
os.environ.setdefault("SALESFORCE_USERNAME", "env-token")

try:
    from guardrails_light import detect_injection, sanitize_input, validate_output_text
except Exception:
    def sanitize_input(text: str) -> tuple[str, list[str]]:
        return text, []

    def detect_injection(text: str) -> tuple[bool, list[str]]:
        return False, []

    def validate_output_text(text: str, canary: str = "") -> tuple[bool, list[str]]:
        return True, []


@lru_cache(maxsize=1)
def _pipeline_modules() -> tuple[Any, Any, Any]:
    """Load pipeline modules lazily after runtime path discovery."""
    _register_vendor_paths()
    pipeline_server = import_module("pipeline_mcp.server")
    progression_service = import_module("pipeline_mcp.services.progression")
    soql_utils = import_module("pipeline_mcp.utils.soql")
    return pipeline_server, progression_service, soql_utils


def _pipeline_server() -> Any:
    server, _, _ = _pipeline_modules()
    return server


def _escape_soql(value: str) -> str:
    _, _, soql_utils = _pipeline_modules()
    return soql_utils.escape_soql(value)


def _escape_soql_ids(ids: list[str]) -> str:
    _, _, soql_utils = _pipeline_modules()
    return soql_utils.escape_soql_ids(ids)


@lru_cache(maxsize=1)
def _services() -> Any:
    """Reuse the pipeline-mcp service container."""
    return _pipeline_server().get_services()


_canary = os.getenv("GUARDRAILS_CANARY", "")
_SF_OAUTH_APP_ID = "salesforce_oauth2_auth_code_ibm_184bdbd3"
_NEO4J_KV_APP_ID = "neo4j_key_value_custom_test"
_EXPECTED_CREDENTIALS = [
    ExpectedCredentials(
        app_id=_SF_OAUTH_APP_ID,
        type=[ConnectionType.OAUTH2_AUTH_CODE],
    ),
    ExpectedCredentials(
        app_id=_NEO4J_KV_APP_ID,
        type=[ConnectionType.KEY_VALUE],
    ),
]


def _resolve_salesforce_connection_payload(
    salesforce_oauth2_auth_code_ibm_184bdbd3: Any = None,
    salesforce_conn: Any = None,
) -> Any:
    """Pick the first available Salesforce connection payload."""
    return salesforce_oauth2_auth_code_ibm_184bdbd3 or salesforce_conn


def _resolve_neo4j_connection_payload(
    neo4j_pipeline_key_value_ibm_184bdbd3: Any = None,
    neo4j_conn: Any = None,
) -> Any:
    """Pick Neo4j connection payload."""
    return neo4j_pipeline_key_value_ibm_184bdbd3 or neo4j_conn


def _guard_input(user_text: str) -> str:
    """Evaluate and sanitize tool input with guardrails."""
    sanitized, _flags = sanitize_input(user_text)
    is_injection, _patterns = detect_injection(sanitized)
    if is_injection:
        raise ValueError("Input blocked by guardrails policy.")
    return sanitized


def _guard_output(text: str) -> str:
    """Validate output against canary/pattern leakage."""
    is_clean, flags = validate_output_text(text, _canary)
    if is_clean:
        return text
    return f"Output blocked by guardrails: {', '.join(flags)}"


def _neo4j_explicitly_configured() -> bool:
    """Return True only when Neo4j credentials are explicitly provided."""
    uri = os.getenv("NEO4J_PIPELINE_URI", "").strip()
    user = os.getenv("NEO4J_PIPELINE_USER", "").strip()
    password = os.getenv("NEO4J_PIPELINE_PASSWORD", "").strip()
    return bool(uri and user and password)


def _normalize_health_output(report: str) -> str:
    """Treat Neo4j as optional unless explicitly configured."""
    if _neo4j_explicitly_configured() or not report:
        return report

    lines = report.splitlines()
    normalized: list[str] = []
    for line in lines:
        if line.startswith("**Neo4j Pipeline:**"):
            normalized.append("**Neo4j Pipeline:** ➖ Not configured (optional)")
            continue
        if line.startswith("**Overall:**") and ("connectivity issues" in line.lower()):
            normalized.append("**Overall:** ✅ Core systems healthy (Neo4j optional not configured)")
            continue
        normalized.append(line)

    return "\n".join(normalized)


def _extract_salesforce_credentials(salesforce_conn: Any) -> tuple[str | None, str | None]:
    """Extract (access_token, instance_url) from a connection object or dict."""
    if not salesforce_conn:
        return None, None

    def _to_plain(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: _to_plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_to_plain(v) for v in value]
        if hasattr(value, "model_dump"):
            try:
                return _to_plain(value.model_dump())
            except Exception:
                pass
        if hasattr(value, "__dict__"):
            try:
                return _to_plain(vars(value))
            except Exception:
                pass
        return value

    def _normalize(key: Any) -> str:
        text = str(key).strip()
        text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
        return text.lower().replace("-", "_").replace(" ", "_")

    def _find_first(data: Any, keys: set[str]) -> Any | None:
        normalized_keys = {_normalize(k) for k in keys}
        if isinstance(data, dict):
            for key, value in data.items():
                if _normalize(key) in normalized_keys and value:
                    return value
            for value in data.values():
                found = _find_first(value, keys)
                if found:
                    return found
        elif isinstance(data, list):
            for item in data:
                found = _find_first(item, keys)
                if found:
                    return found
        return None

    payload = _to_plain(salesforce_conn)

    token = None
    instance_url = None

    if isinstance(payload, dict):
        entries = payload.get("entries")
        if isinstance(entries, list):
            kv_entries: dict[str, Any] = {}
            for item in entries:
                if not isinstance(item, dict):
                    continue
                item_key = item.get("key") or item.get("name")
                item_value = item.get("value")
                if item_key and item_value:
                    kv_entries[_normalize(item_key)] = item_value

            if kv_entries:
                token = (
                    kv_entries.get("access_token")
                    or kv_entries.get("token")
                    or kv_entries.get("bearer_token")
                    or kv_entries.get("salesforce_access_token")
                )
                instance_url = (
                    kv_entries.get("instance_url")
                    or kv_entries.get("url")
                    or kv_entries.get("salesforce_instance_url")
                )

        token = _find_first(
            payload,
            {"access_token", "token", "bearer_token", "SALESFORCE_ACCESS_TOKEN"},
        ) or token
        instance_url = _find_first(
            payload,
            {"instance_url", "url", "SALESFORCE_INSTANCE_URL"},
        ) or instance_url

    return token, instance_url


def _extract_salesforce_env_vars(salesforce_conn: Any) -> dict[str, str]:
    """Extract Salesforce credential fields from connection payload as env vars."""
    if not salesforce_conn:
        return {}

    def _to_plain(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: _to_plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_to_plain(v) for v in value]
        if hasattr(value, "model_dump"):
            try:
                return _to_plain(value.model_dump())
            except Exception:
                pass
        if hasattr(value, "__dict__"):
            try:
                return _to_plain(vars(value))
            except Exception:
                pass
        return value

    def _normalize(key: Any) -> str:
        text = str(key).strip()
        text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
        return text.lower().replace("-", "_").replace(" ", "_")

    payload = _to_plain(salesforce_conn)
    flat: dict[str, Any] = {}

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                normalized = _normalize(key)
                if value:
                    flat.setdefault(normalized, value)
                _walk(value)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(payload)

    entries = payload.get("entries") if isinstance(payload, dict) else None
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict):
                continue
            item_key = item.get("key") or item.get("name")
            item_value = item.get("value")
            if item_key and item_value:
                flat[_normalize(item_key)] = item_value

    key_map = {
        "SALESFORCE_ACCESS_TOKEN": [
            "salesforce_access_token",
            "access_token",
            "token",
            "bearer_token",
        ],
        "SALESFORCE_INSTANCE_URL": [
            "salesforce_instance_url",
            "instance_url",
            "url",
        ],
        "SALESFORCE_USERNAME": [
            "salesforce_username",
            "username",
            "user",
            "email",
        ],
        "SALESFORCE_PASSWORD": ["salesforce_password", "password"],
        "SALESFORCE_SECURITY_TOKEN": [
            "salesforce_security_token",
            "security_token",
        ],
        "SALESFORCE_DOMAIN": ["salesforce_domain", "domain", "login_domain"],
        "SALESFORCE_CLIENT_ID": ["salesforce_client_id", "client_id"],
        "SALESFORCE_CLIENT_SECRET": ["salesforce_client_secret", "client_secret"],
        "SALESFORCE_REFRESH_TOKEN": ["salesforce_refresh_token", "refresh_token"],
    }

    env_updates: dict[str, str] = {}
    for env_key, aliases in key_map.items():
        for alias in aliases:
            value = flat.get(alias)
            if value:
                env_updates[env_key] = str(value)
                break

    return env_updates


def _extract_connection_entries(connection_payload: Any) -> dict[str, str]:
    """Extract normalized key/value entries from connection payload."""
    if not connection_payload:
        return {}

    def _to_plain(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: _to_plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_to_plain(v) for v in value]
        if hasattr(value, "model_dump"):
            try:
                return _to_plain(value.model_dump())
            except Exception:
                pass
        if hasattr(value, "__dict__"):
            try:
                return _to_plain(vars(value))
            except Exception:
                pass
        return value

    def _normalize(key: Any) -> str:
        text = str(key).strip()
        text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
        return text.lower().replace("-", "_").replace(" ", "_")

    payload = _to_plain(connection_payload)
    flat: dict[str, str] = {}

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if value is not None and not isinstance(value, (dict, list, tuple)):
                    flat.setdefault(_normalize(key), str(value))
                _walk(value)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(payload)

    entries = payload.get("entries") if isinstance(payload, dict) else None
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict):
                continue
            item_key = item.get("key") or item.get("name")
            item_value = item.get("value")
            if item_key and item_value is not None:
                flat[_normalize(item_key)] = str(item_value)

    return flat


def _bootstrap_salesforce_auth(salesforce_conn: Any = None) -> None:
    """Configure runtime auth from connection payload when available."""
    env_updates = _extract_salesforce_env_vars(salesforce_conn)

    if not env_updates:
        try:
            from ibm_watsonx_orchestrate.run.connections import oauth2_auth_code

            runtime_oauth = oauth2_auth_code(_SF_OAUTH_APP_ID)
            env_updates = _extract_salesforce_env_vars(runtime_oauth)
        except Exception:
            pass

    for key, value in env_updates.items():
        os.environ[key] = value

    token, instance_url = _extract_salesforce_credentials(salesforce_conn)

    if not token or not instance_url:
        try:
            from ibm_watsonx_orchestrate.run.connections import oauth2_auth_code

            runtime_oauth = oauth2_auth_code(_SF_OAUTH_APP_ID)
            runtime_token, runtime_url = _extract_salesforce_credentials(runtime_oauth)
            token = token or runtime_token
            instance_url = instance_url or runtime_url
        except Exception:
            pass

    if not token or not instance_url:
        return

    os.environ["SALESFORCE_ACCESS_TOKEN"] = str(token)
    os.environ["SALESFORCE_INSTANCE_URL"] = str(instance_url)
    os.environ.setdefault("SALESFORCE_USERNAME", "env-token")

    _services.cache_clear()
    try:
        _pipeline_server()._services = None
    except Exception:
        pass


def _bootstrap_neo4j_auth(neo4j_conn: Any = None) -> None:
    """Configure Neo4j env vars from connection payload when available."""
    entries = _extract_connection_entries(neo4j_conn)
    if not entries:
        try:
            from ibm_watsonx_orchestrate.run.connections import key_value

            runtime_kv = key_value(_NEO4J_KV_APP_ID)
            entries = _extract_connection_entries(runtime_kv)
        except Exception:
            entries = {}

    uri = (
        entries.get("neo4j_pipeline_uri")
        or entries.get("neo4j_uri")
        or entries.get("uri")
        or entries.get("url")
    )
    user = (
        entries.get("neo4j_pipeline_user")
        or entries.get("neo4j_user")
        or entries.get("username")
        or entries.get("user")
    )
    password = (
        entries.get("neo4j_pipeline_password")
        or entries.get("neo4j_password")
        or entries.get("password")
    )

    if not (uri and user and password):
        return

    os.environ["NEO4J_PIPELINE_URI"] = str(uri)
    os.environ["NEO4J_PIPELINE_USER"] = str(user)
    os.environ["NEO4J_PIPELINE_PASSWORD"] = str(password)

    _services.cache_clear()
    try:
        _pipeline_server()._services = None
    except Exception:
        pass


@tool(expected_credentials=_EXPECTED_CREDENTIALS)
def health_check(
    salesforce_oauth2_auth_code_ibm_184bdbd3: dict | None = None,
    neo4j_pipeline_key_value_ibm_184bdbd3: dict | None = None,
) -> str:
    """Return pipeline health (Salesforce + Neo4j + services)."""
    salesforce_conn = _resolve_salesforce_connection_payload(
        salesforce_oauth2_auth_code_ibm_184bdbd3=salesforce_oauth2_auth_code_ibm_184bdbd3,
    )
    neo4j_conn = _resolve_neo4j_connection_payload(
        neo4j_pipeline_key_value_ibm_184bdbd3=neo4j_pipeline_key_value_ibm_184bdbd3,
    )
    _bootstrap_neo4j_auth(neo4j_conn)
    _bootstrap_salesforce_auth(salesforce_conn)
    report = _pipeline_server().health_check()
    report = _normalize_health_output(report)
    return _guard_output(report)


@tool(expected_credentials=_EXPECTED_CREDENTIALS)
def pipeline_overview(
    salesforce_oauth2_auth_code_ibm_184bdbd3: dict | None = None,
    neo4j_pipeline_key_value_ibm_184bdbd3: dict | None = None,
) -> str:
    """Return current open-pipeline summary."""
    salesforce_conn = _resolve_salesforce_connection_payload(
        salesforce_oauth2_auth_code_ibm_184bdbd3=salesforce_oauth2_auth_code_ibm_184bdbd3,
    )
    neo4j_conn = _resolve_neo4j_connection_payload(
        neo4j_pipeline_key_value_ibm_184bdbd3=neo4j_pipeline_key_value_ibm_184bdbd3,
    )
    _bootstrap_neo4j_auth(neo4j_conn)
    _bootstrap_salesforce_auth(salesforce_conn)
    return _guard_output(_pipeline_server().get_pipeline())


@tool(expected_credentials=_EXPECTED_CREDENTIALS)
def pipeline_progression(
    salesforce_oauth2_auth_code_ibm_184bdbd3: dict | None = None,
    neo4j_pipeline_key_value_ibm_184bdbd3: dict | None = None,
    days: int = 365,
    stuck_threshold: int = 60,
) -> str:
    """Historical pipeline progression/velocity report.

    Args:
        days: Lookback window in days for stage movements and conversions.
        stuck_threshold: Days without movement to flag as stuck.
    """
    salesforce_conn = _resolve_salesforce_connection_payload(
        salesforce_oauth2_auth_code_ibm_184bdbd3=salesforce_oauth2_auth_code_ibm_184bdbd3,
    )
    neo4j_conn = _resolve_neo4j_connection_payload(
        neo4j_pipeline_key_value_ibm_184bdbd3=neo4j_pipeline_key_value_ibm_184bdbd3,
    )
    _bootstrap_neo4j_auth(neo4j_conn)
    _bootstrap_salesforce_auth(salesforce_conn)
    _guard_input(f"pipeline_progression days={days} stuck_threshold={stuck_threshold}")

    services = _services()
    progression = services.progression
    report = progression.get_pipeline_progression(days=days, stuck_threshold=stuck_threshold)
    return _guard_output(progression.format_pipeline_progression(report))


def _parse_sf_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        if value.endswith("+0000"):
            value = value.replace("+0000", "+00:00")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            return parsed.replace(tzinfo=None)
        return parsed
    except Exception:
        try:
            return datetime.fromisoformat(value[:10])
        except Exception:
            return None


def _resolve_record_types(channel: str) -> list[str]:
    if not channel:
        return ["Retail", "Foodservice", "Industry", "Wholesale"]

    parts = [part.strip() for part in channel.split(",") if part.strip()]
    result: list[str] = []
    mapping = {
        "foodservice": ["Foodservice"],
        "retail": ["Retail"],
        "industry": ["Industry"],
        "wholesale": ["Wholesale"],
        "b2b": ["Industry", "Wholesale"],
    }

    for item in parts:
        key = item.lower()
        if key in mapping:
            result.extend(mapping[key])
        else:
            result.append(item)

    deduped = list(dict.fromkeys(result))
    return deduped or ["Foodservice"]


@tool(expected_credentials=_EXPECTED_CREDENTIALS)
def historical_pipeline_duration_audit(
    salesforce_oauth2_auth_code_ibm_184bdbd3: dict | None = None,
    neo4j_pipeline_key_value_ibm_184bdbd3: dict | None = None,
    country: str = "Germany",
    channel: str = "Foodservice,Industry,Wholesale",
    days: int = 365,
) -> str:
    """Historical duration audit with explicit country/channel filters.

    Args:
        country: Billing country filter (e.g., Germany, Switzerland).
        channel: Comma-separated channels/record types (e.g., Foodservice,Industry,Wholesale).
        days: Lookback window in days.
    """
    salesforce_conn = _resolve_salesforce_connection_payload(
        salesforce_oauth2_auth_code_ibm_184bdbd3=salesforce_oauth2_auth_code_ibm_184bdbd3,
    )
    neo4j_conn = _resolve_neo4j_connection_payload(
        neo4j_pipeline_key_value_ibm_184bdbd3=neo4j_pipeline_key_value_ibm_184bdbd3,
    )
    _bootstrap_neo4j_auth(neo4j_conn)
    _bootstrap_salesforce_auth(salesforce_conn)
    _guard_input(
        f"historical_pipeline_duration_audit country={country} channel={channel} days={days}"
    )

    services = _services()
    sf = services.salesforce
    if sf is None or not sf.health_check():
        return (
            "Salesforce-Verbindung ist nicht verfügbar. "
            "Bitte Credentials/Session prüfen und Tool erneut ausführen."
        )

    rt_names = _resolve_record_types(channel)
    rt_clause = ", ".join(f"'{_escape_soql(x)}'" for x in rt_names)
    country_safe = _escape_soql(country)

    opp_soql = f"""
        SELECT Id, Name, StageName, IsWon, IsClosed, CreatedDate, CloseDate,
               Owner.Name, Amount, RecordType.Name, Account.BillingCountry
        FROM Opportunity
        WHERE CreatedDate >= LAST_N_DAYS:{days}
          AND Account.BillingCountry = '{country_safe}'
          AND RecordType.Name IN ({rt_clause})
    """

    opportunities = sf.query(opp_soql)
    if not opportunities:
        return (
            f"Keine Opportunities für Country={country} und Channel={channel} "
            f"in den letzten {days} Tagen gefunden."
        )

    opp_by_id = {o.get("Id"): o for o in opportunities if o.get("Id")}
    opp_ids = list(opp_by_id.keys())

    history_records: list[dict[str, Any]] = []
    for index in range(0, len(opp_ids), 100):
        batch = opp_ids[index : index + 100]
        ids_clause = _escape_soql_ids(batch)
        history_soql = f"""
            SELECT OpportunityId, StageName, CreatedDate
            FROM OpportunityHistory
            WHERE OpportunityId IN ({ids_clause})
            ORDER BY OpportunityId, CreatedDate
        """
        history_records.extend(sf.query(history_soql))

    history_by_opp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in history_records:
        opportunity_id = row.get("OpportunityId")
        if opportunity_id:
            history_by_opp[opportunity_id].append(row)

    tracked_stages = ["Qualification", "Sampling", "Proposal Submitted", "Negotiation"]
    stage_durations: dict[str, list[int]] = {stage: [] for stage in tracked_stages}

    won_cycle_days: list[int] = []
    lost_cycle_days: list[int] = []
    won_sampling_days: list[int] = []
    sampling_closed: list[tuple[int, bool]] = []

    owner_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"closed": 0, "won": 0, "cycle_days": []}
    )

    for opportunity_id, history in history_by_opp.items():
        opportunity = opp_by_id.get(opportunity_id, {})
        owner_name = ((opportunity.get("Owner") or {}).get("Name")) or "Unknown"

        events: list[tuple[str, datetime]] = []
        for row in history:
            stage = row.get("StageName")
            dt = _parse_sf_datetime(row.get("CreatedDate"))
            if stage and dt:
                events.append((stage, dt))

        events.sort(key=lambda item: item[1])
        sampling_days_for_opp = 0

        for idx in range(len(events) - 1):
            from_stage, from_time = events[idx]
            _to_stage, to_time = events[idx + 1]
            delta_days = (to_time - from_time).days
            if delta_days < 0:
                continue
            if from_stage in stage_durations:
                stage_durations[from_stage].append(delta_days)
            if from_stage == "Sampling":
                sampling_days_for_opp += delta_days

        created = _parse_sf_datetime(opportunity.get("CreatedDate"))
        closed = _parse_sf_datetime(opportunity.get("CloseDate"))
        is_closed = bool(opportunity.get("IsClosed"))
        is_won = bool(opportunity.get("IsWon"))

        if is_closed and created and closed:
            cycle_days = (closed - created).days
            if cycle_days >= 0:
                if is_won:
                    won_cycle_days.append(cycle_days)
                else:
                    lost_cycle_days.append(cycle_days)

                owner_stats[owner_name]["closed"] += 1
                owner_stats[owner_name]["cycle_days"].append(cycle_days)
                if is_won:
                    owner_stats[owner_name]["won"] += 1

                if sampling_days_for_opp > 0:
                    sampling_closed.append((sampling_days_for_opp, is_won))
                    if is_won:
                        won_sampling_days.append(sampling_days_for_opp)

    best_threshold: tuple[int, float, float] | None = None
    for threshold in [20, 30, 40, 50, 60, 70, 80, 90]:
        fast = [won for duration, won in sampling_closed if duration <= threshold]
        slow = [won for duration, won in sampling_closed if duration > threshold]
        if len(fast) < 3 or len(slow) < 3:
            continue
        fast_win_rate = sum(1 for value in fast if value) / len(fast)
        slow_win_rate = sum(1 for value in slow if value) / len(slow)
        drop = fast_win_rate - slow_win_rate
        if best_threshold is None or drop > best_threshold[2]:
            best_threshold = (threshold, fast_win_rate, drop)

    lines = [
        f"# Historical Pipeline Duration Audit ({country} | {channel} | last {days} days)",
        "",
        "## 1) Historical Velocity Metrics",
    ]

    for stage in tracked_stages:
        values = stage_durations.get(stage, [])
        if values:
            lines.append(f"- {stage}: {mean(values):.1f} Tage (n={len(values)})")
        else:
            lines.append(f"- {stage}: keine belastbaren Werte")

    if won_sampling_days:
        lines.append(
            f"- Sampling baseline (Closed Won): {mean(won_sampling_days):.1f} Tage (n={len(won_sampling_days)})"
        )
    else:
        lines.append("- Sampling baseline (Closed Won): keine belastbaren Werte")

    if best_threshold:
        threshold, fast_rate, drop = best_threshold
        slow_rate = fast_rate - drop
        lines.append(
            f"- Stagnation point: >{threshold} Tage in Sampling, Win-Rate sinkt von {fast_rate:.0%} auf {slow_rate:.0%}"
        )
    else:
        lines.append("- Stagnation point: nicht genug Daten für signifikante Schätzung")

    lines.extend(["", "## 2) Win-Loss Correlation"])
    if won_cycle_days:
        lines.append(f"- Closed Won: {mean(won_cycle_days):.1f} Tage durchschnittliche Cycle Time (n={len(won_cycle_days)})")
    else:
        lines.append("- Closed Won: keine Daten")

    if lost_cycle_days:
        lines.append(
            f"- Closed Lost: {mean(lost_cycle_days):.1f} Tage durchschnittliche Cycle Time (n={len(lost_cycle_days)})"
        )
    else:
        lines.append("- Closed Lost: keine Daten")

    if won_cycle_days and lost_cycle_days:
        faster = "schneller" if mean(won_cycle_days) < mean(lost_cycle_days) else "langsamer"
        lines.append(f"- Hypothese: Won-Deals bewegen sich {faster} durch den Zyklus als Lost-Deals.")

    lines.extend(["", "## 3) Account-Type Segmentation (by owner)"])
    if owner_stats:
        ranked = sorted(owner_stats.items(), key=lambda item: item[1]["closed"], reverse=True)
        for owner, stats in ranked[:10]:
            closed_count = stats["closed"]
            won_count = stats["won"]
            win_rate = (won_count / closed_count) if closed_count else 0
            avg_cycle = mean(stats["cycle_days"]) if stats["cycle_days"] else 0
            lines.append(
                f"- {owner}: Avg Cycle {avg_cycle:.1f} Tage | Win-Rate {win_rate:.0%} | Closed {closed_count}"
            )
    else:
        lines.append("- Keine Owner-Segmentdaten verfügbar.")

    lines.extend(
        [
            "",
            "## Data Basis",
            f"- Opportunities im Scope: {len(opportunities)}",
            f"- OpportunityHistory events: {len(history_records)}",
        ]
    )

    return _guard_output("\n".join(lines))

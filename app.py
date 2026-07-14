"""Streamlit dashboard for the Binance USDT-M Futures Testnet bot."""

from __future__ import annotations

import re
import time
import hmac
from collections import deque
from collections.abc import Mapping
from dataclasses import asdict
from decimal import ROUND_CEILING, Decimal

import streamlit as st

from bot.client import (
    BinanceAuthenticationError,
    BinanceFuturesClient,
    BinanceFuturesClientError,
    BinanceNetworkError,
    BinanceServiceError,
    BinanceSymbolNotFoundError,
    ConnectionCheckResult,
    MissingCredentialsError,
    check_binance_connection,
    create_binance_client,
    get_futures_market_price,
)
from bot.dashboard import FuturesDashboardService
from bot.logging_config import LOG_FILE, configure_logging, safe_log_value
from bot.orders import OrderResult, OrderServiceError, place_futures_order
from bot.validators import (
    OrderValidationError,
    QuantityRules,
    ValidatedOrderInput,
    build_quantity_rules,
    format_decimal,
    validate_order_input,
    validate_quantity_rules,
    validate_symbol,
)


PAGE_TITLE = "Binance Futures Testnet Trading Dashboard"
DUPLICATE_GUARD_SECONDS = 10
CURATED_TRADING_SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "SUIUSDT",
    "AVAXUSDT",
    "LINKUSDT",
)
logger = configure_logging()

st.set_page_config(
    page_title=PAGE_TITLE,
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


def streamlit_secret(name: str) -> str | None:
    """Return one non-empty Streamlit secret without displaying or logging it."""
    try:
        value = st.secrets.get(name)
    except Exception:
        return None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def apply_dashboard_style() -> None:
    """Apply restrained dark trading-dashboard styling."""
    st.markdown(
        """
        <style>
        .stApp { background: #07111f; color: #e5edf7; }
        [data-testid="stSidebar"] { background: #0b1728; }
        [data-testid="stMetric"] {
            background: #0d1c30;
            border: 1px solid #20334d;
            border-radius: 12px;
            padding: 14px;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background: #0b1728;
            border-color: #20334d;
            border-radius: 12px;
        }
        .testnet-banner {
            background: #33240a;
            border: 1px solid #8b6418;
            border-radius: 10px;
            color: #ffd56a;
            padding: 12px 16px;
            margin-bottom: 18px;
        }
        .block-container { padding-top: 2rem; padding-bottom: 2rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_resource
def get_client() -> BinanceFuturesClient:
    """Prefer Cloud secrets, then fall back to local environment configuration."""
    return create_binance_client(
        api_key=streamlit_secret("BINANCE_API_KEY"),
        api_secret=streamlit_secret("BINANCE_API_SECRET"),
        base_url=streamlit_secret("BINANCE_BASE_URL"),
    )


def get_dashboard_service() -> FuturesDashboardService:
    """Create a current service wrapper around the cached Binance client."""
    return FuturesDashboardService(get_client())


@st.cache_data(ttl=10, show_spinner=False)
def load_market_price(symbol: str) -> str:
    return get_futures_market_price(symbol, get_client())


@st.cache_data(ttl=300, show_spinner=False)
def load_exchange_info() -> dict[str, object]:
    """Cache public exchange information shared by symbols and quantity rules."""
    return get_client().get_futures_exchange_info()


@st.cache_data(ttl=300, show_spinner=False)
def load_trading_symbols() -> tuple[tuple[str, ...], bool]:
    """Return verified active curated symbols, with a safe offline fallback."""
    try:
        exchange_info = load_exchange_info()
        raw_symbols = exchange_info.get("symbols", [])
        active_symbols = {
            str(item["symbol"])
            for item in raw_symbols
            if isinstance(item, dict)
            and item.get("status") == "TRADING"
            and item.get("quoteAsset") == "USDT"
            and item.get("symbol")
        }
        symbols = tuple(
            symbol for symbol in CURATED_TRADING_SYMBOLS if symbol in active_symbols
        )
        if symbols:
            return symbols, False
    except Exception:
        pass
    return CURATED_TRADING_SYMBOLS, True


@st.cache_data(ttl=300, show_spinner=False)
def load_symbol_info(symbol: str) -> dict[str, object]:
    """Return cached exchange filters for the selected symbol."""
    for item in load_exchange_info().get("symbols", []):
        if isinstance(item, dict) and item.get("symbol") == symbol:
            return item
    raise ValueError(f"Trading filters are unavailable for {symbol}.")


@st.cache_data(ttl=15, show_spinner=False)
def load_account_summary() -> dict[str, object]:
    return asdict(get_dashboard_service().get_account_summary())


@st.cache_data(ttl=15, show_spinner=False)
def load_open_orders(symbol: str) -> list[dict[str, object]]:
    return [asdict(record) for record in get_dashboard_service().get_open_orders(symbol)]


@st.cache_data(ttl=15, show_spinner=False)
def load_positions() -> list[dict[str, object]]:
    return [asdict(record) for record in get_dashboard_service().get_positions()]


@st.cache_data(ttl=15, show_spinner=False)
def load_recent_orders(symbol: str) -> list[dict[str, object]]:
    return [
        asdict(record) for record in get_dashboard_service().get_recent_orders(symbol)
    ]


def initialise_state() -> None:
    """Create only non-sensitive dashboard session values."""
    defaults = {
        "connection_result": None,
        "connection_error": None,
        "order_result": None,
        "ui_message": None,
        "last_submission_fingerprint": None,
        "last_submission_at": 0.0,
        "authenticated": False,
        "login_error": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def connected() -> bool:
    result: ConnectionCheckResult | None = st.session_state.connection_result
    return result is not None and result.success


def credential_status() -> tuple[bool, str | None]:
    """Report credential readiness without returning or exposing credential values."""
    try:
        client = get_client()
    except BinanceFuturesClientError as exc:
        return False, str(exc)
    except Exception:
        return False, "The Binance Testnet client could not be initialized."
    ready = client.api_key_configured and client.api_secret_configured
    if ready:
        return True, None
    return False, "Binance Futures Testnet API credentials are not configured."


def render_credential_setup(message: str | None = None) -> None:
    """Explain safe local and Cloud credential setup without showing values."""
    st.warning(message or "Binance Futures Testnet credentials are required.")
    st.markdown(
        """
        Configure both `BINANCE_API_KEY` and `BINANCE_API_SECRET` using one method:

        - **Local:** copy `.env.example` to `.env` and add Testnet credentials.
        - **Streamlit Community Cloud:** add the keys in the app's **Secrets** settings.

        Keep `BINANCE_BASE_URL` set to `https://testnet.binancefuture.com`.
        Trading and authenticated account controls remain disabled until setup is
        complete.
        """
    )


def handle_login() -> None:
    """Validate the password before rerendering and clear the entered value."""
    configured_password = streamlit_secret("APP_PASSWORD")
    password_attempt = str(st.session_state.get("password_attempt", ""))
    authenticated = bool(configured_password) and hmac.compare_digest(
        password_attempt, configured_password
    )
    st.session_state.authenticated = authenticated
    st.session_state.login_error = not authenticated
    st.session_state.password_attempt = ""


def handle_logout() -> None:
    """Clear authenticated and account-related session state."""
    st.session_state.authenticated = False
    st.session_state.connection_result = None
    st.session_state.connection_error = None
    st.session_state.order_result = None
    st.session_state.ui_message = None
    st.session_state.password_attempt = ""


def run_connection_check() -> None:
    """Update session state with a safe, structured connection result."""
    try:
        result = check_binance_connection(get_client())
        st.session_state.connection_result = result
        st.session_state.connection_error = None
        if result.success:
            st.session_state.ui_message = (
                "success",
                "Public and authenticated Futures Testnet connections succeeded.",
            )
        else:
            failed = []
            if not result.public.ok:
                failed.append(result.public.error_message or "Public check failed.")
            if not result.authenticated.ok:
                failed.append(
                    result.authenticated.error_message
                    or "Authenticated check failed."
                )
            st.session_state.ui_message = ("error", " ".join(failed))
    except BinanceFuturesClientError as exc:
        st.session_state.connection_result = None
        st.session_state.connection_error = str(exc)
        st.session_state.ui_message = ("error", str(exc))
    except Exception as exc:
        logger.error(
            "GUI_CONNECTION_FAILED error_type=%s", safe_log_value(type(exc).__name__)
        )
        message = "Connection check failed due to an unexpected error."
        st.session_state.connection_result = None
        st.session_state.connection_error = message
        st.session_state.ui_message = ("error", message)


def local_order_validation(
    *, symbol: str, side: str, order_type: str, quantity: str, price: str | None
) -> tuple[ValidatedOrderInput | None, str | None]:
    """Validate form values without making a Binance request."""
    try:
        return (
            validate_order_input(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
            ),
            None,
        )
    except OrderValidationError as exc:
        return None, str(exc)


def submission_fingerprint(order: ValidatedOrderInput) -> tuple[str, ...]:
    """Build a non-sensitive signature for short-window duplicate protection."""
    return (
        order.symbol,
        order.side,
        order.order_type,
        format_decimal(order.quantity),
        format_decimal(order.price) if order.price is not None else "",
    )


def submit_order(
    order: ValidatedOrderInput,
    confirmed: bool,
    quantity_rules: QuantityRules | None = None,
) -> None:
    """Enforce GUI safety gates, then delegate order placement to the backend."""
    st.session_state.order_result = None
    if not confirmed:
        st.session_state.ui_message = (
            "warning",
            "Confirm that you reviewed this Futures Testnet order before submitting.",
        )
        return
    if not connected():
        st.session_state.ui_message = (
            "warning",
            "Run a successful public and authenticated connection check first.",
        )
        return

    fingerprint = submission_fingerprint(order)
    now = time.monotonic()
    if (
        fingerprint == st.session_state.last_submission_fingerprint
        and now - st.session_state.last_submission_at < DUPLICATE_GUARD_SECONDS
    ):
        st.session_state.ui_message = (
            "warning",
            "Duplicate submission blocked. Wait a few seconds before retrying.",
        )
        return

    st.session_state.last_submission_fingerprint = fingerprint
    st.session_state.last_submission_at = now
    try:
        st.session_state.order_result = place_futures_order(
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            quantity=order.quantity,
            price=order.price,
            client=get_client(),
        )
        st.session_state.ui_message = (
            "success",
            "Futures Testnet order submitted successfully.",
        )
    except (OrderValidationError, BinanceFuturesClientError, OrderServiceError) as exc:
        message = str(exc)
        if (
            "minimum notional" in message.lower()
            and quantity_rules is not None
            and quantity_rules.estimated_minimum_quantity is not None
        ):
            message = (
                "Quantity must be at least "
                f"{display_decimal(quantity_rules.estimated_minimum_quantity)} "
                "at the current order price to meet the minimum order value."
            )
        st.session_state.ui_message = ("error", message)
    except Exception as exc:
        logger.error("GUI_ORDER_FAILED error_type=%s", type(exc).__name__)
        st.session_state.ui_message = (
            "error",
            "Order submission failed due to an unexpected error.",
        )


def render_connection_indicator() -> None:
    result: ConnectionCheckResult | None = st.session_state.connection_result
    if result is None:
        if st.session_state.connection_error:
            st.error("Connection unavailable")
        else:
            st.info("Connection not checked")
    elif result.success:
        st.success("Testnet connected")
    elif result.public.ok:
        st.warning("Public API only")
    else:
        st.error("Testnet unavailable")


def render_feedback() -> None:
    message = st.session_state.ui_message
    if message:
        level, text = message
        getattr(st, level)(text)


def render_order_summary(order: ValidatedOrderInput | None, error: str | None) -> None:
    st.subheader("Final order summary")
    if error:
        st.warning(error)
        return
    if order is None:
        st.info("Complete the order form to see a validated summary.")
        return
    rows = {
        "Environment": "Binance Futures Testnet",
        "Symbol": order.symbol,
        "Side": order.side,
        "Order type": order.order_type,
        "Quantity": format_decimal(order.quantity),
        "Price": (
            format_decimal(order.price) if order.price is not None else "Market price"
        ),
    }
    st.table({"Field": list(rows.keys()), "Value": list(rows.values())})


def display_decimal(value: Decimal | None) -> str:
    """Format guidance values compactly without float conversion."""
    if value is None:
        return "Unavailable"
    text = format_decimal(value)
    return text.rstrip("0").rstrip(".") if "." in text else text


def render_quantity_guidance(
    rules: QuantityRules | None, order_type: str
) -> None:
    """Show the active Binance quantity filter and estimated valid minimum."""
    if rules is None:
        st.caption("Quantity guidance is temporarily unavailable.")
        return
    minimum_notional = (
        f"{display_decimal(rules.minimum_notional)} USDT"
        if rules.minimum_notional is not None
        else "Unavailable"
    )
    estimated = (
        display_decimal(rules.estimated_minimum_quantity)
        if rules.reference_price is not None
        else "Enter a valid limit price"
        if order_type == "LIMIT"
        else "Current mark price unavailable"
    )
    st.caption(f"Quantity filter: {rules.filter_name}")
    st.markdown(
        "  \n".join(
            (
                f"Minimum quantity: **{display_decimal(rules.minimum_quantity)}**",
                f"Quantity step: **{display_decimal(rules.step_size)}**",
                f"Minimum order value: **{minimum_notional}**",
                f"Estimated minimum quantity at this price: **{estimated}**",
            )
        )
    )


def render_quantity_input(
    rules: QuantityRules | None,
    *,
    symbol: str,
    order_type: str,
    disabled: bool,
) -> str:
    """Use Binance min/step controls when they can be represented safely."""
    if (
        rules is not None
        and rules.minimum_quantity is not None
        and rules.step_size is not None
    ):
        minimum = rules.minimum_quantity
        step = rules.step_size
        preferred = max(Decimal("0.002"), minimum)
        default = (preferred / step).to_integral_value(rounding=ROUND_CEILING) * step
        if rules.maximum_quantity is not None:
            default = min(default, rules.maximum_quantity)
        decimal_places = max(0, -step.normalize().as_tuple().exponent)
        value = st.number_input(
            "Quantity",
            min_value=float(minimum),
            max_value=(
                float(rules.maximum_quantity)
                if rules.maximum_quantity is not None
                else None
            ),
            value=float(default),
            step=float(step),
            format=f"%.{decimal_places}f",
            disabled=disabled,
            key=f"quantity_{symbol}_{order_type}",
            help="The minimum and step come from the active Binance quantity filter.",
        )
        return format_decimal(Decimal(str(value)))
    return st.text_input(
        "Quantity",
        value="0.002",
        disabled=disabled,
        help="Enter an exact Decimal value aligned to the displayed step size.",
        key=f"quantity_text_{symbol}_{order_type}",
    )


def render_order_result(result: OrderResult) -> None:
    labels = {
        "order_id": "Order ID",
        "symbol": "Symbol",
        "side": "Side",
        "order_type": "Type",
        "status": "Status",
        "original_quantity": "Quantity",
        "executed_quantity": "Executed quantity",
        "price": "Price",
        "average_price": "Average price",
    }
    values = asdict(result)
    st.subheader("Latest order result")
    st.dataframe(
        {
            "Field": list(labels.values()),
            "Value": [values[name] or "N/A" for name in labels],
        },
        hide_index=True,
        width="stretch",
    )


def render_records(records: list[object], columns: dict[str, str]) -> None:
    """Render allow-listed dataclass fields using readable column labels."""
    rows = []
    for record in records:
        values = dict(record) if isinstance(record, Mapping) else asdict(record)
        rows.append({label: values.get(field, "N/A") for field, label in columns.items()})
    st.dataframe(rows, hide_index=True, width="stretch")


def safe_exception_message(exc: Exception) -> str:
    """Return a bounded diagnostic message with common secret forms redacted."""
    message = safe_log_value(str(exc) or type(exc).__name__)
    message = re.sub(
        r"(?i)(api[_-]?key|api[_-]?secret|secret|signature)(\s*[=:]\s*)(\S+)",
        r"\1\2[REDACTED]",
        message,
    )
    return re.sub(r"(?i)(signature|apiKey)=[^&\s]+", r"\1=[REDACTED]", message)


def exception_chain_contains(exc: Exception, type_name: str) -> bool:
    """Inspect exception types without exposing nested exception text."""
    current: BaseException | None = exc
    while current is not None:
        if type_name.casefold() in type(current).__name__.casefold():
            return True
        current = current.__cause__ or current.__context__
    return False


def render_section_error(section: str, exc: Exception) -> None:
    """Render an actionable safe error while preserving diagnostics in the log."""
    safe_detail = safe_exception_message(exc)
    logger.error(
        "GUI_SECTION_FAILED section=%s error_type=%s safe_message=%s",
        safe_log_value(section),
        safe_log_value(type(exc).__name__),
        safe_detail,
        exc_info=(type(exc), RuntimeError(safe_detail), exc.__traceback__),
    )

    if isinstance(exc, MissingCredentialsError):
        message = "API credentials are missing. Configure Testnet credentials and retry."
    elif isinstance(exc, BinanceAuthenticationError):
        message = "Authentication failed. Check the Binance Testnet API credentials."
    elif isinstance(exc, (BinanceSymbolNotFoundError, OrderValidationError)):
        message = "The selected symbol is invalid or unavailable on Binance Testnet."
    elif exception_chain_contains(exc, "timeout"):
        message = "The Binance Testnet request timed out. Please refresh and retry."
    elif isinstance(exc, BinanceNetworkError):
        message = "Binance Testnet connection failed. Check the network and retry."
    elif isinstance(exc, BinanceServiceError):
        message = safe_detail
    elif isinstance(exc, BinanceFuturesClientError):
        message = safe_detail
    else:
        message = f"{section} could not be loaded. Please refresh and retry."
    st.error(message)
    with st.expander("Technical details"):
        st.code(safe_detail, language="text")


def render_data_access_status(credentials_ready: bool) -> bool:
    """Explain why authenticated tab data cannot currently be requested."""
    if not credentials_ready:
        st.info("API credentials are missing. Configure Testnet credentials to continue.")
        return False
    if connected():
        return True

    result: ConnectionCheckResult | None = st.session_state.connection_result
    connection_error = st.session_state.connection_error
    if result is None and not connection_error:
        st.info("Run the Testnet connection check to load authenticated account data.")
        return False

    details = []
    if connection_error:
        details.append(safe_exception_message(RuntimeError(connection_error)))
    if result is not None:
        for status in (result.public, result.authenticated):
            if not status.ok and status.error_message:
                details.append(safe_exception_message(RuntimeError(status.error_message)))
    authentication_failed = bool(
        result is not None
        and not result.authenticated.ok
        and result.authenticated.error_type == "BinanceAuthenticationError"
    )
    if authentication_failed:
        st.error("Authentication failed. Check the Binance Testnet API credentials.")
    else:
        st.error("Binance Testnet connection failed. Check the connection and credentials.")
    if details:
        with st.expander("Technical details"):
            st.code("\n".join(dict.fromkeys(details)), language="text")
    return False


def read_recent_log_lines(maximum_lines: int = 80) -> list[str]:
    """Read a bounded, defensively redacted tail of the application log."""
    if not LOG_FILE.exists():
        return []
    with LOG_FILE.open("r", encoding="utf-8", errors="replace") as log_file:
        lines = list(deque(log_file, maxlen=maximum_lines))
    pattern = re.compile(
        r"(?i)(api[_-]?key|api[_-]?secret|secret|signature)(\s*[=:]\s*)(\S+)"
    )
    return [pattern.sub(r"\1\2[REDACTED]", line.rstrip()) for line in lines]


apply_dashboard_style()
initialise_state()

app_password = streamlit_secret("APP_PASSWORD")
if app_password:
    with st.sidebar:
        st.subheader("Secure access")
        if st.session_state.authenticated:
            st.success("Authenticated")
            st.button("Log out", width="stretch", on_click=handle_logout)
        else:
            st.text_input(
                "Dashboard password", type="password", key="password_attempt"
            )
            st.button(
                "Log in",
                type="primary",
                width="stretch",
                on_click=handle_login,
            )
            if st.session_state.login_error:
                st.error("Incorrect password.")

if app_password and not st.session_state.authenticated:
    st.title(PAGE_TITLE)
    st.markdown(
        '<div class="testnet-banner"><strong>TESTNET ONLY</strong> — Secure '
        "dashboard access is required.</div>",
        unsafe_allow_html=True,
    )
    st.info("Enter the deployment password in the sidebar to continue.")
    st.stop()

credentials_ready, credential_error = credential_status()

with st.sidebar:
    st.title("Dashboard controls")
    st.caption("Binance USDT-M Futures Testnet")
    if st.button("Check connection", width="stretch"):
        with st.spinner("Checking Futures Testnet..."):
            run_connection_check()
    render_connection_indicator()
    st.divider()
    trading_symbols, using_symbol_fallback = load_trading_symbols()
    default_symbol_index = (
        trading_symbols.index("BTCUSDT") if "BTCUSDT" in trading_symbols else 0
    )
    symbol = st.selectbox(
        "Trading symbol",
        trading_symbols,
        index=default_symbol_index,
        on_change=load_market_price.clear,
    )
    if using_symbol_fallback:
        st.caption(
            "Using the curated fallback symbol list because live Testnet verification "
            "is unavailable."
        )
    else:
        st.caption("Verified active curated USDT-M Futures Testnet symbols.")
    if not credentials_ready:
        st.divider()
        st.warning("Trading controls disabled: credentials are missing.")
    st.divider()
    st.caption("Read-only account data is cached briefly and can be refreshed below.")

st.title(PAGE_TITLE)
st.markdown(
    '<div class="testnet-banner"><strong>TESTNET ONLY</strong> — This dashboard '
    "is locked to Binance USDT-M Futures Testnet and never uses real funds.</div>",
    unsafe_allow_html=True,
)
if not credentials_ready:
    render_credential_setup(credential_error)

connection = st.session_state.connection_result
connection_label = (
    "Connected"
    if connection is not None and connection.success
    else "Public only"
    if connection is not None and connection.public.ok
    else "Not checked"
    if connection is None and not st.session_state.connection_error
    else "Unavailable"
)

market_price = "Unavailable"
market_price_error = None
if connection is not None and connection.public.ok:
    try:
        market_price = load_market_price(validate_symbol(symbol))
    except (OrderValidationError, BinanceFuturesClientError) as exc:
        market_price_error = str(exc)
    except Exception:
        market_price_error = "Market price is temporarily unavailable."

account_summary = None
account_summary_error = None
if connected():
    try:
        account_summary = load_account_summary()
    except Exception as exc:
        account_summary_error = exc

card_connection, card_price, card_balance, card_positions = st.columns(4)
card_connection.metric("Testnet connection", connection_label)
card_price.metric(f"{symbol or 'Symbol'} mark price", market_price)
card_balance.metric(
    "Available USDT",
    account_summary.get("available_usdt_balance", "Unavailable")
    if account_summary
    else "Unavailable",
)
card_positions.metric(
    "Open positions",
    account_summary.get("open_position_count", "Unavailable")
    if account_summary
    else "Unavailable",
)

render_feedback()
if market_price_error:
    st.warning(market_price_error)
if account_summary_error:
    render_section_error("Account summary", account_summary_error)

place_tab, open_tab, positions_tab, recent_tab, logs_tab, project_tab = st.tabs(
    (
        "Place Order",
        "Open Orders",
        "Positions",
        "Recent Orders",
        "Application Logs",
        "Project Information",
    )
)

with place_tab:
    st.subheader("Place a Futures Testnet order")
    st.warning("TESTNET ONLY — Review every field before submitting.")
    input_left, input_right = st.columns(2, gap="large")
    with input_left:
        side = st.selectbox("Side", ("BUY", "SELL"), disabled=not credentials_ready)
        order_type = st.selectbox(
            "Order type", ("MARKET", "LIMIT"), disabled=not credentials_ready
        )
    with input_right:
        price = (
            st.text_input(
                "Limit price", value="", disabled=not credentials_ready
            )
            if order_type == "LIMIT"
            else None
        )
        quantity_rules = None
        try:
            symbol_info = load_symbol_info(symbol)
            reference_price = price
            if order_type == "MARKET":
                try:
                    reference_price = load_market_price(symbol)
                except Exception:
                    reference_price = None
            try:
                quantity_rules = build_quantity_rules(
                    symbol_info=symbol_info,
                    order_type=order_type,
                    reference_price=reference_price,
                )
            except OrderValidationError:
                quantity_rules = build_quantity_rules(
                    symbol_info=symbol_info,
                    order_type=order_type,
                )
        except Exception:
            quantity_rules = None
        quantity = render_quantity_input(
            quantity_rules,
            symbol=symbol,
            order_type=order_type,
            disabled=not credentials_ready,
        )
        render_quantity_guidance(quantity_rules, order_type)
    confirmed = st.checkbox(
        "I reviewed and confirm this TESTNET order",
        help="No order is sent until this confirmation is selected.",
        disabled=not credentials_ready,
    )
    validated_order, validation_error = local_order_validation(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        price=price,
    )
    if validated_order is not None and quantity_rules is not None:
        try:
            validate_quantity_rules(validated_order.quantity, quantity_rules)
        except OrderValidationError as exc:
            validated_order = None
            validation_error = str(exc)
    summary_column, result_column = st.columns((1, 1.2), gap="large")
    with summary_column:
        with st.container(border=True):
            render_order_summary(validated_order, validation_error)
        place_clicked = st.button(
            "Place TESTNET order",
            type="primary",
            width="stretch",
            disabled=not credentials_ready,
        )
    if place_clicked:
        if validated_order is None:
            st.session_state.order_result = None
            st.session_state.ui_message = (
                "error",
                validation_error or "Order input is invalid.",
            )
        else:
            submit_order(validated_order, confirmed, quantity_rules)
        level, message = st.session_state.ui_message
        getattr(st, level)(message)
    with result_column:
        with st.container(border=True):
            if st.session_state.order_result is None:
                st.subheader("Latest order result")
                st.info("No order has been submitted in this dashboard session.")
            else:
                render_order_result(st.session_state.order_result)
    st.caption("Reduce-only is unavailable because the backend does not support it.")

with open_tab:
    heading, refresh = st.columns((5, 1))
    heading.subheader(f"Open orders — {symbol}")
    if refresh.button("Refresh open orders", width="stretch"):
        load_open_orders.clear(symbol)
    if render_data_access_status(credentials_ready):
        try:
            open_orders = load_open_orders(symbol)
            if not open_orders:
                st.info(f"No open orders found for {symbol}.")
            else:
                render_records(
                    open_orders,
                    {
                        "order_id": "Order ID",
                        "symbol": "Symbol",
                        "side": "Side",
                        "order_type": "Type",
                        "original_quantity": "Original quantity",
                        "executed_quantity": "Executed quantity",
                        "price": "Price",
                        "status": "Status",
                        "creation_time": "Creation time",
                        "update_time": "Update time",
                    },
                )
        except Exception as exc:
            render_section_error("Open orders", exc)

with positions_tab:
    heading, refresh = st.columns((5, 1))
    heading.subheader("Non-zero positions")
    if refresh.button("Refresh positions", width="stretch"):
        load_positions.clear()
    if render_data_access_status(credentials_ready):
        try:
            positions = load_positions()
            if not positions:
                st.info("No active positions found.")
            else:
                render_records(
                    positions,
                    {
                        "symbol": "Symbol",
                        "position_amount": "Position amount",
                        "entry_price": "Entry price",
                        "mark_price": "Mark price",
                        "unrealized_profit_loss": "Unrealized P/L",
                        "leverage": "Leverage",
                    },
                )
        except Exception as exc:
            render_section_error("Positions", exc)

with recent_tab:
    heading, refresh = st.columns((5, 1))
    heading.subheader(f"Recent orders — {symbol or 'No symbol'}")
    if refresh.button("Refresh recent orders", width="stretch"):
        load_recent_orders.clear(symbol)
    if render_data_access_status(credentials_ready):
        try:
            recent_orders = load_recent_orders(symbol)
            if not recent_orders:
                st.info(f"No recent orders found for {symbol}.")
            else:
                render_records(
                    recent_orders,
                    {
                        "order_id": "Order ID",
                        "symbol": "Symbol",
                        "side": "Side",
                        "order_type": "Type",
                        "original_quantity": "Original quantity",
                        "executed_quantity": "Executed quantity",
                        "price": "Price",
                        "status": "Status",
                        "creation_time": "Creation time",
                    },
                )
        except Exception as exc:
            render_section_error("Recent orders", exc)

with logs_tab:
    heading, refresh = st.columns((5, 1))
    heading.subheader("Latest application log entries")
    refresh.button("Refresh logs", width="stretch")
    try:
        log_lines = read_recent_log_lines()
        if not log_lines:
            st.info("The application log is not available or is currently empty.")
        else:
            st.code("\n".join(log_lines), language="text")
            st.caption(f"Showing the latest {len(log_lines)} lines only.")
    except OSError as exc:
        logger.error("GUI_LOG_READ_FAILED error_type=%s", type(exc).__name__)
        st.error("The application log could not be read.")

with project_tab:
    st.subheader("Project information")
    st.markdown(
        """
        This is a **Python-based Binance Futures Testnet Trading Dashboard** built
        as an internship project. It combines:

        - Python and Streamlit for the application and dashboard interface
        - the Binance USDT-M Futures Testnet API for market and account data
        - Decimal-based local and exchange-rule validation
        - modular client, service, validation, order, and logging layers
        - defensive exception handling and append-only application logging

        **No real-money trading is performed.** The client rejects any base URL
        other than the Binance Futures Testnet endpoint, and credentials are loaded
        only from the local environment configuration.
        """
    )

st.caption(
    "The dashboard displays only allow-listed fields. API keys, secrets, "
    "signatures, and raw Binance responses are never shown."
)

//! CrusaderBot order sidecar — Polymarket CLOB orders for EIP-7702 deposit wallets.
//!
//! WHY THIS EXISTS: Polymarket migrated Magic/email accounts to EIP-7702
//! "deposit wallets" (post 2026-04-28). py-clob-client-v2 (Python) cannot sign
//! orders for them — its L1 auth + order signature paths are EOA-shaped
//! (upstream issues #52/#53/#64/#70/#71, all OPEN). The official Rust SDK's
//! canary line is the only client that carries `SignatureType::Poly1271` and
//! the wrapped EIP-1271 order signature (`sign_poly1271_order`). This binary
//! wraps exactly that capability behind a one-shot JSON-over-stdio protocol so
//! the Python bot can invoke it as a subprocess.
//!
//! PROTOCOL (one request per invocation — stateless, idempotent-friendly):
//!   stdin  : one JSON object {"action": "...", "params": {...}}
//!   stdout : one JSON object {"ok": true, "result": ...}
//!                          | {"ok": false, "error": "...", "kind": "..."}
//!   exit   : 0 on protocol success (even when ok=false), 2 on protocol error
//!
//! SECRETS: the private key arrives via the SIDECAR_PRIVATE_KEY environment
//! variable — NEVER via argv (argv is world-readable in /proc). Optional L2
//! credentials via SIDECAR_API_KEY / SIDECAR_API_SECRET / SIDECAR_PASSPHRASE
//! skip the L1 derive round-trip. The funder (deposit wallet) arrives via
//! SIDECAR_FUNDER. Nothing secret is ever printed to stdout/stderr.
//!
//! ACTIONS:
//!   derive_creds      -> {api_key, api_secret, passphrase, address}
//!   place_order       -> PostOrderResponse passthrough
//!   cancel_order      -> CancelOrdersResponse passthrough
//!   cancel_all        -> CancelOrdersResponse passthrough
//!   get_open_orders   -> [OpenOrder] passthrough
//!
//! SAFETY: this binary performs NO risk checks — sizing, dedup, drawdown,
//! kill-switch, and ENABLE_LIVE_TRADING all live in the Python RISK layer,
//! which must run BEFORE every invocation (CLAUDE.md SYSTEM PIPELINE:
//! RISK before EXECUTION, no exceptions).

use std::io::Read as _;
use std::str::FromStr as _;

use alloy::primitives::Address;
use alloy::signers::local::LocalSigner;
use alloy::signers::Signer as _;
use anyhow::{anyhow, bail, Context as _, Result};
use polymarket_client_sdk_v2::auth::Credentials;
use polymarket_client_sdk_v2::clob::types::request::OrdersRequest;
use polymarket_client_sdk_v2::clob::types::{OrderType, Side, SignatureType};
use polymarket_client_sdk_v2::clob::{Client, Config};
use polymarket_client_sdk_v2::types::{Decimal, U256};
use polymarket_client_sdk_v2::POLYGON;
use secrecy::ExposeSecret as _;
use serde::Deserialize;
use serde_json::{json, Value};
use uuid::Uuid;

const CLOB_URL_VAR: &str = "SIDECAR_CLOB_URL";
const DEFAULT_CLOB_URL: &str = "https://clob-v2.polymarket.com";
const PRIVATE_KEY_VAR: &str = "SIDECAR_PRIVATE_KEY";
const FUNDER_VAR: &str = "SIDECAR_FUNDER";
const API_KEY_VAR: &str = "SIDECAR_API_KEY";
const API_SECRET_VAR: &str = "SIDECAR_API_SECRET";
const PASSPHRASE_VAR: &str = "SIDECAR_PASSPHRASE";

#[derive(Deserialize)]
struct Request {
    action: String,
    #[serde(default)]
    params: Value,
}

#[derive(Deserialize)]
struct PlaceOrderParams {
    token_id: String,
    side: String,       // "BUY" | "SELL"
    price: String,      // decimal string — never floats for money
    size: String,       // decimal string
    #[serde(default = "default_order_type")]
    order_type: String, // "GTC" | "FOK" | "FAK"
}

fn default_order_type() -> String {
    "GTC".to_owned()
}

#[derive(Deserialize)]
struct CancelOrderParams {
    order_id: String,
}

fn emit(value: Value) {
    // Single line of JSON on stdout — the entire contract with the Python side.
    println!("{value}");
}

fn emit_err(kind: &str, error: impl std::fmt::Display) {
    emit(json!({"ok": false, "kind": kind, "error": error.to_string()}));
}

#[tokio::main]
async fn main() {
    let mut input = String::new();
    if std::io::stdin().read_to_string(&mut input).is_err() {
        emit_err("protocol", "failed to read stdin");
        std::process::exit(2);
    }
    let request: Request = match serde_json::from_str(&input) {
        Ok(r) => r,
        Err(e) => {
            emit_err("protocol", format!("invalid request JSON: {e}"));
            std::process::exit(2);
        }
    };

    match run(request).await {
        Ok(result) => emit(json!({"ok": true, "result": result})),
        // Action-level failures (auth refused, order rejected, config missing)
        // are DATA, not process errors: exit 0 with ok=false so the Python
        // wrapper distinguishes "sidecar broke" from "broker said no".
        Err(e) => emit_err("action", format!("{e:#}")),
    }
}

const KNOWN_ACTIONS: &[&str] = &[
    "derive_creds",
    "place_order",
    "cancel_order",
    "cancel_all",
    "get_open_orders",
    "get_order",
    "get_trades",
];

async fn run(request: Request) -> Result<Value> {
    // Validate the action BEFORE any env read or network call — an unknown
    // action must not cost a broker round-trip (authenticate() mints/derives
    // L2 credentials server-side when none are supplied).
    if !KNOWN_ACTIONS.contains(&request.action.as_str()) {
        bail!("unknown action: {}", request.action);
    }

    let private_key =
        std::env::var(PRIVATE_KEY_VAR).context("SIDECAR_PRIVATE_KEY env var is required")?;
    let funder_raw = std::env::var(FUNDER_VAR).context("SIDECAR_FUNDER env var is required")?;
    let funder = Address::from_str(funder_raw.trim())
        .map_err(|e| anyhow!("SIDECAR_FUNDER is not a valid address: {e}"))?;
    let clob_url = std::env::var(CLOB_URL_VAR).unwrap_or_else(|_| DEFAULT_CLOB_URL.to_owned());

    let signer = LocalSigner::from_str(private_key.trim())
        .map_err(|e| anyhow!("SIDECAR_PRIVATE_KEY is not a valid key: {e}"))?
        .with_chain_id(Some(POLYGON));

    let config = Config::builder().use_server_time(true).build();
    let mut builder = Client::new(&clob_url, config)
        .context("CLOB client construction failed")?
        .authentication_builder(&signer)
        // The whole point of this binary: deposit-wallet maker via the
        // wrapped EIP-1271 order signature. L1 auth stays plain-EOA ECDSA
        // (the SDK's proven architecture — POLY_ADDRESS = signer EOA),
        // the deposit wallet enters as funder on the Poly1271 order.
        .funder(funder)
        .signature_type(SignatureType::Poly1271);

    // Reuse persisted L2 creds when provided — skips the create/derive
    // round-trip per invocation (and avoids minting new keys server-side).
    if let (Ok(key), Ok(secret), Ok(pass)) = (
        std::env::var(API_KEY_VAR),
        std::env::var(API_SECRET_VAR),
        std::env::var(PASSPHRASE_VAR),
    ) {
        let key = Uuid::from_str(key.trim()).context("SIDECAR_API_KEY is not a UUID")?;
        builder = builder.credentials(Credentials::new(key, secret, pass));
    }

    let client = builder
        .authenticate()
        .await
        .context("CLOB authentication failed")?;

    match request.action.as_str() {
        "derive_creds" => {
            let creds = client.credentials();
            Ok(json!({
                "api_key": creds.key().to_string(),
                "api_secret": creds.secret().expose_secret(),
                "passphrase": creds.passphrase().expose_secret(),
                "address": signer.address().to_checksum(None),
                "funder": funder.to_checksum(None),
            }))
        }
        "place_order" => {
            let p: PlaceOrderParams = serde_json::from_value(request.params)
                .context("place_order params invalid")?;
            let token_id =
                U256::from_str(p.token_id.trim()).context("token_id is not a valid uint256")?;
            let side = match p.side.to_uppercase().as_str() {
                "BUY" => Side::Buy,
                "SELL" => Side::Sell,
                other => bail!("side must be BUY or SELL, got {other}"),
            };
            let order_type = match p.order_type.to_uppercase().as_str() {
                "GTC" => OrderType::GTC,
                "FOK" => OrderType::FOK,
                "FAK" => OrderType::FAK,
                other => bail!("order_type must be GTC/FOK/FAK, got {other}"),
            };
            let price = Decimal::from_str(p.price.trim()).context("price is not a decimal")?;
            let size = Decimal::from_str(p.size.trim()).context("size is not a decimal")?;

            let order = client
                .limit_order()
                .token_id(token_id)
                .order_type(order_type)
                .price(price)
                .size(size)
                .side(side)
                .build()
                .await
                .context("order build failed")?;
            let signed = client
                .sign(&signer, order)
                .await
                .context("order signing failed")?;
            let resp = client
                .post_order(signed)
                .await
                .context("post_order failed")?;
            Ok(post_order_to_json(&resp))
        }
        "cancel_order" => {
            let p: CancelOrderParams = serde_json::from_value(request.params)
                .context("cancel_order params invalid")?;
            let resp = client
                .cancel_order(&p.order_id)
                .await
                .context("cancel_order failed")?;
            Ok(cancel_to_json(&resp))
        }
        "cancel_all" => {
            let resp = client
                .cancel_all_orders()
                .await
                .context("cancel_all_orders failed")?;
            Ok(cancel_to_json(&resp))
        }
        "get_open_orders" => {
            // Single page (limit defaults server-side). The bot holds ≤ a few
            // dozen resting orders per user — pagination loop is a follow-up
            // if that assumption ever breaks.
            let resp = client
                .orders(&OrdersRequest::default(), None)
                .await
                .context("orders query failed")?;
            let rows: Vec<Value> = resp.data.iter().map(open_order_to_json).collect();
            Ok(json!({
                "orders": rows,
                "next_cursor": resp.next_cursor,
                "count": resp.count,
            }))
        }
        "get_order" => {
            let p: CancelOrderParams = serde_json::from_value(request.params)
                .context("get_order params invalid (needs order_id)")?;
            let resp = client
                .order(&p.order_id)
                .await
                .context("order lookup failed")?;
            Ok(open_order_to_json(&resp))
        }
        "get_trades" => {
            #[derive(Deserialize, Default)]
            struct TradesParams {
                #[serde(default)]
                order_id: Option<String>,
            }
            let p: TradesParams = serde_json::from_value(request.params).unwrap_or_default();
            let mut req = polymarket_client_sdk_v2::clob::types::request::TradesRequest::default();
            req.id = p.order_id;
            let resp = client
                .trades(&req, None)
                .await
                .context("trades query failed")?;
            let rows: Vec<Value> = resp.data.iter().map(trade_to_json).collect();
            Ok(json!({"trades": rows, "next_cursor": resp.next_cursor, "count": resp.count}))
        }
        // Unreachable — guarded by the KNOWN_ACTIONS check at entry.
        other => bail!("unknown action: {other}"),
    }
}

fn trade_to_json(t: &polymarket_client_sdk_v2::clob::types::response::TradeResponse) -> Value {
    json!({
        "id": t.id,
        "taker_order_id": t.taker_order_id,
        "market": t.market.to_string(),
        "asset_id": t.asset_id.to_string(),
        "token_id": t.asset_id.to_string(),
        "side": format!("{:?}", t.side).to_uppercase(),
        "size": t.size.to_string(),
        "price": t.price.to_string(),
        "fee_rate_bps": t.fee_rate_bps.to_string(),
        "status": format!("{:?}", t.status).to_lowercase(),
        "outcome": t.outcome,
        "match_time": t.match_time.timestamp(),
        "transaction_hash": t.transaction_hash.to_string(),
        "maker_address": t.maker_address.to_checksum(None),
    })
}

// The SDK's response structs are Deserialize-only (no Serialize), so the JSON
// the Python wrapper sees is mapped by hand here. Field names mirror what the
// existing Python ClobV2Client expects from py-clob-client-v2 dicts (orderID
// alias + order_id + id all carried) so the wrapper can reuse the proven
// alias-tolerant readers.

fn post_order_to_json(r: &polymarket_client_sdk_v2::clob::types::response::PostOrderResponse) -> Value {
    json!({
        "success": r.success,
        "orderID": r.order_id,
        "order_id": r.order_id,
        "status": format!("{:?}", r.status).to_lowercase(),
        "error_msg": r.error_msg,
        "making_amount": r.making_amount.to_string(),
        "taking_amount": r.taking_amount.to_string(),
        "transaction_hashes": r.transaction_hashes.iter().map(|h| h.to_string()).collect::<Vec<_>>(),
        "trade_ids": r.trade_ids,
    })
}

fn cancel_to_json(r: &polymarket_client_sdk_v2::clob::types::response::CancelOrdersResponse) -> Value {
    json!({
        "canceled": r.canceled,
        "not_canceled": r.not_canceled,
    })
}

fn open_order_to_json(o: &polymarket_client_sdk_v2::clob::types::response::OpenOrderResponse) -> Value {
    json!({
        "id": o.id,
        "orderID": o.id,
        "order_id": o.id,
        "status": format!("{:?}", o.status).to_lowercase(),
        "market": o.market.to_string(),
        "asset_id": o.asset_id.to_string(),
        "token_id": o.asset_id.to_string(),
        "side": format!("{:?}", o.side).to_uppercase(),
        "original_size": o.original_size.to_string(),
        "size_matched": o.size_matched.to_string(),
        "price": o.price.to_string(),
        "outcome": o.outcome,
        "order_type": format!("{:?}", o.order_type),
        "maker_address": o.maker_address.to_checksum(None),
        "created_at": o.created_at.timestamp(),
        "expiration": o.expiration.timestamp(),
        "associate_trades": o.associate_trades,
    })
}

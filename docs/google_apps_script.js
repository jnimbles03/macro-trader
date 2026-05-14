/**
 * Macro Scout Market Data — Google Apps Script
 *
 * Setup:
 *   1. In your Google Sheet: Extensions > Apps Script
 *   2. Paste this file
 *   3. Update MARKET_DATA_URL to your Tailscale IP
 *   4. Use =MD_QUOTE("EEM") or =MD_CHAIN("EEM","2026-11-21") in cells
 *
 * Requires: your Mac must be reachable on Tailscale (100.126.133.54:8001)
 * and macro-scout must be running.
 */

const MARKET_DATA_URL = "http://100.126.133.54:8001";

function MD_QUOTE(ticker) {
  try {
    const url = `${MARKET_DATA_URL}/api/v1/quote/${ticker}`;
    const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    if (resp.getResponseCode() !== 200) return "N/A";
    const data = JSON.parse(resp.getContentText());
    return parseFloat(data.price) || "N/A";
  } catch (e) {
    return "ERR: " + e.message;
  }
}

function MD_CHAIN(ticker, expiry) {
  /**
   * Dumps an option chain into the sheet starting at the calling cell.
   * Returns a 2D array: [strike, type, bid, ask, iv, delta, gamma]
   */
  expiry = expiry || "front";
  try {
    const url = `${MARKET_DATA_URL}/api/v1/chain/${ticker}/${expiry}`;
    const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    if (resp.getResponseCode() !== 200) return [["No data for " + ticker]];
    const data = JSON.parse(resp.getContentText());
    const rows = [["strike", "type", "bid", "ask", "iv", "delta", "gamma", "vega"]];
    (data.contracts || []).forEach(c => {
      rows.push([c.strike, c.type, c.bid, c.ask,
                 (c.iv * 100).toFixed(1) + "%",
                 c.delta.toFixed(3), c.gamma.toFixed(4), c.vega.toFixed(3)]);
    });
    return rows;
  } catch (e) {
    return [["ERR: " + e.message]];
  }
}

function MD_SUBSCRIBE(ticker, secType, ttlHours) {
  /**
   * Register a ticker for ad-hoc ingest from a Sheet.
   * =MD_SUBSCRIBE("NVDA") subscribes NVDA for 24h.
   */
  secType = secType || "STK";
  ttlHours = ttlHours || 24;
  try {
    const url = `${MARKET_DATA_URL}/api/v1/subscribe/${ticker}?sec_type=${secType}&ttl_hours=${ttlHours}&requested_by=sheets`;
    const resp = UrlFetchApp.fetch(url, { method: "post", muteHttpExceptions: true });
    const data = JSON.parse(resp.getContentText());
    return "Subscribed until " + data.expires_at;
  } catch (e) {
    return "ERR: " + e.message;
  }
}

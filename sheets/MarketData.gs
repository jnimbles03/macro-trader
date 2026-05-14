/**
 * Macro Scout — Google Sheets Market Data Add-on
 * 
 * SETUP:
 *   1. In Google Sheets: Extensions → Apps Script → paste this file
 *   2. Set your Tailscale IP in the CONFIG section below
 *   3. Save and reload the sheet — a "Market Data" menu appears
 *
 * CUSTOM FUNCTIONS (use in any cell):
 *   =IBQUOTE("EEM")                        → latest price
 *   =IBCHAIN("EEM","2026-11-21")           → dumps full chain starting at this cell
 *   =IBCHAIN("EEM","front")               → front-month chain
 *
 * MENU ACTIONS:
 *   Market Data → Subscribe Ticker        → add ad-hoc ticker (lasts 24h)
 *   Market Data → Refresh Active Sheet    → re-run all IBQUOTE/IBCHAIN formulas
 *   Market Data → Show Watchlist          → list active subscriptions
 */

// ── CONFIG ────────────────────────────────────────────────────────────────────
var BASE_URL = "http://100.126.133.54:8001/api/v1";
var REQUEST_TIMEOUT_MS = 10000;
// ─────────────────────────────────────────────────────────────────────────────


// ── CUSTOM FUNCTIONS ──────────────────────────────────────────────────────────

/**
 * Get the latest price for a ticker from the market data hub.
 * @param {string} ticker  Ticker symbol, e.g. "EEM" or "ES"
 * @return Latest price as a number, or an error string.
 * @customfunction
 */
function IBQUOTE(ticker) {
  if (!ticker) return "ERROR: ticker required";
  try {
    var resp = UrlFetchApp.fetch(BASE_URL + "/quote/" + ticker.toUpperCase(), {
      muteHttpExceptions: true,
      deadline: REQUEST_TIMEOUT_MS / 1000
    });
    if (resp.getResponseCode() === 404) return "N/A";
    if (resp.getResponseCode() !== 200) return "ERR:" + resp.getResponseCode();
    var data = JSON.parse(resp.getContentText());
    return data.price || data.last || "N/A";
  } catch (e) {
    return "ERR: " + e.message;
  }
}


/**
 * Get a full option chain and write it to cells starting from where this
 * formula is placed. Each row = one contract (type, strike, bid, ask, IV, delta, gamma).
 * @param {string} ticker  Ticker symbol, e.g. "EEM"
 * @param {string} expiry  ISO date "2026-11-21" or "front" for nearest expiry
 * @return 2D array of option chain data.
 * @customfunction
 */
function IBCHAIN(ticker, expiry) {
  if (!ticker) return [["ERROR: ticker required"]];
  expiry = expiry || "front";
  try {
    var url = BASE_URL + "/chain/" + ticker.toUpperCase() + "/" + expiry;
    var resp = UrlFetchApp.fetch(url, {
      muteHttpExceptions: true,
      deadline: REQUEST_TIMEOUT_MS / 1000
    });
    if (resp.getResponseCode() === 404) return [["No chain data — subscribe first or wait for next ingest"]];
    if (resp.getResponseCode() !== 200) return [["ERR:" + resp.getResponseCode()]];

    var data = JSON.parse(resp.getContentText());
    var contracts = data.contracts || [];
    if (contracts.length === 0) return [["No contracts in chain"]];

    // Header row
    var rows = [["Type", "Strike", "Bid", "Ask", "Mid", "IV", "Delta", "Gamma", "Theta", "Vega", "Volume", "OI",
                 "Underlying: " + ticker, data.underlying_price || "",
                 "Expiry:", data.expiration || expiry,
                 "Updated:", data.quote_time || ""]];

    contracts.forEach(function(c) {
      var mid = (c.bid != null && c.ask != null) ? ((c.bid + c.ask) / 2).toFixed(2) : "";
      rows.push([
        c.type,
        c.strike,
        c.bid != null ? c.bid : "",
        c.ask != null ? c.ask : "",
        mid,
        c.iv != null ? (c.iv * 100).toFixed(1) + "%" : "",
        c.delta != null ? c.delta.toFixed(3) : "",
        c.gamma != null ? c.gamma.toFixed(4) : "",
        c.theta != null ? c.theta.toFixed(3) : "",
        c.vega != null ? c.vega.toFixed(3) : "",
        c.volume != null ? c.volume : "",
        c.open_interest != null ? c.open_interest : ""
      ]);
    });
    return rows;

  } catch (e) {
    return [["ERR: " + e.message]];
  }
}


// ── MENU ──────────────────────────────────────────────────────────────────────

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("📈 Market Data")
    .addItem("Subscribe Ticker (24h)", "menuSubscribe")
    .addItem("Refresh Sheet", "menuRefresh")
    .addSeparator()
    .addItem("Show Watchlist", "menuWatchlist")
    .addItem("Status Check", "menuStatus")
    .addToUi();
}


function menuSubscribe() {
  var ui = SpreadsheetApp.getUi();
  var result = ui.prompt(
    "Subscribe Ticker",
    "Enter ticker symbol (e.g. EEM, SPY, /ES):",
    ui.ButtonSet.OK_CANCEL
  );
  if (result.getSelectedButton() !== ui.Button.OK) return;

  var ticker = result.getResponseText().trim().toUpperCase();
  if (!ticker) return;

  // Detect sec type
  var secType = ticker.startsWith("/") ? "FUT" : "STK";
  var cleanTicker = ticker.replace("/", "");

  try {
    var resp = UrlFetchApp.fetch(
      BASE_URL + "/subscribe/" + cleanTicker +
      "?sec_type=" + secType +
      "&requested_by=google_sheets&ttl_hours=24",
      { method: "post", muteHttpExceptions: true }
    );
    var data = JSON.parse(resp.getContentText());
    ui.alert("Subscribed: " + cleanTicker + "\n\nData will populate within 5 minutes during market hours.");
  } catch (e) {
    ui.alert("Error: " + e.message);
  }
}


function menuRefresh() {
  // Force-recalculate all custom functions on the active sheet
  var sheet = SpreadsheetApp.getActiveSheet();
  var range = sheet.getDataRange();
  var formulas = range.getFormulas();
  
  // Touch any cell with IBQUOTE or IBCHAIN to force recalc
  for (var r = 0; r < formulas.length; r++) {
    for (var c = 0; c < formulas[r].length; c++) {
      var f = formulas[r][c];
      if (f && (f.indexOf("IBQUOTE") >= 0 || f.indexOf("IBCHAIN") >= 0)) {
        var cell = sheet.getRange(r + 1, c + 1);
        var current = cell.getFormula();
        cell.setFormula("");
        SpreadsheetApp.flush();
        cell.setFormula(current);
      }
    }
  }
  SpreadsheetApp.getUi().alert("Refresh complete.");
}


function menuWatchlist() {
  try {
    var resp = UrlFetchApp.fetch(BASE_URL + "/watchlist", { muteHttpExceptions: true });
    var data = JSON.parse(resp.getContentText());
    var items = data.watchlist || [];
    if (items.length === 0) {
      SpreadsheetApp.getUi().alert("Watchlist is empty.\nUse Subscribe Ticker to add tickers.");
      return;
    }
    var msg = "Active subscriptions (" + items.length + "):\n\n";
    items.forEach(function(w) {
      msg += "• " + w.ticker + " (" + w.sec_type + ")";
      if (w.expires_at) msg += " — expires " + w.expires_at.substring(0, 16);
      msg += "\n";
    });
    SpreadsheetApp.getUi().alert(msg);
  } catch (e) {
    SpreadsheetApp.getUi().alert("Error connecting to data hub: " + e.message +
      "\n\nMake sure the hub is running at:\n" + BASE_URL);
  }
}


function menuStatus() {
  try {
    var resp = UrlFetchApp.fetch(BASE_URL + "/status", {
      muteHttpExceptions: true,
      deadline: 5
    });
    var data = JSON.parse(resp.getContentText());
    var db = data.db || [];
    var counts = (db[1] && db[1].warehouse_counts) || {};
    var msg = "Market Data Hub Status\n" +
      "─────────────────────\n" +
      "Redis:    " + (data.redis || "unknown") + "\n" +
      "DB:       connected\n" +
      "Chains:   " + (counts.option_chains || 0) + " stored\n" +
      "Headlines:" + (counts.headlines || 0) + "\n" +
      "Updated:  " + (data.ts || "").substring(0, 19) + " UTC\n" +
      "─────────────────────\n" +
      "Hub URL: " + BASE_URL;
    SpreadsheetApp.getUi().alert(msg);
  } catch (e) {
    SpreadsheetApp.getUi().alert("Cannot reach hub: " + e.message);
  }
}


/**
 * =IBEXPIRATIONS("EEM")
 * Returns all available expiration dates as a vertical list.
 * Paste into a cell; dates spill downward automatically.
 */
function IBEXPIRATIONS(ticker) {
  if (!ticker) return "Enter a ticker";
  try {
    var resp = UrlFetchApp.fetch(BASE_URL + "/expirations/" + ticker.toString().toUpperCase(), {
      muteHttpExceptions: true,
      deadline: 10
    });
    if (resp.getResponseCode() !== 200) return "No data for " + ticker;
    var data = JSON.parse(resp.getContentText());
    var dates = data.expirations || [];
    if (dates.length === 0) return "No expirations found";
    // Return as a vertical array so it spills downward in Sheets
    return dates.map(function(d) { return [d]; });
  } catch (e) {
    return "Error: " + e.message;
  }
}


/**
 * =IBCHAINALL("EEM")
 * Dumps ALL expiration chains into the sheet — one block per expiry.
 * Each row: expiry | type | strike | bid | ask | mid | IV | delta | gamma | theta | vega | vol | OI
 */
function IBCHAINALL(ticker) {
  if (!ticker) return "Enter a ticker";
  try {
    var resp = UrlFetchApp.fetch(BASE_URL + "/chain/" + ticker.toString().toUpperCase() + "/all", {
      muteHttpExceptions: true,
      deadline: 30
    });
    if (resp.getResponseCode() !== 200) return "No data for " + ticker;
    var data = JSON.parse(resp.getContentText());
    var chains = data.chains || [];
    if (chains.length === 0) return "No chains found";

    var rows = [["Expiry","Type","Strike","Bid","Ask","Mid","IV","Delta","Gamma","Theta","Vega","Volume","OI"]];
    chains.forEach(function(chain) {
      chain.contracts.forEach(function(c) {
        rows.push([
          chain.expiration,
          c.type,
          c.strike,
          c.bid,
          c.ask,
          c.bid != null && c.ask != null ? ((c.bid + c.ask) / 2).toFixed(4) : "",
          c.iv != null ? (c.iv * 100).toFixed(2) + "%" : "",
          c.delta != null ? c.delta.toFixed(4) : "",
          c.gamma != null ? c.gamma.toFixed(6) : "",
          c.theta != null ? c.theta.toFixed(4) : "",
          c.vega != null ? c.vega.toFixed(4) : "",
          c.volume || 0,
          c.open_interest || 0
        ]);
      });
    });
    return rows;
  } catch (e) {
    return "Error: " + e.message;
  }
}

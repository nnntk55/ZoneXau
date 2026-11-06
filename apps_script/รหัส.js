const SHEET_NAME = "State";
const TRADE_SHEET_NAME = "Trades";
const HEADERS = ["asset","note","current_stage","target_mode","active_direction",
                 "custom_mode","custom_tf","custom_dir","is_active","last_trade_date",
                 "auto_paused_today","stage_tfs","s5_enabled","lot","tp_pips","sl_pips","updated_at",
                 "sr_enabled","auto_order","set2","alerts"];
const TRADE_HEADERS = ["time","asset","action","price","lot","tp_pips","sl_pips","result","profit"];
const LOG_SHEET_NAME = "Logs";
const LOG_HEADERS = ["time","source","msg"];

function getSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) sheet = ss.insertSheet(SHEET_NAME);
  // เขียนหัวคอลัมน์ใหม่ทุกครั้งถ้าหัวไม่ครบ (sheet เก่าอาจขาด set2/alerts คอลัมน์ท้าย)
  const head = sheet.getRange(1, 1, 1, HEADERS.length).getValues()[0];
  if (sheet.getLastRow() === 0 || head[0] !== "asset" || head[HEADERS.length - 1] !== "alerts") {
    sheet.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]);
  }
  return sheet;
}

function getTradeSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(TRADE_SHEET_NAME);
  if (!sheet) sheet = ss.insertSheet(TRADE_SHEET_NAME);
  if (sheet.getLastRow() === 0 || sheet.getRange(1,1).getValue() !== "time") {
    sheet.getRange(1, 1, 1, TRADE_HEADERS.length).setValues([TRADE_HEADERS]);
  }
  return sheet;
}

function getLogSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(LOG_SHEET_NAME);
  if (!sheet) sheet = ss.insertSheet(LOG_SHEET_NAME);
  if (sheet.getLastRow() === 0 || sheet.getRange(1,1).getValue() !== "time") {
    sheet.getRange(1, 1, 1, LOG_HEADERS.length).setValues([LOG_HEADERS]);
  }
  return sheet;
}

// ==== PLUTUS FINANCE — ชีทการเงินแยกของนิน ===
const FIN_SS_PROP = "FIN_SS_ID";
const FIN_TABS = {
  "Transactions": ["time","date","kind","amount","cur","cat","note","pocket"],
  "Payables":     ["who","amount","due","note","paid"],
  "Recurring":    ["name","amount","due_day","cat"],
  "Planned":      ["item","amount","date","note"]
};

function finSS() {
  const p = PropertiesService.getScriptProperties();
  const id = p.getProperty(FIN_SS_PROP);
  if (id) {
    try { return SpreadsheetApp.openById(id); } catch (e) { /* ชีทหาย/สิทธิ์หลุด สร้างใหม่ */ }
  }
  const ss = SpreadsheetApp.create("Ninin Finance");
  p.setProperty(FIN_SS_PROP, ss.getId());
  return ss;
}

function finTab(ss, name) {
  let s = ss.getSheetByName(name);
  if (!s) s = ss.insertSheet(name);
  const heads = FIN_TABS[name];
  const head = s.getLastRow() > 0 ? s.getRange(1, 1, 1, heads.length).getValues()[0] : [];
  if (heads && (s.getLastRow() === 0 || head[0] !== heads[0] || head[heads.length - 1] !== heads[heads.length - 1])) {
    s.getRange(1, 1, 1, heads.length).setValues([heads]);
  }
  return s;
}

function finWrite(sheet, rows) {
  if (sheet.getLastRow() > 1) {
    sheet.getRange(2, 1, sheet.getLastRow() - 1, sheet.getLastColumn()).clearContent();
  }
  if (rows.length) {
    sheet.getRange(2, 1, rows.length, rows[0].length).setValues(rows);
  }
}

function financeSync(data) {
  const ss = finSS();
  const d = data.ledger || {};
  finWrite(finTab(ss, "Transactions"), (d.tx || []).map(function (x) {
    return [x.t || "", x.date || "", x.kind || "", x.amount != null ? x.amount : "",
            x.cur || "THB", x.cat || "", x.note || "", x.pocket || ""];
  }));
  finWrite(finTab(ss, "Payables"), (d.payables || []).map(function (x) {
    return [x.who || "", x.amount != null ? x.amount : "", x.due || "", x.note || "", !!x.paid];
  }));
  finWrite(finTab(ss, "Recurring"), (d.recurring || []).map(function (x) {
    return [x.name || "", x.amount != null ? x.amount : "", x.due_day != null ? x.due_day : "", x.cat || ""];
  }));
  finWrite(finTab(ss, "Planned"), (d.planned || []).map(function (x) {
    return [x.item || "", x.amount != null ? x.amount : "", x.date || "", x.note || ""];
  }));
  return {status: "success", type: "finance_sync", url: ss.getUrl()};
}

function finRead() {
  const ss = finSS();
  const out = {url: ss.getUrl()};
  for (const name in FIN_TABS) {
    const s = finTab(ss, name);
    const vals = s.getLastRow() > 1 ? s.getRange(2, 1, s.getLastRow() - 1, FIN_TABS[name].length).getValues() : [];
    out[name] = vals.map(function (r) {
      const o = {};
      FIN_TABS[name].forEach(function (h, i) { o[h] = r[i]; });
      return o;
    });
  }
  return out;
}

function sheetOp(d) {
  try {
    const ss = SpreadsheetApp.openById(d.ssid);
    const s = d.sheet ? ss.getSheetByName(d.sheet) : ss.getSheets()[0];
    if (!s) return {status: "error", message: "no sheet " + d.sheet};
    if (d.op === "write") {
      if (d.cell) s.getRange(d.cell).setValue(d.value);
      else if (Array.isArray(d.rows) && d.rows.length)
        s.getRange(d.row || s.getLastRow() + 1, d.col || 1, d.rows.length, d.rows[0].length).setValues(d.rows);
      return {status: "success", type: "sheet_op"};
    }
    const rng = d.range ? s.getRange(d.range) : s.getDataRange();
    return {status: "success", type: "sheet_op", a1: rng.getA1Notation(), values: rng.getValues()};
  } catch (e) { return {status: "error", message: String(e)}; }
}

function normBool(v, def) {
  if (v === true || v === false) return v;
  if (v === null || v === undefined || v === "") return def;
  const s = String(v).toLowerCase().trim();
  return !(s === "false" || s === "0" || s === "off" || s === "no");
}

function normJson(v) {
  if (v === null || v === undefined) return "";
  return (typeof v === "string") ? v : JSON.stringify(v);
}

function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);

    // === บันทึกออเดอร์ (open + close) ลง tab Trades ===
    if (data && data.type === "trade") {
      const ts = getTradeSheet();
      ts.appendRow([
        data.time || new Date().toISOString(),
        data.asset || "",
        data.action || "",
        data.price != null ? data.price : "",
        data.lot != null ? data.lot : "",
        data.tp_pips != null ? data.tp_pips : "",
        data.sl_pips != null ? data.sl_pips : "",
        data.result != null ? data.result : "",
        data.profit != null ? data.profit : ""
      ]);
      return ContentService.createTextOutput(JSON.stringify({status:"success",type:"trade"}))
        .setMimeType(ContentService.MimeType.JSON);
    }

    // === log ของ Midas/บอท (ให้ Devin อ่านจากนอกเครื่องได้) ===
    if (data && data.type === "log") {
      const lines = Array.isArray(data.lines) ? data.lines : [data.msg || ""];
      const ls = getLogSheet();
      const now = new Date().toISOString();
      const rows = lines.slice(0, 50).map(function (l) {
        return [l && l.time ? l.time : now, data.source || "", String(l && l.msg !== undefined ? l.msg : l).slice(0, 1000)];
      });
      if (rows.length) ls.getRange(ls.getLastRow() + 1, 1, rows.length, LOG_HEADERS.length).setValues(rows);
      return ContentService.createTextOutput(JSON.stringify({status:"success",type:"log",n:rows.length}))
        .setMimeType(ContentService.MimeType.JSON);
    }

    // === พลูตัส: ซิงก์ ledger การเงินทั้งก้อนขึ้นชีทแยก ===
    if (data && data.type === "finance_sync") {
      return ContentService.createTextOutput(JSON.stringify(financeSync(data)))
        .setMimeType(ContentService.MimeType.JSON);
    }

    // === พลูตัส: อ่าน/เขียนชีทใดๆ ที่สคริปต์เข้าถึงได้ (เช่น Students Schedule) ===
    if (data && data.type === "sheet_op") {
      return ContentService.createTextOutput(JSON.stringify(sheetOp(data)))
        .setMimeType(ContentService.MimeType.JSON);
    }

    // === เซฟ state ===
    if (!data || !data.asset) {
      return ContentService.createTextOutput(JSON.stringify({status:"error",message:"no asset"}))
        .setMimeType(ContentService.MimeType.JSON);
    }
    const sheet = getSheet();
    const row = [
      data.asset,
      data.note !== undefined ? data.note : "",
      data.current_stage !== undefined ? data.current_stage : 1,
      data.target_mode !== undefined ? data.target_mode : "AUTO",
      data.active_direction !== undefined ? data.active_direction : "LOW",
      data.custom_mode !== undefined ? data.custom_mode : false,
      data.custom_tf != null ? data.custom_tf : "",
      data.custom_dir != null ? data.custom_dir : "",
      data.is_active !== undefined ? data.is_active : true,
      data.last_trade_date != null ? data.last_trade_date : "",
      data.auto_paused_today !== undefined ? data.auto_paused_today : false,
      data.stage_tfs !== undefined ? JSON.stringify(data.stage_tfs) : "",
      data.s5_enabled !== undefined ? data.s5_enabled : true,
      data.lot !== undefined ? data.lot : "",
      data.tp_pips !== undefined ? data.tp_pips : "",
      data.sl_pips !== undefined ? data.sl_pips : "",
      new Date().toISOString(),
      data.sr_enabled !== undefined ? data.sr_enabled : false,
      data.auto_order !== undefined ? data.auto_order : false,
      normJson(data.set2),
      normJson(data.alerts)
    ];
    const values = sheet.getDataRange().getValues();
    let found = -1;
    for (let i = 1; i < values.length; i++) {
      if (values[i][0] === data.asset) { found = i + 1; break; }
    }
    if (found > 0) {
      sheet.getRange(found, 1, 1, row.length).setValues([row]);
    } else {
      sheet.appendRow(row);
    }
    return ContentService.createTextOutput(JSON.stringify({status:"success"}))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({status:"error",message:String(err)}))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  if (e && e.parameter && e.parameter.finance) {
    return ContentService.createTextOutput(JSON.stringify(finRead()))
      .setMimeType(ContentService.MimeType.JSON);
  }
  if (e && e.parameter && e.parameter.logs) {
    const ls = getLogSheet();
    const n = Math.min(Number(e.parameter.logs) || 100, 500);
    const last = ls.getLastRow();
    const start = Math.max(2, last - n + 1);
    const vals = last >= 2 ? ls.getRange(start, 1, last - start + 1, LOG_HEADERS.length).getValues() : [];
    return ContentService.createTextOutput(JSON.stringify(vals.map(function (r) {
      return {time: r[0], source: r[1], msg: r[2]};
    }))).setMimeType(ContentService.MimeType.JSON);
  }
  const sheet = getSheet();
  const values = sheet.getDataRange().getValues();
  const result = {};
  for (let i = 1; i < values.length; i++) {
    const r = values[i];
    if (!r[0]) continue;
    let tfs = ["4h","1h","15m","5m"];
    if (r[11]) {
      try { tfs = JSON.parse(r[11]); } catch(err) { tfs = String(r[11]).split(","); }
    }
    result[r[0]] = {
      note: r[1] || "ยังไม่มีบันทึกแผน",
      current_stage: Number(r[2]) || 1,
      target_mode: r[3] || "AUTO",
      active_direction: r[4] || "LOW",
      custom_mode: normBool(r[5], false),
      custom_tf: r[6] || null,
      custom_dir: r[7] || null,
      is_active: normBool(r[8], true),
      last_trade_date: r[9] || null,
      auto_paused_today: normBool(r[10], false),
      stage_tfs: tfs,
      s5_enabled: normBool(r[12], true),
      lot: Number(r[13]) || 0.01,
      tp_pips: Number(r[14]) || 300,
      sl_pips: Number(r[15]) || 200,
      sr_enabled: normBool(r[17], false),
      auto_order: normBool(r[18], false),
      set2: r[19] || "",
      alerts: r[20] || ""
    };
  }
  return ContentService.createTextOutput(JSON.stringify(result))
    .setMimeType(ContentService.MimeType.JSON);
}
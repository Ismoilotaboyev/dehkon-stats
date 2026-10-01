const API_URL = "https://api.dehkonbi.uz/api/dashboard";

function money(v) {
  return new Intl.NumberFormat("uz-UZ").format(Number(v || 0)) + " so‘m";
}

async function load(period) {
  const r = await fetch(`${API_URL}?period=${encodeURIComponent(period)}`, {
    cache: "no-store",
    headers: { "Accept": "application/json" }
  });

  if (!r.ok) {
    let detail = "";
    try { detail = await r.text(); } catch (_) {}
    throw new Error(`API ${r.status}${detail ? ": " + detail.slice(0, 120) : ""}`);
  }

  return await r.json();
}

function card(label, value, note = "") {
  return `<div class="card"><div class="label">${label}</div><div class="value">${value}</div><div class="delta">${note}</div></div>`;
}

function render(d) {
  const t = d.totals || {};
  const searched = Number(t.searched || 0);
  const found = Number(t.found || 0);
  const foundRate = searched ? Math.round(found / searched * 100) : 0;

  cards.innerHTML = [
    card("Jami so‘rovlar", t.requests || 0, "Telegram + Instagram"),
    card("Dori topildi", found, `${foundRate}% topilish`),
    card("Buyurtmalar", t.completed || t.orders || 0, `${t.orders || 0} ta boshlangan`),
    card("Savdo", money(t.sales || 0), `${t.conversion || 0}% konversiya`),
    card("Telegram", t.telegram || 0),
    card("Instagram", t.instagram || 0),
    card("Topilmadi", t.not_found || 0),
    card("Dori qidiruvi", searched)
  ].join("");

  const funnelData = d.funnel || [];
  const mf = Math.max(...funnelData.map(x => Number(x[1] || 0)), 1);
  funnel.innerHTML = funnelData.map(([n, v]) =>
    `<div class="frow"><div>${n}</div><div class="bar"><i style="width:${Number(v || 0) / mf * 100}%"></i></div><div class="num">${v}</div></div>`
  ).join("") || '<div class="empty">Ma’lumot yo‘q</div>';

  const platforms = d.platforms || {};
  const mp = Math.max(...Object.values(platforms).map(Number), 1);
  platformBars.innerHTML = Object.entries(platforms).map(([n, v]) =>
    `<div class="prow"><div class="top"><span>${n}</span><b>${v}</b></div><div class="bar"><i style="width:${Number(v || 0) / mp * 100}%"></i></div></div>`
  ).join("") || '<div class="empty">Ma’lumot yo‘q</div>';

  topDrugs.innerHTML = (d.top_drugs || []).map((r, i) =>
    `<tr><td>${i + 1}</td><td>${r[0]}</td><td>${r[1]}</td><td><span class="badge">${r[2]}</span></td></tr>`
  ).join("");

  notFound.innerHTML = (d.not_found || []).map((r, i) =>
    `<tr><td>${i + 1}</td><td>${r[0]}</td><td>${r[1]}</td><td><span class="badge">${r[2]}</span></td></tr>`
  ).join("");

  operatorLeads.textContent = d.operator_leads || 0;
  complaints.textContent = d.complaints || 0;
  hotLeads.textContent = d.hot_leads || 0;

  const trendData = d.trend || [];
  const mt = Math.max(...trendData.flatMap(x => [Number(x[1] || 0), Number(x[2] || 0) * 12]), 1);
  trend.innerHTML = trendData.map(([x, r, s]) =>
    `<div class="day"><i style="height:${Number(r || 0) / mt * 100}%"></i><i class="sales" style="height:${Number(s || 0) * 12 / mt * 100}%"></i><label>${x}</label></div>`
  ).join("");
}

function renderError(err) {
  cards.innerHTML = `<div class="panel" style="grid-column:1/-1"><b>API bilan ulanishda xato</b><div style="margin-top:8px;color:#6f7c74;font-size:13px">${err.message}</div></div>`;
  funnel.innerHTML = "";
  platformBars.innerHTML = "";
  topDrugs.innerHTML = "";
  notFound.innerHTML = "";
  operatorLeads.textContent = "—";
  complaints.textContent = "—";
  hotLeads.textContent = "—";
  trend.innerHTML = "";
}

async function refreshDashboard() {
  const p = period.value;
  const names = {
    today: "Bugungi ko‘rsatkichlar",
    yesterday: "Kechagi ko‘rsatkichlar",
    "7d": "Oxirgi 7 kun",
    "30d": "Oxirgi 30 kun",
    month: "Shu oy"
  };

  periodText.textContent = names[p] || "Statistika";
  refresh.disabled = true;
  refresh.textContent = "Yuklanmoqda...";

  try {
    render(await load(p));
  } catch (err) {
    renderError(err);
  } finally {
    refresh.disabled = false;
    refresh.textContent = "Yangilash";
  }
}

refresh.onclick = refreshDashboard;
period.onchange = refreshDashboard;
refreshDashboard();

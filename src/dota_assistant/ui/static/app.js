async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(r.status + " " + (await r.text()));
  return r.json();
}

async function stats() {
  try {
    const s = await api("/api/stats");
    document.getElementById("stats").textContent =
      `样本 ${s.samples} 条 / 英雄-位置 ${s.hero_position_combos} 组 | 建议 ${s.advice} 条`;
  } catch (e) { /* ignore */ }
}

async function load() {
  const hero = document.getElementById("f-hero").value.trim();
  const pos = document.getElementById("f-pos").value;
  const q = new URLSearchParams();
  if (hero) q.set("hero", hero);
  if (pos) q.set("position", pos);
  const rows = await api("/api/advice?" + q.toString());
  const tb = document.querySelector("#table tbody");
  tb.innerHTML = "";
  for (const a of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${esc(a.hero)}</td><td>${esc(a.position)}</td>
      <td>${a.t_start_min}–${a.t_end_min}</td>
      <td>${esc(a.advice)}</td><td>${esc(a.source || "")}</td>
      <td>${esc(a.updated_at || "")}</td>
      <td><button class="danger" onclick="del(${a.id})">删除</button></td>`;
    tb.appendChild(tr);
  }
  stats();
}

function showNew() {
  document.getElementById("editor").style.display = "block";
  document.getElementById("e-hero").value = document.getElementById("f-hero").value.trim();
  document.getElementById("e-pos").value =
    document.getElementById("f-pos").value || "carry";
}

function hideEditor() { document.getElementById("editor").style.display = "none"; }

async function save() {
  const body = {
    hero: document.getElementById("e-hero").value.trim(),
    position: document.getElementById("e-pos").value,
    t_start_min: parseFloat(document.getElementById("e-start").value),
    t_end_min: parseFloat(document.getElementById("e-end").value),
    advice: document.getElementById("e-advice").value.trim(),
    source: "user",
  };
  if (!body.hero || !body.advice) { alert("英雄和建议文本必填"); return; }
  await api("/api/advice", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  hideEditor(); load();
}

async function del(id) {
  if (!confirm("删除这条建议？")) return;
  await api("/api/advice/" + id, { method: "DELETE" });
  load();
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
}

load();

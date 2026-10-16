/* ScanEats · Panel del local — comportamiento del cliente (sin dependencias) */
(function () {
  "use strict";

  var CIRC = 2 * Math.PI * 96;
  var t0 = performance.now();

  function pad(n) { return n < 10 ? "0" + n : "" + n; }
  function mmss(s) {
    s = Math.max(0, Math.floor(s));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    return h ? h + ":" + pad(m) + ":" + pad(r) : pad(m) + ":" + pad(r);
  }
  function minseg(s) { s = Math.max(0, Math.floor(s)); return Math.floor(s / 60) + ":" + pad(s % 60); }
  function nivel(seg, prom) { var f = seg / prom; return f > 1 ? "tarde" : (f >= 0.8 ? "cerca" : "ok"); }
  function coma(v) { return Number(v).toFixed(2).replace(".", ","); }

  /* ---------- temporizadores en vivo ---------- */
  function tick() {
    var dt = (performance.now() - t0) / 1000;
    document.querySelectorAll("[data-timer]").forEach(function (el) {
      var src = el.dataset.seg !== undefined ? el : el.closest("[data-seg]");
      if (!src) return;
      el.textContent = mmss(Number(src.dataset.seg) + dt);
    });
    document.querySelectorAll(".wait-row[data-seg]").forEach(function (row) {
      row.dataset.nivel = nivel(Number(row.dataset.seg) + dt, Number(row.dataset.prom));
    });
    document.querySelectorAll(".ring-wrap[data-seg]").forEach(function (wrap) {
      var seg = Number(wrap.dataset.seg) + dt, prom = Number(wrap.dataset.prom);
      var ring = wrap.querySelector(".ring"), total = Number(ring.dataset.total);
      var nv = nivel(seg, prom);
      ring.dataset.nivel = nv;
      ring.querySelector(".ring-prog").setAttribute("stroke-dasharray", (Math.min(seg, total) / total * CIRC).toFixed(1) + " " + CIRC.toFixed(1));
      var centro = wrap.querySelector(".ring-centro"), delta = wrap.querySelector("[data-delta]");
      if (centro) centro.dataset.nivel = nv;
      if (delta) {
        var d = Math.floor(seg - prom);
        delta.textContent = d > 0 ? "+" + minseg(d) + " sobre el promedio" : minseg(-d) + " bajo el promedio";
      }
    });
  }
  if (document.querySelector("[data-timer]")) { tick(); setInterval(tick, 1000); }

  /* ---------- contadores en vivo (cada 15 s) ---------- */
  var urlEstado = document.body.dataset.estadoUrl;
  function refrescar() {
    if (document.hidden || !urlEstado) return;
    fetch(urlEstado, { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d) return;
        document.querySelectorAll("[data-bind]").forEach(function (el) {
          var k = el.dataset.bind;
          if (d.resumen && d.resumen[k] !== undefined) el.textContent = d.resumen[k];
        });
      })
      .catch(function () { /* sin conexión: se mantiene lo último mostrado */ });
  }
  if (urlEstado && document.querySelector("[data-bind]")) setInterval(refrescar, 15000);

  /* ---------- deslizador con valor visible ---------- */
  document.querySelectorAll("input[type=range][data-out]").forEach(function (r) {
    var out = document.getElementById(r.dataset.out);
    r.addEventListener("input", function () { if (out) out.textContent = coma(r.value); });
  });

  /* ---------- diálogos ---------- */
  document.querySelectorAll("[data-dialog]").forEach(function (d) {
    var f = d.querySelector("[data-autofocus]"); if (f) f.focus();
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { var s = d.querySelector(".btn--sec"); if (s) s.click(); }
    });
  });

  /* =====================================================================
     Editor de zonas (escritorio)
     ===================================================================== */
  var app = document.getElementById("zonas-app");
  if (!app) return;
  app.hidden = false;
  var acciones = document.getElementById("zonas-acciones"); if (acciones) acciones.hidden = false;

  var datos = JSON.parse(document.getElementById("zonas-data").textContent);
  var zonas = datos.zonas;
  var svg = document.querySelector("#z-canvas svg");
  var capa = document.getElementById("z-capa");
  var NS = "http://www.w3.org/2000/svg";
  var sel = zonas.length ? 0 : -1, herramienta = "select", borrador = [];
  var $ = function (id) { return document.getElementById(id); };

  function corto(z) { return z.tipo === "caja" ? "Caja · excluida" : (z.nombre.replace(/^Mesa\s*/i, "M")); }
  function centro(p) {
    var x = 0, y = 0; p.forEach(function (q) { x += q[0]; y += q[1]; });
    return [x / p.length, y / p.length];
  }
  function pt(evt) {
    var m = svg.getScreenCTM().inverse(), p = svg.createSVGPoint();
    p.x = evt.clientX; p.y = evt.clientY; var r = p.matrixTransform(m);
    return [Math.max(0, Math.min(datos.ancho, Math.round(r.x * 10) / 10)), Math.max(0, Math.min(datos.alto, Math.round(r.y * 10) / 10))];
  }
  function el(nombre, attrs) {
    var e = document.createElementNS(NS, nombre);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    return e;
  }

  function dibujar() {
    capa.textContent = "";
    zonas.forEach(function (z, i) {
      var poly = el("polygon", { "class": "zpoly" + (z.tipo === "caja" ? " caja" : "") + (i === sel ? " sel" : ""), points: z.puntos.join(" ") });
      poly.addEventListener("pointerdown", function (e) {
        if (herramienta !== "select") return;
        e.stopPropagation(); seleccionar(i);
      });
      capa.appendChild(poly);
      var c = centro(z.puntos), t = el("text", { "class": "ztxt", x: c[0] - 14, y: c[1] + 5 });
      t.textContent = corto(z); capa.appendChild(t);
    });
    if (sel >= 0 && zonas[sel]) {
      zonas[sel].puntos.forEach(function (p, k) {
        var v = el("circle", { "class": "vert", cx: p[0], cy: p[1], r: 6 });
        v.addEventListener("pointerdown", function (e) { arrastrar(e, k); });
        capa.appendChild(v);
      });
    }
    if (borrador.length) {
      capa.appendChild(el("polyline", { "class": "draft", points: borrador.join(" ") }));
      borrador.forEach(function (p) { capa.appendChild(el("circle", { "class": "vert", cx: p[0], cy: p[1], r: 5 })); });
    }
    lista(); panel();
  }

  function lista() {
    var cont = $("z-lista"); cont.textContent = "";
    zonas.forEach(function (z, i) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "zitem" + (z.tipo === "caja" ? " caja" : ""); if (i === sel) b.setAttribute("aria-current", "true");
      b.innerHTML = "<i></i><span></span><small></small>";
      b.children[1].textContent = z.nombre;
      b.children[2].textContent = z.tipo === "caja" ? "excluida" : z.puntos.length + " vértices";
      b.addEventListener("click", function () { seleccionar(i); });
      cont.appendChild(b);
    });
    $("z-count").textContent = zonas.length;
  }

  function panel() {
    var z = zonas[sel], hay = !!z;
    $("z-form").hidden = !hay; $("z-badge").hidden = !hay; $("z-sel-vacio").hidden = hay;
    if (!hay) return;
    if (document.activeElement !== $("z-nombre")) $("z-nombre").value = z.nombre;
    if (document.activeElement !== $("z-cap")) $("z-cap").value = z.capacidad == null ? "" : z.capacidad;
    document.querySelectorAll("[data-tipo]").forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.tipo === z.tipo ? "true" : "false"); });
    $("z-cap-wrap").hidden = z.tipo === "caja"; $("z-adj-wrap").hidden = z.tipo === "caja";
    var adj = $("z-adj"); adj.textContent = "";
    (z.adyacentes || []).forEach(function (a, k) {
      var s = document.createElement("span"); s.textContent = a + " ";
      var x = document.createElement("button"); x.type = "button"; x.textContent = "×"; x.setAttribute("aria-label", "Quitar " + a);
      x.style.cssText = "border:0;background:none;cursor:pointer;font-weight:700;color:inherit;padding:0 0 0 4px";
      x.addEventListener("click", function () { z.adyacentes.splice(k, 1); panel(); });
      s.appendChild(x); adj.appendChild(s);
    });
  }

  function seleccionar(i) { sel = i; dibujar(); }
  function tool(nombre) {
    herramienta = nombre; borrador = [];
    document.querySelectorAll("[data-tool]").forEach(function (b) {
      if (b.dataset.tool !== "borrar") b.setAttribute("aria-pressed", b.dataset.tool === nombre ? "true" : "false");
    });
    $("z-ayuda").textContent = nombre === "select"
      ? "Selecciona una zona y arrastra sus puntos para ajustarla."
      : "Haz clic para agregar vértices; doble clic (o Enter) para cerrar la zona. Esc cancela.";
    dibujar();
  }

  function arrastrar(e, k) {
    e.stopPropagation(); e.preventDefault();
    var z = zonas[sel];
    function mover(ev) { z.puntos[k] = pt(ev); dibujar(); }
    function soltar() { window.removeEventListener("pointermove", mover); window.removeEventListener("pointerup", soltar); }
    window.addEventListener("pointermove", mover); window.addEventListener("pointerup", soltar);
  }

  function cerrar() {
    if (borrador.length < 3) { error("Una zona necesita al menos 3 vértices."); return; }
    var esCaja = herramienta === "caja";
    var n = zonas.filter(function (z) { return z.tipo === "mesa"; }).length + 1;
    var id = zonas.reduce(function (m, z) { return Math.max(m, z.id || 0); }, 0) + 1;
    zonas.push({ id: id, nombre: esCaja ? "Caja" : "Mesa " + n, tipo: esCaja ? "caja" : "mesa", capacidad: esCaja ? null : 4, adyacentes: [], puntos: borrador.slice() });
    sel = zonas.length - 1; error(""); tool("select");
  }

  svg.addEventListener("pointerdown", function (e) {
    if (herramienta === "select") { sel = -1; dibujar(); return; }
    var p = pt(e);
    if (borrador.length >= 3 && Math.hypot(p[0] - borrador[0][0], p[1] - borrador[0][1]) < 10) { cerrar(); return; }
    borrador.push(p); dibujar();
  });
  svg.addEventListener("dblclick", function () { if (herramienta !== "select") { borrador.pop(); cerrar(); } });
  document.addEventListener("keydown", function (e) {
    if (herramienta === "select") return;
    if (e.key === "Enter") cerrar();
    if (e.key === "Escape") tool("select");
  });

  document.querySelectorAll("[data-tool]").forEach(function (b) {
    b.addEventListener("click", function () {
      if (b.dataset.tool === "borrar") {
        if (sel < 0) { error("Selecciona primero la zona que quieres borrar."); return; }
        zonas.splice(sel, 1); sel = zonas.length ? Math.min(sel, zonas.length - 1) : -1; error(""); dibujar();
      } else tool(b.dataset.tool);
    });
  });
  $("z-nombre").addEventListener("input", function (e) { if (zonas[sel]) { zonas[sel].nombre = e.target.value; dibujar(); } });
  $("z-cap").addEventListener("input", function (e) { if (zonas[sel]) zonas[sel].capacidad = e.target.value === "" ? null : Number(e.target.value); });
  document.querySelectorAll("[data-tipo]").forEach(function (b) {
    b.addEventListener("click", function () {
      var z = zonas[sel]; if (!z) return;
      z.tipo = b.dataset.tipo; z.capacidad = z.tipo === "caja" ? null : (z.capacidad || 4); dibujar();
    });
  });
  function agregarAdy() {
    var z = zonas[sel], inp = $("z-adj-in"), v = inp.value.trim().toUpperCase();
    if (!z || !v) return;
    z.adyacentes = z.adyacentes || [];
    if (z.adyacentes.indexOf(v) < 0) z.adyacentes.push(v);
    inp.value = ""; panel();
  }
  $("z-adj-add").addEventListener("click", agregarAdy);
  $("z-adj-in").addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); agregarAdy(); } });

  function error(msg) { var e = $("z-error"); e.hidden = !msg; e.textContent = msg || ""; }
  function cookie(n) { var m = document.cookie.match("(^|;)\\s*" + n + "\\s*=\\s*([^;]+)"); return m ? decodeURIComponent(m.pop()) : ""; }

  $("z-guardar").addEventListener("click", function () {
    var btn = this; btn.disabled = true; error("");
    fetch(window.PANEL_ZONAS_URL, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": cookie("csrftoken") },
      body: JSON.stringify({ zonas: zonas })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        btn.disabled = false;
        if (!res.ok || !res.j.ok) { error((res.j && res.j.error) || "No se pudieron guardar las zonas."); return; }
        $("zok-p").textContent = "Se actualizaron " + res.j.mesas + " mesas" + (res.j.cajas ? " y la zona de caja" : "") + ". El sistema usará esta configuración en la siguiente detección.";
        $("z-ok").hidden = false; $("zok-seguir").focus();
      })
      .catch(function () { btn.disabled = false; error("Sin conexión con el servidor. Inténtalo de nuevo."); });
  });
  $("zok-seguir").addEventListener("click", function () { $("z-ok").hidden = true; });

  dibujar();
})();

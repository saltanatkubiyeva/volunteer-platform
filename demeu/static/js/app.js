(function () {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

  const header = $(".site-header");
  const onScroll = () => header && header.classList.toggle("scrolled", window.scrollY > 8);
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  $$("[data-toggle]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const target = document.getElementById(btn.dataset.toggle);
      const open = target.classList.toggle("open");
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
  });
  document.addEventListener("click", (e) => {
    $$(".dropdown.open").forEach((d) => { if (!d.contains(e.target)) d.classList.remove("open"); });
  });

  $$(".flash").forEach((f) => {
    const close = () => { f.style.transition = "opacity .3s"; f.style.opacity = "0"; setTimeout(() => f.remove(), 300); };
    const b = $("button", f);
    if (b) b.addEventListener("click", close);
    if (!f.classList.contains("error")) setTimeout(close, 6000);
  });

  $$("form[data-autosubmit]").forEach((form) => {
    form.addEventListener("change", (e) => {
      if (e.target.matches("select, input[type=radio], input[type=checkbox]")) form.submit();
    });
  });

  const dlg = $("#confirm-dialog");
  $$("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (form.dataset.confirmed === "1" || !dlg || !dlg.showModal) return;
      e.preventDefault();
      $("#confirm-text", dlg).textContent = form.dataset.confirm;
      dlg.showModal();
      $("#confirm-yes", dlg).onclick = () => { dlg.close(); form.dataset.confirmed = "1"; form.requestSubmit ? form.requestSubmit() : form.submit(); };
      $("#confirm-no", dlg).onclick = () => dlg.close();
    });
  });

  $$("[data-dialog]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const d = document.getElementById(btn.dataset.dialog);
      if (d && d.showModal) d.showModal();
    });
  });
  $$("dialog [data-close]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));

  $$("[data-demo]").forEach((b) => {
    b.addEventListener("click", () => {
      $("#email").value = b.dataset.demo;
      $("#password").value = b.dataset.pw;
      $("#password").focus();
    });
  });

  $$("[data-attendance-row]").forEach((row) => {
    const hours = $("input[type=number]", row);
    const sync = () => {
      const no = $("input[value=no_show]", row);
      if (hours && no) hours.disabled = no.checked;
    };
    row.addEventListener("change", sync);
    sync();
  });

  $$("[data-show-pw]").forEach((b) => {
    b.addEventListener("click", () => {
      const inp = document.getElementById(b.dataset.showPw);
      inp.type = inp.type === "password" ? "text" : "password";
    });
  });

  $$("textarea[maxlength]").forEach((t) => {
    const c = document.createElement("div");
    c.className = "hint";
    c.style.textAlign = "right";
    const upd = () => (c.textContent = `${t.value.length} / ${t.maxLength}`);
    t.after(c);
    t.addEventListener("input", upd);
    upd();
  });
})();

(function () {
  var box = document.querySelector("[data-shifts]");
  if (!box) return;
  var toggle = box.querySelector("[data-shifts-toggle]");
  var area = box.querySelector("[data-shifts-box]");
  var rows = box.querySelector("[data-shift-rows]");
  var sum = box.querySelector("[data-shift-sum]");
  var cap = document.getElementById("max_volunteers");
  function update() {
    var total = 0;
    rows.querySelectorAll("input[name=shift_need]").forEach(function (i) { total += parseInt(i.value, 10) || 0; });
    sum.textContent = sum.dataset.template.replace("{n}", total).replace("{m}", cap ? cap.value || 0 : 0);
  }
  toggle.addEventListener("change", function () { area.hidden = !toggle.checked; });
  box.querySelector("[data-shift-add]").addEventListener("click", function () {
    var all = rows.querySelectorAll("[data-shift-row]");
    if (all.length >= 6) return;
    var copy = all[all.length - 1].cloneNode(true);
    copy.querySelectorAll("input").forEach(function (i) { i.value = ""; });
    rows.appendChild(copy);
    update();
  });
  rows.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-shift-remove]");
    if (!btn) return;
    var all = rows.querySelectorAll("[data-shift-row]");
    var row = btn.closest("[data-shift-row]");
    if (all.length > 1) { row.remove(); } else { row.querySelectorAll("input").forEach(function (i) { i.value = ""; }); }
    update();
  });
  rows.addEventListener("input", update);
  if (cap) cap.addEventListener("input", update);
  update();
})();

(function () {
  var start = document.getElementById("starts_at");
  var deadline = document.getElementById("registration_deadline");
  if (!start || !deadline || !deadline.dataset.auto) return;
  var touched = false;
  deadline.addEventListener("input", function () { touched = true; });
  start.addEventListener("change", function () {
    if (touched || !start.value) return;
    var d = new Date(start.value);
    if (isNaN(d)) return;
    d.setHours(d.getHours() - 24);
    if (d < new Date()) { d = new Date(start.value); d.setHours(d.getHours() - 1); }
    var pad = function (n) { return String(n).padStart(2, "0"); };
    deadline.value = d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + "T" + pad(d.getHours()) + ":" + pad(d.getMinutes());
  });
})();

(function () {
  document.querySelectorAll("form[data-ann-hide]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!window.fetch) return;
      e.preventDefault();
      var box = form.closest("[data-ann]");
      fetch(form.action, {method: "POST", body: new FormData(form), headers: {"X-Requested-With": "fetch"},
                          credentials: "same-origin"}).catch(function () {});
      if (box) {
        box.classList.add("ann-gone");
        setTimeout(function () { var stack = box.parentNode; box.remove(); if (stack && !stack.children.length) stack.remove(); }, 220);
      }
    });
  });
})();

(function () {
  var dlg = document.getElementById("photo-dlg");
  if (!dlg) return;
  var items = Array.prototype.slice.call(document.querySelectorAll("[data-photo]"));
  var img = dlg.querySelector("[data-photo-img]"), cap = dlg.querySelector("[data-photo-cap]");
  var count = dlg.querySelector("[data-photo-count]"), tools = dlg.querySelector("[data-photo-tools]");
  var idx = 0;
  function show(i) {
    idx = (i + items.length) % items.length;
    var it = items[idx];
    img.src = it.dataset.full; img.alt = it.dataset.caption || "";
    cap.textContent = it.dataset.caption || "";
    count.textContent = (idx + 1) + " / " + items.length;
    tools.innerHTML = "";
    var t = document.getElementById("photo-tools-" + it.dataset.photo);
    if (t) tools.appendChild(t.content.cloneNode(true));
  }
  items.forEach(function (it, i) {
    it.addEventListener("click", function (e) { e.preventDefault(); show(i); if (dlg.showModal) dlg.showModal(); });
  });
  dlg.querySelector("[data-photo-prev]").addEventListener("click", function () { show(idx - 1); });
  dlg.querySelector("[data-photo-next]").addEventListener("click", function () { show(idx + 1); });
  dlg.addEventListener("keydown", function (e) {
    if (e.key === "ArrowLeft") show(idx - 1);
    if (e.key === "ArrowRight") show(idx + 1);
  });
  dlg.addEventListener("click", function (e) { if (e.target === dlg) dlg.close(); });
  var input = document.querySelector("[data-photo-input]"), label = document.querySelector("[data-photo-picked]");
  if (input && label) input.addEventListener("change", function () {
    label.textContent = input.files.length ? label.dataset.template.replace("{n}", input.files.length) : label.dataset.empty;
  });
})();

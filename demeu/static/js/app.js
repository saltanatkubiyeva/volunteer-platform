// DEMEU — small progressive enhancements. Every page works without JavaScript.
(function () {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

  // dropdown menus
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

  // flash messages: close button + auto hide for success/info
  $$(".flash").forEach((f) => {
    const close = () => { f.style.transition = "opacity .3s"; f.style.opacity = "0"; setTimeout(() => f.remove(), 300); };
    const b = $("button", f);
    if (b) b.addEventListener("click", close);
    if (!f.classList.contains("error")) setTimeout(close, 6000);
  });

  // filter forms: submit on change of selects / radios / checkboxes
  $$("form[data-autosubmit]").forEach((form) => {
    form.addEventListener("change", (e) => {
      if (e.target.matches("select, input[type=radio], input[type=checkbox]")) form.submit();
    });
  });

  // confirmation dialog for dangerous actions: <form data-confirm="text">
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

  // open a <dialog> by id
  $$("[data-dialog]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const d = document.getElementById(btn.dataset.dialog);
      if (d && d.showModal) d.showModal();
    });
  });
  $$("dialog [data-close]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));

  // demo accounts on the login page
  $$("[data-demo]").forEach((b) => {
    b.addEventListener("click", () => {
      $("#email").value = b.dataset.demo;
      $("#password").value = b.dataset.pw;
      $("#password").focus();
    });
  });

  // attendance table: hours field follows the attended / no-show choice
  $$("[data-attendance-row]").forEach((row) => {
    const hours = $("input[type=number]", row);
    const sync = () => {
      const no = $("input[value=no_show]", row);
      if (hours && no) hours.disabled = no.checked;
    };
    row.addEventListener("change", sync);
    sync();
  });

  // show password
  $$("[data-show-pw]").forEach((b) => {
    b.addEventListener("click", () => {
      const inp = document.getElementById(b.dataset.showPw);
      inp.type = inp.type === "password" ? "text" : "password";
    });
  });

  // character counters
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

// Sliding highlight for every tab bar (top menu and category tabs).
(function () {
  document.querySelectorAll(".tabs").forEach(function (nav) {
    const indicator = nav.querySelector(".tab-indicator");
    const tabs = Array.from(nav.querySelectorAll(".tab"));
    if (!indicator || !tabs.length) return;
    const current = () => nav.querySelector(".tab.is-active") || tabs[0];

    function place(tab) {
      if (!tab) return;
      indicator.style.width = tab.offsetWidth + "px";
      indicator.style.transform = "translateX(" + tab.offsetLeft + "px)";
      indicator.style.opacity = "1";
    }

    tabs.forEach(function (tab) {
      tab.addEventListener("mouseenter", () => place(tab));
      tab.addEventListener("focus", () => place(tab));
      tab.addEventListener("mouseleave", () => place(current()));
      tab.addEventListener("blur", () => place(current()));
    });
    nav.addEventListener("mouseleave", () => place(current()));
    window.addEventListener("resize", () => place(current()));
    place(current());
  });
})();

// Suggestions while typing. The search box submits when you pick one;
// the category box on the recipe form (data-submit="off") just fills in the text.
(function () {
  document.querySelectorAll("input[data-suggest]").forEach(function (input) {
    const box = document.getElementById(input.dataset.box);
    if (!box) return;
    let timer = null;
    let items = [];
    let active = -1;

    function hide() { box.hidden = true; active = -1; }

    function render(list) {
      box.innerHTML = "";
      items = list;
      active = -1;
      if (!list.length) return hide();
      list.forEach(function (text, i) {
        const li = document.createElement("li");
        li.textContent = text;
        li.setAttribute("role", "option");
        li.addEventListener("mousedown", function (e) { e.preventDefault(); choose(i); });
        box.appendChild(li);
      });
      box.hidden = false;
    }

    function mark() {
      Array.from(box.children).forEach(function (li, i) {
        li.classList.toggle("is-active", i === active);
      });
    }

    function choose(i) {
      input.value = items[i];
      hide();
      if (input.dataset.submit !== "off") input.form.submit();
    }

    function fetchSuggestions(value) {
      const url = new URL(input.dataset.suggest, window.location.origin);
      if (input.dataset.query) {
        input.dataset.query.split("&").forEach(function (pair) {
          const [k, v] = pair.split("=");
          url.searchParams.set(k, v);
        });
      }
      url.searchParams.set("q", value);
      return fetch(url).then(function (resp) { return resp.json(); });
    }

    input.addEventListener("input", function () {
      clearTimeout(timer);
      const value = input.value.trim();
      if (!value) return render([]);
      timer = setTimeout(function () {
        fetchSuggestions(value).then(render).catch(function () { render([]); });
      }, 120);
    });

    input.addEventListener("keydown", function (e) {
      if (box.hidden || !items.length) return;
      if (e.key === "ArrowDown") { active = (active + 1) % items.length; mark(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { active = (active - 1 + items.length) % items.length; mark(); e.preventDefault(); }
      else if (e.key === "Enter" && active >= 0) { e.preventDefault(); choose(active); }
      else if (e.key === "Escape") { hide(); }
    });

    input.addEventListener("blur", function () { setTimeout(hide, 150); });
  });
})();

// Recipe text size (A− / A+), remembered on this device.
(function () {
  const KEY = "rk-text-scale";
  const MIN = 0.85, MAX = 1.6, STEP = 0.1;
  let scale = parseFloat(localStorage.getItem(KEY)) || 1;
  const apply = () => document.documentElement.style.setProperty("--reader-scale", scale.toFixed(2));
  apply();
  document.querySelectorAll("[data-size]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const next = scale + parseFloat(btn.dataset.size) * STEP;
      scale = Math.min(MAX, Math.max(MIN, Math.round(next * 100) / 100));
      localStorage.setItem(KEY, String(scale));
      apply();
    });
  });
})();

// Steps you've finished stay ticked on this device, so you can follow along while cooking.
(function () {
  document.querySelectorAll(".step-done").forEach(function (box) {
    const key = "rk-step-" + box.dataset.key;
    box.checked = localStorage.getItem(key) === "1";
    box.addEventListener("change", function () {
      localStorage.setItem(key, box.checked ? "1" : "0");
    });
  });
})();

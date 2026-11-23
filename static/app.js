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

// Category boxes: each category becomes its own removable chip. Press Enter or comma to attach.
(function () {
  document.querySelectorAll("[data-tokens]").forEach(function (wrap) {
    const hidden = wrap.querySelector("input[type=hidden]");
    const input = wrap.querySelector("[data-token-input]");
    const list = wrap.querySelector(".token-list");
    const box = wrap.querySelector(".suggest");
    const form = wrap.closest("form");
    let values = (hidden.value || "").split(",").map(function (s) { return s.trim(); }).filter(Boolean);
    let items = [];
    let active = -1;
    let timer = null;

    function sync() { hidden.value = values.join(","); }
    function has(name) { return values.some(function (v) { return v.toLowerCase() === name.toLowerCase(); }); }
    function hide() { box.hidden = true; active = -1; }

    function chipFor(name) {
      return Array.from(list.querySelectorAll(".token")).find(function (chip) {
        return chip.dataset.name.toLowerCase() === name.toLowerCase();
      });
    }

    function addChip(name, animate) {
      const chip = document.createElement("span");
      chip.className = "token" + (animate ? " just-added" : "");
      chip.dataset.name = name;
      const label = document.createElement("span");
      label.textContent = name;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.setAttribute("aria-label", "Remove " + name);
      remove.textContent = "×";
      remove.addEventListener("click", function () {
        values = values.filter(function (v) { return v !== name; });
        chip.remove();
        sync();
        input.focus();
      });
      chip.append(label, remove);
      list.appendChild(chip);
    }

    function attach(raw) {
      const name = raw.replace(/,/g, " ").replace(/\s+/g, " ").trim().slice(0, 40);
      if (!name) return false;
      if (has(name)) {
        // Already attached: replay the highlight so you can see it.
        const existing = chipFor(name);
        if (existing) {
          existing.classList.remove("just-added");
          void existing.offsetWidth;
          existing.classList.add("just-added");
        }
        return false;
      }
      values.push(name);
      addChip(name, true);
      sync();
      return true;
    }

    function choose(i) {
      attach(items[i].value);
      input.value = "";
      hide();
      input.focus();
    }

    function render(list2) {
      const typed = input.value.trim();
      const lower = function (s) { return s.toLowerCase(); };
      const matches = [];
      list2.forEach(function (s) {
        if (!has(s) && !matches.some(function (m) { return lower(m) === lower(s); })) matches.push(s);
      });
      const options = matches.map(function (s) { return { label: s, value: s }; });
      if (typed && !has(typed) && !matches.some(function (m) { return lower(m) === lower(typed); })) {
        options.push({ label: "Add “" + typed + "”", value: typed, add: true });
      }
      box.innerHTML = "";
      items = options.slice(0, 8);
      // The best match is highlighted, so Tab or Enter fills it in as you type.
      active = items.length && !items[0].add ? 0 : -1;
      if (!items.length) return hide();
      items.forEach(function (item, i) {
        const li = document.createElement("li");
        li.textContent = item.label;
        li.setAttribute("role", "option");
        li.classList.toggle("is-active", i === active);
        li.addEventListener("mousedown", function (e) { e.preventDefault(); choose(i); });
        box.appendChild(li);
      });
      box.hidden = false;
    }

    input.addEventListener("input", function () {
      clearTimeout(timer);
      const typed = input.value.trim();
      if (!typed) return render([]);
      timer = setTimeout(function () {
        const url = new URL(wrap.dataset.suggest, window.location.origin);
        url.searchParams.set("kind", "category");
        url.searchParams.set("q", typed);
        fetch(url).then(function (r) { return r.json(); }).then(render).catch(function () { render([]); });
      }, 120);
    });

    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === ",") {
        e.preventDefault();
        if (!box.hidden && active >= 0) return choose(active);
        if (attach(input.value)) input.value = "";
        else input.value = "";
        hide();
      } else if (e.key === "Backspace" && !input.value) {
        const last = list.lastElementChild;
        if (last) {
          values = values.filter(function (v) { return v !== last.dataset.name; });
          last.remove();
          sync();
        }
      } else if (!box.hidden && items.length && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        Array.from(box.children).forEach(function (li, i) { li.classList.toggle("is-active", i === active); });
        e.preventDefault();
      } else if (e.key === "Tab" && !box.hidden && items.length) {
        e.preventDefault();
        choose(active >= 0 ? active : 0);
      } else if (e.key === "Escape") {
        hide();
      }
    });

    input.addEventListener("blur", function () {
      setTimeout(function () {
        if (input.value.trim()) attach(input.value);
        input.value = "";
        hide();
      }, 150);
    });

    if (form) {
      form.addEventListener("submit", function () {
        if (input.value.trim()) attach(input.value);
        input.value = "";
        sync();
      });
    }

    values.forEach(function (name) { addChip(name, false); });
    sync();
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

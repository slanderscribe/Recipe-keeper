// Sliding highlight for every tab bar (top menu and category tabs).
// It follows the pointer and keyboard focus, then settles on the current tab.
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

// Search suggestions: as you type, offer matching categories, tags, recipe names and authors.
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
      input.form.submit();
    }

    input.addEventListener("input", function () {
      clearTimeout(timer);
      const value = input.value.trim();
      if (!value) return render([]);
      timer = setTimeout(async function () {
        try {
          const resp = await fetch(input.dataset.suggest + "?q=" + encodeURIComponent(value));
          render(await resp.json());
        } catch (err) {
          render([]);
        }
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

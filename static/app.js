// Sliding highlight for the top tabs. It follows the pointer and keyboard focus,
// then settles on the current page.
(function () {
  const nav = document.getElementById("tabs");
  if (!nav) return;

  const indicator = nav.querySelector(".tab-indicator");
  const tabs = Array.from(nav.querySelectorAll(".tab"));
  const current = () => nav.querySelector(".tab.is-active") || tabs[0];

  function place(tab) {
    if (!tab || !indicator) return;
    indicator.style.width = tab.offsetWidth + "px";
    indicator.style.transform = "translateX(" + tab.offsetLeft + "px)";
    indicator.style.opacity = "1";
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("mouseenter", function () { place(tab); });
    tab.addEventListener("focus", function () { place(tab); });
    tab.addEventListener("mouseleave", function () { place(current()); });
    tab.addEventListener("blur", function () { place(current()); });
  });

  nav.addEventListener("mouseleave", function () { place(current()); });
  window.addEventListener("resize", function () { place(current()); });
  place(current());
})();

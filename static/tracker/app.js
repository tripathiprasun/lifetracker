/* Small progressive enhancements. The app works without any of this. */
(function () {
  "use strict";

  // Let textareas grow with what's typed.
  document.querySelectorAll("textarea").forEach(function (box) {
    function fit() {
      box.style.height = "auto";
      box.style.height = box.scrollHeight + 2 + "px";
    }
    box.addEventListener("input", fit);
    fit();
  });

  // Show the day number for whichever date is chosen on the entry form.
  var dateInput = document.querySelector("[data-start-date]");
  var label = document.querySelector("[data-day-label]");
  if (dateInput && label) {
    var toUtc = function (iso) {
      var p = iso.split("-");
      return Date.UTC(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
    };
    var update = function () {
      if (!dateInput.value) { label.textContent = ""; return; }
      var n = Math.round((toUtc(dateInput.value) - toUtc(dateInput.dataset.startDate)) / 86400000) + 1;
      label.textContent = n >= 1 ? "Day " + n : "Before Day 1";
    };
    dateInput.addEventListener("input", update);
    dateInput.addEventListener("change", update);
    update();
  }

  // Units only apply to number parameters.
  var typeSelect = document.querySelector("[data-metric-type]");
  var unitField = document.querySelector("[data-unit-field]");
  if (typeSelect && unitField) {
    var toggleUnit = function () { unitField.hidden = typeSelect.value !== "number"; };
    typeSelect.addEventListener("change", toggleUnit);
    toggleUnit();
  }
})();

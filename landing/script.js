// Lyrebird landing page — small, dependency-free interactions.
// Two jobs: scroll-reveal sections, and the bilingual "typing" demo in the hero.

(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- Scroll reveal ---------- */

  var revealTargets = document.querySelectorAll(".fade-up");

  if (reduceMotion || !("IntersectionObserver" in window)) {
    revealTargets.forEach(function (el) { el.classList.add("visible"); });
  } else {
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.15, rootMargin: "0px 0px -40px 0px" }
    );
    revealTargets.forEach(function (el) { observer.observe(el); });
  }

  /* ---------- Bilingual typing demo ----------
     Demonstrates the auto-detect feature: a line in English, then a line
     in Spanish, typed and erased in a loop. */

  var transcriptEl = document.getElementById("transcript-text");

  var phrases = [
    "Just talk. Lyrebird writes.",
    "Hablá normal, Lyrebird transcribe.",
  ];

  if (transcriptEl) {
    if (reduceMotion) {
      transcriptEl.textContent = phrases[0];
    } else {
      typeLoop(transcriptEl, phrases);
    }
  }

  function typeLoop(el, lines) {
    var lineIndex = 0;
    var charIndex = 0;
    var typingSpeed = 55;
    var erasingSpeed = 28;
    var holdMs = 1400;

    function step() {
      var current = lines[lineIndex];

      if (charIndex <= current.length) {
        el.textContent = current.slice(0, charIndex);
        charIndex++;
        setTimeout(step, typingSpeed);
        return;
      }

      // Finished typing this line — hold, then erase.
      setTimeout(erase, holdMs);
    }

    function erase() {
      var current = lines[lineIndex];

      if (charIndex > 0) {
        charIndex--;
        el.textContent = current.slice(0, charIndex);
        setTimeout(erase, erasingSpeed);
        return;
      }

      lineIndex = (lineIndex + 1) % lines.length;
      setTimeout(step, 300);
    }

    step();
  }

  /* ---------- Nav: subtle solidify on scroll ---------- */

  var navbar = document.getElementById("navbar");
  if (navbar) {
    var lastState = false;
    window.addEventListener(
      "scroll",
      function () {
        var scrolled = window.scrollY > 12;
        if (scrolled !== lastState) {
          navbar.style.opacity = scrolled ? "1" : "0.96";
          lastState = scrolled;
        }
      },
      { passive: true }
    );
  }
})();

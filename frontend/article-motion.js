// Article motion: on-demand demos and highlight replays for the four career guides.
// Loaded with "defer" by article.html. Each initializer runs only on its own guide, so the other articles are untouched.
// Reduced motion: the static content stays readable and the replay and play controls stay hidden.
(() => {
  const slug = new URLSearchParams(window.location.search).get("slug");

  // ATS Basics: the vague-to-specific highlights and the resume-parsing demo.
  if (slug === "what-is-ats") {
    (() => {
      const demo = document.querySelector(".ct-ats-demo");
      const controls = demo.querySelector(".ct-demo-controls");
      const play = demo.querySelector(".ct-demo-play");
      const buttons = Array.from(controls.querySelectorAll("[data-scene]"));
      const scenes = Array.from(demo.querySelectorAll(".ct-demo-scene"));
      const kicker = demo.querySelector(".ct-demo-kicker");
      const title = demo.querySelector(".ct-demo-copy h3");
      const description = demo.querySelector(".ct-demo-description");
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
      const frames = [
        ["Apply", "A resume arrives", "You submit a resume and application answers. The employer’s system receives them.", 2400],
        ["Read details", "The ATS reads the resume", "Some systems pull details such as job titles and skills into separate fields.", 3000],
        ["Organize records", "Details become searchable", "The ATS organizes the details into a record recruiters can search, filter, or review.", 2800],
        ["Employer decision", "The employer takes it from here", "The employer decides how to screen applications and whom to move forward.", 3000]
      ];
      let index = 0;
      let timer = null;
      let deadline = 0;
      let remaining = 0;
      let status = "idle";

      function showFrame(next, motion) {
        index = next;
        const [label, heading, detail] = frames[index];
        demo.removeAttribute("data-motion");
        demo.removeAttribute("data-paused");
        kicker.textContent = (index + 1) + " of " + frames.length + " · " + label;
        title.textContent = heading;
        description.textContent = detail;
        scenes.forEach((scene, number) => { scene.hidden = number !== index; });
        buttons.forEach((button, number) => {
          if (number === index) button.setAttribute("aria-current", "step");
          else button.removeAttribute("aria-current");
        });
        if (motion) {
          void demo.offsetWidth;
          demo.setAttribute("data-motion", "");
        }
      }

      function setStatus(next) {
        status = next;
        const [icon, label] = {
          idle: ["▶", "Play animation"],
          playing: ["Ⅱ", "Pause animation"],
          paused: ["▶", "Resume animation"],
          ended: ["↻", "Replay animation"]
        }[status];
        play.querySelector("span").textContent = icon;
        play.lastChild.textContent = " " + label;
      }

      function cancelTimer() {
        window.clearTimeout(timer);
        timer = null;
      }

      function schedule(duration) {
        deadline = performance.now() + duration;
        timer = window.setTimeout(() => {
          timer = null;
          if (index === frames.length - 1) {
            setStatus("ended");
            return;
          }
          showFrame(index + 1, true);
          schedule(frames[index][3]);
        }, duration);
      }

      function updateMotionPreference() {
        play.hidden = reduce.matches;
        if (!reduce.matches) return;
        cancelTimer();
        demo.removeAttribute("data-motion");
        demo.removeAttribute("data-paused");
        setStatus("idle");
      }

      play.addEventListener("click", () => {
        if (reduce.matches) return;
        if (status === "playing") {
          remaining = Math.max(0, deadline - performance.now());
          cancelTimer();
          demo.setAttribute("data-paused", "");
          setStatus("paused");
          return;
        }
        if (status === "paused") {
          demo.removeAttribute("data-paused");
          setStatus("playing");
          schedule(remaining);
          return;
        }
        showFrame(status === "ended" ? 0 : index, true);
        setStatus("playing");
        schedule(frames[index][3]);
      });

      buttons.forEach(button => button.addEventListener("click", () => {
        cancelTimer();
        showFrame(Number(button.dataset.scene), false);
        setStatus("idle");
      }));
      reduce.addEventListener("change", updateMotionPreference);
      setStatus("idle");
      updateMotionPreference();
      controls.hidden = false;
    })();
  }

  // Shared replay pattern for the three other guides: the step lift and the highlight replay.
  const sections = [
    ["linkedin-article-main", "honest-self-marketing", "ct-linkedin"],
    ["interview-article-main", "how-we-grade", "ct-interview"]
  ];
  for (const [, guideSlug, prefix] of sections) {
    if (slug !== guideSlug) continue;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    for (const section of document.querySelectorAll("." + prefix + "-motion")) {
      const replay = section.querySelector("." + prefix + "-replay");
      const updateControl = () => {
        replay.hidden = reduceMotion.matches;
        if (reduceMotion.matches) section.removeAttribute("data-playing");
      };
      replay.addEventListener("click", () => {
        if (reduceMotion.matches) return;
        section.removeAttribute("data-playing");
        void section.offsetWidth;
        section.setAttribute("data-playing", "");
      });
      reduceMotion.addEventListener("change", updateControl);
      updateControl();
    }
  }
})();

import { showToast } from "./dom.js";

/* ====================================================================
   Footer: team photos and contact
   ==================================================================== */
/** A tile shows its photo if the file exists, otherwise the initials already in the markup. */
export function initPeople() {
  document.querySelectorAll(".photo-slot[data-photo]").forEach((slot) => {
    const img = slot.querySelector("img");
    const fallback = slot.querySelector(".photo-fallback");
    const probe = new Image();
    probe.onload = () => {
      img.src = probe.src;
      img.hidden = false;
      if (fallback) fallback.hidden = true;
      slot.classList.add("has-photo");
    };
    probe.src = slot.dataset.photo; // a missing file just leaves the initials in place
  });
}

export async function copyEmail(event) {
  const button = event.currentTarget;
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
    showToast("Email address copied");
    button.textContent = "Copied";
    setTimeout(() => { button.textContent = "Copy"; }, 1800);
  } catch {
    showToast("Could not copy automatically. The address is shown next to the button.", "error");
  }
}

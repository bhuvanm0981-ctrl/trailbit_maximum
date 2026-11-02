import { $, STAR_PATH, SVG_NS, TOAST_MS } from "./state.js";

export let toastTimer = null;

/* ====================================================================
   DOM helpers (text always goes through textContent / text nodes)
   ==================================================================== */
export function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "checked" || key === "disabled") node[key] = Boolean(value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** Turn `inline code` in a plain string into <code> elements without using innerHTML. */
export function richText(text) {
  return String(text)
    .split(/(`[^`]+`)/g)
    .filter(Boolean)
    .map((part) =>
      part.startsWith("`") && part.endsWith("`") && part.length > 2 ? h("code", { text: part.slice(1, -1) }) : part
    );
}

export function safeHref(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" ? parsed.href : "#";
  } catch {
    return "#";
  }
}

/** Link that opens in a new tab, with that said out loud to screen-reader users. */
export function externalLink(className, url, label) {
  return h(
    "a",
    { class: className, href: safeHref(url), target: "_blank", rel: "noopener noreferrer" },
    label,
    h("span", { class: "sr-only", text: " (opens in a new tab)" })
  );
}

export const slug = (value) => String(value).toLowerCase().replace(/[^a-z0-9]+/g, "-");

export function eachForIssue(selector, issueId, fn) {
  document.querySelectorAll(selector).forEach((node) => {
    if (node.dataset.issue === issueId) fn(node);
  });
}

export function starIcon(filled = false) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", `bookmark-icon${filled ? " is-filled" : ""}`);
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", STAR_PATH);
  path.setAttribute("stroke-linejoin", "round");
  svg.appendChild(path);
  return svg;
}
/* ====================================================================
   Toast
   ==================================================================== */
export function showToast(message, kind = "info") {
  const toast = $("toast");
  toast.textContent = message;
  toast.className = `toast show${kind === "error" ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), TOAST_MS);
}
